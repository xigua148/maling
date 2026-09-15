"""gui/tavern/engine.py —— 酒馆功能域 · 受控变换状态机（V22-02，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.2  7 变换 ``pre``/``post``、``vars`` 白名单、三条不变量 I1/I2/I3、6 条硬禁区
    - §4.3  engine 接口签名（``ApplyResult`` / ``validate`` / ``apply_transform`` /
            ``check_invariants`` / ``is_forbidden``）
    - §5    高自由度机制的「一致性约束」环节（白名单 + 前置条件 + 不变量 + 硬禁区 + 留痕）
    - §5.4  #8 ``vars`` 键名受白名单约束 / #9 三条不变量 / #10 硬禁区最高优先级 /
            #11 ``transcript`` append-only / #12 显式 seed
    - §9/§10 风险与测试要点（7 变换 ×（pre 满足/不满足）、6 硬禁区、seed 可复现）

硬约束（逐条对齐任务书）：
    * 仅依赖标准库；**零 Qt**（``import gui.tavern.engine`` 在无 PySide6 环境必须成功）。
    * **不重复实现单条不变量判定** —— 复用 :mod:`gui.tavern.model` 的
      ``check_i1`` / ``check_i2`` / ``check_i3``（§4.3 归属：单条判定在 model，
      **聚合**在 engine）。本模块只做**聚合**（:func:`check_invariants`）与
      **施加 / 回滚**。
    * 显式 seed 的确定性随机：只用 ``random.Random(seed + turn)``，
      **不依赖全局 ``random``**（D-V22-07 / §5.4#12）。
    * 异常走 :mod:`gui.tavern.errors` 已冻结层级；日志 ``logger.debug(..., exc_info=True)``，
      **不写裸 ``except: pass``**。

模块对外契约（供批 2 的 ``intent_router`` 对接）见 :data:`__all__`。

``content``（已解析内容包）契约（**本模块读取的键，全部可缺省、缺省即安全**）::

    {
      "node_ids": ["opening", ...],           # I2 引用有效：节点集（或等价的 "nodes"）
      "scene_ids": ["counter", ...],          # I2 引用有效：地点集（或等价的 "scenes"）
      "reachable": {"counter": ["bar"], ...},  # move_to 的 reachable(scene)
      "known_topics": {"counter": ["photo"]},  # ask_about 的 known_topics(scene)
      "menu": {"counter": ["long_night"]},     # order 的 menu(scene)
      "open_conditions": {"counter:drawer": true},  # open 的 precondition(scene, key)
      "var_names": ["custom_note"],            # 内容包额外声明的合法 var 名（白名单扩充）
    }
"""
from __future__ import annotations

import copy
import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .errors import TavernForbiddenError, TavernInvariantError, TavernValidationError
from .model import (
    DEFAULT_VAR_NAMES,
    FORBIDDEN_RULES,
    FORBIDDEN_STRUCTURE_FIELDS,
    MAX_VARS,
    REASON_CODES,
    REASON_PREFIXES,
    RESOLUTION_REQUIRED_KEYS,
    TRANSFORM_WHITELIST,
    check_i1,
    check_i2,
    check_i3,
)

_LOGGER = logging.getLogger("maling.tavern.engine")

__all__ = [
    # —— 结果与主入口 ——
    "ApplyResult",
    "validate",
    "apply_transform",
    "check_invariants",
    "is_forbidden",
    # —— 确定性随机（显式 seed）——
    "derive_rng",
    "deterministic_choice",
    # —— 内容包查询小工具（供 router / UI 复用）——
    "reachable_scenes",
    "known_topics",
    "menu_items",
    "open_condition_met",
    "declared_var_names",
    "is_known_var",
    # —— 留痕辅助 ——
    "build_resolution",
    "is_known_reason",
    # —— 常量 ——
    "RA_NUMBER_FIELDS",
    "KILL_REVIVE_FIELDS",
    "ALLOWED_EFFECT_FIELDS",
    "ARG_KEYS",
]


# ===========================================================================
# 常量：硬禁区字段集合 / 效果面字段 / 各变换 args 键
# ===========================================================================

