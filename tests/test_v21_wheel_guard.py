# -*- coding: utf-8 -*-
"""v2.1(P1)：滚轮守卫回归测试。

覆盖：
  ① 未聚焦滚轮 → 值不变，且事件转交滚动区（页面照常滚动）；
  ② 聚焦后滚轮 → 值仍不变（只允许点击/键盘改值）；
  ③ 键盘方向键仍可调（没把交互整体废掉）；
  ④ 不在滚动区里（如对话框）→ 值不变（宁可不改，不可误改）；
  ⑤ QComboBox / QSpinBox / QSlider 三类都受守卫；
  ⑥ 总开关关闭 → 恢复默认行为（可被滚轮改）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent

from gui import wheel_guard
from gui.qt_compat import (
    QApplication, QComboBox, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

#: 复用一个过滤器实例（Qt 不持有 eventFilter 所有权，必须自己保引用）
_GUARD_FILTER = wheel_guard._WheelGuard()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _guard_state():
    """每个用例前后复位守卫总开关，防外泄。"""
    wheel_guard.set_enabled(True)
    yield
    wheel_guard.set_enabled(True)


def _wheel(w, dy=120):
    pos = QPointF(w.rect().center())
    return QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, dy),
                       Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)


def _area_with(widget):
    """把控件放进一个可滚动的区域，返回 (area, widget)。"""
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    lay = QVBoxLayout(content)
    for _ in range(40):
        lay.addWidget(QWidget())
    lay.addWidget(widget)
    for _ in range(40):
        lay.addWidget(QWidget())
    area.setWidget(content)
    area.resize(300, 200)
    area.show()
    QApplication.processEvents()
    return area, widget


def _slider(value=50):
    s = QSlider(Qt.Horizontal)
    s.setRange(0, 100)
    s.setValue(value)
    return s


# ---------------------------------------------------------------------------
# ① 值不变 + 页面滚动
# ---------------------------------------------------------------------------
def test_wheel_does_not_change_value_but_scrolls_page(qapp):
    area, s = _area_with(_slider())
    s.installEventFilter(_GUARD_FILTER)
    bar = area.verticalScrollBar()
    bar.setValue(300)
    qapp.processEvents()

    v0, sc0 = s.value(), bar.value()
    QApplication.sendEvent(s, _wheel(s))
    qapp.processEvents()

    assert s.value() == v0, "滚轮不得改动滑块值"
    assert bar.value() != sc0, "滚轮应把页面滚下去（而不是被吞掉）"


# ---------------------------------------------------------------------------
# ② 聚焦后仍不改值
# ---------------------------------------------------------------------------
def test_focused_widget_still_ignores_wheel(qapp):
    area, s = _area_with(_slider())
    s.installEventFilter(_GUARD_FILTER)
    s.setFocus()
    qapp.processEvents()
    v0 = s.value()
    QApplication.sendEvent(s, _wheel(s))
    qapp.processEvents()
    assert s.value() == v0, "即使聚焦，滚轮也不得改值（只允许点击/键盘）"


# ---------------------------------------------------------------------------
# ③ 键盘仍可调
# ---------------------------------------------------------------------------
def test_keyboard_still_works(qapp):
    area, s = _area_with(_slider(50))
    s.installEventFilter(_GUARD_FILTER)
    s.setFocus()
    s.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
    assert s.value() == 51, "方向键必须仍能调整"


# ---------------------------------------------------------------------------
# ④ 不在滚动区里 → 也不改值
# ---------------------------------------------------------------------------
def test_widget_outside_scroll_area_keeps_value(qapp):
    s = _slider()
    s.show()
    qapp.processEvents()
    s.installEventFilter(_GUARD_FILTER)
    v0 = s.value()
    QApplication.sendEvent(s, _wheel(s))
    qapp.processEvents()
    assert s.value() == v0


# ---------------------------------------------------------------------------
# ⑤ 三类控件都受守卫
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["combo", "spin", "slider"])
def test_all_guarded_types(qapp, kind):
    if kind == "combo":
        w = QComboBox()
        w.addItems(["A", "B", "C"])
        w.setCurrentIndex(1)
        read = w.currentIndex
    elif kind == "spin":
        w = QSpinBox()
        w.setRange(0, 100)
        w.setValue(50)
        read = w.value
    else:
        w = _slider(50)
        read = w.value

    area, w = _area_with(w)
    w.installEventFilter(_GUARD_FILTER)
    v0 = read()
    QApplication.sendEvent(w, _wheel(w))
    qapp.processEvents()
    assert read() == v0, f"{kind} 被滚轮改动了"


def test_guarded_types_cover_three_kinds():
    from gui.qt_compat import QAbstractSpinBox

    assert QComboBox in wheel_guard.GUARDED_TYPES
    assert QAbstractSpinBox in wheel_guard.GUARDED_TYPES
    assert QSlider in wheel_guard.GUARDED_TYPES


# ---------------------------------------------------------------------------
# ⑥ 总开关关闭 → 恢复默认（可被滚轮改）
# ---------------------------------------------------------------------------
def test_disabled_restores_default_behaviour(qapp):
    wheel_guard.set_enabled(False)
    s = _slider(50)
    s.show()
    qapp.processEvents()
    s.installEventFilter(_GUARD_FILTER)
    v0 = s.value()
    QApplication.sendEvent(s, _wheel(s))
    qapp.processEvents()
    assert s.value() != v0, "关掉守卫后应恢复默认（滚轮可改值）"


# ---------------------------------------------------------------------------
# install / uninstall 幂等
# ---------------------------------------------------------------------------
def test_install_and_uninstall(qapp):
    assert wheel_guard.install(qapp) is True
    assert wheel_guard.install(qapp) is True
    wheel_guard.uninstall(qapp)
    assert wheel_guard._GUARD is None
    assert wheel_guard.install(qapp) is True
    wheel_guard.uninstall(qapp)


# ---------------------------------------------------------------------------
# ⑦ 气泡内浏览器不响应滚轮（v2.1(UI-Fix-0914)：鼠标停在气泡上滚 → 气泡内文字
#    上下跑、下方留大片空白）。做法：wheelEvent 不消费事件 → 冒泡给外层滚动区。
# ---------------------------------------------------------------------------
def test_bubble_browser_does_not_consume_wheel(qapp):
    from gui.widgets.message_bubble import _NoWheelTextBrowser

    b = _NoWheelTextBrowser()
    b.setHtml("<p>" + "<br>".join(f"line {i}" for i in range(300)) + "</p>")
    b.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    b.setFixedHeight(200)
    b.show()
    qapp.processEvents()
    assert b.verticalScrollBar().maximum() > 0, "前提：文档比控件高（可滚）"

    before = b.verticalScrollBar().value()
    ev = _wheel(b)
    b.wheelEvent(ev)
    qapp.processEvents()

    assert b.verticalScrollBar().value() == before, "气泡内文档不得被滚轮滚动"
    assert not ev.isAccepted(), "滚轮须保持未接受，才能冒泡给外层聊天滚动区"


def test_bubble_browser_is_subclass_of_text_browser():
    from gui.qt_compat import QTextBrowser
    from gui.widgets.message_bubble import _NoWheelTextBrowser

    assert issubclass(_NoWheelTextBrowser, QTextBrowser)


def test_adaptive_browser_uses_no_wheel_subclass(qapp):
    """确认气泡的内容控件确实走的是「不响应滚轮」子类。"""
    from gui.widgets.message_bubble import MessageBubble, _NoWheelTextBrowser

    w = MessageBubble._make_adaptive_browser("<p>hello</p>")
    assert isinstance(w, _NoWheelTextBrowser)


# ---------------------------------------------------------------------------
# ⑧ v2.1(P1/D-V21-01)：总开关接上真实配置键（消灭「有 set_enabled 无配置键」）
# ---------------------------------------------------------------------------
def test_config_key_default_enabled(monkeypatch, tmp_path):
    """设置项默认 True（既有行为：守卫默认开启；升级用户零变化）。"""
    import gui.config as config_mod

    monkeypatch.setattr(config_mod, "get_user_data_dir", lambda: tmp_path)
    assert config_mod.GuiConfig().wheel_guard_enabled is True


def test_config_key_missing_falls_back_enabled(monkeypatch):
    """缺键（旧存档）→ _config_enabled 回落 True（零迁移）。"""

    class _NoKeyConfig:
        @staticmethod
        def load():
            return object()  # 无 wheel_guard_enabled 属性

    import gui.config as config_mod
    monkeypatch.setattr(config_mod, "GuiConfig", _NoKeyConfig)
    assert wheel_guard._config_enabled() is True


def test_sync_from_config_seeds_disabled(monkeypatch):
    """未显式设置时，sync_from_config 按持久化配置初始化总开关。"""
    monkeypatch.setattr(wheel_guard, "_EXPLICIT", False)
    monkeypatch.setattr(wheel_guard, "_config_enabled", lambda: False)
    assert wheel_guard.sync_from_config() is False
    assert wheel_guard.ENABLED is False


def test_sync_from_config_respects_explicit(monkeypatch):
    """已显式设置过 → 启动同步不覆盖运行中的切换。"""
    wheel_guard.set_enabled(True)
    monkeypatch.setattr(wheel_guard, "_config_enabled", lambda: False)
    assert wheel_guard.sync_from_config() is True
    assert wheel_guard.ENABLED is True


def test_install_seeds_from_config(monkeypatch, qapp):
    """install() 会按配置初始化总开关（未被显式设置时）。"""
    wheel_guard.uninstall(qapp)
    monkeypatch.setattr(wheel_guard, "_EXPLICIT", False)
    monkeypatch.setattr(wheel_guard, "_config_enabled", lambda: False)
    assert wheel_guard.install(qapp) is True
    assert wheel_guard.ENABLED is False
    wheel_guard.uninstall(qapp)


def test_toggle_off_then_combo_wheel_changes_value(qapp):
    """两态对照：关 → 不再拦截（组合框值被滚轮改）。

    与 ``test_disabled_restores_default_behaviour``（滑块态）互补，覆盖评审
    点名的 QComboBox 场景。
    """
    wheel_guard.set_enabled(False)
    combo = QComboBox()
    combo.addItems(["A", "B", "C"])
    combo.setCurrentIndex(1)
    area, combo = _area_with(combo)
    combo.installEventFilter(_GUARD_FILTER)
    v0 = combo.currentIndex()
    QApplication.sendEvent(combo, _wheel(combo))
    qapp.processEvents()
    assert combo.currentIndex() != v0, "关掉守卫后组合框应恢复默认（滚轮可改值）"


def test_toggle_on_then_combo_wheel_keeps_value(qapp):
    """两态对照：开 → 拦截（组合框值不变，事件转发给滚动区）。"""
    wheel_guard.set_enabled(True)
    combo = QComboBox()
    combo.addItems(["A", "B", "C"])
    combo.setCurrentIndex(1)
    area, combo = _area_with(combo)
    combo.installEventFilter(_GUARD_FILTER)
    bar = area.verticalScrollBar()
    bar.setValue(300)
    qapp.processEvents()
    v0, sc0 = combo.currentIndex(), bar.value()
    QApplication.sendEvent(combo, _wheel(combo))
    qapp.processEvents()
    assert combo.currentIndex() == v0, "开启守卫时组合框值不得被滚轮改动"
    assert bar.value() != sc0, "滚轮应转交滚动区（页面照常滚动）"

