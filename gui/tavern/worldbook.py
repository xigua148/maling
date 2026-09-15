"""gui/tavern/worldbook.py —— 酒馆功能域 · 世界书（V22-04，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.1  世界书条目字段（**18 字段**，见 :data:`gui.tavern.model.WORLDBOOK_ENTRY_FIELDS`）；
    - §4.3  ``WorldBook`` 接口签名（``__init__`` / ``match`` / ``select_within_budget``）；
    - §5.4-14 「内容包加载校验」：**脏正则丢弃 / 违规条目禁用 / ``constant`` 超额裁剪**；
    - D-V22-09 世界书决策：关键词触发 + 四种 selective logic + **字符预算（非 token，近似）**
      + 淘汰顺序 ``weight↓ → order↓ → uid↑`` + 递归上限（默认 2，带 visited 集合）
      + 落点仅三种 ``system_head`` / ``system_tail`` / ``history_depth``。

机制来源：``docs/research-tavern-game.md`` §2.2（SillyTavern World Info）与 §3.2-⑥（lorebook
authoring）。**本模块不做 RAG / 向量 / embedding / 网络** —— 只做「关键词 + 子串命中」
与「字符预算裁剪」，复杂度压在**条目撰写规范**与**预算裁剪**上（调研结论）。

设计取舍（诚实标注，见回传「与设计不符之处 / 不确定点」）：
    * **确定性优先**：所有触发判定为**纯函数**、不读墙钟、不依赖全局 ``random``。
      条目 ``probability`` 只有在**显式注入** ``rng`` 时才生效（``rng=None`` → 概率不参与
      判定），以保证单测可复现（对齐 design-v22 D-V22-07「显式 seed」精神）。
      同理，``sticky`` / ``cooldown`` 只有在**显式注入** ``turn`` + ``ledger``（跨拍激活账本）
      时才生效；两者都不注入 = 与旧行为逐字节一致。账本由调用方持有（本模块每拍被重建，
      无自持状态），``collect`` **就地更新**账本、只记「本拍由关键词新激活且真的入选」的条目。
    * **primary / secondary 与 selective logic 的判定口径**（对公开规范的最小化实现）：
        - ``primary_hit`` = 任一次关键词在扫描窗口内命中（无主键 → 不命中）；
        - 无 ``secondary_keys`` → selective logic 不参与，命中即激活；
        - ``AND_ANY`` = 主键命中 且 至少 1 个次键命中；
        - ``AND_ALL`` = 主键命中 且 **全部**次键命中；
        - ``NOT_ALL`` = 主键命中 且 **非全部**次键命中（含 0 个）；
        - ``NOT_ANY`` = 主键命中 且 **0 个**次键命中。
    * **预算口径**：``budget_chars`` 对**本次选中的全部条目**（含 ``constant``）生效；
      ``max_entries`` 只对**非 constant**（即关键词触发）条目计数。``constant`` 排序优先，
      故不会被预算淘汰（``constant`` 上限 5 × 单条 200 = 1000 < 默认 1600）。
    * **单条超长**：``content`` 超过 :data:`LORE_MAX_CONTENT_CHARS` **截断**（非丢弃），并留痕；
      ``constant`` 超过 :data:`CONSTANT_ENTRY_LIMIT` **加载时禁用**（非丢弃），并留痕。

硬约束：
    * 仅依赖标准库（``json`` / ``re`` / ``logging`` / ``dataclasses`` / ``pathlib`` / ``typing``）
      + 本包内的 ``.model`` / ``.errors``；**零 Qt**（无 PySide6 环境下 ``import`` 必须成功）。
    * 条目级脏数据（字段缺失 / 类型错 / 超长 / 空键 / 重复 uid / 未知字段 / 脏正则）
      **逐级降级或丢弃，绝不抛到调用方**；文件级损坏以 ``TavernContentError`` 受控上报。
    * 不新增任何第三方运行时依赖；不做向量 / embedding / 网络。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import TavernContentError
from .model import (
    CONSTANT_ENTRY_LIMIT,
    LORE_MAX_CONTENT_CHARS,
    LORE_POSITIONS,
    SELECTIVE_LOGIC_MODES,
    SETTING_DEFAULTS,
    WORLDBOOK_ENTRY_FIELDS,
    default_worldbook_entry,
)

logger = logging.getLogger("maling.tavern.worldbook")

__all__ = [
    # —— 常量：默认值与留痕级别 ——
    "DEFAULT_SELECTIVE_LOGIC",
    "DEFAULT_POSITION",
    "DEFAULT_WEIGHT",
    "DEFAULT_ORDER",
    "DEFAULT_UID",
    "DEFAULT_BUDGET_CHARS",
    "DEFAULT_SCAN_DEPTH",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_RECURSIVE_MAX_DEPTH",
    "LEVEL_DROPPED",
    "LEVEL_DISABLED",
    "LEVEL_TRUNCATED",
    "LEVEL_DEGRADED",
    "LEVEL_UNKNOWN",
    "LEVEL_ERROR",
    # —— 数据结构 ——
    "Matcher",
    "WorldbookIssue",
    "LoadResult",
    "WorldbookSelection",
    # —— 纯函数 / 加载器 ——
    "normalize_entry",
    "load_entries",
    "load_book",
    "load_book_file",
    "content_dir",
    "load_builtin_book",
    "load_content",
    "entry_activates",
    # —— 主类 ——
    "WorldBook",
]


# ===========================================================================
# 常量
# ===========================================================================

#: selective logic 非法时的回落值（对齐 ``default_worldbook_entry``）。
DEFAULT_SELECTIVE_LOGIC: str = "AND_ANY"

#: ``position`` 非法时的回落落点。
DEFAULT_POSITION: str = "system_tail"

#: ``weight`` / ``order`` / ``uid`` 缺省值。
DEFAULT_WEIGHT: int = 100
DEFAULT_ORDER: int = 100
DEFAULT_UID: int = 0

#: 预算 / 扫描 / 条数 / 递归默认值（**单一来源 = model.SETTING_DEFAULTS**，不复制字面量）。
DEFAULT_BUDGET_CHARS: int = SETTING_DEFAULTS["worldbook_budget_chars"]
DEFAULT_SCAN_DEPTH: int = SETTING_DEFAULTS["worldbook_scan_depth"]
DEFAULT_MAX_ENTRIES: int = SETTING_DEFAULTS["max_lore_entries_per_turn"]
DEFAULT_RECURSIVE_MAX_DEPTH: int = SETTING_DEFAULTS["recursive_max_depth"]

#: 留痕级别（``WorldbookIssue.level``）。
LEVEL_DROPPED: str = "dropped"          # 整条丢弃（非对象 / 重复 uid / entries 非列表）
LEVEL_DISABLED: str = "disabled"        # 保留但禁用（空键 / 空内容 / constant 超限）
LEVEL_TRUNCATED: str = "truncated"      # 内容超长被截断
LEVEL_DEGRADED: str = "degraded"        # 单字段类型错 → 回落默认
LEVEL_UNKNOWN: str = "unknown_field"    # 未知字段（保留，前向兼容）
LEVEL_ERROR: str = "error"              # 文件级错误（读不到 / JSON 坏）

#: 正则键标志表（``/pattern/flags``）。
_REGEX_FLAG_MAP: Dict[str, int] = {
    "i": re.IGNORECASE,
    "m": re.MULTILINE,
    "s": re.DOTALL,
    "x": re.VERBOSE,
}


# ===========================================================================
# 数据结构（全部 frozen，纯数据）
# ===========================================================================

@dataclass(frozen=True)
class Matcher:
    """一个已编译的关键词匹配器。

    Attributes:
        kind: ``"sub"`` 子串匹配 / ``"re"`` 正则匹配。
        text: ``kind=="sub"`` 时的比较串（非大小写敏感时已预小写）。
        pattern: ``kind=="re"`` 时已编译的正则；否则为 ``None``。
    """

    kind: str
    text: str = ""
    pattern: Optional[re.Pattern] = None


@dataclass(frozen=True)
class WorldbookIssue:
    """单条加载 / 校验留痕（供内容包编辑器与调试面展示）。

    Attributes:
        level: 见 ``LEVEL_*`` 常量。
        uid: 相关条目 uid；无法定位时为 ``-1``。
        field: 相关字段名（``"<entry>"`` / ``"<file>"`` 为整体级）。
        detail: 中文可读说明。
    """

    level: str
    uid: int
    field: str
    detail: str


@dataclass(frozen=True)
class LoadResult:
    """一次内容包加载的结果（**从不抛**，除文件级 ``strict=True`` 场景）。

    Attributes:
        entries: 规范化后的条目列表（18 字段齐全 + 保留的未知字段）。
        issues: 全部留痕。
        ok: 文件级是否成功（读不到 / 坏 JSON → ``False``；条目级问题仍为 ``True``）。
        dropped: 被丢弃的条目数。
        disabled: 被禁用的条目数。
    """

    entries: List[dict]
    issues: List[WorldbookIssue] = field(default_factory=list)
    ok: bool = True
    dropped: int = 0
    disabled: int = 0


@dataclass(frozen=True)
class WorldbookSelection:
    """一回合世界书选中的结果（供批 2 的 prompt 组装消费）。

    Attributes:
        entries: 最终入选条目（**已过预算与条数裁剪**），顺序 = 优先级降序。
        by_position: 按 :data:`gui.tavern.model.LORE_POSITIONS` 三种落点分类（三种键恒在）。
        used_chars: 入选条目 ``content`` 字符总数（近似，**非 token**）。
        depth_reached: 递归实际展开深度（``0`` = 未发生递归）。
        trimmed: 因预算 / 条数被裁掉的条数。
        issues: 构造本 WorldBook 时携带的加载留痕（只读透传）。
    """

    entries: List[dict]
    by_position: Dict[str, List[dict]]
    used_chars: int
    depth_reached: int
    trimmed: int
    issues: List[WorldbookIssue] = field(default_factory=list)


# ===========================================================================
# 类型守卫小工具（本地副本，避免耦合 model 私有名）
# ===========================================================================

def _as_int(value: Any, default: Optional[int]) -> Optional[int]:
    """``int`` 守卫：``bool`` 不算 ``int``；非法回 ``default``（可为 ``None``）。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    """``bool`` 守卫：接受 ``bool`` 与 ``0/1`` 整数。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return default


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list 或含非 str 项时丢该项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


# ===========================================================================
# 正则键解析与匹配器构建
# ===========================================================================

def _parse_regex_key(key: str) -> Optional[Tuple[str, int]]:
    """把 ``/pattern/flags`` 形态的键解析为 ``(pattern, flags)``；纯文本键返回 ``None``。

    Raises:
        re.error: 出现未知正则标志时（调用方 ``try`` 后丢弃该键）。
    """
    if len(key) < 2 or not key.startswith("/"):
        return None
    last = key.rfind("/")
    if last <= 0:  # 无闭合斜杠（如 "/abc"）→ 视为纯文本键
        return None
    pattern = key[1:last]
    if not pattern:  # "//" 之类 → 视为纯文本键
        return None
    flags = 0
    for ch in key[last + 1:]:
        if ch not in _REGEX_FLAG_MAP:
            raise re.error(f"未知正则标志: {ch!r}")
        flags |= _REGEX_FLAG_MAP[ch]
    # 括号预编译校验（惰性抛 re.error，由调用方捕获）
    re.compile(pattern, flags)
    return pattern, flags


def _build_matchers(keys: Any, *, case_sensitive: bool) -> List[Matcher]:
    """把一组键编译为 :class:`Matcher` 列表；**非法正则逐条丢弃并日志**（绝不抛）。"""
    matchers: List[Matcher] = []
    for key in _as_str_list(keys):
        if not key:
            continue
        try:
            parsed = _parse_regex_key(key)
        except re.error:
            logger.debug("世界书正则键解析失败，丢弃该键: %r", key, exc_info=True)
            continue
        if parsed is not None:
            pattern, flags = parsed
            if not case_sensitive:
                flags |= re.IGNORECASE
            try:
                matchers.append(Matcher(kind="re", pattern=re.compile(pattern, flags)))
            except re.error:
                logger.debug("世界书正则键编译失败，丢弃该键: %r", key, exc_info=True)
                continue
        else:
            matchers.append(Matcher(kind="sub", text=key if case_sensitive else key.lower()))
    return matchers


def _matcher_hits(matcher: Matcher, text: str, case_sensitive: bool) -> bool:
    """单个匹配器是否命中给定文本。"""
    if matcher.kind == "sub":
        hay = text if case_sensitive else text.lower()
        return matcher.text in hay
    if matcher.pattern is None:
        return False
    return matcher.pattern.search(text) is not None


def _matches_any(matchers: List[Matcher], texts: List[str], case_sensitive: bool) -> bool:
    """任一匹配器命中任一文本即真。"""
    for matcher in matchers:
        for text in texts:
            if _matcher_hits(matcher, text, case_sensitive):
                return True
    return False


def _count_hits(matchers: List[Matcher], texts: List[str], case_sensitive: bool) -> int:
    """命中任一文本的**匹配器个数**（用于 ``AND_ALL`` / ``NOT_*`` 组合判定）。"""
    hits = 0
    for matcher in matchers:
        if any(_matcher_hits(matcher, text, case_sensitive) for text in texts):
            hits += 1
    return hits


def _activates(
    primary: List[Matcher],
    secondary: List[Matcher],
    entry: dict,
    texts: List[str],
) -> bool:
    """按主键 + 次键 + selective logic 判定单条是否激活（纯函数）。"""
    window = [t for t in texts if isinstance(t, str) and t]
    if not window:
        return False
    case_sensitive = bool(entry.get("case_sensitive", False))
    if not _matches_any(primary, window, case_sensitive):
        return False
    if not secondary:
        return True
    hits = _count_hits(secondary, window, case_sensitive)
    logic = entry.get("selective_logic", DEFAULT_SELECTIVE_LOGIC)
    if logic == "AND_ANY":
        return hits >= 1
    if logic == "AND_ALL":
        return hits >= len(secondary)
    if logic == "NOT_ALL":
        return hits < len(secondary)
    if logic == "NOT_ANY":
        return hits == 0
    return hits >= 1


def _probability_ok(entry: dict, rng: Any) -> bool:
    """``probability`` 判定；``rng=None``（默认）→ 概率不参与，恒真（确定性）。"""
    prob = _as_int(entry.get("probability"), 100)
    if prob is None or prob >= 100:
        return True
    if prob <= 0:
        return False
    if rng is None:
        return True
    try:
        return rng.randint(1, 100) <= prob
    except Exception:  # pragma: no cover - 注入 rng 异常时按命中处理，绝不崩
        logger.debug("probability 抽取失败，按命中处理", exc_info=True)
        return True


def _sort_key(entry: dict) -> Tuple[int, int, int]:
    """排序键：``weight`` 降序 → ``order`` 降序 → ``uid`` 升序（D-V22-09 淘汰顺序）。"""
    return (
        -(_as_int(entry.get("weight"), DEFAULT_WEIGHT) or 0),
        -(_as_int(entry.get("order"), DEFAULT_ORDER) or 0),
        _as_int(entry.get("uid"), DEFAULT_UID) or 0,
    )


def _turns_since(last: Any, turn: Any) -> Optional[int]:
    """``turn - last`` 的整数差；任一侧不可用（非 int / ``turn is None``）→ ``None``。

    ``None`` = **sticky / cooldown 不参与判定**（与 ``rng=None`` 时 ``probability`` 不参与
    同一口径：调用方不提供「第几拍」，机制就保持确定性沉默，而不是凭空生效）。
    """
    if not isinstance(turn, int) or isinstance(turn, bool):
        return None
    if not isinstance(last, int) or isinstance(last, bool):
        return None
    return turn - last


def _sticky_active(entry: dict, turn: Any, ledger: Any) -> bool:
    """``sticky``：条目被激活后**再保持** ``sticky`` 拍（期间不要求关键词命中）。

    口径：``0 < turn - 上次激活拍 <= sticky``。账本缺失 / 无 ``turn`` → ``False``（不生效）。
    """
    sticky = _as_int(entry.get("sticky"), 0) or 0
    if sticky <= 0 or not isinstance(ledger, dict):
        return False
    delta = _turns_since(ledger.get(entry.get("uid")), turn)
    return delta is not None and 0 < delta <= sticky


def _on_cooldown(entry: dict, turn: Any, ledger: Any) -> bool:
    """``cooldown``：条目被激活后 ``cooldown`` 拍内**不再激活**。

    口径：``0 < turn - 上次激活拍 <= cooldown`` → 抑制。账本缺失 / 无 ``turn`` → ``False``。
    """
    cooldown = _as_int(entry.get("cooldown"), 0) or 0
    if cooldown <= 0 or not isinstance(ledger, dict):
        return False
    delta = _turns_since(ledger.get(entry.get("uid")), turn)
    return delta is not None and 0 < delta <= cooldown


def _content_len(entry: dict) -> int:
    """条目 ``content`` 的字符数（**近似预算，非 token**）。"""
    content = entry.get("content")
    return len(content) if isinstance(content, str) else 0


def entry_activates(entry: Any, texts: Any) -> bool:
    """单条条目的激活判定（公开纯函数；供测试与批 2 复用）。

    ``constant`` 条目恒激活；其余按主键 + 次键 + selective logic 判定。
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("constant"):
        return True
    case_sensitive = bool(entry.get("case_sensitive", False))
    primary = _build_matchers(entry.get("keys") or [], case_sensitive=case_sensitive)
    secondary = _build_matchers(entry.get("secondary_keys") or [], case_sensitive=case_sensitive)
    window = [t for t in (texts or []) if isinstance(t, str)]
    return _activates(primary, secondary, entry, window)


