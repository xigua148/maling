"""gui/tavern/prompt.py —— 酒馆功能域 · 五段式说书人 prompt 组装（V22-05，纯逻辑零 Qt）。

设计依据：``docs/design-v22.md``
    - §4.3  ``build_story_prompt(state, book, play, content, *, relation_ctx, mode)`` 冻结签名；
    - §4.3  五段式**有序**段名 = :data:`gui.tavern.model.PROMPT_SEGMENTS`，逐段 role =
            :data:`gui.tavern.model.PROMPT_SEGMENT_ROLES`（前 4 段 ``system``、末段 ``history``）；
    - D-V22-10  prompt 组装：纯函数 + ``mode="normal"|"reroll"``；``reroll`` 时**本回合必不携带
            上一版文本**；narrator 长度约束（``short``/``medium``/``long``）；
    - D-V22-04  关系只读：``relation_ctx`` 由 UI 层读入后**作为参数传入**，本模块只读、只用于
            语气与称呼，**绝不产出任何数值、绝不回写**；
    - D-V22-05  界面零序号：说书人规则里明令**不给故事编排序号**（"第几夜 / 第几幕" 不上屏）。
    - §5.2  状态与文本分离 → ``reroll`` 天然安全：本模块是**纯函数**，**绝不修改** ``state`` /
            ``play`` / ``content`` 入参（任务书 V22-05 的"状态零写入"契约）。

硬约束（逐条对齐任务书）：
    * 仅依赖标准库 + 本包 ``.model`` / ``.summarize``；**零 Qt**（无 PySide6 环境 ``import`` 必须成功）。
    * 纯文本拼装、纯函数、可单测；不读墙钟、不联网、不写盘、无全局随机。
    * 不硬编码任何颜色 / 字号（本模块与 UI 无关）；不新增第三方依赖。
    * 降级不抛：世界书不可用时按"空世界规则"继续；未知 ``mode`` 回落 ``normal``；
      日志 ``logger.debug(..., exc_info=True)``，**不写裸 ``except: pass``**。

★ 段 ↔ 世界书落点映射（本模块的固定契约；设计 §4.3 五段注释即此语义）
    世界书三种 ``position``（:data:`gui.tavern.model.LORE_POSITIONS`）分别落到：

    ==================  ==================  ==========================================
    世界书 position      prompt 段名          依据
    ==================  ==================  ==========================================
    ``system_head``     ``world_rules``       §4.3「世界规则（constant 条目）」= 常驻世界设定
    ``system_tail``     ``turn_context``      §4.3「本回合情境（命中条目）」= 本回合浮现的线索
    ``history_depth``   ``history``           §4.3「history 段 = 近 N 条叙述 + 前情提要」，
                                              深度注入插进历史叙述之中
    ==================  ==================  ==========================================

    （见 :data:`SEGMENT_POSITION_MAP`。设计 §4.3 已给出"位置即权重"的分层语义，
    本映射为其唯一自然解读，**列为不确定点之一是"若某 position 为空"的产出形态**，
    见下。）

★ "某 position 为空"的行为（**明确契约**，非不确定）
    :func:`render_messages` **恒定产出 5 段**（顺序 = ``PROMPT_SEGMENTS``），即使某段内容为空串。
    即：**不因某 position 为空而减少段数**（顺序契约优先）。空段内容为 ``""``（如无 ``constant``
    世界规则时 ``world_rules`` 段为空串）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import labels as tavern_labels
from .model import (
    NARRATOR_LENGTHS,
    PROMPT_MODES,
    PROMPT_SEGMENT_ROLES,
    PROMPT_SEGMENTS,
    SETTING_DEFAULTS,
)
from .summarize import SUMMARY_HEADING, history_window

logger = logging.getLogger("maling.tavern.prompt")

__all__ = [
    # —— 契约常量（转发 model，便于批 2 单点 import）——
    "PROMPT_SEGMENTS",
    "PROMPT_SEGMENT_ROLES",
    "PROMPT_MODES",
    # —— 本模块常量 ——
    "NARRATOR_LENGTH_INSTRUCTIONS",
    "DEFAULT_NARRATOR_LENGTH",
    "SEGMENT_POSITION_MAP",
    "REROLL_DIRECTIVE",
    "EMPTY_HISTORY_HINT",
    # —— 分段内容构建（纯函数）——
    "narrator_rule_text",
    "world_rules_text",
    "character_card_text",
    "vars_summary_lines",
    "turn_context_text",
    "history_text",
    # —— 主入口 ——
    "position_entries",
    "collect_segments",
    "render_messages",
    "build_story_prompt",
]


# ===========================================================================
# 常量
# ===========================================================================

#: ``narrator_length`` 三档 → 叙述长度约束指令（单一来源，供 UI 复用）。
NARRATOR_LENGTH_INSTRUCTIONS: Dict[str, str] = {
    "short": "篇幅：叙述请压在 60–120 字，节奏紧一点，点到为止。",
    "medium": "篇幅：叙述请放在 120–220 字，可以带一两处细节描写。",
    "long": "篇幅：叙述可以写到 220–400 字，允许更细腻的描写与留白。",
}

#: ``narrator_length`` 缺省 / 非法时的回落值（单一来源 = ``SETTING_DEFAULTS``）。
DEFAULT_NARRATOR_LENGTH: str = SETTING_DEFAULTS["narrator_length"]

#: 世界书 ``position`` → prompt 段名的**固定映射**（见模块 docstring ★）。
SEGMENT_POSITION_MAP: Dict[str, str] = {
    "system_head": "world_rules",
    "system_tail": "turn_context",
    "history_depth": "history",
}

#: ``reroll`` 指令：明确要求换一种写法（**不携带**上一版文本）。
REROLL_DIRECTIVE: str = "（这是重写：请换一种写法，不要重复之前已经写过的句子。）"

#: 空局的占位提示（避免 ``history`` 段整体为空白）。
EMPTY_HISTORY_HINT: str = "（故事刚刚开始。）"


# ===========================================================================
# 类型守卫小工具（本地副本，避免耦合 model 私有名）
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


def _turn_of(entry: Any) -> Optional[int]:
    """安全取条目的 ``turn`` 整数值（``bool`` / 非法 → ``None``）。"""
    if not isinstance(entry, dict):
        return None
    tv = entry.get("turn")
    if isinstance(tv, bool) or not isinstance(tv, int):
        return None
    return tv


# ===========================================================================
# 入参归一：state / play / content / settings
# ===========================================================================

def _resolve_settings(
    state: Any,
    play: Any,
    content: Any,
    settings: Any,
) -> dict:
    """解析酒馆设置来源（优先级：显式 ``settings`` → ``content.settings`` → ``state.settings``）。

    ``build_story_prompt`` 的冻结签名不含 ``settings`` 位置参数（design §4.3），故本模块以
    **关键字可选** ``settings`` 注入；未注入时依次回退到 ``content`` / ``state`` / ``play``
    里可能内嵌的 ``settings``，最后回落空 dict（各键再各自回落类默认）。
    """
    if isinstance(settings, dict):
        return settings
    for src in (content, state, play):
        if isinstance(src, dict):
            inner = src.get("settings")
            if isinstance(inner, dict):
                return inner
    return {}


def _state_of(state: Any, play: Any) -> dict:
    """把入参收敛为"游戏状态"字典（``state`` 优先，退化到 ``play``）。"""
    if isinstance(state, dict):
        return state
    if isinstance(play, dict):
        return play
    return {}


def _play_of(state: Any, play: Any) -> dict:
    """把入参收敛为"局记录"字典（``play`` 优先，退化到 ``state``）。"""
    if isinstance(play, dict):
        return play
    if isinstance(state, dict):
        return state
    return {}


def _recent_texts(state: dict) -> List[str]:
    """取 ``transcript`` 里的可读文本（按时间升序），供世界书关键词扫描。"""
    transcript = state.get("transcript")
    if not isinstance(transcript, (list, tuple)):
        return []
    out: List[str] = []
    for entry in transcript:
        if isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str) and text:
                out.append(text)
    return out


def _collect_worldbook(book: Any, state: dict) -> Any:
    """安全调用 ``WorldBook.collect``；失败 / 无书 → ``None``（按空世界规则继续，不抛）。"""
    if book is None:
        return None
    collect = getattr(book, "collect", None)
    if not callable(collect):
        logger.debug("book 无 collect() 方法，按空世界规则处理: %r", type(book))
        return None
    try:
        return collect(_recent_texts(state), turn=_as_int(state.get("turn"), 0))
    except Exception:  # 世界书异常绝不影响 prompt 组装（降级不抛）
        logger.debug("世界书 collect 失败，按空世界规则处理", exc_info=True)
        return None


def _worldbook_summary(state: dict, play: dict) -> Any:
    """择一取"前情提要"文本源：优先 ``play.summary``，退化 ``state.summary``。"""
    summary = play.get("summary")
    if not isinstance(summary, dict):
        summary = state.get("summary")
    return summary if isinstance(summary, dict) else {}


# ===========================================================================
# 分段内容构建（纯函数）
# ===========================================================================

def narrator_rule_text(narrator_length: Any) -> str:
    """段 1 ``narrator_rules``：说书人规则（身份 / 视角 / 边界 / 戒律 / 篇幅）。

    ``narrator_length`` 三档（``short``/``medium``/``long``）只影响**篇幅**一行，
    非法值回落 :data:`DEFAULT_NARRATOR_LENGTH`（``short``）。

    Args:
        narrator_length: ``short`` / ``medium`` / ``long``（其余回落默认）。

    Returns:
        说书人规则文本（多行，``【说书人规则】`` 起头）。
    """
    length = narrator_length if narrator_length in NARRATOR_LENGTHS else DEFAULT_NARRATOR_LENGTH
    return "\n".join([
        "【说书人规则】",
        "- 身份：你是「灯笼酒馆」里那位老板娘，也是今晚的说书人，替她把这个夜晚讲下去。",
        "- 视角：用第二人称「你」讲客人的所见所感；老板娘只做她在做的事、说她该说的话。",
        "- 边界：只写叙述正文。不要向客人提问，不要替客人做决定；客人没做的，就留白。",
        "- 戒律：不写任何数值、计数或刻度；不给故事编排序号，也不出现「第几夜 / 第几幕」这类标签。",
        "- " + NARRATOR_LENGTH_INSTRUCTIONS[length],
    ])


def position_entries(selection: Any, position: str) -> List[dict]:
    """从 ``WorldbookSelection.by_position`` 取某落点的条目（纯读，缺失 → 空列表）。"""
    if selection is None:
        return []
    by_position = getattr(selection, "by_position", None)
    if not isinstance(by_position, dict):
        return []
    entries = by_position.get(position)
    if not isinstance(entries, (list, tuple)):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def world_rules_text(selection: Any) -> str:
    """段 2 ``world_rules``：世界书 ``system_head`` 条目（常驻世界规则）。

    ``system_head`` 为空 → 返回空串（**空段**：五段固定，段数不因空而减少）。
    """
    entries = position_entries(selection, "system_head")
    if not entries:
        return ""
    lines = ["【世界规则】"]
    for entry in entries:
        content = _as_str(entry.get("content")).strip()
        if content:
            lines.append("- " + content)
    return "\n".join(lines) if len(lines) > 1 else ""


def character_card_text(relation_ctx: Any = None, content: Any = None) -> str:
    """段 3 ``character_card``：角色卡（她是谁 / 怎么行动 / 语气样本）+ 只读关系提示。

    * 人设正文优先取 ``content["character_card"]``（或 ``content["persona"]``）；缺省时给一段
      灯笼酒馆老板娘的**中性默认人设**（保证段非空）。
    * ``relation_ctx``（D-V22-04，**只读**）用于语气与称呼：如 ``{"stage_name": "亲近",
      "self_ref": "我"}``。**绝不产出任何数值、绝不回写**。
    """
    lines = ["【她是这样一个人】"]
    card: Any = None
    if isinstance(content, dict):
        card = content.get("character_card") or content.get("persona")
    if isinstance(card, str) and card.strip():
        lines.append(card.strip())
    else:
        lines.append("她系着围裙站在吧台后，说话慢，习惯替客人把杯沿擦干净；她记得每一个来过的人。")

    relation = relation_ctx if isinstance(relation_ctx, dict) else {}
    stage = _as_str(relation.get("stage_name")).strip()
    self_ref = _as_str(relation.get("self_ref")).strip()
    name = _as_str(relation.get("name")).strip()
    if stage or self_ref or name:
        bits: List[str] = []
        if stage:
            bits.append(f"你们此刻的关系是「{stage}」")
        if self_ref:
            bits.append(f"她称你为「{self_ref}」")
        if name:
            bits.append(f"她的名字是「{name}」")
        lines.append("（只读的语气提示，仅供称呼与口吻参考：" + "；".join(bits) + "。）")
    return "\n".join(lines)


def vars_summary_lines(state: Any, content: Any = None) -> List[str]:
    """把 ``state.vars`` 收敛为若干可读行（**结构化摘要，非临时拼接串**）。

    ★ A2-5：**面向 LLM 的文本不得出现机器名**。地点 / 酒 / 物品 / 话题等值一律经
    :mod:`gui.tavern.labels` 翻成中文；内容包没声明中文名时给**中性中文**短句，
    **绝不**把 ``long_night`` / ``drawer`` 这类机器名写进提示词。
    """
    vars_ = state.get("vars") if isinstance(state, dict) else None
    vars_ = vars_ if isinstance(vars_, dict) else {}
    lines: List[str] = []

    scene_id = _as_str(state.get("scene_id")).strip() if isinstance(state, dict) else ""
    if scene_id:
        lines.append(f"- 此刻你在的地方：{tavern_labels.scene_label(content, scene_id)}")

    def _value_line(prefix: str, values: Any, fallback: str) -> None:
        """有中文名 → ``prefix：中文顿号串``；取不到 → 中性中文整句。"""
        cleaned = [v for v in _as_str_list(values) if v.strip()]
        if not cleaned:
            return
        resolved = tavern_labels.labeled_values(content, cleaned, "")
        lines.append(f"{prefix}：{resolved}" if resolved else fallback)

    _value_line("- 点过的酒", [_as_str(vars_.get("poured")).strip()], "- 你已经点过酒了。")
    _value_line("- 你身上带着", _as_str_list(vars_.get("held_items")), "- 你身上带着些东西。")
    _value_line("- 眼前能拿到", _as_str_list(vars_.get("scene_items")), "- 眼前有些能拿的东西。")
    _value_line("- 你已经交给她", _as_str_list(vars_.get("given")), "- 你交给她过东西。")
    _value_line("- 你打开过", _as_str_list(vars_.get("opened")), "- 你打开过一些东西。")
    _value_line("- 你问起过", _as_str_list(vars_.get("known")), "- 你问起过一些事。")
    if vars_.get("knows_name") is True:
        lines.append("- 你已经知道她的名字。")
    return lines


def _current_entry(state: dict) -> Optional[dict]:
    """取"本回合"的留痕条目：优先当前 ``turn`` 的 ``player`` 条，退化末条。"""
    transcript = state.get("transcript")
    if not isinstance(transcript, (list, tuple)):
        return None
    cur_turn = _as_int(state.get("turn"), 0)
    same_turn = [e for e in transcript if isinstance(e, dict) and _turn_of(e) == cur_turn]
    for entry in reversed(same_turn):
        if _as_str(entry.get("role")) == "player":
            return entry
    if same_turn:
        return same_turn[-1]
    last = [e for e in transcript if isinstance(e, dict)]
    return last[-1] if last else None


def turn_context_text(
    state: Any,
    selection: Any = None,
    *,
    mode: str = "normal",
    content: Any = None,
) -> str:
    """段 4 ``turn_context``：vars 摘要 + 本回合发生了什么 + ``system_tail`` 命中条目。

    ★ A2-5：``node_id`` / ``scene_id`` / ``transform`` / 未生效原因码一律经
    :mod:`gui.tavern.labels` 翻成中文（节点 → ``title``；取不到 → 中性中文兜底），
    **绝不**把机器名写进提示词。
    """
    st = state if isinstance(state, dict) else {}
    lines: List[str] = ["【此刻】"]

    node_id = _as_str(st.get("node_id")).strip()
    if node_id:
        title = tavern_labels.node_label(content, node_id)
        if title:
            lines.append(f"- 正在发生：{title}")
    lines.extend(vars_summary_lines(st, content))

    entry = _current_entry(st)
    if isinstance(entry, dict):
        player_text = _as_str(entry.get("text")).strip()
        if player_text:
            lines.append(f"- 客人刚才做的事：{player_text}")
        resolution = entry.get("resolution") if isinstance(entry.get("resolution"), dict) else {}
        mode_r = _as_str(resolution.get("mode")).strip()
        transform = _as_str(resolution.get("transform")).strip()
        reason = _as_str(resolution.get("reason")).strip()
        ok = resolution.get("ok") if isinstance(resolution.get("ok"), bool) else None
        if transform or mode_r:
            label = tavern_labels.transform_label(transform) if transform else tavern_labels.mode_label(mode_r)
            if ok is True:
                lines.append(f"- 这一拍已经生效：{label}")
            else:
                lines.append(f"- 这一拍没有改变什么（{label}；{tavern_labels.reason_label(reason)}）")

    tail = position_entries(selection, "system_tail")
    if tail:
        lines.append("【这一回合浮现的线索】")
        for entry in tail:
            content_text = _as_str(entry.get("content")).strip()
            if content_text:
                lines.append("- " + content_text)
    return "\n".join(lines)


def history_text(
    state: Any,
    selection: Any = None,
    *,
    mode: str = "normal",
    keep_turns: Optional[int] = None,
    summary: Any = None,
) -> str:
    """段 5 ``history``：``【前情提要】`` + 近 N 条叙述 + ``history_depth`` 深度注入。

    * 保留窗口由 ``transcript_keep_turns``（默认 14）决定（:func:`gui.tavern.summarize.history_window`）；
    * ``mode == "reroll"`` 时**绝不携带本回合上一版叙述文本**（D-V22-10），并加一条重写指令；
    * ``history_depth`` 条目按 ``depth`` 从末往前插入历史叙述之中（``depth<=0`` → 追加）。
    """
    st = state if isinstance(state, dict) else {}
    transcript = st.get("transcript")
    entries = [e for e in transcript if isinstance(e, dict)] if isinstance(transcript, (list, tuple)) else []
    if keep_turns is None:
        keep_turns = SETTING_DEFAULTS["transcript_keep_turns"]
    window = history_window(entries, keep_turns)
    cur_turn = _as_int(st.get("turn"), 0)

    narrative: List[str] = []
    for entry in window:
        role = _as_str(entry.get("role"))
        if mode == "reroll" and role == "narrator" and _turn_of(entry) == cur_turn:
            continue  # 重掷：本回合必不携带上一版文本
        text = _as_str(entry.get("text")).strip()
        if not text:
            continue
        speaker = "你" if role == "player" else "她"
        narrative.append(f"{speaker}：{text}")

    for entry in position_entries(selection, "history_depth"):
        content = _as_str(entry.get("content")).strip()
        if not content:
            continue
        depth = _as_int(entry.get("depth"), 0)
        index = max(0, len(narrative) - depth) if depth > 0 else len(narrative)
        narrative.insert(index, f"- 【背景】{content}")

    summary_text = _as_str((summary or {}).get("text") if isinstance(summary, dict) else "").strip()
    # ★ P2：``summary.text`` 自带标题（``local_summary_text`` 以「【前情提要】」开头），
    # 这里再补一次会让 history 段出现**两次**标题。统一口径：剥掉正文里已有的标题，
    # 由本段**恰好加一次**（LLM 产出的摘要若不带标题，同样由这里补上）。
    while summary_text.startswith(SUMMARY_HEADING):
        summary_text = summary_text[len(SUMMARY_HEADING):].lstrip()
    lines: List[str] = []
    if summary_text:
        lines.append(SUMMARY_HEADING)
        lines.append(summary_text)
        lines.append("")
    lines.append("【最近的经过】")
    if mode == "reroll":
        lines.append(REROLL_DIRECTIVE)
    lines.extend(narrative)
    if not narrative and not summary_text and mode != "reroll":
        lines.append(EMPTY_HISTORY_HINT)
    return "\n".join(lines)


# ===========================================================================
# 主入口
# ===========================================================================

def collect_segments(
    state: Any,
    book: Any,
    play: Any,
    content: Any = None,
    *,
    relation_ctx: Any = None,
    mode: str = "normal",
    settings: Any = None,
    selection: Any = None,
) -> Dict[str, str]:
    """组装五段内容：返回 ``段名 → 文本`` 映射（键恒 = :data:`PROMPT_SEGMENTS`）。

    纯函数：**绝不修改** ``state`` / ``play`` / ``content`` 入参（reroll 天然零状态写入）。

    Args:
        state: 当前游戏状态（``vars`` / ``turn`` / ``transcript`` / ``scene_id`` / ``node_id``）。
        book: :class:`gui.tavern.worldbook.WorldBook`（可为 ``None``，按空世界规则）。
        play: 局记录（``summary`` / ``chapter_id`` 等）；与 ``state`` 传同一 dict 亦可。
        content: 已解析内容包 dict（可选；只读）。
        relation_ctx: 只读关系上下文（D-V22-04）：``{"stage_name","self_ref",...}``。
        mode: ``"normal"`` / ``"reroll"``；非法值回落 ``normal``（降级不抛）。
        settings: 可选设置来源（``narrator_length`` / ``transcript_keep_turns``）。
        selection: **本拍已算好的世界书选择结果**（:class:`WorldbookSelection`）。

    ★ A2-1（P0）：``selection`` 由 ``service`` 在**本拍**算好后传入（与「世界书」Tab 快照
    **同一份**），prompt 侧**不再自行 collect** —— 这样 ``probability`` / ``sticky`` /
    ``cooldown`` 才会**真的改变 LLM 看到的内容**，且天然保证
    「Tab 快照 == 提示词」。未传（``None``）时保留旧的"自行 collect"路径，
    供纯函数调用方（单测）使用。

    Returns:
        ``{段名: 文本}``，五种键恒在（某段可为空串）。
    """
    st = _state_of(state, play)
    pl = _play_of(state, play)

    if mode not in PROMPT_MODES:
        logger.debug("未知 prompt mode=%r，回落 normal", mode)
        mode = "normal"

    resolved = _resolve_settings(st, pl, content, settings)
    length = _as_str(resolved.get("narrator_length"), DEFAULT_NARRATOR_LENGTH)
    if length not in NARRATOR_LENGTHS:
        length = DEFAULT_NARRATOR_LENGTH
    keep_turns = _as_int(resolved.get("transcript_keep_turns"), SETTING_DEFAULTS["transcript_keep_turns"])

    if selection is None:
        selection = _collect_worldbook(book, st)
    summary = _worldbook_summary(st, pl)

    return {
        "narrator_rules": narrator_rule_text(length),
        "world_rules": world_rules_text(selection),
        "character_card": character_card_text(relation_ctx, content),
        "turn_context": turn_context_text(st, selection, mode=mode, content=content),
        "history": history_text(st, selection, mode=mode, keep_turns=keep_turns, summary=summary),
    }


def render_messages(segments: Any) -> List[dict]:
    """把 ``段名 → 文本`` 映射渲染为消息列表（**顺序 + role 固定契约**）。

    顺序恒 = :data:`PROMPT_SEGMENTS`；每段 role 取 :data:`PROMPT_SEGMENT_ROLES`
    （前 4 段 ``system``、末段 ``history``）。**恒定产出 5 条**（缺段 / 非 str → 空串），
    顺序契约优先于"省略空段"。
    """
    segs = segments if isinstance(segments, dict) else {}
    messages: List[dict] = []
    for name in PROMPT_SEGMENTS:
        value = segs.get(name)
        content = value if isinstance(value, str) else ""
        messages.append({
            "segment": name,
            "role": PROMPT_SEGMENT_ROLES[name],
            "content": content,
        })
    return messages


def build_story_prompt(
    state: Any,
    book: Any,
    play: Any,
    content: Any = None,
    *,
    relation_ctx: Any = None,
    mode: str = "normal",
    settings: Any = None,
    selection: Any = None,
) -> List[dict]:
    """五段式说书人 prompt 组装（design-v22 §4.3 冻结签名）。

    ``selection`` 为**关键字可选扩展**（同 ``settings``）：由 ``service`` 传入本拍已算好的
    世界书选择结果，使提示词与「世界书」Tab 快照**共用同一份**（A2-1）。不传则保持旧的
    自行 ``collect`` 行为，签名向后兼容。

    Returns:
        ``list[dict]``，每项 ``{"segment","role","content"}``，顺序 = ``PROMPT_SEGMENTS``。
        纯函数，可对同一输入反复调用得到完全一致输出。
    """
    segments = collect_segments(
        state, book, play, content,
        relation_ctx=relation_ctx, mode=mode, settings=settings, selection=selection,
    )
    return render_messages(segments)
