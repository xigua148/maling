"""gui/widgets/tavern/tavern_trace.py —— 酒馆「记录」Tab 控件（V22-08，只读留痕）。

设计依据：``docs/design-v22.md`` §6.1（记录 Tab 只读；**不呈现成功率 / 进度 / 胜率**）、
§6.3（只走语义键取色）、§6.4（字号只写 QSS）、§6.5（全局派生值读时取、不缓存）。

职责（**只读**）：用 :meth:`TavernService.trace` 渲染每一拍的**过程留痕** ——
``mode``（本地判定 / 她提议后本地裁决 / 本地照看）、``transform``、``ok``、
``reason``、``llm_used``。它是**过程记录**，不是**计量报表**。

另有一节「走过的结尾」：用 :meth:`TavernService.journal_endings` 列出**跨局累积的
已抵达结局名**（``journal.seen_endings``）。此前该字段**只写不读**（全仓无展示面），
本节即其唯一展示面 —— **只列结局名**，**不显示数量 / 「X / Y 已收集」/ 进度条 / 序号**。

🚨 **R-A 硬约束（机器可验，不可让步）**：
    木柜上**不得出现任何计量或评价性数值** —— 成功率 / 进度 / 胜率 / 评分 / 百分比 /
    得分 / 排名 / 计数 … 一律不许；界面上**一个阿拉伯数字都不出现**；
    ``reason`` 这类技术串**绝不原样上屏**（一律翻成中性中文，裸错误码如
    ``bad_args:`` / ``precondition_failed:`` 原串不进任何 ``QLabel``）。

审美与纪律：
    * **零字号代码**（字号只在 ``base.qss``）；
    * **颜色不硬编码**（走 ``service.theme_color``；本次状态点取 ``state_ok`` /
      ``state_warn`` 语义键，仅静态着色，**不做任何几何母题运动**）；
    * **无动效**（不涉及 ``gui/motion.py``；``off`` 档天然静态）。

公开 API（供页面 ``PageTavern`` 组装）::

    panel = TracePanel(service, app_ctx=None, parent=None)
    panel.refresh()               # 重新读取并渲染
    panel.apply_theme()           # 换肤后重刷取色
    panel.row_count()             # 当前渲染的拍数（测试用）
    panel.field_texts()           # 逐拍的 5 个字段中性文案（测试用）
    panel.ending_texts()          # 「走过的结尾」当前上屏的结局名（测试用）

自订阅信号：``turn_ready`` / ``play_changed`` → :meth:`refresh`。
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

logger = logging.getLogger("maling.tavern.widgets.trace")

__all__ = ["TracePanel"]

#: 面板标题（**无序号**，Q4）。
PANEL_TITLE: str = "记录"

#: 空态文案。
EMPTY_TEXT: str = "还没有走过任何一步。"

#: 无 service 时的中性兜底文案。
UNAVAILABLE_TEXT: str = "这一程的记录这会儿打不开。"

#: 摘要说明（中性，无任何数值）。
HINT_TEXT: str = "这里记的是每一拍由谁拿主意、后来怎样了。"

#: 「走过的结尾」小节标题（跨局 ``journal.seen_endings`` 的**只读**展示面）。
#: R-A 口径：**只列结局名**，不显示数量 / 序号 / 进度 / 达成率，也没有任何计量条。
ENDING_SECTION_TITLE: str = "走过的结尾"

#: 还没有抵达过任何结局时的中性空态（**无数字、无「X / Y 已收集」**）。
ENDING_EMPTY_TEXT: str = "这一程还没有走到过结尾。"

#: 角色 → 中性称呼（**不上屏英文 role 串**）。
_ROLE_LABELS: Dict[str, str] = {
    "player": "你",
    "narrator": "说书人",
}

#: 三级路由档位 → 中性中文（**不上屏 verbatim/propose/narrate 裸串**）。
_MODE_LABELS: Dict[str, str] = {
    "verbatim": "本地照着你的原话落实",
    "propose": "她先提了个想法，本地裁决后落实",
    "narrate": "本地替你把这一程照看过去",
}

#: 变换 → 中性中文（7 变换白名单；未知 / 空 → 破折号，**不回显裸串**）。
_TRANSFORM_LABELS: Dict[str, str] = {
    "move_to": "换了个地方",
    "take": "拿起一样东西",
    "give": "把东西递了过去",
    "open": "打开了什么",
    "ask_about": "问起了一件事",
    "wait": "静静等了一会儿",
    "order": "要了点什么",
}

#: ``reason`` 基础短码 → 中性中文（**含前缀型短码**，按 ``:`` 之前的基码匹配）。
_REASON_LABELS: Dict[str, str] = {
    "ok": "顺顺当当地过去了",
    "unknown_transform": "这一步没听明白，就当作随口一说",
    "bad_args": "这一步的说法没能对上，照着气氛过去了",
    "precondition_failed": "这会儿还做不到，先搁下了",
    "forbidden": "这一步越了界，被轻轻拦下了",
    "invariant_violated": "为了不把故事弄乱，这一步没有落下",
    "llm_timeout": "她想了太久，先由本地接上了话",
    "llm_bad_json": "她这句没说明白，由本地接上了话",
    "llm_disabled": "这会儿没有联网，由本地接上了话",
}

#: 未知 / 空 ``reason`` 的中性兜底（**绝不回显原始串**）。
_REASON_FALLBACK: str = "本地把这一程记了下来"

#: ``ok`` 的中性文案。
_OK_TRUE: str = "这一步落实了"
_OK_FALSE: str = "这一步没落下"

#: ``llm_used`` 的中性文案。
_LLM_TRUE: str = "这一拍有她参与"
_LLM_FALSE: str = "这一拍全由本地接住"


# ===========================================================================
# 小工具
# ===========================================================================

def _as_text(value: Any, default: str = "") -> str:
    """``str`` 守卫。"""
    return value if isinstance(value, str) else default


def _role_text(role: Any) -> str:
    """角色 → 中性称呼（未知 → "旁白"）。"""
    return _ROLE_LABELS.get(_as_text(role), "旁白")


def _mode_text(mode: Any) -> str:
    """路由档位 → 中性中文（未知 / 空 → 兜底叙述口径，**不回显裸串**）。"""
    return _MODE_LABELS.get(_as_text(mode), _MODE_LABELS["narrate"])


def _transform_text(transform: Any) -> str:
    """变换 → 中性中文（未知 / 空 → "—"，**不回显裸串**）。"""
    return _TRANSFORM_LABELS.get(_as_text(transform), "—")


def _reason_text(reason: Any) -> str:
    """``reason`` → 中性中文（**含前缀型短码**；**绝不原样上屏**）。"""
    text = _as_text(reason).strip()
    if not text:
        return _REASON_FALLBACK
    base = text.split(":", 1)[0].strip()
    return _REASON_LABELS.get(base, _REASON_FALLBACK)


# ===========================================================================
# 主控件
# ===========================================================================

class TracePanel(QWidget):
    """「记录」Tab 控件：逐拍过程留痕 + 跨局「走过的结尾」（只读，**零计量 / 零评价数值**）。"""

    def __init__(
        self,
        service: Any,
        app_ctx: Any = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """构造记录面板。

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
        self._fields: List[Dict[str, str]] = []
        self._ending_names: List[str] = []
        self._init_ui()
        self._connect_signals()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.setObjectName("tavernTracePanel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self._title_label = QLabel(f"{icons.text_glyph('article', '📋')} {PANEL_TITLE}")
        self._title_label.setObjectName("tavernPanelTitle")
        head.addWidget(self._title_label)
        head.addStretch(1)
        root.addLayout(head)

        self._hint_label = QLabel(HINT_TEXT)
        self._hint_label.setObjectName("tavernPanelHint")
        self._hint_label.setWordWrap(True)
        root.addWidget(self._hint_label)

        # 「走过的结尾」：跨局 journal 的**只读**展示面（只列结局名，零数量 / 零序号）。
        # 此前 ``journal.seen_endings`` 只写不读 —— 玩家抵达过的结局没有任何展示面。
        self._endings_box = QFrame()
        self._endings_box.setObjectName("tavernEndingsBox")
        endings_box = QVBoxLayout(self._endings_box)
        endings_box.setContentsMargins(0, 0, 0, 0)
        endings_box.setSpacing(3)
        self._endings_title = QLabel(ENDING_SECTION_TITLE)
        self._endings_title.setObjectName("tavernPanelHint")
        endings_box.addWidget(self._endings_title)
        self._endings_host = QWidget()
        self._endings_layout = QVBoxLayout(self._endings_host)
        self._endings_layout.setContentsMargins(0, 0, 0, 0)
        self._endings_layout.setSpacing(2)
        self._endings_layout.addStretch(1)
        endings_box.addWidget(self._endings_host)
        root.addWidget(self._endings_box)

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
        for name in ("turn_ready", "play_changed"):
            signal = getattr(svc, name, None)
            if signal is None or not hasattr(signal, "connect"):
                continue
            try:
                signal.connect(self._on_signal)
            except Exception:
                logger.debug("记录面板订阅 %s 失败（忽略）", name, exc_info=True)

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """重新读取 service 并整体重绘（幂等）。"""
        self._apply_panel_style()
        try:
            entries = self._collect_trace()
        except Exception:
            logger.debug("记录读取失败（渲染空态）", exc_info=True)
            entries = []
        self._render(entries)
        self._render_endings()

    def apply_theme(self) -> None:
        """换肤后重刷取色（页面订阅 ``theme_changed`` 后调用；**不新增订阅**）。"""
        self.refresh()

    def row_count(self) -> int:
        """当前渲染的拍数（测试 / 页面断言用）。"""
        return len(self._rows)

    def field_texts(self) -> List[Dict[str, str]]:
        """逐拍的 5 个字段中性文案（测试用；**已是上屏文本**，不含技术串）。"""
        return [dict(item) for item in self._fields]

    def ending_texts(self) -> List[str]:
        """「走过的结尾」小节当前上屏的**结局名**（测试 / 页面断言用）。

        只含结局名（自然语言），**不含**任何数量 / 序号 / 进度文案。
        """
        return list(self._ending_names)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _collect_trace(self) -> List[dict]:
        svc = self._service
        if svc is None:
            return []
        raw = svc.trace()
        if not isinstance(raw, list):
            return []
        return [e for e in raw if isinstance(e, dict)]

    def _collect_endings(self) -> List[str]:
        """跨局已抵达结局名（``service.journal_endings()``；无该方法 / 非法形状 → 空表）。

        用 ``getattr`` 取（而非硬依赖）：旧桩 service / 未来替换实现缺此方法时，
        本小节只渲染空态，**绝不因此崩掉整个「记录」Tab**。
        """
        svc = self._service
        if svc is None:
            return []
        getter = getattr(svc, "journal_endings", None)
        if not callable(getter):
            return []
        raw = getter()
        if not isinstance(raw, list):
            return []
        return [n for n in raw if isinstance(n, str) and n]

    def _render_endings(self) -> None:
        """重绘「走过的结尾」小节（**只列结局名**；空 → 中性空态）。"""
        while self._endings_layout.count() > 1:
            item = self._endings_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._ending_names = []

        names = self._collect_endings()
        if not names:
            empty = QLabel(ENDING_EMPTY_TEXT)
            empty.setObjectName("tavernEmptyHint")
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"QLabel#tavernEmptyHint {{ color: {self._color('text_hint', '#9A9A9A')};"
                " background: transparent; }"
            )
            self._endings_layout.insertWidget(0, empty)
            return

        for name in names:
            label = QLabel(name)
            label.setObjectName("tavernEndingName")
            label.setWordWrap(True)
            label.setStyleSheet(
                f"QLabel#tavernEndingName {{ color: {self._color('text', '#4A4A4A')}; }}"
            )
            self._endings_layout.insertWidget(self._endings_layout.count() - 1, label)
            self._ending_names.append(name)

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
            row, fields = self._build_row(entry)
            self._rows.append(row)
            self._fields.append(fields)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _build_row(self, entry: dict) -> tuple:
        ok = bool(entry.get("ok"))
        llm_used = bool(entry.get("llm_used"))

        role_text = _role_text(entry.get("role"))
        mode_text = _mode_text(entry.get("mode"))
        transform_text = _transform_text(entry.get("transform"))
        ok_text = _OK_TRUE if ok else _OK_FALSE
        reason_text = _reason_text(entry.get("reason"))
        llm_text = _LLM_TRUE if llm_used else _LLM_FALSE

        card = QFrame()
        card.setObjectName("tavernTraceRow")
        bg_card = self._color("bg_card", "#FFFFFF")
        border = self._color("border", "#FFE4E1")
        radius = self._color("radius_md", "10px")
        card.setStyleSheet(
            "QFrame#tavernTraceRow {"
            f" background: {bg_card}; border: 1px solid {border}; border-radius: {radius};"
            "}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        text_color = self._color("text", "#4A4A4A")
        secondary = self._color("text_secondary", "#8A8A8A")
        ok_color = self._color("state_ok", "#3FA06A") if ok else self._color("text_secondary", "#8A8A8A")

        # 行①：角色 + 结果（静态着色，无几何运动）
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        role_label = QLabel(f"{icons.text_glyph('person', '🧑')} {role_text}")
        role_label.setObjectName("tavernTraceRole")
        role_label.setStyleSheet(f"QLabel#tavernTraceRole {{ color: {text_color}; }}")
        ok_label = QLabel(ok_text)
        ok_label.setObjectName("tavernTraceField")
        ok_label.setStyleSheet(f"QLabel#tavernTraceField {{ color: {ok_color}; }}")
        head.addWidget(role_label)
        head.addStretch(1)
        head.addWidget(ok_label)
        layout.addLayout(head)

        # 行②：档位 + 变换
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(6)
        mode_label = QLabel(mode_text)
        mode_label.setObjectName("tavernTraceField")
        mode_label.setWordWrap(True)
        mode_label.setStyleSheet(f"QLabel#tavernTraceField {{ color: {secondary}; }}")
        transform_label = QLabel(transform_text)
        transform_label.setObjectName("tavernTraceField")
        transform_label.setStyleSheet(f"QLabel#tavernTraceField {{ color: {secondary}; }}")
        mid.addWidget(mode_label, 1)
        mid.addWidget(transform_label, 0, Qt.AlignRight)
        layout.addLayout(mid)

        # 行③：是否用过她（中性）
        llm_label = QLabel(llm_text)
        llm_label.setObjectName("tavernTraceField")
        llm_label.setStyleSheet(f"QLabel#tavernTraceField {{ color: {secondary}; }}")
        layout.addWidget(llm_label)

        # 行④：中性缘故（技术串已翻成中文；**绝不回显裸错误码**）
        reason_label = QLabel(reason_text)
        reason_label.setObjectName("tavernTraceReason")
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet(f"QLabel#tavernTraceReason {{ color: {text_color}; }}")
        layout.addWidget(reason_label)

        fields = {
            "role": role_text,
            "mode": mode_text,
            "transform": transform_text,
            "ok": ok_text,
            "reason": reason_text,
            "llm_used": llm_text,
        }
        return card, fields

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
            logger.debug("记录面板取色失败，用兜底色 key=%s", key, exc_info=True)
            return fallback

    def _apply_panel_style(self) -> None:
        self.setStyleSheet("QWidget#tavernTracePanel { background: transparent; }")
        self._title_label.setStyleSheet(
            f"QLabel#tavernPanelTitle {{ color: {self._color('text', '#4A4A4A')}; }}"
        )
        self._hint_label.setStyleSheet(
            f"QLabel#tavernPanelHint {{ color: {self._color('text_hint', '#9A9A9A')}; }}"
        )
        self._endings_title.setStyleSheet(
            f"QLabel#tavernPanelHint {{ color: {self._color('text_hint', '#9A9A9A')}; }}"
        )

    def _on_signal(self, *_args: Any) -> None:
        """信号槽：载荷不拘，一律整体重绘。"""
        self.refresh()

    def _clear_rows(self) -> None:
        """清空记录行（``setParent(None)`` 立刻脱离，避免延迟删除残留）。"""
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._rows = []
        self._fields = []
