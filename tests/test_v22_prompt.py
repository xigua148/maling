"""tests/test_v22_prompt.py —— V22-05 prompt 五段式 + 摘要 · 纯函数断言。

覆盖 design-v22 的可断言点（**确定性、无墙钟、无 Qt、无网络**）：

    1. 五段顺序与 role **逐段固定**（顺序错即红）；
    2. ``reroll`` 版与 ``normal`` 版**确实不同**，且 **reroll 零状态写入**（入参未被修改）；
    3. ``narrator_length`` 三档产出**可区分**；
    4. 世界书三种 ``position`` **各自落到正确位置**；「某 position 为空」的行为明确（五段固定）；
    5. 摘要：第 8 拍触发一次（15 拍内**触发次数与时机**）；``transcript_keep_turns=14`` 窗口生效；
    6. 摘要落盘 / 读回：字段缺失或类型错 → **降级不崩**；结构化字段**不是拼接串**（键集断言）；
    7. 纯函数性：同一输入两次调用结果完全一致；
    8. 零 Qt（源码 AST + 命名空间无 ``Q*`` 符号）。

只 import ``gui.tavern.*``（零 Qt 链）；不建 ``QApplication``、不联网。
"""
from __future__ import annotations

import ast
import copy
import pathlib
import re

import pytest

from gui.tavern import prompt as P
from gui.tavern import summarize as S
from gui.tavern import worldbook as wb
from gui.tavern.model import (
    LORE_POSITIONS,
    NARRATOR_LENGTHS,
    PROMPT_SEGMENT_ROLES,
    PROMPT_SEGMENTS,
    default_play,
    default_summary,
    default_worldbook_entry,
)


# ---------------------------------------------------------------------------
# 夹具小工具
# ---------------------------------------------------------------------------

def mk_entry(uid: int, content: str, position: str, **over) -> dict:
    """从类默认出发覆盖若干字段，得到一条 18 字段条目。"""
    entry = default_worldbook_entry()
    entry.update(uid=uid, content=content, position=position, **over)
    return entry


def make_book(entries, **over) -> wb.WorldBook:
    """构造一本世界书（默认：预算充足、扫描 4 拍、条数 10、不递归）。"""
    return wb.WorldBook(
        entries,
        budget_chars=over.get("budget_chars", 10000),
        scan_depth=over.get("scan_depth", 4),
        max_entries=over.get("max_entries", 10),
        recursive_max_depth=over.get("recursive_max_depth", 0),
    )


def entry(turn: int, role: str, text: str, *, mode: str = "verbatim",
          transform: str = "wait", ok: bool = True, reason: str = "ok") -> dict:
    """构造一条 ``transcript`` 留痕（字段齐全）。"""
    return {
        "turn": turn,
        "role": role,
        "input_kind": "free",
        "text": text,
        "resolution": {"mode": mode, "transform": transform, "ok": ok, "reason": reason, "llm_used": False},
        "narrated": True,
        "at": "",
    }


def make_state(*, turn: int = 1, transcript=None, scene_id: str = "counter",
               node_id: str = "counter_photo", vars_over=None) -> dict:
    """构造一个游戏状态（= ``default_play`` 的定制版）。"""
    st = default_play()
    st["turn"] = turn
    st["scene_id"] = scene_id
    st["node_id"] = node_id
    if transcript is not None:
        st["transcript"] = transcript
    if vars_over:
        st["vars"].update(vars_over)
    return st


def by_segment(messages) -> dict:
    """把消息列表折叠为 ``段名 → content`` 便于断言。"""
    return {m["segment"]: m["content"] for m in messages}


# ===========================================================================
# 1. 五段顺序与 role 固定
# ===========================================================================

def test_segment_order_and_roles_are_frozen():
    # 契约字面值（顺序错即红）
    assert PROMPT_SEGMENTS == ("narrator_rules", "world_rules", "character_card", "turn_context", "history")
    assert PROMPT_SEGMENT_ROLES == {
        "narrator_rules": "system",
        "world_rules": "system",
        "character_card": "system",
        "turn_context": "system",
        "history": "history",
    }


