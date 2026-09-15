"""gui/tavern/intent_router.py —— 酒馆功能域 · 三级意图路由（V22-03，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.2 ★ 三级路由的精确定义（``verbatim`` / ``propose`` / ``narrate`` 的触发、
      失败行为、留痕）+ 白名单枚举 + ``args`` 形状 + 本地校验器序
    - §4.3 ``intent_router`` 冻结签名（``resolve_verbatim`` / ``route``）
    - §5    高自由度机制的「② 可自由输入的对话层」环节
    - §5.4  #13 降级不抛错（LLM 失败 → 纯叙述 + 留痕）
    - D-V22-02 / D-V22-03 / D-V22-12（降级铁律 / ``propose`` 默认开可关 / 失败同路径）
    - §9.3 / §10.1 路由验收要点（三档 + LLM 关闭 + 超时 + 脏返回，均不抛且留痕齐全）

三级路由（**写权恒在本地**）::

    玩家输入 / 选项点击
       │
       ├─ ① verbatim ── 本地词表 + 动词/名词解析命中 → 直接构造 args → engine.apply_transform
       │                 零 token、不依赖网络 / LLM；pre 不满足 → 降级 ③ narrate
       │
       ├─ ② propose  ── 未命中 且 allow_propose 且 LLM 可用 → LLM **只从 7 条白名单里提议**
       │                 ``{transform, args}`` → **本地校验器裁决**（engine.validate / apply_transform）
       │                 通过才施加；否则降级 ③ narrate
       │
       └─ ③ narrate  ── 兜底终态：状态**不变**，只产叙述（无人改状态）

降级铁律（D-V22-12，**硬要求**）：
    **LLM 关闭 / 超时 / 返回畸形 JSON / 抛异常 四种失败走完全同一条代码路径**
    —— 全部汇入唯一兜底函数 :func:`_narrate`，产出 ``mode="narrate"`` 的
    ``resolution`` 且**状态逐字节不变**；**绝不弹窗、绝不抛到调用方**。

LLM 以注入方式解耦（保零 Qt）：
    ``llm_propose(strict_json_prompt) -> dict | None`` 由批 2 的 ``service.py`` 注入；
    本模块**不联网、不 import 任何网络库**（``socket`` / ``urllib`` / ``http`` /
    ``requests`` / ``httpx`` / ``aiohttp`` 一律不引）。

硬约束：
    * 仅标准库（含 ``concurrent.futures`` 用于给注入 callable 施加超时阈值）；
    * **零 Qt**（``import gui.tavern.intent_router`` 在无 PySide6 环境必须成功）；
    * 异常走 :mod:`gui.tavern.errors` 冻结层级（``TavernRouteError`` 仅用于
      「入参本身不可用」的理论场景，如 ``state`` 非 dict / ``input_kind`` 非法）；
    * 日志 ``logger.debug(..., exc_info=True)``，**不写裸 ``except: pass``**。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeoutError
from typing import Any, Callable, Dict, List, Optional, Tuple

from .engine import ApplyResult, apply_transform, build_resolution, validate
from .errors import TavernRouteError
from .model import INPUT_KINDS, RESOLUTION_REQUIRED_KEYS, ROUTE_MODES, TRANSFORM_WHITELIST

_LOGGER = logging.getLogger("maling.tavern.intent_router")

__all__ = [
    # —— 主入口（批 2 service 对接面）——
    "route",
    "resolve_verbatim",
    "resolve_choice",
    "build_strict_json_prompt",
    # —— 词表与常量 ——
    "VERB_WORDS",
    "VERB_PRIORITY",
    "DEFAULT_TIMEOUT_S",
    "ROUTE_MODES",
    "TRANSFORM_WHITELIST",
    "RESOLUTION_REQUIRED_KEYS",
    "INPUT_KINDS",
    # —— LLM 失败短码（与 model.REASON_CODES 对齐）——
    "REASON_LLM_DISABLED",
    "REASON_LLM_TIMEOUT",
    "REASON_LLM_BAD_JSON",
    "REASON_UNKNOWN_CHOICE",
]

#: 注入 LLM 提议 callable 的类型别名（``llm_propose(strict_json_prompt) -> dict | None``）。
LLMProposeFn = Callable[[str], Optional[dict]]

#: ``propose`` 请求默认超时阈值（秒；设计 §4.2「有超时阈值」）。
DEFAULT_TIMEOUT_S: float = 6.0

#: LLM 层失败短码（**全部以 ``llm_`` 起头**，与 :data:`model.REASON_CODES` 对齐）。
#: —— 四类失败共用同一前缀，便于「降级同路径」可断言 + 「记录」Tab 归因。
REASON_LLM_DISABLED: str = "llm_disabled"    # LLM 关闭 / 未注入 / 返回 None / 抛异常
REASON_LLM_TIMEOUT: str = "llm_timeout"      # 调用超时（阈值内未返回）
REASON_LLM_BAD_JSON: str = "llm_bad_json"    # 返回非 dict / 畸形 JSON / 缺 transform

#: 选项点击命中不到受控快照时的归因短码（``bad_args`` 前缀，属可归因短码）。
REASON_UNKNOWN_CHOICE: str = "bad_args:unknown_choice"

# ===========================================================================
# 词表：动词 + 名词解析（零 token 主路径，写法对齐 gui/intent.py 的「词表 + 逐条匹配」）
# ===========================================================================

#: 各变换的内置动词词表（子串匹配；中文为主，保守覆盖常见祈使式）。
#: 内容包可经 ``content["intents"]`` **显式覆盖**（最高优先级）或经 ``content["aliases"]``
#: 补显示名 → id 映射，从而精确驱动解析。
VERB_WORDS: Dict[str, Tuple[str, ...]] = {
    "take": (
        "拿起来", "拿起", "拿走", "拿上", "拿了", "抓起", "捡起", "拾起",
        "取走", "取来", "捡", "拿", "取",
    ),
    "give": (
        "交给", "递给", "送给", "还给", "塞给", "递", "给",
    ),
    "open": (
        "打开", "拉开", "掀开", "推开", "撬开", "解开", "解锁", "开",
    ),
    "ask_about": (
        "打听", "询问", "问起", "问到", "问", "聊起", "谈到", "提到", "说说", "聊",
    ),
    "order": (
        "点一杯", "点一份", "点一壶", "点个", "点份", "来一杯", "来一份",
        "来一个", "来一壶", "来点", "要一杯", "要一份",
    ),
    "move_to": (
        "走到", "走向", "前往", "移动到", "来到", "回到", "进去", "出去",
        "过去", "走", "去", "回", "进",
    ),
    "wait": (
        "等一下", "等一会", "稍等", "等等", "等待", "停一会", "停一下", "等",
    ),
}

#: 动词判定**优先级**（先具体后泛化；避免「去点一杯」被误判为 move_to）。
#: 需名词的类别（take/give/open/ask_about）无名词即**不触发**，故顺序即决策顺序。
VERB_PRIORITY: Tuple[str, ...] = (
    "take", "give", "open", "ask_about", "order", "move_to", "wait",
)

#: 需要**名词命中**才触发的变换（无名词则跳过该类别，继续看下一优先级）。
_NOUN_REQUIRED: Tuple[str, ...] = ("take", "give", "open", "ask_about")


# ===========================================================================
# 小工具（类型守卫）
# ===========================================================================

def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list/tuple 或含非 str 项时丢弃非法项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if isinstance(x, str) and x]


def _dedupe(seq: List[str]) -> List[str]:
    """保序去重。"""
    seen: Dict[str, None] = {}
    for x in seq:
        seen.setdefault(x, None)
    return list(seen.keys())


def _flatten_str_map(value: Any) -> List[str]:
    """把 ``{k: [str,…]}`` 的映射值拍平为 ``list[str]``（非 dict 返回空）。"""
    out: List[str] = []
    if isinstance(value, dict):
        for v in value.values():
            out.extend(_as_str_list(v))
    return out


# ===========================================================================
# 名词词表装配（内容包 + 局状态派生；全部可缺省、缺省即空）
# ===========================================================================

def _scene_vocab(content: dict) -> List[str]:
    ids = _as_str_list(content.get("scene_ids"))
    reach = content.get("reachable")
    if isinstance(reach, dict):
        ids.extend(x for x in reach.keys() if isinstance(x, str))
        ids.extend(_flatten_str_map(reach))
    return _dedupe(ids)


def _item_vocab(content: dict, key: str) -> List[str]:
    ids = _as_str_list(content.get(key)) or _as_str_list(content.get("items"))
    return _dedupe(ids)


def _order_vocab(content: dict) -> List[str]:
    ids = _as_str_list(content.get("items"))
    ids.extend(_flatten_str_map(content.get("menu")))
    return _dedupe(ids)


def _topic_vocab(content: dict) -> List[str]:
    ids = _as_str_list(content.get("topics"))
    ids.extend(_flatten_str_map(content.get("known_topics")))
    return _dedupe(ids)


def _key_vocab(content: dict) -> List[str]:
    ids = _as_str_list(content.get("keys"))
    conds = content.get("open_conditions")
    if isinstance(conds, dict):
        for k in conds.keys():
            if not isinstance(k, str) or not k:
                continue
            ids.append(k)
            if ":" in k:
                ids.append(k.split(":", 1)[1])
    return _dedupe(ids)


def _match_noun(text_low: str, ids: List[str], aliases: dict) -> Optional[str]:
    """在 ``text_low`` 中匹配一个已知名词 id（**最长匹配优先**，确定性）。

    Args:
        text_low: 已小写化的输入文本。
        ids: 候选名词 id 集合。
        aliases: ``{显示名: 规范 id}`` 映射（内容包可选提供）。

    Returns:
        命中的规范 id；无命中返回 ``None``。同长度并列时取 **排序后首个** id（确定性）。
    """
    id_set = {i for i in ids if isinstance(i, str) and i}
    best: Optional[str] = None
    best_len = -1
    for nid in sorted(id_set):
        candidates = [nid]
        for alias, canon in aliases.items():
            if canon == nid and isinstance(alias, str) and alias:
                candidates.append(alias)
        for cand in candidates:
            cl = cand.lower()
            if cl and cl in text_low and len(cand) > best_len:
                best, best_len = nid, len(cand)
    return best


def _has_verb(text_low: str, transform: str) -> bool:
    """``transform`` 的任一动词是否出现在文本中。"""
    return any(w.lower() in text_low for w in VERB_WORDS.get(transform, ()))


# ===========================================================================
# 显式意图表（内容包作者精确驱动，最高优先级）
# ===========================================================================

def _match_intents(text_low: str, content: dict) -> Optional[Tuple[str, dict]]:
    """匹配内容包显式意图表 ``content["intents"]``（**最长短语优先**，确定性）。

    支持两种写法（二者择一即可）::

        # 形式 A：短语 → 变换/参数
        {"拿起照片": {"transform": "take", "args": {"item": "old_photo"}}}

        # 形式 B：关键词列表 → 变换/参数
        [{"keywords": ["拿起", "拿"], "transform": "take", "args": {"item": "old_photo"}}]

    Returns:
        ``(transform, args)``；无命中返回 ``None``。只接受合法字符串变换 + dict 参数。
    """
    table = content.get("intents")
    best: Optional[Tuple[str, dict]] = None
    best_len = -1

    def _consider(phrase: str, spec: Any) -> None:
        nonlocal best, best_len
        if not isinstance(phrase, str) or not phrase:
            return
        if phrase.lower() not in text_low or len(phrase) <= best_len:
            return
        if not isinstance(spec, dict):
            return
        transform = spec.get("transform")
        args = spec.get("args", {})
        if isinstance(transform, str) and transform and isinstance(args, dict):
            best, best_len = (transform, dict(args)), len(phrase)

    if isinstance(table, dict):
        for phrase, spec in table.items():
            _consider(phrase, spec)
    elif isinstance(table, list):
        for entry in table:
            if not isinstance(entry, dict):
                continue
            spec = {"transform": entry.get("transform"), "args": entry.get("args", {})}
            for kw in _as_str_list(entry.get("keywords")):
                _consider(kw, spec)
    return best


# ===========================================================================
# ① verbatim：本地词表 / 动词解析（零 token）
# ===========================================================================

def resolve_verbatim(text: Any, content: Any = None) -> Optional[Tuple[str, dict]]:
    """把自由输入解析为受控意图 ``(transform, args)``；未命中返回 ``None``。

    **纯本地、零 token、无网络**（写法对齐 ``gui/intent.py``：词表 + 子串匹配 + 逐项守卫）。

    判定顺序（确定性）：
      1) 内容包显式意图表 ``content["intents"]``（最高优先级，精确驱动）；
      2) 内置动词词表 :data:`VERB_WORDS` × 名词词表（按 :data:`VERB_PRIORITY` 逐个类别）：
         ``take`` / ``give`` / ``open`` / ``ask_about`` 需**名词命中**才触发；
         ``order`` / ``move_to`` 名词**可选**（缺则交 engine 按 ``seed+turn`` 确定性选）；
         ``wait`` 无名词。

    Args:
        text: 玩家自由输入（``str``；非 str 视为未命中）。
        content: 已解析内容包。读取键（**全部可缺省**）：``intents`` / ``aliases`` /
            ``scene_ids`` / ``reachable`` / ``known_topics`` / ``menu`` /
            ``open_conditions`` / ``keys`` / ``items`` / ``scene_items`` / ``held_items``。
            （``scene_items`` / ``held_items`` 由 :func:`route` 从局状态注入，供 take/give 解析。）

    Returns:
        ``(transform, args)`` 或 ``None``。
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    low = stripped.lower()
    content = content if isinstance(content, dict) else {}

    explicit = _match_intents(low, content)
    if explicit is not None:
        return explicit

    aliases = content.get("aliases")
    aliases = aliases if isinstance(aliases, dict) else {}

    take_ids = _item_vocab(content, "scene_items")
    give_ids = _item_vocab(content, "held_items")
    order_ids = _order_vocab(content)
    scene_ids = _scene_vocab(content)
    topic_ids = _topic_vocab(content)
    key_ids = _key_vocab(content)

    for transform in VERB_PRIORITY:
        if not _has_verb(low, transform):
            continue

        if transform == "take":
            nid = _match_noun(low, take_ids, aliases)
            if nid:
                return "take", {"item": nid}
            continue
        if transform == "give":
            nid = _match_noun(low, give_ids, aliases)
            if nid:
                return "give", {"item": nid}
            continue
        if transform == "open":
            nid = _match_noun(low, key_ids, aliases)
            if nid:
                return "open", {"key": nid}
            continue
        if transform == "ask_about":
            nid = _match_noun(low, topic_ids, aliases)
            if nid:
                return "ask_about", {"topic": nid}
            continue
        if transform == "order":
            nid = _match_noun(low, order_ids, aliases)
            return ("order", {"item": nid} if nid else {})
        if transform == "move_to":
            nid = _match_noun(low, scene_ids, aliases)
            return ("move_to", {"target": nid} if nid else {})
        if transform == "wait":
            return "wait", {}

    return None