# ===========================================================================
# 条目规范化（字段级降级，**绝不抛**）
# ===========================================================================

def normalize_entry(raw: Any, *, index: int = 0) -> Tuple[Optional[dict], List[WorldbookIssue]]:
    """把一条原始记录规范化为 18 字段条目（**逐级降级 / 丢弃**，绝不抛）。

    规则（对齐 design-v22 §5.4-14 与 model 的「类型守卫 + 未知字段不销毁」精神）：
        * 非 dict → 丢弃（``LEVEL_DROPPED``）；
        * 单字段类型错 → 回落该字段默认（``LEVEL_DEGRADED``）；
        * ``content`` 超 :data:`LORE_MAX_CONTENT_CHARS` → 截断（``LEVEL_TRUNCATED``）；
        * 非法 ``selective_logic`` / ``position`` → 回落默认（``LEVEL_DEGRADED``）；
        * ``content`` 空 或 非 ``constant`` 且无主键 → 禁用（``LEVEL_DISABLED``）；
        * 未知字段 → **保留**（``LEVEL_UNKNOWN``，前向兼容）。

    Args:
        raw: 原始记录（任意类型）。
        index: 在 entries 列表中的序号（仅用于留痕文案）。

    Returns:
        ``(entry, issues)``；``entry`` 为 ``None`` 表示整条已丢弃。
    """
    issues: List[WorldbookIssue] = []
    if not isinstance(raw, dict):
        issues.append(WorldbookIssue(LEVEL_DROPPED, -1, "<entry>", f"第 {index} 个条目不是对象，已丢弃"))
        return None, issues

    entry = default_worldbook_entry()

    # uid ------------------------------------------------------------------
    raw_uid = raw.get("uid")
    uid = _as_int(raw_uid, DEFAULT_UID)
    if uid is None or uid < 0:
        uid = DEFAULT_UID
    if not isinstance(raw_uid, int) or isinstance(raw_uid, bool):
        issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "uid", "uid 缺失或类型非法，回落默认"))
    entry["uid"] = uid

    # title ----------------------------------------------------------------
    if isinstance(raw.get("title"), str):
        entry["title"] = raw["title"]
    elif raw.get("title") is not None:
        issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "title", "title 类型非法，回落空串"))

    # keys / secondary_keys ------------------------------------------------
    raw_keys = raw.get("keys")
    if raw_keys is not None and not isinstance(raw_keys, (list, tuple)):
        issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "keys", "keys 非列表，仅保留字符串项"))
    entry["keys"] = _as_str_list(raw_keys)

    raw_sec = raw.get("secondary_keys")
    if raw_sec is not None and not isinstance(raw_sec, (list, tuple)):
        issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "secondary_keys", "secondary_keys 非列表，仅保留字符串项"))
    entry["secondary_keys"] = _as_str_list(raw_sec)

    # selective_logic ------------------------------------------------------
    logic = raw.get("selective_logic")
    if logic in SELECTIVE_LOGIC_MODES:
        entry["selective_logic"] = logic
    else:
        if logic is not None:
            issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "selective_logic", f"未知 selective logic {logic!r}，回落 {DEFAULT_SELECTIVE_LOGIC}"))
        entry["selective_logic"] = DEFAULT_SELECTIVE_LOGIC

    # content（超长截断）--------------------------------------------------
    content = raw.get("content")
    if isinstance(content, str):
        if len(content) > LORE_MAX_CONTENT_CHARS:
            content = content[:LORE_MAX_CONTENT_CHARS]
            issues.append(WorldbookIssue(LEVEL_TRUNCATED, uid, "content", f"content 超 {LORE_MAX_CONTENT_CHARS} 字，已截断"))
        entry["content"] = content
    else:
        if content is not None:
            issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "content", "content 非字符串，回落空串"))
        entry["content"] = ""

    # position -------------------------------------------------------------
    position = raw.get("position")
    if position in LORE_POSITIONS:
        entry["position"] = position
    else:
        if position is not None:
            issues.append(WorldbookIssue(LEVEL_DEGRADED, uid, "position", f"未知落点 {position!r}，回落 {DEFAULT_POSITION}"))
        entry["position"] = DEFAULT_POSITION

    # 数值字段（**保留合法的 0**，只在非法/缺失时回落默认）------------------
    depth = _as_int(raw.get("depth"), 0)
    entry["depth"] = max(0, depth if depth is not None else 0)
    order = _as_int(raw.get("order"), DEFAULT_ORDER)
    entry["order"] = DEFAULT_ORDER if order is None else order
    weight = _as_int(raw.get("weight"), DEFAULT_WEIGHT)
    entry["weight"] = DEFAULT_WEIGHT if weight is None else weight
    sticky = _as_int(raw.get("sticky"), 0)
    cooldown = _as_int(raw.get("cooldown"), 0)
    entry["sticky"] = max(0, sticky if sticky is not None else 0)
    entry["cooldown"] = max(0, cooldown if cooldown is not None else 0)

    # 布尔字段 -------------------------------------------------------------
    entry["constant"] = _as_bool(raw.get("constant"), False)
    entry["recursive"] = _as_bool(raw.get("recursive"), False)
    entry["case_sensitive"] = _as_bool(raw.get("case_sensitive"), False)
    entry["enabled"] = _as_bool(raw.get("enabled"), True)

    # probability（夹取 0..100）-------------------------------------------
    prob = _as_int(raw.get("probability"), 100)
    if prob is None:
        prob = 100
    entry["probability"] = max(0, min(100, prob))

    # budget_chars_est（缺失 / 非法 → 由 content 长度推算）----------------
    est = _as_int(raw.get("budget_chars_est"), None)
    if est is None or est < 0:
        est = len(entry["content"])
    entry["budget_chars_est"] = est

    # 空内容 / 空主键 → 禁用（保留条目但不参与触发）------------------------
    if not entry["content"]:
        entry["enabled"] = False
        issues.append(WorldbookIssue(LEVEL_DISABLED, uid, "content", "content 为空，条目禁用"))
    elif not entry["constant"] and not entry["keys"]:
        entry["enabled"] = False
        issues.append(WorldbookIssue(LEVEL_DISABLED, uid, "keys", "非 constant 条目无主键，永久禁用"))

    # 未知字段保留（前向兼容）---------------------------------------------
    for key, value in raw.items():
        if key not in WORLDBOOK_ENTRY_FIELDS:
            entry[key] = value
            issues.append(WorldbookIssue(LEVEL_UNKNOWN, uid, str(key), "未知字段保留（前向兼容）"))

    return entry, issues