def test_build_story_prompt_five_segments_in_order_with_roles():
    st = make_state(turn=1, transcript=[entry(1, "player", "我推门进来看看")])
    msgs = P.build_story_prompt(st, None, st, {})
    # 恰好 5 段，顺序 == PROMPT_SEGMENTS
    assert len(msgs) == 5
    assert [m["segment"] for m in msgs] == list(PROMPT_SEGMENTS)
    # 逐段 role 固定（前 4 system，末段 history）
    assert [m["role"] for m in msgs] == ["system", "system", "system", "system", "history"]
    for i, name in enumerate(PROMPT_SEGMENTS):
        assert msgs[i]["role"] == PROMPT_SEGMENT_ROLES[name]


def test_render_messages_always_five_even_when_empty():
    msgs = P.render_messages({})  # 空映射
    assert len(msgs) == 5
    assert [m["segment"] for m in msgs] == list(PROMPT_SEGMENTS)
    # 非 str 内容 → 空串（降级不崩）
    msgs2 = P.render_messages({"history": 123})
    assert by_segment(msgs2)["history"] == ""


# ===========================================================================
# 2. reroll 与 normal 差异 + reroll 零状态写入
# ===========================================================================

def test_reroll_differs_and_excludes_previous_narration():
    st = make_state(
        turn=2,
        transcript=[
            entry(1, "player", "我坐下了"),
            entry(1, "narrator", "你找了个位置坐下。"),
            entry(2, "player", "我想问她的名字"),
            entry(2, "narrator", "上一版的叙述文本X"),
        ],
    )
    snapshot = copy.deepcopy(st)

    normal = P.build_story_prompt(st, None, st, {}, mode="normal")
    reroll = P.build_story_prompt(st, None, st, {}, mode="reroll")

    # ★ reroll 零状态写入：传入的 state 未被修改
    assert st == snapshot

    normal_text = "\n".join(m["content"] for m in normal)
    reroll_text = "\n".join(m["content"] for m in reroll)

    # 两版确实不同
    assert normal_text != reroll_text
    # normal 携带本回合上一版文本；reroll **绝不**携带
    assert "上一版的叙述文本X" in normal_text
    assert "上一版的叙述文本X" not in reroll_text
    # reroll 带重写指令，normal 不带
    assert P.REROLL_DIRECTIVE in reroll_text
    assert P.REROLL_DIRECTIVE not in normal_text


def test_unknown_mode_falls_back_to_normal():
    st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
    assert P.build_story_prompt(st, None, st, {}, mode="bogus") == \
        P.build_story_prompt(st, None, st, {}, mode="normal")


# ===========================================================================
# 3. narrator_length 三档可区分
# ===========================================================================

def test_narrator_length_three_levels_distinct():
    outs = {}
    for length in NARRATOR_LENGTHS:
        st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
        segs = P.collect_segments(st, None, st, {}, settings={"narrator_length": length})
        outs[length] = segs["narrator_rules"]
    # 三档互不相同
    assert len({outs["short"], outs["medium"], outs["long"]}) == 3
    # 各含对应篇幅指令
    assert P.NARRATOR_LENGTH_INSTRUCTIONS["short"] in outs["short"]
    assert P.NARRATOR_LENGTH_INSTRUCTIONS["medium"] in outs["medium"]
    assert P.NARRATOR_LENGTH_INSTRUCTIONS["long"] in outs["long"]
    # 非法值回落 short
    st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
    segs = P.collect_segments(st, None, st, {}, settings={"narrator_length": "nope"})
    assert segs["narrator_rules"] == outs["short"]


# ===========================================================================
# 4. 世界书三落点各归其位 + 空落点行为
# ===========================================================================

def test_three_positions_map_to_correct_segments():
    head = mk_entry(1, "世界规则甲", "system_head", constant=True)
    tail = mk_entry(2, "本回合线索乙", "system_tail", keys=["照片"])
    deep = mk_entry(3, "历史深处丙", "history_depth", keys=["巷子"], depth=1)
    book = make_book([head, tail, deep])
    st = make_state(turn=1, transcript=[entry(1, "player", "我看看照片，又望向窗外的巷子")])

    segs = P.collect_segments(st, book, st, {})

    assert "世界规则甲" in segs["world_rules"]     # system_head → world_rules
    assert "本回合线索乙" in segs["turn_context"]  # system_tail → turn_context
    assert "历史深处丙" in segs["history"]          # history_depth → history

    # 不串位
    assert "世界规则甲" not in segs["turn_context"]
    assert "本回合线索乙" not in segs["world_rules"]
    assert "历史深处丙" not in segs["turn_context"]
    assert "世界规则甲" not in segs["history"]