def resolve_choice(choice_id: Any, pending: Any) -> Optional[Tuple[str, dict]]:
    """把选项点击解析为受控意图 ``(transform, args)``；未命中返回 ``None``。

    选项快照（``pending[]``）形状：``{"choice_id": str, "transform": str, "args": dict,
    "text"?: str}``（``text`` 仅展示用，不参与判定；``id`` 作为**容忍别名**，canonical 为
    ``choice_id``）。选项**自带受控结构**，故命中即等价于 ``verbatim``（零 token）。

    Args:
        choice_id: 被点击的选项 id（对应 ``pending[].choice_id``）。
        pending: 选项快照列表（``list[dict]``；通常取 ``state["pending"]``）。

    Returns:
        ``(transform, args)``；无匹配或快照畸形返回 ``None``。
    """
    cid = choice_id if isinstance(choice_id, str) else ""
    if not cid or not isinstance(pending, list):
        return None
    for opt in pending:
        if not isinstance(opt, dict):
            continue
        oid = opt.get("choice_id") or opt.get("id")
        if oid != cid:
            continue
        transform = opt.get("transform")
        args = opt.get("args", {})
        if isinstance(transform, str) and transform and isinstance(args, dict):
            return transform, dict(args)
        _LOGGER.debug("intent_router: 选项 %s 快照畸形，忽略", cid)
        return None
    return None


