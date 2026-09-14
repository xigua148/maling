# -*- coding: utf-8 -*-
"""聊天面板 · 输入区补全（``/`` 指令补全 + 群聊 ``@`` 成员补全）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。

依赖宿主控件（ChatPanelWidget）提供的实例属性与协作者：
``input_edit`` / ``_command_registry`` / ``_cmd_popup`` / ``_mention_popup``，
以及 ``_current_group_session()`` / ``_group_member_roles()``。
浮层淡入淡出由 :class:`ChatPopupFadeMixin` 提供，故宿主须同时混入它。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.chat_input_logic import should_trigger_command_popup
from gui.chat_service import (
    apply_mention_completion as _apply_mention_completion,
    mention_candidates as _mention_candidates,
    parse_mention_partial as _parse_mention_partial,
)
from gui.qt_compat import QListWidgetItem, Qt
from gui.session_manager import is_group_session as _is_group_session

logger = logging.getLogger("maid_coder.gui.chat_panel.completion")


class ChatCompletionMixin:
    """``/`` 指令补全与群聊 ``@`` 成员补全（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 指令补全
    # ==================================================================
    def _adjust_input_height(self) -> None:
        """v1.4.6: 输入框随内容多行增高（Bug6: 上限约 6 行，超出内部滚动）。"""
        try:
            edit = self.input_edit
            # 约 6 行上限：行高取字体行距，加少量内边距余量（随主题字号自适应）
            line_h = edit.fontMetrics().lineSpacing()
            max_h = max(48, line_h * 6 + 16)
            doc_h = int(edit.document().size().height() + 14)
            edit.setFixedHeight(max(48, min(doc_h, max_h)))
            edit.setMaximumHeight(max_h)
        except Exception:
            logger.debug("静默降级：_adjust_input_height 中忽略异常", exc_info=True)

    def _on_input_text_changed(self) -> None:
        """输入变化时：/ 前缀触发指令补全列表；@ 输入态触发群成员补全（F10b）。"""
        text = self.input_edit.toPlainText()
        if should_trigger_command_popup(text):
            first_line = text.split("\n", 1)[0].strip()
            matches = self._command_registry.search(first_line)
            if matches:
                self._show_command_popup(matches)
            else:
                self._hide_command_popup()
        else:
            self._hide_command_popup()
        # v1.7(F10b): 群聊 @补全（仅群聊会话激活时评估，单聊零开销）
        self._update_mention_popup()

    def _show_command_popup(self, matches) -> None:
        self._cmd_popup.clear()
        for cmd in matches:
            item = QListWidgetItem(f"{cmd['name']}  —  {cmd['description']}")
            item.setData(Qt.UserRole, cmd)
            self._cmd_popup.addItem(item)
        if self._cmd_popup.count() > 0:
            self._cmd_popup.setCurrentRow(0)
            # 定位到输入框上方
            pos = self.input_edit.mapToGlobal(self.input_edit.rect().topLeft())
            self._cmd_popup.move(pos.x(), pos.y() - self._cmd_popup.sizeHint().height() - 4)
            self._fade_show_popup(self._cmd_popup)
        else:
            self._fade_hide_popup(self._cmd_popup)

    def _hide_command_popup(self) -> None:
        self._fade_hide_popup(self._cmd_popup)

    def _accept_command(self) -> None:
        """确认选中的指令：填入模板前缀（如 '/explain '）。"""
        item = self._cmd_popup.currentItem()
        self._hide_command_popup()
        if item is None:
            return
        cmd = item.data(Qt.UserRole)
        if not cmd:
            return
        # 替换首行指令词为完整模板前缀，保留其余输入
        text = self.input_edit.toPlainText()
        lines = text.split("\n")
        lines[0] = cmd["template"]
        self.input_edit.setPlainText("\n".join(lines))
        cursor = self.input_edit.textCursor()
        cursor.movePosition(cursor.End)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    # ==================================================================
    # v1.7(F10b): 群聊 @成员补全（@ 输入态 → 成员名浮层 → 补全插入）
    # ==================================================================
    def _update_mention_popup(self) -> None:
        """按光标前的 @片段刷新成员补全浮层（仅群聊会话；单聊零影响）。"""
        popup = getattr(self, "_mention_popup", None)
        if popup is None:
            return
        session = self._current_group_session()
        if session is None or not _is_group_session(session):
            self._fade_hide_popup(popup)
            return
        cursor = self.input_edit.textCursor()
        before = self.input_edit.toPlainText()[:cursor.position()]
        partial = _parse_mention_partial(before)
        if partial is None:
            self._fade_hide_popup(popup)
            return
        roles = self._group_member_roles(session)
        names = _mention_candidates([r.name for r in roles.values()], partial)
        if not names:
            self._fade_hide_popup(popup)
            return
        popup.clear()
        for name in names:
            item = QListWidgetItem(f"@{name}")
            item.setData(Qt.UserRole, name)
            popup.addItem(item)
        popup.setCurrentRow(0)
        popup.setFixedWidth(max(160, popup.sizeHintForColumn(0) + 24))
        rect = self.input_edit.cursorRect(cursor)
        pos = self.input_edit.mapToGlobal(rect.bottomLeft())
        popup.move(pos.x(), pos.y() + 4)
        self._fade_show_popup(popup)

    def _hide_mention_popup(self) -> None:
        popup = getattr(self, "_mention_popup", None)
        if popup is not None:
            self._fade_hide_popup(popup)

    def _accept_mention(self, name: Optional[str] = None) -> None:
        """确认补全：光标前 @片段 → @完整名字 + 空格（保留其余输入）。"""
        popup = getattr(self, "_mention_popup", None)
        item = popup.currentItem() if popup is not None else None
        if popup is not None:
            self._fade_hide_popup(popup)
        if not name:
            name = item.data(Qt.UserRole) if item is not None else None
        if not name:
            return
        cursor = self.input_edit.textCursor()
        before = self.input_edit.toPlainText()[:cursor.position()]
        after = self.input_edit.toPlainText()[cursor.position():]
        new_before = _apply_mention_completion(before, name)
        self.input_edit.blockSignals(True)
        try:
            self.input_edit.setPlainText(new_before + after)
        finally:
            self.input_edit.blockSignals(False)
        new_cursor = self.input_edit.textCursor()
        new_cursor.movePosition(new_cursor.End)
        self.input_edit.setTextCursor(new_cursor)
        self.input_edit.setFocus()
