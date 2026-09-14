# -*- coding: utf-8 -*-
"""聊天面板 · 非模态浮层淡入 / 淡出。

v2.1(M-4/D-V21-02) 起自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）：
仅非模态浮层（命令 / 提及补全）做淡入 + 淡出；模态 ``exec()`` 对话框只做淡入
（阻塞语义下延迟关闭与返回值时序不可控 —— design 已裁）。``off`` 档 / 系统关闭
动画（``motion.fade`` 返回 ``None``）→ 直显直隐、直接设终态，不留半透明残影。

本 mixin **不依赖任何实例状态**，只操作传入的 ``popup``。
"""
from __future__ import annotations

import logging

from gui import motion
from gui.qt_compat import QGraphicsOpacityEffect

logger = logging.getLogger("maid_coder.gui.chat_panel.popup_fade")


class ChatPopupFadeMixin:
    """非模态浮层淡入 / 淡出（供 ChatPanelWidget 多继承）。"""

    # ==================================================================
    # v2.1(M-4/D-V21-02): 非模态浮层淡入 / 淡出
    # ------------------------------------------------------------
    # 仅非模态浮层（命令/提及补全）做淡入 + 淡出；模态 exec() 对话框只做淡入
    #（阻塞语义下延迟关闭与返回值时序不可控 —— design 已裁）。
    # off 档 / 系统关闭动画（motion.fade 返回 None）→ 直显直隐、直接设终态，
    # 不留半透明残影。
    # ==================================================================
    def _popup_open(self, popup) -> bool:
        """浮层是否处于「逻辑打开」态（淡出进行中即视为已关闭，防键盘误命中）。"""
        if popup is None:
            return False
        try:
            return bool(popup.isVisible()) and not getattr(popup, "_fading_out", False)
        except Exception:
            return False

    def _popup_opacity(self, popup) -> float:
        """浮层当前不透明度（无 effect = 默认不透明 1.0）。"""
        try:
            eff = popup.graphicsEffect()
            if isinstance(eff, QGraphicsOpacityEffect):
                return float(eff.opacity())
        except Exception:
            logger.debug("静默降级：_popup_opacity 中忽略异常", exc_info=True)
        return 1.0

    def _set_popup_opacity(self, popup, value: float) -> None:
        """直接设浮层不透明度终态（off 档收束用；无 effect 时静默跳过）。"""
        try:
            eff = popup.graphicsEffect()
            if isinstance(eff, QGraphicsOpacityEffect):
                eff.setOpacity(float(value))
        except Exception:
            logger.debug("静默降级：_set_popup_opacity 中忽略异常", exc_info=True)

    def _popup_anim_stop(self, popup) -> None:
        """停掉该浮层上一段未结束的淡入/淡出（避免两段动画抢同一 opacity 属性）。

        ``stop()`` 不触发 ``finished``，故旧的 ``on_finished``（延迟 hide）不会误跑；
        随后 ``deleteLater`` 让动画随事件循环释放，不留常驻对象（R-P）。
        """
        anim = getattr(popup, "_fade_anim", None)
        if anim is None:
            return
        try:
            anim.stop()
            anim.deleteLater()
        except Exception:
            logger.debug("静默降级：_popup_anim_stop 中忽略异常", exc_info=True)
        try:
            popup._fade_anim = None
        except Exception:
            logger.debug("静默降级：_popup_anim_stop 中忽略异常", exc_info=True)

    def _fade_show_popup(self, popup) -> None:
        """非模态浮层淡入（M-4）；off 档直显即终态。"""
        if popup is None:
            return
        already_open = self._popup_open(popup)
        self._popup_anim_stop(popup)
        try:
            if not popup.isVisible():
                popup.show()
        except Exception:
            return
        try:
            popup._fading_out = False
        except Exception:
            logger.debug("静默降级：_fade_show_popup 中忽略异常", exc_info=True)
        # 已完全显示且不透明 → 不重复播放入场（避免逐键抖动 / 无谓动画对象）
        if already_open and self._popup_opacity(popup) >= 1.0:
            return
        anim = motion.fade(popup, to=1.0)
        if anim is None:
            self._set_popup_opacity(popup, 1.0)
        else:
            try:
                popup._fade_anim = anim
            except Exception:
                logger.debug("静默降级：_fade_show_popup 中忽略异常", exc_info=True)

    def _fade_hide_popup(self, popup) -> None:
        """非模态浮层淡出（动画结束再真正 hide）；off 档直隐即终态。"""
        if popup is None:
            return
        try:
            visible = bool(popup.isVisible())
        except Exception:
            return
        if not visible:
            try:
                popup._fading_out = False
            except Exception:
                logger.debug("静默降级：_fade_hide_popup 中忽略异常", exc_info=True)
            self._set_popup_opacity(popup, 1.0)
            return
        self._popup_anim_stop(popup)
        try:
            popup._fading_out = True
        except Exception:
            logger.debug("静默降级：_fade_hide_popup 中忽略异常", exc_info=True)

        def _done() -> None:
            try:
                if getattr(popup, "_fading_out", False):
                    popup.hide()
                    popup._fading_out = False
            except Exception:
                logger.debug("静默降级：_done 中忽略异常", exc_info=True)

        anim = motion.fade(popup, to=0.0, on_finished=_done)
        if anim is None:
            try:
                popup.hide()
                popup._fading_out = False
            except Exception:
                logger.debug("静默降级：_done 中忽略异常", exc_info=True)
            self._set_popup_opacity(popup, 1.0)
        else:
            try:
                popup._fade_anim = anim
            except Exception:
                logger.debug("静默降级：_done 中忽略异常", exc_info=True)

    def _exec_modal_fade(self, dialog):
        """模态 ``exec()`` 对话框**只做淡入**，透传其返回值（design D-V21-02）。

        模态阻塞语义下延迟关闭会与返回值时序纠缠（且 ``QMessageBox`` 静态方法由
        框架内部 ``exec()`` 驱动、不可控）→ 此处**只**在 ``exec()`` 前淡入，
        **绝不**做淡出 / 延迟关闭；``off`` 档或系统关闭动画时直接原样 ``exec()``。
        """
        try:
            motion.fade(dialog, to=1.0)
        except Exception:
            logger.debug("静默降级：_exec_modal_fade 中忽略异常", exc_info=True)
        return dialog.exec_()

