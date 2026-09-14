# -*- coding: utf-8 -*-
"""免提状态条 —— v1.3 P2-2（design-v13 D-V13-07）

聊天面板顶部常驻的免提状态条：醒目标识 + 实时状态 + 「⏹ 停止」按钮。

- 对外只报状态、不发业务：状态/文案由 chat_panel 依据
  VoiceConversationController.state_changed / notice 驱动刷新；
  「⏹ 停止」按钮发出 stop_requested 信号，由面板回调 controller.stop()。
- 颜色全部经 theme_color() 取活动色板（深色模式可用），无裸硬编码。
- 主题切换（theme_changed）时自动重刷配色。
"""
from __future__ import annotations

import math

from typing import Optional

from gui.qt_compat import QWidget, QHBoxLayout, QLabel, QPushButton, QTimer, Signal, Qt
from gui.utils import theme_color

STATE_TEXTS = {
    "idle": "免提未开启：点下方「🎙 免提」即可开口发消息（说「暂停」或敲键盘会自动停下）",
    "listening": "🎧 免提中 · 我在听，主人直接说就好～（开始打字/动鼠标会自动暂停）",
    "recognizing": "👂 听到了，正在识别…",
    "sending": "📨 正在发送给码铃… 稍等一下下~",
    "speaking": "🔊 码铃正在把回答读给主人听…",
}


class HandsfreeBar(QWidget):
    """免提状态条：状态文案 + 常驻 ⏹ 停止（仅在免提激活期间可见）。"""

    stop_requested = Signal()

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._state: str = "idle"

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 2, 12, 2)
        self._row.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._row.addWidget(self._dot)

        # v1.6(P1-1/D-V16-11): listening 态录音呼吸动画 —— QTimer 驱动 ● 透明度
        # 正弦波动（纯 UI；无波形分析、无音频落盘，R-B）。仅 listening 启停。
        self._breath_timer: Optional[QTimer] = None
        self._breath_phase: float = 0.0

        self._status = QLabel(STATE_TEXTS["idle"])
        self._status.setObjectName("handsfreeStatus")
        self._status.setWordWrap(True)
        self._row.addWidget(self._status, 1)

        self._stop_btn = QPushButton("⏹ 停止免提")
        self._stop_btn.setObjectName("handsfreeStopBtn")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setFixedHeight(24)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._row.addWidget(self._stop_btn)

        # 主题切换自刷配色
        engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
        if engine is not None and hasattr(engine, "theme_changed"):
            try:
                engine.theme_changed.connect(lambda _name: self._apply_theme())
            except Exception:
                pass

        self._apply_theme()
        self.set_state("idle")

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        self._state = state if state in STATE_TEXTS else "idle"
        self._status.setText(STATE_TEXTS.get(self._state, STATE_TEXTS["idle"]))
        active = self._state != "idle"
        self._stop_btn.setVisible(active)
        self._apply_theme()
        self._set_breathing(self._state == "listening")

    # ------------------------------------------------------------------
    # v1.6(P1-1/D-V16-11): 录音呼吸动画（仅 listening 态启停，防常驻耗电）
    # ------------------------------------------------------------------
    def _set_breathing(self, on: bool) -> None:
        try:
            if on:
                if self._breath_timer is None:
                    self._breath_timer = QTimer(self)
                    self._breath_timer.setInterval(120)
                    self._breath_timer.timeout.connect(self._on_breath_tick)
                    self._breath_phase = 0.0
                if not self._breath_timer.isActive():
                    self._breath_timer.start()
            else:
                if self._breath_timer is not None and self._breath_timer.isActive():
                    self._breath_timer.stop()
                self._dot.setStyleSheet(
                    f"color: {theme_color(self.app_ctx, 'accent', '#FF6B9D')};"
                    f" font-size: 10px;"
                )
        except Exception:
            pass

    def _on_breath_tick(self) -> None:
        try:
            self._breath_phase += 0.28
            alpha = 0.45 + 0.55 * abs(math.sin(self._breath_phase))
            hex_color = theme_color(self.app_ctx, "accent", "#FF6B9B").lstrip("#")
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            self._dot.setStyleSheet(
                f"color: rgba({r}, {g}, {b}, {alpha:.2f}); font-size: 10px;"
            )
        except Exception:
            pass

    def set_notice(self, text: str) -> None:
        """一次性说明（识别失败/自动暂停等），2.4s 后回落为状态文案。"""
        if text:
            self._status.setText(text)
        try:
            from gui.qt_compat import QTimer
            QTimer.singleShot(2400, self._restore_from_notice)
        except Exception:
            pass

    def _restore_from_notice(self) -> None:
        try:
            if not self.isVisible():
                return
            self._status.setText(STATE_TEXTS.get(self._state, STATE_TEXTS["idle"]))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _on_stop_clicked(self) -> None:
        self.stop_requested.emit()

    def _apply_theme(self) -> None:
        try:
            idle_dot = theme_color(self.app_ctx, "disabled_text", "#9E9E9E")
            active_dot = theme_color(self.app_ctx, "accent", "#FF6B9D")
            text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
            text_on_accent = theme_color(self.app_ctx, "text_on_accent", "#FFFFFF")
            primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
            border = theme_color(self.app_ctx, "border", "#FFE4E1")
            dot = active_dot if self._state != "idle" else idle_dot
            bg = theme_color(self.app_ctx, "surface_muted", "#FFF9FA")
            self.setStyleSheet(
                f"HandsfreeBar {{ background: {bg}; border: 1px solid {border};"
                f" border-radius: 10px; }}"
            )
            self._dot.setStyleSheet(f"color: {dot}; font-size: 10px;")
            self._status.setStyleSheet(
                f"color: {text}; font-size: 11px; background: transparent;"
            )
            self._stop_btn.setStyleSheet(
                f"QPushButton#handsfreeStopBtn {{"
                f"  background: {primary}; color: {text_on_accent};"
                f"  border: none; border-radius: 10px; padding: 2px 12px; font-size: 11px;"
                f"}}"
                f"QPushButton#handsfreeStopBtn:hover {{"
                f"  background: {active_dot}; }}"
            )
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_theme()