# ===========================================================================
# 加载器（entries / book / file / builtin）
# ===========================================================================

def load_entries(raw_entries: Any, *, source: str = "") -> LoadResult:
    """加载一组条目：规范化 + **重复 uid 处理** + ``constant`` 上限裁剪（**绝不抛**）。

    Args:
        raw_entries: 原始条目序列（非列表 → 按空书加载并留痕）。
        source: 来源标识（文件路径等，仅用于留痕文案）。

    Returns:
        :class:`LoadResult`；``ok`` 恒为 ``True``（条目级问题不视为加载失败）。
    """
    issues: List[WorldbookIssue] = []
    if not isinstance(raw_entries, (list, tuple)):
        issues.append(WorldbookIssue(LEVEL_DROPPED, -1, "entries", f"entries 不是列表（{source}），按空书加载"))
        return LoadResult(entries=[], issues=issues, ok=True)

    out: List[dict] = []
    seen_uids: set = set()
    constant_count = 0
    for index, raw in enumerate(raw_entries):
        entry, entry_issues = normalize_entry(raw, index=index)
        issues.extend(entry_issues)
        if entry is None:
            continue
        uid = entry["uid"]
        if uid > 0:
            if uid in seen_uids:
                issues.append(WorldbookIssue(LEVEL_DROPPED, uid, "uid", "uid 重复，丢弃后续重复条目"))
                continue
            seen_uids.add(uid)
        if entry["constant"] and entry["enabled"]:
            if constant_count >= CONSTANT_ENTRY_LIMIT:
                entry["enabled"] = False
                issues.append(WorldbookIssue(LEVEL_DISABLED, uid, "constant", f"constant 条目超过上限 {CONSTANT_ENTRY_LIMIT}，加载时禁用"))
            else:
                constant_count += 1
        out.append(entry)

    dropped = sum(1 for item in issues if item.level == LEVEL_DROPPED)
    disabled = sum(1 for item in issues if item.level == LEVEL_DISABLED)
    return LoadResult(entries=out, issues=issues, ok=True, dropped=dropped, disabled=disabled)


