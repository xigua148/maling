"""gui/widgets/tavern/tavern_worldbook.py —— 酒馆「世界书」Tab 控件（V22-08，只读展示）。

设计依据：``docs/design-v22.md`` §6（Tab 结构 / 信息层级 / 语义键纪律）、
§6.3（只走语义键取色）、§6.4（字号只写 QSS）、§6.5（全局派生值读时取、不缓存）。

职责（**只读**，不触碰 ``gui/tavern/**`` 冻结服务层、不直接读写 ``store``）：把
:meth:`TavernService.worldbook_entries` 的全部条目列出来，并标出**本拍命中**
（:meth:`TavernService.worldbook_hits`）；同时把条目里**真实存在**的触发信息
（``keys`` / ``secondary_keys`` / ``selective_logic`` / ``constant``）如实展示，
让玩家看得懂"为什么这一回合出现了这些内容"。

⚠️ 文案语义铁律：``worldbook_changed`` / ``worldbook_hits`` 的语义是
**"叙述前快照"**，即"本拍**选中**"的世界书条目，**不是**叙述之后**新增**出来的。
故本控件一切命中文案只用"本拍选中"，**严禁**出现"新增 / 获得 / 解锁 / 得到"等误导词。

审美与纪律：
    * **零字号代码**：任何 ``setPointSize`` / ``setPixelSize`` 都不允许；字号只在
      ``gui/themes/base.qss`` 的 ``#tavern*`` id 规则里给（见 §6.4）。
    * **颜色不硬编码**：一律经 :meth:`_color` → ``service.theme_color`` 现取现用，
      **不在 ``__init__`` 缓存**（§6.5）；``apply_theme()`` 由页面在换肤后调用重刷。
    * **无动效**：本控件是静态列表，不创建任何动画对象（``gui/motion.py`` 不涉及）。

公开 API（供页面 ``PageTavern`` 组装）::

    panel = WorldbookPanel(service, app_ctx=None, parent=None)

注意：``service`` 是**必填的第一个位置参数**（一等依赖：信号 / 查询 / 取色都从它来），
``app_ctx`` 仅作可选保留位。
    panel.refresh()        # 重新读取并渲染（页面 on_enter / 收到信号后调用）
    panel.apply_theme()    # 换肤后重刷取色（页面订阅 theme_changed 后调用）
    panel.entry_count()    # 当前渲染的条目数（测试 / 页面断言用）
    panel.is_hit(uid)      # 某 uid 是否被视为"本拍选中"（测试用）

自订阅信号（**仅本控件自己的域**，不重复驱动他人）：``worldbook_changed`` /
``play_changed`` → :meth:`refresh`。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui import icons
from gui.qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("maling.tavern.widgets.worldbook")

__all__ = ["WorldbookPanel"]

#: 面板标题（**无序号**，Q4）。
PANEL_TITLE: str = "世界书"

#: 命中标记文案（语义 = 本拍**选中**；**严禁**改写为"新增 / 获得"）。
HIT_CHIP_TEXT: str = "本拍选中"

#: 命中语义说明（中性，如实描述"叙述前快照"）。
HINT_TEXT: str = "亮起来的是这一拍正要讲到的内容。"

#: 空态文案。
EMPTY_TEXT: str = "这本书还没有写下任何一页。"

#: 无 service / 数据不可用时的中性兜底文案（不崩、不弹框）。
UNAVAILABLE_TEXT: str = "世界书这会儿打不开。"

#: 条目摘要截断长度（字符数，近似，仅用于列表可读性）。
SUMMARY_MAX_CHARS: int = 120

#: 触发字段展示前缀（如实展示条目自带的字段，**不编造**）。
_PRIMARY_PREFIX: str = "触发词"

#: 关联（次要）触发字段前缀。
_SECONDARY_PREFIX: str = "关联触发词"

#: selective logic → 中性中文说明（仅当条目确有 ``secondary_keys`` 时才展示）。
_LOGIC_LABELS: Dict[str, str] = {
    "AND_ANY": "其中任一项出现即可",
    "AND_ALL": "这些也都要出现",
    "NOT_ALL": "但不要全部出现",
    "NOT_ANY": "并且这些都不要出现",
}

#: 常驻条目（``constant``）的中性说明。
_CONSTANT_TEXT: str = "每次都会带上"


# ===========================================================================
# 小工具（本地副本，避免跨文件耦合）
# ===========================================================================

def _as_text(value: Any, default: str = "") -> str:
    """``str`` 守卫。"""
    return value if isinstance(value, str) else default


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（只保留非空字符串项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _clip(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """把长文本压成单行短摘要（保留可读性，**不改动原文语义**）。"""
    flat = " ".join(text.split())
    if len(flat) > limit:
        return flat[:limit] + "…"
    return flat


def _entry_key(entry: Any) -> tuple:
    """条目的稳定匹配键（用于"全部条目"与"本拍命中"两张表对齐）。

    ``uid > 0`` 时用 uid（内容包里的唯一号）；否则退化为 ``(title, content)``
    组合键 —— 两张表来自不同来源（持久化槽 vs 规范化 WorldBook），不能靠对象身份
    对齐，故用字段键。
    """
    if not isinstance(entry, dict):
        return ("", "", "")
    uid = entry.get("uid")
    if isinstance(uid, int) and not isinstance(uid, bool) and uid > 0:
        return ("uid", uid, "")
    return ("tc", _as_text(entry.get("title")), _as_text(entry.get("content")))


# ===========================================================================
# 主控件
# ===========================================================================

class WorldbookPanel(QWidget):
    """「世界书」Tab 控件：全部条目一览 + 本拍命中高亮（只读）。"""

    def __init__(
        self,
        service: Any,
        app_ctx: Any = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """构造世界书面板。

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
        self._hit_keys: set = set()
        self._init_ui()
        self._connect_signals()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.setObjectName("tavernWorldbookPanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self._title_label = QLabel(f"{icons.text_glyph('menu_book', '📖')} {PANEL_TITLE}")
        self._title_label.setObjectName("tavernPanelTitle")
        head.addWidget(self._title_label)
        head.addStretch(1)
        root.addLayout(head)

        self._hint_label = QLabel(HINT_TEXT)
        self._hint_label.setObjectName("tavernPanelHint")
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

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
        """自订阅本控件自己的域信号（**不重复驱动别人**）。"""
        svc = self._service
        if svc is None:
            return
        for name, slot in (
            ("worldbook_changed", self._on_signal),
            ("play_changed", self._on_signal),
        ):
            signal = getattr(svc, name, None)
            if signal is None or not hasattr(signal, "connect"):
                continue
            try:
                signal.connect(slot)
            except Exception:
                logger.debug("世界书面板订阅 %s 失败（忽略）", name, exc_info=True)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取 service 并整体重绘（幂等；页面 ``on_enter`` / 收信号后调用）。"""
        self._apply_panel_style()
        try:
            entries = self._collect_entries()
        except Exception:
            logger.debug("世界书条目读取失败（渲染空态）", exc_info=True)
            entries = []
        self._hit_keys = self._collect_hit_keys()
        self._render(entries)

    def apply_theme(self) -> None:
        """换肤后重刷取色（页面订阅 ``theme_changed`` 后调用；**不新增订阅**）。"""
        self.refresh()

    def entry_count(self) -> int:
        """当前渲染的条目数（测试 / 页面断言用）。"""
        return len(self._rows)

    def is_hit(self, uid: Any) -> bool:
        """某 uid 是否命中本拍（测试用；``uid`` 为内容包里的条目号）。"""
        return ("uid", uid, "") in self._hit_keys

    # ------------------------------------------------------------------
    # 数据读取
    # ------------------------------------------------------------------
    def _collect_entries(self) -> List[dict]:
        svc = self._service
        if svc is None:
            return []
        raw = svc.worldbook_entries()
        if not isinstance(raw, dict):
            return []
        title = _as_text(raw.get("title"))
        if title:
            self._title_label.setText(
                f"{icons.text_glyph('menu_book', '📖')} {PANEL_TITLE} · {title}"
            )
        else:
            self._title_label.setText(
                f"{icons.text_glyph('menu_book', '📖')} {PANEL_TITLE}"
            )
        entries = raw.get("entries")
        if not isinstance(entries, list):
            return []
        return [e for e in entries if isinstance(e, dict)]

    def _collect_hit_keys(self) -> set:
        svc = self._service
        if svc is None:
            return set()
        try:
            raw = svc.worldbook_hits()
        except Exception:
            logger.debug("世界书命中读取失败（按无一命中）", exc_info=True)
            return set()
        if not isinstance(raw, dict):
            return set()
        hits = raw.get("entries")
        if not isinstance(hits, list):
            return set()
        return {_entry_key(e) for e in hits if isinstance(e, dict)}

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _render(self, entries: List[dict]) -> None:
        self._clear_rows()
        if not entries:
            empty = QLabel(EMPTY_TEXT if self._service is not None else UNAVAILABLE_TEXT)
            empty.setObjectName("tavernEmptyHint")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"QLabel#tavernEmptyHint {{ color: {self._color('text_hint', '#9A9A9A')};"
                " background: transparent; }"
            )
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, empty)
            return
        for entry in entries:
            row = self._build_row(entry)
            self._rows.append(row)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _build_row(self, entry: dict) -> QFrame:
        hit = _entry_key(entry) in self._hit_keys
        card = QFrame()
        card.setObjectName("tavernEntryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        bg_card = self._color("bg_card", "#FFFFFF")
        border = self._color("border", "#FFE4E1")
        accent = self._color("accent", "#FF6B9D")
        # v2.1(UI-P1)：chip 文字用 accent_text；描边仍用 accent（非文字图形）。
        accent_text = self._color("accent_text", "#B45073")
        if hit:
            border = accent
        radius = self._color("radius_md", "10px")
        card.setStyleSheet(
            "QFrame#tavernEntryCard {"
            f" background: {bg_card}; border: 1px solid {border}; border-radius: {radius};"
            "}"
        )

        # ① 标题行（标题 + 命中标记）
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        name = _as_text(entry.get("title")) or "（未命名条目）"
        title_label = QLabel(name)
        title_label.setObjectName("tavernEntryTitle")
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"QLabel#tavernEntryTitle {{ color: {self._color('text', '#4A4A4A')}; }}"
        )
        top.addWidget(title_label, 1)
        if hit:
            chip = QLabel(HIT_CHIP_TEXT)
            chip.setObjectName("tavernHitChip")
            chip.setStyleSheet(
                "QLabel#tavernHitChip {"
                f" color: {accent_text}; border: 1px solid {accent};"
                f" border-radius: {self._color('radius_sm', '6px')}; padding: 1px 8px;"
                " background: transparent; }"
            )
            top.addWidget(chip, 0, Qt.AlignTop)
        layout.addLayout(top)

        # ② 触发信息行（仅当条目**确有**该字段，不编造）
        trigger = self._trigger_text(entry)
        if trigger:
            trigger_label = QLabel(trigger)
            trigger_label.setObjectName("tavernEntryKeys")
            trigger_label.setWordWrap(True)
            trigger_label.setStyleSheet(
                f"QLabel#tavernEntryKeys {{ color: {self._color('text_secondary', '#8A8A8A')}; }}"
            )
            layout.addWidget(trigger_label)

        # ③ 摘要行
        summary = _clip(_as_text(entry.get("content")))
        if summary:
            summary_label = QLabel(summary)
            summary_label.setObjectName("tavernEntrySummary")
            summary_label.setWordWrap(True)
            summary_label.setStyleSheet(
                f"QLabel#tavernEntrySummary {{ color: {self._color('text_hint', '#9A9A9A')}; }}"
            )
            layout.addWidget(summary_label)

        return card

    @staticmethod
    def _trigger_text(entry: dict) -> str:
        """把条目里**真实存在**的触发字段拼成中性中文（无字段则空串）。"""
        parts: List[str] = []
        if entry.get("constant"):
            parts.append(_CONSTANT_TEXT)
        keys = _as_str_list(entry.get("keys"))
        if keys:
            parts.append(f"{_PRIMARY_PREFIX}：{'、'.join(keys)}")
        secondary = _as_str_list(entry.get("secondary_keys"))
        if secondary:
            logic = entry.get("selective_logic")
            logic_cn = _LOGIC_LABELS.get(logic, "")
            suffix = f"（{logic_cn}）" if logic_cn else ""
            parts.append(f"{_SECONDARY_PREFIX}：{'、'.join(secondary)}{suffix}")
        return "　".join(parts)

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
            logger.debug("世界书取色失败，用兜底色 key=%s", key, exc_info=True)
            return fallback

    def _apply_panel_style(self) -> None:
        self.setStyleSheet("QWidget#tavernWorldbookPanel { background: transparent; }")
        self._title_label.setStyleSheet(
            f"QLabel#tavernPanelTitle {{ color: {self._color('text', '#4A4A4A')}; }}"
        )
        self._hint_label.setStyleSheet(
            f"QLabel#tavernPanelHint {{ color: {self._color('text_hint', '#9A9A9A')}; }}"
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _on_signal(self, *_args: Any) -> None:
        """信号槽：载荷不拘（dict / str），一律整体重绘。"""
        self.refresh()

    def _clear_rows(self) -> None:
        """清空条目行（``setParent(None)`` 立刻脱离，避免延迟删除残留）。"""
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
