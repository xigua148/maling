# -*- coding: utf-8 -*-
"""会话管理（列表刷新 / 切换 / 新建 / 重命名 / 清空 / 删除 / 群设置入口）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from gui import icons
from gui.chat_service import GROUP_DEFAULT_NO_AT_POLICY
from gui.models import ChatSession
from gui.qt_compat import QCheckBox
from gui.qt_compat import QDialog
from gui.qt_compat import QHBoxLayout
from gui.qt_compat import QInputDialog
from gui.qt_compat import QLabel
from gui.qt_compat import QListWidgetItem
from gui.qt_compat import QMenu
from gui.qt_compat import QMessageBox
from gui.qt_compat import QPushButton
from gui.qt_compat import QVBoxLayout
from gui.qt_compat import Qt
from gui.session_manager import is_group_session as _is_group_session
from gui.widgets.thinking_indicator import ThinkingIndicator
from typing import List
from typing import Optional

logger = logging.getLogger("maid_coder.gui.chat_panel.sessions")


class ChatSessionsMixin:
    """会话管理（列表刷新 / 切换 / 新建 / 重命名 / 清空 / 删除 / 群设置入口）（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 会话管理
    # ==================================================================
    def _publish_activity(self, state: Optional[str]) -> None:
        """v1.2(A-9/A-10): 活动态广播到 companion_bridge（thinking/focus/surprised/None）。

        设计（design-v12 D2 §3.2 广播约定）：聊天面板作为活动态呈现触发源，经
        bridge.note_activity 广播同一条 mood_changed —— 角落宠物 / 气泡头像 /
        首页形象 / 侧栏同步更新；无 bridge 或方法缺失时静默空转（不崩）。
        """
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None:
            return
        note = getattr(bridge, "note_activity", None)
        if not callable(note):
            return
        try:
            note(state)
        except Exception:
            logger.debug("静默降级：_publish_activity 中忽略异常", exc_info=True)

    def _load_active_session(self) -> None:
        """加载活跃会话并显示其消息。"""
        if self.session_manager is None:
            return
        session = self.session_manager.ensure_active()
        self._current_session_id = session.id
        self._refresh_session_list()
        self._load_session_messages(session)
        # v1.5.1(切角色人设残留): 启动加载也让 LLM 历史对齐显示会话
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        self._apply_group_placeholder(session)

    def _refresh_session_list(self) -> None:
        """刷新会话列表显示。"""
        if self.session_manager is None:
            return
        self.session_list.clear()
        for session in self.session_manager.all_sessions():
            # v1.7(F10a): 群聊会话带 👥 群标签（旧单聊会话零影响）
            prefix = (icons.text_glyph('people', '👥') + " ") if _is_group_session(session) else ""
            item = QListWidgetItem(f"{prefix}{session.name} ({session.message_count})")
            item.setData(Qt.UserRole, session.id)
            self.session_list.addItem(item)
            if session.id == self._current_session_id:
                self.session_list.setCurrentItem(item)
        if self._tab_mode:
            self._sync_tabs()

    def _load_session_messages(self, session: ChatSession) -> None:
        """将会话消息加载到消息列表。"""
        # v2.1(M-2/D-V21-02): 置「历史重载中」标志 —— 期间新增气泡一律不放入场动画
        #（切会话 / 重载历史 / 恢复会话绝不逐条重播，避免滚动时满屏闪动）。
        # finally 复位，保证异常也不残留标志。
        self._loading_history = True
        try:
            # v1.1(B2): 切换会话时清掉旧会话残留的工具轨迹
            try:
                self.tool_trace_panel.reset()
                self._agent_trace_active = False
            except Exception:
                logger.debug("静默降级：_load_session_messages 中忽略异常", exc_info=True)
            # v1.6(P0-4): 切换会话时清掉旧会话残留的失败动作行引用
            self._clear_failure_actions()
            # 清空现有消息气泡（保留 stretch 和 thinking_indicator）
            for i in range(self.messages_layout.count() - 2, -1, -1):
                item = self.messages_layout.itemAt(i)
                if item is not None:
                    widget = item.widget()
                    if widget is not None and not isinstance(widget, ThinkingIndicator):
                        self.messages_layout.removeWidget(widget)
                        widget.deleteLater()

            self._last_role = None
            self._last_speaker_id = None
            for msg in session.messages:
                if msg.role in ("user", "assistant"):
                    atts = (msg.metadata or {}).get("attachments") if msg.metadata else None
                    # v1.7(F10a): 群聊 assistant 消息带发言者（气泡名字+头像渲染）
                    speaker_id = (msg.metadata or {}).get("speaker_id") if msg.metadata else None
                    # animate 缺省 = 非历史重载 → 此处经 _loading_history 判定为 False
                    self._add_message_bubble(msg.role, msg.content, attachments=atts,
                                             speaker_id=speaker_id)
            self._scroll_to_bottom()
        finally:
            self._loading_history = False

    def _on_session_selected(self, item: QListWidgetItem) -> None:
        """切换会话。"""
        session_id = item.data(Qt.UserRole)
        self._switch_to_session(session_id)

    def _switch_to_session(self, session_id: str) -> None:
        """切换活跃会话（同时供会话列表点击和标签页切换调用）。"""
        if not session_id or session_id == self._current_session_id:
            return
        if self.session_manager is None:
            return
        self.session_manager.set_active(session_id)
        session = self.session_manager.get_session(session_id)
        if session is not None:
            self._current_session_id = session_id
            self.title_label.setText(session.name)
            self._load_session_messages(session)
            # v1.5.1(切角色人设残留): LLM 历史跟随显示会话（旧会话的对话不再泄漏）
            self._sync_llm_context(session)
            self._apply_group_placeholder(session)
            if self._tab_mode and session_id not in self._open_tab_ids:
                self._open_tab_ids.append(session_id)
                self._sync_tabs()

    def _on_new_session(self) -> None:
        """新建会话（通过侧栏 + 按钮触发，默认名「新会话」，不弹对话框）。"""
        if self.session_manager is None:
            return
        name = "新会话"
        session = self.session_manager.create_session(name)
        self._current_session_id = session.id
        self._refresh_session_list()
        self._clear_messages()
        # v1.5.1(切角色人设残留): 新会话 = 干净的 LLM 历史（空 entries → 仅当前
        # 角色 system）。此前 LLM 历史跨显示会话持续累积，旧角色对话泄漏进新会话。
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        if self._tab_mode and session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
            self._sync_tabs()

    def _sync_llm_context(self, session) -> None:
        """v1.5.1(切角色人设残留): 让 LLM 会话历史跟随活跃显示会话。

        根因：显示会话（session_manager）与 LLM 会话（app_ctx.session）是两套
        历史 —— LLM history 自启动起持续累积、跨显示会话/角色切换从不清空，
        旧角色（如鲸鱼娘）的对话持续带偏模型，且"新会话"也携带旧上下文。
        本方法以显示会话的 user/assistant 消息重建 LLM 历史（首条 = 当前角色
        system，人设来源唯一）。重建走 session.replace_history（直赋值，
        不触发 GuiChatSession.message_added，气泡不会被重放）。

        v1.7(F10a/D-V17-06): 群聊会话隔离分支 —— 群聊消息**绝不写入** LLM
        对齐历史（R-J④⑤ / 共享知识 26），仅清空 LLM 历史防跨会话泄漏；
        单聊路径零改动。
        """
        if session is None:
            return
        llm_session = getattr(self.app_ctx, "session", None)
        if llm_session is None or not callable(getattr(llm_session, "replace_history", None)):
            return
        if _is_group_session(session):
            try:
                llm_session.replace_history([])
            except Exception as exc:
                logger.debug("群聊会话 LLM 历史清空失败（不影响会话切换）: %s", exc)
            return
        entries: List[dict] = []
        for msg in session.messages:
            if msg.role not in ("user", "assistant"):
                continue
            content = msg.content or ""
            # 附件按发送时的摘要规则回填（与 _collect_ui_history_before 一致）
            atts = (msg.metadata or {}).get("attachments") if msg.metadata else None
            if msg.role == "user" and atts:
                att_lines = "\n".join(
                    f"[附件] {a.get('name', '')} ({a.get('size', 0)} bytes)"
                    for a in atts
                )
                content = (content + "\n" if content else "") + att_lines
            entries.append({"role": msg.role, "content": content})
        try:
            llm_session.replace_history(entries)
        except Exception as exc:
            logger.debug("LLM 历史对齐失败（不影响会话切换）: %s", exc)

    def _show_session_menu(self, pos) -> None:
        """会话右键菜单（空白处 = 新建群聊入口）。"""
        item = self.session_list.itemAt(pos)
        if item is None:
            # v1.7(F10a): 空白处右键 → 最小建群入口（选 2-3 个已建角色）
            menu = QMenu(self)
            new_group_action = menu.addAction(f"{icons.text_glyph('people', '👥')} 新建群聊")
            action = menu.exec_(self.session_list.mapToGlobal(pos))
            if action == new_group_action:
                self._on_new_group_session()
            return
        session_id = item.data(Qt.UserRole)
        session = self.session_manager.get_session(session_id) if self.session_manager else None
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        # v1.7(F10b): 群聊会话专属「群聊设置」（成员查看/改名/解散）
        group_settings_action = menu.addAction(f"{icons.text_glyph('people', '👥')} 群聊设置") \
            if session is not None and _is_group_session(session) else None
        clear_action = menu.addAction("清空消息")
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.session_list.mapToGlobal(pos))

        if action == rename_action:
            self._rename_session(session_id)
        elif group_settings_action is not None and action == group_settings_action:
            self._on_group_settings(session_id)
        elif action == clear_action:
            self._clear_session(session_id)
        elif action == delete_action:
            self._delete_session(session_id)

    def _on_group_settings(self, session_id: str) -> None:
        """v1.7(F10b): 群聊设置（最小集）—— 查看成员 / 改名 / 解散确认。

        R-J③：成员只读展示（人员增减留 v1.7.x，避免运行中改群composition
        与历史改写语义冲突）；解散 = 删除会话（复用既有删除链，含文件清理）。
        """
        if self.session_manager is None:
            return
        session = self.session_manager.get_session(session_id)
        if session is None or not _is_group_session(session):
            return
        roles = self._group_member_roles(session)
        member_names = [getattr(roles.get(rid), "name", "（已删除角色）")
                        for rid in (session.metadata or {}).get("members", [])]
        box = QMessageBox(self)
        box.setWindowTitle("群聊设置")
        box.setText(f"群聊：{session.name}\n成员（{len(member_names)}/3）：\n  · "
                    + "\n  · ".join(member_names))
        rename_btn = box.addButton(f"{icons.text_glyph('rename', '✏️')} 改名", QMessageBox.ActionRole)
        disband_btn = box.addButton("💥 解散群聊", QMessageBox.DestructiveRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        self._exec_modal_fade(box)
        clicked = box.clickedButton()
        if clicked is rename_btn:
            self._rename_session(session_id)
        elif clicked is disband_btn:
            confirm = QMessageBox.question(
                self, "解散群聊",
                f"确定要解散「{session.name}」吗？\n群聊记录将一并删除，此操作不可恢复。",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self._delete_session(session_id)

    def _on_new_group_session(self) -> None:
        """v1.7(F10a): 新建群聊 —— 选 2-3 个已建角色的最小选择框（R-J③ 成员 ≤3）。"""
        if self.session_manager is None:
            return
        try:
            from gui.pages.page_role import RoleManager
            roles = list(RoleManager().all_roles())
        except Exception as exc:
            logger.warning("角色列表读取失败: %s", exc)
            roles = []
        if len(roles) < 2:
            QMessageBox.information(self, "新建群聊", "至少需要 2 个已创建的角色才能建群哦~")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("新建群聊（选择 2-3 个成员）")
        dialog.setMinimumWidth(280)
        lay = QVBoxLayout(dialog)
        lay.addWidget(QLabel("选择群聊成员（最多 3 个）："))
        checks: List[QCheckBox] = []
        for role in roles:
            cb = QCheckBox(role.name or role.id)
            cb.setParent(dialog)
            lay.addWidget(cb)
            checks.append(cb)
        hint = QLabel("")
        hint.setStyleSheet("QLabel { color: #FF6B9D; font-size: 11px; }")
        lay.addWidget(hint)

        def _validate() -> None:
            n = sum(1 for c in checks if c.isChecked())
            ok_btn.setEnabled(2 <= n <= 3)
            hint.setText("" if n <= 3 else "最多选择 3 个成员")
            if n < 2:
                hint.setText("至少选择 2 个成员")

        ok_btn = QPushButton("创建群聊")
        ok_btn.setEnabled(False)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        for cb in checks:
            cb.toggled.connect(_validate)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        lay.addLayout(btns)

        if self._exec_modal_fade(dialog) != QDialog.Accepted:
            return
        member_ids = [r.id for r, c in zip(roles, checks) if c.isChecked()][:3]
        if len(member_ids) < 2:
            return
        # v1.7(F10b): 无@策略全局默认读 GuiConfig（会话级 metadata 可覆盖）
        gui_cfg = getattr(self.app_ctx, "config", None)
        policy = str(getattr(gui_cfg, "group_no_at_policy", GROUP_DEFAULT_NO_AT_POLICY)
                     or GROUP_DEFAULT_NO_AT_POLICY)
        session = self.session_manager.create_group_session(
            "群聊", member_ids, no_at_policy=policy
        )
        self._current_session_id = session.id
        self._refresh_session_list()
        self._load_session_messages(session)
        # v1.7(F10a): 群聊隔离 —— LLM 对齐历史保持干净（不写群聊消息）
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        self._apply_group_placeholder(session)
        if self._tab_mode and session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
            self._sync_tabs()

    def _rename_session(self, session_id: str) -> None:
        session = self.session_manager.get_session(session_id) if self.session_manager else None
        if session is None:
            return
        name, ok = QInputDialog.getText(self, "重命名会话", "新名称:", text=session.name)
        if ok and name.strip():
            self.session_manager.rename_session(session_id, name.strip())
            self._refresh_session_list()
            if session_id == self._current_session_id:
                self.title_label.setText(name.strip())
            if self._tab_mode:
                self._sync_tabs()

    def _clear_session(self, session_id: str) -> None:
        if self.session_manager is None:
            return
        reply = QMessageBox.question(
            self, "清空消息", "确定要清空该会话的所有消息吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.session_manager.clear_session(session_id)
            if session_id == self._current_session_id:
                self._clear_messages()
            self._refresh_session_list()

    def _delete_session(self, session_id: str) -> None:
        if self.session_manager is None:
            return
        reply = QMessageBox.question(
            self, "删除会话", "确定要删除该会话吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # 先从标签页打开列表中移除（删除是删除，关闭 tab 是另一回事）
            if session_id in self._open_tab_ids:
                self._open_tab_ids.remove(session_id)
            self.session_manager.delete_session(session_id)
            if session_id == self._current_session_id:
                self._clear_messages()
                active = self.session_manager.active_session
                if active is not None:
                    self._current_session_id = active.id
                    self.title_label.setText(active.name)
                    self._load_session_messages(active)
                    if self._tab_mode and active.id not in self._open_tab_ids:
                        self._open_tab_ids.append(active.id)
                else:
                    self._current_session_id = None
                    self.title_label.setText("聊天")
            self._refresh_session_list()
            if self._tab_mode:
                self._sync_tabs()

    def _clear_messages(self) -> None:
        """清空消息列表。"""
        # v1.1(B2): 清空消息时同步清掉工具轨迹
        try:
            self.tool_trace_panel.reset()
            self._agent_trace_active = False
        except Exception:
            logger.debug("静默降级：_clear_messages 中忽略异常", exc_info=True)
        # v1.6(P0-4): 清空消息时同步清掉失败动作行引用（widget 将被 deleteLater）
        self._clear_failure_actions()
        for i in range(self.messages_layout.count() - 2, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None and not isinstance(widget, ThinkingIndicator):
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()
        self._last_role = None
        self._last_speaker_id = None

    def _on_toggle_sidebar(self) -> None:
        """折叠/展开会话列表。"""
        visible = self.session_sidebar.isVisible()
        self.session_sidebar.setVisible(not visible)
        self.toggle_sidebar_btn.setText("◀" if not visible else "▶")

