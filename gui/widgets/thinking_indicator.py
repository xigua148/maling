# -*- coding: utf-8 -*-
"""思考指示器 —— 静态文案 + **文字省略号节奏**（纯文字，无任何自绘图形）。

（v1.4.9 回退：shimmer 大字版经用户实测否决——太大且位置突兀，恢复本版）

v2.x 落点①（阶段 B「融入度」复核后**回退**）：
  曾把"文字省略号循环"升级为"小号三点头"（``LoopIndicator("typing")``）。
  阶段 B 复核判定 —— **几何三点属通用 IM 外来母题**，且与文本省略号
  **语义重复**（整行读作「••• AI 正在思考…」）→ **回退为纯文字省略号节奏**
  （即本文件的原生语言，见 ``_phaseB_report.md §2①``）。

回退后形态（沿用 v1.4.9 原版文字节奏）：
  · 主文案 ``QLabel("AI 正在思考")`` + **独立省略号 QLabel**，文本在
    ``"" → "." → ".." → "..."`` 间循环；
  · **无任何自绘图形**（不再引入几何母题）；
  · 省略号 QLabel **固定宽度** → 文本长短变化**不引起版式抖动**
    （实测见 ``_phaseB_revert_report.md``）。

动效**统一经** :func:`gui.motion.loop` 收口（**不自带** ``QTimer``，R-P/R-Q 纪律）。
R-P：**隐藏即停** —— ``hideEvent`` → 停循环（保留 ``_active`` 业务意图），
``showEvent`` 仅在 ``_active`` 时复启。
R-Q：``off`` 档 / 系统关动画 → 省略号定格为**静态 ``…``**，静态文案照常显示，
**绝不空白、绝不残留几何图形**。

两条硬约束（当年翻车点）：**绝不放大**（仍内联于原文本行，20×12 量级）、
**绝不改位置**（沿用 ``chat_panel.py`` / ``chat_window.py`` 既有槽位与
``start()``/``stop()`` 契约，不新增浮层、不移版位）。
"""
from __future__ import annotations

from gui.qt_compat import QWidget, QHBoxLayout, QLabel, Qt
from gui import motion

#: 省略号 QLabel 的固定宽度（px）——与旧自绘三点头的 20px 占位一致，**防版式抖动**。
_DOTS_WIDTH = 20
#: 省略号节奏：一个循环 4 拍（``"" → "." → ".." → "..."``），与 v1.4.9 原版一致。
_DOTS_STEPS = ("", ".", "..", "...")
#: 循环周期（ms）；``motion.loop()`` 会夹取到 ``[800, 1600]`` → 4 拍 ≈ 400ms/拍
#: （贴近原实现的 500ms/拍，且不超循环周期上限）。
_PERIOD_MS = 1600


class ThinkingIndicator(QWidget):
    """AI 思考动画：静态「AI 正在思考」+ 文字省略号节奏。"""

    def __init__(self, text: str = "AI 正在思考", app_context=None, parent=None):
        super().__init__(parent)
        self._text = text
        self.app_ctx = app_context
        # R-P：业务上"是否应显示思考态"的标志（与"当前是否可见"解耦）。
        # 仅 _active 为真时，showEvent 才复启循环；hideEvent 一律停循环。
        self._active = False
        #: 循环句柄；None ⇒ 画静态省略号
        self._handle = None
        self._init_ui()
        self.hide()

    def _get_accent_color(self) -> str:
        te = getattr(self.app_ctx, "theme_engine", None) if self.app_ctx else None
        if te is not None:
            return te.get_color("accent", "#FF6B9D")
        return "#FF6B9D"

    def _style(self, accent: str) -> str:
        return f"QLabel {{ color: {accent}; font-size: 13px; font-style: italic; }}"

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)   # 与原实现一致（不改位置/留白）
        layout.setSpacing(4)

        accent = self._get_accent_color()
        style = self._style(accent)

        # 顺序 = 文案在前、省略号在后（v1.4.9 原版「AI 正在思考...」语序）。
        self._label = QLabel(self._text)
        self._label.setStyleSheet(style)
        layout.addWidget(self._label)

        # 省略号：**纯文字**（非自绘图形）；固定宽度 → 文本长短不抖动版式。
        self._dots = QLabel("…")
        self._dots.setStyleSheet(style)
        self._dots.setFixedWidth(_DOTS_WIDTH)
        self._dots.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self._dots)

        layout.addStretch()

    def start(self) -> None:
        # v2.1(UI)：每次开始思考都把文案刷新为**当前角色名**。
        #   文案若在构造时固定，切换角色后仍会显示旧名字；这里刷新即无需重建指示器。
        self._refresh_speaker_text()
        self._active = True
        self.show()
        self._resume_loop()

    def _refresh_speaker_text(self) -> None:
        """主文案刷新为「<当前角色名> 正在思考」；取不到名字时保留构造时的文案。"""
        try:
            from gui.widgets.message_bubble import resolve_default_speaker_name
            _name = resolve_default_speaker_name()
        except Exception:
            _name = ""
        if not _name:
            return
        _new = f"{_name} 正在思考"
        if _new == self._text:
            return
        self._text = _new
        _label = getattr(self, "_label", None)
        if _label is not None:
            _label.setText(_new)

    def stop(self) -> None:
        self._active = False
        self._kill_loop()
        self.hide()

    # ------------------------------------------------------------------
    # 循环生命周期（唯一收口：motion.loop / stop_loop）
    # ------------------------------------------------------------------
    def _resume_loop(self) -> None:
        if not self._active or self._handle is not None:
            return
        if not self.isVisible() or not motion.enabled():
            self._set_static()          # 不可动（隐藏 / off / 系统关动画）→ 静态省略号
            return
        handle = motion.loop(
            self, self._on_tick, period_ms=_PERIOD_MS, on_disabled=self._on_disabled,
        )
        if handle is None:
            self._set_static()          # loop() 拒绝启动 → 静态省略号
            return
        self._handle = handle
        self._on_tick(0.0)

    def _kill_loop(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            motion.stop_loop(handle)    # 显式停止：不触发 on_disabled

    def _on_tick(self, progress: float) -> None:
        idx = int(progress * len(_DOTS_STEPS))
        if idx >= len(_DOTS_STEPS):
            idx = len(_DOTS_STEPS) - 1
        self._dots.setText(_DOTS_STEPS[idx])

    def _on_disabled(self) -> None:
        """因 ``enabled()`` 变 False 而停（含 ``stop_all``）→ 切静态省略号。"""
        self._handle = None
        self._set_static()

    def _set_static(self) -> None:
        """静态终态：单个省略号字符（纯文字，非空白、无几何图形）。"""
        self._dots.setText("…")

    # ------------------------------------------------------------------
    # R-P：隐藏即停（停循环但保留业务意图，显示时按 _active 复启）
    # ------------------------------------------------------------------
    def hideEvent(self, event) -> None:  # noqa: N802
        self._kill_loop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._active:
            self._resume_loop()

    def set_text(self, text: str) -> None:
        self._text = text
        self._label.setText(text)

    def update_theme(self) -> None:
        """主题变更时刷新颜色（文案 + 省略号）。"""
        accent = self._get_accent_color()
        style = self._style(accent)
        self._label.setStyleSheet(style)
        self._dots.setStyleSheet(style)