def load_book(data: Any, *, source: str = "") -> LoadResult:
    """从已解析的 ``book.json`` 结构（dict）或裸 entries 列表加载。"""
    if isinstance(data, dict):
        raw_entries = data.get("entries")
    else:
        raw_entries = data
    return load_entries(raw_entries, source=source)


def load_book_file(path: Any, *, strict: bool = False) -> LoadResult:
    """从磁盘读取 ``book.json`` 并加载。

    Args:
        path: 文件路径（``str`` / ``Path``）。
        strict: ``True`` 时文件级错误（读不到 / JSON 坏）**抛出**
            :class:`~gui.tavern.errors.TavernContentError`；``False``（默认）时返回
            ``ok=False`` 的空结果（**条目级问题无论如何都不抛**）。

    Returns:
        :class:`LoadResult`。

    Raises:
        TavernContentError: 仅当 ``strict=True`` 且文件级读取失败。
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        logger.debug("世界书文件读取失败: %s", p, exc_info=True)
        if strict:
            raise TavernContentError("内容包不可用", reason="content_unreadable", source=str(p)) from exc
        return LoadResult(
            entries=[],
            issues=[WorldbookIssue(LEVEL_ERROR, -1, "<file>", f"内容包读取失败: {p.name}")],
            ok=False,
        )
    return load_book(data, source=str(p))


def content_dir() -> Path:
    """内容包根目录。

    懒 import ``gui.utils.get_resource_path``（**唯一路径口径**，且不在本模块 import 期
    触发任何 Qt 导入）：
        * 源码态 → ``<repo>/gui/tavern/content``；
        * frozen 态 → ``<_MEIPASS>/tavern/content``（spec ``datas`` 的 target 须为
          ``tavern/content``，见 design-v22 §1.4 校正② / §3.2 附注）。
    """
    from gui.utils import get_resource_path  # 懒 import：保证本模块 import 期零 Qt

    return get_resource_path("tavern/content")


def load_builtin_book(book_id: str = "lantern", *, strict: bool = False) -> LoadResult:
    """加载随包内容包 ``content/<book_id>/book.json``。"""
    return load_book_file(content_dir() / book_id / "book.json", strict=strict)


# ===========================================================================
# 内容包 → engine/router 读取键契约（design-v22 §4.2「内容包 ↔ engine 读取键契约」）
# ===========================================================================
#
# 三个文件解析合并为一个 ``content: dict``（engine/router **只消费 dict、不解析文件**）。
# 落点（唯一解析入口 = :func:`load_content`）：
#   * ``book.json``       → 世界书条目（供 :func:`load_book` 建 :class:`WorldBook`）
#   * ``chapters.json``   → 章节/节点 + 按 scene 分组的动作面（reachable/known_topics/menu）
#                           + 扁平 open_conditions + 全局 openable + 可选 labels（机器名→中文名）
#   * ``transforms.json`` → var_names（var 名校验） + quick_actions（UI 用）
#
# 冻结键（§4.2，**全部可缺省**；缺省 = fail-closed，见各键语义）：
#   node_ids / scene_ids（全局，I2 用；别名 nodes/scenes）、
#   reachable / known_topics / menu（**按 scene 分组** dict）、
#   open_conditions（**扁平** dict，键 ``"<scene>:<key>"`` 优先、回退 ``"<key>"``）、
#   openable（全局 list，可选）、var_names（全局 list，**只能追加声明**）。
#
# 附加键（§4.2「保留附加键」；**engine 不读**，供 prompt / UI）：
#   worldbook / chapters / quick_actions / labels（机器名 → 中文名，可选）。
#
# 派生根（本模块实现，规则明确、可测）：
#   * ``node_ids`` 缺省 → 由 ``chapters[].nodes[].id`` 顺序去重推导；
#   * ``scene_ids`` 缺省 → 由 ``reachable`` / ``known_topics`` / ``menu`` 的键 ∪
#     ``open_conditions`` 中 ``"<scene>:..."`` 的 scene 部分推导，**过滤空串**。

#: 内容包三文件（顺序即解析顺序）。
CONTENT_FILES: Tuple[str, ...] = ("book.json", "chapters.json", "transforms.json")

#: ``effects.field`` 的三个推进字段白名单（engine.ALLOWED_EFFECT_FIELDS 只读镜像，供内容包自检/UI）。
CONTENT_EFFECT_FIELDS: Tuple[str, ...] = ("scene_id", "node_id", "turn", "transcript")


def _read_json(path: Path) -> Any:
    """读 JSON 文件；失败返回 ``None``（**不抛**，仅 ``logger.debug`` 留痕）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("内容包文件不存在: %s", path)
        return None
    except (OSError, ValueError):
        logger.debug("内容包文件读取失败: %s", path, exc_info=True)
        return None


