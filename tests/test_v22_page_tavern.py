# -*- coding: utf-8 -*-
"""V22-06 酒馆页装配单测（``PageTavern``：5 Tab 容器 + 换肤 + 退出收口 + 红线自查）。

覆盖（全部 **offscreen、确定性、零网络**；存档目录一律走 ``tmp_path``，
绝不写真实 ``~/.maid_coder``，对齐 design §4.4 规则 6）：

  · 构造：stub ``app_ctx`` + ``tmp_path`` 存档目录（服务经模块同名符号替换注入）；
  · 5 Tab：``count() == 5``，标题顺序 = 今夜 / 世界书 / 我的故事 / 人物 / 记录；
  · 「今夜」装配：HUD + 叙述流 + 输入三件套齐备；
  · 换肤：``theme_changed`` 一次 → 6 个控件 ``apply_theme()`` 各恰好一次（MagicMock 计数）；
  · 退出：``aboutToQuit`` → ``service.stop(2000)`` + ``service.save()``；**幂等**（第二次不再调）；
  · 玩家回显：``TavernInput.submitted`` → ``narrative.add_player``，且本页**不重发** ``submit``；
  · 「人物」Tab：``_content_cast`` 为空 → 中性空态；注入 3 条 → 3 张只读卡（零序号、零数字）；
  · 设置行：默认值来自 ``get_settings()``；改动 → ``set_settings(allow_propose=…)`` /
    ``set_settings(worldbook_budget_chars=…)``；回读过程**不回写**；
  · 文案纪律：设置行不含「性能 / 准确率 / 落后 / 开销」等焦虑词（R-A / D-V22-03）；
  · 源码红线：零 ``setPointSize(`` / ``setPixelSize(``；除 ``_FALLBACK_COLORS`` 表外零
    ``#RRGGBB`` 字面量；不订阅控件侧数据信号、不直连 ``service.submit/reroll/edit_narration``。
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, call

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui.qt_compat import QApplication, QLabel, QObject, Signal

from gui.pages import page_tavern
from gui.tavern.service import TavernService

ROOT = Path(__file__).resolve().parents[1]
PAGE_SOURCE = ROOT / "gui" / "pages" / "page_tavern.py"
BASE_QSS = ROOT / "gui" / "themes" / "base.qss"

#: R-A 序号形态（「第 N 夜/幕/回合/章/节/轮/次」）。
_ORDINAL_RE = re.compile(r"第\s*[0-9]+\s*[夜幕回合章节轮次]")
#: 任意 ASCII 数字（序号 / 进度 / 计分一律含数字 → 命中即视为违规）。
_DIGIT_RE = re.compile(r"[0-9]")
#: 裸色字面量形态。
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
#: 设置行文案禁用的「焦虑词」（R-A / D-V22-03）。
_ANXIETY_WORDS = ("性能", "准确率", "落后", "开销")
#: 控件侧数据信号（**各控件自订阅**，本页不得重复连接）。
_WIDGET_DATA_SIGNALS = (
    "narration_chunk", "narration_done", "hud_changed", "choices_changed",
    "busy_changed", "read_only_changed", "degraded", "worldbook_changed", "turn_ready",
)
#: 本页自带小部件的 id（字号收口在 base.qss 的 11c 段）。
_PAGE_OBJECT_NAMES = (
    "tavernCastName", "tavernCastRole", "tavernCastLine",
    "tavernSettingsLabel", "tavernSettingsHint",
    "tavernAllowPropose", "tavernBudgetSpin",
    "tavernRerollBtn", "tavernEditBtn",
    "tavernStartHint", "tavernStartBtn",
)


# ---------------------------------------------------------------------------
# stub 上下文 / fixtures
# ---------------------------------------------------------------------------
class _FakeThemeEngine(QObject):
    """最小主题引擎桩：``theme_changed`` 可手动 emit；取色一律回落调用方兜底值。"""

    theme_changed = Signal(str)

    def get_color(self, key: str, fallback: str) -> str:  # noqa: ARG002 - 桩
        return fallback


class _FakeAppCtx:
    """最小应用上下文桩（无 api / cfg → 酒馆走本地降级，不触网）。"""

    def __init__(self) -> None:
        self.theme_engine = _FakeThemeEngine()
        self.api = None
        self.cfg = None
        self.config = None
        self.companion = None
        self.intimacy = None


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def ctx():
    return _FakeAppCtx()


@pytest.fixture
def page(qapp, ctx, tmp_path, monkeypatch):  # noqa: ARG001 - qapp 保证 QApplication 就绪
    """构造 ``PageTavern``；存档目录注入 ``tmp_path``（**绝不写真实 ``~/.maid_coder``**）。"""

    def _factory(app_ctx, parent=None, **kwargs):
        kwargs.setdefault("base_dir", tmp_path)
        kwargs.setdefault("synchronous", True)
        return TavernService(app_ctx, parent=parent, **kwargs)

    monkeypatch.setattr(page_tavern, "TavernService", _factory)
    widget = page_tavern.PageTavern(ctx, "酒馆")
    yield widget
    try:
        widget.close()
    except Exception:  # pragma: no cover - 关闭边界
        pass


def _label_texts(widget) -> list:
    return [label.text() for label in widget.findChildren(QLabel)]


def _qss_rule_body(qss: str, object_name: str) -> str:
    for mm in re.finditer(r"#([A-Za-z_][A-Za-z0-9_]*)\s*\{([^}]*)\}", qss):
        if mm.group(1) == object_name:
            return mm.group(2)
    return ""


def _hex_literals(tree: ast.AST) -> set:
    return {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and _HEX_RE.match(node.value)
    }


def _fallback_table_values(tree: ast.AST) -> set:
    """``_FALLBACK_COLORS = {...}`` 里的字符串值（唯一允许出现裸色的位置）。

    支持 ``ast.Assign`` 与带注解的 ``ast.AnnAssign``（源码目前是后者）。
    """
    out = set()
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if not (isinstance(target, ast.Name) and target.id == "_FALLBACK_COLORS"):
            continue
        if isinstance(node.value, ast.Dict):
            for value in node.value.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out.add(value.value)
    return out


def _connected_signal_names(src: str) -> set:
    """源码里所有 ``X.<name>.connect(...)`` 中被订阅的信号名（**AST 判定**，忽略注释/文档串）。"""
    names = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "connect":
            if isinstance(func.value, ast.Attribute):
                names.add(func.value.attr)
    return names


def _direct_service_intent_calls(src: str) -> list:
    """源码里对 ``X.service.submit / reroll / edit_narration`` 的直接调用（**AST 判定**）。"""
    hits = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"submit", "reroll", "edit_narration"}:
            continue
        target = node.func.value
        if isinstance(target, ast.Attribute) and target.attr == "service":
            hits.append(node.func.attr)
    return hits


# ===========================================================================
# 构造 / Tab 结构
# ===========================================================================
def test_page_constructs_with_tmp_store(page, tmp_path):
    """构造成功，且数据层确实落在 ``tmp_path`` 之下（不碰真实用户目录）。"""
    assert isinstance(page.service, TavernService)
    assert page.service._store.base_dir == tmp_path
    assert str(page.service._store.path).startswith(str(tmp_path))


def test_five_tabs_in_frozen_order(page):
    """§6.1：5 Tab，顺序冻结为 今夜 / 世界书 / 我的故事 / 人物 / 记录。"""
    assert page.tabs.count() == 5
    assert page.tab_titles() == ["今夜", "世界书", "我的故事", "人物", "记录"]
    assert page_tavern.TAB_TITLES == ("今夜", "世界书", "我的故事", "人物", "记录")
    assert (page_tavern.TAB_TONIGHT, page_tavern.TAB_CAST, page_tavern.TAB_TRACE) == (0, 3, 4)


def test_tonight_tab_assembles_hud_narrative_input(page):
    """「今夜」= 章标题条 + 叙述流 + 输入行（三件套齐备，且属同一 Tab）。"""
    from gui.widgets.tavern.tavern_hud import TavernHud
    from gui.widgets.tavern.tavern_input import TavernInput
    from gui.widgets.tavern.tavern_narrative import TavernNarrative

    assert isinstance(page.hud, TavernHud)
    assert isinstance(page.narrative, TavernNarrative)
    assert isinstance(page.tavern_input, TavernInput)
    tonight = page.tabs.widget(page_tavern.TAB_TONIGHT)
    for widget in (page.hud, page.narrative, page.tavern_input):
        assert widget is not None and tonight.isAncestorOf(widget)


def test_other_tabs_host_their_panels(page):
    """世界书 / 我的故事 / 人物 / 记录 四个 Tab 各挂上对应面板（人物为本页只读卡片）。"""
    from gui.widgets.tavern.tavern_plays import PlaysPanel
    from gui.widgets.tavern.tavern_trace import TracePanel
    from gui.widgets.tavern.tavern_worldbook import WorldbookPanel

    assert isinstance(page.worldbook, WorldbookPanel)
    assert isinstance(page.plays, PlaysPanel)
    assert isinstance(page.trace, TracePanel)
    assert page.worldbook.isAncestorOf(page.allow_propose_check) is False  # 设置行与面板并列
    assert page.tabs.widget(page_tavern.TAB_WORLDBOOK).isAncestorOf(page.worldbook)
    assert page.tabs.widget(page_tavern.TAB_PLAYS).isAncestorOf(page.plays)
    assert page.tabs.widget(page_tavern.TAB_TRACE).isAncestorOf(page.trace)
    assert page.tabs.widget(page_tavern.TAB_CAST).isAncestorOf(page._cast_scroll)


# ===========================================================================
# 换肤（本页独占订阅）
# ===========================================================================
def test_theme_changed_reapplies_all_six_widgets(page, qapp):
    """``theme_changed`` → 6 个控件的 ``apply_theme()`` 各恰好一次。"""
    widgets = {
        "hud": page.hud,
        "narrative": page.narrative,
        "input": page.tavern_input,
        "worldbook": page.worldbook,
        "plays": page.plays,
        "trace": page.trace,
    }
    spies = {}
    for name, widget in widgets.items():
        spy = MagicMock()
        widget.apply_theme = spy          # 实例级替换：只统计本页调用
        spies[name] = spy

    page.app_ctx.theme_engine.theme_changed.emit("ui_night")
    qapp.processEvents()

    assert len(spies) == 6
    for name, spy in spies.items():
        assert spy.call_count == 1, name


def test_page_colors_come_from_theme_color_at_use_time(page, ctx, qapp):
    """取色**读时现取**：换色后重刷即跟随（不缓存旧色值）。"""
    page.app_ctx.theme_engine.get_color = lambda key, fallback: "#abcdef"
    page._on_theme_changed("ui_minimal")
    qapp.processEvents()
    assert "#abcdef" in page._cast_title.styleSheet()
    assert "#abcdef" in page.reroll_btn.styleSheet()


# ===========================================================================
# 退出收口（QThread 崩溃防线）
# ===========================================================================
def test_about_to_quit_stops_worker_saves_and_is_idempotent(page, qapp):
    """``aboutToQuit`` → ``stop(2000)`` + ``save()``；重复触发/重复调用槽均幂等。"""
    fake = MagicMock()
    page.service = fake
    assert page._quit_app is qapp, "构造期应已挂上 QApplication.aboutToQuit"

    qapp.aboutToQuit.emit()
    qapp.processEvents()
    assert fake.stop.call_args_list == [call(page_tavern.QUIT_STOP_WAIT_MS)]
    assert fake.save.call_count == 1

    # 第二次真实信号：幂等（不再调 stop / save）
    qapp.aboutToQuit.emit()
    qapp.processEvents()
    assert fake.stop.call_count == 1
    assert fake.save.call_count == 1

    # 直接重复调用槽：不抛，且不再调
    page._on_app_about_to_quit()
    page._on_app_about_to_quit()
    assert fake.stop.call_count == 1
    assert fake.save.call_count == 1


def test_about_to_quit_slot_survives_missing_service_methods(page):
    """服务缺 ``stop`` / ``save``（或本身为 None）时槽不得抛（防御性）。"""
    page.service = object()
    page._quit_handled = False
    page._on_app_about_to_quit()      # 不应抛
    page.service = None
    page._quit_handled = False
    page._on_app_about_to_quit()      # 不应抛


# ===========================================================================
# 玩家回显 / 不双发
# ===========================================================================
def test_input_submitted_echoes_player_line_without_resubmitting(page):
    """``submitted`` → ``add_player``（回显由本页负责），且**不**重发 ``submit``。"""
    echoed = []
    page.narrative.add_player = lambda text, turn=-1: echoed.append((text, turn))
    submitted = []
    page.service.submit = lambda *args, **kwargs: submitted.append((args, kwargs)) or True

    page.tavern_input.submitted.emit("我推门进去", "free")

    assert echoed == [("我推门进去", -1)]
    assert submitted == [], "页面不得在槽里再调 service.submit（会双发）"


def test_plays_changed_refreshes_plays_panel(page):
    """``plays_changed`` → 刷新「我的故事」列表（面板亦自订阅，刷新幂等，故可能 > 1 次）。"""
    calls = []
    page.plays.refresh = lambda: calls.append(1)
    page.service.plays_changed.emit()
    assert calls, "plays_changed 应触发「我的故事」刷新"

    calls.clear()
    page._on_plays_changed()
    assert calls == [1]


def test_on_enter_refreshes_service_and_settings_row(page):
    """``on_enter`` → ``service.refresh()`` + 设置行回读 + 人物面重绘。"""
    calls = []
    page.service.refresh = lambda: calls.append("refresh")
    cast_calls = []
    page.refresh_cast = lambda: cast_calls.append(1)
    page.on_enter()
    assert calls == ["refresh"]
    assert cast_calls == [1]


def test_reroll_and_edit_go_through_narrative_widget(page):
    """文本级操作经控件转发（**不**直连 ``service.reroll`` / ``service.edit_narration``）。"""
    page.service.current_narrative = lambda: [
        {"turn": 1, "role": "player", "text": "我推门进去"},
        {"turn": 1, "role": "narrator", "text": "门轴响了一声。"},
    ]
    rerolled = []
    edited = []
    page.narrative.reroll = lambda turn: rerolled.append(turn) or True
    page.narrative.edit_text = lambda turn, text: edited.append((turn, text)) or True

    page._on_reroll_clicked()
    assert rerolled == [1]

    class _FakeDialog:
        @staticmethod
        def getMultiLineText(parent, title, label, text=""):  # noqa: ARG004 - 桩
            return ("换一种说法。", True)

    real_dialog = page_tavern.QInputDialog
    page_tavern.QInputDialog = _FakeDialog
    try:
        page._on_edit_clicked()
    finally:
        page_tavern.QInputDialog = real_dialog
    assert edited == [(1, "换一种说法。")]


def test_text_actions_noop_without_narrator_entry(page):
    """没有叙述条目时点击重写 / 改字：静默不动（不抛、不下发）。"""
    page.service.current_narrative = lambda: []
    page.narrative.reroll = MagicMock()
    page.narrative.edit_text = MagicMock()
    page._on_reroll_clicked()
    page._on_edit_clicked()
    assert page.narrative.reroll.call_count == 0
    assert page.narrative.edit_text.call_count == 0


# ===========================================================================
# 「人物」Tab（只读卡片 / 中性空态）
# ===========================================================================
def test_cast_tab_shows_neutral_empty_state(page, monkeypatch):
    """内容包没有 ``cast`` → 中性空态（不空白、不崩、零数字）。"""
    monkeypatch.setattr(page_tavern, "_content_cast", lambda book_id: [])
    page.refresh_cast()

    assert page._cast_cards == []
    assert page._cast_empty.isHidden() is False
    assert page._cast_empty.text().strip()
    assert _DIGIT_RE.search(page._cast_empty.text()) is None
    assert _ORDINAL_RE.search(page._cast_empty.text()) is None


def test_cast_tab_renders_readonly_cards_from_content_pack(page, monkeypatch):
    """内容包声明 ``cast`` → 逐条只读卡片；文案零序号、零数字。"""
    monkeypatch.setattr(page_tavern, "_content_cast", lambda book_id: [
        {"cast_id": "host", "role": "老板娘",
         "card_snapshot": {"given_name": "阿萤", "description": "系着围裙，说话慢。"}},
        {"cast_id": "guest_a", "role": "客人",
         "card_snapshot": {"given_name": "带伞的人"}},
        {"cast_id": "guest_b", "role": "客人", "card_snapshot": {}},
    ])
    page.refresh_cast()

    assert len(page._cast_cards) == 3
    assert page._cast_empty.isHidden() is True

    texts = [t for card in page._cast_cards for t in _label_texts(card)]
    assert "阿萤" in texts
    assert "带伞的人" in texts
    assert "老板娘" in texts
    for text in texts:
        assert _DIGIT_RE.search(text) is None, text
        assert _ORDINAL_RE.search(text) is None, text


def test_cast_member_view_falls_back_without_inventing(page):
    """取不到姓名 → 回落角色名 / 中性占位，**绝不编造**内容。"""
    assert page_tavern._cast_member_view({})["name"] == page_tavern.CAST_UNNAMED
    assert page_tavern._cast_member_view({"role": "客人"})["name"] == "客人"
    view = page_tavern._cast_member_view({"card_snapshot": {"given_name": " 阿萤 "}})
    assert view["name"] == "阿萤"
    assert view["line"] == ""


# ===========================================================================
# 「世界书」设置行
# ===========================================================================
def test_settings_row_reads_defaults_and_writes_setting(page, tmp_path):
    """默认从 ``get_settings()`` 回读；勾选 / 预算变化 → ``set_settings(**kw)``。"""
    assert page.allow_propose_check.isChecked() is True          # 默认开启（Q1）
    assert page.budget_spin.value() == page_tavern.BUDGET_DEFAULT
    assert page.budget_spin.minimum() == page_tavern.BUDGET_MIN
    assert page.budget_spin.maximum() == page_tavern.BUDGET_MAX

    written = []
    page.service.set_settings = lambda **kwargs: written.append(kwargs) or True

    page.allow_propose_check.setChecked(False)
    assert written == [{"allow_propose": False}]

    page.budget_spin.setValue(1400)
    assert written[-1] == {"worldbook_budget_chars": 1400}


def test_settings_row_sync_does_not_write_back(page):
    """``sync_settings_row`` 只回读、不回写（否则每次进入页面都写盘一次）。"""
    written = []
    page.service.set_settings = lambda **kwargs: written.append(kwargs) or True
    page.service.get_settings = lambda: {
        "allow_propose": False, "worldbook_budget_chars": 1800,
    }
    page.sync_settings_row()
    assert page.allow_propose_check.isChecked() is False
    assert page.budget_spin.value() == 1800
    assert written == []


def test_settings_wording_has_no_anxiety_words(page):
    """设置行文案不含「性能 / 准确率 / 落后 / 开销」（R-A / D-V22-03）。"""
    blob = " ".join(_label_texts(page)) + " " + page.allow_propose_check.text()
    for word in _ANXIETY_WORDS:
        assert word not in blob, word


def test_tonight_tab_texts_have_no_numbers_or_ordinals(page):
    """「今夜」面零序号、零数值（章标题条由控件守卫，此处覆盖按钮等本页文案）。"""
    tonight = page.tabs.widget(page_tavern.TAB_TONIGHT)
    for text in _label_texts(tonight):
        assert _DIGIT_RE.search(text) is None, text
        assert _ORDINAL_RE.search(text) is None, text
    for button in (page.reroll_btn, page.edit_btn):
        assert _DIGIT_RE.search(button.text()) is None, button.text()


# ===========================================================================
# 开局 / 终局出口（P0：首次进入必须能开局；终局后必须有出口）
#   一律走**真 service + 真内容包**（仅 base_dir 指到 tmp_path），不纯桩。
# ===========================================================================
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


def test_default_book_id_comes_from_content_pack(page):
    """缺省书 id 从内容包目录集中取（**不硬编码**），且与真内容包一致。"""
    book_id = page_tavern._default_book_id()
    assert book_id and isinstance(book_id, str)
    from gui.tavern.worldbook import content_dir

    assert (content_dir() / book_id / "book.json").is_file(), "缺省书 id 应指向真实内容包"


def test_start_entry_visible_and_starts_real_play(page):
    """无活动局：开局入口**存在且可见**；点击 → 真调 ``start_play`` 且选项排出现。"""
    assert page.service.current_play() is None
    assert page._start_panel.isHidden() is False, "无局时开局入口应可见"
    assert page_tavern.START_BTN_TEXT in page._start_btn.text()

    calls = []
    real = page.service.start_play

    def _spy(book_id, **kwargs):
        calls.append(book_id)
        return real(book_id, **kwargs)

    page.service.start_play = _spy
    page._start_btn.click()

    assert calls == [page_tavern._default_book_id()], "开局应经真 service.start_play 且带上内容包书 id"
    play = page.service.current_play()
    assert play is not None and play.get("status") == "active"
    assert page.service.current_choices(), "开局后选项排仍为空 —— 玩家点不到任何东西"
    assert page._start_panel.isHidden() is True, "已有活动局 → 开局入口应隐藏"


def test_start_entry_hidden_when_play_active(page):
    """有活动局：开局入口**隐藏**（避免重复开局）。"""
    page.service.start_play(page_tavern._default_book_id())
    assert page._start_panel.isHidden() is True

    # 防御性：入口虽已隐藏，即便被误触也不得重复开局
    before = page.service.current_play_id()
    page._on_start_clicked()
    assert page.service.current_play_id() == before


def test_ended_play_shows_restart_entry_and_can_start_new_night(page):
    """终局：出现余韵引导 + 「再来一夜」；点击 → 开新局且状态回到 ``active``。"""
    page.service.start_play(page_tavern._default_book_id())
    play = _walk_to_ending(page.service)
    assert play.get("status") == "ended"
    assert page.service.current_choices() == []

    assert page._start_panel.isHidden() is False, "终局后应出现出口"
    assert page_tavern.RESTART_BTN_TEXT in page._start_btn.text()

    old_play_id = page.service.current_play_id()
    page._start_btn.click()

    new_play = page.service.current_play()
    assert new_play is not None
    assert page.service.current_play_id() != old_play_id, "再来一夜应开一局新的"
    assert new_play.get("status") == "active"
    assert page._start_panel.isHidden() is True


def test_empty_state_hint_exists_and_has_no_numbers(page):
    """空态引导文案存在，且**不含数字 / 序号**（无活动局时指向开局入口）。"""
    assert page._start_panel.isHidden() is False
    hint = page._start_hint.text()
    assert hint.strip(), "无局时应有引导文案，不能空白"
    assert _DIGIT_RE.search(hint) is None, hint
    assert _ORDINAL_RE.search(hint) is None, hint

    narrative_hint = page.narrative.empty_text()
    assert narrative_hint.strip()
    assert _DIGIT_RE.search(narrative_hint) is None, narrative_hint
    assert _ORDINAL_RE.search(narrative_hint) is None, narrative_hint


def test_narrative_empty_hint_switches_with_play_state(page):
    """叙述流空态文案随局状态切换：无局 → 指向入口；有局 → 中性（不误导）。"""
    assert page.narrative.empty_text() == page_tavern.NARRATIVE_EMPTY_HINT
    page.service.start_play(page_tavern._default_book_id())
    assert page.narrative.empty_text() == page_tavern.NARRATIVE_IDLE_HINT


# ===========================================================================
# 源码红线自查
# ===========================================================================
def test_page_source_has_no_direct_font_size():
    """字号只能写在 QSS：源码零 ``setPointSize(`` / ``setPixelSize(``（AST + 文本双查）。"""
    src = PAGE_SOURCE.read_text(encoding="utf-8")
    assert "setPointSize(" not in src
    assert "setPixelSize(" not in src
    banned = {"setPointSize", "setPixelSize"}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in banned, node.func.attr


def test_page_hex_literals_only_inside_fallback_table():
    """除 ``_FALLBACK_COLORS`` 外零 ``#RRGGBB`` 字面量（颜色一律经 ``theme_color`` 现取）。"""
    tree = ast.parse(PAGE_SOURCE.read_text(encoding="utf-8"))
    hexes = _hex_literals(tree)
    assert hexes, "兜底色表不应为空（否则取色兜底失效）"
    assert hexes == _fallback_table_values(tree), hexes - _fallback_table_values(tree)


def test_page_does_not_resubscribe_widget_data_signals():
    """控件自订阅数据信号（契约 §5.1）→ 本页**不** connect 这些信号（AST 判定）。"""
    src = PAGE_SOURCE.read_text(encoding="utf-8")
    connected = _connected_signal_names(src)
    assert connected, "本页应至少订阅自身的换肤 / 回显 / 列表 / 退出信号"
    assert connected & set(_WIDGET_DATA_SIGNALS) == set()


def test_page_never_calls_service_write_intents_directly():
    """本页不直连 ``service.submit`` / ``service.reroll`` / ``service.edit_narration``（防双发）。"""
    src = PAGE_SOURCE.read_text(encoding="utf-8")
    assert _direct_service_intent_calls(src) == []


def test_base_qss_declares_page_ids_and_appends_11c():
    """页面自带 id 的字号收口在 ``base.qss`` 的 11c 段（追加在 11a / 11b 之后）。"""
    qss = BASE_QSS.read_text(encoding="utf-8")
    assert qss.index("--- 11c.") > qss.index("--- 11b."), "11c 段必须追加在 11b 之后"
    for object_name in _PAGE_OBJECT_NAMES:
        body = _qss_rule_body(qss, object_name)
        assert body, f"base.qss 缺少 `#{object_name}` 规则"
        assert re.search(r"font-size:\s*\d+px", body), object_name
        assert "color" not in body, f"`#{object_name}` 不得在 QSS 里写 color（读时取色）"
