"""tests/test_v22_play_e2e.py —— 酒馆「真能玩」端到端断言（真 service + 真内容包）。

## 为什么必须有这个文件
之前酒馆的控件/面板用例**全部用桩**（`choices_changed.emit([...])`、`StubService.worldbook_entries()`），
于是三个「入口在、数据在、就是不通」的空壳一路绿到上线前：

* 🔴 ``play["pending"]`` **没有任何写入点** → 快捷动作排恒为空、玩家点不到任何选项；
* 🔴 ``worldbook_entries()`` 读的 ``library.books`` 恒为 ``[]`` → 「世界书」Tab 恒空；
* 🔴 **storylet 选择从未实现**（``prerequisites`` 无消费方）→ ``node_id`` 恒为 ``opening``，
    16 个 storylet 里 15 个（含两个结局）**永不可达**。

本文件一律走**真** ``TavernService`` + **真** ``gui/tavern/content/lantern`` 内容包，
只把 ``base_dir`` 指到 ``tmp_path``（绝不写真实 ``~/.maid_coder``）。
"""
from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Tuple

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.qt_compat import QApplication  # noqa: E402
from gui.tavern import engine as tavern_engine  # noqa: E402
from gui.tavern import model as tavern_model  # noqa: E402
from gui.tavern import service as svc_mod  # noqa: E402
from gui.tavern.service import FALLBACK_BOOK_ID, TavernService  # noqa: E402
from gui.tavern.worldbook import load_builtin_book, load_content  # noqa: E402

_REAL_TAVERN_DIR = Path.home() / ".maid_coder" / "tavern"


def _qapp() -> "QApplication":
    return QApplication.instance() or QApplication([])


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        api=None, cfg=None, config=None, theme_engine=None,
        companion=None, intimacy=None, page_manager=None,
    )


@pytest.fixture
def svc(tmp_path):
    """真 service（同步执行）+ 内容包，存档隔离到 tmp_path。"""
    _qapp()
    service = TavernService(_ctx(), base_dir=tmp_path, synchronous=True)
    yield service
    service.stop()


@pytest.fixture(autouse=True)
def _guard_real_user_dir():
    """断言本文件**绝不**创建/改动真实 ``~/.maid_coder/tavern``。"""
    before = _REAL_TAVERN_DIR.exists()
    yield
    assert _REAL_TAVERN_DIR.exists() == before, "测试污染了真实用户存档目录"


def _node_of(svc_: TavernService, node_id: str) -> dict:
    """从真实内容包里取节点定义。"""
    content = load_content(FALLBACK_BOOK_ID)
    for chapter in content["chapters"]:
        for node in chapter["nodes"]:
            if node.get("id") == node_id:
                return node
    raise AssertionError(f"内容包缺少节点：{node_id}")


# --------------------------------------------------------------------------- #
# ① 快捷动作排真的有内容（旧缺陷：pending 无写入点 → 恒空）
# --------------------------------------------------------------------------- #
def test_start_play_exposes_choices_from_initial_node(svc):
    """开局即应给出初始节点的选项，而不是空列表。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e1")

    choices = svc.current_choices()
    assert choices, "current_choices() 为空 —— pending 又没有写入点了"

    initial = _node_of(svc, "opening")
    assert {c["choice_id"] for c in choices} == {c["choice_id"] for c in initial["choices"]}
    for item in choices:
        assert item["label"], "选项缺少可显示文案"


def test_pending_snapshot_carries_transform_and_args(svc):
    """``pending[]`` 必须带 ``transform``/``args`` —— ``resolve_choice`` 靠它执行。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e2")
    pending = (svc.current_play() or {}).get("pending") or []
    assert pending
    for snap in pending:
        assert snap.get("choice_id")
        assert snap.get("transform"), f"缺少 transform，点了也没反应：{snap}"
        assert isinstance(snap.get("args"), dict)


# --------------------------------------------------------------------------- #
# ② 点选项真的执行变换，并推进故事（旧缺陷：node_id 恒为 opening）
# --------------------------------------------------------------------------- #
def test_clicking_choice_applies_transform_and_advances_node(svc):
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e3")
    before = dict(svc.current_play() or {})
    first = svc.current_choices()[0]["choice_id"]

    assert svc.submit(first, "choice") is True

    after = svc.current_play() or {}
    transcript = after.get("transcript") or []
    assert transcript, "点击后没有留痕"
    resolution = transcript[-1].get("resolution") or {}
    assert resolution.get("ok") is True, f"变换未成功：{resolution}"
    assert resolution.get("reason") == "ok"

    # 变换确实施加：turn 前进，且 scene/node 至少动了一个
    assert after.get("turn") == (before.get("turn") or 0) + 1
    moved = (after.get("node_id") != before.get("node_id")
             or after.get("scene_id") != before.get("scene_id"))
    assert moved, "点了选项但世界状态没有任何变化"

    # 选项换成了新节点的（旧选项消失）
    new_ids = {c["choice_id"] for c in svc.current_choices()}
    assert first not in new_ids, "推进后仍在提供旧节点的选项 —— node 没有真正推进"


def test_storylet_progression_crosses_chapters_and_reaches_ending(svc):
    """走完整一局：跨章推进，最终抵达 ``choices == []`` 的终局节点。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e4")

    visited = []
    for _ in range(40):
        play = svc.current_play() or {}
        node_id = play.get("node_id")
        visited.append(node_id)
        choices = svc.current_choices()
        if not choices:
            break
        pending = {p.get("choice_id"): p for p in (play.get("pending") or [])}
        pick = None
        for item in choices:
            snap = pending.get(item["choice_id"]) or {}
            args = snap.get("args") or {}
            if snap.get("transform") == "move_to" and args.get("target") == "backdoor":
                pick = item["choice_id"]
                break
        svc.submit(pick or choices[0]["choice_id"], "choice")
    else:
        pytest.fail(f"40 拍仍未抵达终局；轨迹={visited}")

    final = svc.current_play() or {}
    assert final.get("node_id", "").startswith("ending_"), \
        f"终局节点命名不符（应 ending_*）：{final.get('node_id')!r}"
    assert svc.current_choices() == [], "终局节点的选项排应为空"


def test_terminal_node_hides_action_row(svc):
    """终局节点：``pending`` 空 = 那一排正确隐藏（而不是被 quick_actions 兜成常驻）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e5")
    for _ in range(40):
        play = svc.current_play() or {}
        if (play.get("node_id") or "").startswith("ending_"):
            break
        choices = svc.current_choices()
        if not choices:
            break
        svc.submit(choices[0]["choice_id"], "choice")
    final = svc.current_play() or {}
    if (final.get("node_id") or "").startswith("ending_"):
        assert final.get("pending") == []


# --------------------------------------------------------------------------- #
# ③ 世界书 Tab 有内容（旧缺陷：library.books 恒空 → Tab 恒空）
# --------------------------------------------------------------------------- #
def test_worldbook_entries_fall_back_to_builtin_pack(svc):
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e6")
    snap = svc.worldbook_entries()

    builtin = load_builtin_book(FALLBACK_BOOK_ID)
    assert snap["entries"], "「世界书」Tab 没有条目 —— 内置包回落又断了"
    assert len(snap["entries"]) == len(builtin.entries)
    assert snap["title"], "世界书标题为空"
    assert snap["budget_chars"] > 0