def _dedupe_names(values: Any) -> List[str]:
    """收敛为去重后的 ``list[str]``（丢非 str / 空串，保持出现顺序）。"""
    out: List[str] = []
    for item in _as_str_list(values):
        if item and item not in out:
            out.append(item)
    return out


def _scene_map(value: Any) -> Dict[str, List[str]]:
    """收敛为 ``{scene_id: [str,...]}``（非 dict / 非 list 项安全丢弃）。"""
    out: Dict[str, List[str]] = {}
    if isinstance(value, dict):
        for scene, items in value.items():
            if isinstance(scene, str):
                out[scene] = _dedupe_names(items)
    return out


def _bool_map(value: Any) -> Dict[str, bool]:
    """收敛为 ``{key: bool}``（用于扁平的 ``open_conditions``）。"""
    out: Dict[str, bool] = {}
    if isinstance(value, dict):
        for key, flag in value.items():
            if isinstance(key, str):
                out[key] = bool(flag)
    return out


def _str_map(value: Any) -> Dict[str, str]:
    """收敛为 ``{machine_name: 中文名}``（可选附加键 ``labels``；非 str 项丢弃）。

    供 ``prompt`` / ``summarize`` 把机器名翻成人类可读中文（见 ``gui.tavern.labels``）；
    **engine 不读**，与 ``worldbook`` / ``chapters`` / ``quick_actions`` 同属"保留附加键"。
    """
    out: Dict[str, str] = {}
    if isinstance(value, dict):
        for key, label in value.items():
            if isinstance(key, str) and key and isinstance(label, str) and label.strip():
                out[key] = label.strip()
    return out