def test_empty_position_still_five_segments_declared_behavior():
    book = make_book([])  # 空世界书
    st = make_state(turn=1, transcript=[entry(1, "player", "随便说点什么")])
    msgs = P.build_story_prompt(st, book, st, {})

    # 行为契约：恒定 5 段，段数不因空而减少
    assert len(msgs) == 5
    segs = by_segment(msgs)
    assert segs["world_rules"] == ""          # system_head 空 → 空段（明确）
    assert segs["turn_context"] != ""          # 本回合情境仍非空


def test_position_map_constant_matches_design():
    assert P.SEGMENT_POSITION_MAP == {
        "system_head": "world_rules",
        "system_tail": "turn_context",
        "history_depth": "history",
    }
    assert set(P.SEGMENT_POSITION_MAP) == set(LORE_POSITIONS)


# ===========================================================================
# 5. 摘要触发（时机 + 次数）与窗口
# ===========================================================================

def test_should_summarize_triggers_once_at_turn_8():
    hits = []
    for turn in range(1, 16):          # 15 拍（up_to_turn 恒 0）
        st = default_play()
        st["turn"] = turn
        if S.should_summarize(st):
            hits.append(turn)
    assert hits == [8]                 # 触发次数 == 1，时机 == 第 8 拍


def test_should_summarize_no_double_after_summarized():
    st = default_play()
    st["turn"] = 8
    st["summary"]["up_to_turn"] = 8    # 已摘要到第 8 拍 → 去重闸生效
    assert S.should_summarize(st) is False


def test_should_summarize_respects_settings_interval():
    hits = []
    for turn in range(1, 16):
        st = default_play()
        st["turn"] = turn
        if S.should_summarize(st, settings={"auto_summary_every": 5}):
            hits.append(turn)
    assert hits == [5, 10, 15]


def test_should_summarize_new_chapter_and_content_chapter_end():
    st = default_play()
    st["turn"] = 3
    assert S.should_summarize(st, new_chapter=True) is True     # 进入新章即触发
    assert S.should_summarize(st, {"chapter_end_turns": [3]}) is True
    assert S.should_summarize(st, {"chapter_end_turns": [4]}) is False


def test_history_window_keep_turns_effective():
    tr = [entry(i, "player", f"句{i:02d}") for i in range(1, 21)]  # 20 个不同拍
    win = S.history_window(tr, 14)
    assert len(win) == 14
    assert win[0]["turn"] == 7          # 最后 14 个不同拍 = 7..20
    assert win[-1]["turn"] == 20

    # 窗口在 prompt 的 history 段生效
    st = make_state(turn=20, transcript=tr)
    segs = P.collect_segments(st, None, st, {}, settings={"transcript_keep_turns": 14})
    assert "句20" in segs["history"]
    assert "句07" in segs["history"]
    assert "句06" not in segs["history"]  # 窗口外（更早的拍）已不在逐字窗口

    # keep_turns<=0 → 空窗口
    assert S.history_window(tr, 0) == []


# ===========================================================================
# 6. 摘要结构化 / 落盘读回降级
# ===========================================================================

def test_summary_is_structured_not_concatenation():
    st = default_play()
    st["turn"] = 9
    st["vars"]["poured"] = "long_night"
    st["vars"]["known"] = ["photo"]
    st["pending"] = [{"label": "问她照片里的人是谁", "transform": "ask_about", "args": {"topic": "photo"}}]

    summary = S.make_summary(st)
    assert isinstance(summary, dict)                       # 结构化字段（非裸字符串）
    assert set(summary) == set(S.SUMMARY_KEYS)             # 键集断言
    assert S.SUMMARY_KEYS == ("up_to_turn", "text", "generated_by", "verified")
    assert summary["up_to_turn"] == 9
    assert isinstance(summary["text"], str) and summary["text"]
    assert summary["text"].startswith("【前情提要】")
    assert summary["generated_by"] in ("local", "llm")
    assert isinstance(summary["verified"], bool)