def test_worldbook_hits_still_available_with_builtin_fallback(svc):
    """回落内置包**不影响**本拍命中（命中本来就是从内置包算的）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e7")
    svc.submit("我推门进去", "free")
    hits = svc.worldbook_hits()
    assert hits["entries"], "本拍世界书命中为空"


# --------------------------------------------------------------------------- #
# ④ 纯函数：prerequisites 判定是 fail-closed 的
# --------------------------------------------------------------------------- #
def test_prerequisites_met_is_fail_closed():
    assert svc_mod._prerequisites_met({}, {"scene_id": "counter"}) is True       # 无条件 = 通过
    assert svc_mod._prerequisites_met(None, {"scene_id": "counter"}) is True
    assert svc_mod._prerequisites_met({"scene_id": "counter"}, {"scene_id": "counter"}) is True
    assert svc_mod._prerequisites_met({"scene_id": "counter"}, {"scene_id": "table"}) is False
    # 键不在状态里 → 不放行（宁可少放行，也不误导进未满足的块）
    assert svc_mod._prerequisites_met({"poured": "long_night"}, {"scene_id": "counter"}) is False


def test_advance_node_keeps_current_when_no_candidate(svc):
    """没有候选时**保持当前节点**，绝不把玩家卡进没有选项的死路。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e8")
    play = svc.current_play()
    play["node_id"] = "not_a_real_node"
    assert svc._advance_node(play) is False
    assert play["node_id"] == "not_a_real_node"   # 未被推到某个无关节点


def test_unknown_node_falls_back_to_quick_actions(svc):
    """节点未知时，选项排回落 ``quick_actions``（而不是空死）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e9")
    play = svc.current_play()
    play["node_id"] = "not_a_real_node"
    svc._sync_pending(play)
    content = load_content(FALLBACK_BOOK_ID)
    assert {p["choice_id"] for p in play["pending"]} == {
        a["action_id"] for a in content["quick_actions"]
    }


# --------------------------------------------------------------------------- #
# ⑤ 叙述流回显：选项只出中文，机器名不得上屏 / 进存档 / 进提示词（P0）
# --------------------------------------------------------------------------- #
def test_choice_echo_writes_chinese_label_not_machine_id(svc):
    """点选项后，玩家条的 ``text`` 必须是该选项的中文 label，而不是 ``sit_down``。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-echo")
    first = svc.current_choices()[0]
    assert svc.submit(first["choice_id"], "choice") is True

    transcript = (svc.current_play() or {}).get("transcript") or []
    players = [e for e in transcript if e.get("role") == "player"]
    assert players, "点选项后没有留下玩家条"
    assert players[-1]["text"] == first["label"], (
        f"玩家条写的是机器名而非中文文案：{players[-1]['text']!r} != {first['label']!r}")
    assert "_" not in players[-1]["text"], f"玩家条里仍有下划线机器名：{players[-1]['text']!r}"

    # 机器级留痕（resolution）保持原样，不回退、不丢键
    assert set(players[-1]["resolution"]) == set(tavern_model.RESOLUTION_REQUIRED_KEYS)

    # 「今夜」Tab 读到的那一行（UI 真正渲染的面）同样是中文
    narr_players = [e for e in svc.current_narrative() if e["role"] == "player"]
    assert narr_players[-1]["text"] == first["label"]


def test_turn_context_never_contains_machine_choice_id(svc, tmp_path):
    """构造出的 prompt（含 ``turn_context``）里不得出现 ``sit_down`` 这类机器名。"""
    captured: list = []

    class _Api:
        def chat(self, *_a, **_k):  # noqa: D401 - 桩
            return ""

        def chat_stream_chunks(self, messages, **_k):
            captured.append(messages)
            return iter(["夜里的风停了，她没抬头。"])

    ctx = _ctx()
    ctx.api = _Api()
    ctx.cfg = SimpleNamespace(api_provider="deepseek", api_key="sk-test")
    ctx.config = ctx.cfg

    service = TavernService(ctx, base_dir=tmp_path / "llm", synchronous=True)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="e2e-ctx")
        first = service.current_choices()[0]
        assert service.submit(first["choice_id"], "choice") is True

        assert captured, "叙述走的是 LLM 桩，应当捕获到 messages"
        blob = "\n".join(
            str(m.get("content")) for m in captured[-1] if isinstance(m, dict)
        )
        assert first["label"] in blob, "中文动作没有进 turn_context"
        assert first["choice_id"] not in blob, (
            f"机器名 {first['choice_id']!r} 泄漏进了提示词")
        # 更严格：开局那一排选项的机器名一个都不该出现
        assert not any(c["choice_id"] in blob for c in service.current_choices())
    finally:
        service.stop()


# --------------------------------------------------------------------------- #
# ⑥ 选项前置条件：不满足的选项不进选项排（旧缺陷：prerequisites 无消费方）
# --------------------------------------------------------------------------- #
def test_pending_filters_choices_by_prerequisites(svc, monkeypatch):
    """节点 ``choices[].prerequisites`` 不满足 → 不进选项排；未写的照旧放行。"""
    import copy as _copy

    patched = _copy.deepcopy(load_content(FALLBACK_BOOK_ID))
    node = None
    for chapter in patched["chapters"]:
        for item in chapter["nodes"]:
            if item.get("id") == "opening":
                node = item
    assert node is not None
    node["choices"] = [
        {"choice_id": "gated_ok", "label": "坐下（条件已满足）", "transform": "wait",
         "prerequisites": {"scene_id": ""}},
        {"choice_id": "gated_no", "label": "开后门（条件未满足）", "transform": "wait",
         "prerequisites": {"poured": "long_night"}},
        {"choice_id": "no_gate", "label": "环顾四周（未写条件）", "transform": "wait"},
    ]
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_content",
        lambda pack_id="lantern", **kw: patched,
    )

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-gate")
    ids = [c["choice_id"] for c in svc.current_choices()]

    assert "gated_ok" in ids, "条件已满足的选项被误过滤"
    assert "no_gate" in ids, "未写 prerequisites 的选项被误过滤（破坏向后兼容）"
    assert "gated_no" not in ids, "条件未满足的选项仍然出现在选项排里"


def test_pending_prerequisite_filter_uses_scene_and_vars(svc, monkeypatch):
    """过滤用的是 ``vars`` ∪ ``{scene_id}``（与 ``_advance_node`` 同一把尺子）。"""
    import copy as _copy

    patched = _copy.deepcopy(load_content(FALLBACK_BOOK_ID))
    for chapter in patched["chapters"]:
        for item in chapter["nodes"]:
            if item.get("id") == "opening":
                item["choices"] = [
                    {"choice_id": "needs_counter", "label": "（要柜台）", "transform": "wait",
                     "prerequisites": {"scene_id": "counter"}},
                ]
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_content",
        lambda pack_id="lantern", **kw: patched,
    )

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-gate2")
    assert svc.current_choices() == []          # 开局 scene_id 为空 → 不满足

    play = svc.current_play()
    play["scene_id"] = "counter"                # 只改 scene_id（不落盘、不走引擎）
    svc._sync_pending(play)
    assert [c["choice_id"] for c in svc.current_choices()] == ["needs_counter"]


# --------------------------------------------------------------------------- #
# ⑦ 终局：status 收束 + 跨局 journal 留痕（旧缺陷：status 恒 active、append_journal 无调用者）
# --------------------------------------------------------------------------- #
def _walk_to_ending(svc_) -> dict:
    """一路点下去直到终局节点（返回终局时的 play）。

    优先走 ``move_to → backdoor``：终局节点（``ending_*``）的前置都是 ``scene_id == backdoor``，
    盲点第一个选项会一直在中段打转（与既有 e2e 用例同一走法）。
    """
    for _ in range(40):
        play = svc_.current_play() or {}
        if (play.get("node_id") or "").startswith("ending_"):
            return play
        choices = svc_.current_choices()
        if not choices:
            return play
        pending = {p.get("choice_id"): p for p in (play.get("pending") or [])}
        pick = None
        for item in choices:
            snap = pending.get(item["choice_id"]) or {}
            args = snap.get("args") or {}
            if snap.get("transform") == "move_to" and args.get("target") == "backdoor":
                pick = item["choice_id"]
                break
        svc_.submit(pick or choices[0]["choice_id"], "choice")
    pytest.fail("40 拍仍未抵达终局")