def _derive_ids(chapters: Any) -> Tuple[List[str], List[str]]:
    """从 ``chapters.json`` 推导 ``(node_ids, scene_ids)``（缺省键时的兜底）。"""
    node_ids: List[str] = []
    scene_ids: List[str] = []
    if not isinstance(chapters, dict):
        return node_ids, scene_ids
    for chapter in chapters.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        for node in chapter.get("nodes") or []:
            if isinstance(node, dict):
                node_id = node.get("id")
                if isinstance(node_id, str) and node_id and node_id not in node_ids:
                    node_ids.append(node_id)
    for key in ("reachable", "known_topics", "menu"):
        mapping = chapters.get(key)
        if isinstance(mapping, dict):
            for scene in mapping:
                if isinstance(scene, str) and scene and scene not in scene_ids:
                    scene_ids.append(scene)
    conditions = chapters.get("open_conditions")
    if isinstance(conditions, dict):
        for compound in conditions:
            if isinstance(compound, str) and ":" in compound:
                scene = compound.split(":", 1)[0]
                if scene and scene not in scene_ids:
                    scene_ids.append(scene)
    return node_ids, scene_ids


def _empty_content(pack_id: str) -> dict:
    """空内容包（**全部冻结键齐备**，缺省即安全：动作面为空 → 全部动作不可用）。"""
    return {
        "book_id": pack_id,
        "node_ids": [],
        "scene_ids": [],
        "reachable": {},
        "known_topics": {},
        "menu": {},
        "open_conditions": {},
        "openable": [],
        "var_names": [],
        # engine 不读、供 prompt/UI 复用的附加键（命名隔离，避免与 nodes/scenes 别名冲突）
        "worldbook": {},
        "chapters": [],
        "quick_actions": [],
        # 机器名 → 中文名（可选；prompt/summarize 用，engine 不读）
        "labels": {},
    }


def _merge_content(pack_id: str, book: Any, chapters: Any, transforms: Any) -> dict:
    """把三文件解析结果合并为冻结键形状的 ``content: dict``（engine/router 消费）。"""
    book_d = book if isinstance(book, dict) else {}
    chapters_d = chapters if isinstance(chapters, dict) else {}
    transforms_d = transforms if isinstance(transforms, dict) else {}

    derived_nodes, derived_scenes = _derive_ids(chapters_d)
    node_ids = _dedupe_names(chapters_d.get("node_ids")) or derived_nodes
    scene_ids = _dedupe_names(chapters_d.get("scene_ids")) or derived_scenes
    book_id = book_d.get("book_id")
    if not (isinstance(book_id, str) and book_id):
        book_id = pack_id

    chapters_list = chapters_d.get("chapters")
    quick_actions = transforms_d.get("quick_actions")
    return {
        "book_id": book_id,
        # —— 冻结键（§4.2）——
        "node_ids": node_ids,
        "scene_ids": scene_ids,
        "reachable": _scene_map(chapters_d.get("reachable")),
        "known_topics": _scene_map(chapters_d.get("known_topics")),
        "menu": _scene_map(chapters_d.get("menu")),
        "open_conditions": _bool_map(chapters_d.get("open_conditions")),
        "openable": _dedupe_names(chapters_d.get("openable")),
        "var_names": _dedupe_names(transforms_d.get("var_names")),
        # —— 附加键（engine 不读）——
        "worldbook": book_d,
        "chapters": chapters_list if isinstance(chapters_list, list) else [],
        "quick_actions": quick_actions if isinstance(quick_actions, list) else [],
        # 机器名 → 中文名（可选；prompt/summarize 把机器名翻成人类可读中文用）
        "labels": _str_map(chapters_d.get("labels")),
    }


def load_content(pack_id: str = "lantern", *, strict: bool = False) -> dict:
    """解析内容包三文件 → 冻结的 ``content: dict``（engine/router/prompt 的**唯一**入口）。

    Args:
        pack_id: 内容包目录名（如 ``"lantern"``）。
        strict: ``True`` 时**内容包目录不存在**抛 :class:`TavernContentError`；
            ``False``（默认）返回 :func:`_empty_content`（全部冻结键齐备、动作面为空 →
            fail-closed）。**单文件缺失/坏 JSON 一律降级**（该文件视作空），**不抛**。

    Returns:
        键集见 §4.2 的 ``content`` 契约 + 三个附加键（``worldbook`` / ``chapters`` / ``quick_actions``）。
    """
    base = content_dir() / pack_id
    if not base.is_dir():
        logger.debug("内容包目录不存在: %s", base)
        if strict:
            raise TavernContentError("内容包不可用", reason="pack_missing", source=str(base))
        return _empty_content(pack_id)
    book = _read_json(base / "book.json")
    chapters = _read_json(base / "chapters.json")
    transforms = _read_json(base / "transforms.json")
    return _merge_content(pack_id, book, chapters, transforms)


# ===========================================================================
# WorldBook 主类
# ===========================================================================