def test_history_text_summary_heading_appears_exactly_once():
    """P2③：``history`` 段的「【前情提要】」标题**只出现一次**。

    旧缺陷：``summary.text`` 自带标题（``local_summary_text`` 以标题开头），
    ``history_text`` 又补一次 → 段落里出现两次标题。
    """
    st = make_state(turn=9, transcript=[entry(1, "player", "你好")])
    st["vars"]["poured"] = "long_night"

    local = S.local_summary_text(st)
    assert local.startswith(S.SUMMARY_HEADING), "前置：本地摘要应自带标题"

    # 自带标题的摘要（local 路径）→ 仍恰好一次
    hist = P.history_text(st, None, summary={"text": local})
    assert hist.count(S.SUMMARY_HEADING) == 1, f"标题重复出现：{hist!r}"
    assert hist.index(S.SUMMARY_HEADING) == 0

    # LLM 摘要**不带**标题 → 仍由 history 段恰好补一次
    hist2 = P.history_text(st, None, summary={"text": "你推门进来，她正在擦一只杯子。"})
    assert hist2.count(S.SUMMARY_HEADING) == 1, f"标题数量异常：{hist2!r}"
    assert "你推门进来" in hist2


def test_summary_sections_structured_fields():
    st = default_play()
    st["vars"]["poured"] = "long_night"
    st["vars"]["given"] = ["old_photo"]
    st["pending"] = [{"label": "问她名字"}]
    sections = S.summary_sections(st)
    assert set(sections) == {"facts", "relations", "open_threads"}
    # A2-5：面向 LLM 的摘要分片**不得**出现机器名（改前红：旧实现拼出 long_night / old_photo）
    assert any("点过一杯" in x for x in sections["facts"])
    assert sections["relations"], "「交给她东西」这件事没有记进 relations"
    assert all("_" not in x for x in sections["facts"] + sections["relations"])
    assert sections["open_threads"] == ["问她名字"]


def test_summary_sections_uses_content_labels_when_declared():
    """内容包声明了中文名表时，摘要分片用中文名（而不是机器名）。"""
    st = default_play()
    st["vars"]["poured"] = "long_night"
    st["vars"]["known"] = ["photo"]
    content = {"labels": {"long_night": "长夜酒", "photo": "那张照片"}}
    sections = S.summary_sections(st, content)
    assert any("长夜酒" in x for x in sections["facts"])
    assert any("那张照片" in x for x in sections["facts"])
    assert all("long_night" not in x and "photo" not in x
               for x in sections["facts"] + sections["relations"])


def test_normalize_summary_degrades_not_crash():
    # 缺字段 → 补默认
    d = S.normalize_summary({})
    assert set(S.SUMMARY_KEYS) <= set(d)
    assert d["up_to_turn"] == 0 and d["text"] == "" and d["generated_by"] == "" and d["verified"] is False

    # 类型错 → 逐字段回落，不崩
    d2 = S.normalize_summary({"up_to_turn": "x", "text": 123, "generated_by": [], "verified": "yes"})
    assert d2["up_to_turn"] == 0
    assert d2["text"] == ""
    assert d2["generated_by"] == ""
    assert d2["verified"] is False

    # 非 dict → 直接类默认
    assert S.normalize_summary(None) == default_summary()
    assert S.normalize_summary("坏档") == default_summary()

    # 未知字段保留（前向兼容）
    d3 = S.normalize_summary({"up_to_turn": 3, "future": 1})
    assert d3["future"] == 1


def test_make_summary_rejects_bad_and_keeps_old():
    st = default_play()
    st["turn"] = 8
    old = S.normalize_summary({"up_to_turn": 0, "text": "旧摘要", "generated_by": "local", "verified": False})
    st["summary"] = dict(old)

    # 越权臆断 → 拒绝入库（保留旧摘要）
    assert S.make_summary(st, llm_summarize=lambda src: "玩家的选择是什么，他想要一杯酒") == old
    # 超长 → 拒绝
    assert S.make_summary(st, llm_summarize=lambda src: "字" * (S.MAX_SUMMARY_CHARS + 1)) == old
    # 空 / 空白 → 拒绝
    assert S.make_summary(st, llm_summarize=lambda src: "   ") == old
    # 合法 LLM 文本 → 入库
    good = S.make_summary(st, llm_summarize=lambda src: "你推门进来，她正在擦一只杯子。")
    assert good["text"] == "你推门进来，她正在擦一只杯子。"
    assert good["generated_by"] == "llm" and good["verified"] is True