def test_terminal_node_sets_ended_status_and_journals_ending(svc, tmp_path):
    """终局节点 → ``play["status"] == "ended"``，且 journal 记下**结局的名字**。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-end")
    play = _walk_to_ending(svc)

    assert play.get("node_id", "").startswith("ending_"), f"没走到终局：{play.get('node_id')!r}"
    assert play.get("status") == "ended", "终局后 status 仍不是 ended"

    # 落盘（单写点）后 journal 里必须有这条结局；内容是自然语言，不含数字 / 序号
    data = json.loads((tmp_path / "tavern.json").read_text(encoding="utf-8"))
    endings = (data.get("journal") or {}).get("seen_endings") or []
    assert endings, "journal.seen_endings 为空 —— append_journal 又没有调用者了"

    ending_node = _node_of(svc, play["node_id"])
    assert endings[-1] == ending_node["title"], "journal 记的应是结局的名字（自然语言）"
    assert not any(ch.isdigit() for ch in endings[-1]), f"journal 里出现了数值/序号：{endings[-1]!r}"
    assert "_" not in endings[-1], f"journal 里出现了机器名：{endings[-1]!r}"


def test_active_play_keeps_active_status(svc):
    """非终局拍不得被误标为 ended（口径从严）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-active")
    svc.submit(svc.current_choices()[0]["choice_id"], "choice")
    assert (svc.current_play() or {}).get("status") == "active"


# --------------------------------------------------------------------------- #
# ⑧ 章末摘要：should_summarize 必须收到 new_chapter（旧缺陷：恒不传 → 永不触发）
# --------------------------------------------------------------------------- #
def test_chapter_change_passes_new_chapter_to_should_summarize(svc, monkeypatch):
    """换章那一拍必须把 ``new_chapter=True`` 传下去，并因此触发摘要。"""
    seen: list = []
    real = svc_mod.tavern_summarize.should_summarize

    def _spy(play, content=None, *, settings=None, new_chapter=False):
        result = real(play, content, settings=settings, new_chapter=new_chapter)
        seen.append((play.get("turn"), bool(new_chapter), bool(result)))
        return result

    monkeypatch.setattr(svc_mod.tavern_summarize, "should_summarize", _spy)

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-chapter")
    for _ in range(40):
        choices = svc.current_choices()
        if not choices:
            break
        svc.submit(choices[0]["choice_id"], "choice")

    crossing = [(t, res) for t, nc, res in seen if nc]
    assert crossing, "整局走完都没有任何一拍带上 new_chapter=True"
    # 触发它的必须是「换章」，不是「每 8 拍」那条规则（否则本用例证明不了接线）
    assert all((t or 0) % 8 != 0 for t, _ in crossing), f"new_chapter 与周期规则重合，无法区分：{crossing}"
    assert any(res for _t, res in crossing), "传了 new_chapter 却仍没触发摘要"
    assert not all(nc for _t, nc, _r in seen), "new_chapter 被写死成恒 True"
    assert svc.current_summary().get("up_to_turn", 0) > 0, "摘要没有真正生成"


# --------------------------------------------------------------------------- #
# ⑨ 世界书：rng / ledger 真的被传下去（旧缺陷：probability 恒不生效、sticky/cooldown 无消费方）
# --------------------------------------------------------------------------- #
def test_worldbook_collect_receives_deterministic_rng_and_ledger(svc, monkeypatch):
    """``_worldbook_for`` 必须给 ``collect`` 传 rng（由 seed+turn 派生）与激活账本。"""
    captured: list = []
    real_collect = svc_mod.tavern_worldbook.WorldBook.collect

    def _spy(self, recent_texts, *, rng=None, turn=None, ledger=None):
        captured.append((rng, turn, ledger))
        return real_collect(self, recent_texts, rng=rng, turn=turn, ledger=ledger)

    monkeypatch.setattr(svc_mod.tavern_worldbook.WorldBook, "collect", _spy)

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-lore-wire", seed=4242)
    assert captured, "开局首帧就应取一次世界书"
    rng, _turn, ledger = captured[-1]
    assert rng is not None and hasattr(rng, "randint"), "probability 的 rng 没有传下去"
    assert isinstance(ledger, dict), "sticky/cooldown 的账本没有传下去"

    # 确定性：同 seed + 同拍 ⇒ 同一次抽取
    play = svc.current_play() or {}
    expect = tavern_engine.derive_rng(play["seed"], play["turn"]).randint(1, 100)
    assert rng.randint(1, 100) == expect, "rng 不是由 seed+turn 确定性派生的"


def test_real_pack_sticky_entry_is_recorded_in_ledger(svc):
    """真实内容包里 ``照片`` 条目带 ``sticky``；它被关键词激活后必须写进账本。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-lore-ledger")
    assert svc.submit("我看看吧台后的旧照片", "free") is True

    ledger = svc._lore_ledgers.get(svc.current_play_id()) or {}
    assert 11 in ledger, f"sticky 条目没有被记账（账本={ledger}）—— sticky 仍是假机制"


def test_lore_ledger_is_isolated_per_play(svc):
    """账本按局隔离，删局即清（不跨局串味）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-ledger-a")
    svc.submit("我看看吧台后的旧照片", "free")
    assert 11 in (svc._lore_ledgers.get("e2e-ledger-a") or {})

    svc.delete_play("e2e-ledger-a")
    assert "e2e-ledger-a" not in svc._lore_ledgers


# --------------------------------------------------------------------------- #
# ⑩ 首帧世界书快照（旧缺陷：start_play / load_play 不跑 _worldbook_for → turn=0 恒空）
# --------------------------------------------------------------------------- #
def test_start_play_primes_worldbook_snapshot(svc):
    """开局（turn=0）就应拿到世界书快照，而不是等到第一拍之后。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-prime")
    hits = svc.worldbook_hits()
    assert hits["entries"], "turn=0 时「世界书」Tab 仍为空 —— start_play 没跑 _worldbook_for"


def test_load_play_primes_worldbook_snapshot(svc):
    """载入旧档同样要补快照（否则切局后 Tab 先空一拍）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-prime2")
    svc._last_selection = None            # 模拟「刚重启 / 刚切局」的冷快照
    assert svc.worldbook_hits()["entries"] == []

    assert svc.load_play("e2e-prime2") is True
    assert svc.worldbook_hits()["entries"], "load_play 没有补世界书快照"


# --------------------------------------------------------------------------- #
# ⑪ A2-1（P0）：提示词与「世界书」Tab 快照吃**同一份** rng/ledger
#
# 旧缺陷：`_worldbook_for` 把 rng/ledger 喂给了 collect，但结果**只**存进
# `_last_selection`（Tab）；提示词由 `prompt._collect_worldbook` **另起一次**
# `collect(recent_texts, turn=…)` —— 不传 rng、不传 ledger。于是
# `probability` / `sticky` / `cooldown` 对 LLM **完全无效**，且 Tab 与提示词可能不一致。
# 下面用「概率归零 / 冷却中」两个反例证明：改后它们**真的改变了 LLM 看到的东西**。
# --------------------------------------------------------------------------- #

def _load_result(entries: list):
    """构造一个假的 ``LoadResult``（只带条目，供 monkeypatch 内置世界书加载）。"""
    from gui.tavern.worldbook import LoadResult
    return LoadResult(entries=entries)


def _wb_entry(uid: int, content: str, *, keys=(), position: str = "system_tail",
              probability: int = 100, cooldown: int = 0, sticky: int = 0,
              constant: bool = False) -> dict:
    """从类默认出发造一条世界书条目（字段齐全）。"""
    entry = tavern_model.default_worldbook_entry()
    entry.update(
        uid=uid, title=f"条目{uid}", keys=list(keys), content=content,
        position=position, probability=probability, cooldown=cooldown,
        sticky=sticky, constant=constant, enabled=True,
    )
    return entry


