# -*- coding: utf-8 -*-
"""v2.1(P1)：按钮按压反馈铺开的回归测试。

覆盖点（此前 transitions 无任何测试）：
  ① 递归安装覆盖 ``QPushButton``（含子类）与 ``QToolButton``；
  ② 幂等（重复安装返回 0，不重复装过滤器）；
  ③ 已挂「非 opacity」图形效果的控件自动跳过（不抢占 elevation 阴影等）；
  ④ ``off`` 档不安装任何东西（界面必须完全正常）；
  ⑤ 对话框：显示时由应用级过滤器自动铺开；
  ⑥ 行为：按下变暗 → 松开复原（只改 opacity）。
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QMouseEvent

import gui.motion as motion
from gui import transitions
from gui.qt_compat import (
    QApplication, QDialog, QEvent, QGraphicsDropShadowEffect,
    QPushButton, QToolButton, QVBoxLayout, QWidget, Qt,
)

_PROP = "pressFeedbackInstalled"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_motion():
    old = motion.level()
    motion.stop_all(final=True)
    motion.configure("standard")
    yield
    motion.stop_all(final=True)
    motion.configure(old)


def _mouse(etype) -> QMouseEvent:
    """构造左键鼠标事件（用带全局坐标的构造，避免 PySide6 弃用告警）。"""
    return QMouseEvent(etype, QPointF(5, 5), QPointF(5, 5),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _installed(root) -> int:
    return sum(1 for w in root.findChildren(QWidget) if w.property(_PROP))


def _pump(qapp, timeout_s: float = 2.0) -> None:
    """驱动事件循环直到动画登记表清空（或超时）。"""
    deadline = time.time() + timeout_s
    while motion.running_count() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


# ---------------------------------------------------------------------------
# ① 覆盖范围：QPushButton + QToolButton
# ---------------------------------------------------------------------------
def test_recursive_covers_push_and_tool_button(qapp):
    root = QWidget()
    lay = QVBoxLayout(root)
    for _ in range(3):
        lay.addWidget(QPushButton("pb"))
    for _ in range(2):
        lay.addWidget(QToolButton())

    n = transitions.install_press_feedback_recursive(root)
    assert n == 5, f"应装 5 个（3 QPushButton + 2 QToolButton），实装 {n}"
    assert _installed(root) == 5


def test_recursive_returns_zero_for_empty_widget(qapp):
    assert transitions.install_press_feedback_recursive(QWidget()) == 0
    assert transitions.install_press_feedback_recursive(None) == 0


# ---------------------------------------------------------------------------
# ② 幂等
# ---------------------------------------------------------------------------
def test_recursive_is_idempotent(qapp):
    root = QWidget()
    QVBoxLayout(root).addWidget(QPushButton("x"))
    assert transitions.install_press_feedback_recursive(root) == 1
    assert transitions.install_press_feedback_recursive(root) == 0, "重复安装不应再计数"
    assert _installed(root) == 1


# ---------------------------------------------------------------------------
# ③ 已有「非 opacity」效果的控件 → 跳过（不抢占 elevation 阴影）
# ---------------------------------------------------------------------------
def test_skips_widget_with_non_opacity_effect(qapp):
    btn = QPushButton("shadowed")
    btn.setGraphicsEffect(QGraphicsDropShadowEffect(btn))
    assert transitions.install_press_feedback(btn) is None
    assert not btn.property(_PROP), "不得在已有非 opacity effect 的控件上标记安装"


def test_reuses_existing_opacity_effect(qapp):
    from gui.qt_compat import QGraphicsOpacityEffect

    btn = QPushButton("faded")
    eff = QGraphicsOpacityEffect(btn)
    btn.setGraphicsEffect(eff)
    filt = transitions.install_press_feedback(btn)
    assert filt is not None
    assert btn.graphicsEffect() is eff, "已有 opacity effect 应被复用，不新建"


# ---------------------------------------------------------------------------
# ④ off 档 → 不安装任何东西
# ---------------------------------------------------------------------------
def test_off_level_installs_nothing(qapp):
    motion.configure("off")
    root = QWidget()
    QVBoxLayout(root).addWidget(QPushButton("x"))
    QVBoxLayout(root).addWidget(QToolButton())
    assert transitions.install_press_feedback_recursive(root) == 0
    assert _installed(root) == 0
    assert transitions.install_press_feedback(root.findChildren(QPushButton)[0]) is None


# ---------------------------------------------------------------------------
# ⑤ 对话框：显示时自动铺开
# ---------------------------------------------------------------------------
def test_dialog_buttons_get_feedback_on_show(qapp):
    assert transitions.install_press_feedback_for_dialogs(qapp) is True

    dlg = QDialog()
    lay = QVBoxLayout(dlg)
    lay.addWidget(QPushButton("ok"))
    lay.addWidget(QPushButton("cancel"))
    assert _installed(dlg) == 0, "未显示前不应安装"

    dlg.show()
    qapp.processEvents()
    assert _installed(dlg) == 2, "显示后对话框内按钮应已铺开"


def test_dialog_filter_idempotent(qapp):
    assert transitions.install_press_feedback_for_dialogs(qapp) is True
    assert transitions.install_press_feedback_for_dialogs(qapp) is True


# ---------------------------------------------------------------------------
# ⑥ 行为：按下变暗 → 松开复原（只改 opacity，不动 geometry/size）
# ---------------------------------------------------------------------------
def test_press_dims_then_release_restores(qapp):
    btn = QPushButton("press me")
    btn.resize(90, 30)
    before_size = (btn.width(), btn.height())

    filt = transitions.install_press_feedback(btn)
    assert filt is not None

    def _send(etype):
        QApplication.sendEvent(btn, _mouse(etype))

    _send(QEvent.MouseButtonPress)
    _pump(qapp)
    eff = btn.graphicsEffect()
    assert eff is not None, "按下应创建/复用 opacity effect"
    assert eff.opacity() < 1.0, f"按下应变暗，实际 {eff.opacity()}"

    _send(QEvent.MouseButtonRelease)
    _pump(qapp)
    assert eff.opacity() == pytest.approx(1.0, abs=0.02), "松开应复原到不透明"
    assert (btn.width(), btn.height()) == before_size, "按压反馈不得改动尺寸"


def test_leave_resets_to_opaque(qapp):
    btn = QPushButton("leave me")
    transitions.install_press_feedback(btn)

    press = _mouse(QEvent.MouseButtonPress)
    QApplication.sendEvent(btn, press)
    _pump(qapp)
    eff = btn.graphicsEffect()
    assert eff is not None and eff.opacity() < 1.0

    QApplication.sendEvent(btn, QEvent(QEvent.Leave))
    _pump(qapp)
    assert eff.opacity() == pytest.approx(1.0, abs=0.02), "指针移出应兜底复原"


def test_uninstall_restores_and_clears_property(qapp):
    btn = QPushButton("uninstall me")
    transitions.install_press_feedback(btn)
    assert btn.property(_PROP)
    transitions.uninstall_press_feedback(btn)
    assert not btn.property(_PROP)
    assert transitions.install_press_feedback(btn) is not None, "卸载后应可重新安装"