def test_make_summary_llm_exception_degrades_to_local():
    st = default_play()
    st["turn"] = 2

    def boom(src):  # noqa: ANN001 - 注入的假 LLM
        raise RuntimeError("模拟 LLM 不可用")

    out = S.make_summary(st, llm_summarize=boom)
    assert out["generated_by"] == "local"
    assert out["text"].startswith("【前情提要】")
    ok, _ = S.validate_summary(out["text"])
    assert ok is True


def test_validate_summary_pure():
    assert S.validate_summary("")[0] is False
    assert S.validate_summary(None)[0] is False
    assert S.validate_summary("字" * (S.MAX_SUMMARY_CHARS + 1))[0] is False
    assert S.validate_summary("玩家的选择")[0] is False
    assert S.validate_summary("你推门进来，她正在擦杯子。") == (True, "ok")


def test_apply_summary_is_pure_transform():
    st = default_play()
    st["turn"] = 8
    new = S.apply_summary(st, {"up_to_turn": 8, "text": "新情节", "generated_by": "local", "verified": True})
    assert new["summary"]["text"] == "新情节"
    assert new["summary"]["up_to_turn"] == 8
    assert st["summary"]["text"] == ""             # 入参未被改（深拷贝）
    assert new is not st
    # 非 dict 入参 → 空 dict（不崩）
    assert S.apply_summary(None, {}) == {}


# ===========================================================================
# 7. 纯函数性
# ===========================================================================

def test_prompt_is_deterministic():
    st = make_state(turn=3, transcript=[entry(1, "player", "甲"), entry(2, "narrator", "乙"), entry(3, "player", "丙")])
    book = make_book([mk_entry(1, "常驻规则", "system_head", constant=True)])
    a = P.build_story_prompt(st, book, st, {}, relation_ctx={"stage_name": "亲近", "self_ref": "我"})
    b = P.build_story_prompt(st, book, st, {}, relation_ctx={"stage_name": "亲近", "self_ref": "我"})
    assert a == b
    assert S.make_summary(st) == S.make_summary(st)


def test_relation_ctx_used_readonly_no_numbers():
    st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
    segs = P.collect_segments(st, None, st, {}, relation_ctx={"stage_name": "亲近", "self_ref": "我"})
    card = segs["character_card"]
    assert "亲近" in card and "我" in card
    # 只读提示，不产生数值展示（不出现明显数值分数字样）
    assert "好感" not in card


# ===========================================================================
# 8. 零 Qt
# ===========================================================================

def test_modules_have_no_qt_imports():
    for module in (P, S):
        src = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PySide6"), alias.name
                    assert alias.name.split(".")[0] not in {"PyQt5", "PyQt6", "PySide2"}
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert not mod.startswith("PySide6")
                assert mod.split(".")[0] not in {"PyQt5", "PyQt6", "PySide2"}


def test_namespace_has_no_qt_symbols():
    for module in (P, S):
        leaked = [n for n in dir(module) if n.startswith("Q") and n[1:2].isupper()]
        assert leaked == [], f"{module.__name__} 命名空间疑似泄漏 Qt 符号: {leaked}"


def test_public_api_all_names_exist():
    for name in P.__all__:
        assert hasattr(P, name), f"prompt.__all__ 声明的 {name} 不存在"
    for name in S.__all__:
        assert hasattr(S, name), f"summarize.__all__ 声明的 {name} 不存在"


# ===========================================================================
# 9. A2-5：面向 LLM 的文本不得出现机器名（节点 / 地点 / 变换 / var 值全覆盖）
# ===========================================================================

#: 机器名形态：``snake_case``（下划线连接）。
_MACHINE_RE = re.compile(r"[A-Za-z0-9]+_[A-Za-z0-9_]+")

#: 内容包里的机器名（下划线形态 + 单字形态都要从提示词 / 摘要里消失）。
_MACHINE_IDS = (
    "counter_photo", "move_to", "ask_about", "long_night", "old_photo",
    "counter", "photo", "guest", "drawer", "oil", "lantern",
)


