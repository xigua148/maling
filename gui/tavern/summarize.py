"""gui/tavern/summarize.py —— 酒馆功能域 · 结构化摘要与触发（V22-05，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.1  ``play.summary`` 结构：``{up_to_turn:int, text:str, generated_by:str, verified:bool}``
            （**结构化字段，非 prompt 里的临时拼接**；单写点落盘由 ``store.save()`` 负责）；
    - §4.3  ``summarize`` 冻结签名：``should_summarize(play, content)`` /
            ``validate_summary(text)`` / ``make_summary(play, *, llm_summarize=None)``；
    - D-V22-11  摘要触发（每 ``auto_summary_every=8`` 拍或进入新章）+ **落盘前校验**
            （非空 / 长度上限 / 不含"玩家的选择 / 他想要…"这类**越权臆断**）；不通过 → **保留旧摘要**；
    - §4.4  坏档恢复矩阵 L1/L2：读回时**字段缺失 / 类型错 → 降级不崩**（默认结构为底 + 类型守卫）；
    - §5.2  状态 / 文本分离：本模块全部为**纯数据变换**，落盘仍由 ``store.save()`` 承担。

硬约束（逐条对齐任务书）：
    * 仅依赖标准库 + 本包 ``.model``；**零 Qt**。
    * **不自己写盘** —— 只提供"生成后如何写回"的**纯数据变换** :func:`apply_summary`
      （把新 ``summary`` 合进 ``play``，返回新 dict，**不改入参**）；真正落盘是 ``store.save()``。
    * 纯函数、无墙钟、无网络、无全局随机；降级不抛；日志 ``logger.debug(..., exc_info=True)``，
      **不写裸 ``except: pass``**。

★ 触发口径（确定性，可单测）
    :func:`should_summarize` 在下列任一成立时返回 ``True``：
      1. ``turn > up_to_turn`` 且 ``turn % auto_summary_every == 0``（默认每 8 拍一次）；
      2. ``new_chapter=True`` 且 ``turn > up_to_turn``（UI / 引擎在进入新章时显式传入）；
      3. ``content["chapter_end_turns"]`` 含当前 ``turn`` 且 ``turn > up_to_turn``（内容包声明章末）。
    ``up_to_turn``（旧摘要已覆盖到的拍数）作为"去重闸"，避免同一拍重复触发。
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import labels as tavern_labels
from .model import SETTING_DEFAULTS, default_summary

logger = logging.getLogger("maling.tavern.summarize")

__all__ = [
    # —— 常量 ——
    "SUMMARY_KEYS",
    "SUMMARY_HEADING",
    "MAX_SUMMARY_CHARS",
    "OVERREACH_PATTERNS",
    "DEFAULT_AUTO_SUMMARY_EVERY",
    "DEFAULT_TRANSCRIPT_KEEP_TURNS",
    # —— 触发与校验 ——
    "should_summarize",
    "validate_summary",
    "history_window",
    # —— 结构化摘要 ——
    "summary_sections",
    "local_summary_text",
    "make_summary",
    # —— 落盘 / 读回（纯数据变换，不写盘）——
    "normalize_summary",
    "apply_summary",
]


# ===========================================================================
# 常量
# ===========================================================================

#: ``summary`` 的结构化键集（**单一来源 =** :func:`gui.tavern.model.default_summary`）。
SUMMARY_KEYS: Tuple[str, ...] = tuple(default_summary().keys())

#: 摘要正文的**标题**（单一来源）：``local_summary_text`` 以它开头；``prompt.history_text``
#: 用它做**去重**（正文已带标题时不再补一次，避免 history 段出现两次标题）。
SUMMARY_HEADING: str = "【前情提要】"

#: 摘要正文长度上限（字符；超限拒绝入库，保留旧摘要）。
MAX_SUMMARY_CHARS: int = 800

#: 越权臆断短语（命中即拒绝入库）："玩家的选择是什么 / 他想要…" 一类替客人做主 / 出戏的表述。
OVERREACH_PATTERNS: Tuple[str, ...] = (
    "玩家",
    "用户",
    "他想要",
    "他打算",
    "他决定要",
    "选择是什么",
)

#: 自动摘要间隔缺省（单一来源 = ``SETTING_DEFAULTS``）。
DEFAULT_AUTO_SUMMARY_EVERY: int = SETTING_DEFAULTS["auto_summary_every"]

#: ``transcript`` 逐字保留窗口缺省（单一来源 = ``SETTING_DEFAULTS``）。
DEFAULT_TRANSCRIPT_KEEP_TURNS: int = SETTING_DEFAULTS["transcript_keep_turns"]


# ===========================================================================
# 类型守卫小工具
# ===========================================================================

def _as_int(value: Any, default: int) -> int:
    """``int`` 守卫：``bool`` 不算 ``int``；非法回 ``default``。"""
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


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list 或含非 str 项时丢该项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _resolve_settings(play: dict, content: Any, settings: Any) -> dict:
    """解析设置来源（优先级：显式 ``settings`` → ``content.settings`` → ``play.settings``）。"""
    if isinstance(settings, dict):
        return settings
    for src in (content, play):
        if isinstance(src, dict):
            inner = src.get("settings")
            if isinstance(inner, dict):
                return inner
    return {}


# ===========================================================================
# 触发与窗口
# ===========================================================================

def history_window(transcript: Any, keep_turns: int) -> List[dict]:
    """按 ``transcript_keep_turns`` 取"逐字保留窗口"（**按 ``turn`` 计，非按条数**）。

    保留**最后 N 个不同 ``turn``** 的全部条目（同一拍的多条 —— 如 player+narrator —— 一并保留）。
    ``keep_turns <= 0`` → 空窗口；``turn`` 缺失 / 非法的条目仅在"未发生裁剪"时保留。

    Args:
        transcript: ``play["transcript"]``（任意类型，非列表 → ``[]``）。
        keep_turns: 保留拍数（默认 14，见 :data:`DEFAULT_TRANSCRIPT_KEEP_TURNS`）。

    Returns:
        窗口内条目列表（保持原顺序）。
    """
    entries = [e for e in transcript if isinstance(e, dict)] if isinstance(transcript, (list, tuple)) else []
    keep = _as_int(keep_turns, DEFAULT_TRANSCRIPT_KEEP_TURNS)
    if keep <= 0:
        return []

    turns: List[int] = []
    for entry in entries:
        tv = entry.get("turn")
        if isinstance(tv, int) and not isinstance(tv, bool):
            if tv not in turns:
                turns.append(tv)
    if len(turns) <= keep:
        return list(entries)

    kept = set(turns[-keep:])
    out: List[dict] = []
    for entry in entries:
        tv = entry.get("turn")
        if isinstance(tv, int) and not isinstance(tv, bool) and tv in kept:
            out.append(entry)
    return out


def should_summarize(
    play: Any,
    content: Any = None,
    *,
    settings: Any = None,
    new_chapter: bool = False,
) -> bool:
    """本拍是否应生成摘要（触发口径见模块 docstring ★）。

    冻结签名首两参数为 ``(play, content)``（design §4.3）；``settings`` / ``new_chapter``
    为**关键字可选扩展**（供批 2 ``service`` 注入设置与章切换信号），不破坏原签名。

    Args:
        play: 局记录（读 ``turn`` / ``summary.up_to_turn``）。
        content: 已解析内容包 dict（可选；读 ``chapter_end_turns``）。
        settings: 可选设置（读 ``auto_summary_every``）。
        new_chapter: 调用方是否检测到"进入新章"。

    Returns:
        是否触发。
    """
    pl = play if isinstance(play, dict) else {}
    resolved = _resolve_settings(pl, content, settings)
    every = _as_int(resolved.get("auto_summary_every"), DEFAULT_AUTO_SUMMARY_EVERY)
    turn = _as_int(pl.get("turn"), 0)
    up_to = _as_int(normalize_summary(pl.get("summary")).get("up_to_turn"), 0)

    if new_chapter and turn > up_to:
        return True

    if isinstance(content, dict):
        ends = content.get("chapter_end_turns")
        if isinstance(ends, (list, tuple)) and turn > up_to:
            if turn in [x for x in ends if isinstance(x, int) and not isinstance(x, bool)]:
                return True

    if every > 0 and turn > 0 and turn % every == 0 and turn > up_to:
        return True
    return False


# ===========================================================================
# 校验
# ===========================================================================

def validate_summary(text: Any) -> Tuple[bool, str]:
    """摘要正文落盘前校验（D-V22-11）：非空 / 长度上限 / 不含越权臆断。

    Args:
        text: 待校验摘要正文。

    Returns:
        ``(ok, reason)``；``ok=False`` 时 ``reason`` 为中文可读说明。
    """
    if not isinstance(text, str):
        return False, "摘要不是文本"
    stripped = text.strip()
    if not stripped:
        return False, "摘要为空"
    if len(stripped) > MAX_SUMMARY_CHARS:
        return False, f"摘要超长（{len(stripped)} > {MAX_SUMMARY_CHARS}）"
    for pattern in OVERREACH_PATTERNS:
        if pattern in stripped:
            return False, f"摘要含越权臆断：{pattern}"
    return True, "ok"


# ===========================================================================
# 结构化摘要
# ===========================================================================

def summary_sections(play: Any, content: Any = None) -> dict:
    """把局状态收敛为**结构化摘要分片**（非临时拼接串）。

    ★ A2-5：面向 LLM 的文本不得出现机器名 —— 酒 / 物品 / 话题等值经
    :mod:`gui.tavern.labels` 翻成中文；内容包没声明中文名时给**中性中文**短句，
    **绝不**把 ``long_night`` / ``photo`` / ``drawer`` 这类机器名拼进摘要。

    Returns:
        ``{"facts": [...], "relations": [...], "open_threads": [...]}`` ——
        已发生的事实 / 关系变化 / 未决线索（各自为可读中文短句列表）。
    """
    pl = play if isinstance(play, dict) else {}
    vars_ = pl.get("vars") if isinstance(pl.get("vars"), dict) else {}

    facts: List[str] = []
    relations: List[str] = []
    threads: List[str] = []

    def _join(values: Any) -> str:
        """机器值列表 → 中文顿号串（取不到中文名 → 空串）。"""
        return tavern_labels.labeled_values(content, _as_str_list(values), "")

    poured = _as_str(vars_.get("poured")).strip()
    if poured:
        label = _join([poured])
        facts.append(f"点过一杯「{label}」" if label else "点过一杯酒")
    held = _as_str_list(vars_.get("held_items"))
    if held:
        label = _join(held)
        facts.append("身上带着：" + label if label else "身上带着些东西")
    known = _as_str_list(vars_.get("known"))
    if known:
        label = _join(known)
        facts.append("问起过：" + label if label else "问起过一些事")
    opened = _as_str_list(vars_.get("opened"))
    if opened:
        label = _join(opened)
        facts.append("打开过：" + label if label else "打开过一些东西")
    if vars_.get("knows_name") is True:
        facts.append("知道了她的名字")

    given = _as_str_list(vars_.get("given"))
    if given:
        label = _join(given)
        relations.append(("把" + label + "交给了她") if label else "交给她过东西")

    pending = pl.get("pending")
    if isinstance(pending, (list, tuple)):
        for item in pending:
            if isinstance(item, dict):
                label = _as_str(item.get("label")).strip()
                if label:
                    threads.append(label)

    return {"facts": facts, "relations": relations, "open_threads": threads}


def local_summary_text(play: Any, content: Any = None) -> str:
    """本地（确定性）摘要正文：由 :func:`summary_sections` 分片合成，**无 LLM 依赖**。

    采用第二人称、**无任何数值 / 序号**（避开越权臆断词，保证 :func:`validate_summary` 通过）。
    """
    sections = summary_sections(play, content)
    parts: List[str] = []
    if sections["facts"]:
        parts.append("；".join(sections["facts"]) + "。")
    if sections["relations"]:
        parts.append("；".join(sections["relations"]) + "。")
    body = "".join(parts) or "你们还在灯笼酒馆里，慢慢开始这个夜晚。"
    text = SUMMARY_HEADING + body
    if sections["open_threads"]:
        text += "还有没做的事：" + "、".join(sections["open_threads"]) + "。"
    return text


def _summary_source(play: dict) -> str:
    """把 ``transcript`` 收敛为纯文本（供注入的 ``llm_summarize`` 读取；无墙钟 / 无副作用）。"""
    transcript = play.get("transcript")
    if not isinstance(transcript, (list, tuple)):
        return ""
    lines: List[str] = []
    for entry in transcript:
        if not isinstance(entry, dict):
            continue
        text = _as_str(entry.get("text")).strip()
        if not text:
            continue
        speaker = "你" if _as_str(entry.get("role")) == "player" else "她"
        lines.append(f"{speaker}：{text}")
    return "\n".join(lines)


def make_summary(
    play: Any,
    *,
    llm_summarize: Optional[Callable[[str], Optional[str]]] = None,
    settings: Any = None,
    content: Any = None,
) -> dict:
    """生成 ``play.summary``（**结构化 4 键**）；校验不通过 → **保留旧摘要**（D-V22-11）。

    流程（区分"LLM 不可用"与"LLM 给了不合格结果"，两者降级去向不同）：
        1. 若注入了 ``llm_summarize``（``(source_text) -> str|None``）：
              * **抛异常 / 返回非 str（含 None）** → 视为"LLM 不可用" → 回落**本地确定性摘要**；
              * **返回 str（含空串）** → 作为**候选正文**交给校验（空串属"垃圾结果"）；
           未注入 → 直接用本地摘要；
        2. 用 :func:`validate_summary` 校验候选正文；不通过 → 返回**旧摘要副本**（原样保留）；
        3. 通过 → 返回 ``{up_to_turn, text, generated_by, verified}``（**恰好** :data:`SUMMARY_KEYS`）。

    Args:
        play: 局记录（读 ``turn`` / ``summary`` / ``transcript`` / ``vars`` / ``pending``）。
        llm_summarize: 可选注入的 LLM 摘要回调；``None`` → 纯本地摘要。
        settings: 可选设置（当前仅透传，预留）。
        content: 可选内容包（透传给本地摘要分片）。

    Returns:
        合法的 ``summary`` dict（键集 == :data:`SUMMARY_KEYS`）。
    """
    pl = play if isinstance(play, dict) else {}
    old = normalize_summary(pl.get("summary"))
    del settings  # 预留：当前本地摘要不依赖设置，保持签名稳定

    text: Optional[str] = None
    generated_by = "local"
    if callable(llm_summarize):
        candidate: Any = None
        try:
            candidate = llm_summarize(_summary_source(pl))
        except Exception:  # LLM 不可用 → 回退本地（降级铁律，不抛）
            logger.debug("llm_summarize 调用失败，回退本地摘要", exc_info=True)
            candidate = None
        if isinstance(candidate, str):
            # 返回 str（含空串）即为候选正文；是否合格交由 validate_summary 裁决
            text = candidate
            generated_by = "llm"

    if text is None:
        text = local_summary_text(pl, content)

    ok, reason = validate_summary(text)
    if not ok:
        logger.debug("摘要校验未通过(%s)，保留旧摘要", reason)
        return dict(old)

    return {
        "up_to_turn": _as_int(pl.get("turn"), 0),
        "text": text,
        "generated_by": generated_by,
        "verified": True,
    }


# ===========================================================================
# 落盘 / 读回（纯数据变换；真正落盘 = store.save()）
# ===========================================================================

def normalize_summary(raw: Any) -> dict:
    """``summary`` 读回降级（§4.4 L1/L2）：默认结构为底 + 类型守卫；未知字段保留。

    * 非 dict → 直接返回 :func:`gui.tavern.model.default_summary`；
    * 字段缺失 / 类型错 → 回落默认（**降级不崩**）；
    * 未知字段 → 保留（前向兼容，对齐 model 的"未知字段不销毁"）。
    """
    result = default_summary()
    if not isinstance(raw, dict):
        return result

    result["up_to_turn"] = _as_int(raw.get("up_to_turn"), result["up_to_turn"])
    result["text"] = raw["text"] if isinstance(raw.get("text"), str) else result["text"]
    result["generated_by"] = raw["generated_by"] if isinstance(raw.get("generated_by"), str) else result["generated_by"]
    if isinstance(raw.get("verified"), bool):
        result["verified"] = raw["verified"]

    for key, value in raw.items():
        if key not in result:  # 未知字段保留
            result[key] = value
    return result


def apply_summary(play: Any, summary: Any) -> dict:
    """纯数据变换：把新 ``summary`` 写回 ``play`` 的**副本**（**不改入参**、**不写盘**）。

    真正落盘由 ``store.save()`` 负责（单写点）；本函数只产出"改好的新 ``play``"，供
    调用方（批 2 ``service``）交给 ``store``。

    Args:
        play: 原局记录（任意类型，非 dict → 返回空 dict）。
        summary: 新摘要（经 :func:`normalize_summary` 归一）。

    Returns:
        写入新 ``summary`` 后的**新** play dict（深拷贝，入参零改动）。
    """
    if not isinstance(play, dict):
        return {}
    out = copy.deepcopy(play)
    out["summary"] = normalize_summary(summary)
    return out
