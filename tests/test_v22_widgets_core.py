# -*- coding: utf-8 -*-
"""V22-07 酒馆 UI 控件核心单测（叙述流 / 输入 + 选项 / 顶部状态条）。

覆盖（全部 **offscreen、确定性、零网络**，用假 service 桩，不触真实 LLM 存档）：
  · 叙述流：``narration_chunk`` 多次累加 → ``narration_done`` 以全文收口；
  · 叙述流：**贴底跟随** —— 追加时滚到底；**用户手动上滚后不再被强行拽回**（硬断言）；
  · 输入：``choices_changed`` → 按钮数量 / 文本正确；点击 → ``submit(value, "choice")``（计数断言）；
  · 输入：``busy_changed(True)`` → 提交禁用；``False`` → 恢复；
  · 输入：``degraded`` → 出现**行内提示**且**无 QMessageBox**（断言未弹窗）；
  · 状态条：``hud_changed`` → 显示章标题；**R-A 机器守卫**：全部 QLabel 文本零「第 N 夜/幕」
    序号、零进度 / 计分数值；
  · **零字号守卫**：三个控件的源码 AST / 文本扫描均无 ``setPointSize(`` / ``setPixelSize(``；
  · **颜色不硬编码**：颜色取自 ``theme_color``（stub 返回固定色 → 断言控件样式含该色）。

GUI 一律 ``QT_QPA_PLATFORM=offscreen``；起止不依赖真事件循环、不注册真实图标字体。
"""
import ast
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui.qt_compat import QApplication, QLabel, QMessageBox, QObject, QProgressBar, Signal

ROOT = Path(__file__).resolve().parents[1]

#: R-A 序号形态（「第 N 夜/幕/回合/章/节/轮/次」）。
_ORDINAL_RE = re.compile(r"第\s*[0-9]+\s*[夜幕回合章节轮次]")
#: 任意 ASCII 数字（进度 / 计分 / 序号一律含数字 → 命中即视为违规）。
_DIGIT_RE = re.compile(r"[0-9]")

WIDGET_FILES = (
    ROOT / "gui" / "widgets" / "tavern" / "tavern_narrative.py",
    ROOT / "gui" / "widgets" / "tavern" / "tavern_input.py",
    ROOT / "gui" / "widgets" / "tavern" / "tavern_hud.py",
)


# ---------------------------------------------------------------------------
# 假 service（带同名信号 / 方法，不依赖真实存档 / LLM / 网络）
# ---------------------------------------------------------------------------
class FakeService(QObject):
    """``TavernService`` 的最小桩：同名信号 + 查询面 + 动作（记录调用以便断言）。"""

    narration_chunk = Signal(str)
    narration_done = Signal(str)
    play_changed = Signal(str)
    degraded = Signal(str)
    plays_changed = Signal()
    turn_ready = Signal(dict)
    hud_changed = Signal(dict)
    choices_changed = Signal(list)
    worldbook_changed = Signal(dict)
    summary_changed = Signal(dict)
    busy_changed = Signal(bool)
    read_only_changed = Signal(bool)

    def __init__(self, *, colors=None, narrative=None, choices=None, hud=None,
                 busy=False, read_only=False):
        super().__init__()
        self._colors = dict(colors or {})
        self._narrative = list(narrative or [])
        self._choices = list(choices or [])
        self._hud = dict(hud or {})
        self._busy = bool(busy)
        self._read_only = bool(read_only)
        self.submit_calls = []
        self.reroll_calls = []
        self.edit_calls = []

    # 主题（现取语义色）
    def theme_color(self, key, fallback):
        return self._colors.get(key, fallback)

    # 只读查询面
    def current_narrative(self):
        return list(self._narrative)

    def current_choices(self):
        return list(self._choices)

    def current_hud(self):
        return dict(self._hud)

    def is_busy(self):
        return self._busy

    def is_read_only(self):
        return self._read_only

    # 动作
    def submit(self, text, input_kind="free"):
        self.submit_calls.append((text, input_kind))
        return True

    def reroll(self, turn):
        self.reroll_calls.append(turn)
        return True

    def edit_narration(self, turn, text):
        self.edit_calls.append((turn, text))
        return True


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _motion_reset():
    """每例前后收束动效内核（防忙态循环外泄到其它测试）。"""
    from gui import motion

    before = motion.level()
    yield
    try:
        motion.stop_all()
    finally:
        motion.configure(before)


def _make_service(colors=None, **kwargs):
    from gui.qt_compat import QApplication as _QApp
    _QApp.instance() or _QApp([])
    return FakeService(colors=colors, **kwargs)


