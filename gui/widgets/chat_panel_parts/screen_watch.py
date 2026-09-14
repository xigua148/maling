# -*- coding: utf-8 -*-
"""聊天面板 · 看屏（ScreenWatch）+ GUI 单步操作（Computer Use）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。

覆盖：看屏服务初始化与 UI 状态同步、看屏按钮 / chip 事件、区域截图直接问、
单步操作路由（``_route_computer_request``）。``ScreenWatchService`` /
``ComputerUseController`` 均在方法内**惰性导入**，本模块无重型模块级依赖。

依赖宿主控件（ChatPanelWidget）的实例状态，如 ``_watch_svc``、
``_screen_pending_token``、``_screenshot_active`` 及各看屏控件。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui import icons
from gui.qt_compat import QMessageBox

logger = logging.getLogger("maid_coder.gui.chat_panel.screen_watch")


class ChatScreenWatchMixin:
    """看屏 + GUI 单步操作（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # v1.4(B1b/B2): 看屏 + GUI 单步操作（ScreenWatchService / ComputerUseController）
    # ==================================================================
    def _init_screen_watch(self) -> None:
        """看屏接线：取 app 级服务、订阅事件、连 chip 按钮；cfg 曾开启 → 直接恢复。

        单例语义：与 V-1.4-0 main._mount_v14_b_screen 共用 get_screen_watch_service，
        不会重复创建；此处只读 config 默认值（getattr 容错）。
        """
        try:
            from gui.screen_watch import get_screen_watch_service
            svc = get_screen_watch_service(self.app_ctx)
        except Exception as exc:
            logger.warning("看屏服务初始化失败: %s", exc)
            svc = None
        self._watch_svc = svc
        self._watch_svc_ready = svc is not None
        if svc is None:
            btn = getattr(self, "watch_btn", None)
            if btn is not None:
                btn.setEnabled(False)
                btn.setToolTip("看屏组件初始化失败，暂不可用")
            return
        try:
            svc.watch_state_changed.connect(self._on_watch_state_changed)
            svc.frame_captured.connect(self._on_watch_frame_captured)
            svc.screen_changed.connect(self._on_watch_screen_changed)
            svc.stats_changed.connect(self._on_watch_stats_changed)
            svc.auto_paused.connect(self._on_watch_auto_paused)
            svc.paused_changed.connect(self._on_watch_paused_changed)
            svc.high_value_notice.connect(self._on_watch_high_value_notice)
            svc.notice.connect(self._on_watch_notice)
        except Exception as exc:
            logger.warning("看屏信号订阅失败: %s", exc)
        bar = getattr(self, "screen_watch_bar", None)
        if bar is not None:
            try:
                bar.peek_requested.connect(self._on_watch_peek)
                bar.stop_requested.connect(self._on_watch_close)
                bar.resume_requested.connect(self._on_watch_resume)
                bar.ask_screen_toggled.connect(self._on_watch_ask_toggled)
            except Exception as exc:
                logger.warning("看屏 chip 接线失败: %s", exc)
        # 启动默认态：用户此前显式开启并持久化 → 恢复运行（已确认过成本，不再重复弹窗）
        try:
            from gui.screen_watch import read_sw
            enabled = bool(read_sw(getattr(self.app_ctx, "config", None), "enabled", False))
            if enabled:
                svc.start()
        except Exception as exc:
            logger.warning("看屏默认态恢复失败: %s", exc)
        self._sync_watch_ui()

    def _watch_svc(self):
        return self._watch_svc

    # ----- 看屏 UI 状态同步 -----
    def _sync_watch_ui(self) -> None:
        """按钮 checked 态 + chip 显隐/状态与 ScreenWatchService 对齐。"""
        svc = self._watch_svc
        btn = getattr(self, "watch_btn", None)
        if btn is not None:
            if svc is None:
                btn.setEnabled(False)
            else:
                on = svc.is_running() or svc.is_paused()
                if btn.isChecked() != on:
                    btn.blockSignals(True)
                    try:
                        btn.setChecked(on)
                    finally:
                        btn.blockSignals(False)
        bar = getattr(self, "screen_watch_bar", None)
        if bar is None:
            return
        if svc is None:
            bar.setVisible(False)
            return
        if svc.is_running():
            bar.setVisible(True)
            bar.set_state("running")
            bar.set_stats(svc.frame_count(), svc.token_total())
        elif svc.is_paused():
            bar.setVisible(True)
            bar.set_state("paused")
            bar.set_stats(svc.frame_count(), svc.token_total())
        else:
            bar.setVisible(False)

    def _on_watch_state_changed(self, running: bool) -> None:
        self._sync_watch_ui()

    def _on_watch_paused_changed(self, paused: bool) -> None:
        self._sync_watch_ui()

    def _on_watch_stats_changed(self) -> None:
        svc = self._watch_svc
        bar = getattr(self, "screen_watch_bar", None)
        if svc is None or bar is None or not bar.isVisible():
            return
        bar.set_stats(svc.frame_count(), svc.token_total())

    def _on_watch_frame_captured(self, _uri: str, _meta_json: str) -> None:
        pass  # 最近帧由服务内部维护；此处保留扩展位

    def _on_watch_screen_changed(self, _ratio: float) -> None:
        pass  # 显著变化事件（分类/提示由服务处理；UI 不逐帧刷）

    def _on_watch_notice(self, text: str) -> None:
        bar = getattr(self, "screen_watch_bar", None)
        if bar is not None:
            bar.set_notice(text)

    def _on_watch_auto_paused(self, limit: int) -> None:
        self._sync_watch_ui()
        try:
            if self.chat_service is not None:
                self.chat_service.screen_bubble(
                    f"👀 看屏已自动暂停：本会话已分析到 {limit} 帧（成本护栏）。"
                    "想继续看就点 chip 里的「▶ 续开」，或在设置里调高单会话帧上限。",
                    "screen_pause",
                )
        except Exception:
            logger.debug("静默降级：_on_watch_auto_paused 中忽略异常", exc_info=True)

    def _on_watch_high_value_notice(self, text: str) -> None:
        """高价值主动提示：仅对话气泡（chat_service.screen_bubble），不 toast（R-C）。"""
        if not (text or "").strip():
            return
        try:
            if self.chat_service is not None:
                self.chat_service.screen_bubble(
                    "👀 " + text.strip(), "screen_notice")
        except Exception as exc:
            logger.warning("高价值提示投递失败: %s", exc)

    # ----- 看屏按钮 / chip 事件 -----
    def _on_watch_toggled(self, checked: bool) -> None:
        svc = self._watch_svc
        if svc is None:
            self._set_watch_checked(False)
            return
        if checked:
            if not self._confirm_watch_start():
                self._set_watch_checked(False)
                return
            try:
                from gui.screen_watch import write_sw
                write_sw(getattr(self.app_ctx, "config", None), "enabled", True)
            except Exception:
                logger.debug("静默降级：_on_watch_toggled 中忽略异常", exc_info=True)
            svc.start()
        else:
            svc.stop()
            try:
                from gui.screen_watch import write_sw
                write_sw(getattr(self.app_ctx, "config", None), "enabled", False)
            except Exception:
                logger.debug("静默降级：_on_watch_toggled 中忽略异常", exc_info=True)
        self._sync_watch_ui()

    def _set_watch_checked(self, checked: bool) -> None:
        btn = getattr(self, "watch_btn", None)
        if btn is not None:
            btn.blockSignals(True)
            try:
                btn.setChecked(checked)
            finally:
                btn.blockSignals(False)

    def _confirm_watch_start(self) -> bool:
        """开启看屏的成本确认弹窗（含单会话帧上限自动暂停说明 + 视觉模型提示）。"""
        box = QMessageBox(self)
        box.setWindowTitle("开启持续看屏")
        box.setIcon(QMessageBox.Question)
        box.setText("开启后，码铃会周期性看一下你的屏幕：回答「这个报错为什么」、按当前屏提问，并在检测到报错/异常时主动提醒。")
        lines = [
            "· 会额外消耗 token 与额度（chip 里会显示已分析帧数与约消耗）",
            "· 单会话帧上限（默认 200 帧）到达会自动暂停，可随时续开",
            "· 帧只在内存里当轮即弃：不落盘、不进历史、不做行为统计",
            "· 随时可一键关闭，关闭即停采并丢弃内存帧",
        ]
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            lines.append("\n" + icons.text_glyph('warning', '⚠️') + " " + hint)
        box.setInformativeText("\n".join(lines))
        ok_btn = box.addButton("继续开启", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is ok_btn

    def _on_watch_close(self) -> None:
        """chip ✕ 关闭：停采弃帧 + 持久化关 + 按钮回弹。"""
        svc = self._watch_svc
        if svc is not None:
            svc.stop()
        try:
            from gui.screen_watch import write_sw
            write_sw(getattr(self.app_ctx, "config", None), "enabled", False)
        except Exception:
            logger.debug("静默降级：_on_watch_close 中忽略异常", exc_info=True)
        self._set_watch_checked(False)
        self._sync_watch_ui()

    def _on_watch_resume(self) -> None:
        """chip ▶ 续开：重置会话计数（start 内部处理）并重启。"""
        svc = self._watch_svc
        if svc is None:
            return
        svc.start()
        self._sync_watch_ui()

    def _on_watch_ask_toggled(self, pending: bool) -> None:
        if pending:
            self.status_label.setText(f"{icons.text_glyph('search', '🔍')} 已点亮按屏提问：下一条消息将带上当前屏幕")
        else:
            self.status_label.setText("")

    def _on_watch_peek(self) -> None:
        """chip「📷 看一帧」：即时采集 → 送视觉 → 结果以对话气泡呈现（非 toast）。"""
        svc = self._watch_svc
        if svc is None or not svc.is_running():
            return
        if self.chat_service is None:
            return
        if self.chat_service.is_busy():
            try:
                self.chat_service.screen_bubble("码铃还在说上一条呢，等它说完再「看一帧」~", "screen_peek")
            except Exception:
                logger.debug("静默降级：_on_watch_peek 中忽略异常", exc_info=True)
            return
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            try:
                self.chat_service.screen_bubble(hint, "screen_peek")
            except Exception:
                logger.debug("静默降级：_on_watch_peek 中忽略异常", exc_info=True)
            return
        att = self._attach_screen_frame()
        if not att:
            self.status_label.setText("取帧失败，稍后再试")
            return
        self._screen_pending_token = True
        text = "📷 看一眼当前屏幕：用一两句话告诉我有什么值得注意或需要帮忙的地方吧~"
        self._add_message_bubble("user", text, attachments=[att])
        self._save_current_session()
        prompt = "这是当前屏幕的一张截图。请用一两句中文简要说说：有什么值得注意的地方、异常或需要帮忙的地方吗？"
        self.chat_service.send_message(prompt, suppress_echo=True, attachments=[att])

    def _attach_screen_frame(self) -> Optional[dict]:
        """取一张新鲜内存帧作为附件条目（uri 通道，不落盘）；送前计一帧分析。"""
        svc = self._watch_svc
        if svc is None or not svc.is_running():
            return None
        try:
            uri = svc.capture_now() or svc.latest_frame_data_uri()
        except Exception:
            uri = None
        if not uri:
            return None
        try:
            svc.note_analysis(0)
        except Exception:
            logger.debug("静默降级：_attach_screen_frame 中忽略异常", exc_info=True)
        return {"name": "当前屏幕", "ext": ".jpg", "size": len(uri), "uri": uri}

    def _screen_intent_hit(self, text: str) -> bool:
        """被动解释启发式：文本含指向当前屏的意图词才附最近帧（非命中不附，防烧 token）。"""
        if not text:
            return False
        keywords = ("屏幕", "报错", "错误", "崩溃", "弹窗", "界面", "页面", "窗口",
                    "怎么点", "点一下", "看一下", "看下", "哪里", "这个", "那个")
        return any(k in text for k in keywords)

    def _settle_screen_round_tokens(self, usage: dict) -> None:
        """本轮回传了屏幕帧 → 流结束把 usage.total_tokens 补记进看屏 chip。"""
        if not getattr(self, "_screen_pending_token", False):
            return
        self._screen_pending_token = False
        svc = self._watch_svc
        if svc is None:
            return
        try:
            tokens = int((usage or {}).get("total_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        if tokens > 0:
            try:
                svc.note_tokens(tokens)
            except Exception:
                logger.debug("静默降级：_settle_screen_round_tokens 中忽略异常", exc_info=True)

    # ----- v1.4(B2): 单步操作路由 -----
    def _route_computer_request(self, text: str) -> None:
        """「🖱 操作」点亮后的下一条消息：渲染用户气泡 + 路由给 ComputerUseController。"""
        self.input_edit.clear()
        self._add_message_bubble("user", "🖱 " + text)
        self.attachment_bar.clear()
        self._save_current_session()
        # 单步语义：路由即熄（每次只处理一条）
        btn = getattr(self, "computer_btn", None)
        if btn is not None and btn.isChecked():
            btn.blockSignals(True)
            try:
                btn.setChecked(False)
            finally:
                btn.blockSignals(False)
        try:
            from gui.computer_use import get_computer_use_controller
            ctrl = get_computer_use_controller(self.app_ctx)
        except Exception as exc:
            logger.warning("单步操作控制器不可用: %s", exc)
            ctrl = None
        if ctrl is None:
            if self.chat_service is not None:
                try:
                    self.chat_service.screen_bubble("单步操作组件暂不可用，请稍后再试。", "screen_action")
                except Exception:
                    logger.debug("静默降级：_route_computer_request 中忽略异常", exc_info=True)
            return
        self.status_label.setText("码铃正在看屏幕…")
        ctrl.handle_request(text, parent_widget=self)

    # ----- v1.3(P1-2): 区域截图直接问（聊天工具按钮 / 热键 / 托盘共用入口）-----
    def capture_screenshot(self) -> None:
        """划屏选区截图 -> 附件条 + 输入框预填引导，**不自动发送**。

        供「🖼 截图」按钮、P1-3 热键 Ctrl+Alt+S、P2-4 托盘动作复用；
        隐私：仅在用户显式操作下截图；选完由用户确认/改字后走既有发送链路。
        """
        if self._screenshot_active:
            return
        self._screenshot_active = True
        try:
            # 主窗可能处于隐藏（热键触发），先呼出并切到聊天页，保证选区后可见可发
            mw = getattr(self.app_ctx, "main_window", None) or self.window()
            if mw is not None:
                try:
                    if not mw.isVisible():
                        mw.showNormal()
                        mw.raise_()
                        mw.activateWindow()
                except Exception:
                    logger.debug("静默降级：capture_screenshot 中忽略异常", exc_info=True)
                try:
                    pm = getattr(self.app_ctx, "page_manager", None)
                    if pm is not None and hasattr(pm, "navigate"):
                        pm.navigate("chat")
                except Exception:
                    logger.debug("静默降级：capture_screenshot 中忽略异常", exc_info=True)
            try:
                from gui.widgets.screen_capture import capture_region
            except Exception:
                QMessageBox.information(
                    self, "截图",
                    f"截图功能暂不可用，可改用「{icons.text_glyph('attach', '📎')} 附件」选择一张已有图片。"
                )
                return
            path = capture_region(self)
            if not path:
                return  # 用户取消/不可用（内部已提示）
            ok, reason = self.attachment_bar.add_file_path(path)
            if not ok:
                if reason == "duplicate":
                    self.status_label.setText("截图已在附件列表中")
                elif reason == "too_large":
                    QMessageBox.warning(self, "图片过大", "截图超过 10MB，未添加。")
                else:
                    QMessageBox.warning(self, "添加失败", "截图文件无效，未添加。")
                return
            # 不自动发送：进附件条 + 预填引导文字，用户确认/改字后自行发送
            self.input_edit.setPlainText("帮我看看这张截图…")
            self.input_edit.setFocus()
            self.status_label.setText("截图已加入附件，可修改文字后发送（不会自动发送）")
        finally:
            self._screenshot_active = False

