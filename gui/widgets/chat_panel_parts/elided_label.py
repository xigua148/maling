# -*- coding: utf-8 -*-
"""窄宽度自动省略的 QLabel（自 ``gui/widgets/chat_panel.py`` 纯移动，行为不变）。

对外接口与 ``QLabel`` 完全一致（``setText`` 等调用点无需改动），
仅在窄宽度下把显示文本替换为省略号（…），``text()`` 仍返回完整原文。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import QLabel, QWidget, Qt


class _ElidedLabel(QLabel):
    """窄宽度下自动显示省略号（…）的 QLabel，替代直接截断/挤压重叠。

    对外接口与 QLabel 完全一致（setText 等调用点无需改动）。
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._full_text = text
        self.setMinimumWidth(4)

    def setText(self, text: str) -> None:
        self._full_text = text
        QLabel.setText(self, text)
        self._apply_elide()

    def text(self) -> str:
        # 对外始终返回完整原文（省略号只用于显示，不污染读取方）
        return self._full_text

    def _apply_elide(self) -> None:
        width = self.contentsRect().width()
        if width <= 0:
            return
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, width
        )
        QLabel.setText(self, elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()