# ===========================================================================
# 叙述流
# ===========================================================================
def test_narration_chunk_accumulates_then_done_finalizes(qapp):
    from gui.widgets.tavern.tavern_narrative import TavernNarrative

    svc = FakeService()
    w = TavernNarrative(svc)
    w.resize(360, 220)
    w.show()
    qapp.processEvents()

    for chunk in ("灯", "笼", "还亮着"):
        svc.narration_chunk.emit(chunk)
    qapp.processEvents()
    assert w.live_text() == "灯笼还亮着"
    assert w.block_texts()[-1] == "灯笼还亮着"

    svc.narration_done.emit("灯笼还亮着，风从门缝钻进来。")
    qapp.processEvents()
    assert w.block_texts()[-1] == "灯笼还亮着，风从门缝钻进来。"
    assert w.live_text() == ""
    w.close()


def test_narration_rebuilds_from_query_surface(qapp):
    from gui.widgets.tavern.tavern_narrative import TavernNarrative

    svc = FakeService(narrative=[
        {"turn": 1, "role": "player", "text": "我推门进去", "input_kind": "free", "at": ""},
        {"turn": 1, "role": "narrator", "text": "门轴响了一声。", "input_kind": "free", "at": ""},
    ])
    w = TavernNarrative(svc)
    w.show()
    qapp.processEvents()
    assert w.block_texts() == ["我推门进去", "门轴响了一声。"]
    w.close()


def test_narration_follows_bottom_and_respects_user_scroll(qapp):
    from gui.widgets.tavern.tavern_narrative import FOLLOW_EPSILON_PX, TavernNarrative

    svc = FakeService()
    w = TavernNarrative(svc)
    w.resize(360, 140)
    w.show()
    qapp.processEvents()

    # 灌入足够内容撑出纵向滚动条
    svc.narration_chunk.emit("阿" * 400)
    qapp.processEvents()
    bar = w.scroll_area().verticalScrollBar()
    assert bar.maximum() > 0, "内容应溢出以形成滚动条"

    # ① 追加时自动滚到底（贴底跟随）
    assert w.is_following() is True
    assert bar.value() >= bar.maximum() - FOLLOW_EPSILON_PX

    # ② 用户手动上滚 → 不再贴底
    bar.setValue(0)
    qapp.processEvents()
    assert w.is_following() is False
    pinned = bar.value()

    # ③ 再追加内容：**绝不**把用户强行拽回底部
    svc.narration_chunk.emit("乙" * 400)
    qapp.processEvents()
    assert bar.value() <= pinned + FOLLOW_EPSILON_PX
    assert bar.value() < bar.maximum() - FOLLOW_EPSILON_PX
    w.close()


def test_narration_reroll_and_edit_forward_to_service(qapp):  # noqa: ARG001
    from gui.widgets.tavern.tavern_narrative import TavernNarrative

    svc = FakeService()
    w = TavernNarrative(svc)
    assert w.reroll(3) is True
    assert svc.reroll_calls == [3]
    assert w.edit_text(3, "换一种说法") is True
    assert svc.edit_calls == [(3, "换一种说法")]


# ===========================================================================
# 输入 + 选项
# ===========================================================================
def test_choices_render_click_submits_choice(qapp):
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService(choices=[
        {"choice_id": "c1", "label": "问她照片里的人"},
        {"choice_id": "c2", "label": "先喝一口"},
    ])
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    buttons = w.choice_buttons()
    assert len(buttons) == 2
    assert "问她照片里的人" in buttons[0].text()
    assert "先喝一口" in buttons[1].text()

    buttons[0].click()
    qapp.processEvents()
    assert svc.submit_calls == [("c1", "choice")]

    # 兼容别名形状 {"text","value","kind"}
    svc.choices_changed.emit([{"text": "静静等她开口", "value": "v3", "kind": "choice"}])
    qapp.processEvents()
    buttons = w.choice_buttons()
    assert len(buttons) == 1
    assert "静静等她开口" in buttons[0].text()
    buttons[0].click()
    qapp.processEvents()
    assert svc.submit_calls[-1] == ("v3", "choice")
    w.close()