def test_prompt_llm_text_has_no_machine_names():
    """五段式 prompt 里不得出现节点 / 地点 / 变换 / var 值的机器名。"""
    st = make_state(turn=2, transcript=[
        entry(1, "player", "我推门进来"),
        entry(2, "player", "我在吧台前坐下", transform="move_to", ok=True),
    ])
    st["node_id"] = "counter_photo"
    st["scene_id"] = "counter"
    st["vars"]["poured"] = "long_night"
    st["vars"]["held_items"] = ["letter"]
    st["vars"]["scene_items"] = ["lamp"]
    st["vars"]["given"] = ["old_photo"]
    st["vars"]["opened"] = ["drawer", "oil"]
    st["vars"]["known"] = ["photo", "guest", "name"]
    content = {"chapters": [{"chapter_id": "ch1", "title": "灯笼还亮着",
                             "nodes": [{"id": "counter_photo", "title": "吧台后的旧照片"}]}]}

    segs = P.collect_segments(st, None, st, content)
    blob = "\n".join(segs.values())

    found = _MACHINE_RE.findall(blob)
    assert not found, f"提示词里仍有下划线机器名：{found}"
    for machine in _MACHINE_IDS:
        assert machine not in blob, f"提示词里仍有机器名 {machine!r}"
    # 正向：节点用中文 title、变换用中文动词
    assert "吧台后的旧照片" in segs["turn_context"]
    assert "换了个地方" in segs["turn_context"]


def test_prompt_failure_reason_has_no_machine_code():
    """未生效分支不得把 ``precondition_failed:condition_not_met`` 这类原因码拼进提示词。"""
    st = make_state(turn=1, transcript=[
        entry(1, "player", "我试着开门", transform="open", ok=False,
              reason="precondition_failed:condition_not_met"),
    ])
    tc = P.collect_segments(st, None, st, {})["turn_context"]
    assert "precondition_failed" not in tc
    assert "condition_not_met" not in tc
    assert "_" not in tc, f"turn_context 里仍有机器名：{tc!r}"


def test_vars_summary_lines_humanized():
    """``vars`` 摘要行不得出现机器值。"""
    st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
    st["vars"]["poured"] = "long_night"
    st["vars"]["known"] = ["photo"]
    st["vars"]["opened"] = ["drawer"]
    blob = "\n".join(P.vars_summary_lines(st, {}))
    for machine in ("long_night", "photo", "drawer"):
        assert machine not in blob, f"vars 摘要里仍有机器名 {machine!r}"
    assert "点过" in blob and "问起过" in blob and "打开过" in blob


def test_prompt_uses_content_labels_when_declared():
    """内容包声明 ``labels``（机器名 → 中文名）时，场景 / 酒 / 话题都用中文名。"""
    st = make_state(turn=1, transcript=[entry(1, "player", "你好")])
    st["node_id"] = "counter_photo"
    st["scene_id"] = "counter"
    st["vars"]["poured"] = "long_night"
    st["vars"]["known"] = ["photo"]
    content = {"labels": {"counter": "吧台", "long_night": "长夜酒", "photo": "那张照片"}}

    tc = P.collect_segments(st, None, st, content)["turn_context"]
    assert "吧台" in tc and "长夜酒" in tc and "那张照片" in tc
    assert "counter" not in tc and "long_night" not in tc and "photo" not in tc


def test_summary_text_has_no_machine_names():
    """``local_summary_text`` / ``make_summary`` 产出（进 history 段）不得含机器名。"""
    st = default_play()
    st["turn"] = 9
    st["vars"]["poured"] = "long_night"
    st["vars"]["known"] = ["photo", "guest", "name"]
    st["vars"]["opened"] = ["drawer", "oil"]
    st["vars"]["given"] = ["old_photo"]
    st["vars"]["held_items"] = ["letter"]
    st["pending"] = [{"label": "问她照片里的人是谁"}]

    text = S.local_summary_text(st)
    found = _MACHINE_RE.findall(text)
    assert not found, f"前情提要里仍有机器名：{found}"
    for machine in _MACHINE_IDS:
        assert machine not in text, f"前情提要里仍有机器名 {machine!r}"

    summary = S.make_summary(st)
    assert not _MACHINE_RE.findall(summary["text"]), (
        f"make_summary 产出仍有机器名：{_MACHINE_RE.findall(summary['text'])}")
    assert S.validate_summary(summary["text"])[0] is True