def _player_line(text: str, turn: int = 0) -> dict:
    """造一条 ``transcript`` 玩家留痕（供世界书关键词扫描）。"""
    return {"turn": turn, "role": "player", "input_kind": "free", "text": text,
            "resolution": {}, "narrated": True, "at": ""}


def _prompt_blob(svc_, play: dict, content: dict = None, *, mode: str = "normal") -> str:
    """走**真实** service 路径取本拍提示词全文（`_worldbook_for` → `_render_messages`）。"""
    if content is None:
        content = svc_._content_for(FALLBACK_BOOK_ID)
    settings = svc_._settings()
    book = svc_._worldbook_for(play, settings)
    msgs = svc_._render_messages(play, content, settings, mode=mode, book=book)
    return "\n".join(str(m.get("content")) for m in msgs if isinstance(m, dict))


def test_prompt_worldbook_entries_equal_tab_snapshot(svc):
    """硬性验收：**提示词里的世界书条目集合 == Tab 快照条目集合**。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a21-eq")
    assert svc.submit("我看看吧台后的那张旧照片", "free") is True

    play = svc.current_play() or {}
    blob = _prompt_blob(svc, play)

    tab = {e["content"] for e in svc.worldbook_hits()["entries"]}
    assert tab, "本拍世界书命中为空，断言会挂空"

    all_entries = svc.worldbook_entries()["entries"]
    in_prompt = {e["content"] for e in all_entries if e.get("content") and e["content"] in blob}
    assert in_prompt == tab, f"提示词世界书集合 {in_prompt} != Tab 快照 {tab}"


def test_probability_changes_what_llm_sees(svc, monkeypatch):
    """反例①：``probability`` 未中签的条目**必须**从提示词里消失（改前：提示词恒有它）。

    口径：``probability<=0`` 即便无 rng 也被抑制，**区分不出**两条路径，故这里取
    「本拍确定性抽签值 - 1」当 ``probability`` —— 有 rng → 未中签；无 rng → 恒真命中。
    """
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a21-prob")
    play = svc.current_play()
    seed = play.get("seed")
    turn, draw = 1, 1
    for candidate in range(1, 60):
        value = tavern_engine.derive_rng(seed, candidate).randint(1, 100)
        if value > 1:
            turn, draw = candidate, value
            break
    assert draw > 1, "找不到可用的确定性抽签值，断言会挂空"
    prob = draw - 1                      # 有 rng：draw <= prob 为假 → 未中签

    entries = [
        _wb_entry(1, "常驻规则甲", keys=[], position="system_head", constant=True),
        _wb_entry(2, "关键词命中乙", keys=["照片"]),
        _wb_entry(3, "概率未中丙", keys=["照片"], probability=prob),
    ]
    monkeypatch.setattr(svc_mod.tavern_worldbook, "load_builtin_book",
                        lambda *a, **k: _load_result(entries))

    play["turn"] = turn
    play["transcript"] = [_player_line("我想看看那张照片", turn=turn)]

    blob = _prompt_blob(svc, play)
    assert "关键词命中乙" in blob, "命中条目没有进提示词，断言会挂空"
    assert "概率未中丙" not in blob, (
        "probability 未中签却仍进了提示词 —— 世界书 rng 仍未喂给提示词路径")

    tab = {e["content"] for e in svc.worldbook_hits()["entries"]}
    assert "概率未中丙" not in tab
    in_prompt = {e["content"] for e in entries if e["content"] in blob}
    assert in_prompt == tab, f"提示词 {in_prompt} != Tab {tab}"


def test_cooldown_changes_what_llm_sees(svc, monkeypatch):
    """反例②：``cooldown`` 内的条目**必须**从提示词里消失（改前：提示词仍有它）。"""
    entries = [
        _wb_entry(1, "常驻规则甲", keys=[], position="system_head", constant=True),
        _wb_entry(4, "冷却中的线索丁", keys=["照片"], cooldown=3),
    ]
    monkeypatch.setattr(svc_mod.tavern_worldbook, "load_builtin_book",
                        lambda *a, **k: _load_result(entries))

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a21-cool")
    play = svc.current_play()
    play["turn"] = 6
    play["transcript"] = [_player_line("我想看看那张照片", turn=5)]
    # 上一拍（第 5 拍）刚由关键词激活 → 第 6 拍仍在 cooldown=3 的抑制窗口内
    svc._lore_ledgers["e2e-a21-cool"] = {4: 5}

    blob = _prompt_blob(svc, play)
    assert "冷却中的线索丁" not in blob, (
        "cooldown 没有改变提示词 —— 世界书 ledger 仍未喂给提示词路径")
    tab = {e["content"] for e in svc.worldbook_hits()["entries"]}
    assert "冷却中的线索丁" not in tab


def test_sticky_keeps_entry_in_prompt_without_keyword(svc, monkeypatch):
    """反例③：``sticky`` 保活的条目**没有关键词命中也要进提示词**（改前：提示词里没有）。"""
    entries = [
        _wb_entry(1, "常驻规则甲", keys=[], position="system_head", constant=True),
        _wb_entry(5, "余温未散的线索戊", keys=["绝不会出现的词"], sticky=3),
    ]
    monkeypatch.setattr(svc_mod.tavern_worldbook, "load_builtin_book",
                        lambda *a, **k: _load_result(entries))

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a21-sticky")
    play = svc.current_play()
    play["turn"] = 2
    play["transcript"] = [_player_line("我什么都没提", turn=1)]
    svc._lore_ledgers["e2e-a21-sticky"] = {5: 1}   # 第 1 拍激活 → sticky=3 保活到第 4 拍

    blob = _prompt_blob(svc, play)
    assert "余温未散的线索戊" in blob, (
        "sticky 保活的条目没有进提示词 —— 世界书 ledger 仍未喂给提示词路径")


# --------------------------------------------------------------------------- #
# ⑫ A2-2（P0）：绑定书分支**不得**提前 return（否则 Tab 恒空 / 陈旧）
# --------------------------------------------------------------------------- #

def test_binding_book_refreshes_tab_and_matches_prompt(svc):
    """用户自建世界书（``library.books`` 绑定书）走的正是这条路径。"""
    entries = [
        _wb_entry(1, "绑定书常驻规则", keys=[], position="system_head", constant=True),
        _wb_entry(2, "绑定书命中线索", keys=["照片"]),
    ]
    data = svc._ensure_loaded()
    library = data.setdefault("library", {})
    library.setdefault("books", []).append(
        {"book_id": FALLBACK_BOOK_ID, "title": "我的世界书", "entries": entries})

    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a22")
    assert svc.worldbook_hits()["entries"], (
        "绑定书场景下「世界书」Tab 恒空 —— _worldbook_for 在绑定书分支提前 return 了")

    play = svc.current_play()
    play["transcript"] = [_player_line("我想看看那张照片")]
    blob = _prompt_blob(svc, play)
    assert "绑定书命中线索" in blob, "绑定书的世界书条目没有进提示词"

    tab = {e["content"] for e in svc.worldbook_hits()["entries"]}
    in_prompt = {e["content"] for e in entries if e["content"] in blob}
    assert in_prompt == tab, f"绑定书：提示词 {in_prompt} != Tab {tab}"


# --------------------------------------------------------------------------- #
# ⑬ A2-3（P1）：终局之后不得再推进（旧缺陷：submit 不看 status）
# --------------------------------------------------------------------------- #

def test_submit_rejected_after_ending(svc, tmp_path):
    """终局（``status == "ended"``）后 ``submit`` 必须返回 ``False``，不写状态、不追加 journal。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a23")
    play = _walk_to_ending(svc)
    assert play.get("status") == "ended", "没走到终局，断言会挂空"

    before = json.loads((tmp_path / "tavern.json").read_text(encoding="utf-8"))
    endings_before = list((before.get("journal") or {}).get("seen_endings") or [])
    node_before = play.get("node_id")
    turn_before = play.get("turn")
    len_before = len(play.get("transcript") or [])

    assert svc.submit("sit_down", "choice") is False, "终局后 submit 仍被接受"
    assert svc.submit("我还想说点什么", "free") is False, "终局后自由输入仍被接受"

    after = json.loads((tmp_path / "tavern.json").read_text(encoding="utf-8"))
    endings_after = list((after.get("journal") or {}).get("seen_endings") or [])
    assert endings_after == endings_before, f"终局后又记了结局：{endings_after}"

    play2 = svc.current_play() or {}
    assert play2.get("node_id") == node_before, "终局后 node_id 被推进了"
    assert play2.get("turn") == turn_before, "终局后拍数被推进了"
    assert len(play2.get("transcript") or []) == len_before, "终局后 transcript 被追加了"