def test_choice_click_routes_machine_id_but_echoes_chinese_label(qapp):
    """点击选项：``submit`` 拿 ``choice_id``（路由要它），``submitted`` 发中文 label（回显要它）。

    旧缺陷：两者都发 ``choice_id`` → 玩家在叙述流里看到自己的动作变成 ``sit_down``。
    """
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService(choices=[{"choice_id": "sit_down", "label": "在吧台前坐下"}])
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    echoed = []
    w.submitted.connect(lambda text, kind: echoed.append((text, kind)))

    w.choice_buttons()[0].click()
    qapp.processEvents()

    assert svc.submit_calls == [("sit_down", "choice")], "路由必须仍用机器名（resolve_choice 靠它）"
    assert echoed == [("在吧台前坐下", "choice")], "回显必须是中文 label，不是机器名"
    w.close()


def test_free_input_echo_is_verbatim_text(qapp):
    """自由输入档回显不受影响：原样发玩家敲的字。"""
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService()
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    echoed = []
    w.submitted.connect(lambda text, kind: echoed.append((text, kind)))
    w.input_edit().setPlainText("我想把那盏灯挪近一点")
    w.send_button().click()
    qapp.processEvents()

    assert echoed == [("我想把那盏灯挪近一点", "free")]
    w.close()

def test_free_input_submits_and_clears(qapp):
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService()
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    w.input_edit().setPlainText("我想把那盏灯挪近一点")
    w.send_button().click()
    qapp.processEvents()
    assert svc.submit_calls == [("我想把那盏灯挪近一点", "free")]
    assert w.input_edit().toPlainText() == ""
    w.close()


def test_busy_disables_submit_then_restores(qapp):
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService()
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    svc.busy_changed.emit(True)
    qapp.processEvents()
    assert w.send_button().isEnabled() is False
    assert w.input_edit().isEnabled() is False

    w.input_edit().setPlainText("想做点什么")
    before = len(svc.submit_calls)
    w.send_button().click()  # 禁用态 → 不触发提交
    assert len(svc.submit_calls) == before

    svc.busy_changed.emit(False)
    qapp.processEvents()
    assert w.send_button().isEnabled() is True
    w.send_button().click()
    qapp.processEvents()
    assert svc.submit_calls[-1] == ("想做点什么", "free")
    w.close()


def test_degraded_shows_inline_hint_without_messagebox(qapp, monkeypatch):
    from gui.widgets.tavern.tavern_input import TavernInput

    popped = []
    for name in ("information", "warning", "critical", "question", "about"):
        monkeypatch.setattr(
            QMessageBox, name,
            staticmethod(lambda *a, **k: popped.append(name)), raising=False,
        )

    svc = FakeService()
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    hint = "这份存档来自更高的版本，本期只能看一看。"
    svc.degraded.emit(hint)
    qapp.processEvents()

    assert w.hint_text() == hint          # 行内提示出现
    assert popped == []                   # 未弹任何 QMessageBox
    assert w.findChildren(QProgressBar) == []   # 也不用进度条
    w.close()