#: 硬禁区第 5 条的 R-A 禁项数值字段名（好感/心情/经验/货币/筹码/胜率/连胜/进度/断签/倒计时）。
#: 命中即 ``forbidden:emit_ra_number``（**隐藏不展示也不做**，§4.2 第 5 条）。
RA_NUMBER_FIELDS: Tuple[str, ...] = (
    "favor",
    "favour",
    "affection",
    "affinity",
    "intimacy_value",
    "mood",
    "exp",
    "experience",
    "level",
    "score",
    "currency",
    "money",
    "coin",
    "coins",
    "chips",
    "win_rate",
    "winrate",
    "streak",
    "combo",
    "progress",
    "progress_bar",
    "checkin",
    "check_in",
    "countdown",
)

#: 硬禁区第 3 条的「杀死/复活关键角色、改人物身份」字段名。
#: 命中即 ``forbidden:kill_revive_character``（§4.2 第 3 条）。
KILL_REVIVE_FIELDS: Tuple[str, ...] = (
    "alive",
    "is_alive",
    "dead",
    "died",
    "kill",
    "revive",
    "revived",
    "resurrect",
    "character_alive",
    "cast_alive",
    "persona",
    "identity",
)

#: 硬禁区第 4 条的**结构字段**（结构字段不参与玩法，直接复用 model 冻结常量）。
_STRUCTURE_FIELDS: Tuple[str, ...] = tuple(FORBIDDEN_STRUCTURE_FIELDS)  # meta/schema_version/settings

#: 硬禁区第 1 条的「改写历史」触发名（``transcript`` 只可 append，不可 edit）。
_REWRITE_FIELDS: Tuple[str, ...] = ("history", "rewrite_history", "rewrite")

#: 硬禁区第 2 条的「跨章」触发名（``chapter_id`` 只能由章节结束条件推进）。
_CROSS_CHAPTER_FIELDS: Tuple[str, ...] = ("chapter_id", "chapter")

#: state 顶层**允许被效果通道写入**的字段（非 vars、非结构、非历史）。
#:   * ``scene_id`` / ``node_id``：地点 / 节点推进（I2 会校验引用有效）
#:   * ``turn``：拍数推进
#:   * ``transcript``：**只增不改**（append 允许；set 缩短 → I3；edit → REWRITE_HISTORY）
ALLOWED_EFFECT_FIELDS: Tuple[str, ...] = ("scene_id", "node_id", "turn", "transcript")

#: 各变换可接受的 ``args`` 键（**结构声明的键之外一律 ``bad_args:unexpected_args``**）。
#: ``effects`` 为所有变换共用的受控额外写入通道（供内容包驱动自定义 var / 节点推进）。
ARG_KEYS: Dict[str, Tuple[str, ...]] = {
    "move_to": ("target", "effects"),
    "take": ("item", "effects"),
    "give": ("item", "effects"),
    "open": ("key", "target", "effects"),
    "ask_about": ("topic", "effects"),
    "wait": ("effects",),
    "order": ("item", "effects"),
}


# ===========================================================================
# 结果类型（§4.3 冻结签名）
# ===========================================================================

@dataclass(frozen=True)
class ApplyResult:
    """单次「校验 / 施加」的结果（不可变）。

    Attributes:
        ok: 是否**成功施加**（``validate`` 仅做前置校验，通过时 ``ok=True`` 且 ``state`` 原样回传）。
        state: 施加成功时为**新 state**（不改入参）；失败时**恒为入参 state**（回滚语义）。
        reason: 可读机读短码（见 :data:`gui.tavern.model.REASON_CODES` /
            :data:`REASON_PREFIXES`）；成功为 ``"ok"``。
        transform: 变换 id（原样回传，便于留痕）。
    """

    ok: bool
    state: dict
    reason: str
    transform: str


# ===========================================================================
# 小工具：类型守卫 / 内容包查询
# ===========================================================================

