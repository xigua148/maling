"""会话标签页栏 —— 类似浏览器 tab 的多会话切换/关闭。"""
from __future__ import annotations

from typing import Dict, List, Optional

from gui.qt_compat import (
    Qt, QWidget, QHBoxLayout, QPushButton, QTabBar, QSizePolicy, Signal,
)
from gui.utils import theme_color
from gui import icons


class SessionTabsBar(QWidget):
    """会话标签页栏：

    - 标签页显示会话标题（未命名显示「未命名」），关闭按钮（×）
    - 「+」按钮触发新会话
    - 切换标签发出 `tab_switched(session_id)`
    - 关闭标签发出 `tab_close_requested(session_id)`
    - 全部颜色由 theme_engine 提供；主题变更调用 `apply_theme()` 刷新
    """

    tab_switched = Signal(str)              # session_id
    tab_new_requested = Signal()
    tab_close_requested = Signal(str)        # session_id

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        self._ids: List[str] = []
        self._group_ids: set = set()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        self.tab_bar = QTabBar(self)
        self.tab_bar.setObjectName("sessionTabsBar")
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(False)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        self.tab_bar.tabCloseRequested.connect(self._on_close_requested)
        layout.addWidget(self.tab_bar, 1)

        self.new_btn = QPushButton("+")
        self.new_btn.setObjectName("sessionTabsNewBtn")
        self.new_btn.setFixedSize(28, 24)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip("新建会话标签")
        self.new_btn.clicked.connect(self.tab_new_requested.emit)
        layout.addWidget(self.new_btn)

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def rebuild(self, open_ids: List[str], id_to_name: Dict[str, str],
                current_id: Optional[str], group_ids: Optional[set] = None) -> None:
        """刷新标签页内容（外部管理 open_ids / current）。

        group_ids：群聊会话 id 集合（v1.7 design 要求 Tab 显示「👥」角标）。
        """
        self._ids = list(open_ids)
        self._group_ids = set(group_ids or ())
        self.tab_bar.blockSignals(True)
        try:
            while self.tab_bar.count():
                self.tab_bar.removeTab(0)
            current_index = 0
            for idx, sid in enumerate(self._ids):
                name = (id_to_name.get(sid) or "新会话")
                # 显示标题：未命名统一显示「新会话」
                if not name.strip():
                    name = "新会话"
                title = self._format_tab_title(name)
                # v1.7(F10b) 遗留收口：群聊会话 Tab 带 👥 角标（与左侧列表一致）
                if sid in self._group_ids:
                    title = f"{icons.text_glyph('people', '👥')} " + title
                self.tab_bar.addTab(title)
                if sid == current_id:
                    current_index = idx
            if self._ids:
                if 0 <= current_index < self.tab_bar.count():
                    self.tab_bar.setCurrentIndex(current_index)
                self.setVisible(True)
            else:
                self.setVisible(False)
        finally:
            self.tab_bar.blockSignals(False)
        self.apply_theme()

    def apply_theme(self) -> None:
        """按当前主题刷新标签页 QSS。"""
        bg = theme_color(self._app_ctx, "bg_card", "#FFFFFF")
        text = theme_color(self._app_ctx, "text", "#4A4A4A")
        border = theme_color(self._app_ctx, "border", "#E0E0E0")
        primary = theme_color(self._app_ctx, "primary", "#FFB6C1")
        # 对比度修复：选中页字落在 bg_card 上，原用 accent 只有
        # 3.267/2.163/6.485/3.245（三套浅色 <4.5）→ 改用「文字用」accent_text
        # （4.844/4.924/6.507/4.935）。
        # ⚠ primary 在本函数里同时是 hover 底、text_on_accent 是 hover 字 ——
        #   只换字色，不动这两者的实底配对。
        accent_text = theme_color(self._app_ctx, "accent_text", "#B45073")
        bg_light = theme_color(self._app_ctx, "bg_light", "#FFF0F3")
        text_on_accent = theme_color(self._app_ctx, "text_on_accent", "#FFFFFF")

        self.tab_bar.setStyleSheet(
            f"QTabBar#sessionTabsBar {{"
            f"  background: {bg};"
            f"}}"
            f"QTabBar::tab {{"
            f"  background: {bg_light};"
            f"  color: {text};"
            f"  border: 1px solid {border};"
            f"  border-bottom: none;"
            f"  border-top-left-radius: 8px;"
            f"  border-top-right-radius: 8px;"
            f"  padding: 4px 24px 4px 10px;"
            f"  margin-right: 2px;"
            f"  min-width: 90px;"
            f"  max-width: 200px;"
            f"}}"
            f"QTabBar::tab:selected {{"
            f"  background: {bg};"
            f"  color: {accent_text};"
            f"  border-color: {primary};"
            f"  font-weight: 600;"
            f"}}"
            f"QTabBar::tab:hover:!selected {{"
            f"  background: {primary};"
            f"  color: {text_on_accent};"
            f"}}"
            f"QTabBar::close-button {{"
            f"  image: none;"
            f"  subcontrol-position: right;"
            f"}}"
        )
        self.new_btn.setStyleSheet(
            # 对比度修复：new_btn 的字/号落在 bg_light 实底上，原用 accent 仅
            # 2.783/1.931/5.317/2.814（ui_cream 1.931，连图形阈值 3.0 都不过）→
            # 改用文字色 text（14.492/11.556/12.503/11.980）。
            f"QPushButton#sessionTabsNewBtn {{"
            f"  background: {bg_light}; color: {text};"
            f"  border: 1px solid {border}; border-radius: 6px;"
            f"  font-size: 16px; font-weight: bold;"
            f"}}"
            f"QPushButton#sessionTabsNewBtn:hover {{"
            f"  background: {primary}; color: {text_on_accent};"
            f"}}"
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _format_tab_title(name: str) -> str:
        # 标签页标题过长截断，依赖 setStyleSheet 的 max-width
        return name if len(name) <= 16 else name[:15] + "…"

    def _on_current_changed(self, index: int) -> None:
        if 0 <= index < len(self._ids):
            self.tab_switched.emit(self._ids[index])

    def _on_close_requested(self, index: int) -> None:
        if 0 <= index < len(self._ids):
            self.tab_close_requested.emit(self._ids[index])