# ===========================================================================
# ② propose：严格 JSON 提示词（LLM **只从中择一**）
# ===========================================================================

def build_strict_json_prompt(state: Any, content: Any = None) -> str:
    """构造 ``propose`` 用的**严格 JSON** 提示词（只含 7 条白名单 + 当前可选面）。

    提示词**确定性**（列表全部 ``sorted``），不含任何时间 / 随机成分；
    内容包缺省时对应选项显示「（无）」。服务层据此发起一次小请求
    （``max_tokens ≤ 80``、严格 JSON），返回值再由本模块的校验器裁决。

    Returns:
        单段提示词字符串（要求 LLM **只输出** ``{"transform": …, "args": {…}}``）。
    """
    eff = content if isinstance(content, dict) else {}
    scene = ""
    if isinstance(state, dict) and isinstance(state.get("scene_id"), str):
        scene = state["scene_id"]

    reach = eff.get("reachable")
    reach = reach if isinstance(reach, dict) else {}
    topics = eff.get("known_topics")
    topics = topics if isinstance(topics, dict) else {}
    menu = eff.get("menu")
    menu = menu if isinstance(menu, dict) else {}

    reachable = sorted(_as_str_list(reach.get(scene, [])))
    known = sorted(_as_str_list(topics.get(scene, [])))
    drinks = sorted(_as_str_list(menu.get(scene, [])))

    lines = [
        "你是酒馆的规则顾问。只输出一个 JSON 对象，不要解释、不要多余文字。",
        '输出格式：{"transform": "<动作id>", "args": { ... }}',
        "允许的动作 id 与参数（只能从中选一个）：",
        '- move_to: {"target": <地点>}   可选地点：' + (",".join(reachable) or "（无）"),
        '- take: {"item": <物品>}        物品：当前场景里的东西',
        '- give: {"item": <物品>}        物品：你手里拿着的东西',
        '- open: {"key": <条件/钥匙>}',
        '- ask_about: {"topic": <话题>}  可问话题：' + (",".join(known) or "（无）"),
        '- wait: {}                      让一拍过去',
        '- order: {"item": <酒或物>}     可点：' + (",".join(drinks) or "（无）"),
    ]
    return "\n".join(lines)