class WorldBook:
    """一本书的世界书：关键词触发 + selective logic + 字符预算 + 递归上限。

    构造入参对齐 design-v22 §4.3；预算 / 扫描深度 / 条数 / 递归上限默认取
    :data:`gui.tavern.model.SETTING_DEFAULTS`（调用方通常传 ``tavern.json.settings`` 的值）。

    典型用法（批 2 prompt）：:

        result = load_builtin_book("lantern")
        book = WorldBook.from_result(result, settings=play_settings)
        selection = book.collect(recent_texts)      # → WorldbookSelection
        world_rules = selection.by_position["system_head"]   # constant 世界规则
        turn_context = selection.by_position["system_tail"]  # 本回合命中
        deep = selection.by_position["history_depth"]        # 历史内注入
    """

    def __init__(
        self,
        entries: Any,
        *,
        budget_chars: int = DEFAULT_BUDGET_CHARS,
        scan_depth: int = DEFAULT_SCAN_DEPTH,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        recursive_max_depth: int = DEFAULT_RECURSIVE_MAX_DEPTH,
        issues: Optional[List[WorldbookIssue]] = None,
    ) -> None:
        self.budget_chars: int = max(0, _as_int(budget_chars, DEFAULT_BUDGET_CHARS) or 0)
        self.scan_depth: int = max(0, _as_int(scan_depth, DEFAULT_SCAN_DEPTH) or 0)
        self.max_entries: int = max(0, _as_int(max_entries, DEFAULT_MAX_ENTRIES) or 0)
        self.recursive_max_depth: int = max(0, _as_int(recursive_max_depth, DEFAULT_RECURSIVE_MAX_DEPTH) or 0)
        self.issues: List[WorldbookIssue] = list(issues) if issues else []
        self._entries: List[dict] = self._coerce(entries)
        self._matchers: Tuple[Tuple[List[Matcher], List[Matcher]], ...] = tuple(
            self._compile(entry) for entry in self._entries
        )

    # —— 构造辅助 ——

    @classmethod
    def from_settings(
        cls,
        entries: Any,
        settings: Any,
        *,
        issues: Optional[List[WorldbookIssue]] = None,
    ) -> "WorldBook":
        """从 ``tavern.json.settings`` 读取四个旋钮构造（缺键回落类默认）。"""
        s: dict = settings if isinstance(settings, dict) else {}
        budget = _as_int(s.get("worldbook_budget_chars"), DEFAULT_BUDGET_CHARS)
        scan = _as_int(s.get("worldbook_scan_depth"), DEFAULT_SCAN_DEPTH)
        max_entries = _as_int(s.get("max_lore_entries_per_turn"), DEFAULT_MAX_ENTRIES)
        depth_cap = _as_int(s.get("recursive_max_depth"), DEFAULT_RECURSIVE_MAX_DEPTH)
        return cls(
            entries,
            budget_chars=DEFAULT_BUDGET_CHARS if budget is None else budget,
            scan_depth=DEFAULT_SCAN_DEPTH if scan is None else scan,
            max_entries=DEFAULT_MAX_ENTRIES if max_entries is None else max_entries,
            recursive_max_depth=DEFAULT_RECURSIVE_MAX_DEPTH if depth_cap is None else depth_cap,
            issues=issues,
        )

    @classmethod
    def from_result(cls, result: Any, settings: Any = None, **overrides: Any) -> "WorldBook":
        """从 :class:`LoadResult`（或裸条目列表）构造，并透传加载留痕。"""
        if isinstance(result, LoadResult):
            entries = result.entries
            issues = list(result.issues)
        else:
            entries = result
            issues = []
        if settings is None:
            return cls(entries, issues=issues, **overrides)
        book = cls.from_settings(entries, settings, issues=issues)
        if overrides:
            book = cls(
                book._entries,
                budget_chars=overrides.get("budget_chars", book.budget_chars),
                scan_depth=overrides.get("scan_depth", book.scan_depth),
                max_entries=overrides.get("max_entries", book.max_entries),
                recursive_max_depth=overrides.get("recursive_max_depth", book.recursive_max_depth),
                issues=issues,
            )
        return book

    @property
    def entries(self) -> List[dict]:
        """规范化后的条目列表（**浅拷贝**，元素为原 dict 引用）。"""
        return list(self._entries)

    # —— 内部 ——

    def _coerce(self, entries: Any) -> List[dict]:
        """把入参收敛为「18 字段齐全」的条目列表（静默，不产生留痕）。"""
        out: List[dict] = []
        if not isinstance(entries, (list, tuple)):
            return out
        seen_uids: set = set()
        constant_count = 0
        for index, raw in enumerate(entries):
            entry, _ = normalize_entry(raw, index=index)
            if entry is None:
                continue
            uid = entry["uid"]
            if uid > 0:
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
            if entry["constant"] and entry["enabled"]:
                if constant_count >= CONSTANT_ENTRY_LIMIT:
                    entry["enabled"] = False
                else:
                    constant_count += 1
            out.append(entry)
        return out

    def _compile(self, entry: dict) -> Tuple[List[Matcher], List[Matcher]]:
        case_sensitive = bool(entry.get("case_sensitive", False))
        primary = _build_matchers(entry.get("keys") or [], case_sensitive=case_sensitive)
        secondary = _build_matchers(entry.get("secondary_keys") or [], case_sensitive=case_sensitive)
        return primary, secondary

    def _scan_window(self, recent_texts: Any) -> List[str]:
        """取最近 ``scan_depth`` 条可读文本（入参按时间**升序**，取末 N 条）。"""
        texts = [t for t in (recent_texts or []) if isinstance(t, str) and t]
        if self.scan_depth <= 0:
            return []
        return texts[-self.scan_depth:]

    # —— 公开 API（对齐 §4.3）——

    def match(
        self,
        recent_texts: Any,
        *,
        rng: Any = None,
        turn: Optional[int] = None,
        ledger: Any = None,
        fresh: Any = None,
    ) -> List[dict]:
        """触发命中：``constant`` 恒入 + 关键词命中条目；按 ``weight↓/order↓/uid↑`` 排序。

        **不做预算裁剪**（交给 :meth:`select_within_budget`）；**不做递归**（交给
        :meth:`collect`）。``rng`` 用于 ``probability``（``None`` → 概率不参与）。

        Args:
            recent_texts: 最近若干条文本（按时间**升序**），只扫末 ``scan_depth`` 条。
            rng: 可注入的确定性随机源（实现 ``randint(a, b)``）；``None`` = 确定性模式。
            turn: 当前拍数；``None`` → ``sticky`` / ``cooldown`` **不参与判定**。
            ledger: 激活账本 ``{uid: 上次被关键词激活的拍}``（由调用方跨拍持有）。
            fresh: 可选的 ``set``；命中后把**本次由关键词新激活**的 ``uid`` 写入其中
                （供 :meth:`collect` 记账 —— 靠 ``sticky`` 保活的条目**不算**新激活，
                否则它会自我续期、永不脱落）。

        Returns:
            命中条目列表（dict 引用）。
        """
        window = self._scan_window(recent_texts)
        activated: List[dict] = []
        for index, entry in enumerate(self._entries):
            if not entry.get("enabled", True):
                continue
            if entry.get("constant"):
                activated.append(entry)
                continue
            # sticky：上次关键词激活后仍在保活窗口内 → 不要求关键词命中
            if _sticky_active(entry, turn, ledger):
                activated.append(entry)
                continue
            # cooldown：上次激活太近 → 本拍抑制
            if _on_cooldown(entry, turn, ledger):
                continue
            primary, secondary = self._matchers[index]
            if _activates(primary, secondary, entry, window) and _probability_ok(entry, rng):
                activated.append(entry)
                if isinstance(fresh, set):
                    fresh.add(entry.get("uid"))
        activated.sort(key=_sort_key)
        return activated

    def select_within_budget(self, matched: Any) -> List[dict]:
        """对命中条目做**字符预算 + 条数**裁剪（D-V22-09：``weight↓ → order↓ → uid↑``）。

        * ``constant`` 条目**优先保留**（不占 ``max_entries`` 名额）；
        * 非 ``constant`` 条目按排序累加，超过 ``max_entries`` 或加入后总量超
          ``budget_chars`` 即**截断**（停止继续取）；
        * 保证返回条目 ``content`` 字符总数 ``<= budget_chars``。

        Returns:
            入选条目列表（顺序 = 优先级降序）。
        """
        valid = [entry for entry in (matched or []) if isinstance(entry, dict)]
        constants = sorted((e for e in valid if e.get("constant")), key=_sort_key)
        others = sorted((e for e in valid if not e.get("constant")), key=_sort_key)

        selected: List[dict] = []
        used = 0
        for entry in constants:
            size = _content_len(entry)
            if used + size > self.budget_chars:
                break
            selected.append(entry)
            used += size

        count = 0
        for entry in others:
            if count >= self.max_entries:
                break
            size = _content_len(entry)
            if used + size > self.budget_chars:
                break
            selected.append(entry)
            used += size
            count += 1
        return selected

    def _expand_recursive(
        self,
        base: List[dict],
        *,
        rng: Any = None,
        turn: Optional[int] = None,
        ledger: Any = None,
        fresh: Any = None,
    ) -> Tuple[List[dict], int]:
        """递归扫描：``recursive`` 条目的 ``content`` 再触发其他条目，**深度有上界**。

        ``cooldown`` 同样在递归路径上生效（否则被冷却的条目会从这里绕回来）。

        Returns:
            ``(展开后的条目列表, 实际递归深度)``；深度 ``<= recursive_max_depth``。
        """
        activated = list(base)
        seen = {id(entry) for entry in activated}
        depth_reached = 0
        frontier = [entry for entry in activated if entry.get("recursive") and entry.get("enabled", True)]
        while frontier and depth_reached < self.recursive_max_depth:
            depth_reached += 1
            texts = [entry.get("content") for entry in frontier if isinstance(entry.get("content"), str) and entry.get("content")]
            newly: List[dict] = []
            for index, entry in enumerate(self._entries):
                if entry.get("constant") or not entry.get("enabled", True):
                    continue
                if id(entry) in seen:
                    continue
                if _on_cooldown(entry, turn, ledger):
                    continue
                primary, secondary = self._matchers[index]
                if _activates(primary, secondary, entry, texts) and _probability_ok(entry, rng):
                    seen.add(id(entry))
                    newly.append(entry)
                    if isinstance(fresh, set):
                        fresh.add(entry.get("uid"))
            activated.extend(newly)
            frontier = [entry for entry in newly if entry.get("recursive")]
        return activated, depth_reached

    def collect(
        self,
        recent_texts: Any,
        *,
        rng: Any = None,
        turn: Optional[int] = None,
        ledger: Any = None,
    ) -> WorldbookSelection:
        """一回合完整取值：触发 + 递归 + 预算裁剪 + 按落点分类 + **sticky/cooldown 记账**。

        Args:
            recent_texts: 最近若干条文本（按时间**升序**）。
            rng: 确定性随机源（``None`` → ``probability`` 不参与）。
            turn: 当前拍数（``None`` → ``sticky`` / ``cooldown`` 不参与）。
            ledger: 激活账本 ``{uid: 上次被关键词激活的拍}``；**就地更新**（调用方持有、
                跨拍传递）。只有「本拍由关键词新激活、且真的被选入 prompt」的条目才记账
                —— 被预算裁掉的没进 prompt，被 ``sticky`` 保活的没有新激活。

        Returns:
            :class:`WorldbookSelection`；``by_position`` 三种键恒在（可能为空列表）。
        """
        fresh: set = set()
        base = self.match(recent_texts, rng=rng, turn=turn, ledger=ledger, fresh=fresh)
        expanded, depth_reached = self._expand_recursive(
            base, rng=rng, turn=turn, ledger=ledger, fresh=fresh,
        )
        selected = self.select_within_budget(expanded)
        if isinstance(ledger, dict) and isinstance(turn, int) and not isinstance(turn, bool):
            for entry in selected:
                uid = entry.get("uid")
                if not entry.get("constant") and uid in fresh:
                    ledger[uid] = turn
        by_position: Dict[str, List[dict]] = {position: [] for position in LORE_POSITIONS}
        for entry in selected:
            position = entry.get("position", DEFAULT_POSITION)
            by_position.setdefault(position, []).append(entry)
        used_chars = sum(_content_len(entry) for entry in selected)
        return WorldbookSelection(
            entries=selected,
            by_position=by_position,
            used_chars=used_chars,
            depth_reached=depth_reached,
            trimmed=max(0, len(expanded) - len(selected)),
            issues=list(self.issues),
        )