def test_reroll_still_works_after_ending(svc):
    """终局闸**不得**误伤只读操作：``reroll`` / ``edit_narration`` 仍可用。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a23b")
    play = _walk_to_ending(svc)
    assert play.get("status") == "ended"

    turn = max(e.get("turn") or 0 for e in play.get("transcript") or [])
    assert svc.reroll(turn) is True, "终局后 reroll 被误伤"
    assert svc.edit_narration(turn, "她只是把灯芯拨亮了一点。") is True, "终局后改字被误伤"


# --------------------------------------------------------------------------- #
# ⑭ A2-4（P1）：``choice`` 档查不到 label 时**绝不** fail-open 写机器名
# --------------------------------------------------------------------------- #

def test_choice_echo_never_writes_machine_id_when_label_missing(svc):
    """内容包也查不到的 ``choice_id`` → 中性中文占位（旧实现：``or text`` 写回机器名）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a24")
    assert svc.submit("not_a_real_choice_id", "choice") is True

    players = [e for e in (svc.current_play() or {}).get("transcript") or []
               if e.get("role") == "player"]
    assert players, "没有留下玩家条"
    assert players[-1]["text"] == svc_mod.NEUTRAL_CHOICE_ECHO, (
        f"fail-open 写回了机器名：{players[-1]['text']!r}")
    assert "not_a_real_choice_id" not in players[-1]["text"]
    assert all("_" not in (e.get("text") or "") for e in players), (
        f"transcript 里出现机器名：{[e.get('text') for e in players]}")