# ===========================================================================
# LLM 调用（注入 callable + 超时阈值；失败分类但**共用同一前缀**）
# ===========================================================================

def _invoke_propose(
    llm_propose: Optional[LLMProposeFn],
    prompt: str,
    timeout_s: Any,
) -> Tuple[bool, Any, str]:
    """调用注入的 ``llm_propose``（可施加超时阈值），**永不抛**。

    Args:
        llm_propose: 注入 callable；``None`` 视为「LLM 关闭」。
        prompt: 严格 JSON 提示词。
        timeout_s: 超时阈值（秒）；``None`` 或 ``<=0`` 表示不加线程超时（由 callable 自管）。

    Returns:
        ``(ok, raw, reason)``：
          * ``ok=True`` → ``raw`` 为 callable 原始返回值（仍需 :func:`_normalize_proposal` 规范化）；
          * ``ok=False`` → ``reason`` ∈ {``llm_disabled``, ``llm_timeout``, ``llm_*``}。
    """
    if llm_propose is None:
        return False, None, REASON_LLM_DISABLED
    try:
        if isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool) and timeout_s > 0:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tavern-propose")
            try:
                future = executor.submit(llm_propose, prompt)
                raw = future.result(timeout=float(timeout_s))
            finally:
                # 不阻塞：超时后立即返回，避免把调用方拖住（callable 契约应自管网络超时）
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            raw = llm_propose(prompt)
    except (TimeoutError, _FutureTimeoutError):
        _LOGGER.debug("intent_router: propose 超时（阈值 %s s），降级 narrate", timeout_s)
        return False, None, REASON_LLM_TIMEOUT
    except Exception:
        # 与「LLM 关闭」同语义：LLM 这一拍不可用 → 降级 narrate（D-V22-12）
        _LOGGER.debug("intent_router: propose 调用抛异常，降级 narrate", exc_info=True)
        return False, None, REASON_LLM_DISABLED

    if raw is None:
        return False, None, REASON_LLM_DISABLED
    return True, raw, ""


