# -*- coding: utf-8 -*-
"""思考指示器 —— 三个跳动圆点动画，表示 AI 正在生成回复。

（v1.4.9 回退：shimmer 大字版经用户实测否决——太大且位置突兀，恢复本版）
"""
from __future__ import annotations

from gui.qt_compat import (
    QWidget, QHBoxLayout, QLabel, QTimer, Qt,
)


class ThinkingIndicator(QWidget):
    """AI 思考动画：三个依次跳动的圆点 + 可选文字。"""

    def __init__(self, text: str = "AI 正在思考", app_context=None, parent=None):
        super().__init__(parent)
        self._text = text
        self.app_ctx = app_context
        self._dots = ["", ".", "..", "..."]
        self._idx = 0
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.setInterval(500)
        self.hide()

    def _get_accent_color(self) -> str:
        te = getattr(self.app_ctx, "theme_engine", None) if self.app_ctx else None
        if te is not None:
            return te.get_color("accent", "#FF6B9D")
        return "#FF6B9D"

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(4)

        self._label = QLabel(self._text + "...")
        accent = self._get_accent_color()
        self._label.setStyleSheet(
            f"QLabel {{ color: {accent}; font-size: 13px; font-style: italic; }}"
        )
        layout.addWidget(self._label)
        layout.addStretch()

    def _animate(self) -> None:
        self._idx = (self._idx + 1) % len(self._dots)
        self._label.setText(self._text + self._dots[self._idx])

    def start(self) -> None:
        self._idx = 0
        self._label.setText(self._text + "...")
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def set_text(self, text: str) -> None:
        self._text = text
        self._label.setText(text + self._dots[self._idx])

    def update_theme(self) -> None:
        """主题变更时刷新颜色。"""
        accent = self._get_accent_color()
        self._label.setStyleSheet(
            f"QLabel {{ color: {accent}; font-size: 13px; font-style: italic; }}"
        )
