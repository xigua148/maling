# -*- coding: utf-8 -*-
"""v2.x 加载体感落点（第三批）：``LoopIndicator`` + 三处接线（①思考 ②免提 ③看屏）。

覆盖：
  · ``LoopIndicator`` 四形态固定小尺寸（防 v1.4.9「太大」回退）；
  · 循环经 ``motion.loop`` 收口：``off`` 不启、隐藏即停、``stop_all`` 一并停、
    禁用中途自停切静态；
  · 静态基态**非空白**（对透明底 render 后统计墨量 > 0）；
  · 相位确实驱动画面（不同相位渲染差异 > 0）；
  · 三处落点：① 思考（接口一致性，隐藏即停细项见 test_v21_motion）
    ② 免提聆听 ③ 看屏在看。

**阶段 B「融入度」复核后回退（2026-09-11）**：① 思考 → 去几何三点、回**文字省略号节奏**；
② 免提 → bars(4 柱) → **pulse(单点呼吸)**；③ 看屏 → **去涟漪图形**（回到既有 👀 文案，
本控件不再有循环）。三处回退后断言同步更新；`LoopIndicator` 四形态本体测试**保留不变**。
详见 ``_phaseB_report.md`` / ``_phaseB_revert_report.md``。

> **不依赖真事件循环**：相位推进走 ``motion._tick_loops(now=...)`` / 句柄属性注入；
> 隐藏即停用 ``QWidget.hide()`` 同步触发 ``hideEvent``。GUI 走 offscreen。
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import gui.motion as motion
from gui.qt_compat import QApplication, QColor, QImage, Qt
from gui.widgets.loop_indicator import LoopIndicator

_ARGB = QImage.Format.Format_ARGB32


@pytest.fixture(autouse=True)
def _reset_motion(monkeypatch):
    motion.stop_all(final=True)
    motion.configure("standard")
    monkeypatch.setattr(motion, "system_animations_enabled", lambda: True)
    yield
    motion.stop_all(final=True)
    motion.configure("standard")


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _ctx():
    return SimpleNamespace(theme_engine=None, config=None)


def _show(w):
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.show()
    return w


def _render(w):
    """对**透明底**渲染控件（控件无自绘背景 → 非透明像素 = 图形墨量）。"""
    img = QImage(w.size(), _ARGB)
    img.fill(0)
    w.render(img)
    return img


def _ink(w):
    img = _render(w)
    return sum(
        1
        for y in range(img.height())
        for x in range(img.width())
        if QColor(img.pixel(x, y)).alpha() > 0
    )


def _img_diff(a, b):
    return sum(
        1
        for y in range(a.height())
        for x in range(a.width())
        if a.pixel(x, y) != b.pixel(x, y)
    )


# ---------------------------------------------------------------------------
# LoopIndicator 本体
# ---------------------------------------------------------------------------
class TestLoopIndicator:
    def test_shape_sizes_are_small(self, qapp):
        """四形态固定小尺寸（宽度 ≤ 20px，防"大字版"回退）。"""
        for shape, (w, h) in (("typing", (20, 12)), ("bars", (18, 12)),
                              ("ripple", (14, 14)), ("pulse", (14, 14))):
            ind = LoopIndicator(shape)
            assert (ind.width(), ind.height()) == (w, h)
            assert ind.width() <= 20 and ind.height() <= 18

    def test_start_stop_loop_accounting(self, qapp):
        motion.configure("standard")
        ind = _show(LoopIndicator("typing"))
        base = motion.running_loop_count()
        ind.start()
        assert ind.is_running() is True
        assert motion.running_loop_count() == base + 1
        ind.stop()
        assert ind.is_running() is False
        assert motion.running_loop_count() == base

    def test_off_is_static_and_non_blank(self, qapp):
        """R-Q：``off`` 档不起循环，但静态基态**必须有内容**（不得空白）。"""
        motion.configure("off")
        for shape in ("typing", "bars", "ripple", "pulse"):
            ind = _show(LoopIndicator(shape))
            ind.start()
            assert ind.is_running() is False
            assert motion.running_loop_count() == 0
            assert _ink(ind) > 0, "静态基态不得空白：%s" % shape

    def test_hide_stops_and_reshow_resumes(self, qapp):
        ind = _show(LoopIndicator("bars"))
        ind.start()
        assert ind.is_running() is True
        ind.hide()
        assert ind.is_running() is False
        assert motion.running_loop_count() == 0
        ind.show()
        assert ind.is_running() is True          # 业务意图仍在 → 复启

    def test_disabled_mid_run_self_stops(self, qapp, monkeypatch):
        """因禁用而停：``enabled()`` 变 False → 下一 tick 自停并切静态。"""
        ind = _show(LoopIndicator("ripple"))
        ind.start()
        assert ind.is_running() is True
        monkeypatch.setattr(motion, "system_animations_enabled", lambda: False)
        motion._tick_loops()
        assert ind.is_running() is False
        assert motion.running_loop_count() == 0

    def test_stop_all_stops_everything(self, qapp):
        a = _show(LoopIndicator("typing"))
        b = _show(LoopIndicator("pulse"))
        a.start(); b.start()
        assert motion.running_loop_count() == 2
        motion.stop_all(final=True)
        assert motion.running_loop_count() == 0
        assert a.is_running() is False and b.is_running() is False

    def test_phase_drives_painting(self, qapp):
        """相位确实驱动画面；静态基态与动效帧不同。"""
        for shape in ("typing", "bars", "ripple", "pulse"):
            ind = _show(LoopIndicator(shape))
            ind.start()
            ind._phase = 0.0
            ind.update()
            frame_a = _render(ind)
            ind._phase = 0.25
            ind.update()
            frame_b = _render(ind)
            assert _img_diff(frame_a, frame_b) > 0, shape
            ind.stop()
            static = _render(ind)
            assert _img_diff(frame_a, static) > 0, "%s 静态==动效" % shape
            ind.hide()


# ---------------------------------------------------------------------------
# 落点② 免提聆听
# ---------------------------------------------------------------------------
class TestHandsfreeLanding:
    def test_listening_loop_lifecycle(self, qapp):
        from gui.widgets.handsfree_bar import HandsfreeBar

        bar = _show(HandsfreeBar(_ctx()))
        assert bar._indicator.is_running() is False
        bar.set_state("listening")
        assert bar._indicator.is_running() is True
        assert motion.running_loop_count() == 1
        bar.set_state("recognizing")
        assert bar._indicator.is_running() is False
        assert motion.running_loop_count() == 0

    def test_hidden_stops_loop(self, qapp):
        from gui.widgets.handsfree_bar import HandsfreeBar

        bar = _show(HandsfreeBar(_ctx()))
        bar.set_state("listening")
        assert bar._indicator.is_running() is True
        bar.hide()
        assert bar._indicator.is_running() is False
        assert motion.running_loop_count() == 0

    def test_off_static_non_blank(self, qapp):
        from gui.widgets.handsfree_bar import HandsfreeBar

        motion.configure("off")
        bar = _show(HandsfreeBar(_ctx()))
        bar.set_state("listening")
        assert bar._indicator.is_running() is False
        assert _ink(bar._indicator) > 0

    def test_indicator_is_pulse_shape_width_14(self, qapp):
        """② 形态 = pulse（14×14）；**阶段 B 回退**：bars(4 柱) → pulse(单点呼吸)。

        回退理由见 ``_phaseB_report.md §2②``（柱条=外来"音频电平"母题，与本控件
        自述"非音频电平"自相矛盾）。切档不改控件尺寸（不跳版）。
        """
        from gui.widgets.handsfree_bar import HandsfreeBar

        bar = _show(HandsfreeBar(_ctx()))
        assert bar._indicator._shape == "pulse"
        assert (bar._indicator.width(), bar._indicator.height()) == (14, 14)
        bar.set_state("listening")
        on_size = (bar._indicator.width(), bar._indicator.height())
        motion.configure("off")
        motion.stop_all(final=True)
        assert (bar._indicator.width(), bar._indicator.height()) == on_size
        motion.configure("standard")


# ---------------------------------------------------------------------------
# 落点③ 看屏"在看"
# ---------------------------------------------------------------------------
class TestScreenWatchLanding:
    """③ 看屏"在看"——**阶段 B 回退后**：涟漪图形已移除，本控件**无任何循环**。"""

    def test_no_indicator_no_loop(self, qapp):
        """回退后本控件不起任何循环（涟漪已删；无 `_wave` 字段）。"""
        from gui.widgets.screen_watch_bar import (
            ScreenWatchBar, STATE_RUNNING, STATE_PAUSED, STATE_IDLE,
        )

        bar = _show(ScreenWatchBar(_ctx()))
        assert not hasattr(bar, "_wave")
        for st in (STATE_RUNNING, STATE_PAUSED, STATE_IDLE, STATE_RUNNING):
            bar.set_state(st)
            assert motion.running_loop_count() == 0
        bar.hide()
        assert motion.running_loop_count() == 0

    def test_no_graphic_residue_and_text_non_blank(self, qapp):
        """回退后：**无任何自绘指示图形残留**，状态文案仍在（不空白）。"""
        from gui.widgets.screen_watch_bar import ScreenWatchBar, STATE_RUNNING

        bar = _show(ScreenWatchBar(_ctx()))
        bar.set_state(STATE_RUNNING)
        assert bar.findChild(LoopIndicator) is None       # 无自绘几何图形
        assert bar._status.text()                          # 文案非空
        assert "在看" in bar._status.text()


# ---------------------------------------------------------------------------
# 落点① 思考指示器（**阶段 B 回退后**：纯文字省略号节奏；隐藏即停细项见 test_v21_motion）
# ---------------------------------------------------------------------------
class TestThinkingLanding:
    def test_contract_kept(self, qapp):
        from gui.widgets.thinking_indicator import ThinkingIndicator

        motion.configure("standard")
        w = _show(ThinkingIndicator("AI 正在思考", app_context=None))
        w.start()
        assert w._active is True
        assert motion.running_loop_count() == 1          # 文字节奏经 motion.loop 收口
        w.set_text("正在生成")
        assert "正在生成" in w._label.text()
        w.update_theme()
        w.stop()
        assert w._active is False
        assert motion.running_loop_count() == 0

    def test_no_geometry_indicator(self, qapp):
        """回退后：**无任何自绘几何图形控件**（LoopIndicator 已从本控件移除）。"""
        from gui.widgets.thinking_indicator import ThinkingIndicator

        w = _show(ThinkingIndicator("AI 正在思考", app_context=None))
        w.start()
        assert w.findChild(LoopIndicator) is None
        w.stop()

    def test_off_is_static_text_not_blank(self, qapp):
        """R-Q：``off`` 档定格为**静态纯文字省略号**，无几何图形、不空白。"""
        from gui.widgets.thinking_indicator import ThinkingIndicator

        motion.configure("off")
        try:
            w = _show(ThinkingIndicator("AI 正在思考", app_context=None))
            w.start()
            assert motion.running_loop_count() == 0
            assert w._dots.text() == "…"                 # 静态纯文字
            # v2.1(UI)：文案改为「<当前角色名> 正在思考」，不再绑死 "AI"
            _t = w._label.text()
            assert _t.strip()
            assert _t.endswith("正在思考")
            assert w.findChild(LoopIndicator) is None
        finally:
            motion.configure("standard")

    def test_dots_fixed_width_no_layout_jitter(self, qapp):
        """回退后：省略号循环**不改变任何控件几何**（固定宽 → 无版式抖动）。"""
        from gui.widgets.thinking_indicator import ThinkingIndicator

        motion.configure("standard")
        w = _show(ThinkingIndicator("AI 正在思考", app_context=None))
        w.start()
        try:
            seen = set()
            for p in (0.0, 0.26, 0.51, 0.76, 0.99):
                w._on_tick(p)
                qapp.processEvents()
                seen.add((
                    w._dots.width(),
                    w._label.geometry().x(),
                    w._label.width(),
                    w.size().width(),
                ))
            assert len(seen) == 1, "版式抖动：%r" % (seen,)
        finally:
            w.stop()
