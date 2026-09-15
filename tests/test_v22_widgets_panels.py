"""tests/test_v22_widgets_panels.py —— V22-08 酒馆「世界书 / 我的故事 / 记录」控件断言。

覆盖 ``docs/design-v22.md`` §6 与 V22-08 任务书对三个 **只读** 控件的验收要点：

    * **世界书**：条目数正确；命中项被标出；命中文案语义 =「本拍**选中**」，
      **不含**「新增 / 获得 / 解锁 / 得到」等误导词；
    * **我的故事**：``list_plays`` 正确渲染；载入调用 ``load_play(id)``（计数断言）；
      **删除前有确认**（确认函数被调用断言），确认取消则不删；删除后列表刷新；
      当前局有非序号标记；
    * **记录**：逐拍渲染 5 个字段；**R-A 机器可验守卫** —— 断言界面上所有 ``QLabel``
      文本**不含**成功率 / 进度 / 胜率 / 评分 / 百分比 / 得分 / 排名 / 计数等评价性
      或计量性内容，**且不含任何阿拉伯数字**；断言**不出现裸错误码**（``bad_args:`` /
      ``precondition_failed:`` 原串不进任何 ``QLabel``，``:`` 也不出现）；
    * **零字号**：扫描三个控件文件，断言无 ``setPointSize(`` / ``setPixelSize(``；
    * **颜色不硬编码**：断言任何 ``#RRGGBB`` 都只作为 ``_color(...)`` / ``theme_color(...)``
      的参数出现（且取色确实走 ``theme_color``）。

纪律：``QT_QPA_PLATFORM=offscreen``；**确定性**（无网络、无墙钟断言）；
**隔离**控件与并行写者：以文件路径直接加载三模块，**不触发** ``gui.widgets.tavern``
包 ``__init__``（该文件由另一位工程师独占）。
**防再犯**：三条关键数据链（世界书 / 我的故事 / 记录）除**保留**桩用例作边界补充外，
各补一条 **真 service + 真内容包** 的对照断言 —— 当初两个 P0 空壳（``pending`` 无写者、
世界书 Tab 恒空）正是被"只用桩喂数据"掩盖绿的。真 service 的 ``base_dir`` 一律指
``tmp_path``，并以 autouse 前后快照守卫真实 ``~/.maid_coder/tavern`` **不被创建 / 改动**。
"""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.qt_compat import QApplication, QFrame, QLabel, QObject, Signal  # noqa: E402
from gui.tavern.service import FALLBACK_BOOK_ID, TavernService  # noqa: E402
from gui.tavern.worldbook import load_builtin_book  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_TAVERN_DIR = ROOT / "gui" / "widgets" / "tavern"

#: 真实用户存档目录（**本文件绝不创建 / 改动它**；正确路径是 ``~/.maid_coder``）。
_REAL_TAVERN_DIR = Path.home() / ".maid_coder" / "tavern"


# ===========================================================================
# 隔离加载：按文件路径加载三模块，不触发包 __init__（并行写者独占该文件）
# ===========================================================================

