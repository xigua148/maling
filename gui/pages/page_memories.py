"""gui/pages/page_memories.py —— v1.3 P2-3 高光回忆册页

设计（docs/design-v13.md D-V13-06 / PRD P2-3）：
  - 时间倒序回忆卡 + 「取消收藏 / 清空」收藏管理；文本 ≤500 字截断由 HighlightsManager 保证。
  - 底部一行**中性相伴信息**（相伴总天数 / 首次相见日，读 companion；无数值墙/统计卡）。
  - 红线：本地存储绝不上云；无打卡/断签/连续收藏 N 天/成就；本页不显示高光条目计数。
  - 取色一律 theme_color(app_ctx, key, fallback)，禁裸硬编码色。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

from gui import icons
from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, Qt, QMessageBox, QSizePolicy,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# v2.1(V21-12/D-V21-06): 回忆册图标统一 —— 只记「图标名 + 尺寸 + theme_color 取色」，
# 字体不可用时回落原 emoji。
_MEM_ICON_SIZE = 14


def _vector_icon(app_ctx, name: str, size: int, color):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落 emoji）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


def get_highlights_manager(app_ctx):
    """app 级 HighlightsManager 单例（lazy 挂 app_ctx.highlights；失败返回 None 不崩）。"""
    mgr = getattr(app_ctx, "highlights", None)
    if mgr is not None:
        return mgr
    try:
        from highlights import HighlightsManager
        mgr = HighlightsManager()
    except Exception as exc:
        logger.warning("HighlightsManager 初始化失败: %s", exc)
        mgr = None
    try:
        app_ctx.highlights = mgr
    except Exception:
        pass
    return mgr


def add_highlight(app_ctx, role: str, text: str, session_id: str = "") -> Optional[str]:
    """收藏高光回忆（chat_panel/chat_window 气泡右键统一入口）。

    返回新 id；manager 缺失/空文本时返回 None（静默，不打扰）。
    """
    if not text or not str(text).strip():
        return None
    mgr = get_highlights_manager(app_ctx)
    if mgr is None:
        return None
    mood = "normal"
    companion = getattr(app_ctx, "companion", None)
    if companion is not None:
        try:
            mood = companion.mood or "normal"
        except Exception:
            mood = "normal"
    return mgr.add(role=role, text=text, session_id=session_id, mood=mood)


_MOOD_CHARS = {
    "normal": "😌", "happy": "😊", "concerned": "😢",
    "shy": "😳", "tired": "🥱",
}
_MOOD_LABELS = {
    "normal": "平静", "happy": "开心", "concerned": "挂念",
    "shy": "害羞", "tired": "困倦",
}


def _companion_info_line(app_ctx) -> str:
    """底部中性相伴信息行（读 companion；无数值墙，只一句）。"""
    companion = getattr(app_ctx, "companion", None)
    if companion is None:
        return "码铃在这里陪着主人~"
    try:
        streak = companion.streak_info() or {}
    except Exception:
        streak = {}
    first_seen = str(streak.get("first_seen_date") or "").strip()
    days = 0
    if first_seen:
        try:
            days = max(0, (datetime.now() - datetime.strptime(first_seen, "%Y-%m-%d")).days)
        except (TypeError, ValueError):
            days = 0
    parts = []
    if days:
        parts.append(f"相伴 {days} 天")
    meet = ""
    try:
        ann = companion.get_anniversaries()
        meet = str(ann.get("first_meet") or "").strip()
    except Exception:
        meet = ""
    if meet:
        try:
            d = datetime.strptime(meet, "%m-%d")
            parts.append(f"初见于 {d.month} 月 {d.day} 日")
        except (TypeError, ValueError):
            pass
    elif first_seen:
        try:
            d = datetime.strptime(first_seen, "%Y-%m-%d")
            parts.append(f"初见于 {d.year} 年 {d.month} 月 {d.day} 日")
        except (TypeError, ValueError):
            pass
    if not parts:
        return "码铃在这里陪着主人~"
    return " · ".join(parts)


class _MemoryCard(QFrame):
    """单条回忆卡：角色/日期/心情 + 文本 + 取消收藏按钮。"""

    def __init__(self, item: dict, on_remove, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self.item = item
        self._on_remove = on_remove
        self.setObjectName("memoryCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        role = "主人" if item.get("role") == "user" else "码铃"
        mood = item.get("mood") or "normal"
        mood_char = _MOOD_CHARS.get(mood, "😌")
        mood_label = _MOOD_LABELS.get(mood, "平静")
        at = str(item.get("at") or "")
        try:
            dt = datetime.fromisoformat(at)
            date_txt = dt.strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            date_txt = str(item.get("date") or "")
        mic = _vector_icon(app_ctx, "emotion", _MEM_ICON_SIZE,
                           theme_color(app_ctx, "text_secondary", "#8A8A8A"))
        if mic is not None:
            mood_icon = QLabel()
            mood_icon.setObjectName("memoryCardMood")
            mood_icon.setFixedSize(_MEM_ICON_SIZE, _MEM_ICON_SIZE)
            mood_icon.setPixmap(mic.pixmap(_MEM_ICON_SIZE, _MEM_ICON_SIZE))
            head.addWidget(mood_icon)
            role_text = f"{role} · {date_txt} · {mood_label}"
        else:
            role_text = f"{role} · {date_txt} · {mood_char} {mood_label}"
        role_lab = QLabel(role_text)
        role_lab.setObjectName("memoryCardHead")
        head.addWidget(role_lab)
        head.addStretch()

        remove_btn = QPushButton("取消收藏")
        remove_btn.setObjectName("memoryRemoveBtn")
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.clicked.connect(self._remove)
        head.addWidget(remove_btn)
        lay.addLayout(head)

        text_lab = QLabel(str(item.get("text") or ""))
        text_lab.setObjectName("memoryCardText")
        text_lab.setWordWrap(True)
        text_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(text_lab)

        self._apply_style()

    def _remove(self) -> None:
        if self._on_remove is not None:
            self._on_remove(self)

    def _apply_style(self) -> None:
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        border = theme_color(self.app_ctx, "divider", "#EFE0E2")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        self.setStyleSheet(
            f"QFrame#memoryCard {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 10px; }}"
        )
        head = self.findChild(QLabel, "memoryCardHead")
        if head is not None:
            head.setStyleSheet(
                f"QLabel#memoryCardHead {{ color: {secondary}; font-size: 11px; }}"
            )
        text_lab = self.findChild(QLabel, "memoryCardText")
        if text_lab is not None:
            text_lab.setStyleSheet(
                f"QLabel#memoryCardText {{ color: {text}; font-size: 13px;"
                f" background: transparent; }}"
            )
        btn = self.findChild(QPushButton, "memoryRemoveBtn")
        if btn is not None:
            btn.setStyleSheet(
                f"QPushButton#memoryRemoveBtn {{ background: transparent;"
                f" color: {accent}; border: 1px solid {border}; border-radius: 6px;"
                f" font-size: 11px; padding: 3px 10px; }}"
                f"QPushButton#memoryRemoveBtn:hover {{ background: {border}; }}"
            )


class PageMemories(QWidget):
    """回忆页：时间倒序卡片 + 收藏管理 + 中性相伴信息行。"""

    def __init__(self, app_context, title: str = "回忆", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._list_widgets: List[QWidget] = []   # 追踪本次插入的空态/卡片，refresh 统一清理
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)

        head_row = QHBoxLayout()
        title = QLabel("高光回忆")
        title.setObjectName("pageTitle")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        head_row.addWidget(title)
        head_row.addStretch()

        self.clear_btn = QPushButton("🗑 清空回忆")
        self.clear_btn.setObjectName("memoryClearBtn")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setToolTip("清空所有收藏的高光回忆（不可恢复）")
        self.clear_btn.clicked.connect(self._on_clear)
        cic = _vector_icon(self.app_ctx, "delete", _MEM_ICON_SIZE,
                           theme_color(self.app_ctx, "text_secondary", "#8A8A8A"))
        if cic is not None:
            self.clear_btn.setIcon(cic)
            self.clear_btn.setText("清空回忆")
        head_row.addWidget(self.clear_btn)
        outer.addLayout(head_row)

        sub = QLabel(
            f"聊天气泡上点右键 → 「{icons.text_glyph('auto_awesome', '✨')} 收藏为高光回忆」，"
            "重要时刻就能在这里回味~")
        sub.setObjectName("memorySubHint")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # 卡片滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area = scroll

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(2, 4, 2, 4)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_host)
        outer.addWidget(scroll, 1)

        # 中性相伴信息行（无数值墙）
        self.info_label = QLabel("")
        self.info_label.setObjectName("memoryInfoLine")
        self.info_label.setWordWrap(True)
        outer.addWidget(self.info_label)

        self.refresh()

    def on_enter(self) -> None:
        """每次进入回忆页都重读（新收藏即时出现）。"""
        self.refresh()

    def refresh(self) -> None:
        """重建回忆卡片列表（时间倒序由 manager.all() 保证）。"""
        # 清掉旧卡片/空态占位
        for w in self._list_widgets:
            self.list_layout.removeWidget(w)
            w.deleteLater()
        self._list_widgets = []
        mgr = get_highlights_manager(self.app_ctx)
        items: List[dict] = []
        if mgr is not None:
            try:
                items = mgr.all()
            except Exception as exc:
                logger.warning("读取高光回忆失败: %s", exc)
                items = []
        if not items:
            empty = QLabel(
                f"还没有收藏过回忆。\n在聊天消息气泡上点右键 → "
                f"「{icons.text_glyph('auto_awesome', '✨')} 收藏为高光回忆」即可收藏~")
            empty.setObjectName("memoryEmpty")
            empty.setAlignment(Qt.AlignCenter)
            empty.setWordWrap(True)
            idx = max(0, self.list_layout.count() - 1)
            self.list_layout.insertWidget(idx, empty)
            self._list_widgets.append(empty)
        else:
            for item in items:
                card = _MemoryCard(item, self._remove_card, self.app_ctx)
                idx = max(0, self.list_layout.count() - 1)
                self.list_layout.insertWidget(idx, card)
                self._list_widgets.append(card)
        # 提示行 + 中性相伴信息
        info = _companion_info_line(self.app_ctx)
        self.info_label.setText(info)
        self._apply_style()

    def _remove_card(self, card: _MemoryCard) -> None:
        mgr = get_highlights_manager(self.app_ctx)
        if mgr is None:
            return
        try:
            mgr.remove(card.item.get("id", ""))
        except Exception as exc:
            logger.warning("取消收藏失败: %s", exc)
        self.refresh()

    def _on_clear(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("清空回忆")
        box.setIcon(QMessageBox.Question)
        box.setText("要清空所有高光回忆吗？\n此操作不可恢复。")
        yes = box.addButton("清空", QMessageBox.DestructiveRole)
        box.addButton("再想想", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is not yes:
            return
        mgr = get_highlights_manager(self.app_ctx)
        if mgr is not None:
            try:
                mgr.clear()
            except Exception as exc:
                logger.warning("清空回忆失败: %s", exc)
        self.refresh()

    def _apply_style(self) -> None:
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        self.info_label.setStyleSheet(
            f"QLabel#memoryInfoLine {{ color: {secondary}; font-size: 12px;"
            f" border-top: 1px solid {divider}; padding-top: 10px; }}"
        )
        for nm in ("memorySubHint", "memoryEmpty"):
            lab = self.findChild(QLabel, nm)
            if lab is not None:
                lab.setStyleSheet(f"QLabel#{nm} {{ color: {secondary}; font-size: 12px; }}")
        self.clear_btn.setStyleSheet(
            f"QPushButton#memoryClearBtn {{ background: transparent; color: {secondary};"
            f" border: 1px solid {divider}; border-radius: 8px; font-size: 12px;"
            f" padding: 6px 14px; }}"
            f"QPushButton#memoryClearBtn:hover {{ color: {accent}; border-color: {accent}; }}"
        )