def test_second_submit_of_stale_choice_id_never_writes_machine_id(svc):
    """验证者反例：第二次 ``submit('sit_down')`` —— 机器名不得写回存档。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-a24b")
    assert svc.submit("sit_down", "choice") is True
    assert svc.submit("sit_down", "choice") is True   # 第二拍：sit_down 已不在 pending

    players = [e for e in (svc.current_play() or {}).get("transcript") or []
               if e.get("role") == "player"]
    assert all("sit_down" not in (e.get("text") or "") for e in players), (
        f"机器名 fail-open 写回了存档：{[e.get('text') for e in players]}")
    # 内容包反查得到中文 label → 玩家条应是中文
    assert players[-1]["text"] and "_" not in players[-1]["text"]


# --------------------------------------------------------------------------- #
# ⑮ 批次 B-1：``prerequisites`` 条件算子（has / has_all / has_not / not）
#
# 旧缺陷：``_prerequisites_met`` 是**严格等值** —— 而 ``opened`` / ``known`` /
# ``held_items`` / ``scene_items`` / ``given`` 这 5 个基底变量**全是列表型**，
# 列表永不等于字符串 ⇒ 这 5 个变量**完全无法用于分支**。本批（经用户批准）新增
# 算子形态，让「已被维护、但查询不到」的列表变量第一次真正可用。
# --------------------------------------------------------------------------- #

def _operator_pack() -> dict:
    """最小内容包：两个**只由算子区分**的 storylet 节点 + 一条算子门控的选项。

    ``letter_seen``   前置 = ``{"opened": {"has": "letter"}}``
    ``letter_unseen`` 前置 = ``{"opened": {"has_not": "letter"}}``
    两者互斥 —— 谁被推进，完全取决于 ``opened`` 列表里有没有 ``letter``。
    """
    return {
        "book_id": FALLBACK_BOOK_ID,
        "node_ids": ["opening", "letter_seen", "letter_unseen"],
        "scene_ids": ["counter"],
        "reachable": {"": ["counter"], "counter": ["counter"]},
        "known_topics": {"": [], "counter": []},
        "menu": {"": [], "counter": []},
        "open_conditions": {"letter": True},
        "openable": ["letter"],
        "var_names": [],
        "worldbook": {"title": "灯笼酒馆"},
        "chapters": [{
            "chapter_id": "ch1",
            "title": "灯笼还亮着",
            "nodes": [
                {"id": "opening", "title": "开局", "text": "她推来一只杯子。",
                 "prerequisites": {}, "effects": [],
                 "choices": [
                     {"choice_id": "open_letter", "label": "拆开那封信",
                      "transform": "open", "args": {"key": "letter"}},
                     {"choice_id": "wait_here", "label": "先坐一会儿", "transform": "wait"},
                     {"choice_id": "gated_by_opened", "label": "把信纸摊开再看一眼",
                      "transform": "wait", "prerequisites": {"opened": {"has": "letter"}}},
                 ]},
                {"id": "letter_seen", "title": "读过信", "text": "信纸上只有半行字。",
                 "prerequisites": {"opened": {"has": "letter"}}, "effects": [],
                 "choices": [{"choice_id": "seen_next", "label": "把信收好", "transform": "wait"}]},
                {"id": "letter_unseen", "title": "还没读", "text": "信封还没拆。",
                 "prerequisites": {"opened": {"has_not": "letter"}}, "effects": [],
                 "choices": [{"choice_id": "unseen_next", "label": "先喝一口", "transform": "wait"}]},
            ],
        }],
        "quick_actions": [],
    }


@pytest.fixture
def operator_svc(tmp_path, monkeypatch):
    """真 service + 算子内容包（存档隔离到 tmp_path）。"""
    _qapp()
    pack = _operator_pack()
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_content",
        lambda pack_id=FALLBACK_BOOK_ID, **kw: pack,
    )
    service = TavernService(_ctx(), base_dir=tmp_path / "op", synchronous=True)
    yield service
    service.stop()


def test_operator_forms_supported_and_fail_closed():
    """5 种形态全部生效；fail-closed 全分支一律不通过且**不抛异常**。"""
    ok = svc_mod._prerequisites_met
    st = {"opened": ["drawer", "letter"], "poured": "long_night",
          "known": "photo", "scene_id": "counter"}

    # ① 原样：严格等值
    assert ok({"scene_id": "counter"}, st) is True
    assert ok({"scene_id": "table"}, st) is False
    # ② has
    assert ok({"opened": {"has": "drawer"}}, st) is True
    assert ok({"opened": {"has": "latch"}}, st) is False
    # ③ has_all
    assert ok({"opened": {"has_all": ["drawer", "letter"]}}, st) is True
    assert ok({"opened": {"has_all": ["drawer", "latch"]}}, st) is False
    # ④ has_not
    assert ok({"opened": {"has_not": "latch"}}, st) is True
    assert ok({"opened": {"has_not": "drawer"}}, st) is False
    # ⑤ not（标量）
    assert ok({"poured": {"not": "short_night"}}, st) is True
    assert ok({"poured": {"not": "long_night"}}, st) is False
    # 多键混合
    assert ok({"scene_id": "counter", "opened": {"has": "letter"}}, st) is True
    assert ok({"scene_id": "counter", "opened": {"has": "latch"}}, st) is False

    # —— fail-closed（一律 False 且不抛）——
    assert ok({"missing": {"has": "x"}}, st) is False                       # 缺键
    assert ok({"opened": {"has": "drawer", "has_not": "latch"}}, st) is False  # >1 算子
    assert ok({"opened": {"contains": "drawer"}}, st) is False              # 未知算子
    assert ok({"opened": {}}, st) is False                                  # 空算子 dict
    assert ok({"known": {"has": "photo"}}, st) is False                     # has 用于非列表
    assert ok({"poured": {"has": "long_night"}}, st) is False               # has 用于标量
    assert ok({"poured": {"has_all": ["x"]}}, st) is False                  # has_all 用于非列表
    assert ok({"poured": {"has_not": "x"}}, st) is False                    # has_not 用于非列表
    assert ok({"opened": {"not": "drawer"}}, st) is False                   # not 用于列表
    assert ok({"opened": {"has_all": "drawer"}}, st) is False               # has_all 取值非 list
    assert ok({"opened": {"has": "drawer"}}, None) is False                 # 状态非 dict
    assert ok({1: "x"}, st) is False                                        # 键非 str


def test_operator_has_gates_storylet_advancement(operator_svc):
    """「打开信」这条路上，``has`` 算子把节点推进到 ``letter_seen``。"""
    svc = operator_svc
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-op-has")
    assert svc.submit("open_letter", "choice") is True

    play = svc.current_play() or {}
    assert play["vars"]["opened"] == ["letter"], "open 变换没有把 letter 记进 opened"
    assert play["node_id"] == "letter_seen", (
        f"has 算子未生效：node_id={play['node_id']!r}（应 letter_seen）")


def test_operator_has_not_gates_storylet_advancement(operator_svc):
    """「不打开信」这条路上，``has_not`` 算子把节点推进到 ``letter_unseen``。"""
    svc = operator_svc
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-op-hasnot")
    assert svc.submit("wait_here", "choice") is True

    play = svc.current_play() or {}
    assert play["vars"]["opened"] == [], "wait 不应改动 opened"
    assert play["node_id"] == "letter_unseen", (
        f"has_not 算子未生效：node_id={play['node_id']!r}（应 letter_unseen）")


def test_operator_filters_choices_via_sync_pending(operator_svc):
    """算子同样作用在**选项准入**（``_sync_pending``）上，而不只是节点推进。"""
    svc = operator_svc
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-op-pending")
    play = svc.current_play()

    ids = {c["choice_id"] for c in svc.current_choices()}
    assert "gated_by_opened" not in ids, "opened=[] 时 has 门控的选项仍出现"

    play["vars"]["opened"] = ["letter"]      # 只改状态，不落盘
    svc._sync_pending(play)
    assert "gated_by_opened" in {c["choice_id"] for c in svc.current_choices()}, (
        "opened 含 letter 后，has 门控的选项仍未放行")


def test_operator_has_all_empty_list_is_fail_closed():
    """★ 批次 C（C-0②）：``{"key": {"has_all": []}}`` 原本**恒真**（vacuous truth）。

    ``all(…)`` 对空表恒返回 ``True`` ⇒ 空表前置**无条件放行**，与「写错一律不通过」
    （README / design §4.2 的 fail-closed 口径）精神相反：作者漏写/清空取值时，
    本该「拦下并让人发现」，实际却「静默全放行」。
    """
    ok = svc_mod._prerequisites_met
    st = {"opened": ["drawer", "letter"], "scene_id": "counter"}

    assert ok({"opened": {"has_all": ["drawer"]}}, st) is True       # 非空表照旧生效
    assert ok({"opened": {"has_all": []}}, st) is False, (
        "空表 has_all 被判为真（vacuous truth）—— 与 fail-closed 口径相反")
    # 空表 fail-closed 不能影响其余形态
    assert ok({"opened": {"has": "drawer"}}, st) is True
    assert ok({"opened": {"has_not": "latch"}}, st) is True
    assert ok({"scene_id": "counter"}, st) is True


# --------------------------------------------------------------------------- #
# ⑯ 批次 B-4：三条已确认的 P2
# --------------------------------------------------------------------------- #

def test_choice_snapshot_missing_label_is_neutralized(svc, monkeypatch):
    """P2①：缺 ``label`` 的选项 → 中性中文占位，**绝不**回落 ``choice_id``（机器名旁路）。"""
    import copy as _copy

    patched = _copy.deepcopy(load_content(FALLBACK_BOOK_ID))
    for chapter in patched["chapters"]:
        for item in chapter["nodes"]:
            if item.get("id") == "opening":
                item["choices"] = [{"choice_id": "no_label_choice", "transform": "wait"}]
    monkeypatch.setattr(
        svc_mod.tavern_worldbook, "load_content",
        lambda pack_id=FALLBACK_BOOK_ID, **kw: patched,
    )
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-nolabel")

    choices = svc.current_choices()
    assert [c["choice_id"] for c in choices] == ["no_label_choice"]
    assert choices[0]["label"] == svc_mod.NEUTRAL_CHOICE_LABEL, (
        f"缺 label 的选项回落成了机器名：{choices[0]['label']!r}")
    assert "no_label_choice" not in choices[0]["label"]

    pending = (svc.current_play() or {}).get("pending") or []
    assert pending and pending[0]["label"] == svc_mod.NEUTRAL_CHOICE_LABEL


def test_current_choices_neutralizes_legacy_pending_without_label(svc):
    """P2①（旧档旁路）：``pending`` 快照缺 ``label`` 时也不得回落到 ``choice_id``。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-legacy-pending")
    play = svc.current_play()
    play["pending"] = [{"choice_id": "legacy_choice", "transform": "wait", "args": {}}]

    out = svc.current_choices()
    assert out[0]["label"] == svc_mod.NEUTRAL_CHOICE_LABEL
    assert out[0]["label"] != "legacy_choice"