def _load_module(modname: str, filename: str):
    path = _TAVERN_DIR / filename
    assert path.is_file(), f"缺失控件文件: {path}"
    spec = importlib.util.spec_from_file_location(modname, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def wb_mod():
    return _load_module("tavern_worldbook_under_test", "tavern_worldbook.py")


@pytest.fixture(scope="module")
def plays_mod():
    return _load_module("tavern_plays_under_test", "tavern_plays.py")


@pytest.fixture(scope="module")
def trace_mod():
    return _load_module("tavern_trace_under_test", "tavern_trace.py")


def _qapp() -> "QApplication":
    return QApplication.instance() or QApplication([])


# ===========================================================================
# 真 service 夹具（真 ``TavernService`` + 真内容包；防再犯：数据链不许只用桩覆盖）
# ===========================================================================
#
# 隔离纪律：真 service 的 ``base_dir`` 一律指 ``tmp_path``，**绝不**碰真实
# ``~/.maid_coder``（下方 autouse 夹具做前后快照守卫）。


def _real_ctx() -> SimpleNamespace:
    """最小应用上下文（真 service 只读它的可选字段；缺省给 ``None`` 即可）。"""
    return SimpleNamespace(
        api=None, cfg=None, config=None, theme_engine=None,
        companion=None, intimacy=None, page_manager=None,
    )


def _real_service(base_dir: Path) -> TavernService:
    """真 ``TavernService``（同步执行）+ 真内容包；存档隔离到 ``base_dir``。"""
    return TavernService(_real_ctx(), base_dir=base_dir, synchronous=True)


def _real_tavern_snapshot() -> tuple:
    """真实 ``~/.maid_coder/tavern`` 的存在性 + 文件清单快照（前后比对用）。"""
    if not _REAL_TAVERN_DIR.exists():
        return (False, ())
    manifest = []
    for path in sorted(_REAL_TAVERN_DIR.rglob("*")):
        if path.is_file():
            info = path.stat()
            manifest.append(
                (str(path.relative_to(_REAL_TAVERN_DIR)), info.st_size, int(info.st_mtime))
            )
    return (True, tuple(manifest))


@pytest.fixture(autouse=True)
def _guard_real_user_dir():
    """断言本文件**绝不**创建 / 改动真实 ``~/.maid_coder/tavern``。"""
    before = _real_tavern_snapshot()
    yield
    assert _real_tavern_snapshot() == before, "测试污染了真实用户存档目录 ~/.maid_coder/tavern"


# ===========================================================================
# 假 service（stub QObject，带同名信号 / 方法，计数断言用）
# ===========================================================================

class StubService(QObject):
    """假 ``TavernService``：同名信号 + 同名查询 / 动作方法，且记录调用。"""

    worldbook_changed = Signal(dict)
    plays_changed = Signal()
    play_changed = Signal(str)
    turn_ready = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.entries_payload: Dict[str, Any] = {"book_id": "lantern", "title": "灯笼酒馆",
                                                "entries": [], "budget_chars": 1600}
        self.hits_payload: Dict[str, Any] = {"entries": [], "by_position": {},
                                             "used_chars": 0, "trimmed": 0}
        self.plays: List[dict] = []
        self.trace_payload: List[dict] = []
        self.load_calls: List[str] = []
        self.delete_calls: List[str] = []
        self.theme_calls: List[str] = []
        self._theme: Dict[str, str] = {}

    # —— 取色（读时现取；stub 记录键名以便断言"取色走 theme_color"）——
    def theme_color(self, key: str, fallback: str) -> str:
        self.theme_calls.append(key)
        return self._theme.get(key, fallback)

    # —— 世界书 ——
    def worldbook_entries(self) -> dict:
        return self.entries_payload

    def worldbook_hits(self) -> dict:
        return self.hits_payload

    # —— 故事 ——
    def list_plays(self) -> List[dict]:
        return [dict(p) for p in self.plays]

    def load_play(self, play_id: str) -> bool:
        self.load_calls.append(play_id)
        for play in self.plays:
            play["is_active"] = (play.get("play_id") == play_id)
        self.play_changed.emit(play_id)
        return True

    def delete_play(self, play_id: str) -> bool:
        self.delete_calls.append(play_id)
        before = len(self.plays)
        self.plays = [p for p in self.plays if p.get("play_id") != play_id]
        self.plays_changed.emit()
        return len(self.plays) < before

    # —— 记录 ——
    def trace(self) -> List[dict]:
        return [dict(t) for t in self.trace_payload]


def _labels(widget) -> List[str]:
    return [lbl.text() for lbl in widget.findChildren(QLabel)]


def _change_theme(stub: StubService, mapping: Dict[str, str]) -> None:
    stub._theme = dict(mapping)
    stub.theme_calls.clear()


# ===========================================================================
# 世界书：条目数 / 命中标出 / 命中语义（不含误导词）
# ===========================================================================

def _worldbook_stub() -> StubService:
    stub = StubService()
    entry_constant = {
        "uid": 1, "title": "酒馆的规矩", "keys": [], "secondary_keys": [],
        "selective_logic": "AND_ANY", "content": "进了这扇门，就按这儿的规矩来。",
        "position": "system_head", "constant": True, "enabled": True,
    }
    entry_hit = {
        "uid": 2, "title": "那盏灯笼", "keys": ["灯笼", "长夜"], "secondary_keys": [],
        "selective_logic": "AND_ANY",
        "content": "灯芯是旧年的，火苗很小，却一直没灭。",
        "position": "system_tail", "constant": False, "enabled": True,
    }
    entry_plain = {
        "uid": 3, "title": "柜台后的照片", "keys": ["照片"], "secondary_keys": ["旧"],
        "selective_logic": "AND_ANY",
        "content": "相框里两个人挨着站，笑得有点模糊。",
        "position": "system_tail", "constant": False, "enabled": True,
    }
    stub.entries_payload = {
        "book_id": "lantern", "title": "灯笼酒馆",
        "entries": [entry_constant, entry_hit, entry_plain], "budget_chars": 1600,
    }
    # 本拍命中：仅 uid=2（**叙述前快照**，"本拍选中"）
    stub.hits_payload = {
        "entries": [dict(entry_hit)],
        "by_position": {"system_head": [], "system_tail": [dict(entry_hit)], "history_depth": []},
        "used_chars": len(entry_hit["content"]), "trimmed": 0,
    }
    return stub


def test_worldbook_renders_all_entries(wb_mod, tmp_path):
    """**真链路**：面板渲染条数 == 真内容包内置世界书条数（**不写死条数**）。

    防再犯：本用例原以 ``StubService`` 硬编码喂 3 条并断言 ``== 3``，于是「世界书
    Tab 恒空」的空壳能一路绿到上线前。改走真 service + 真内容包后，两侧任一处断链
    （``pending`` / ``library.books`` 回落 / 面板读取）都会当场变红。

    断言用「面板渲染条数 == ``load_builtin_book("lantern").entries`` 条数」两边相等，
    **不写死 17** —— 否则内容包一改就假红。
    """
    _qapp()
    service = _real_service(tmp_path)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-wb")
        panel = wb_mod.WorldbookPanel(service)
        builtin = load_builtin_book(FALLBACK_BOOK_ID)
        assert len(builtin.entries) > 0, "内置内容包没有条目"
        assert panel.entry_count() == len(builtin.entries)
    finally:
        service.stop()


def test_worldbook_marks_hit_entry(wb_mod):
    _qapp()
    stub = _worldbook_stub()
    panel = wb_mod.WorldbookPanel(stub)

    # 恰好一条被标为"本拍选中"，且落在 uid=2 的条目行上。
    chips = [c for c in panel.findChildren(QLabel) if c.objectName() == "tavernHitChip"]
    assert len(chips) == 1
    assert panel.is_hit(2) is True
    assert panel.is_hit(3) is False

    # 逐条目行核对：带 chip 的那一行标题 = 命中条目标题。
    hit_titles: List[str] = []
    for card in panel.findChildren(QFrame):
        if card.objectName() != "tavernEntryCard":
            continue
        if card.findChild(QLabel, "tavernHitChip") is None:
            continue
        title_label = card.findChild(QLabel, "tavernEntryTitle")
        assert title_label is not None
        hit_titles.append(title_label.text())
    assert hit_titles == ["那盏灯笼"]


def test_worldbook_hit_copy_has_no_misleading_words(wb_mod):
    _qapp()
    stub = _worldbook_stub()
    panel = wb_mod.WorldbookPanel(stub)
    joined = "\n".join(_labels(panel))
    # 命中语义 = 本拍"选中"（叙述前快照），**绝不能**写成"新增 / 获得 / 解锁 / 得到"。
    forbidden = ["新增", "获得", "解锁", "得到", "拿到", "触发获得", "刚刚添加"]
    for word in forbidden:
        assert word not in joined, f"命中语义出现误导词：{word!r}\n{joined}"
    assert "本拍选中" in joined


def test_worldbook_shows_real_trigger_fields_only(wb_mod):
    """触发信息只来自条目真实字段（keys / secondary_keys / constant），不编造。"""
    _qapp()
    stub = _worldbook_stub()
    panel = wb_mod.WorldbookPanel(stub)
    joined = "\n".join(_labels(panel))
    assert "触发词：灯笼、长夜" in joined          # uid=2 的主键如实展示
    assert "关联触发词：旧" in joined               # uid=3 的次键如实展示
    assert "每次都会带上" in joined                 # uid=1 常驻条目如实展示


# ===========================================================================
# 我的故事：渲染 / 载入 / 删除（确认 + 刷新）
# ===========================================================================

def _plays_stub() -> StubService:
    stub = StubService()
    stub.plays = [
        {"play_id": "p1", "title": "灯笼还亮着", "book_id": "lantern",
         "status": "active", "updated_at": "2026-09-15T20:00:00",
         "chapter_title": "灯笼还亮着", "is_active": True},
        {"play_id": "p2", "title": "雨夜来客", "book_id": "lantern",
         "status": "active", "updated_at": "2026-09-14T20:00:00",
         "chapter_title": "雨夜来客", "is_active": False},
    ]
    return stub


def test_plays_renders_list(plays_mod):
    _qapp()
    stub = _plays_stub()
    panel = plays_mod.PlaysPanel(stub)
    assert panel.play_count() == 2
    joined = "\n".join(_labels(panel))
    assert "灯笼还亮着" in joined
    assert "雨夜来客" in joined
    # 当前局有标记，但**不是序号**。
    joined_all = joined + "\n".join(b.text() for b in panel.findChildren(QLabel))
    assert plays_mod.ACTIVE_CHIP_TEXT in joined_all
    assert "第 1" not in joined_all and "局" not in joined_all


def test_plays_load_calls_service(plays_mod):
    _qapp()
    stub = _plays_stub()
    panel = plays_mod.PlaysPanel(stub)
    ok = panel.load_play("p2")
    assert ok is True
    assert stub.load_calls == ["p2"]           # 载入确实调用 load_play(id)
    # 载入后刷新：当前局标记移动到 p2。
    assert stub.plays[1]["is_active"] is True
    assert panel.play_count() == 2


def test_plays_delete_confirms_then_refreshes(plays_mod, monkeypatch):
    _qapp()
    stub = _plays_stub()
    panel = plays_mod.PlaysPanel(stub)

    events: List[str] = []
    monkeypatch.setattr(plays_mod, "_confirm_delete",
                        lambda parent, title: (events.append("confirm:" + title), True)[1])

    ok = panel.delete_play("p2")
    assert ok is True
    assert events == ["confirm:雨夜来客"]        # 删除**前**有确认
    assert stub.delete_calls == ["p2"]           # 确认后才删
    assert panel.play_count() == 1               # 删除后列表刷新
    assert stub.plays[0]["play_id"] == "p1"


def test_plays_delete_cancelled_does_not_delete(plays_mod, monkeypatch):
    _qapp()
    stub = _plays_stub()
    panel = plays_mod.PlaysPanel(stub)

    called: List[str] = []
    monkeypatch.setattr(plays_mod, "_confirm_delete",
                        lambda parent, title: (called.append(title), False)[1])

    ok = panel.delete_play("p2")
    assert ok is False
    assert called == ["雨夜来客"]                 # 确认被调用
    assert stub.delete_calls == []                # 取消 → 不删
    assert panel.play_count() == 2


# ===========================================================================
# 记录：5 字段 / R-A 机器可验守卫
# ===========================================================================

def _trace_stub() -> StubService:
    stub = StubService()
    stub.trace_payload = [
        {"turn": 1, "role": "player", "mode": "verbatim", "transform": "order",
         "ok": True, "reason": "ok", "llm_used": False},
        {"turn": 2, "role": "narrator", "mode": "propose", "transform": "",
         "ok": False, "reason": "bad_args:unexpected_args:write_vars", "llm_used": True},
        {"turn": 3, "role": "narrator", "mode": "narrate", "transform": "move_to",
         "ok": False, "reason": "precondition_failed:open_condition", "llm_used": False},
        {"turn": 4, "role": "player", "mode": "narrate", "transform": "",
         "ok": True, "reason": "llm_disabled", "llm_used": False},
    ]
    return stub


#: 评价性 / 计量性词表（R-A 红线，界面**任何 QLabel** 都不许出现）。
_METRIC_WORDS = [
    "成功率", "进度", "胜率", "评分", "百分比", "得分", "分数", "排名",
    "战胜", "击败", "通过率", "转化率", "占比", "计数", "次数统计", "统计",
]

#: 裸错误码基名（原串**绝不进任何 QLabel**）。
_RAW_REASON_BASES = [
    "ok:", "unknown_transform", "bad_args", "precondition_failed", "forbidden",
    "invariant_violated", "llm_timeout", "llm_bad_json", "llm_disabled",
]


def test_trace_renders_five_fields(trace_mod):
    _qapp()
    stub = _trace_stub()
    panel = trace_mod.TracePanel(stub)
    assert panel.row_count() == 4
    fields = panel.field_texts()
    assert len(fields) == 4
    for row in fields:
        for key in ("mode", "transform", "ok", "reason", "llm_used"):
            assert key in row
            assert isinstance(row[key], str) and row[key]
    # ok / llm_used 是布尔 → 中性中文（不回显 True/False 裸值）。
    assert fields[0]["ok"] == trace_mod._OK_TRUE
    assert fields[0]["llm_used"] == trace_mod._LLM_FALSE


def test_trace_ra_guard_no_metric_words(trace_mod):
    """R-A 守卫①：界面所有 QLabel 文本不含任何评价性 / 计量性词。"""
    _qapp()
    stub = _trace_stub()
    panel = trace_mod.TracePanel(stub)
    for text in _labels(panel):
        for word in _METRIC_WORDS:
            assert word not in text, f"记录界面出现计量/评价词 {word!r}：{text!r}"


def test_trace_ra_guard_no_digits(trace_mod):
    """R-A 守卫②：界面所有 QLabel 文本**不含任何阿拉伯数字**（过程记录，非报表）。"""
    _qapp()
    stub = _trace_stub()
    panel = trace_mod.TracePanel(stub)
    for text in _labels(panel):
        assert not any(ch.isdigit() for ch in text), f"记录界面出现数字：{text!r}"


def test_trace_ra_guard_no_raw_reason_codes(trace_mod):
    """R-A 守卫③：不出现裸错误码（reason 技术串已翻成中性中文）。"""
    _qapp()
    stub = _trace_stub()
    panel = trace_mod.TracePanel(stub)
    for text in _labels(panel):
        # 冒号是错误码 `code:detail` 的形态标记；中文全角冒号不在此列，故断言 ASCII ":" 缺席。
        assert ":" not in text, f"记录界面出现裸错误码分隔符 ':'：{text!r}"
        for code in _RAW_REASON_BASES:
            assert code not in text, f"记录界面出现裸错误码 {code!r}：{text!r}"
    # 反面证据：中性中文确实上屏了（ok → 顺顺当当地过去了；被拒 → 搁下）。
    joined = "\n".join(_labels(panel))
    assert trace_mod._REASON_LABELS["ok"] in joined
    assert trace_mod._REASON_LABELS["precondition_failed"] in joined
    assert "bad_args" not in joined and "precondition_failed" not in joined


# ===========================================================================
# 真链路对照（防再犯）：另两条数据链各一条「真 service + 真内容包」断言
# ===========================================================================
#
# 上面「世界书」链已由 ``test_worldbook_renders_all_entries`` 走真 service。此处补齐
# 「我的故事」与「记录」两条链；桩用例（``_plays_stub`` / ``_trace_stub``）**一律保留**
# 作边界补充，本处只**新增**真链路覆盖，**不删**任何桩用例。

def test_plays_renders_real_service_plays(plays_mod, tmp_path):
    """真链路：面板渲染故事数 == 真 service ``list_plays()`` 条数（**不写死**）。"""
    _qapp()
    service = _real_service(tmp_path)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-plays-1")
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-plays-2")
        panel = plays_mod.PlaysPanel(service)
        assert panel.play_count() == len(service.list_plays())
        assert panel.play_count() >= 2
    finally:
        service.stop()


def test_trace_renders_real_service_trace(trace_mod, tmp_path):
    """真链路：走完一拍后，记录面板渲染拍数 == 真 service ``trace()`` 条数。"""
    _qapp()
    service = _real_service(tmp_path)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-trace")
        choices = service.current_choices()
        assert choices, "开局没有选项，产不出一条真回合"
        assert service.submit(choices[0]["choice_id"], "choice") is True
        panel = trace_mod.TracePanel(service)
        assert panel.row_count() == len(service.trace())
        assert panel.row_count() >= 1
    finally:
        service.stop()


# --------------------------------------------------------------------------- #
# 记录 ·「走过的结尾」：跨局 journal 的**只读**展示面（批次 D / E4）
#
# 旧缺陷：``journal.seen_endings`` **只写不读** —— 全仓无任何读取点，玩家抵达过的
# 结局**没有任何展示面**（``gui/widgets/tavern/*`` 与 ``page_tavern.py`` 均不读 journal）。
# --------------------------------------------------------------------------- #

def _walk_to_ending(svc) -> dict:
    """一路点下去直到终局节点（优先 ``move_to → backdoor``，与既有 e2e 同一走法）。"""
    for _ in range(40):
        play = svc.current_play() or {}
        if (play.get("node_id") or "").startswith("ending_"):
            return play
        choices = svc.current_choices()
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
        svc.submit(pick or choices[0]["choice_id"], "choice")
    raise AssertionError("40 拍仍未抵达终局")


def test_trace_panel_shows_reached_ending_names_from_real_journal(trace_mod, tmp_path):
    """★ 批次 D（E4）：真 service + 真内容包 —— 抵达过的结局名能在 UI 面被读到。

    R-A 硬约束（机器可验）：展示面**只列结局名** —— 不得出现数字 / 序号 /
    计量评价词 / 「X / Y」式进度写法。
    """
    _qapp()
    service = _real_service(tmp_path)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-ending-1")
        play = _walk_to_ending(service)
        assert (play.get("node_id") or "").startswith("ending_"), "没走到终局，断言会挂空"

        names = service.journal_endings()
        assert names, "journal_endings() 为空 —— 展示面又没了数据源"

        panel = trace_mod.TracePanel(service)
        assert panel.ending_texts() == names, (
            f"面板列出的结局名 {panel.ending_texts()} != journal {names}")

        joined = "\n".join(_labels(panel))
        assert names[-1] in joined, f"结局名没有真的上屏：{names[-1]!r}\n{joined}"
        assert not any(ch.isdigit() for ch in joined), f"「走过的结尾」出现数字：{joined!r}"
        assert "/" not in joined, f"「走过的结尾」出现进度式写法：{joined!r}"
        for word in _METRIC_WORDS:
            assert word not in joined, f"「走过的结尾」出现计量/评价词 {word!r}"
    finally:
        service.stop()


def test_trace_panel_ending_section_is_cross_play_and_neutral_when_empty(trace_mod, tmp_path):
    """同上：结局名取自**跨局** ``journal``（换一局后仍在）；尚未抵达过 → 中性空态。"""
    _qapp()
    service = _real_service(tmp_path)
    try:
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-ending-a")
        panel = trace_mod.TracePanel(service)
        assert panel.ending_texts() == [], "还没走到终局就列出了结局名"
        assert trace_mod.ENDING_EMPTY_TEXT in "\n".join(_labels(panel)), "空态文案缺失"

        _walk_to_ending(service)
        reached = service.journal_endings()
        assert reached, "走完一局后 journal 仍为空"

        # 换一局（新 play）：journal 跨局累积，结局名**不随换局消失**
        service.start_play(FALLBACK_BOOK_ID, play_id="panels-ending-b")
        assert (service.current_play() or {}).get("node_id") == "opening"
        panel.refresh()
        assert panel.ending_texts() == reached, (
            "换局后结局名消失 —— 读的不是跨局 journal")
    finally:
        service.stop()


# ===========================================================================
# 零字号 + 颜色不硬编码（三文件静态扫描）
# ===========================================================================

_WIDGET_FILES = ("tavern_worldbook.py", "tavern_plays.py", "tavern_trace.py")
_HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


@pytest.mark.parametrize("filename", _WIDGET_FILES)
def test_no_code_font_size(filename):
    """字号只能写在 QSS：控件代码里**禁止** setPointSize / setPixelSize。"""
    src = (_TAVERN_DIR / filename).read_text(encoding="utf-8")
    assert "setPointSize(" not in src, f"{filename} 出现 setPointSize("
    assert "setPixelSize(" not in src, f"{filename} 出现 setPixelSize("


@pytest.mark.parametrize("filename", _WIDGET_FILES)
def test_no_hardcoded_color(filename):
    """颜色不硬编码：任何 ``#RRGGBB`` 都只作为 ``_color(...)`` 的参数出现。"""
    src = (_TAVERN_DIR / filename).read_text(encoding="utf-8")
    assert "def _color" in src, f"{filename} 缺少统一取色入口 _color"
    assert "theme_color" in src, f"{filename} 取色未走 theme_color"
    for lineno, line in enumerate(src.splitlines(), start=1):
        for match in _HEX_RE.finditer(line):
            assert ("_color(" in line) or ("theme_color(" in line), (
                f"{filename}:{lineno} 出现裸色 {match.group()}（应经 _color/theme_color）"
            )


@pytest.mark.parametrize("modname,filename,cls,theme_key", [
    ("wb", "tavern_worldbook.py", "WorldbookPanel", "bg_card"),
    ("plays", "tavern_plays.py", "PlaysPanel", "border"),
    ("trace", "tavern_trace.py", "TracePanel", "state_ok"),
])
def test_color_goes_through_theme_color(modname, filename, cls, theme_key):
    """取色**确实**走 ``theme_color``（stub 记录键名），且 refresh 后仍未缓存。"""
    _qapp()
    module = _load_module(f"tavern_{modname}_color_under_test", filename)
    stub = StubService()
    stub.entries_payload = {"book_id": "lantern", "title": "灯笼酒馆", "entries": [], "budget_chars": 0}
    stub.plays = [{"play_id": "p1", "title": "x", "is_active": True, "updated_at": "", "chapter_title": ""}]
    stub.trace_payload = [{"turn": 1, "role": "player", "mode": "verbatim", "transform": "order",
                           "ok": True, "reason": "ok", "llm_used": False}]
    panel = getattr(module, cls)(stub)
    assert "text" in stub.theme_calls or "bg_card" in stub.theme_calls

    # 换肤：theme_color 返回新值 → apply_theme() 后仍按"读时现取"重新取色（未缓存）。
    _change_theme(stub, {"text": "#123456", "bg_card": "#0A0B0C", "border": "#111111"})
    panel.apply_theme()
    assert stub.theme_calls, "apply_theme() 未重新取色（疑似在构造期缓存）"


def test_widgets_do_not_import_motion():
    """三个控件走静态列表，**不引入动效**（无几何母题运动风险）。"""
    for filename in _WIDGET_FILES:
        src = (_TAVERN_DIR / filename).read_text(encoding="utf-8")
        assert "QPropertyAnimation" not in src, f"{filename} 出现 QPropertyAnimation"
        assert "setDuration(" not in src, f"{filename} 出现 setDuration("
