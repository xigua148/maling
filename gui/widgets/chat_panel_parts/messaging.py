# -*- coding: utf-8 -*-
"""消息发送与群聊发言调度/渲染（含气泡增删、头像联动、群占位提示）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from datetime import datetime
from gui import motion
from gui.chat_bubble_utils import DEFAULT_MAX_BUBBLE_WIDTH
from gui.models import ChatMessage
from gui.qt_compat import QGraphicsOpacityEffect
from gui.qt_compat import QTimer
from gui.session_manager import is_group_session as _is_group_session
from gui.widgets.message_bubble import MessageBubble
from gui.widgets.message_bubble import invalidate_default_speaker_name
from gui.widgets.message_bubble import resolve_speaker_name
from typing import List
from typing import Optional

logger = logging.getLogger("maid_coder.gui.chat_panel.messaging")


class ChatMessagingMixin:
    """消息发送与群聊发言调度/渲染（含气泡增删、头像联动、群占位提示）（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 消息处理
    # ==================================================================
    def _on_send(self) -> None:
        """发送消息（支持纯文本、附件、或两者都有）。"""
        text = self.input_edit.toPlainText().strip()
        attachments = self.attachment_bar.attachments()
        if not text and not attachments:
            return
        # v1.7(F10a/D-V17-06): 群聊会话 → 群聊发言调度（独立路径，不进单聊链）
        if _is_group_session(self._current_group_session()):
            self.input_edit.clear()
            self._on_group_send(text, attachments)
            return
        # v1.4(B2): 「🖱 操作」点亮时，下一条纯文本消息路由给单步操作（单次即熄）
        computer_btn = getattr(self, "computer_btn", None)
        if computer_btn is not None and computer_btn.isChecked() and text and not attachments:
            self._route_computer_request(text)
            return
        self.input_edit.clear()
        bubble_text = text if text else "📎 附件"

        # v1.6(P0-3): 用户开新话头 → 移除未点击的反馈动作行（防堆积）
        self._clear_feedback_bars()
        # v1.6(P0-4): 用户开新话头 → 移除上一条失败动作行（用户已选择继续前进）
        self._clear_failure_actions()

        # v1.4(B1b): 看屏期间 —— 按屏提问 / 被动命中 → 把最近帧作为内存附件随消息发送
        screen_att = None
        if self.chat_service is not None and not attachments and getattr(self, "_watch_svc", None) is not None:
            try:
                want_ask = False
                bar = getattr(self, "screen_watch_bar", None)
                if bar is not None and bar.ask_pending():
                    want_ask = True
                elif self._watch_svc.is_running() and self._screen_intent_hit(text):
                    want_ask = True
                if want_ask:
                    screen_att = self._attach_screen_frame()
                    bar.set_ask_pending(False) if bar is not None else None
                    if screen_att:
                        self.status_label.setText("已附上当前屏幕（内存帧，不落盘）")
            except Exception:
                screen_att = None

        extra_attachments = list(attachments)
        if screen_att:
            extra_attachments.append(screen_att)
            self._screen_pending_token = True  # 流结束补记 token
        self._add_message_bubble("user", bubble_text, attachments=extra_attachments)
        self.attachment_bar.clear()
        self._save_current_session()
        # v10.15: 用共享 helper 拼装附件 payload（文本 ≤50KB 直入 prompt，二进制做诚实标注）
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(text, attachments)

        # v1.1(B2): 新一次用户消息：清空上一轮工具轨迹；若处于 Agent 模式则预备收集
        self._reset_agent_trace()

        if self.chat_service is not None:
            # v1.4.7: 任务模式时 task_type="managed_task"，否则由 chat_service 内部根据 agent_mode 决定
            task_type = "managed_task" if self._is_task_mode() else "chat"
            # R1: UI 直插气泡为唯一 user 渲染入口——抑制服务层 message_added 回声
            self.chat_service.send_message(send_text, task_type=task_type, suppress_echo=True, attachments=extra_attachments)
            # v1.6(P0-4/T4): 发送状态链第一拍 ——「发送中…」
            self._status_first_chunk = False
            self.status_label.setText("发送中…")
        else:
            self._add_message_bubble("assistant", "哎呀，女仆的聊天服务还没准备好呢... 请主人稍等~")

    def _reset_agent_trace(self) -> None:
        """清空上一轮工具轨迹；若处于 Agent 模式则标记为本轮预备收集。

        面板本身保持隐藏，直到第一个 agent 事件到达才 show（避免空白卡片）。
        """
        try:
            panel = getattr(self, "tool_trace_panel", None)
            if panel is not None:
                panel.reset()
            agent_mode = False
            if self.chat_service is not None:
                agent_mode = bool(self.chat_service.is_agent_mode())
            self._agent_trace_active = agent_mode
        except Exception:
            self._agent_trace_active = False

    # ==================================================================
    # v1.7(F10a/F10b/D-V17-06): 群聊发言调度与渲染（显示会话层）
    # ==================================================================
    def _current_group_session(self):
        """v1.7(F10a): 当前活跃显示会话（群聊判定用；单聊返回该会话但由调用方判定）。"""
        if self.session_manager is None or not self._current_session_id:
            return None
        return self.session_manager.get_session(self._current_session_id)

    def _group_role_by_id(self, role_id: Optional[str]):
        """v1.7(F10a): RoleManager 只读解析角色（头像/名字渲染；仅群聊路径调用）。"""
        if not role_id:
            return None
        try:
            from gui.pages.page_role import RoleManager
            return RoleManager().get_role(role_id)
        except Exception:
            return None

    def _group_member_roles(self, session) -> dict:
        """v1.7(F10a): 群成员 id→Role 只读映射。"""
        if session is None:
            return {}
        try:
            from gui.pages.page_role import RoleManager
            ids = set((session.metadata or {}).get("members") or [])
            return {r.id: r for r in RoleManager().all_roles() if r.id in ids}
        except Exception:
            return {}

    def _apply_group_placeholder(self, session) -> None:
        """v1.7(F10a): 群聊/单聊输入框占位提示切换（零逻辑影响）。"""
        try:
            # v1.7(F10b): 切换会话时收起 @补全浮层（防旧会话成员名单残留）
            self._hide_mention_popup()
            if session is not None and _is_group_session(session):
                self.input_edit.setPlaceholderText("在群里 @角色名 说话...")
            else:
                self.input_edit.setPlaceholderText("和女仆说点什么吧... （或拖拽文件）")
        except Exception:
            logger.debug("静默降级：_apply_group_placeholder 中忽略异常", exc_info=True)

    def _on_group_send(self, text: str, attachments: list) -> None:
        """v1.7(F10 自由发言): 群聊发送路径 —— user 气泡入显示会话 → 一轮调度。

        - @点名（显式覆盖，最高优先级）：被 @ 角色必回；
        - 未 @：轻量 LLM 调度决定本轮接话者（1-2 人串行接话），
          silent 策略则全员沉默等待 @（消息照常入会话，零回复）；
        - 完全不触碰 app_ctx.session（LLM 对齐历史）与 v1.5.1 对齐链。
        """
        session = self._current_group_session()
        if session is None or self.chat_service is None:
            return
        self._hide_mention_popup()
        self._clear_feedback_bars()
        self._clear_failure_actions()
        bubble_text = text if text else "📎 附件"
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(text, attachments)
        self._add_message_bubble("user", bubble_text, attachments=list(attachments) or None)
        self._save_current_session()
        self._reset_agent_trace()
        self._status_first_chunk = False
        member_roles = self._group_member_roles(session)
        try:
            mode = self.chat_service.send_group_turn(send_text, session, member_roles)
        except Exception as exc:
            logger.exception("群聊一轮调度失败: %s", exc)
            mode = "silent"
        if mode == "silent":
            # silent 策略：消息已入会话，零回复（诚实呈现「等你点名」）
            self.status_label.setText("已发送。本群为沉默模式，@角色名 才会回复~")
        else:
            self.status_label.setText("")

    def _on_message_added(self, role: str, content: str) -> None:
        # v1.7(F10b): proactive 边界收口 —— 群聊会话激活时，单聊链的主动消息
        #（proactive_ask 等写 LLM 会话触发 message_added 的路径）不入群聊面板/
        # 不落群聊显示会话（防被当成无 speaker 的「成员」发言污染历史改写）。
        # LLM 历史中的该条由下次切回单聊的 replace_history 重建自然收敛。
        current = self._current_group_session()
        if current is not None and _is_group_session(current) \
                and role == "assistant" \
                and getattr(self, "_current_ai_bubble", None) is None:
            return
        # R1: 发送方已抑制回声（面板/独立窗口直插气泡）时跳过，避免双气泡
        if role == "user":
            service = self.chat_service
            if service is not None and getattr(service, "echo_suppressed", False):
                return
        # R1: 流式期间 assistant 回声跳过——流式气泡已是展示载体；
        # 仅非流式（mock / 非流式 API）回放路径经此处渲染
        if role == "assistant" and getattr(self, "_current_ai_bubble", None) is not None:
            return
        if role in ("user", "assistant"):
            self._add_message_bubble(role, content)
            self._save_current_session()

    def _on_role_avatar_changed(self, role_id: str, avatar_path: str, base_expr: str) -> None:
        """Bug4: 角色生效广播 → 缓存头像路径，新 AI 气泡用角色头像（历史气泡不追溯）。"""
        self._current_role_avatar = str(avatar_path or "")
        # v2.1(UI-P2): 角色换了 → 人名（given_name）缓存失效，下一条 AI 气泡取新名字。
        # 缓存失效后才解析，故 RoleManager 读盘次数 = 角色切换次数，而非气泡条数。
        try:
            invalidate_default_speaker_name()
        except Exception:
            logger.debug("静默降级：_on_role_avatar_changed 中忽略异常", exc_info=True)

    @staticmethod
    def _speaker_display_name(speaker_role) -> str:
        """v2.1(UI-P2): 群聊发言者显示**人名** —— 与单聊同一真值源。

        走 message_bubble.resolve_speaker_name 三级兜底（given_name → 预设表 →
        「码铃」）。**绝不退回 role.name** —— 「猫娘」「女仆」是人设标签，不是人名。
        """
        try:
            return resolve_speaker_name(speaker_role)
        except Exception:
            return "码铃"

    def _add_message_bubble(
        self, role: str, content: str, attachments: Optional[List[dict]] = None,
        error_style: bool = False, speaker_id: Optional[str] = None,
        animate: Optional[bool] = None,
    ) -> "MessageBubble":
        """新增消息气泡。

        ``animate``（v2.1/M-2）：``None`` = 按 ``_loading_history`` 自动判定
        （历史重载 → False，新消息 → True）；显式 ``True``/``False`` 覆盖判定。
        入场动效绝不改变落库 / 流式时序，也不阻塞发送链路。
        """
        is_consecutive = self._last_role == role
        # v1.7(F10a): 群聊中不同发言者的连续 assistant 气泡不算连续（保留名字/头像）
        if role == "assistant" and speaker_id is not None:
            is_consecutive = is_consecutive and self._last_speaker_id == speaker_id
        # v1.7(F10a): 群聊发言者 → 头像/名字从 RoleManager 只读解析
        speaker_role = self._group_role_by_id(speaker_id) \
            if (speaker_id and role == "assistant") else None
        # v2.1(UI-Fix-0912): 优先取发言者头像(新角色),空就空——不再回退到上一个角色的 _current_role_avatar
        avatar_path = ""
        if speaker_role is not None:
            avatar_path = str(getattr(speaker_role, "avatar", "") or "")
        if not avatar_path:
            avatar_path = self._current_role_avatar
        bubble = MessageBubble(
            role, content,
            is_consecutive=is_consecutive,
            # 大气化：气泡最大宽度从 280 提到 720，对齐 WorkBuddy/豆包现代 AI 聊天观感
            max_bubble_width=DEFAULT_MAX_BUBBLE_WIDTH,
            app_context=self.app_ctx,
            attachments=attachments,
            error_style=error_style,  # v10.15: 错误气泡红框
            # Bug4: AI 气泡传入当前角色头像（无则回落女仆表情头像）
            # v1.7(F10a): 群聊气泡优先用发言角色头像
            avatar_path=avatar_path if (role == "assistant" and avatar_path) else None,  # v2.1(UI-Fix-0912): 空就空,不再回退到上一个角色的小铃
            # v2.1(UI-P2): 群聊气泡显示发言者**人名**（given_name），非人设标签
            speaker_name=self._speaker_display_name(speaker_role) if speaker_role else None,
        )
        if speaker_role is not None:
            try:
                bubble.speaker_id = speaker_id  # _save_current_session 持久化用
            except Exception:
                logger.debug("静默降级：_add_message_bubble 中忽略异常", exc_info=True)
        bubble.delete_requested.connect(lambda: self._remove_bubble(bubble))
        bubble.edit_requested.connect(lambda b=bubble: self._on_edit_requested(b))
        bubble.regenerate_requested.connect(lambda b=bubble: self._on_regenerate_requested(b))
        # v1.3(P1-1): 朗读按钮 -> 本面板接 TTS（只朗读 AI 文本）
        bubble.read_aloud_requested.connect(lambda b=bubble: self._on_bubble_read_aloud(b))
        # v1.3(P2-3): 右键收藏高光回忆（AI 与用户气泡均可）
        bubble.favorite_requested.connect(
            lambda role, text, meta, b=bubble: self._on_favorite_requested(b, role, text, meta)
        )
        idx = self.messages_layout.count() - 2
        if idx < 0:
            idx = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(idx, bubble)
        self._last_role = role
        self._last_speaker_id = speaker_id if role == "assistant" else None
        # v1.6(P0-4/T2): 记录最近一条 user 气泡（失败动作行「改后重发」锚点用）
        if role == "user":
            self._last_user_bubble = bubble
        # v2.1(M-2): 新消息入场（历史重载期自动跳过；off 档直落终态）
        self._apply_bubble_entrance(bubble, animate)
        self._scroll_to_bottom()
        return bubble

    # ------------------------------------------------------------------
    # v2.1(M-2/D-V21-02): 气泡入场（历史重载不重播）
    # ------------------------------------------------------------------
    def _apply_bubble_entrance(self, bubble, animate: Optional[bool] = None) -> None:
        """新气泡短促淡入；``animate=None`` 时按 ``_loading_history`` 判定。

        · 历史重载 / 切会话 / 恢复会话（``_loading_history=True``）→ 不放动画；
        · ``off`` 档或系统关闭动画（``motion.fade`` 返回 ``None``）→ 直接设终态；
        · 全程 try/except：动画失败绝不打断发送 / 流式 / 落库链路（R-D/R-P）。
        """
        try:
            if animate is None:
                animate = not getattr(self, "_loading_history", False)
            if not animate:
                return
            anim = motion.fade(
                bubble, to=1.0,
                on_finished=lambda b=bubble: self._schedule_effect_removal(b),
            )
            if anim is None:
                # off 档 / 系统关闭动画：直接设不透明终态，绝不留半透明残影
                self._set_widget_opacity(bubble, 1.0)
        except Exception:
            logger.debug("静默降级：_apply_bubble_entrance 中忽略异常", exc_info=True)

    def _set_widget_opacity(self, widget, value: float) -> None:
        """直接设控件不透明度终态（无 opacity effect 时静默跳过）。"""
        try:
            eff = widget.graphicsEffect()
            if isinstance(eff, QGraphicsOpacityEffect):
                eff.setOpacity(float(value))
        except Exception:
            logger.debug("静默降级：_set_widget_opacity 中忽略异常", exc_info=True)

    def _schedule_effect_removal(self, widget) -> None:
        """入场结束 → 延迟移除临时 QGraphicsOpacityEffect（R-P：不留常驻离屏合成）。"""
        try:
            QTimer.singleShot(0, lambda w=widget: self._drop_opacity_effect(w))
        except Exception:
            logger.debug("静默降级：_schedule_effect_removal 中忽略异常", exc_info=True)

    def _drop_opacity_effect(self, widget) -> None:
        try:
            eff = widget.graphicsEffect()
            if isinstance(eff, QGraphicsOpacityEffect):
                widget.setGraphicsEffect(None)
        except Exception:
            logger.debug("静默降级：_drop_opacity_effect 中忽略异常", exc_info=True)

    def add_message(
        self, role: str, content: str, attachments: Optional[List[dict]] = None
    ) -> None:
        """外部调用：添加消息。"""
        self._add_message_bubble(role, content, attachments=attachments)
        self._save_current_session()

    def _remove_bubble(self, bubble: MessageBubble) -> None:
        self.messages_layout.removeWidget(bubble)
        bubble.deleteLater()
        self._save_current_session()

    def _save_current_session(self) -> None:
        """将当前消息保存到活跃会话。

        R11: 增量同步——按序对位更新，命中前缀的消息对象原位改 content/metadata，
        保留 id/timestamp/model/tokens 等既有字段；仅新增消息才生成新 ChatMessage。
        """
        if self.session_manager is None or self._current_session_id is None:
            return
        session = self.session_manager.get_session(self._current_session_id)
        if session is None:
            return
        # 先快照当前气泡（R10 同理：避免边遍历边删引发的不一致）
        bubbles: List[MessageBubble] = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                bubbles.append(widget)
        # 会话中多出的尾部消息（截断/删除）直接裁掉
        if len(session.messages) > len(bubbles):
            del session.messages[len(bubbles):]
        # 逐条对位同步
        for i, widget in enumerate(bubbles):
            atts = widget.get_attachments()
            metadata = {"attachments": atts} if atts else {}
            text = widget.get_text()
            # v1.7(F10a): 群聊发言者归属持久化（气泡 attr → 存量消息 metadata 均可来源）
            speaker_id = getattr(widget, "speaker_id", None)
            if not speaker_id and i < len(session.messages):
                speaker_id = (session.messages[i].metadata or {}).get("speaker_id")
            if speaker_id and widget.role == "assistant":
                metadata["speaker_id"] = speaker_id
            if i < len(session.messages):
                msg = session.messages[i]
                if msg.role == widget.role:
                    if msg.content != text or msg.metadata != metadata:
                        msg.content = text
                        msg.metadata = metadata
                else:
                    # 角色错位（编辑后重排）：整条替换
                    session.messages[i] = ChatMessage(
                        role=widget.role, content=text, metadata=metadata
                    )
            else:
                session.messages.append(
                    ChatMessage(role=widget.role, content=text, metadata=metadata)
                )
        session.updated_at = datetime.now()
        self.session_manager.save_active()
        self._refresh_session_list()

