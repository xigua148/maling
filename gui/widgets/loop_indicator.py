# -*- coding: utf-8 -*-
"""循环指示器 —— 自绘「进行中」动效（v2.x / 走 ``motion.loop()`` 单点收口）。

四种形态（对应参考素材的纯 CSS 动画，去掉 CSS 壳只留形态）：
  · ``"typing"`` —— 3 点上下跳动（③⑥ 打字点）→ 模型请求中
  · ``"bars"``   —— 4 柱高低起伏（③ 弹跳柱条）→ 免提聆听中（**默认形态**）
  · ``"ripple"`` —— 中心点 + 同心圆涟漪（④ 波纹圆圈） → 看屏「在看」
  · ``"pulse"``  —— 单点透明度呼吸 → 免提聆听中（**回退形态**，改 "bars"↔"pulse" 一键切换）

契约（team-lead 第三批硬要求，逐条对应）：
  · **动效一律经** :func:`gui.motion.loop` —— 本控件**不自带 QTimer**
    （``design-v21.md`` 否决"每落点自写相位定时器"）；``off`` 档 / 系统关动画时
    ``loop()`` 返回 ``None`` → 直接画**静态基态**（不得空白，R-Q）。
  · **``hideEvent`` → 停循环**（隐藏即停，R-P）；``showEvent`` 仅在"业务上应动"
    （``_should_run``）时复启，不做常驻空转。
  · **因禁用而停**（``motion.stop_all`` / 档位切 ``off``）→ ``on_disabled`` 回调
    → 切**静态基态**；**落点显式** :meth:`stop`（状态结束）**不**切静态，由落点决定去向。
  · **不改布局占位**：自绘在固定小尺寸内（``sizeHint``），不新增/移动版位。
  · **静态基态 = 参考素材 ``@media (prefers-reduced-motion: reduce)`` 的 ``animation:none``
    态** —— 即各动画"关键字帧之前的元素基态"：打字点=平排 3 点、柱条=等高短柱、
    涟漪/单点=状态条既有实心 ●（看屏/免提不因关动画而改变外观）。

R-A：纯形态，无数字/进度/倒计时上屏；柱条**非**音量电平（沿用免提条"无波形分析"口径）。
R-F：仅 PySide6 内置（``QPainter``/``QColor``/``QPen``）+ 标准库。
"""
from __future__ import annotations

import math
from typing import Optional

from gui.qt_compat import QWidget, QSize, QPainter, QColor, QPen, QRectF, Qt
from gui import motion

#: 各形态的固定尺寸（宽, 高）——**刻意小**，规避 v1.4.9「太大」回滚教训。
#: ``pulse`` / ``ripple`` 沿用状态条既有 ``●`` 的 14px 宽，**不改布局占位**。
_SHAPE_SIZE = {
    "typing": (20, 12),
    "bars": (18, 12),
    "ripple": (14, 14),
    "pulse": (14, 14),
}