# ===========================================================================
# 顶部状态条（R-A 机器守卫）
# ===========================================================================
def _label_texts(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


def test_hud_shows_chapter_title_and_has_no_ordinals_or_numbers(qapp):
    from gui.widgets.tavern.tavern_hud import TavernHud

    svc = FakeService(hud={
        "chapter_title": "灯笼还亮着",
        "scene_id": "甬道尽头",
        "held_items": ["手帕", "铜钥匙"],
        "read_only": False,
        "degraded": False,
    })
    w = TavernHud(svc)
    w.show()
    qapp.processEvents()

    assert w.chapter_text() == "灯笼还亮着"
    assert "灯笼还亮着" in w.label_texts()

    for text in _label_texts(w):
        assert _ORDINAL_RE.search(text) is None, text
        assert _DIGIT_RE.search(text) is None, text

    # 投喂**脏载荷**（含序号 / 机器 id / 计数）→ 界面仍须零序号、零数值
    svc.hud_changed.emit({
        "title": "第 3 夜 · 灯笼还亮着",
        "scene": "scene_02",
        "held_items": ["第2枚硬币", "进度 3/7"],
        "read_only": False,
        "busy": False,
        "turn": 5,
    })
    qapp.processEvents()

    assert "灯笼还亮着" in w.chapter_text()
    for text in _label_texts(w):
        assert _ORDINAL_RE.search(text) is None, text
        assert _DIGIT_RE.search(text) is None, text
    w.close()


def test_hud_read_only_and_busy_visible_without_progress_bar(qapp):
    from gui.widgets.tavern.tavern_hud import TavernHud

    svc = FakeService()
    w = TavernHud(svc)
    w.show()
    qapp.processEvents()

    svc.busy_changed.emit(True)
    qapp.processEvents()
    assert any("正在续写" in t for t in w.label_texts())

    svc.busy_changed.emit(False)
    qapp.processEvents()
    svc.read_only_changed.emit(True)
    qapp.processEvents()
    assert any("只读存档" in t for t in w.label_texts())

    assert w.findChildren(QProgressBar) == []
    w.close()


# ===========================================================================
# 纪律守卫：零字号 + 颜色取自 theme_color
# ===========================================================================
def test_zero_direct_font_size_in_widget_sources():
    """三个控件源码 AST / 文本扫描均无 setPointSize / setPixelSize 调用。"""
    banned_attrs = {"setPointSize", "setPixelSize"}
    for path in WIDGET_FILES:
        text = path.read_text(encoding="utf-8")
        assert "setPointSize(" not in text, path
        assert "setPixelSize(" not in text, path
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned_attrs, (path, node.func.attr)


def test_colors_come_from_theme_color(qapp):  # noqa: ARG001
    from gui.widgets.tavern.tavern_hud import TavernHud
    from gui.widgets.tavern.tavern_input import TavernInput
    from gui.widgets.tavern.tavern_narrative import TavernNarrative

    keys = (
        "text", "text_secondary", "text_hint", "bg_card", "bg_light", "surface_muted",
        "divider", "border", "focus_accent", "primary", "primary_dark", "accent",
        "state_ok", "state_warn", "disabled_bg", "disabled_text", "text_on_accent",
    )
    svc = FakeService(colors={k: "#123456" for k in keys})

    for factory in (TavernHud, TavernInput, TavernNarrative):
        widget = factory(svc)
        widget.apply_theme()
        assert "#123456" in widget.styleSheet(), factory.__name__

    # 换色后 apply_theme 现取新色（**不缓存**）
    svc._colors["accent"] = "#abcdef"
    hud = TavernHud(svc)
    hud.apply_theme()
    assert "#abcdef" in hud.styleSheet()


# ---------------------------------------------------------------------------
# 批次 C（C-0④）：缺 label 的选项 —— 中性占位，**绝不**回落机器名
#
# 旧写法 ``label = value``（缺 label 时回落 ``choice_id``）在当时的真 service 上不可达
# （``service._choice_snapshot`` 已中性化），但那是**旁路**：任何绕过 service 的载荷
# （旧档 / 兼容别名 / 未来新调用方）都会把 ``sit_down`` 这类下划线机器名直接送上按钮。
# ---------------------------------------------------------------------------

def test_normalize_choices_missing_label_uses_neutral_placeholder():
    """缺 ``label`` / ``text`` → 中性占位，**绝不**等于 ``value``（机器名）。"""
    from gui.widgets.tavern.tavern_input import _normalize_choices

    out = _normalize_choices([
        {"choice_id": "sit_down"},                       # 缺 label
        {"choice_id": "ask_photo", "label": "问她那张照片"},
        {"value": "look_closer", "text": ""},            # label 为空串
        {"choice_id": "x", "label": "   "},              # label 全空白
    ])
    assert [c["value"] for c in out] == ["sit_down", "ask_photo", "look_closer", "x"]
    assert out[0]["label"] != "sit_down", "缺 label 时回落成了机器名（旁路）"
    assert out[0]["label"] == "（未命名的动作）"
    assert out[1]["label"] == "问她那张照片"
    assert out[2]["label"] == "（未命名的动作）"
    assert out[3]["label"] == "（未命名的动作）"


def test_normalize_choices_neutral_label_matches_service_single_source():
    """控件层的中性占位必须与 ``service.NEUTRAL_CHOICE_LABEL`` **逐字节一致**（防漂移）。"""
    from gui.tavern.service import NEUTRAL_CHOICE_LABEL
    from gui.widgets.tavern.tavern_input import _NEUTRAL_CHOICE_LABEL

    assert _NEUTRAL_CHOICE_LABEL == NEUTRAL_CHOICE_LABEL


def test_choice_button_never_shows_machine_id_when_label_missing(qapp):
    """控件级旁路：``choices_changed`` 里缺 label → 按钮文本不得出现机器名。"""
    from gui.widgets.tavern.tavern_input import TavernInput

    svc = FakeService()
    w = TavernInput(svc)
    w.show()
    qapp.processEvents()

    svc.choices_changed.emit([{"choice_id": "sit_down"}])
    qapp.processEvents()

    buttons = w.choice_buttons()
    assert len(buttons) == 1
    text = buttons[0].text()
    assert "sit_down" not in text, f"按钮上出现了机器名：{text!r}"
    assert "（未命名的动作）" in text
    w.close()
