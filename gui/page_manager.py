"""页面路由与状态管理 —— QStackedWidget 包装。"""
from __future__ import annotations

from typing import Dict, List, Optional

from gui.qt_compat import QObject, Signal, QStackedWidget, QWidget


class PageManager(QObject):
    """页面路由与状态管理。"""

    page_changed = Signal(str)  # 参数：页面 key

    def __init__(self, page_stack: QStackedWidget, pages: Dict[str, QWidget]):
        super().__init__()
        self._stack = page_stack
        self._pages = pages
        self._history: List[str] = []
        self._current_key: Optional[str] = None

    def navigate(self, key: str) -> None:
        """切换到指定页面。"""
        if key not in self._pages:
            return
        page = self._pages[key]
        self._stack.setCurrentWidget(page)
        if self._current_key is not None and (not self._history or self._history[-1] != self._current_key):
            self._history.append(self._current_key)
        self._current_key = key
        if not self._history or self._history[-1] != key:
            self._history.append(key)
        self.page_changed.emit(key)

        # 触发页面进入生命周期钩子
        if hasattr(page, "on_enter"):
            page.on_enter()

    def back(self) -> None:
        """返回上一页。"""
        if len(self._history) >= 2:
            self._history.pop()  # 移除当前
            prev = self._history[-1]
            self._stack.setCurrentWidget(self._pages[prev])
            self._current_key = prev
            self.page_changed.emit(prev)

    def current_page_key(self) -> Optional[str]:
        return self._current_key

    def page(self, key: str) -> Optional[QWidget]:
        """按 key 取页面对象（不存在返回 ``None``），**不触发导航**。

        v2.2.5 新增：供"非导航"场景使用 —— 目前是内置酒馆的启动预热
        （要在用户没打开该页时，从外部戳一下它的 :meth:`warmup`）。
        """
        return self._pages.get(key)
