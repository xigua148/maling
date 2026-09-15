"""gui/widgets/tavern/tavern_plays.py —— 酒馆「我的故事」Tab 控件（V22-08）。

设计依据：``docs/design-v22.md`` §6.1（列表项 = 章标题 + 相对时间，**无序号**）、
§6.3（只走语义键取色）、§6.4（字号只写 QSS）、§6.5（全局派生值读时取、不缓存）。

职责（只读 + 载入 / 删除两个动作，**不直接读写 store**）：用
:meth:`TavernService.list_plays` 渲染多局存档，支持**载入**
（:meth:`TavernService.load_play`）与**删除**（:meth:`TavernService.delete_play`）。

硬约束：
    * **删除必须有确认**（沿用项目既有 ``QMessageBox.question`` 方式），确认取消即
      不删；删除后**刷新列表**（由 ``plays_changed`` 信号 + 显式重刷共同保证）。
    * **当前局标记明确但不刺眼**，且**不用序号**（"正在这里" chip，非 "第 1 局"）。
    * **零字号代码**（字号只在 ``base.qss``）；**颜色不硬编码**（走 ``theme_color``）；
      **无动效**（静态列表，不涉及 ``gui/motion.py``）。

公开 API（供页面 ``PageTavern`` 组装）::

    panel = PlaysPanel(service, app_ctx=None, parent=None)
    panel.refresh()                 # 重新读取并渲染
    panel.apply_theme()             # 换肤后重刷取色
    panel.play_count()              # 当前渲染的故事数（测试用）
    panel.load_play(play_id)        # 载入某局（按钮点击同此路径）
    panel.delete_play(play_id)      # 删除某局（先确认；按钮点击同此路径）

自订阅信号：``plays_changed`` / ``play_changed`` → :meth:`refresh`。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List, Optional

from gui import icons
from gui.qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("maling.tavern.widgets.plays")

__all__ = ["PlaysPanel"]

#: 面板标题（**无序号**，Q4）。
PANEL_TITLE: str = "我的故事"

#: 当前局标记文案（明确但不刺眼；**不是**序号）。
ACTIVE_CHIP_TEXT: str = "正在这里"

#: 空态文案。
EMPTY_TEXT: str = "还没有故事，去「今夜」开一局吧。"

#: 无 service 时的中性兜底文案。
UNAVAILABLE_TEXT: str = "故事列表这会儿打不开。"

#: 删除确认框标题 / 正文模板（沿用项目既有确认口径）。
CONFIRM_TITLE: str = "删除故事"
CONFIRM_BODY_TMPL: str = "确定要删除「{title}」吗？\n这个故事就再也找不回来了。"


# ===========================================================================
# 删除确认（模块级函数，便于测试替换 / 复用既有确认方式）
# ===========================================================================

def _confirm_delete(parent: Optional[QWidget], title: str) -> bool:
    """弹既有风格的确认框；返回用户是否确认删除。

    Args:
        parent: 父控件（模态居中所用）。
        title: 待删除故事的标题（拼进确认正文）。

    Returns:
        ``True`` 表示用户点了"是"。
    """
    reply = QMessageBox.question(
        parent,
        CONFIRM_TITLE,
        CONFIRM_BODY_TMPL.format(title=title or "这个故事"),
        QMessageBox.Yes | QMessageBox.No,
    )
    return reply == QMessageBox.Yes


# ===========================================================================
# 小工具
# ===========================================================================

def _as_text(value: Any, default: str = "") -> str:
    """``str`` 守卫。"""
    return value if isinstance(value, str) else default


def _relative_time(iso: str) -> str:
    """把 ISO 时间串渲染为**相对时间**（中文；解析失败返回空串）。

    设计 §6.1：列表项 = 章标题 + 相对时间。相对时间里的数字是"时间量"，与"界面
    零序号"（Q4，指不出现局号 / 拍号）不冲突。
    """
    text = _as_text(iso).strip()
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        logger.debug("故事时间解析失败（略过相对时间）: %r", text)
        return ""
    try:
        delta = datetime.now() - moment
    except Exception:
        logger.debug("计算故事相对时间失败（忽略）", exc_info=True)
        return ""
    seconds = delta.total_seconds()
    if seconds < 0:
        return "刚刚"
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    if seconds < 86400 * 30:
        return f"{int(seconds // 86400)} 天前"
    return moment.strftime("%Y-%m-%d")


# ===========================================================================
# 主控件
# ===========================================================================

class PlaysPanel(QWidget):
    """「我的故事」Tab 控件：多局存档列表 + 载入 / 删除。"""

    def __init__(
        self,
        service: Any,
        app_ctx: Any = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """构造故事列表面板。

        Args:
            service: :class:`~gui.tavern.service.TavernService`（或同名契约的假对象）——
                **必填的第一个位置参数**（一等依赖）。
            app_ctx: 应用上下文（可选保留位；本控件取色走 ``service.theme_color``）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self._service = service
        self._app_ctx = app_ctx
        self._rows: List[QFrame] = []
        self._plays: List[dict] = []
        self._init_ui()
        self._connect_signals()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.setObjectName("tavernPlaysPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self._title_label = QLabel(f"{icons.text_glyph('history', '🕰')} {PANEL_TITLE}")
        self._title_label.setObjectName("tavernPanelTitle")
        head.addWidget(self._title_label)
        head.addStretch(1)
        root.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        root.addWidget(self._scroll, 1)

    def _connect_signals(self) -> None:
        svc = self._service
        if svc is None:
            return
        for name in ("plays_changed", "play_changed"):
            signal = getattr(svc, name, None)
            if signal is None or not hasattr(signal, "connect"):
                continue
            try:
                signal.connect(self._on_signal)
            except Exception:
                logger.debug("故事列表面板订阅 %s 失败（忽略）", name, exc_info=True)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取 service 并整体重绘（幂等）。"""
        self._apply_panel_style()
        try:
            self._plays = self._collect_plays()
        except Exception:
            logger.debug("故事列表读取失败（渲染空态）", exc_info=True)
            self._plays = []
        self._render()

    def apply_theme(self) -> None:
        """换肤后重刷取色（页面订阅 ``theme_changed`` 后调用；**不新增订阅**）。"""
        self.refresh()

    def play_count(self) -> int:
        """当前渲染的故事数（测试 / 页面断言用）。"""
        return len(self._rows)

    def load_play(self, play_id: str) -> bool:
        """载入某局（按钮点击同此路径）；随后刷新当前局标记。"""
        svc = self._service
        if svc is None or not play_id:
            return False
        try:
            ok = bool(svc.load_play(play_id))
        except Exception:
            logger.debug("载入故事失败: %s", play_id, exc_info=True)
            return False
        if ok:
            self.refresh()
        return ok

    def delete_play(self, play_id: str) -> bool:
        """删除某局：**先确认**，确认后删除并**刷新列表**。

        Returns:
            ``True`` 表示确实删除（或用户未确认时返回 ``False``）。
        """
        svc = self._service
        if svc is None or not play_id:
            return False
        title = self._title_of(play_id)
        if not _confirm_delete(self, title):
            return False
        try:
            ok = bool(svc.delete_play(play_id))
        except Exception:
            logger.debug("删除故事失败: %s", play_id, exc_info=True)
            return False
        if ok:
            # 删除后刷新列表：既靠 plays_changed 信号，也显式重刷一次兜底。
            self.refresh()
        return ok

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _collect_plays(self) -> List[dict]:
        svc = self._service
        if svc is None:
            return []
        raw = svc.list_plays()
        if not isinstance(raw, list):
            return []
        return [p for p in raw if isinstance(p, dict)]

    def _title_of(self, play_id: str) -> str:
        for play in self._plays:
            if _as_text(play.get("play_id")) == play_id:
                return _as_text(play.get("title"))
        return ""

    def _render(self) -> None:
        self._clear_rows()
        if not self._plays:
            empty = QLabel(EMPTY_TEXT if self._service is not None else UNAVAILABLE_TEXT)
            empty.setObjectName("tavernEmptyHint")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"QLabel#tavernEmptyHint {{ color: {self._color('text_hint', '#9A9A9A')};"
                " background: transparent; }"
            )
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, empty)
            return
        for play in self._plays:
            row = self._build_row(play)
            self._rows.append(row)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _build_row(self, play: dict) -> QFrame:
        play_id = _as_text(play.get("play_id"))
        is_active = bool(play.get("is_active"))

        card = QFrame()
        card.setObjectName("tavernPlayCard")
        bg_card = self._color("bg_card", "#FFFFFF")
        border = self._color("accent", "#FF6B9D") if is_active else self._color("border", "#FFE4E1")
        radius = self._color("radius_md", "10px")
        card.setStyleSheet(
            "QFrame#tavernPlayCard {"
            f" background: {bg_card}; border: 1px solid {border}; border-radius: {radius};"
            "}"
        )

        outer = QVBoxLayout(card)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        # 标题行：标题 + （当前局）标记
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        title_label = QLabel(_as_text(play.get("title")) or "（未命名故事）")
        title_label.setObjectName("tavernPlayTitle")
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"QLabel#tavernPlayTitle {{ color: {self._color('text', '#4A4A4A')}; }}"
        )
        top.addWidget(title_label, 1)
        if is_active:
            chip = QLabel(ACTIVE_CHIP_TEXT)
            chip.setObjectName("tavernActiveChip")
            accent = self._color("accent", "#FF6B9D")
            # v2.1(UI-P1)：chip 文字用 accent_text；描边仍用 accent（非文字图形）。
            accent_text = self._color("accent_text", "#B45073")
            chip.setStyleSheet(
                "QLabel#tavernActiveChip {"
                f" color: {accent_text}; border: 1px solid {accent};"
                f" border-radius: {self._color('radius_sm', '6px')}; padding: 1px 8px;"
                " background: transparent; }"
            )
            top.addWidget(chip, 0, Qt.AlignTop)
        outer.addLayout(top)

        # 元信息行：章标题 + 相对时间（**无序号**）
        chapter = _as_text(play.get("chapter_title"))
        when = _relative_time(_as_text(play.get("updated_at")))
        meta_parts = [p for p in (chapter, when) if p]
        if meta_parts:
            meta = QLabel("　".join(meta_parts))
            meta.setObjectName("tavernPlayMeta")
            meta.setWordWrap(True)
            meta.setStyleSheet(
                f"QLabel#tavernPlayMeta {{ color: {self._color('text_secondary', '#8A8A8A')}; }}"
            )
            outer.addWidget(meta)

        # 动作行：载入 / 删除
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(6)
        actions.addStretch(1)
        load_btn = QPushButton(f"{icons.text_glyph('forward', '➡')} 载入")
        load_btn.setObjectName("tavernPlayLoad")
        load_btn.setCursor(Qt.PointingHandCursor)
        load_btn.clicked.connect(lambda _checked=False, pid=play_id: self.load_play(pid))
        actions.addWidget(load_btn)

        delete_btn = QPushButton(f"{icons.text_glyph('delete', '🗑')} 删除")
        delete_btn.setObjectName("tavernPlayDelete")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(lambda _checked=False, pid=play_id: self.delete_play(pid))
        actions.addWidget(delete_btn)
        outer.addLayout(actions)

        load_btn.setStyleSheet(
            "QPushButton#tavernPlayLoad {"
            f" color: {self._color('primary_dark', '#FF6B9D')};"
            f" border: 1px solid {self._color('divider', '#EFE0E2')};"
            f" border-radius: {self._color('radius_sm', '6px')}; padding: 2px 10px;"
            " background: transparent; }"
        )
        delete_btn.setStyleSheet(
            "QPushButton#tavernPlayDelete {"
            f" color: {self._color('text_secondary', '#8A8A8A')};"
            f" border: 1px solid {self._color('divider', '#EFE0E2')};"
            f" border-radius: {self._color('radius_sm', '6px')}; padding: 2px 10px;"
            " background: transparent; }"
        )
        return card

    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------
    def _color(self, key: str, fallback: str) -> str:
        """统一取色入口（**读时现取**，绝不缓存；见 §6.5）。"""
        svc = self._service
        if svc is None:
            return fallback
        try:
            return svc.theme_color(key, fallback)
        except Exception:
            logger.debug("故事列表取色失败，用兜底色 key=%s", key, exc_info=True)
            return fallback

    def _apply_panel_style(self) -> None:
        self.setStyleSheet("QWidget#tavernPlaysPanel { background: transparent; }")
        self._title_label.setStyleSheet(
            f"QLabel#tavernPanelTitle {{ color: {self._color('text', '#4A4A4A')}; }}"
        )

    def _on_signal(self, *_args: Any) -> None:
        """信号槽：载荷不拘，一律整体重绘。"""
        self.refresh()

    def _clear_rows(self) -> None:
        """清空故事行（``setParent(None)`` 立刻脱离，避免延迟删除残留）。"""
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
