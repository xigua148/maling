"""ChatSession 的 GUI 适配包装 —— 零侵入，将历史变更转为 Qt Signal。"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import QObject, Signal


class GuiChatSession(QObject):
    """将 CLI ChatSession 的变更转换为 Qt Signal，供 GUI 组件订阅。"""

    message_added = Signal(str, str)      # (role, content)
    history_cleared = Signal()
    system_updated = Signal(str)          # (new_system_prompt)
    mode_changed = Signal(str, bool)      # (mode_name, state)

    def __init__(self, session):
        super().__init__()
        self._session = session
        self._orig_add_message = None
        self._orig_clear = None
        self._orig_toggle_deep = None
        self._orig_toggle_coding = None
        self._patch_add_message()
        self._patch_clear()
        self._patch_toggle_modes()

    def _patch_add_message(self) -> None:
        """Monkey-patch add_message 以拦截消息添加。"""
        self._orig_add_message = self._session.add_message

        def _wrapped(role: str, content: Optional[str] = None, **kwargs) -> None:
            self._orig_add_message(role, content, **kwargs)
            self.message_added.emit(role, content or "")

        self._session.add_message = _wrapped

    def _patch_clear(self) -> None:
        """Monkey-patch clear 以拦截历史清空。"""
        self._orig_clear = self._session.clear

        def _wrapped() -> None:
            self._orig_clear()
            self.history_cleared.emit()

        self._session.clear = _wrapped

    def _patch_toggle_modes(self) -> None:
        """Patch 模式切换方法以发射信号。"""
        self._orig_toggle_deep = self._session.toggle_deep

        def _wrapped_deep() -> bool:
            result = self._orig_toggle_deep()
            self.mode_changed.emit("deep", result)
            return result

        self._session.toggle_deep = _wrapped_deep

        self._orig_toggle_coding = self._session.toggle_coding

        def _wrapped_code() -> bool:
            result = self._orig_toggle_coding()
            self.mode_changed.emit("coding", result)
            return result

        self._session.toggle_coding = _wrapped_code

    def restore(self) -> None:
        """还原所有被 patch 的方法到原始引用。"""
        if self._orig_add_message is not None:
            self._session.add_message = self._orig_add_message
        if self._orig_clear is not None:
            self._session.clear = self._orig_clear
        if self._orig_toggle_deep is not None:
            self._session.toggle_deep = self._orig_toggle_deep
        if self._orig_toggle_coding is not None:
            self._session.toggle_coding = self._orig_toggle_coding

    @property
    def inner(self):
        """返回原始 ChatSession 实例。"""
        return self._session

    def __getattr__(self, name: str):
        """透传所有未定义属性到原始 session。"""
        return getattr(self._session, name)