def _normalize_proposal(raw: Any) -> Tuple[Optional[dict], str]:
    """把 LLM 原始返回规范化为 ``{"transform": str, "args": dict}``。

    容忍：``str``（尝试 ``json.loads``，失败 → ``llm_bad_json``）/ ``dict``。
    要求：``transform`` 为非空 ``str``；``args`` 缺省视为 ``{}``，非 dict → ``llm_bad_json``。

    Returns:
        ``(proposal, reason)``：成功 ``reason=""``；失败 ``proposal=None`` 且
        ``reason == REASON_LLM_BAD_JSON``。
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            _LOGGER.debug("intent_router: propose 返回畸形 JSON，降级 narrate", exc_info=True)
            return None, REASON_LLM_BAD_JSON
    if not isinstance(raw, dict):
        _LOGGER.debug("intent_router: propose 返回非 dict（%s），降级 narrate", type(raw).__name__)
        return None, REASON_LLM_BAD_JSON
    transform = raw.get("transform")
    if not isinstance(transform, str) or not transform:
        _LOGGER.debug("intent_router: propose 缺 transform，降级 narrate")
        return None, REASON_LLM_BAD_JSON
    args = raw.get("args", {})
    if not isinstance(args, dict):
        _LOGGER.debug("intent_router: propose 的 args 非 dict，降级 narrate")
        return None, REASON_LLM_BAD_JSON
    return {"transform": transform, "args": dict(args)}, ""


# ===========================================================================
# ③ narrate 兜底：**唯一降级出口**（超时 / 关闭 / 畸形 / 越权 / pre 不满足 全部汇入）
# ===========================================================================

def _narrate(state: dict, *, reason: str, transform: str = "", llm_used: bool = False) -> dict:
    """构造兜底 ``narrate`` 的 ``resolution``（**状态不改**，只产叙述留痕）。

    ⚠️ **这是降级铁律（D-V22-12）的唯一出口** —— LLM 关闭 / 超时 / 畸形 JSON /
    抛异常 / 越权提议 / pre 不满足 **全部** 经此函数产出 ``mode="narrate"``，
    确保「超时与关闭走同一条代码路径」（不写两套逻辑）。

    Returns:
        含 :data:`RESOLUTION_REQUIRED_KEYS` 全键的 ``resolution`` dict。
    """
    placeholder = ApplyResult(False, state, reason, transform)
    return build_resolution(placeholder, mode="narrate", llm_used=llm_used)


def _decide_and_apply(
    state: dict,
    transform: Any,
    args: Any,
    content: Any,
    *,
    seed: Optional[int],
) -> ApplyResult:
    """本地校验器裁决 → 施加（**写权恒在本地**）。

    先 :func:`engine.validate` 做前置裁决（白名单 / 硬禁区 / args / pre），通过后再
    :func:`engine.apply_transform` 施加并做不变量聚合（失败即回滚）。两步共用同一
    失败归因短码，供 ``resolution.reason`` 直接引用。
    """
    verdict = validate(state, transform, args, content)
    if not verdict.ok:
        return verdict
    return apply_transform(state, transform, args, content, seed=seed)


# ===========================================================================
# 主入口：route（三级路由）
# ===========================================================================

def _effective_content(content: Any, state: dict) -> dict:
    """把局状态里的 ``scene_items`` / ``held_items`` 注入内容包副本（供 take/give 解析）。

    采用 ``setdefault``：内容包**显式提供**的键优先，否则用局状态派生（内容包可覆盖，
    便于单测）。返回**新 dict**，不改动入参。
    """
    eff = dict(content) if isinstance(content, dict) else {}
    vars_ = state.get("vars")
    vars_ = vars_ if isinstance(vars_, dict) else {}
    eff.setdefault("scene_items", _as_str_list(vars_.get("scene_items")))
    eff.setdefault("held_items", _as_str_list(vars_.get("held_items")))
    return eff


def route(
    text: Any,
    state: Any,
    content: Any = None,
    *,
    allow_propose: bool = True,
    llm_propose: Optional[LLMProposeFn] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    input_kind: str = "free",
    seed: Optional[int] = None,
    pending: Any = None,
) -> Tuple[dict, dict]:
    """三级意图路由主入口（design-v22 §4.2 / §4.3）。

    流程（**写权恒在本地；降级绝不抛**）::

        ① verbatim —— 本地词表/动词解析（free）或选项快照（choice）命中 → 校验 → 施加
           · pre/args 不满足 → ③ narrate（状态不变）
        ② propose  —— 未命中 且 allow_propose 且 LLM 可用 → LLM 只从白名单提议 → 校验器裁决
           · allow_propose=False / LLM 关闭 / 超时 / 畸形 / 抛异常 / 越权 / pre 不满足 → ③ narrate
        ③ narrate  —— 兜底终态：状态不变，只产叙述（mode="narrate"）

    Args:
        text: 玩家输入（``input_kind="free"``）或选项 id（``input_kind="choice"``）。
        state: 局状态（``dict``；**不被就地修改**）。
        content: 已解析内容包（可缺省）。
        allow_propose: 是否允许 ``propose`` 档（``False`` → **绝不调用** ``llm_propose``）。
        llm_propose: 注入的 LLM 提议 callable（``strict_json_prompt -> dict|None``）。
        timeout_s: ``propose`` 超时阈值（秒）；``<=0`` 表示不加线程超时。
        input_kind: ``"free"`` | ``"choice"``（∈ :data:`model.INPUT_KINDS`）。
        seed: 显式随机源 seed（``None`` → 用 ``state["seed"]``；随机键 = ``seed + turn``）。
        pending: 选项快照列表；``None`` → 取 ``state["pending"]``（仅 ``choice`` 用）。

    Returns:
        ``(resolution, new_state)``：
          * ``resolution`` —— **恒为** :func:`engine.build_resolution` 的形状（``dict``），
            键集**恰好等于** :data:`RESOLUTION_REQUIRED_KEYS`
            （``mode/transform/ok/reason/llm_used``）；**不另立 ``Resolution`` dataclass**
            （``model.Resolution`` 是唯一规范形状，避免"两套 Resolution"）。
          * ``new_state`` —— 成功施加时为新状态，任何降级时**恒等于入参 ``state``**
            （``new_state is state``，逐字节不变 —— 「状态与文本分离」红利，reroll 依赖此性质）。

    Raises:
        TavernRouteError: 仅当**入参本身不可用**（``state`` 非 dict / ``input_kind`` 非法）
            ——「路由入参不可用」属调用方编程错误，与「LLM 失败降级不抛」铁律无关。
    """
    if not isinstance(state, dict):
        raise TavernRouteError("酒馆状态不可用，无法路由", reason="bad_args:state_not_dict")
    if input_kind not in INPUT_KINDS:
        raise TavernRouteError("未知的输入种类", reason=f"bad_args:input_kind:{input_kind}")

    eff = _effective_content(content, state)

    # ---- ① 选项点击：自带受控结构，走与 verbatim **同一套**施加路径 ----
    if input_kind == "choice":
        snapshots = pending if pending is not None else state.get("pending")
        resolved = resolve_choice(text, snapshots)
        if resolved is None:
            return _narrate(state, reason=REASON_UNKNOWN_CHOICE), state
        transform, args = resolved
        result = _decide_and_apply(state, transform, args, eff, seed=seed)
        if result.ok:
            return build_resolution(result, mode="verbatim", llm_used=False), result.state
        return _narrate(state, reason=result.reason, transform=transform), state

    # ---- ① 自由输入：本地词表 / 动词解析 ----
    resolved_free = resolve_verbatim(text, eff)
    if resolved_free is not None:
        transform, args = resolved_free
        result = _decide_and_apply(state, transform, args, eff, seed=seed)
        if result.ok:
            return build_resolution(result, mode="verbatim", llm_used=False), result.state
        # 命中但 pre/args 不满足 → 降级 ③（design §4.2：前置不满足 → 降级到 ③）
        return _narrate(state, reason=result.reason, transform=transform), state

    # ---- ② propose：LLM 只提议，写权在校验器 ----
    if not allow_propose:
        # 关闭 propose：**绝不调用** llm_propose（可断言）；与「LLM 关闭」同一出口。
        return _narrate(state, reason=REASON_LLM_DISABLED), state

    prompt = build_strict_json_prompt(state, eff)
    ok, raw, fail_reason = _invoke_propose(llm_propose, prompt, timeout_s)
    if not ok:
        # LLM 关闭 / 超时 / 抛异常 —— 同一条降级路径
        return _narrate(state, reason=fail_reason, llm_used=True), state

    proposal, parse_reason = _normalize_proposal(raw)
    if proposal is None:
        return _narrate(state, reason=parse_reason, llm_used=True), state

    transform = proposal["transform"]
    args = proposal["args"]
    result = _decide_and_apply(state, transform, args, eff, seed=seed)
    if result.ok:
        return build_resolution(result, mode="propose", llm_used=True), result.state
    # 越白名单 / 硬禁区 / args 非法 / pre 不满足 / 不变量违反 → ③ narrate（可归因）
    return _narrate(state, reason=result.reason, transform=transform, llm_used=True), state