def test_delete_play_clears_worldbook_snapshot_and_broadcasts(svc):
    """P2②：删**当前局**须清 ``_last_selection`` 并广播 ``worldbook_changed``。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-del-wb")
    assert svc.worldbook_hits()["entries"], "前置：开局应有世界书快照"

    seen: list = []
    svc.worldbook_changed.connect(lambda payload: seen.append(payload))

    assert svc.delete_play("e2e-del-wb") is True
    assert seen, "delete_play 没有广播 worldbook_changed —— Tab 不会刷新"
    assert svc._last_selection is None, "删当前局后 _last_selection 仍残留旧局命中"
    assert svc.worldbook_hits()["entries"] == [], (
        "删局后「世界书」Tab 仍显示已删局的条目")
    assert svc.worldbook_hits()["used_chars"] == 0


# --------------------------------------------------------------------------- #
# ⑰ 批次 C：内容扩充的**端到端**验证（真 service + 真内容包）
#
# 内容层的**结构**不变量（choice_id 唯一 / labels 覆盖 / probability 非默认 / 文案零数字 /
# 每节点有出口 / 三条链各有消费者）见 ``tests/test_v22_content_quality.py`` §8–§11。
# 本节只放**必须真跑 service 才能证伪**的部分：结局可达性、物品链、选项前置过滤、无死路。
# --------------------------------------------------------------------------- #

def _pending_map(play: dict) -> dict:
    """``pending`` 快照 → ``{choice_id: snapshot}``。"""
    return {p.get("choice_id"): p for p in (play.get("pending") or []) if isinstance(p, dict)}


def _walk(svc_: TavernService, picks: List[str], play_id: str) -> List[dict]:
    """按 ``picks`` 逐拍点击，返回每一拍**点击前**的 ``play`` 快照（最后一拍为终态）。"""
    svc_.start_play(FALLBACK_BOOK_ID, play_id=play_id)
    snaps: List[dict] = []
    for cid in picks:
        play = svc_.current_play() or {}
        snaps.append(dict(play))
        available = {c["choice_id"] for c in svc_.current_choices()}
        assert cid in available, (
            f"待选里没有 {cid!r}（当前节点 {play.get('node_id')!r}，可选 {sorted(available)}）"
        )
        assert svc_.submit(cid, "choice") is True, f"{cid!r} 提交失败"
    snaps.append(dict(svc_.current_play() or {}))
    return snaps


def test_two_endings_reachable_through_letter_state(svc):
    """★ 批次 C（缺陷 A）：两个结局原本**同前置** ``{"scene_id": "backdoor"}``，
    ``_advance_node`` 按声明顺序取第一个匹配 → 先声明的 ``ending_guest_leaves`` 永远赢，
    ``ending_dawn`` **不可达**。

    本用例构造两条真路：**读过信** → ``ending_guest_leaves``；**没读信** → ``ending_dawn``。
    """
    read_letter = _walk(
        svc,
        ["sit_down", "ask_photo_who", "sit_table", "ask_letter_about",
         "open_letter", "echo_letter_to_door"],
        "e2e-C-ending-letter",
    )
    assert read_letter[-1]["vars"]["opened"] == ["letter"], "前置：信没有被打开"
    assert read_letter[-1]["node_id"] == "ending_guest_leaves", (
        f"读过信却没有走到 ending_guest_leaves：{read_letter[-1]['node_id']!r}")
    assert read_letter[-1]["status"] == "ended"
    assert svc.current_choices() == [], "终局节点仍给出选项"


def test_other_ending_reachable_when_letter_unread(svc):
    """★ 同上的另一半：**没读信** → ``ending_dawn``（证明两条路真的分叉）。"""
    no_letter = _walk(
        svc,
        ["sit_down", "leave_to_alley"],
        "e2e-C-ending-dawn",
    )
    assert no_letter[-1]["vars"]["opened"] == [], "前置：这局不该打开信"
    assert no_letter[-1]["node_id"] == "ending_dawn", (
        f"没读信却没有走到 ending_dawn：{no_letter[-1]['node_id']!r}")
    assert no_letter[-1]["status"] == "ended"


def test_item_chain_scene_items_take_give_end_to_end(svc):
    """★ 批次 C（缺陷 D）：``take`` / ``give`` 从未被使用 → ``scene_items`` 无写入点、
    ``held_items`` / ``given`` 恒空，物品系统整条死。

    走通完整链：``open_letter`` 写 ``scene_items`` → ``take_letter`` 进 ``held_items``
    → ``give_letter_back`` 进 ``given``。
    """
    snaps = _walk(
        svc,
        ["sit_down", "ask_photo_who", "sit_table", "ask_letter_about",
         "open_letter", "take_letter", "give_letter_back"],
        "e2e-C-items",
    )
    # ① 打开信后，信出现在「眼前能拿到」里（scene_items 有写入点）
    after_open = snaps[5]["vars"]
    assert "letter" in after_open["scene_items"], (
        f"open_letter 没有把信写进 scene_items：{after_open['scene_items']!r}")
    # ② take 之后：从 scene_items 挪进 held_items
    after_take = snaps[6]["vars"]
    assert "letter" in after_take["held_items"], "take 没有把信放进 held_items"
    assert "letter" not in after_take["scene_items"], "take 没有把信从 scene_items 拿走"
    # ③ give 之后：从 held_items 挪进 given
    after_give = snaps[7]["vars"]
    assert "letter" in after_give["given"], "give 没有把信记进 given"
    assert "letter" not in after_give["held_items"], "give 没有把信从 held_items 拿走"


def test_choice_prerequisites_hide_unmet_options_on_real_pack(svc):
    """★ 批次 C（缺陷 B 后半）：选项级 ``prerequisites`` 原本 **0/45** → 「选择有后果」不可见。

    （★ 批次 D（E3）订正：此处原写 **0/51** —— 那是设计文档早先写错的数字；
    批次 B 实测选项数为 **45**，与 ``test_v22_content_quality._OPERATOR_BATCH_PACK_SNAPSHOT`` 一致。）

    真内容包上直接验：``known`` 不含 ``guest`` 时 ``guest_known_ask`` 不出现；补上后出现。
    """
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-C-choice-gate")
    play = svc.current_play()
    play["node_id"] = "guest_arrives"
    play["scene_id"] = "counter"

    svc._sync_pending(play)
    assert "guest_known_ask" not in {c["choice_id"] for c in svc.current_choices()}, (
        "known 里没有 guest 时，门控选项仍然出现")

    play["vars"]["known"] = ["guest"]
    svc._sync_pending(play)
    assert "guest_known_ask" in {c["choice_id"] for c in svc.current_choices()}, (
        "known 含 guest 后，门控选项仍未放行")


def test_held_item_gated_choice_only_appears_when_holding(svc):
    """同上的另一半：``give_letter_back`` 只在**怀里真有信**时出现（``held_items`` 算子）。"""
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-C-hold-gate")
    play = svc.current_play()
    play["node_id"] = "guest_thanks"
    play["scene_id"] = "table"

    svc._sync_pending(play)
    assert "give_letter_back" not in {c["choice_id"] for c in svc.current_choices()}

    play["vars"]["held_items"] = ["letter"]
    svc._sync_pending(play)
    assert "give_letter_back" in {c["choice_id"] for c in svc.current_choices()}


def test_content_exhaustion_still_converges_to_an_ending(svc):
    """★ 批次 C（缺陷 H）：内容耗尽时 ``_advance_node`` 保持当前节点 → 玩家原地打转。

    构造最坏情况：先用**回避一切 ``move_to backdoor``** 的走法把内容尽量耗尽，
    然后只靠节点自带的「走到门口」出口 —— 必须仍能收束到终局。
    """
    svc.start_play(FALLBACK_BOOK_ID, play_id="e2e-C-exhaust")
    for beat in range(200):
        play = svc.current_play() or {}
        if (play.get("node_id") or "").startswith("ending_"):
            break
        choices = svc.current_choices()
        if not choices:
            break
        snap = _pending_map(play)
        avoid = [
            c["choice_id"] for c in choices
            if not (snap[c["choice_id"]].get("transform") == "move_to"
                    and (snap[c["choice_id"]].get("args") or {}).get("target") == "backdoor")
        ]
        if not avoid:
            break
        svc.submit(avoid[beat % len(avoid)], "choice")

    mid = svc.current_play() or {}
    assert len(mid.get("seen_nodes") or []) >= 5, "内容还没走开就停了，用例失去意义"

    for _ in range(8):
        play = svc.current_play() or {}
        if (play.get("node_id") or "").startswith("ending_"):
            break
        snap = _pending_map(play)
        exits = [
            c["choice_id"] for c in svc.current_choices()
            if snap[c["choice_id"]].get("transform") == "move_to"
            and (snap[c["choice_id"]].get("args") or {}).get("target") == "backdoor"
        ]
        assert exits, (
            f"节点 {play.get('node_id')!r} 没有「走到门口」的出口 —— 这就是死路："
            f"{sorted(snap)}")
        svc.submit(exits[0], "choice")

    final = svc.current_play() or {}
    assert (final.get("node_id") or "").startswith("ending_"), (
        f"内容耗尽后走不出去：node_id={final.get('node_id')!r}")
    assert final.get("status") == "ended"


# --------------------------------------------------------------------------- #
# ⑱ 批次 D（E1）：无死路不变量 —— **完整**可达性检查（含空场景 ""）
#
# 旧口径（已作废）：「每个非终局节点都有一条 ``move_to backdoor`` 出口」。
# 事实：``opening`` 节点**没有** ``move_to backdoor``（只有 ``sit_down → counter``）；
# ``reachable[""]`` **不含** ``backdoor``；而旧用例只遍历 ``content["scene_ids"]``
# （**不含** ``""``）⇒ 空场景被**悄悄豁免**，声明 ≠ 实现 ≠ 测试口径。
#
# 本批改为**准确口径 + 真正证明**：
#   不变量 = 「从**任一可达状态**出发，都能在有限步内抵达某个结局」，
#   且 ``""``（初始 scene）**必须**在检查范围内，不得豁免。
#
# 证明方式 = 对**真 service + 真内容包**驱动的状态机做**完整** BFS（不做深度截断），
# 再在探索出的图上做**反向可达**：凡不能抵达任何结局的可达状态即死路 → 直接判红。
# 因为探索是完整的（终止时队列空），所以"能到结局"这一结论不含深度截断的假阴性。
# --------------------------------------------------------------------------- #

#: 状态枚举上限（**安全阀**）。真包实测约 3.6 万个等价状态；超上限即说明枚举不完整，
#: 此时"未发现死路"不再有证明力，故用例**主动判红**而不是静默通过。
_REACHABLE_STATE_CAP = 60000


def _play_state_key(play: dict) -> tuple:
    """状态等价键：列表型 ``var`` 取**集合语义**（去重 + 无序）。

    为什么可以这样合并：``prerequisites`` 只认 ``has`` / ``has_not`` / ``has_all``
    （集合语义），``_advance_node`` / ``_sync_pending`` 也只用这一把尺子 ——
    重复项与顺序**不改变任何后继行为**，故是行为等价类（bisimulation 商）。
    不这样归一化，``open`` / ``ask_about`` 的无限 append 会让状态空间发散。
    """
    vars_map = play.get("vars") if isinstance(play.get("vars"), dict) else {}

    def _as_set(name: str) -> frozenset:
        value = vars_map.get(name)
        if isinstance(value, (list, tuple)):
            return frozenset(str(x) for x in value)
        return frozenset()

    poured = vars_map.get("poured")
    return (
        play.get("node_id"),
        play.get("scene_id"),
        _as_set("opened"), _as_set("known"), _as_set("held_items"),
        _as_set("scene_items"), _as_set("given"),
        poured if isinstance(poured, str) else "",
        bool(vars_map.get("knows_name")),
        bool(vars_map.get("photo_seen")),
        frozenset(play.get("seen_nodes") or []),
    )


def _advance_by_choice(svc_: TavernService, play: dict, snap: dict, content: dict):
    """按 ``pending`` 快照走一拍（与 ``_pipeline_turn`` 的 ``choice`` 档**同一步子**）。

    步子 = ``engine.apply_transform`` → 拍数 +1 → ``_advance_node`` → ``_sync_pending``；
    变换被拒（``ok=False``）→ 返回 ``None``（该选项不改变状态，不入图）。
    """
    result = tavern_engine.apply_transform(
        play, snap.get("transform"), snap.get("args") or {}, content,
        seed=play.get("seed"),
    )
    if not result.ok:
        return None
    nxt = result.state
    nxt["turn"] = max(int(nxt.get("turn") or 0), int(play.get("turn") or 0) + 1)
    svc_._advance_node(nxt)
    svc_._sync_pending(nxt)
    return nxt


def _explore_reachable_states(svc_: TavernService) -> Tuple[dict, dict, dict]:
    """从**真初始态**（``scene_id == ""``）做完整 BFS，返回 ``(start, states, edges)``。

    ``states``: ``{state_key: play}``；``edges``: ``{state_key: [后继 state_key, …]}``。
    """
    content = svc_._content_for(FALLBACK_BOOK_ID)
    start = tavern_model.new_play(FALLBACK_BOOK_ID, "可达性起点", 0, play_id="reach-walk")
    svc_._seed_seen_nodes(start)
    svc_._sync_pending(start)

    states: Dict[tuple, dict] = {_play_state_key(start): start}
    edges: Dict[tuple, List[tuple]] = {}
    queue: deque = deque([start])
    while queue:
        play = queue.popleft()
        key = _play_state_key(play)
        if key in edges:
            continue
        outs: List[tuple] = []
        if not (play.get("node_id") or "").startswith("ending_"):
            for snap in play.get("pending") or []:
                if not isinstance(snap, dict):
                    continue
                nxt = _advance_by_choice(svc_, play, snap, content)
                if nxt is None:
                    continue
                nxt_key = _play_state_key(nxt)
                outs.append(nxt_key)
                if nxt_key not in states and len(states) < _REACHABLE_STATE_CAP:
                    states[nxt_key] = nxt
                    queue.append(nxt)
        edges[key] = outs
    return start, states, edges


def test_no_dead_end_from_any_reachable_state_including_empty_scene(svc):
    """★ 批次 D（E1）：**准确**的无死路不变量 —— 含初始空场景，不再豁免。

    断言（三者缺一不可）：

    1. **空场景在检查范围内**：初始 ``scene_id`` 为 ``""``，且它确实被纳入状态枚举
       （旧用例只遍历 ``content["scene_ids"]``，而 ``""`` 不在其中 —— 这正是豁免的来源）；
    2. **枚举完整**：BFS 自然终止且未触及状态上限（否则"没找到死路"不构成证明）；
    3. **任一可达状态都能抵达结局**：在探索出的状态图上做反向可达，
       「不能抵达任何结局」的可达状态数必须为**零**。

    为什么换成这条口径：``opening`` 节点**没有** ``move_to backdoor`` 直连出口
    （只有 ``sit_down → counter``），``reachable[""]`` 也**不含** ``backdoor`` ——
    旧声明「每个非终局节点都有一条 backdoor 出口」**字面不成立**。真实成立的是
    「两步之内能走到门口，且门口恰有一个结局匹配」，即本用例断言的有界可达性。
    """
    start, states, edges = _explore_reachable_states(svc)

    # ① 空场景不被豁免（旧口径的漏洞就在这里）
    assert start.get("scene_id") == "", f"初始 scene 应为空串：{start.get('scene_id')!r}"
    assert _play_state_key(start) in states, "初始（空场景）状态没有被纳入枚举"
    assert any(key[1] == "" for key in states), "枚举结果里没有任何空场景状态 —— 空场景被豁免了"

    # ② 枚举完整性（超上限即判红，避免"截断式假绿"）
    assert len(states) < _REACHABLE_STATE_CAP, (
        f"可达状态数触及上限 {_REACHABLE_STATE_CAP}，枚举不完整，断言失去证明力")

    # ③ 反向可达：能抵达任何终局状态的可达状态集合
    declared_endings = [
        node for chapter in (svc._content_for(FALLBACK_BOOK_ID).get("chapters") or [])
        for node in (chapter.get("nodes") or [])
        if isinstance(node, dict) and node.get("choices") == []
    ]
    assert declared_endings, "内容包里没有任何终局节点（choices == []），断言会挂空"

    endings = {key for key, play in states.items()
               if (play.get("node_id") or "").startswith("ending_")}

    reverse: Dict[tuple, set] = {}
    for src, outs in edges.items():
        for dst in outs:
            reverse.setdefault(dst, set()).add(src)

    can_reach = set(endings)
    stack = list(endings)
    while stack:
        current = stack.pop()
        for predecessor in reverse.get(current, ()):
            if predecessor not in can_reach:
                can_reach.add(predecessor)
                stack.append(predecessor)

    start_key = _play_state_key(start)
    assert start_key in can_reach, (
        "初始状态（空场景 \"\"）走不到任何结局 —— 玩家一开局就被卡住")
    dead = sorted(key for key in states if key not in can_reach)
    assert dead == [], (
        f"存在 {len(dead)} 个走不到任何结局的可达状态（死路）："
        f"{[(key[0], key[1]) for key in dead[:8]]}")
