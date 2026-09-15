"""gui/tavern/model.py —— 酒馆功能域 · 契约冻结（V22-00，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.1  ``tavern.json`` schema v1 全字段（默认结构工厂）
    - §4.2  7 变换白名单与 ``pre``/``post``、三条不变量 I1/I2/I3、6 条硬禁区
    - §4.3  模块接口签名（``default_tavern`` / ``merge_defaults`` / ``migrate`` /
            ``new_play`` 等）
    - §4.3  ``__init__.py`` 常量：``SCHEMA_VERSION`` / ``TRANSFORM_WHITELIST`` /
            ``ROUTE_MODES`` / ``PROMPT_SEGMENTS`` / ``SETTING_DEFAULTS``

本模块**只冻结「形状」**：常量、类型、默认结构工厂，以及「读时迁移」的骨架
（默认结构为底 + ``setdefault`` + ``isinstance`` 类型守卫 + 未知字段不销毁）。
**不含任何状态机业务逻辑** —— 变换 ``pre``/``post`` 的实际执行、不变量聚合判定、
硬禁区裁决在**批 2 的 ``engine.py``** 实现；本批仅冻结其**签名与语义**。

硬约束：
    * 仅依赖标准库；**零 Qt**（``import gui.tavern.model`` 在无 PySide6 环境必须成功）。
    * 不改 ``GuiConfig``（设置全部落本模块声明的 ``tavern.json.settings``，D-V22-08）。
    * 显式可注入时间（``now``）以支持确定性单测，默认 ``datetime.now().isoformat()``。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, TypedDict

_LOGGER = logging.getLogger("maling.tavern.model")

__all__ = [
    # —— 版本与顶层结构 ——
    "SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "iso_now",
    "default_meta",
    "default_settings",
    "default_library",
    "default_journal",
    "default_summary",
    "default_llm_state",
    "default_vars",
    "default_tavern",
    "merge_defaults",
    "migrate",
    # —— 设置 ——
    "SETTING_DEFAULTS",
    "SETTING_KEYS",
    "NARRATOR_LENGTHS",
    # —— 变换白名单 ——
    "TransformSpec",
    "TRANSFORM_WHITELIST",
    "TRANSFORM_SPECS",
    "DEFAULT_VAR_NAMES",
    "MAX_VARS",
    # —— 不变量 ——
    "INVARIANTS",
    "INVARIANT_RULES",
    "check_i1",
    "check_i2",
    "check_i3",
    # —— 硬禁区 ——
    "ForbiddenRule",
    "FORBIDDEN_RULES",
    "FORBIDDEN_RULE_DESC",
    "FORBIDDEN_STRUCTURE_FIELDS",
    # —— 三级路由与留痕 ——
    "RouteMode",
    "ROUTE_MODES",
    "Resolution",
    "RESOLUTION_REQUIRED_KEYS",
    "TranscriptEntry",
    "TRANSCRIPT_ENTRY_KEYS",
    "INPUT_KINDS",
    "TRANSCRIPT_ROLES",
    "REASON_CODES",
    "REASON_PREFIXES",
    # —— prompt 五段式 ——
    "PROMPT_SEGMENTS",
    "PROMPT_SEGMENT_ROLES",
    # —— 世界书 ——
    "WorldbookEntry",
    "WORLDBOOK_ENTRY_FIELDS",
    "SELECTIVE_LOGIC_MODES",
    "LORE_POSITIONS",
    "CONSTANT_ENTRY_LIMIT",
    "LORE_MAX_CONTENT_CHARS",
    "default_worldbook_entry",
    # —— 局与人物 ——
    "PLAY_KEYS",
    "PLAY_STATUSES",
    "new_play",
    "default_play",
    "merge_play",
    "CastMember",
    "CAST_MEMBER_KEYS",
    "default_cast_member",
    "BookSlot",
    "BOOK_SLOT_KEYS",
    "default_book_slot",
]


# ===========================================================================
# 版本与顶层结构（§4.1）
# ===========================================================================

#: ``tavern.json`` 顶层 schema 版本（迁移依据）。
SCHEMA_VERSION: int = 1

#: 顶层键全集（**逐键对齐 §4.1**；多一个少一个都算契约漂移）。
TOP_LEVEL_KEYS: Tuple[str, ...] = (
    "schema_version",
    "meta",
    "settings",
    "library",
    "plays",
    "active_play_id",
    "journal",
)

#: 落盘目录位于既有业务数据树之下（D-V22-07），**不碰 %APPDATA%**。
TAVERN_DIR_NAME: str = "tavern"
TAVERN_FILE_NAME: str = "tavern.json"


def iso_now() -> str:
    """当前本地时间的 ISO 8601 字符串（对齐 companion.py 的 ``datetime.now().isoformat()``）。"""
    return datetime.now().isoformat()


def default_meta(*, now: Optional[str] = None) -> dict:
    """``meta`` 默认结构：``{created_at, updated_at}``（ISO 8601 本地时区）。"""
    ts = now or iso_now()
    return {"created_at": ts, "updated_at": ts}


def default_settings() -> dict:
    """``settings`` 默认结构（**返回副本**，调用方可安全就地修改）。"""
    return dict(SETTING_DEFAULTS)


def default_library() -> dict:
    """``library`` 默认结构：世界书 / 绑定书 / 人物。"""
    return {"books": [], "bound_book_ids": [], "cast": []}


def default_journal() -> dict:
    """``journal`` 默认结构：**跨局累积**（与 ``plays[]`` 物理分离）。"""
    return {"seen_endings": [], "unlocked_entries": [], "first_seen": {}}


def default_summary() -> dict:
    """``play.summary`` 默认结构：**结构化字段**（非 prompt 里临时拼接）。"""
    return {"up_to_turn": 0, "text": "", "generated_by": "", "verified": False}


def default_llm_state() -> dict:
    """``play.llm`` 默认结构：降级状态留痕（D-V22-12）。"""
    return {"last_model": "", "last_error": "", "degraded": False, "last_propose_at": ""}


def default_vars() -> dict:
    """``play.vars`` 默认结构（§4.1 示例）。

    * ``vars`` 是**唯一可写状态**；键名受内容包 ``transforms.json`` 白名单约束
      （白名单外键名一律拒绝写入，design-v22 §4.2）。
    * 内容包可扩充命名值，建议 ``≤ MAX_VARS`` 个（对齐 QBN「少量命名数值」）。
    """
    return {
        "poured": "",
        "knows_name": False,
        "held_items": [],
        "scene_items": [],
        "given": [],
        "opened": [],
        "known": [],
    }


def default_tavern(*, now: Optional[str] = None) -> dict:
    """``tavern.json`` 完整默认结构（缺文件 / 缺键时的**类默认**）。

    Args:
        now: 可注入时间戳（确定性单测用）；``None`` 时取当前时间。

    Returns:
        与 §4.1 逐键对齐的字典；``schema_version == SCHEMA_VERSION``。
    """
    ts = now or iso_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": default_meta(now=ts),
        "settings": default_settings(),
        "library": default_library(),
        "plays": [],
        "active_play_id": "",
        "journal": default_journal(),
    }


# ===========================================================================
# 设置默认值（§4.1 settings；D-V22-08：**不放 GuiConfig**）
# ===========================================================================

#: 酒馆设置默认值全集（§4.1）。
SETTING_DEFAULTS: Dict[str, Any] = {
    "worldbook_budget_chars": 1600,
    "worldbook_scan_depth": 4,
    "max_lore_entries_per_turn": 3,
    "recursive_max_depth": 2,
    "transcript_keep_turns": 14,
    "auto_summary_every": 8,
    "allow_free_input": True,
    "allow_propose": True,
    "llm_narration": True,
    "narrator_length": "short",
}

#: 设置键全集（顺序即 §4.1 声明顺序）。
SETTING_KEYS: Tuple[str, ...] = tuple(SETTING_DEFAULTS.keys())

#: ``narrator_length`` 合法取值。
NARRATOR_LENGTHS: Tuple[str, ...] = ("short", "medium", "long")


# ===========================================================================
# 7 变换白名单与 pre/post 签名（§4.2；本批只声明，不实现）
# ===========================================================================

@dataclass(frozen=True)
class TransformSpec:
    """单条受控变换的**契约声明**（本批只冻结签名/语义，批 2 engine 实现）。

    Attributes:
        transform_id: 变换 id（必须 ∈ :data:`TRANSFORM_WHITELIST`）。
        pre: ``pre`` 前置条件的**签名式声明**（人类可读；实际判定在 engine）。
        post: ``post`` 后置效果的**签名式声明**（人类可读；实际施加在 engine）。
        touches: 该变换触碰的 ``vars`` 字段名（状态白名单用途）。
    """

    transform_id: str
    pre: str
    post: str
    touches: Tuple[str, ...]


#: 白名单顺序（§4.2 表格顺序，**恰好 7 条**）。
TRANSFORM_WHITELIST: Tuple[str, ...] = (
    "move_to",
    "take",
    "give",
    "open",
    "ask_about",
    "wait",
    "order",
)

#: 7 变换的 ``pre``/``post`` 声明（键集与 :data:`TRANSFORM_WHITELIST` 严格一致）。
TRANSFORM_SPECS: Dict[str, TransformSpec] = {
    "move_to": TransformSpec(
        "move_to",
        pre="target ∈ reachable(scene)",
        post="scene_id = target",
        touches=("scene_id",),
    ),
    "take": TransformSpec(
        "take",
        pre="item ∈ scene_items",
        post="held_items += item ; scene_items -= item",
        touches=("held_items", "scene_items"),
    ),
    "give": TransformSpec(
        "give",
        pre="item ∈ held_items",
        post="held_items -= item ; given += item",
        touches=("held_items", "given"),
    ),
    "open": TransformSpec(
        "open",
        pre="precondition(scene, key) 成立",
        post="opened += target",
        touches=("opened",),
    ),
    "ask_about": TransformSpec(
        "ask_about",
        pre="topic ∈ known_topics(scene)",
        post="known += topic",
        touches=("known",),
    ),
    "wait": TransformSpec(
        "wait",
        pre="—（无前置）",
        post="turn += 1",
        touches=("turn",),
    ),
    "order": TransformSpec(
        "order",
        pre="menu(scene) 非空",
        post="poured += item",
        touches=("poured",),
    ),
}

#: §4.1 示例中出现的 ``vars`` 命名值（内容包可扩充；此为默认集）。
DEFAULT_VAR_NAMES: Tuple[str, ...] = (
    "poured",
    "knows_name",
    "held_items",
    "scene_items",
    "given",
    "opened",
    "known",
)

#: 建议 ``vars`` 命名值上限（§4.2「防变量爆炸」）。
MAX_VARS: int = 8


# ===========================================================================
# 三条不变量 I1/I2/I3（§4.2）
# ===========================================================================

#: 不变量 id 全集。
INVARIANTS: Tuple[str, ...] = ("I1", "I2", "I3")

#: 不变量语义（供 docstring / UI 归因文案复用）。
INVARIANT_RULES: Dict[str, str] = {
    "I1": "集合互斥：held_items ∩ scene_items = ∅（东西不能既在身上又在桌上）",
    "I2": "引用有效：node_id ∈ 内容包节点集 且 scene_id ∈ 本书地点集（防悬空引用）",
    "I3": "只增不改：transcript 长度单调不减；applied 记录不可重写（防历史被覆写）",
}


def _vars_of(state: Any) -> dict:
    """安全取 ``state['vars']``（非 dict 时返回空 dict）。"""
    if isinstance(state, dict):
        v = state.get("vars")
        if isinstance(v, dict):
            return v
    return {}


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list 或含非 str 时丢该项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if isinstance(x, str)]


def check_i1(state: dict) -> Optional[str]:
    """I1 集合互斥判定（最小实现）。

    Returns:
        ``None`` 表示不变量保持；否则返回违规码
        ``"I1:held_item_also_in_scene:<name,...>"``。
    """
    v = _vars_of(state)
    held = _as_str_list(v.get("held_items"))
    scene = _as_str_list(v.get("scene_items"))
    overlap = [x for x in held if x in scene]
    if overlap:
        return "I1:held_item_also_in_scene:" + ",".join(overlap)
    return None


def check_i2(state: dict, content: dict) -> Optional[str]:
    """I2 引用有效判定（最小实现）。

    内容包已解析后的 ``content`` 需含 ``node_ids`` / ``scene_ids``（或等价
    ``nodes`` / ``scenes``）。二者**均缺失时无法判定，放行**（返回 ``None``）。

    Returns:
        ``None`` 表示保持；否则 ``"I2:dangling_node:<id>"`` /
        ``"I2:dangling_scene:<id>"``。
    """
    if not isinstance(state, dict):
        return None
    content = content if isinstance(content, dict) else {}
    node_ids = _as_str_list(content.get("node_ids") or content.get("nodes"))
    scene_ids = _as_str_list(content.get("scene_ids") or content.get("scenes"))
    node_id = state.get("node_id")
    scene_id = state.get("scene_id")
    if node_ids and isinstance(node_id, str) and node_id not in node_ids:
        return f"I2:dangling_node:{node_id}"
    if scene_ids and isinstance(scene_id, str) and scene_id and scene_id not in scene_ids:
        return f"I2:dangling_scene:{scene_id}"
    return None


def check_i3(state: dict, prev_len: Optional[int] = None) -> Optional[str]:
    """I3 只增不改判定（最小实现）。

    Args:
        state: 局状态（读 ``state['transcript']``）。
        prev_len: 施加变换前的 ``transcript`` 长度；``None`` 时不做长度比较。

    Returns:
        ``None`` 表示保持；否则 ``"I3:transcript_shrunk:<prev>-><now>"``。
    """
    if not isinstance(state, dict):
        return None
    transcript = state.get("transcript")
    if not isinstance(transcript, list):
        return None
    if isinstance(prev_len, int) and len(transcript) < prev_len:
        return f"I3:transcript_shrunk:{prev_len}->{len(transcript)}"
    return None


# ===========================================================================
# 6 条硬禁区（§4.2；任何档位都不得触碰，校验器最高优先级）
# ===========================================================================

class ForbiddenRule(str, Enum):
    """6 条硬禁区 id（str 枚举，可直接序列化/比较）。"""

    REWRITE_HISTORY = "rewrite_history"
    CROSS_CHAPTER = "cross_chapter"
    KILL_REVIVE_CHARACTER = "kill_revive_character"
    TOUCH_STRUCTURE = "touch_structure"
    EMIT_RA_NUMBER = "emit_ra_number"
    UNKNOWN_VAR = "unknown_var"


#: 硬禁区 id 全集（**恰好 6 条**；顺序即 §4.2 声明顺序）。
FORBIDDEN_RULES: Tuple[str, ...] = tuple(rule.value for rule in ForbiddenRule)

#: 硬禁区中文语义（逐条对应 §4.2；供校验器 reason 与 UI 归因复用）。
FORBIDDEN_RULE_DESC: Dict[str, str] = {
    "rewrite_history": "改写已发生的事实（transcript append-only，不可改历史）",
    "cross_chapter": "跨越章节边界（chapter_id 只能由章节结束条件推进，不能由输入决定）",
    "kill_revive_character": "杀死/复活关键角色、改变已确立的人物身份",
    "touch_structure": "触碰 meta / schema_version / settings（结构字段不参与玩法）",
    "emit_ra_number": "产出任何 R-A 禁项数值（好感/心情/经验/货币/筹码/胜率/连胜/进度条/断签/倒计时），隐藏不展示也不做",
    "unknown_var": "写入未在白名单声明的 var 名",
}

#: 硬禁区第 4 条针对的**结构字段**（结构字段不参与玩法）。
FORBIDDEN_STRUCTURE_FIELDS: Tuple[str, ...] = ("meta", "schema_version", "settings")


# ===========================================================================
# 三级路由枚举与 resolution 字段形状（§4.2 / §4.3）
# ===========================================================================

class RouteMode(str, Enum):
    """三级意图路由档位（Q1 / D-V22-02）。"""

    VERBATIM = "verbatim"   # ① 词表命中，本地规则函数改状态，零 token
    PROPOSE = "propose"     # ② LLM 只提议，执行权在本地校验器（默认开、可关）
    NARRATE = "narrate"     # ③ 兜底终态，无人改状态


#: 路由档位全集（§4.3 常量，顺序即三级序）。
ROUTE_MODES: Tuple[str, ...] = tuple(mode.value for mode in RouteMode)


class Resolution(TypedDict):
    """``transcript`` 每拍的留痕形状（§4.2 / §4.3）。

    要求：**每条 transcript 自带 resolution**；``mode`` 是三级路由档位；``ok`` 表示
    本回合是否**成功施加**了受控变换；``reason`` 是可读自然语言短码（供「记录」Tab
    归因）；``llm_used`` 标记本拍是否真的调用过 LLM（``allow_propose=False`` 时必须
    ``False``）。
    """

    mode: str          # ∈ ROUTE_MODES
    transform: str     # 变换 id；未施加时为空串
    ok: bool           # 变换是否成功施加
    reason: str        # 可读短码（成功亦可留 "ok"）
    llm_used: bool     # 本拍是否调用过 LLM


#: ``Resolution`` 必填字段全集（**契约断言锚点**）。
RESOLUTION_REQUIRED_KEYS: Tuple[str, ...] = ("mode", "transform", "ok", "reason", "llm_used")


class TranscriptEntry(TypedDict):
    """``transcript`` 单条形状（§4.2 留痕的数据形状）。"""

    turn: int
    role: str
    input_kind: str
    text: str
    resolution: Resolution
    narrated: bool
    at: str


#: ``TranscriptEntry`` 键全集（顺序即 §4.2 示例顺序）。
TRANSCRIPT_ENTRY_KEYS: Tuple[str, ...] = (
    "turn",
    "role",
    "input_kind",
    "text",
    "resolution",
    "narrated",
    "at",
)

#: 输入种类：free = 自由输入；choice = 选项快照（两者同为 verbatim 语义，零 token）。
INPUT_KINDS: Tuple[str, ...] = ("free", "choice")

#: transcript 行的角色集。
TRANSCRIPT_ROLES: Tuple[str, ...] = ("player", "narrator")

#: ``resolution.reason`` 的**基础短码**（可读自然语言；扩展见 REASON_PREFIXES）。
REASON_CODES: Tuple[str, ...] = (
    "ok",
    "unknown_transform",
    "bad_args",
    "precondition_failed",
    "forbidden",
    "invariant_violated",
    "llm_timeout",
    "llm_bad_json",
    "llm_disabled",
)

#: ``resolution.reason`` 的**前缀型短码**（后接 ``:<detail>``，§4.2）。
REASON_PREFIXES: Tuple[str, ...] = (
    "precondition_failed:",
    "forbidden:",
    "invariant_violated:",
    "bad_args:",
)


# ===========================================================================
# prompt 五段式（§4.3 / D-V22-10）
# ===========================================================================

#: 五段式**有序**段名（顺序即「位置即权重」的固定分层）。
PROMPT_SEGMENTS: Tuple[str, ...] = (
    "narrator_rules",   # [system] 说书人规则（长度/视角/禁项）
    "world_rules",      # [system] 世界规则（constant 条目）
    "character_card",   # [system] 角色卡（她是谁/怎么行动/语气样本）
    "turn_context",     # [system] 本回合情境（vars 摘要 + 命中条目 + 本回合发生了什么）
    "history",          # [history] 近 N 条叙述 + 【前情提要】
)

#: 段名 → 消息 role（前 4 段 system，末段 history）。
PROMPT_SEGMENT_ROLES: Dict[str, str] = {
    "narrator_rules": "system",
    "world_rules": "system",
    "character_card": "system",
    "turn_context": "system",
    "history": "history",
}

#: prompt 组装模式（§4.3 ``mode="normal"|"reroll"``）。
PROMPT_MODES: Tuple[str, ...] = ("normal", "reroll")


# ===========================================================================
# 世界书条目结构（§4.1 / D-V22-09）
# ===========================================================================

class WorldbookEntry(TypedDict):
    """世界书条目形状（字段模型照搬公开规范，**不摘录规范正文**）。"""

    uid: int
    title: str
    keys: List[str]
    secondary_keys: List[str]
    selective_logic: str
    content: str
    position: str
    depth: int
    order: int
    weight: int
    constant: bool
    probability: int
    sticky: int
    cooldown: int
    recursive: bool
    case_sensitive: bool
    enabled: bool
    budget_chars_est: int


#: 世界书条目字段全集（顺序即 §4.1 示例顺序）。
WORLDBOOK_ENTRY_FIELDS: Tuple[str, ...] = (
    "uid",
    "title",
    "keys",
    "secondary_keys",
    "selective_logic",
    "content",
    "position",
    "depth",
    "order",
    "weight",
    "constant",
    "probability",
    "sticky",
    "cooldown",
    "recursive",
    "case_sensitive",
    "enabled",
    "budget_chars_est",
)

#: selective logic 四态（§4.2）。
SELECTIVE_LOGIC_MODES: Tuple[str, ...] = ("AND_ANY", "NOT_ALL", "NOT_ANY", "AND_ALL")

#: 落点仅三种（**不做 role=assistant 注入**）。
LORE_POSITIONS: Tuple[str, ...] = ("system_head", "system_tail", "history_depth")

#: ``constant`` 条目的上限（超限条目加载时禁用并记日志，而非崩）。
CONSTANT_ENTRY_LIMIT: int = 5

#: 单条 ``content`` 字数上限（**字符预算，非 token**；如实标注为近似）。
LORE_MAX_CONTENT_CHARS: int = 200


def default_worldbook_entry() -> dict:
    """世界书条目的**类默认**（字段齐全，便于编辑器新增行/缺键补默认）。"""
    return {
        "uid": 0,
        "title": "",
        "keys": [],
        "secondary_keys": [],
        "selective_logic": "AND_ANY",
        "content": "",
        "position": "system_tail",
        "depth": 0,
        "order": 100,
        "weight": 100,
        "constant": False,
        "probability": 100,
        "sticky": 0,
        "cooldown": 0,
        "recursive": False,
        "case_sensitive": False,
        "enabled": True,
        "budget_chars_est": 0,
    }


# ===========================================================================
# 局 / 人物 / 书槽结构（§4.1）
# ===========================================================================

#: ``plays[i]`` 键全集（顺序即 §4.1 示例顺序）。
PLAY_KEYS: Tuple[str, ...] = (
    "play_id",
    "book_id",
    "title",
    "status",
    "created_at",
    "updated_at",
    "chapter_id",
    "node_id",
    "scene_id",
    "turn",
    "seed",
    "vars",
    "seen_nodes",
    "pending",
    "transcript",
    "summary",
    "llm",
)

#: 局状态取值。
PLAY_STATUSES: Tuple[str, ...] = ("active", "ended")


class BookSlot(TypedDict):
    """``library.books[]`` 形状。"""

    book_id: str
    title: str
    builtin: bool
    entries: List[WorldbookEntry]


#: ``library.books[]`` 键全集。
BOOK_SLOT_KEYS: Tuple[str, ...] = ("book_id", "title", "builtin", "entries")


def default_book_slot() -> dict:
    """书槽默认结构。"""
    return {"book_id": "", "title": "", "builtin": False, "entries": []}


class CastMember(TypedDict):
    """``library.cast[]`` 形状（人物卡绑定，复用 role_card 的 card_id）。"""

    cast_id: str
    role: str
    card_id: str
    card_snapshot: dict


#: ``library.cast[]`` 键全集。
CAST_MEMBER_KEYS: Tuple[str, ...] = ("cast_id", "role", "card_id", "card_snapshot")


def default_cast_member() -> dict:
    """人物槽默认结构。"""
    return {"cast_id": "", "role": "", "card_id": "", "card_snapshot": {}}


def new_play(
    book_id: str,
    title: str,
    seed: int,
    *,
    play_id: Optional[str] = None,
    now: Optional[str] = None,
) -> dict:
    """新建一局**默认结构**（§4.3 ``new_play``）。

    Args:
        book_id: 绑定世界书 id。
        title: 局标题（UI 显示，**无序号**，Q4）。
        seed: **显式 seed**（后续本地随机走 ``random.Random(seed + turn)``）。
        play_id: 局 id；``None`` 时为空串（由批 1 store 生成）。
        now: 可注入时间戳（确定性单测用）。

    Returns:
        键集等于 :data:`PLAY_KEYS` 的字典，``status == "active"``。
    """
    ts = now or iso_now()
    return {
        "play_id": play_id or "",
        "book_id": book_id,
        "title": title,
        "status": "active",
        "created_at": ts,
        "updated_at": ts,
        "chapter_id": "ch1",
        "node_id": "opening",
        "scene_id": "",
        "turn": 0,
        "seed": int(seed),
        "vars": default_vars(),
        "seen_nodes": [],
        "pending": [],
        "transcript": [],
        "summary": default_summary(),
        "llm": default_llm_state(),
    }


def default_play() -> dict:
    """空局默认结构（``new_play("", "", 0)`` 的等价物）。"""
    return new_play("", "", 0)


# —— 读时迁移辅助（类型守卫小工具，纯函数） ——

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


def _as_str(value: Any, default: str = "") -> str:
    """``str`` 守卫。"""
    return value if isinstance(value, str) else default


def _type_matches(value: Any, default: Any) -> bool:
    """按默认值的类型判定 ``value`` 是否类型相符（bool/int 严格区分）。"""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def _merge_settings(raw: Any) -> dict:
    """``settings`` 读时合并：已知键做类型守卫，未知键保留（前向兼容）。"""
    out = default_settings()
    if isinstance(raw, dict):
        for key, default in SETTING_DEFAULTS.items():
            if key in raw and _type_matches(raw[key], default):
                out[key] = raw[key]
        for key, value in raw.items():
            if key not in out:  # 未知设置项不销毁
                out[key] = value
    return out


def merge_play(data: Any) -> dict:
    """单局读时迁移：默认结构为底 + 类型守卫；未知字段保留。"""
    d = default_play()
    if not isinstance(data, dict):
        return d
    # 未知字段不销毁（前向兼容）
    for key, value in data.items():
        if key not in d:
            d[key] = value
    d["play_id"] = _as_str(data.get("play_id"), d["play_id"])
    d["book_id"] = _as_str(data.get("book_id"), d["book_id"])
    d["title"] = _as_str(data.get("title"), d["title"])
    d["status"] = data.get("status") if data.get("status") in PLAY_STATUSES else "active"
    d["created_at"] = _as_str(data.get("created_at"), d["created_at"])
    d["updated_at"] = _as_str(data.get("updated_at"), d["updated_at"])
    d["chapter_id"] = _as_str(data.get("chapter_id"), d["chapter_id"])
    d["node_id"] = _as_str(data.get("node_id"), d["node_id"])
    d["scene_id"] = _as_str(data.get("scene_id"), d["scene_id"])
    d["turn"] = _as_int(data.get("turn"), d["turn"])
    d["seed"] = _as_int(data.get("seed"), d["seed"])
    if isinstance(data.get("vars"), dict):
        merged_vars = dict(d["vars"])
        merged_vars.update(data["vars"])
        d["vars"] = merged_vars
    for key in ("seen_nodes", "pending", "transcript"):
        if isinstance(data.get(key), list):
            d[key] = data[key]
    if isinstance(data.get("summary"), dict):
        summary = dict(d["summary"])
        summary.update(data["summary"])
        d["summary"] = summary
    if isinstance(data.get("llm"), dict):
        llm = dict(d["llm"])
        llm.update(data["llm"])
        d["llm"] = llm
    return d


def merge_defaults(data: Any) -> dict:
    """读时迁移（§4.3 / §5.4-4）：默认结构为底 + ``setdefault`` + ``isinstance`` 守卫。

    * 非 dict 入参 → 直接返回 :func:`default_tavern`；
    * 缺键 → 补类默认（**零迁移**，批 1 store 依赖此性质）；
    * 键类型错 → 该字段回落默认（如 ``plays`` 非 list）；
    * **未知字段不销毁**（前向兼容，对齐 ``role_card.py`` 铁则）。

    Returns:
        合并后的新 dict（**不修改入参**）。
    """
    d = default_tavern()
    if not isinstance(data, dict):
        return d
    d["schema_version"] = _as_int(data.get("schema_version"), SCHEMA_VERSION)
    for key, value in data.items():
        if key not in d:  # 未知顶层字段不销毁
            d[key] = value
    if isinstance(data.get("meta"), dict):
        meta = dict(d["meta"])
        meta.update(data["meta"])
        d["meta"] = meta
    d["settings"] = _merge_settings(data.get("settings"))
    if isinstance(data.get("library"), dict):
        lib = data["library"]
        if isinstance(lib.get("books"), list):
            d["library"]["books"] = lib["books"]
        if isinstance(lib.get("bound_book_ids"), list):
            d["library"]["bound_book_ids"] = lib["bound_book_ids"]
        if isinstance(lib.get("cast"), list):
            d["library"]["cast"] = lib["cast"]
        for key, value in lib.items():
            if key not in d["library"]:
                d["library"][key] = value
    if isinstance(data.get("plays"), list):
        d["plays"] = [merge_play(p) for p in data["plays"] if isinstance(p, dict)]
    d["active_play_id"] = _as_str(data.get("active_play_id"), d["active_play_id"])
    if isinstance(data.get("journal"), dict):
        journal = data["journal"]
        if isinstance(journal.get("seen_endings"), list):
            d["journal"]["seen_endings"] = journal["seen_endings"]
        if isinstance(journal.get("unlocked_entries"), list):
            d["journal"]["unlocked_entries"] = journal["unlocked_entries"]
        if isinstance(journal.get("first_seen"), dict):
            d["journal"]["first_seen"] = journal["first_seen"]
        for key, value in journal.items():
            if key not in d["journal"]:
                d["journal"][key] = value
    return d


#: schema 迁移步骤表：``旧版本号 -> 迁移函数``。v1 为当前基线，暂无历史版本。
_MIGRATIONS: Dict[int, Callable[[dict], dict]] = {}


def migrate(data: Any) -> dict:
    """旧 schema → 当前 schema（§4.3 / §4.4 L3）。

    以 :func:`merge_defaults` 的合并结果为底，按版本号**升序**逐步施加
    ``_MIGRATIONS``（当前 v1 为基线，表为空 → 直通），最终把
    ``schema_version`` 归位为 :data:`SCHEMA_VERSION`。

    Returns:
        迁移后的新 dict；**不修改入参**。
    """
    d = merge_defaults(data)
    version = _as_int(d.get("schema_version"), SCHEMA_VERSION)
    if version > SCHEMA_VERSION:
        # L4：schema_version 高于当前 → 只读加载，**不降级、不改写**（由 store 打只读标）。
        return d
    for old_version in sorted(_MIGRATIONS):
        if version <= old_version < SCHEMA_VERSION:
            d = _MIGRATIONS[old_version](d)
    d["schema_version"] = SCHEMA_VERSION
    return d
