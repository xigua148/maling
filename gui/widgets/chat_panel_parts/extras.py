# -*- coding: utf-8 -*-
"""扩展功能（拖拽上传 / 消息编辑与重新生成 / 多会话标签页 / 语音输入 / 免提对话 / 拍照发图 / 小游戏 / 收藏 / 朗读 TTS）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from gui import icons
from gui.qt_compat import QDialog
from gui.qt_compat import QMessageBox
from gui.qt_compat import Qt
from gui.session_manager import is_group_session as _is_group_session
from gui.widgets import voice_input as voice_input_mod
from gui.widgets.message_bubble import MessageBubble
from typing import List
from typing import Optional
import os

logger = logging.getLogger("maid_coder.gui.chat_panel.extras")


class ChatExtrasMixin:
    """扩展功能（拖拽上传 / 消息编辑与重新生成 / 多会话标签页 / 语音输入 / 免提对话 / 拍照发图 / 小游戏 / 收藏 / 朗读 TTS）（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # 第四阶段 · 扩展功能：拖拽 / 编辑 / 重新生成 / 标签页 / 语音
    # ==================================================================
    # ----- 拖拽上传 -----
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        added = 0
        skipped_big: List[str] = []
        skipped_missing: List[str] = []
        skipped_dup: List[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ok, info = self.attachment_bar.add_file_path(path)
            if ok is True:
                added += 1
            elif info == "too_large":
                skipped_big.append(os.path.basename(path))
            elif info == "missing":
                skipped_missing.append(os.path.basename(path))
            elif info == "duplicate":
                skipped_dup.append(os.path.basename(path))
        event.acceptProposedAction()
        # 汇总提示
        if skipped_big:
            QMessageBox.warning(
                self,
                "附件过大",
                f"以下文件超过 10MB 上限，未添加：\n  " + "\n  ".join(skipped_big),
            )
        elif skipped_missing or skipped_dup:
            lines = []
            if skipped_missing:
                lines.append("不存在的文件：\n  " + "\n  ".join(skipped_missing))
            if skipped_dup:
                lines.append("已存在的附件：\n  " + "\n  ".join(skipped_dup))
            QMessageBox.information(self, "部分附件未添加", "\n\n".join(lines))

    # ----- 消息编辑 / 重新生成 -----
    def _on_edit_requested(self, bubble: MessageBubble) -> None:
        """编辑用户消息：截断该消息及其后内容，回填到输入框，保存会话。"""
        if bubble.role != "user":
            return
        # v1.7(F10a): 群聊消息不支持编辑（截断链走 LLM 历史重建，禁入群聊，R-J 隔离）
        if _is_group_session(self._current_group_session()):
            QMessageBox.information(self, "群聊", "群聊消息暂不支持编辑（MVP）~")
            return
        # R9: 编辑会截断该消息及其后全部内容，先弹确认，避免误触即永久丢失
        reply = QMessageBox.question(
            self, "编辑消息",
            "编辑将移除该消息及其后的所有消息（含 AI 回复），\n"
            "原文与附件会回填到输入框。确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # R10: 截断前先取局部变量，deleteLater 之后不再访问 bubble 的内容接口
        text = bubble.get_text()
        atts = bubble.get_attachments()
        if self._truncate_messages_from(bubble):
            # 回填
            self.input_edit.setPlainText(text)
            # 附件也回填
            if atts:
                self.attachment_bar.add_from_dicts(atts)
            self._save_current_session()
            self.input_edit.setFocus()
            self.status_label.setText("已回填到输入框，修改后点击「发送」")

    def _on_regenerate_requested(self, bubble: MessageBubble) -> None:
        """重新生成 AI 回复：截断该回复及其后内容，复跑 ChatService.regenerate()。

        R2: 截断基准与重发文本由 UI 提供——从剩余气泡取最后一条 user 文本传入，
        并把 ui_history（剩余消息）一并交给服务层，使 app_ctx.session.history
        与 UI 截断后的状态对齐，消除两套历史分叉。
        """
        if bubble.role != "assistant":
            return
        # v1.7(F10a): 群聊消息不支持重新生成（重建 LLM 历史禁入群聊，R-J 隔离）
        if _is_group_session(self._current_group_session()):
            QMessageBox.information(self, "群聊", "群聊消息暂不支持重新生成（MVP）~")
            return
        idx = self.messages_layout.indexOf(bubble)
        if idx < 0:
            return
        # R10: 截断前先收集剩余消息（局部变量快照）
        remaining = self._collect_ui_history_before(idx)
        last_user_text = None
        for entry in reversed(remaining):
            if entry.get("role") == "user":
                last_user_text = entry.get("content", "")
                break
        if last_user_text is None:
            QMessageBox.information(
                self, "重新生成", "该回复之前没有用户消息，无法重新生成。"
            )
            return
        if self._truncate_messages_from(bubble):
            self._save_current_session()
            if self.chat_service is not None:
                self.chat_service.regenerate(
                    user_text=last_user_text, ui_history=remaining
                )
            self.status_label.setText("正在重新生成...")

    def _collect_ui_history_before(self, idx: int) -> List[dict]:
        """收集布局中 [0, idx) 的消息，格式与发送时给 AI 的 content 一致（附件带摘要）。"""
        entries: List[dict] = []
        for i in range(idx):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if not isinstance(widget, MessageBubble):
                continue
            content = widget.get_text()
            if widget.role == "user":
                atts = widget.get_attachments()
                if atts:
                    att_lines = "\n".join(
                        f"[附件] {a.get('name', '')} ({a.get('size', 0)} bytes)"
                        for a in atts
                    )
                    content = (content + "\n" if content else "") + att_lines
            entries.append({"role": widget.role, "content": content})
        return entries

    def _truncate_messages_from(self, bubble: MessageBubble) -> bool:
        """从指定气泡（含）开始截断消息列表，返回是否截断成功。"""
        if bubble is None:
            return False
        idx = self.messages_layout.indexOf(bubble)
        if idx < 0:
            return False
        # 收集要移除的 widget 索引（先取列表避免迭代过程中 index 变化）
        to_remove: List[int] = []
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, MessageBubble) and i >= idx:
                to_remove.append(i)
        for i in to_remove:
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        # 重新计算 _last_role（指向剩余最后一条气泡的角色）
        self._last_role = None
        self._last_speaker_id = None
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                self._last_role = widget.role
                self._last_speaker_id = getattr(widget, "speaker_id", None)
                break
        return True

    # ----- 标签页模式 -----
    def _on_toggle_tab_mode(self, checked: bool) -> None:
        self._tab_mode = checked
        self.session_tabs.setVisible(checked)
        if checked:
            # 首次开启：把当前会话加入开放列表
            if self._current_session_id and self._current_session_id not in self._open_tab_ids:
                self._open_tab_ids.append(self._current_session_id)
            self._sync_tabs()
        else:
            # 关闭时保留 open_tab_ids（再次开启可恢复），仅隐藏栏
            pass

    def _sync_tabs(self) -> None:
        """根据当前会话数据刷新标签页栏。"""
        if not self._tab_mode:
            return
        if self.session_manager is None:
            return
        # 清理已删除的会话
        valid_ids = {s.id for s in self.session_manager.all_sessions()}
        self._open_tab_ids = [sid for sid in self._open_tab_ids if sid in valid_ids]
        if self._current_session_id and self._current_session_id not in self._open_tab_ids:
            self._open_tab_ids.append(self._current_session_id)
        id_to_name = {s.id: s.name for s in self.session_manager.all_sessions()}
        # v1.7(F10b) 遗留收口：群聊会话 Tab 带 👥 角标（与左侧列表展示一致）
        group_ids = {s.id for s in self.session_manager.all_sessions()
                     if _is_group_session(s)}
        self.session_tabs.rebuild(self._open_tab_ids, id_to_name,
                                  self._current_session_id, group_ids)

    def _on_tab_switched(self, session_id: str) -> None:
        self._switch_to_session(session_id)

    def _on_tab_new(self) -> None:
        # 标签页 "+" 直接创建默认名「新会话」并打开为 tab
        if self.session_manager is None:
            return
        session = self.session_manager.create_session("新会话")
        if session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
        self._current_session_id = session.id
        self.title_label.setText(session.name)
        self._clear_messages()
        self._refresh_session_list()

    def _on_tab_close(self, session_id: str) -> None:
        """关闭标签 = 结束会话（不删除，仍在左侧列表中）。"""
        if session_id not in self._open_tab_ids:
            return
        # R13: 记住被关 tab 的位置——切换优先其相邻项（先左后右），而非列表末项
        closed_idx = self._open_tab_ids.index(session_id)
        self._open_tab_ids.remove(session_id)
        if session_id == self._current_session_id:
            # 切换到相邻 open tab，或最近一个未打开的会话，或新建空会话
            target: Optional[str] = None
            if self._open_tab_ids:
                pick = closed_idx - 1 if closed_idx > 0 else 0
                target = self._open_tab_ids[min(pick, len(self._open_tab_ids) - 1)]
            elif self.session_manager is not None:
                recent = self.session_manager.all_sessions()
                if recent:
                    target = next((s.id for s in recent if s.id != session_id), None)
            if target:
                self._switch_to_session(target)
                if target not in self._open_tab_ids:
                    self._open_tab_ids.append(target)
            else:
                # 没有任何会话可用：创建新空会话
                if self.session_manager is not None:
                    new_session = self.session_manager.create_session("新会话")
                    self._current_session_id = new_session.id
                    self.title_label.setText(new_session.name)
                    self._clear_messages()
                    self._open_tab_ids.append(new_session.id)
                else:
                    self._current_session_id = None
                    self.title_label.setText("聊天")
        self._sync_tabs()

    # ----- 语音输入 -----
    def _on_voice_input(self) -> None:
        backend_ok, device_ok, desc = voice_input_mod.diagnose_voice_input()
        if not backend_ok or not device_ok:
            QMessageBox.information(
                self, "语音输入", voice_input_mod.build_unavailable_message()
            )
            return
        dlg = voice_input_mod.VoiceInputDialog(self.app_ctx, self)
        if dlg.exec_() == QDialog.Accepted and dlg.transcript:
            current = self.input_edit.toPlainText().strip()
            sep = "\n" if current else ""
            self.input_edit.setPlainText(current + sep + dlg.transcript)
            self.input_edit.setFocus()
            self.status_label.setText("已插入语音识别结果")

    # ------------------------------------------------------------------
    # v1.3(P2-2): 免提对话（voice_conversation 控制器 + handsfree_bar 状态条）
    # ------------------------------------------------------------------
    def _handsfree_ctrl(self):
        """返回 app 级免提控制器单例（无则懒创建；导入失败返回 None）。"""
        app_ctx = self.app_ctx
        ctrl = getattr(app_ctx, "voice_conversation", None) if app_ctx is not None else None
        if ctrl is not None:
            return ctrl
        try:
            from gui.voice_conversation import VoiceConversationController
            ctrl = VoiceConversationController(app_ctx)
            if app_ctx is not None:
                try:
                    setattr(app_ctx, "voice_conversation", ctrl)
                except Exception:
                    logger.debug("静默降级：_handsfree_ctrl 中忽略异常", exc_info=True)
            return ctrl
        except Exception as exc:
            logger.warning("免提控制器不可用: %s", exc)
            return None

    def _init_handsfree(self) -> None:
        """接线免提：控制器信号 -> 状态条/按钮；按钮仅在 STT 后端存在时可用。"""
        bar = getattr(self, "handsfree_bar", None)
        btn = getattr(self, "handsfree_btn", None)
        ctrl = self._handsfree_ctrl()
        backend_ok = bool(voice_input_mod.stt_backend_available())
        self._hf_backend_ok = backend_ok
        if bar is not None:
            bar.setVisible(backend_ok)
        if btn is not None:
            btn.setEnabled(backend_ok)
            if not backend_ok:
                btn.setToolTip(
                    "免提暂不可用：未检测到 SpeechRecognition / PyAudio\n"
                    f"（与「{icons.text_glyph('voice', '🎤')} 语音」同依赖，安装并连接麦克风后可用）"
                )
        if ctrl is None:
            return
        try:
            ctrl.state_changed.connect(self._on_hf_state_changed)
            ctrl.notice.connect(self._on_hf_notice)
            ctrl.speech_ready.connect(self._on_hf_speech_ready)
            if bar is not None:
                bar.stop_requested.connect(self._on_hf_stop_clicked)
        except Exception as exc:
            logger.warning("免提信号接线失败: %s", exc)

    def _on_handsfree_toggled(self, checked: bool) -> None:
        """快捷操作栏「🎙 免提」开关。"""
        if checked:
            ctrl = self._handsfree_ctrl()
            if ctrl is None:
                self._set_hf_btn_checked(False)
                return
            ok = False
            try:
                ok = ctrl.start()
            except Exception as exc:
                logger.warning("免提 start 异常: %s", exc)
            if not ok:
                self._set_hf_btn_checked(False)
        else:
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.stop()
                except Exception:
                    logger.debug("静默降级：_on_handsfree_toggled 中忽略异常", exc_info=True)

    def _set_hf_btn_checked(self, checked: bool) -> None:
        btn = getattr(self, "handsfree_btn", None)
        if btn is None:
            return
        btn.blockSignals(True)
        try:
            btn.setChecked(checked)
        finally:
            btn.blockSignals(False)

    def _on_hf_stop_clicked(self) -> None:
        self._set_hf_btn_checked(False)
        ctrl = self._handsfree_ctrl()
        if ctrl is not None:
            try:
                ctrl.stop()
            except Exception:
                logger.debug("静默降级：_on_hf_stop_clicked 中忽略异常", exc_info=True)

    def _on_hf_state_changed(self, state: str) -> None:
        bar = getattr(self, "handsfree_bar", None)
        if bar is not None:
            bar.set_state(state)
        self._set_hf_btn_checked(state != "idle")

    def _on_hf_notice(self, text: str) -> None:
        bar = getattr(self, "handsfree_bar", None)
        if bar is not None:
            bar.set_notice(text)
        else:
            self.status_label.setText(text)

    def _on_hf_speech_ready(self, text: str) -> None:
        """免提识别结果：复用 UI 直插气泡 + ChatService 发送路径（不直连）。

        speech_ready 只发文本信号，由本面板走与打字发送同源的渲染/发送链，
        保证单气泡渲染入口、不产生第二套发送逻辑。
        """
        content = (text or "").strip()
        if not content:
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.notify_reply_done("")
                except Exception:
                    logger.debug("静默降级：_on_hf_speech_ready 中忽略异常", exc_info=True)
            return
        # UI 直插用户气泡（唯一 user 渲染入口之一，suppress_echo 防双泡）
        self._add_message_bubble("user", content)
        self._save_current_session()
        self._hf_pending_reply = True
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(content, [])
        self._reset_agent_trace()
        if self.chat_service is not None:
            self.chat_service.send_message(send_text, suppress_echo=True, attachments=[])
        else:
            # 无服务（异常态）：不要卡在 sending，放行回 listening
            self._hf_pending_reply = False
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.notify_reply_done("")
                except Exception:
                    logger.debug("静默降级：_on_hf_speech_ready 中忽略异常", exc_info=True)

    def _hf_resume_after_reply(self, reply_text: str) -> None:
        """语音消息的 AI 回复结束 -> 通知控制器朗读/回听。"""
        if not getattr(self, "_hf_pending_reply", False):
            return
        self._hf_pending_reply = False
        ctrl = self._handsfree_ctrl()
        if ctrl is not None:
            try:
                ctrl.notify_reply_done(reply_text or "")
            except Exception:
                logger.debug("静默降级：_hf_resume_after_reply 中忽略异常", exc_info=True)

    # ----- v1.2.2 拍照发图（配合看图）-----
    def _on_camera_capture(self) -> None:
        try:
            from gui.widgets.camera_capture import capture_photo
        except Exception:
            QMessageBox.information(self, "拍照", f"拍照功能暂不可用，可改用「{icons.text_glyph('attach', '📎')} 附件」选择图片。")
            return
        path = capture_photo(self)
        if not path:
            return  # 用户取消或不可用（内部已提示）
        ok, reason = self.attachment_bar.add_file_path(path)
        if ok:
            self.status_label.setText("已加入照片（发送时以图片发送给模型）")
        elif reason == "duplicate":
            self.status_label.setText("照片已在附件列表中")
        elif reason == "too_large":
            QMessageBox.warning(self, "图片过大", "照片超过 10MB，未添加。")
        else:
            QMessageBox.warning(self, "添加失败", "照片文件无效，未添加。")

    # ----- v1.3(P2-1): 小游戏入口（她当荷官，无数值零计分）-----
    def _open_mini_games(self) -> None:
        """打开小游戏对话框（会话隔离、不落聊天记录）。"""
        try:
            from gui.widgets.mini_games import MiniGamesDialog
        except Exception as exc:
            logger.warning("小游戏模块导入失败: %s", exc)
            QMessageBox.information(self, "小游戏", "小游戏暂不可用（模块加载失败），请稍后再试~")
            return
        dlg = MiniGamesDialog(self.app_ctx, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()

    # ----- v1.3(P2-3): 收藏高光回忆（右键 -> HighlightsManager.add）-----
    def _on_favorite_requested(self, bubble, role: str, text: str, meta: object) -> None:
        """收藏一条气泡文本为高光回忆（本地落盘，绝不上云）。"""
        try:
            from gui.pages.page_memories import add_highlight
        except Exception as exc:
            logger.warning("回忆模块导入失败: %s", exc)
            return
        session_id = self._current_session_id or ""
        new_id = add_highlight(self.app_ctx, role, text, session_id=session_id)
        if new_id:
            self.status_label.setText(f"{icons.text_glyph('auto_awesome', '✨')} 已收藏为高光回忆（「回忆」页可随时查看）")
        else:
            self.status_label.setText("收藏失败：高光回忆暂不可用")

    # ----- v1.3(P1-1): 朗读本条（TTS）-----
    def _on_bubble_read_aloud(self, bubble: Optional[MessageBubble]) -> None:
        """气泡「🔊 朗读本条 / ⏹ 停止」点击。

        - 只朗读 AI 气泡文本（用户气泡无朗读按钮）；
        - 正在朗读本气泡 -> 停止；否则全局单例开口（后开口打断前开口）。
        """
        if bubble is None:
            return
        tts = getattr(self.app_ctx, "tts", None)
        if not self._tts_usable(tts):
            return
        if bubble.is_reading() or tts.active_owner is bubble:
            try:
                tts.stop()
            except Exception:
                logger.debug("静默降级：_on_bubble_read_aloud 中忽略异常", exc_info=True)
            return
        text = (bubble.get_text() or "").strip()
        if not text:
            return
        try:
            ok = tts.speak(text, owner=bubble)
        except Exception:
            ok = False
        if not ok:
            self.status_label.setText("语音朗读暂不可用")
        # speak 已同步发 state_changed(owner)，按钮态刷新无需在此手动 set

    def _tts_usable(self, tts) -> bool:
        """TTS 可用性守卫：总开关 + 后端/语音可用；不可用给一句可读提示（不崩）。"""
        config = getattr(self.app_ctx, "config", None)
        if tts is None:
            self._show_tts_unavailable(None)
            return False
        if config is None or not bool(getattr(config, "tts_enabled", True)):
            self._show_tts_unavailable(tts)
            return False
        if not tts.available:
            self._show_tts_unavailable(tts)
            return False
        return True

    def _show_tts_unavailable(self, tts) -> None:
        reason = ""
        if tts is not None:
            try:
                reason = tts.availability_reason or ""
            except Exception:
                reason = ""
        if reason:
            msg = (f"{reason}。\n可在 Windows 语音设置中安装/启用语音包，"
                   f"或在「设置 → 语音」中检查开关。")
        else:
            msg = "语音朗读已关闭或暂不可用。\n可在「设置 → 语音」中开启。"
        QMessageBox.information(self, "语音朗读", msg)

    def _on_tts_state_changed(self, owner) -> None:
        """TTS 朗读归属变化 -> 刷新本面板所有气泡的「朗读中/待朗读」按钮态。"""
        try:
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item is None:
                    continue
                w = item.widget()
                if isinstance(w, MessageBubble):
                    w.set_read_aloud(w is owner)
        except Exception:
            logger.debug("静默降级：_on_tts_state_changed 中忽略异常", exc_info=True)