class LoopIndicator(QWidget):
    """自绘循环指示器；由 :meth:`start` / :meth:`stop` 驱动，相位经 ``motion.loop()``。"""

    def __init__(self, shape: str = "typing", *, color: str = "#FF6B9D",
                 period_ms: Optional[int] = None, parent=None):
        super().__init__(parent)
        self._shape = shape if shape in _SHAPE_SIZE else "typing"
        self._period_ms = period_ms
        self._color = QColor(color) if QColor.isValidColorName(color) else QColor("#FF6B9D")
        #: 业务意图（"是否应处于进行中"），与"当前是否可见/可动"解耦
        self._should_run = False
        self._handle = None          # motion.loop() 句柄；None ⇒ 画静态基态
        self._phase = 0.0            # ∈ [0,1)
        w, h = _SHAPE_SIZE[self._shape]
        self.setFixedSize(w, h)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def start(self) -> None:
        """进入"进行中"：置业务意图并尝试起循环（不可动则停静态基态）。"""
        self._should_run = True
        self._resume_loop()

    def stop(self) -> None:
        """状态结束：停循环。**不**强切静态（落点自己掌握去向 / 通常随即隐藏）。"""
        self._should_run = False
        self._kill_loop()

    def pause(self) -> None:
        """暂停（**隐藏**时用）：停循环但**保留业务意图**，:meth:`resume` 可复启。"""
        self._kill_loop()
        self.update()

    def resume(self) -> None:
        """复启（**显示**时用）：仅当业务意图为真且可动时才起循环。"""
        self._resume_loop()

    def set_color(self, color: str) -> None:
        """主题变更时刷新颜色（落点接 ``theme_changed``）。"""
        if color and QColor.isValidColorName(color):
            self._color = QColor(color)
        self.update()

    def is_running(self) -> bool:
        """当前是否有活动循环（测试用）。"""
        return self._handle is not None

    # ------------------------------------------------------------------
    # 循环生命周期（唯一收口：motion.loop / stop_loop）
    # ------------------------------------------------------------------
    def _resume_loop(self) -> None:
        if not self._should_run or self._handle is not None:
            return
        if not self.isVisible() or not motion.enabled():
            # 不可动（隐藏 / off 档 / 系统关动画）→ 静态基态，绝不留空白
            self.update()
            return
        handle = motion.loop(
            self, self._on_tick,
            period_ms=self._period_ms,
            on_disabled=self._on_disabled,
        )
        if handle is None:
            self.update()            # loop() 拒绝启动 → 静态基态
            return
        self._handle = handle
        self._phase = 0.0
        self.update()

    def _kill_loop(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            motion.stop_loop(handle)   # 显式停止：不触发 on_disabled

    def _on_tick(self, progress: float) -> None:
        self._phase = progress
        self.update()

    def _on_disabled(self) -> None:
        """因 ``enabled()`` 变 False 而停（含 ``stop_all``）→ 切静态基态。"""
        self._handle = None
        self.update()

    # ------------------------------------------------------------------
    # R-P：隐藏即停
    # ------------------------------------------------------------------
    def hideEvent(self, event) -> None:  # noqa: N802
        self.pause()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.resume()

    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802
        w, h = _SHAPE_SIZE[self._shape]
        return QSize(w, h)

    def paintEvent(self, event) -> None:  # noqa: N802
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            # 无活动句柄（禁停 / 隐藏 / 显式停）→ 静态基态
            phase = self._phase if self._handle is not None else None
            if self._shape == "bars":
                self._paint_bars(painter, phase)
            elif self._shape == "ripple":
                self._paint_ripple(painter, phase)
            elif self._shape == "pulse":
                self._paint_pulse(painter, phase)
            else:
                self._paint_typing(painter, phase)
            painter.end()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 形态绘制（phase 为 None 时画静态基态）
    # ------------------------------------------------------------------
    def _paint_typing(self, painter: QPainter, phase: Optional[float]) -> None:
        """3 点上下跳动；静态基态 = 平排 3 点（无位移）。"""
        w = self.width()
        h = self.height()
        d = 4.0
        gap = 3.0
        total = 3 * d + 2 * gap
        x0 = (w - total) / 2.0
        base_y = h - d - 1.0
        amp = max(0.0, h - d - 2.0) * 0.6
        for i in range(3):
            if phase is None:
                offset = 0.0
                alpha = 1.0
            else:
                wave = max(0.0, math.sin(2.0 * math.pi * (phase - i * 0.16)))
                offset = -amp * wave
                alpha = 0.55 + 0.45 * wave
            col = QColor(self._color)
            col.setAlphaF(alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(col)
            painter.drawEllipse(
                QRectF(x0 + i * (d + gap), base_y + offset, d, d)
            )

    def _paint_bars(self, painter: QPainter, phase: Optional[float]) -> None:
        """4 柱高低起伏；静态基态 = 等高短柱。**非**音量电平（R-A/R-B）。"""
        w = self.width()
        h = self.height()
        n = 4
        bw = 3.0
        gap = 2.0
        total = n * bw + (n - 1) * gap
        x0 = (w - total) / 2.0
        base_h = h * 0.35
        peak_h = h - 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        for i in range(n):
            if phase is None:
                bar_h = base_h
            else:
                wave = abs(math.sin(2.0 * math.pi * (phase + i * 0.14)))
                bar_h = base_h + (peak_h - base_h) * wave
            r = QRectF(x0 + i * (bw + gap), h - bar_h - 1.0, bw, bar_h)
            painter.drawRoundedRect(r, bw / 2.0, bw / 2.0)

    def _paint_ripple(self, painter: QPainter, phase: Optional[float]) -> None:
        """中心点 + 同心圆涟漪；静态基态 = **实心中心点**（沿用状态条既有 ● 外观）。"""
        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        dot_r = 2.6
        r_max = min(cx, cy) - 0.5
        r_min = dot_r + 0.8
        # 中心实心点（静态 / 动效都在）
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(cx - dot_r, cy - dot_r, 2 * dot_r, 2 * dot_r))
        if phase is None:
            return
        # 动效：3 圈向外扩散的涟漪
        painter.setBrush(Qt.NoBrush)
        for k in range(3):
            t = (phase + k / 3.0) % 1.0
            r = r_min + t * (r_max - r_min)
            col = QColor(self._color)
            col.setAlphaF(max(0.0, (1.0 - t)) * 0.8)
            painter.setPen(QPen(col, 1.3))
            painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

    def _paint_pulse(self, painter: QPainter, phase: Optional[float]) -> None:
        """单点透明度呼吸（保持免提现有效果）；静态基态 = 满不透明实心点。"""
        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0
        r = 3.4
        if phase is None:
            alpha = 1.0
        else:
            alpha = 0.45 + 0.55 * math.sin(math.pi * phase)   # p∈[0,1) → 一次完整呼吸
        col = QColor(self._color)
        col.setAlphaF(alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(col)
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
