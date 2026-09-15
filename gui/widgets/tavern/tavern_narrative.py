"""gui/widgets/tavern/tavern_narrative.py —— 酒馆「今夜」叙述流控件（V22-07 / 域6）。

设计依据 ``docs/design-v22.md``：
    · §6.1/§6.2 「今夜」Tab 的叙述流（逐段/逐字出现 = 原生母题① 文字节奏）；
    · §7     动效**只用**既有能力，**不新增任何几何母题**（无跳动点 / 电平柱条 /
             同心涟漪 / 旋转环 / 骨架微光 / 打字机光标 —— 一律不做）；
    · §6.3  颜色只走 ``theme_color`` 语义键（**禁在 ``__init__`` 缓存 QColor / 色值**）；
    · §6.5  全局派生值「**读时现取**」：换肤后由 :meth:`TavernNarrative.apply_theme` 重绘跟随；
    · §5.2  状态 / 文本分离：「重掷 / 改字」是**文本级**操作，不触碰状态字段。

============================  数据来源与接线契约（必读）  ============================
本控件**只经 TavernService 的信号**更新（不直接读写 store）：

信号（**本控件自行订阅**，页面**不要**再重复连接，否则会重复渲染）：
    · ``narration_chunk(str)`` —— 增量文本：逐 chunk 追加到当前「直播」块；
    · ``narration_done(str)``  —— 本拍**权威全文**：以完整文本收口直播块；
    · ``play_changed(str)``    —— 切局 / 内容变化 → 从查询面 :meth:`refresh` 重建。

查询面（首帧 / 切局 / 换肤重建）：``service.current_narrative()``
    返回 ``[{"turn", "role", "text", "input_kind", "at"}, ...]``（``role`` = player / narrator）。

**谁订阅 ``theme_engine.theme_changed``**：由**页面拥有者**（``PageTavern``）做**总订阅**，
收到后调用本控件的 :meth:`TavernNarrative.apply_theme`；本控件**不自行订阅**
``theme_changed``（避免与页面重复订阅 → 多次重绘）。

**玩家输入回显**：页面在 ``submit`` 之后调用 :meth:`TavernNarrative.add_player`
（或直接 :meth:`TavernNarrative.refresh`）把玩家那一行补进流中；本控件**不猜测**玩家文本。

**「重掷 / 改字」**：本控件暴露 :meth:`reroll` / :meth:`edit_text` 与信号
``reroll_requested`` / ``edit_requested``，**不内建按钮**（按钮归页面装配），保持控件纯粹。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui.qt_compat import (
    QFrame, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget, Qt, Signal,
)

logger = logging.getLogger("maling.tavern.widgets.narrative")

#: 「贴底跟随」判定容差（px）：滚动条距底 ≤ 该值即视为「贴底」。
FOLLOW_EPSILON_PX: int = 8

#: 角色常量（与 ``service.current_narrative()`` 的 ``role`` 对齐）。
ROLE_NARRATOR: str = "narrator"
ROLE_PLAYER: str = "player"

#: 空态占位文案（页面可经 :meth:`TavernNarrative.set_empty_text` 按局状态改写；
#: **自然语言、零序号、零数值**）。
EMPTY_TEXT: str = "故事还没开始。"

#: 主题语义键的兜底值（仅在 ``theme_color`` 不可用时使用；正常路径一律现取活动色板）。
_COLOR_FALLBACKS: Dict[str, str] = {
    "text": "#3A3A3A",
    "text_hint": "#9A9A9A",
    "bg_card": "#FFFFFF",
    "divider": "#E8E8E8",
}

#: 控件级 QSS（**只加 ``objectName`` 作用域规则**；走 ``%`` 格式化，QSS 花括号无需转义）。
#: 纪律：只设颜色（语义键）/ 圆角 / 内距 / **字号**（字号只写在 QSS，代码侧绝不做字号赋值）。
_QSS_TEMPLATE: str = """
QWidget#tavern_narrative {
    background: transparent;
}
QScrollArea#tavernNarrativeScroll {
    background: transparent;
    border: none;
}
QWidget#tavernNarrativeBody {
    background: transparent;
}
QLabel#tavernNarrativeText {
    color: %(text)s;
    background-color: %(bg_card)s;
    border: 1px solid %(divider)s;
    border-radius: 10px;
    padding: 10px 12px;
}
QLabel#tavernNarrativePlayer {
    color: %(text_hint)s;
    background: transparent;
    padding: 2px 8px;
}
QLabel#tavernNarrativeEmpty {
    color: %(text_hint)s;
    background: transparent;
    padding: 12px;
}
"""

__all__ = ["TavernNarrative", "FOLLOW_EPSILON_PX", "ROLE_NARRATOR", "ROLE_PLAYER"]


class TavernNarrative(QWidget):
    """酒馆叙述流：流式追加 + 贴底跟随 + 查询面重建（``objectName = "tavern_narrative"``）。

    公共 API（供页面装配）：
        * :meth:`refresh` —— 从 ``service.current_narrative()`` 全量重建（首帧 / 切局 / 换肤）；
        * :meth:`apply_theme` —— 现取主题色重刷内联 QSS（页面在 ``theme_changed`` 时调用）；
        * :meth:`add_player` —— 追加一条玩家回显行；
        * :meth:`reroll` / :meth:`edit_text` —— 文本级重掷 / 改字（转发给 service）；
        * :meth:`is_following` / :meth:`live_text` / :meth:`block_texts` —— 测试 / 页面只读查询。

    Signals:
        reroll_requested(int): 请求重掷第 ``turn`` 拍的叙述。
        edit_requested(int, str): 请求把第 ``turn`` 拍的叙述改为给定文本。
    """

    reroll_requested = Signal(int)
    edit_requested = Signal(int, str)

    def __init__(self, service: Any, app_ctx: Any = None, parent: Optional[QWidget] = None) -> None:
        """构造叙述流控件。

        Args:
            service: ``TavernService``（或同名信号 / 方法的桩对象）。
            app_ctx: 应用上下文（本控件经 ``service.theme_color`` 取色，仅作兜底保留）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self._service = service
        self._app_ctx = app_ctx
        self._follow = True
        self._programmatic = False
        self._blocks: List[Dict[str, Any]] = []
        self._live_label: Optional[QLabel] = None
        self._live_buffer = ""
        self._live_turn = -1
        self.setObjectName("tavern_narrative")
        self._build_ui()
        self._connect_service()
        self.apply_theme()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """搭建滚动区 + 段落容器 + 空态占位。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("tavernNarrativeScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._body = QWidget(self._scroll)
        self._body.setObjectName("tavernNarrativeBody")
        self._stream_layout = QVBoxLayout(self._body)
        self._stream_layout.setContentsMargins(4, 4, 4, 4)
        self._stream_layout.setSpacing(8)
        self._stream_layout.addStretch(1)

        self._empty = QLabel(EMPTY_TEXT, self._body)
        self._empty.setObjectName("tavernNarrativeEmpty")
        self._empty.setWordWrap(True)
        self._stream_layout.insertWidget(0, self._empty)

        self._scroll.setWidget(self._body)
        outer.addWidget(self._scroll)

        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_scroll_changed)
        bar.rangeChanged.connect(self._on_range_changed)

    def _connect_service(self) -> None:
        """自行订阅 TavernService 的数据信号（页面**不要**重复连接）。"""
        for name, slot in (
            ("narration_chunk", self._on_chunk),
            ("narration_done", self._on_done),
            ("play_changed", self._on_play_changed),
        ):
            sig = getattr(self._service, name, None)
            if sig is None or not hasattr(sig, "connect"):
                continue
            try:
                sig.connect(slot)
            except Exception:
                logger.debug("订阅酒馆叙述流信号失败: %s", name, exc_info=True)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _tc(self, key: str, fallback: str) -> str:
        """现取主题语义色（**不缓存**）；取不到回落 ``fallback``。"""
        fn = getattr(self._service, "theme_color", None)
        if callable(fn):
            try:
                return str(fn(key, fallback))
            except Exception:
                logger.debug("叙述流取主题色失败: %s", key, exc_info=True)
        return fallback

    def apply_theme(self) -> None:
        """现取主题色重建内联 QSS（页面在 ``theme_changed`` 时调用；**不缓存色值**）。"""
        colors = {k: self._tc(k, v) for k, v in _COLOR_FALLBACKS.items()}
        try:
            self.setStyleSheet(_QSS_TEMPLATE % colors)
        except Exception:
            logger.debug("叙述流应用主题样式失败（忽略）", exc_info=True)

    # ------------------------------------------------------------------
    # 滚动 / 贴底跟随
    # ------------------------------------------------------------------
    def _scrollbar(self):
        return self._scroll.verticalScrollBar()

    def is_following(self) -> bool:
        """当前是否处于「贴底跟随」（用户未手动上翻）。"""
        return bool(self._follow)

    def _on_scroll_changed(self, value: int) -> None:
        """滚动条变化：非程序性滚动时据此判定是否仍贴底。"""
        if self._programmatic:
            return
        self._follow = value >= self._scrollbar().maximum() - FOLLOW_EPSILON_PX

    def _on_range_changed(self, _lo: int, _hi: int) -> None:
        """内容高度变化：贴底态下滑到底（解决布局延后更新导致的 range 变化）。"""
        if self._follow:
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        """程序性滚到底（期间不改变跟随状态）。"""
        bar = self._scrollbar()
        self._programmatic = True
        try:
            bar.setValue(bar.maximum())
        finally:
            self._programmatic = False

    def _after_content_change(self) -> None:
        """内容变更后刷新布局；贴底态则滚到底。"""
        try:
            self._stream_layout.activate()
            self._body.adjustSize()
        except Exception:
            logger.debug("叙述流布局刷新失败（忽略）", exc_info=True)
        if self._follow:
            self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def _add_block(self, role: str, text: str, turn: int) -> QLabel:
        """追加一个叙述 / 玩家块，返回其文本 QLabel。"""
        holder = QWidget(self._body)
        holder.setObjectName("tavernNarrativeBlock")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        label = QLabel(text, holder)
        label.setObjectName("tavernNarrativeText" if role == ROLE_NARRATOR else "tavernNarrativePlayer")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        lay.addWidget(label)

        # 插在尾随 stretch 之前（保持块顶对齐）
        index = max(0, self._stream_layout.count() - 1)
        self._stream_layout.insertWidget(index, holder)
        self._blocks.append({"role": role, "turn": turn, "holder": holder, "label": label})
        self._set_empty(False)
        return label

    def _clear_blocks(self) -> None:
        """移除全部叙述块并复位直播态。"""
        for block in self._blocks:
            holder = block.get("holder")
            if holder is None:
                continue
            try:
                self._stream_layout.removeWidget(holder)
                holder.setParent(None)
                holder.deleteLater()
            except Exception:
                logger.debug("移除叙述块失败（忽略）", exc_info=True)
        self._blocks = []
        self._live_label = None
        self._live_buffer = ""
        self._live_turn = -1

    def _set_empty(self, visible: bool) -> None:
        self._empty.setVisible(bool(visible))

    def set_empty_text(self, text: str) -> None:
        """改写空态占位文案（页面按当前局状态调用；空串 → 回落 :data:`EMPTY_TEXT`）。

        空态是**引导位**：无活动局时页面把它切到「点上面的入口」那版，让玩家知道从哪开始；
        有活动局时切回中性版，避免误导玩家去找并不存在的入口。
        """
        self._empty.setText(text if isinstance(text, str) and text.strip() else EMPTY_TEXT)

    def empty_text(self) -> str:
        """当前空态占位文案（测试 / 页面只读查询）。"""
        return self._empty.text()

    # ------------------------------------------------------------------
    # 服务信号槽
    # ------------------------------------------------------------------
    def _on_chunk(self, text: Any) -> None:
        """增量 chunk：追加到当前直播块（首个 chunk 时新建直播块）。"""
        if not isinstance(text, str) or not text:
            return
        if self._live_label is None:
            self._live_turn = self._guess_turn()
            self._live_label = self._add_block(ROLE_NARRATOR, "", self._live_turn)
            self._live_buffer = ""
        self._live_buffer += text
        self._live_label.setText(self._live_buffer)
        self._after_content_change()

    def _on_done(self, text: Any) -> None:
        """本拍权威全文：以完整文本收口直播块。"""
        final_text = text if isinstance(text, str) else ""
        if self._live_label is None:
            self._live_turn = self._guess_turn()
            self._live_label = self._add_block(ROLE_NARRATOR, "", self._live_turn)
        self._live_label.setText(final_text)
        self._live_buffer = ""
        self._live_label = None
        self._after_content_change()

    def _on_play_changed(self, *_args: Any) -> None:
        """切局 / 内容变化 → 全量重建。"""
        self.refresh()

    def _guess_turn(self) -> int:
        """直播块的 ``turn`` 估计（取当前叙述面最后一条的 ``turn``，取不到回落 -1）。"""
        try:
            entries = self._service.current_narrative()
        except Exception:
            logger.debug("读取叙述面失败（忽略）", exc_info=True)
            return -1
        if isinstance(entries, (list, tuple)):
            for entry in reversed(entries):
                if isinstance(entry, dict):
                    turn = entry.get("turn")
                    if isinstance(turn, int) and not isinstance(turn, bool):
                        return turn
        return -1

    # ------------------------------------------------------------------
    # 公共操作
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """从 ``service.current_narrative()`` 全量重建（首帧 / 切局 / 换肤）。"""
        bar = self._scrollbar()
        prev_value = bar.value()
        entries = self._safe_narrative()
        self._clear_blocks()
        for entry in entries:
            role = entry.get("role")
            text = entry.get("text")
            if not isinstance(text, str) or not text:
                continue
            if role == ROLE_PLAYER:
                self._add_block(ROLE_PLAYER, text, self._as_turn(entry.get("turn")))
            else:
                self._add_block(ROLE_NARRATOR, text, self._as_turn(entry.get("turn")))
        self._set_empty(len(self._blocks) == 0)
        try:
            self._stream_layout.activate()
            self._body.adjustSize()
        except Exception:
            logger.debug("叙述流重建后布局刷新失败（忽略）", exc_info=True)
        if self._follow:
            self._scroll_to_bottom()
        else:
            bar.setValue(min(prev_value, bar.maximum()))

    def add_player(self, text: str, turn: int = -1) -> None:
        """追加一条玩家回显行（页面在 ``submit`` 成功后调用）。"""
        if not isinstance(text, str) or not text:
            return
        self._add_block(ROLE_PLAYER, text, turn)
        self._after_content_change()

    def reroll(self, turn: int) -> bool:
        """请求重掷某拍叙述（文本级；转发给 ``service.reroll``）。"""
        self.reroll_requested.emit(int(turn))
        fn = getattr(self._service, "reroll", None)
        if callable(fn):
            try:
                return bool(fn(int(turn)))
            except Exception:
                logger.debug("重掷请求失败（忽略）", exc_info=True)
        return False

    def edit_text(self, turn: int, text: str) -> bool:
        """请求修改某拍叙述文本（文本级；转发给 ``service.edit_narration``）。"""
        if not isinstance(text, str):
            return False
        self.edit_requested.emit(int(turn), text)
        fn = getattr(self._service, "edit_narration", None)
        if callable(fn):
            try:
                return bool(fn(int(turn), text))
            except Exception:
                logger.debug("改字请求失败（忽略）", exc_info=True)
        return False

    # ------------------------------------------------------------------
    # 只读查询（测试 / 页面）
    # ------------------------------------------------------------------
    def live_text(self) -> str:
        """当前直播块的累计文本（无直播块 → 空串）。"""
        return self._live_buffer

    def block_texts(self) -> List[str]:
        """全部已渲染块的文本（保持时序）。"""
        out: List[str] = []
        for block in self._blocks:
            label = block.get("label")
            if isinstance(label, QLabel):
                out.append(label.text())
        return out

    def scroll_area(self) -> QScrollArea:
        """暴露滚动区（测试断言贴底 / 上翻行为用）。"""
        return self._scroll

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _safe_narrative(self) -> List[dict]:
        try:
            entries = self._service.current_narrative()
        except Exception:
            logger.debug("读取叙述面失败（忽略）", exc_info=True)
            return []
        if not isinstance(entries, (list, tuple)):
            return []
        return [e for e in entries if isinstance(e, dict)]

    @staticmethod
    def _as_turn(value: Any) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return -1
