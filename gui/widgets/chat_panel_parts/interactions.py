# -*- coding: utf-8 -*-
"""其他交互与开关（展开/风格切换/附件/剪贴板/搜索/导出/表情/快捷回复/模式开关/反馈三键/主题联动）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from datetime import datetime
from gui.chat_bubble_utils import collect_messages_from_layout
from gui.chat_exporter import ChatExporter
from gui.chat_helpers import build_matcher as _pure_build_matcher
from gui.chat_helpers import clear_highlight_style as _clear_highlight_style
from gui.chat_helpers import detect_export_format
from gui.chat_helpers import format_search_result
from gui.chat_helpers import highlight_style as _highlight_style
from gui.chat_input_logic import format_agent_event_status
from gui.chat_input_logic import format_tool_label
from gui.qt_compat import QApplication
from gui.qt_compat import QDialog
from gui.qt_compat import QFileDialog
from gui.qt_compat import QLabel
from gui.qt_compat import QListWidget
from gui.qt_compat import QMenu
from gui.qt_compat import QMessageBox
from gui.qt_compat import QPushButton
from gui.qt_compat import QVBoxLayout
from gui.widgets.chat_window import ChatWindow
from gui.widgets.message_bubble import MessageBubble
from gui.widgets.thinking_indicator import ThinkingIndicator
import os

logger = logging.getLogger("maid_coder.gui.chat_panel.interactions")


class ChatInteractionsMixin:
    """其他交互与开关（展开/风格切换/附件/剪贴板/搜索/导出/表情/快捷回复/模式开关/反馈三键/主题联动）（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 其他交互
    # ==================================================================
    def _on_expand_chat(self) -> None:
        if self._chat_window is None:
            self._chat_window = ChatWindow(self.app_ctx, self)
            self._chat_window.attach_requested.connect(self._on_chat_attached)
            # R6: 独立窗口发送的消息由面板统一渲染并持久化（含附件 metadata），
            # 使面板 / 窗口两条发送路径落同一份会话数据
            self._chat_window.user_message_sent.connect(self._on_window_user_message)
        self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()

    # ------------------------------------------------------------------
    # v1.9 A(D-V19-13②)：界面风格快捷入口（顶栏 🎨 → 四风格小菜单）
    # ------------------------------------------------------------------
    def _on_style_menu(self) -> None:
        try:
            from gui.theme_engine import ThemeEngine
        except Exception:
            return
        cur = ThemeEngine.normalize_theme_id(
            getattr(getattr(self.app_ctx, "config", None), "theme_name", "") or "")
        menu = QMenu(self)
        actions = []
        for tid in ThemeEngine.THEME_IDS:
            act = menu.addAction(ThemeEngine.THEME_DEFINITIONS[tid]["name"])
            act.setCheckable(True)
            act.setChecked(tid == cur)
            actions.append((act, tid))
        chosen = menu.exec_(self.style_btn.mapToGlobal(self.style_btn.rect().bottomLeft()))
        for act, tid in actions:
            if chosen is act:
                self._apply_style_choice(tid)
                break

    def _apply_style_choice(self, theme_id: str) -> None:
        """顶栏切换风格：与设置页同一条收口（归一 + C 深色夜间进出 + 即时生效 + 持久化）。"""
        try:
            from gui.theme_engine import ThemeEngine, apply_night_lock
        except Exception:
            return
        theme_id = ThemeEngine.normalize_theme_id(theme_id)
        engine = getattr(self.app_ctx, "theme_engine", None)
        config = getattr(self.app_ctx, "config", None)
        apply_night_lock(engine, config, theme_id)
        if engine is not None:
            try:
                engine.load_theme(theme_id)
            except Exception:
                logger.debug("静默降级：_apply_style_choice 中忽略异常", exc_info=True)
        if config is not None:
            config.theme_name = theme_id
            try:
                config.save()
            except Exception:
                logger.debug("静默降级：_apply_style_choice 中忽略异常", exc_info=True)

    def _on_chat_attached(self) -> None:
        """独立窗口请求合并回主面板。"""
        self._chat_window = None
    def _on_window_user_message(self, display_text: str, attachments: list) -> None:
        """R6: 独立窗口发送路径的持久化入口——面板侧渲染并保存同一份会话数据。"""
        self._add_message_bubble("user", display_text, attachments=attachments or None)
        self._save_current_session()

    def _on_attach_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择附件", "",
            "所有文件 (*);;文本文件 (*.txt);;代码文件 (*.py *.js *.ts *.java *.cpp *.c *.h *.go *.rs *.md)"
        )
        if not path:
            return
        # R5: 与拖拽同一条校验链（存在性 / 10MB 上限 / 重复），不再以纯文本插入输入框
        ok, info = self.attachment_bar.add_file_path(path)
        if ok is True:
            self.status_label.setText(f"已添加附件: {info}")
            return
        name = os.path.basename(path)
        if info == "too_large":
            QMessageBox.warning(self, "附件过大", f"{name} 超过 10MB 上限，未添加。")
        elif info == "missing":
            QMessageBox.warning(self, "附件不存在", f"{name} 不存在或不可访问，未添加。")
        elif info == "duplicate":
            QMessageBox.information(self, "附件已存在", f"{name} 已在附件列表中。")

    def _on_paste_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text()
        if text:
            current = self.input_edit.toPlainText()
            prefix = "\n" if current else ""
            self.input_edit.setPlainText(f"{current}{prefix}{text}")
        else:
            QMessageBox.information(self, "粘贴", "剪贴板中没有文本内容")

    def _on_search_filter(self, text: str) -> None:
        query = text.strip()
        scope = self.scope_combo.currentData() if hasattr(self, "scope_combo") else "current"

        # --- 全部会话范围：跨会话搜索，结果弹窗展示 ---
        if scope == "all" and query:
            self._search_all_sessions(query)
            return

        # --- 当前会话范围 ---
        matcher = self._build_matcher(query)
        if matcher is None:
            # 正则语法错误或空查询：恢复全部可见
            for i in range(self.messages_layout.count() - 1):
                item = self.messages_layout.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                if isinstance(widget, MessageBubble):
                    widget.setVisible(True)
            return

        first_hit = None
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                hit = matcher(widget.get_text())
                widget.setVisible(hit)
                if hit and first_hit is None:
                    first_hit = widget
        # 命中第一条：高亮并滚动定位
        if first_hit is not None:
            self._highlight_bubble(first_hit)
            self.scroll_area.ensureWidgetVisible(first_hit)
        else:
            self._highlight_bubble(None)

    def _build_matcher(self, query: str):
        """根据查询构造匹配函数；正则语法错误时返回 None。"""
        use_regex = hasattr(self, "regex_check") and self.regex_check.isChecked()
        matcher = _pure_build_matcher(query, use_regex=use_regex)
        if query and matcher is None:
            self.status_label.setText("正则语法错误")
        elif query and matcher is not None:
            self.status_label.setText("")
        return matcher

    def _highlight_bubble(self, bubble) -> None:
        """高亮命中的消息气泡（金色边框），清除上一个。"""
        if self._highlighted_bubble is not None:
            try:
                self._highlighted_bubble.setStyleSheet(_clear_highlight_style())
            except RuntimeError:
                logger.debug("静默降级：_highlight_bubble 中忽略异常", exc_info=True)
            self._highlighted_bubble = None
        if bubble is not None:
            bubble.setStyleSheet(_highlight_style())
            self._highlighted_bubble = bubble

    def _search_all_sessions(self, query: str) -> None:
        """跨全部会话搜索，结果以对话框展示。"""
        if self.session_manager is None:
            return
        use_regex = hasattr(self, "regex_check") and self.regex_check.isChecked()
        matcher = _pure_build_matcher(query, use_regex=use_regex)
        if matcher is None and query:
            self.status_label.setText("正则语法错误")
            return

        results = []
        for session in self.session_manager.all_sessions():
            for msg in session.messages:
                if msg.role in ("user", "assistant") and matcher(msg.content):
                    results.append(format_search_result(session.name, msg.role, msg.content))

        dialog = QDialog(self)
        dialog.setWindowTitle(f"搜索结果（{len(results)} 条）")
        dialog.resize(520, 360)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(12, 12, 12, 12)
        result_list = QListWidget(dialog)
        for line in results:
            result_list.addItem(line)
        if not results:
            result_list.addItem("（无匹配结果）")
        dlg_layout.addWidget(result_list)
        close_btn = QPushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        dlg_layout.addWidget(close_btn)
        self._exec_modal_fade(dialog)

    # ==================================================================
    # 聊天记录导出
    # ==================================================================
    def _collect_messages(self) -> list:
        """从当前消息气泡收集 (role, content, timestamp) 列表。"""
        return collect_messages_from_layout(self.messages_layout, MessageBubble)

    def _on_export_chat(self) -> None:
        """导出当前会话聊天记录（Markdown / TXT / JSON）。"""
        messages = self._collect_messages()
        if not messages:
            QMessageBox.information(self, "导出", "当前没有消息可导出")
            return

        session_name = "聊天记录"
        if self.session_manager is not None and self._current_session_id:
            session = self.session_manager.get_session(self._current_session_id)
            if session is not None:
                session_name = session.name

        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出聊天记录", "chat_export.md",
            "Markdown (*.md);;文本文件 (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        fmt = detect_export_format(selected_filter)

        if ChatExporter.export(messages, fmt, path, session_name):
            QMessageBox.information(self, "导出成功", f"聊天记录已导出到:\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", "导出聊天记录失败，请检查文件路径")

    def _on_search_messages(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _on_toggle_emoji_panel(self) -> None:
        self.emoji_panel.setVisible(not self.emoji_panel.isVisible())

    def _on_emoji_clicked(self, emoji: str) -> None:
        cursor = self.input_edit.textCursor()
        cursor.insertText(emoji)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    def _on_quick_reply(self, text: str) -> None:
        self.input_edit.setPlainText(text)
        self._on_send()

    def _on_stop_generation(self) -> None:
        if self.chat_service is not None:
            self.chat_service.stop_generation()

    # ----- v1.1(agent): Agent 模式开关与工具轨迹提示 -----
    def _on_toggle_agent_mode(self, checked: bool) -> None:
        if self.chat_service is not None:
            self.chat_service.set_agent_mode(checked)
        self.input_edit.setPlaceholderText(
            "Agent 模式：女仆会自主调用工具完成任务（读文件/Git/写文件/跑代码/联网搜索）..."
            if checked else "和女仆说点什么吧... （或拖拽文件）"
        )
        hint = "已开启 Agent 模式，女仆现在可以自主调用工具啦~" if checked else "已关闭 Agent 模式，回到普通聊天。"
        try:
            self.status_label.setText(hint)
        except Exception:
            logger.debug("静默降级：_on_toggle_agent_mode 中忽略异常", exc_info=True)
        # 会话级授权状态重置：每次开关都清空（重新授权）
        tools = getattr(self.app_ctx, "agent_tools", None)
        if tools is not None and hasattr(tools, "reset_session_authorization"):
            tools.reset_session_authorization()

    # ----- v1.4.7: 任务模式开关 -----
    def _on_toggle_task_mode(self, checked: bool) -> None:
        """任务模式切换：开启后发送消息走 managed task（自动拆分步骤/自愈/断点恢复）。

        任务模式依赖 Agent 模式：如果 Agent 未开启则自动开启。
        """
        if checked:
            # 任务模式需要 Agent 模式
            agent_btn = getattr(self, "agent_btn", None)
            if agent_btn is not None and not agent_btn.isChecked():
                agent_btn.setChecked(True)
            if self.chat_service is not None:
                self.chat_service.set_agent_mode(True)
            self.input_edit.setPlaceholderText(
                "任务模式：描述一个复杂任务，女仆会自动拆分步骤逐步执行（支持自愈/断点恢复）..."
            )
            self.status_label.setText("已开启任务模式，发送消息将自动拆分步骤执行~")
        else:
            self.input_edit.setPlaceholderText(
                "Agent 模式：女仆会自主调用工具完成任务（读文件/Git/写文件/跑代码/联网搜索）..."
                if (self.chat_service and self.chat_service.is_agent_mode()) else
                "和女仆说点什么吧... （或拖拽文件）"
            )
            self.status_label.setText("已关闭任务模式，回到普通 Agent 聊天。")

    def _is_task_mode(self) -> bool:
        """当前是否处于任务模式。"""
        btn = getattr(self, "task_btn", None)
        return btn is not None and btn.isChecked()

    # ----- v1.5.0: 「🌐 联网」开关与检索提示 -----
    def _on_toggle_web_search(self, checked: bool) -> None:
        """联网开关切换：状态持久化到 GuiConfig.web_search_enabled_gui。

        检索时机由 ChatService 决定（命中 should_auto_search 才搜），
        Agent 模式不受本开关影响（其自带 web_search 工具）。
        """
        try:
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "web_search_enabled_gui"):
                gui_cfg.web_search_enabled_gui = bool(checked)
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            logger.debug("静默降级：_on_toggle_web_search 中忽略异常", exc_info=True)
        try:
            self.status_label.setText(
                "已开启联网搜索：遇到需要最新信息的问题会自动检索~" if checked
                else "已关闭联网搜索。"
            )
        except Exception:
            logger.debug("静默降级：_on_toggle_web_search 中忽略异常", exc_info=True)

    # ----- v1.6(P0-2): 意图选态下拉 -----
    def _on_intent_mode_changed(self, index: int) -> None:
        """意图选态切换：持久化到 GuiConfig.chat_intent_mode。

        手动选态覆盖自动识别（"auto" 恢复纯规则识别）；选态只决定附加的
        语气提示（ChatService 请求副本注入），消息流绝不改道。
        """
        combo = getattr(self, "intent_combo", None)
        if combo is None:
            return
        try:
            mode = str(combo.currentData() or "auto")
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "chat_intent_mode"):
                gui_cfg.chat_intent_mode = mode
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            logger.debug("静默降级：_on_intent_mode_changed 中忽略异常", exc_info=True)
        try:
            tips = {
                "auto": "已回到自动识别：码铃按消息内容自动调整回应方式~",
                "confide": "已切换「只想说说」：码铃会先倾听陪伴，不急着给方案。",
                "chat": "已切换「陪我聊聊」：纯闲聊模式。",
                "analyze": "已切换「帮我分析」：码铃会给出有条理的分析。",
                "advise": "已切换「给我建议」：码铃会直接给明确建议。",
                "act": "已切换「帮我行动」：码铃会给可执行的步骤与方案。",
            }
            if self.status_label is not None:
                self.status_label.setText(tips.get(mode, ""))
        except Exception:
            logger.debug("静默降级：_on_intent_mode_changed 中忽略异常", exc_info=True)

    # ----- v1.8(V18-13/D-V18-07): 场景手动切换下拉 -----
    def _on_scene_mode_changed(self, index: int) -> None:
        """场景切换：持久化 GuiConfig.manual_scene + manual_scene_date（当日）。

        "" = 回到自动感知（清除手动覆盖）；选定场景当日有效、次日回落（Q-D4）。
        场景只影响语气底色（request_injections + 幂等边界消息）与工作时段
        主动降档（Q-D6），消息流绝不改道。
        """
        combo = getattr(self, "scene_combo", None)
        if combo is None:
            return
        try:
            value = str(combo.currentData() or "")
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "manual_scene"):
                gui_cfg.manual_scene = value
                if hasattr(gui_cfg, "manual_scene_date"):
                    gui_cfg.manual_scene_date = datetime.now().strftime("%Y-%m-%d")
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            logger.debug("静默降级：_on_scene_mode_changed 中忽略异常", exc_info=True)
        try:
            tips = {
                "": "已回到自动感知：码铃按时段切换场景语气（次日也无需手动调）。",
                "work": "已进入工作模式：回应会简洁高效，主动消息也会降到最低。",
                "rest": "已进入休息模式：轻松随意地聊，码铃陪主人放松~",
                "sleep": "已进入睡前模式：语气放轻放缓，安静陪伴。",
            }
            value = str(getattr(combo, "currentData", lambda: "")() or "")
            if self.status_label is not None:
                self.status_label.setText(tips.get(value, ""))
        except Exception:
            logger.debug("静默降级：_on_scene_mode_changed 中忽略异常", exc_info=True)

    # ==================================================================
    # v1.6(P0-3/D-V16-05): 反馈三键动作行（不入会话存档；R-A：不进 intimacy）
    # ==================================================================
    def _on_proactive_feedback_ready(self, subject: str, scene: str) -> None:
        """主动消息内容源就绪：在消息流末尾挂反馈三键动作行。"""
        if not subject:
            return  # 纯模板问候 → 不渲染三键
        try:
            from gui.widgets.proactive_feedback import ProactiveFeedbackBar
            bar = ProactiveFeedbackBar(subject, scene, self._on_feedback_picked)
            bar.set_app_ctx(self.app_ctx)
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, bar)
            self._feedback_bars.append(bar)
            self._scroll_to_bottom()
        except Exception:
            logger.debug("静默降级：_on_proactive_feedback_ready 中忽略异常", exc_info=True)

    def _on_feedback_picked(self, subject: str, scene: str, kind: str) -> None:
        """三键回调：纯 memory 策略写入（绝不触碰 intimacy / 交互打点）。"""
        session = getattr(self.app_ctx, "session", None)
        memory_mgr = getattr(session, "memory_mgr", None) if session is not None else None
        if memory_mgr is not None and hasattr(memory_mgr, "record_followup_feedback"):
            try:
                memory_mgr.record_followup_feedback(subject, kind)
            except Exception:
                logger.debug("静默降级：_on_feedback_picked 中忽略异常", exc_info=True)
        # 「想聊聊」：小字引导主人直接开口（复用既有小字插入通道；只引导不记分）
        if kind == "chat" and self.chat_service is not None:
            try:
                self.chat_service.web_search_notice.emit("💬 那我们接着聊~ 主人直接说就好")
            except Exception:
                logger.debug("静默降级：_on_feedback_picked 中忽略异常", exc_info=True)

    def _clear_feedback_bars(self) -> None:
        """新一条用户消息发出时移除未点击的反馈动作行（防堆积）。"""
        try:
            for bar in list(getattr(self, "_feedback_bars", [])):
                self.messages_layout.removeWidget(bar)
                bar.deleteLater()
            self._feedback_bars = []
        except Exception:
            self._feedback_bars = []

    def _on_web_search_notice(self, notice: str) -> None:
        """联网检索提示：在流式气泡前插入一条小字提示（不入会话存档）。"""
        if not notice:
            return
        try:
            from gui.utils import theme_color
            color = theme_color(self.app_ctx, "text_secondary", "#999999")
        except Exception:
            color = "#999999"
        try:
            label = QLabel(str(notice))
            label.setObjectName("webSearchNotice")
            label.setStyleSheet(
                f"color: {color}; font-size: 11px; padding: 2px 8px; background: transparent;"
            )
            label.setWordWrap(True)
            # 与气泡一致的插入位（末尾 stretch 之前），QLabel 不会被 _save_current_session 快照
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, label)
            self._scroll_to_bottom()
        except Exception:
            logger.debug("静默降级：_on_web_search_notice 中忽略异常", exc_info=True)

    def _on_agent_authorization_requested(self, action_desc: str, tool_name: str) -> None:
        """Agent 修改类工具授权弹窗（主线程）。

        用户点「是」→ 本次会话后续同类操作自动放行（会话级一次授权）；
        点「否」/ 关窗 → 拒绝本次。
        """
        try:
            tool_label = format_tool_label(tool_name)
            box = QMessageBox(self)
            box.setWindowTitle("码铃 · Agent 授权请求")
            box.setIcon(QMessageBox.Question)
            box.setText(f"女仆想执行一个修改类操作：\n\n【{tool_label}】\n{action_desc[:200]}")
            box.setInformativeText("允许本次及本次会话内后续操作吗？\n（白名单目录内的操作不受此限制，会自动放行）")
            yes_btn = box.addButton("允许（本次会话）", QMessageBox.AcceptRole)
            box.addButton("拒绝本次", QMessageBox.RejectRole)
            self._exec_modal_fade(box)
            approved = box.clickedButton() is yes_btn
        except Exception:
            approved = False
        try:
            if self.chat_service is not None:
                self.chat_service.resolve_agent_authorization(approved)
        except Exception:
            logger.debug("静默降级：_on_agent_authorization_requested 中忽略异常", exc_info=True)

    def _on_agent_tool_event(self, event_type: str, data_json: str) -> None:
        """Agent 工具轨迹：把 llm_start / tool_call / tool_done 等事件渲染进折叠卡片，
        同时保留状态栏文字提示（原有行为不回退）。
        """
        import json as _json
        try:
            data = _json.loads(data_json or "{}")
        except Exception:
            data = {}
        try:
            # v1.1(B2): 事件 → 工具轨迹卡片（防御式：卡片异常绝不外抛）
            trace = getattr(self, "tool_trace_panel", None)
            if trace is not None:
                try:
                    if not self._agent_trace_active:
                        trace.reset()
                        self._agent_trace_active = True
                    trace.add_event(event_type, data)
                    if event_type in ("final", "max_steps"):
                        trace.finish()
                        self._agent_trace_active = False
                except Exception:
                    self._agent_trace_active = False
        except Exception:
            logger.debug("静默降级：_on_agent_tool_event 中忽略异常", exc_info=True)
        # v1.2(A-9/A-10): Agent 干活中 -> 活动态 focus；结束/收尾 -> 回落
        if event_type in ("final", "max_steps"):
            self._publish_activity(None)
        elif self._agent_trace_active:
            self._publish_activity("focus")
        try:
            status_text = format_agent_event_status(event_type, data)
            if status_text is not None:
                self.status_label.setText(status_text)
        except Exception:
            logger.debug("静默降级：_on_agent_tool_event 中忽略异常", exc_info=True)

    def _on_theme_changed(self, theme_name: str) -> None:
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                widget.update_theme()
            elif isinstance(widget, ThinkingIndicator):
                widget.update_theme()
        # v2.1(I-2): 换肤 / 深浅切换 → 顶栏图标按新活动色板重新着色
        try:
            self._apply_title_icons()
        except Exception:
            logger.debug("静默降级：_on_theme_changed 中忽略异常", exc_info=True)
        # 第四阶段：附件栏 / 标签页栏主题色同步
        self.attachment_bar.refresh_theme()
        self.session_tabs.apply_theme()
        # v1.1(B2): 工具轨迹卡片主题刷新（防御式）
        try:
            self.tool_trace_panel.update_theme()
        except Exception:
            logger.debug("静默降级：_on_theme_changed 中忽略异常", exc_info=True)
        # v2.1(UI-Fix-0913)：会话侧栏 / 搜索区主题刷新（原本漏了这两块 → 切主题后残留粉色）
        try:
            self._apply_sidebar_theme()
        except Exception:
            logger.debug("静默降级：_on_theme_changed 中忽略异常", exc_info=True)

    def _apply_sidebar_theme(self) -> None:
        """会话侧栏 + 搜索区主题刷新（供 _init_ui 与 _on_theme_changed 共用）。

        v2.1(UI-Fix-0913)：这两块虽已改用 ``theme_color``，但那是**构造时**解析的，
        切主题后不会自动重来；而 ``_on_theme_changed`` 原本只刷气泡 / 顶栏图标 /
        附件栏 / 标签页，没覆盖这里 → 残留默认粉色。
        """
        try:
            from gui.utils import theme_color
            _txt2 = theme_color(self.app_ctx, "text_secondary", "#5D4037")
            _ac = theme_color(self.app_ctx, "accent", "#FF6B9D")
            _ac_l = theme_color(self.app_ctx, "accent_light", "#FF9EB5")
            _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
            _bg_card = theme_color(self.app_ctx, "bg_card", "#FFE4EC")
        except Exception:
            return
        try:
            self.session_list.setStyleSheet(
                f"QListWidget {{ background: transparent; border: none; outline: none; }}"
                f"QListWidget::item {{ padding: 6px 8px; border-radius: 6px; color: {_txt2}; }}"
                f"QListWidget::item:selected {{ background: {_bg_card}; color: {_ac}; font-weight: 500; }}"
                f"QListWidget::item:hover {{ background: {_bg_l}; }}"
            )
        except Exception:
            logger.debug("静默降级：_apply_sidebar_theme 中忽略异常", exc_info=True)
        try:
            self.search_edit.setStyleSheet(
                f"QLineEdit {{ background: {_bg_l}; border: 1px solid {_ac_l};"
                f" border-radius: 10px; padding: 2px 8px; font-size: 11px; }}"
                f"QLineEdit:focus {{ border-color: {_ac_l}; }}"
            )
        except Exception:
            logger.debug("静默降级：_apply_sidebar_theme 中忽略异常", exc_info=True)
        try:
            self.toggle_sidebar_btn.setStyleSheet(
                f"QPushButton {{ background: {_bg_l}; color: {_ac_l}; border: none;"
                f" border-radius: 4px; font-size: 10px; }}"
                f"QPushButton:hover {{ background: {_ac_l}; color: white; }}"
            )
        except Exception:
            logger.debug("静默降级：_apply_sidebar_theme 中忽略异常", exc_info=True)