def _as_int(value: Any, default: int) -> int:
    """``int`` 守卫：``bool`` 不算 int；非法回默认。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list/tuple 或含非 str 时丢弃非法项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if isinstance(x, str)]


def _vars_of(state: Any) -> dict:
    """安全取 ``state['vars']``（非 dict 时返回空 dict；**不创建**）。"""
    if isinstance(state, dict):
        v = state.get("vars")
        if isinstance(v, dict):
            return v
    return {}


def _remove_one(seq: List[str], value: Any) -> bool:
    """从 ``seq`` 移除**首个**等于 ``value`` 的元素；返回是否移除。"""
    try:
        seq.remove(value)
        return True
    except ValueError:
        return False


def _scene_map(content: Any, key: str) -> dict:
    """取 ``content[key]`` 的 dict 形态（非 dict 返回空 dict）。"""
    if isinstance(content, dict):
        m = content.get(key)
        if isinstance(m, dict):
            return m
    return {}


def reachable_scenes(scene_id: Any, content: Any) -> List[str]:
    """``reachable(scene)`` —— 当前地点可达的地点列表（缺声明返回空列表）。"""
    if not isinstance(scene_id, str):
        return []
    return _as_str_list(_scene_map(content, "reachable").get(scene_id, []))


def known_topics(scene_id: Any, content: Any) -> List[str]:
    """``known_topics(scene)`` —— 当前地点可问的话题列表（缺声明返回空列表）。"""
    if not isinstance(scene_id, str):
        return []
    return _as_str_list(_scene_map(content, "known_topics").get(scene_id, []))


def menu_items(scene_id: Any, content: Any) -> List[str]:
    """``menu(scene)`` —— 当前地点的可点单列表（缺声明返回空列表）。"""
    if not isinstance(scene_id, str):
        return []
    return _as_str_list(_scene_map(content, "menu").get(scene_id, []))


def open_condition_met(scene_id: Any, key: Any, content: Any) -> bool:
    """``precondition(scene, key)`` —— 开门条件是否成立。

    依次尝试 ``"<scene>:<key>"`` → ``"<key>"`` 两种键；亦支持 ``content["openable"]``
    列表式声明（key 在列表内即成立）。缺声明 → ``False``（安全默认：不满足）。
    """
    if not isinstance(key, str) or not key:
        return False
    scene = scene_id if isinstance(scene_id, str) else ""
    if isinstance(content, dict):
        conds = content.get("open_conditions")
        if isinstance(conds, dict):
            scoped = f"{scene}:{key}"
            if scoped in conds:
                return bool(conds[scoped])
            if key in conds:
                return bool(conds[key])
        openable = content.get("openable")
        if isinstance(openable, (list, tuple)) and key in openable:
            return True
    return False


def declared_var_names(content: Any) -> Tuple[str, ...]:
    """内容包额外声明的合法 ``vars`` 名（在白名单基底 :data:`DEFAULT_VAR_NAMES` 之外）。

    读取 ``content["var_names"]``（内容包 ``transforms.json`` 的声明落点，§4.2）。
    保持出现顺序并去重。
    """
    names: List[str] = []
    if isinstance(content, dict):
        for name in _as_str_list(content.get("var_names")):
            if name not in names:
                names.append(name)
    return tuple(names)


def is_known_var(name: Any, content: Any = None) -> bool:
    """``name`` 是否为**白名单内**的 ``vars`` 名（基底 ∪ 内容包声明）。

    硬禁区第 6 条用途：白名单外的 ``var`` 名 → ``forbidden:unknown_var``。
    """
    if not isinstance(name, str) or not name:
        return False
    if name in DEFAULT_VAR_NAMES:
        return True
    return name in declared_var_names(content)


# ===========================================================================
# 确定性随机（显式 seed，§5.4#12 / D-V22-07）
# ===========================================================================

def derive_rng(seed: int, turn: int) -> random.Random:
    """确定性随机源：``random.Random(int(seed) + int(turn))``。

    **绝不使用全局 ``random``** —— 同 ``seed`` + 同 ``turn`` ⇒ 同序列（可复现）。
    """
    return random.Random(_as_int(seed, 0) + _as_int(turn, 0))


def deterministic_choice(items: Any, seed: int, turn: int) -> Optional[str]:
    """从 ``items`` 里**确定性**地取一项（``None`` 表示无可选项）。

    选择规则：``derive_rng(seed, turn).randrange(len(items))``。非列表入参 → ``None``。
    """
    seq = _as_str_list(items)
    if not seq:
        return None
    return seq[derive_rng(seed, turn).randrange(len(seq))]


def _resolve_seed(seed: Optional[int], src: dict) -> int:
    """取本次施加的随机源 seed：显式 ``seed`` 优先，否则用 ``state["seed"]``。"""
    if seed is not None:
        return _as_int(seed, 0)
    return _as_int(src.get("seed"), 0)


# ===========================================================================
# 硬禁区判定（6 条；校验器最高优先级，§4.2）
# ===========================================================================

def _scan_name_hits(name: Any, hits: set) -> None:
    """将单个字段名归入硬禁区命中集合（非 var 语义的五条硬禁区）。"""
    if not isinstance(name, str) or not name:
        return
    if name in _STRUCTURE_FIELDS:
        hits.add("touch_structure")
    elif name in RA_NUMBER_FIELDS:
        hits.add("emit_ra_number")
    elif name in KILL_REVIVE_FIELDS:
        hits.add("kill_revive_character")
    elif name in _CROSS_CHAPTER_FIELDS:
        hits.add("cross_chapter")
    elif name in _REWRITE_FIELDS:
        hits.add("rewrite_history")


def _is_effect_field_known(field: Any, content: Any) -> bool:
    """效果字段是否为**合法写入面**（state 白名单字段 or 白名单 var 名）。"""
    if isinstance(field, str) and field in ALLOWED_EFFECT_FIELDS:
        return True
    return is_known_var(field, content)


def is_forbidden(state: dict, transform: str, args: Any, content: Any = None) -> Optional[str]:
    """6 条硬禁区判定（§4.2）；命中返回**规则 id**，否则 ``None``。

    判定面：
      * ``args`` 顶层键名（如 ``{"affection": 1}`` → ``emit_ra_number``）；
      * ``args["effects"]`` 每条 ``field``（如 ``{"field": "meta"}`` → ``touch_structure``）；
      * ``transcript`` + ``op="edit"`` → ``rewrite_history``（in-place 改历史）；
      * 效果字段既非 state 白名单字段、又非白名单 var 名 → ``unknown_var``。

    （``args["write_vars"]`` **不在此判定面**：该键不在 ``ARG_KEYS`` 里，会被 args 校验
    直接拒掉；写 var 的唯一通道是 ``effects``。）

    Args:
        state: 局状态（保留参数；当前判定不依赖，便于未来扩展）。
        transform: 变换 id（保留参数）。
        args: 变换入参。
        content: 已解析内容包（用于识别内容包**声明**的合法 var 名；缺省仅认基底白名单）。

    Returns:
        命中的规则 id（∈ :data:`FORBIDDEN_RULES`，按该常量顺序取**首个**命中），或 ``None``。
    """
    _ = (state, transform)  # 显式声明当前未使用，避免 lint 噪音
    if not isinstance(args, dict):
        return None

    hits: set = set()

    # 顶层键名
    for key in args.keys():
        _scan_name_hits(key, hits)

    # 效果通道
    effects = args.get("effects")
    if isinstance(effects, list):
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            field = effect.get("field")
            op = effect.get("op", "set")
            _scan_name_hits(field, hits)
            if field == "transcript" and op == "edit":
                hits.add("rewrite_history")
            if not _is_effect_field_known(field, content):
                hits.add("unknown_var")

    # 注：**不存在** ``args["write_vars"]`` 扫描分支。写 var 的唯一通道是 ``effects``
    # （``{field:<var名>, op, value}``）；``ARG_KEYS`` 未收 ``write_vars``，任何携带它的入参
    # 都会被 ``_validate_args`` 以 ``bad_args:unexpected_args:write_vars`` 拒绝（fail-closed）。
    # 此前这里有一份对 ``write_vars`` 的"死扫描"，永远走不到、只留下"看起来支持 write_vars"
    # 的误导，已按 design-v22 §1180 清理。

    for rule in FORBIDDEN_RULES:  # 按冻结顺序取首个命中（确定性）
        if rule in hits:
            return rule
    return None


# ===========================================================================
# args / pre 校验（§4.2 校验器步骤 2–3）
# ===========================================================================

def _validate_args(transform: str, args: dict) -> Optional[str]:
    """args 结构校验；返回错误 detail（``None`` 表示通过）。"""
    allowed = ARG_KEYS.get(transform, ("effects",))
    for key in args.keys():
        if key not in allowed:
            return f"unexpected_args:{key}"

    if transform == "take" or transform == "give":
        item = args.get("item")
        if not isinstance(item, str) or not item:
            return "missing_item"
    elif transform == "ask_about":
        topic = args.get("topic")
        if not isinstance(topic, str) or not topic:
            return "missing_topic"
    elif transform == "open":
        key = args.get("key")
        target = args.get("target")
        if not (isinstance(key, str) and key) and not (isinstance(target, str) and target):
            return "missing_key"
    elif transform == "move_to":
        target = args.get("target")
        if target is not None and not isinstance(target, str):
            return "arg_type_invalid:target"
    elif transform == "order":
        item = args.get("item")
        if item is not None and not isinstance(item, str):
            return "arg_type_invalid:item"
    # wait: 无必填项（仅 effects）
    return None


def _check_pre(state: dict, transform: str, args: dict, content: Any) -> Optional[str]:
    """``pre`` 前置条件判定；返回错误 detail（``None`` 表示满足）。"""
    vars_ = _vars_of(state)
    scene = state.get("scene_id", "")

    if transform == "move_to":
        target = args.get("target")
        if target is None:
            if not reachable_scenes(scene, content):
                return "no_reachable_target"
            return None
        if target not in reachable_scenes(scene, content):
            return "target_not_reachable"
    elif transform == "take":
        if args.get("item") not in _as_str_list(vars_.get("scene_items")):
            return "item_not_in_scene"
    elif transform == "give":
        if args.get("item") not in _as_str_list(vars_.get("held_items")):
            return "item_not_held"
    elif transform == "open":
        key = args.get("key") or args.get("target")
        if not open_condition_met(scene, key, content):
            return "condition_not_met"
    elif transform == "ask_about":
        if args.get("topic") not in known_topics(scene, content):
            return "topic_not_known"
    elif transform == "order":
        menu = menu_items(scene, content)
        if not menu:
            return "menu_empty"
        item = args.get("item")
        if item is not None and item not in menu:
            return "item_not_on_menu"
    # wait: ——（无前置）
    return None


def validate(state: Any, transform: Any, args: Any, content: Any = None) -> ApplyResult:
    """本地校验器：**只做前置校验，不改状态**（§4.3）。

    依次检查（**硬禁区最高优先级**，见模块注释「与设计不符之处」）::

        1) transform ∈ TRANSFORM_WHITELIST              → 否则 ok=False "unknown_transform"
        2) 6 条硬禁区（is_forbidden）                    → 否则 "forbidden:<id>"
        3) args 结构合法（键名/类型 ∈ 声明）             → 否则 "bad_args:<detail>"
        4) pre 满足                                      → 否则 "precondition_failed:<detail>"

    通过时返回 ``ApplyResult(ok=True, state=state, reason="ok", transform=transform)``。

    Note:
        不变量 I1/I2/I3 的**施加后**校验在 :func:`apply_transform` 内做（需先施加到候选态）。
    """
    tid = transform if isinstance(transform, str) else ""
    if not isinstance(state, dict):
        return ApplyResult(False, {}, "bad_args:state_not_dict", tid)
    if tid not in TRANSFORM_WHITELIST:
        return ApplyResult(False, state, "unknown_transform", tid)

    # 硬禁区最高优先级（先于 args / pre）
    rule = is_forbidden(state, tid, args, content)
    if rule is not None:
        return ApplyResult(False, state, f"forbidden:{rule}", tid)

    args_dict = args if isinstance(args, dict) else {}
    detail = _validate_args(tid, args_dict)
    if detail is not None:
        return ApplyResult(False, state, f"bad_args:{detail}", tid)

    pre_detail = _check_pre(state, tid, args_dict, content)
    if pre_detail is not None:
        return ApplyResult(False, state, f"precondition_failed:{pre_detail}", tid)

    return ApplyResult(True, state, "ok", tid)


# ===========================================================================
# 不变量聚合（§4.3 归属：单条判定在 model，聚合在 engine）
# ===========================================================================

def check_invariants(state: Any, content: Any = None, *, prev_state: Any = None) -> List[str]:
    """三条不变量 I1/I2/I3 的**聚合**校验（§4.2 / §4.3）。

    复用 :func:`model.check_i1` / :func:`model.check_i2` / :func:`model.check_i3`
    （**不重复实现单条判定**），返回**违规码列表**（空列表 = 全部保持）。

    Args:
        state: 待校验状态（施加变换**之后**的候选态）。
        content: 已解析内容包（I2 引用有效所需；缺省时 I2 无法判定 → 放行）。
        prev_state: **施加前**的状态（或直接给 ``int`` 表示前 transcript 长度）。
            I3「只增不改」用它做长度比较；缺省时 I3 不做长度比较。

    Returns:
        违规码列表（元素形如 ``"I1:held_item_also_in_scene:x"`` /
        ``"I2:dangling_scene:y"`` / ``"I3:transcript_shrunk:1->0"``）。
    """
    violations: List[str] = []
    if not isinstance(state, dict):
        return violations

    r1 = check_i1(state)
    if r1:
        violations.append(r1)

    r2 = check_i2(state, content if isinstance(content, dict) else {})
    if r2:
        violations.append(r2)

    prev_len: Optional[int] = None
    if isinstance(prev_state, int):
        prev_len = prev_state
    elif isinstance(prev_state, dict):
        transcript = prev_state.get("transcript")
        if isinstance(transcript, list):
            prev_len = len(transcript)
    r3 = check_i3(state, prev_len)
    if r3:
        violations.append(r3)

    return violations


# ===========================================================================
# 施加（post）+ 效果通道
# ===========================================================================

def _apply_effect(state: dict, effect: dict, content: Any) -> Tuple[bool, str]:
    """施加单条效果（``{"field", "op", "value"}``）；返回 ``(ok, detail)``。

    ``op`` 语义：``append`` 追加到列表 / ``set`` 赋值 / ``remove`` 删首个匹配。
    ``field`` 分三类：``transcript``（只增不改）、``scene_id``/``node_id``/``turn``、
    其余视为 ``vars`` 白名单 var（``op=""`` 时按列表/标量自适应）。
    """
    field = effect.get("field")
    op = effect.get("op", "set")
    value = effect.get("value")
    if not isinstance(field, str) or not field:
        return False, "bad_effect:missing_field"

    if field == "transcript":
        transcript = state.get("transcript")
        if not isinstance(transcript, list):
            transcript = []
            state["transcript"] = transcript
        if op == "append":
            transcript.append(value)
        elif op == "set":
            # 允许整体赋值（缩短 → 由 I3 拦截并回滚；延长视为 append 语义）
            if isinstance(value, list):
                state["transcript"] = list(value)
            else:
                transcript.append(value)
        elif op == "remove":
            _remove_one(transcript, value)
        else:
            return False, f"bad_effect_op:{op}"
        return True, ""

    if field in ("scene_id", "node_id"):
        if op != "set":
            return False, f"bad_effect_op:{op}"
        state[field] = value
        return True, ""

    if field == "turn":
        cur = _as_int(state.get("turn"), 0)
        if op == "set":
            state["turn"] = _as_int(value, cur)
        elif op == "append":
            state["turn"] = cur + _as_int(value, 0)
        else:
            return False, f"bad_effect_op:{op}"
        return True, ""

    # 其余视为 vars 白名单 var
    vars_ = state.get("vars")
    if not isinstance(vars_, dict):
        vars_ = {}
        state["vars"] = vars_
    current = vars_.get(field)
    if op == "set":
        vars_[field] = value
    elif op == "append":
        bucket = current if isinstance(current, list) else ([current] if current not in (None, "") else [])
        bucket.append(value)
        vars_[field] = bucket
    elif op == "remove":
        bucket = current if isinstance(current, list) else []
        _remove_one(bucket, value)
        vars_[field] = bucket
    else:
        return False, f"bad_effect_op:{op}"
    return True, ""


def _apply_post(
    state: dict,
    transform: str,
    args: dict,
    content: Any,
    *,
    seed: Optional[int],
    src: dict,
) -> Tuple[bool, str]:
    """对 ``state``（候选副本）施加 ``transform`` 的 ``post`` 与 ``effects``。

    返回 ``(ok, detail)``；``detail`` 非空仅在失败时给出（供 ``bad_args:<detail>``）。
    """
    vars_ = state.get("vars")
    if not isinstance(vars_, dict):
        vars_ = {}
        state["vars"] = vars_

    rng_seed = _resolve_seed(seed, src)
    turn = _as_int(src.get("turn"), 0)
    scene = src.get("scene_id", "")

    if transform == "move_to":
        target = args.get("target")
        if target is None:
            target = deterministic_choice(reachable_scenes(scene, content), rng_seed, turn)
        if not isinstance(target, str) or not target:
            return False, "missing_target"
        state["scene_id"] = target

    elif transform == "take":
        item = args.get("item")
        if not isinstance(item, str) or not item:
            return False, "missing_item"
        scene_items = _as_str_list(vars_.get("scene_items"))
        _remove_one(scene_items, item)
        vars_["scene_items"] = scene_items
        held = _as_str_list(vars_.get("held_items"))
        held.append(item)
        vars_["held_items"] = held

    elif transform == "give":
        item = args.get("item")
        if not isinstance(item, str) or not item:
            return False, "missing_item"
        held = _as_str_list(vars_.get("held_items"))
        _remove_one(held, item)
        vars_["held_items"] = held
        given = _as_str_list(vars_.get("given"))
        given.append(item)
        vars_["given"] = given

    elif transform == "open":
        target = args.get("target") or args.get("key")
        if not isinstance(target, str) or not target:
            return False, "missing_key"
        opened = _as_str_list(vars_.get("opened"))
        opened.append(target)
        vars_["opened"] = opened

    elif transform == "ask_about":
        topic = args.get("topic")
        if not isinstance(topic, str) or not topic:
            return False, "missing_topic"
        known = _as_str_list(vars_.get("known"))
        known.append(topic)
        vars_["known"] = known

    elif transform == "wait":
        state["turn"] = _as_int(src.get("turn"), 0) + 1

    elif transform == "order":
        item = args.get("item")
        if item is None:
            item = deterministic_choice(menu_items(scene, content), rng_seed, turn)
        if not isinstance(item, str) or not item:
            return False, "menu_empty"
        poured = vars_.get("poured")
        if isinstance(poured, list):
            poured.append(item)
        else:
            vars_["poured"] = item

    # 受控额外写入通道（内容包驱动）
    effects = args.get("effects")
    if isinstance(effects, list):
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            ok, detail = _apply_effect(state, effect, content)
            if not ok:
                return False, detail

    # §4.2「防变量爆炸」：vars 命名值数量上限
    if len(state.get("vars", {})) > MAX_VARS:
        return False, "max_vars_exceeded"

    return True, ""


# ===========================================================================
# 主入口：施加（含回滚）
# ===========================================================================

def _do_apply(
    state: Any,
    transform: Any,
    args: Any,
    content: Any,
    *,
    seed: Optional[int],
) -> ApplyResult:
    """``apply_transform`` 的实现体（不抛，返回结果）。"""
    tid = transform if isinstance(transform, str) else ""
    if not isinstance(state, dict):
        return ApplyResult(False, {}, "bad_args:state_not_dict", tid)

    # 1) 前置校验（白名单 / 硬禁区 / args / pre）
    verdict = validate(state, tid, args, content)
    if not verdict.ok:
        return verdict

    args_dict = args if isinstance(args, dict) else {}

    # 2) 施加到**深拷贝候选**（不可变式：绝不改入参）
    try:
        candidate = copy.deepcopy(state)
    except Exception:  # pragma: no cover - 防御性：理论不可序列化对象
        _LOGGER.debug("engine: state 深拷贝失败，拒绝施加", exc_info=True)
        return ApplyResult(False, state, "bad_args:state_not_copyable", tid)

    ok, detail = _apply_post(candidate, tid, args_dict, content, seed=seed, src=state)
    if not ok:
        return ApplyResult(False, state, f"bad_args:{detail}", tid)

    # 3) 不变量聚合（施加以后）；违反 → 回滚（返回原 state，逐字节不变）
    violations = check_invariants(candidate, content, prev_state=state)
    if violations:
        _LOGGER.debug("engine: 变换 %s 违反不变量 %s，已回滚", tid, violations)
        return ApplyResult(False, state, f"invariant_violated:{violations[0]}", tid)

    return ApplyResult(True, candidate, "ok", tid)


def _raise_for_result(result: ApplyResult) -> None:
    """``strict`` 模式下，把失败结果映射为 :mod:`gui.tavern.errors` 冻结异常。"""
    reason = result.reason
    if reason.startswith("forbidden:"):
        raise TavernForbiddenError("这个动作碰到了酒馆不接受的边界", reason=reason)
    if reason.startswith("invariant_violated:"):
        raise TavernInvariantError("这次改动会让故事前后对不上，已放弃", reason=reason)
    raise TavernValidationError("这个动作现在做不了", reason=reason)


def apply_transform(
    state: Any,
    transform: Any,
    args: Any,
    content: Any = None,
    *,
    seed: Optional[int] = None,
    strict: bool = False,
) -> ApplyResult:
    """施加一条受控变换（§4.3 主入口）。

    流程：``validate`` → 深拷贝候选 → 施加 ``post`` + ``effects`` → 不变量聚合；
    **任一环节不通过即回滚**（返回结果里 ``state`` 恒等于入参 ``state``，逐字节不变）。

    Args:
        state: 局状态（**不被就地修改**）。
        transform: 变换 id（须 ∈ :data:`TRANSFORM_WHITELIST`）。
        args: 变换入参（``dict``；结构见 :data:`ARG_KEYS`）。
        content: 已解析内容包（见模块 docstring）。
        seed: 显式随机源 seed；``None`` 时取 ``state["seed"]``，随机键为 ``seed + turn``。
        strict: ``True`` 时失败即抛对应 :mod:`gui.tavern.errors` 异常（默认 ``False`` 只返回结果）。

    Returns:
        :class:`ApplyResult`；``ok=True`` 时 ``state`` 为 **新状态**，否则为**原状态（回滚）**。
    """
    result = _do_apply(state, transform, args, content, seed=seed)
    if strict and not result.ok:
        _raise_for_result(result)
    return result


# ===========================================================================
# 留痕辅助（供批 2 router 组装 transcript.resolution）
# ===========================================================================

def is_known_reason(reason: Any) -> bool:
    """``reason`` 是否落在冻结的 :data:`REASON_CODES` ∪ :data:`REASON_PREFIXES` 内。"""
    if not isinstance(reason, str) or not reason:
        return False
    if reason in REASON_CODES:
        return True
    return any(reason.startswith(prefix) for prefix in REASON_PREFIXES)


def build_resolution(result: ApplyResult, *, mode: str = "verbatim", llm_used: bool = False) -> dict:
    """把 :class:`ApplyResult` 组装为 ``resolution`` 留痕字段（§4.2 / §4.3）。

    返回的 dict **恰好含** :data:`RESOLUTION_REQUIRED_KEYS`
    （``mode/transform/ok/reason/llm_used``），可由 router 直接塞进 ``transcript`` 条目。

    Args:
        result: 施加结果。
        mode: 三级路由档位（``verbatim`` / ``propose`` / ``narrate``）。
        llm_used: 本拍是否真的调用过 LLM（``allow_propose=False`` 时必须 ``False``）。

    Returns:
        含全部必填键的 ``resolution`` dict。
    """
    resolution = {
        "mode": mode,
        "transform": result.transform,
        "ok": bool(result.ok),
        "reason": result.reason,
        "llm_used": bool(llm_used),
    }
    # 契约自检：必填键齐全（缺键属实现缺陷，直接暴露而非静默）
    assert set(resolution) == set(RESOLUTION_REQUIRED_KEYS), "resolution 必填键漂移"
    return resolution
