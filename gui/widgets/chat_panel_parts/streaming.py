# -*- coding: utf-8 -*-
"""流式输出与失败保留动作行（开始/分块/结束/取消、思考态、失败重试与改后重发）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from gui import icons
from gui.chat_bubble_utils import DEFAULT_MAX_BUBBLE_WIDTH
from gui.qt_compat import QHBoxLayout
from gui.qt_compat import QPushButton
from gui.qt_compat import Qt
from gui.session_manager import is_group_session as _is_group_session
from gui.widgets.message_bubble import MessageBubble
from typing import Optional

logger = logging.getLogger("maid_coder.gui.chat_panel.streaming")


class ChatStreamingMixin:
    """流式输出与失败保留动作行（开始/分块/结束/取消、思考态、失败重试与改后重发）（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 流式输出
    # ==================================================================
    def _on_stream_started(self) -> None:
        self._stream_buffer = ""
        self._current_ai_bubble: Optional[MessageBubble] = None
        self.stop_btn.setVisible(True)
        self.send_btn.setEnabled(False)
        # v1.6(P0-4/T4): 状态链第二拍 —— 模型已响应（思考拍在 _on_thinking）
        try:
            self.status_label.setText("模型响应中…")
        except Exception:
            logger.debug("静默降级：_on_stream_started 中忽略异常", exc_info=True)
        # v1.2(A-9/A-10): 开始回复 -> 活动态 thinking（宠物/气泡头像等广播）
        self._publish_activity("thinking")

    def _on_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        # v1.6(P0-4/T4): 状态链第三拍 —— 首个增量到达 →「正在回复…」
        if not getattr(self, "_status_first_chunk", False):
            self._status_first_chunk = True
            try:
                self.status_label.setText("正在回复…")
            except Exception:
                logger.debug("静默降级：_on_chunk 中忽略异常", exc_info=True)
        if self._current_ai_bubble is None:
            is_consecutive = self._last_role == "assistant"
            # v1.7(F10a): 群聊流式气泡带发言者头像+名字（发言者由 service 调度提供）
            speaker_id = None
            if _is_group_session(self._current_group_session()):
                speaker_id = getattr(self.chat_service, "current_group_speaker", None)
                if speaker_id and is_consecutive:
                    is_consecutive = self._last_speaker_id == speaker_id
            speaker_role = self._group_role_by_id(speaker_id) if speaker_id else None
            # v2.1(UI-Fix-0912-2): 群聊头像同单聊的修法——优先发言者头像,空就空,不再回退到 _current_role_avatar
            avatar_path = ""
            if speaker_role is not None:
                avatar_path = str(getattr(speaker_role, "avatar", "") or "")
            if not avatar_path:
                avatar_path = self._current_role_avatar  # 仅当发言者和 current 都没头像时才用 current
            self._current_ai_bubble = MessageBubble(
                "assistant", self._stream_buffer,
                is_consecutive=is_consecutive,
                max_bubble_width=DEFAULT_MAX_BUBBLE_WIDTH,
                app_context=self.app_ctx,
                # Bug4: 流式 AI 气泡同样用当前角色头像
                # v1.7(F10a): 群聊流式气泡用发言角色头像
                avatar_path=avatar_path,
                # v2.1(UI-P2): 流式气泡同样显示**人名**（given_name），非人设标签
                speaker_name=self._speaker_display_name(speaker_role) if speaker_role else None,
            )
            if speaker_role is not None:
                try:
                    self._current_ai_bubble.speaker_id = speaker_id
                except Exception:
                    logger.debug("静默降级：_on_chunk 中忽略异常", exc_info=True)
            # v1.3(P1-1): 流式气泡同样接朗读（只朗读 AI 文本）
            self._current_ai_bubble.read_aloud_requested.connect(
                lambda b=self._current_ai_bubble: self._on_bubble_read_aloud(b)
            )
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, self._current_ai_bubble)
            self._last_role = "assistant"
            self._last_speaker_id = speaker_id
            # v2.1(M-2): 流式回复气泡落地同样入场（仅视觉，不改流式时序）
            self._apply_bubble_entrance(self._current_ai_bubble, True)
        else:
            self._current_ai_bubble.update_text(self._stream_buffer)
        self._scroll_to_bottom()

    def _on_stream_finished(self, full_text: str, usage: dict) -> None:
        # v1.4(B1b): 本轮回传了屏幕帧 → 把用量补记进看屏 chip（成本可见）
        self._settle_screen_round_tokens(usage)
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 状态链收尾 —— 清状态；成功 → 清残留失败动作行
        self._status_first_chunk = False
        self._clear_failure_actions()
        # v1.2.3(无焦虑红线): 聊天面板不再展示逐条/累计 token（数值焦虑）；
        # 累计用量仍由 session.add_usage 记账，只在首页 Token 卡呈现。
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 回复完成 -> 回落心情态（活动态结束）
        self._publish_activity(None)
        # v1.1(B2): Agent 流结束（含中途取消）→ 轨迹收起为可折叠摘要
        try:
            if self._agent_trace_active:
                trace = getattr(self, "tool_trace_panel", None)
                if trace is not None:
                    if trace.has_events():
                        hint = "已取消" if (usage or {}).get("cancelled") else "执行结束"
                        trace.finish(hint)
                    else:
                        # 没有跑出任何轨迹（如演示模式/立即失败）：不留空卡片
                        trace.reset()
                self._agent_trace_active = False
        except Exception:
            self._agent_trace_active = False
        # v1.3(P2-2): 语音消息的回复流结束 -> 免提读回复/回到 listening
        self._hf_resume_after_reply(full_text or "")
        self._save_current_session()
        # v1.7(F10): 串行接话由 service 队列驱动（_on_group_stream_finished 推进），
        # 面板只负责渲染/落盘，无需再触发下一位

    def _on_stream_cancelled(self) -> None:
        self._settle_screen_round_tokens({})
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 取消 → 状态清除（取消不算失败，失败动作行一并收走）
        self._status_first_chunk = False
        self._clear_failure_actions()
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 中止 -> 回落心情态
        self._publish_activity(None)
        self._add_message_bubble("assistant", "生成已停止~")
        # v1.3(P2-2): 免提语音的回复被取消 -> 放行回 listening
        self._hf_resume_after_reply("")
        self._save_current_session()

    def _on_thinking(self, active: bool) -> None:
        if active:
            self.thinking_indicator.start()
        else:
            self.thinking_indicator.stop()
        # v1.6(P0-4/T4): 状态链第二拍 ——「正在思考…」（自然不机械；
        # 已进入流式时 thinking(False) 不回写，保持「正在回复…」到完成清空）
        # v1.9(C/D-V19-03): 去「女仆」自称残留，改中性表述。
        if active:
            self.status_label.setText("正在思考…")
        elif not getattr(self, "_status_first_chunk", False):
            self.status_label.setText("")

    def _on_message_failed(self, error: str) -> None:
        """v10.15: API 错误冒泡 —— 真实展示错误，不再以女仆语气掩盖。

        v1.6(P0-4/T2/D-V16-07): 失败保留链 UI 入口 —— 数据层 user 消息早已保留
        （_launch_worker 先写 session 后调 API，失败不回滚），此处补动作行：
        错误气泡（红边）之下挂「🔄 重试 / ✏️ 改后重发」。
        """
        self._settle_screen_round_tokens({})
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 失败 → 状态清除（动作行承接后续）
        self._status_first_chunk = False
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 失败同样结束活动态
        self._publish_activity(None)
        # v1.1(B2): Agent 中途出错 → 轨迹收起为「执行中断」摘要
        try:
            if self._agent_trace_active:
                trace = getattr(self, "tool_trace_panel", None)
                if trace is not None:
                    if trace.has_events():
                        trace.finish("执行中断")
                    else:
                        trace.reset()
                self._agent_trace_active = False
        except Exception:
            self._agent_trace_active = False
        # 错误以 assistant 气泡呈现（红色加重），明确告诉用户是失败而非助手回复
        err_bubble = self._add_message_bubble("assistant", error, error_style=True)
        # v1.7(F10a): 群聊失败 → 不挂重试动作行（重试走单聊链，
        # 会写 session.history，群聊禁入，R-J 隔离）；发言者由 service 复位
        if _is_group_session(self._current_group_session()):
            self.status_label.setText("群聊回复失败，请在输入框重新发送~")
        else:
            # v1.6(P0-4/T2): 错误气泡之下挂失败动作行（🔄 重试 / ✏️ 改后重发）
            self._show_failure_actions(err_bubble)
        # v1.3(P2-2): 语音消息发送失败 -> 放行回 listening（避免卡在 sending）
        self._hf_resume_after_reply("")
        self._save_current_session()

    # ==================================================================
    # v1.6(P0-4/T2/D-V16-07): 失败保留动作行（🔄 重试 / ✏️ 改后重发）
    # 数据层 user 消息在失败时不回滚（_launch_worker 先写后调 API）——
    # 重试走 ChatService.retry_last_failure（skip_history_write 幂等，
    # 切勿改走 send_message 会重复入库）；改后重发走既有编辑截断链。
    # ==================================================================
    def _show_failure_actions(self, anchor_bubble=None) -> None:
        """错误气泡之后插入动作行；引用对 (user_bubble, row) 保留失败现场。"""
        try:
            from gui.qt_compat import QWidget as _QWidget
            row = _QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 0, 8, 6)
            lay.setSpacing(8)
            try:
                from gui.utils import theme_color
                _accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
                # v2.1(UI-P1)：按钮文字用 accent_text（「文字用」强调色）；描边仍 accent。
                _accent_text = theme_color(self.app_ctx, "accent_text", "#B45073")
                _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
                _text = theme_color(self.app_ctx, "text", "#5D4037")
            except Exception:
                _accent, _accent_text, _bg_l = "#FF6B9D", "#B45073", "#FFF0F3"
                _text = "#5D4037"
            _btn_ss = (
                "QPushButton {"
                f"  background: transparent; color: {_accent_text};"
                f"  border: 1px solid {_accent}; border-radius: 12px;"
                "  font-size: 12px; padding: 3px 12px;"
                "}"
                "QPushButton:hover {"
                # v2.1(UI-P1)：hover 换 bg_light 实底 → 显式声明 color，
                # 否则回落 accent_text（vs bg_light 仅 4.1~4.4，三套浅色不过）。
                f"  background: {_bg_l}; color: {_text};"
                "}"
            )
            retry_btn = QPushButton(f"{icons.text_glyph('retry', '🔄')} 重试")
            retry_btn.setCursor(Qt.PointingHandCursor)
            retry_btn.setFixedHeight(26)
            retry_btn.setStyleSheet(_btn_ss)
            retry_btn.clicked.connect(self._on_retry_failed)
            edit_btn = QPushButton(f"{icons.text_glyph('edit_resend', '✏️')} 改后重发")
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.setFixedHeight(26)
            edit_btn.setStyleSheet(_btn_ss)
            edit_btn.clicked.connect(self._on_edit_resend_failed)
            lay.addWidget(retry_btn)
            lay.addWidget(edit_btn)
            lay.addStretch()
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, row)
            self._failure_row = row
            # 失败现场引用对：最近一条 user 气泡（改后重发的截断锚点）
            ub = getattr(self, "_last_user_bubble", None)
            self._failure_user_bubble = ub
            self._scroll_to_bottom()
        except Exception:
            self._failure_row = None
            self._failure_user_bubble = None

    def _clear_failure_actions(self) -> None:
        """移除失败动作行（重试成功 / 用户开新话头 / 取消 / 会话切换时）。"""
        row = getattr(self, "_failure_row", None)
        if row is not None:
            try:
                self.messages_layout.removeWidget(row)
                row.deleteLater()
            except RuntimeError:
                logger.debug("静默降级：_clear_failure_actions 中忽略异常", exc_info=True)
            except Exception:
                logger.debug("静默降级：_clear_failure_actions 中忽略异常", exc_info=True)
        self._failure_row = None
        self._failure_user_bubble = None

    def _on_retry_failed(self) -> None:
        """🔄 重试：chat_service.retry_last_failure()（skip_history_write 幂等）。"""
        if self.chat_service is None:
            return
        self._clear_failure_actions()
        # v1.6(P0-4/T4): 状态链「重试中…」
        self._status_first_chunk = False
        self.status_label.setText("重试中…")
        try:
            if not self.chat_service.retry_last_failure():
                self.status_label.setText("没有可重试的消息~")
        except Exception:
            self.status_label.setText("")

    def _on_edit_resend_failed(self) -> None:
        """✏️ 改后重发：对失败前的 user 气泡执行既有编辑截断链
        （R9 确认框 + 截断该条及之后 + 回填输入框），用户改完自行正常发送
        —— 截断后 session 已无该条，正常发送不重复入库（幂等）。
        """
        bubble = getattr(self, "_failure_user_bubble", None)
        if bubble is None:
            return
        self._clear_failure_actions()
        try:
            self._on_edit_requested(bubble)
        except Exception:
            logger.debug("静默降级：_on_edit_resend_failed 中忽略异常", exc_info=True)

