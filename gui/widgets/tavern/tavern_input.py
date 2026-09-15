"""gui/widgets/tavern/tavern_input.py —— 酒馆「今夜」输入行 + 快捷动作排（V22-07 / 域6）。

设计依据 ``docs/design-v22.md``：
    · §6.1/§6.2 「今夜」Tab：**快捷动作排（4–6 槽）** + **自由输入行**；
    · §6.3  颜色只走 ``theme_color`` 语义键（**禁在 ``__init__`` 缓存色值**）；
    · §6.4  字号只写在 QSS（本控件走**控件级内联 QSS + objectName**，§6.4 明确「优先」此形态）；
    · §7    生成中指示只做**文字省略号节奏**（复用 ``kb_dialog.py`` 既有先例），**不新增几何母题**；
    · §5.6  降级（LLM 不可用 / 只读会话 / 自由输入关闭）走 **``degraded`` 中性提示**，
             **绝不弹错误框**（本控件内联提示条呈现，无 ``QMessageBox``）。

============================  数据来源与接线契约（必读）  ============================
本控件**只经 TavernService 的信号**更新（不直接读写 store）：

信号（**本控件自行订阅**，页面**不要**再重复连接）：
    · ``choices_changed(list)`` —— 快捷动作；元素形状**双兼容**：
        · 真实 service：``{"choice_id": str, "label": str}``；
        · 兼容别名：``{"value": str, "text": str, "kind": str}``。
      点击 → ``service.submit(choice_id, input_kind="choice")``（**路由用机器名**），
      同时 ``submitted`` 发 **label**（**回显用中文**）。
    · ``busy_changed(bool)`` —— 生成中：禁用提交 + 中性「进行中」文字节奏提示。
    · ``degraded(str)``      —— **行内**中性提示（**不弹窗、非红色报错框**）。
    · ``read_only_changed(bool)`` / ``play_changed(str)`` —— 刷新。

**谁订阅 ``theme_engine.theme_changed``**：由**页面拥有者**（``PageTavern``）做总订阅，
收到后调用 :meth:`TavernInput.apply_theme`；本控件**不自行订阅** ``theme_changed``。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from gui.qt_compat import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget, Qt, Signal,
)
from gui import icons
from gui import motion
from gui.chat_input_logic import compute_input_height

logger = logging.getLogger("maling.tavern.widgets.input")

#: 进行中指示的**文字节奏**（复用 ``kb_dialog.py`` 既有先例；融入度合规形态，非几何母题）。
_BUSY_DOTS = ("", ".", "..", "...")
#: 循环周期（ms）；``motion.loop`` 会夹取到 [800, 1600]。
_BUSY_PERIOD_MS = 1600

#: 偏好动词 → 图标名（均取 ``gui/icons.py`` 已登记名；**不新增图标**）。
_CHOICE_ICONS: Dict[str, str] = {
    "move_to": "route",
    "take": "gift",
    "give": "gift",
    "open": "key",
    "ask_about": "question_answer",
    "wait": "time",
    "order": "glass",
}
_DEFAULT_CHOICE_ICON = "auto_awesome"

#: 主题语义键兜底值（仅 ``theme_color`` 不可用时使用）。
_COLOR_FALLBACKS: Dict[str, str] = {
    "text": "#3A3A3A",
    "text_hint": "#9A9A9A",
    "bg_card": "#FFFFFF",
    "bg_light": "#F5F5F5",
    "surface_muted": "#EFEFEF",
    "divider": "#E8E8E8",
    "border": "#DDDDDD",
    "focus_accent": "#FF6B9D",
    "primary": "#FF6B9D",
    "primary_dark": "#E8558A",
    "disabled_bg": "#EDEDED",
    "disabled_text": "#B0B0B0",
    "text_on_accent": "#FFFFFF",
}

_QSS_TEMPLATE: str = """
QWidget#tavern_input {
    background: transparent;
}
QPushButton#tavernChoiceBtn {
    background-color: %(bg_card)s;
    color: %(text)s;
    border: 1px solid %(divider)s;
    border-radius: 14px;
    padding: 6px 12px;
}
QPushButton#tavernChoiceBtn:hover {
    background-color: %(surface_muted)s;
    border-color: %(focus_accent)s;
}
QPushButton#tavernChoiceBtn:pressed {
    background-color: %(bg_light)s;
}
QPushButton#tavernChoiceBtn:disabled {
    color: %(disabled_text)s;
    background-color: %(disabled_bg)s;
    border-color: %(divider)s;
}
QPlainTextEdit#tavernInputEdit {
    background-color: %(bg_card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
    padding: 8px 10px;
}
QPlainTextEdit#tavernInputEdit:focus {
    border-color: %(focus_accent)s;
}
QPushButton#tavernSendBtn {
    background-color: %(primary)s;
    color: %(text_on_accent)s;
    border: none;
    border-radius: 16px;
    padding: 8px 20px;
}
QPushButton#tavernSendBtn:hover {
    background-color: %(primary_dark)s;
}
QPushButton#tavernSendBtn:disabled {
    background-color: %(disabled_bg)s;
    color: %(disabled_text)s;
}
"""

__all__ = ["TavernInput"]


class _TavernInputEdit(QPlainTextEdit):
    """自由输入框（多行）：Enter 提交 / Shift+Enter 换行（沿用项目既有聊天输入框范式）。"""

    submit_requested = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 钩子
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() == Qt.ShiftModifier:
                super().keyPressEvent(event)  # 换行
                return
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TavernInput(QWidget):
    """酒馆输入行 + 快捷动作排（``objectName = "tavern_input"``）。

    公共 API（供页面装配）：
        * :meth:`refresh` —— 从查询面拉取选项 / 忙态 / 只读态；
        * :meth:`apply_theme` —— 现取主题色重刷内联 QSS（页面在 ``theme_changed`` 时调用）；
        * :meth:`set_choices` / :meth:`set_busy` / :meth:`show_hint` / :meth:`clear_hint`；
        * :meth:`choice_buttons` / :meth:`send_button` / :meth:`input_edit` / :meth:`hint_text` —— 测试查询。

    Signals:
        submitted(str, str): 一次输入已提交（文本, ``"free"`` | ``"choice"``）—— 供页面回显。
            ``choice`` 档的文本是选项**中文 label**（不是 ``choice_id``）。
    """

    submitted = Signal(str, str)

    def __init__(self, service: Any, app_ctx: Any = None, parent: Optional[QWidget] = None) -> None:
        """构造输入控件。

        Args:
            service: ``TavernService``（或同名信号 / 方法的桩对象）。
            app_ctx: 应用上下文（本控件经 ``service.theme_color`` 取色，仅作兜底保留）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self._service = service
        self._app_ctx = app_ctx
        self._busy = False
        self._read_only = False
        self._degraded_text = ""
        self._busy_text = ""
        self._busy_handle = None
        self._choice_buttons: List[QPushButton] = []
        self.setObjectName("tavern_input")
        self._build_ui()
        self._connect_service()
        self.apply_theme()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """搭建：快捷动作排 → 行内提示 → 自由输入行。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 快捷动作排
        self._choices_host = QWidget(self)
        self._choices_host.setObjectName("tavernChoicesRow")
        self._choices_layout = QHBoxLayout(self._choices_host)
        self._choices_layout.setContentsMargins(0, 0, 0, 0)
        self._choices_layout.setSpacing(6)
        self._choices_layout.addStretch(1)
        outer.addWidget(self._choices_host)

        # 行内中性提示（degraded / 进行中；**永不弹窗**）
        self._hint = QLabel("", self)
        self._hint.setObjectName("tavernInlineHint")
        self._hint.setWordWrap(True)
        self._hint.setVisible(False)
        outer.addWidget(self._hint)

        # 自由输入行
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._edit = _TavernInputEdit(self)
        self._edit.setObjectName("tavernInputEdit")
        self._edit.setPlaceholderText("也可以直接写下你想做的事…")
        self._edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._edit.setFixedHeight(48)
        self._edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._edit.textChanged.connect(self._autosize)
        self._edit.submit_requested.connect(self._on_send)
        row.addWidget(self._edit, 1)

        self._send_btn = QPushButton(self)
        self._send_btn.setObjectName("tavernSendBtn")
        self._send_btn.setText(self._decorate("send", "送出"))
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        row.addWidget(self._send_btn)
        outer.addLayout(row)

    def _connect_service(self) -> None:
        """自行订阅 TavernService 的数据信号（页面**不要**重复连接）。"""
        for name, slot in (
            ("choices_changed", self.set_choices),
            ("busy_changed", self.set_busy),
            ("degraded", self.show_hint),
            ("read_only_changed", self.set_read_only),
            ("play_changed", self._on_play_changed),
        ):
            sig = getattr(self._service, name, None)
            if sig is None or not hasattr(sig, "connect"):
                continue
            try:
                sig.connect(slot)
            except Exception:
                logger.debug("订阅酒馆输入信号失败: %s", name, exc_info=True)

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------
    def _tc(self, key: str, fallback: str) -> str:
        """现取主题语义色（**不缓存**）。"""
        fn = getattr(self._service, "theme_color", None)
        if callable(fn):
            try:
                return str(fn(key, fallback))
            except Exception:
                logger.debug("输入控件取主题色失败: %s", key, exc_info=True)
        return fallback

    def apply_theme(self) -> None:
        """现取主题色重建内联 QSS（**不缓存色值**）。"""
        colors = {k: self._tc(k, v) for k, v in _COLOR_FALLBACKS.items()}
        try:
            self.setStyleSheet(_QSS_TEMPLATE % colors)
        except Exception:
            logger.debug("输入控件应用主题样式失败（忽略）", exc_info=True)
        # 提示条颜色依赖状态，重刷时一并按当前状态重上色
        self._render_hint()

    # ------------------------------------------------------------------
    # 装饰
    # ------------------------------------------------------------------
    @staticmethod
    def _decorate(name: str, label: str) -> str:
        """图标字形 + 文案（**无裸 emoji**：图标不可用时回落为空，仅显示文案）。"""
        glyph = icons.text_glyph(name, "")
        return f"{glyph} {label}" if glyph else label

    @staticmethod
    def _icon_for(value: str) -> str:
        """按选项值里的变换名取图标（取不到回落通用图标）。"""
        low = (value or "").lower()
        for transform, icon_name in _CHOICE_ICONS.items():
            if transform in low:
                return icon_name
        return _DEFAULT_CHOICE_ICON

    # ------------------------------------------------------------------
    # 选项
    # ------------------------------------------------------------------
    def set_choices(self, choices: Any) -> None:
        """重建快捷动作按钮（接 ``choices_changed``；**双形状兼容**）。"""
        while self._choices_layout.count():
            item = self._choices_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._choice_buttons = []

        normalized = _normalize_choices(choices)
        for choice in normalized:
            text = self._decorate(self._icon_for(choice["value"]), choice["label"])
            btn = QPushButton(text, self._choices_host)
            btn.setObjectName("tavernChoiceBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.setEnabled(not self._busy)
            value = choice["value"]
            label = choice["label"]
            btn.clicked.connect(
                lambda _checked=False, v=value, lb=label: self._on_choice(v, lb))
            self._choices_layout.addWidget(btn)
            self._choice_buttons.append(btn)
        self._choices_layout.addStretch(1)
        self._choices_host.setVisible(bool(normalized))

    def _on_choice(self, choice_id: str, label: str = "") -> None:
        """点击选项 → 提交（``input_kind="choice"``）。

        **路由用机器名、回显用中文**（本控件的核心分工）：
            * ``service.submit(choice_id, "choice")`` —— ``intent_router.resolve_choice``
              靠 ``choice_id`` 在 ``pending[]`` 里找 ``transform``/``args``，**必须**是它；
            * ``submitted`` 信号发 **label** —— 页面据此回显「玩家做了什么」。
              若照发 ``choice_id``，玩家会在叙述流里看到自己的动作变成 ``sit_down``。
        """
        if self._busy:
            return
        if self._invoke_submit(choice_id, "choice"):
            self.submitted.emit(label or choice_id, "choice")

    # ------------------------------------------------------------------
    # 自由输入
    # ------------------------------------------------------------------
    def _on_send(self, *_args: Any) -> None:
        """发送（Enter / 按钮）：文本非空且非忙时才提交。"""
        if self._busy:
            return
        text = self._edit.toPlainText().strip()
        if not text:
            return
        if self._invoke_submit(text, "free"):
            self._edit.clear()
            self._autosize()
            self.submitted.emit(text, "free")

    def _autosize(self) -> None:
        """按内容行数自适应输入框高度（复用 ``chat_input_logic.compute_input_height``）。"""
        try:
            doc_height = self._edit.document().size().height()
            spacing = self._edit.fontMetrics().lineSpacing()
            height = compute_input_height(
                doc_height, spacing, min_height=48, max_lines=6, padding=16,
            )
        except Exception:
            logger.debug("输入框自适应高度失败（忽略）", exc_info=True)
            return
        self._edit.setFixedHeight(int(height))

    def _invoke_submit(self, text: str, kind: str) -> bool:
        """调用 ``service.submit(text, input_kind)``（位置参数；异常吞掉不崩）。"""
        fn = getattr(self._service, "submit", None)
        if not callable(fn):
            return False
        try:
            return bool(fn(text, kind))
        except Exception:
            logger.debug("酒馆提交失败（忽略）", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # 忙态（进行中：文字节奏，**不新画动画**）
    # ------------------------------------------------------------------
    def set_busy(self, busy: Any) -> None:
        """生成中：禁用提交 + 中性「进行中」文字节奏提示。"""
        busy = bool(busy)
        self._busy = busy
        self._send_btn.setEnabled(not busy)
        self._edit.setEnabled(not busy)
        for btn in self._choice_buttons:
            btn.setEnabled(not busy)
        if busy:
            self._start_busy()
        else:
            self._stop_busy()
            self._render_hint()

    def _start_busy(self) -> None:
        """先落静态文案（立即出现提示），再用既有循环能力做省略号节奏。"""
        self._busy_text = "她正在想"
        self._set_hint(self._busy_text + "…", "text_hint")
        self._busy_handle = None
        handle = motion.loop(
            self, self._on_busy_tick,
            period_ms=_BUSY_PERIOD_MS, on_disabled=self._on_busy_disabled,
        )
        if handle is not None:
            self._busy_handle = handle

    def _stop_busy(self) -> None:
        handle = self._busy_handle
        self._busy_handle = None
        if handle is not None:
            motion.stop_loop(handle)  # 显式停止：不触发 on_disabled
        self._busy_text = ""

    def _on_busy_tick(self, progress: float) -> None:
        if not self._busy:
            return
        index = int(progress * len(_BUSY_DOTS))
        if index >= len(_BUSY_DOTS):
            index = len(_BUSY_DOTS) - 1
        self._set_hint(self._busy_text + _BUSY_DOTS[index], "text_hint")

    def _on_busy_disabled(self) -> None:
        """因禁用而停（切 ``off`` / 系统关动画）→ 切静态文案，不得空白。"""
        self._busy_handle = None
        if self._busy:
            self._set_hint(self._busy_text + "…", "text_hint")

    # ------------------------------------------------------------------
    # 行内提示（degraded / 忙态；**永不弹窗**）
    # ------------------------------------------------------------------
    def show_hint(self, text: Any) -> None:
        """显示一行中性提示（接 ``degraded``）；**不弹 QMessageBox**。"""
        self._degraded_text = text if isinstance(text, str) else ""
        if not self._busy:
            self._render_hint()

    def clear_hint(self) -> None:
        """清空降级提示。"""
        self._degraded_text = ""
        if not self._busy:
            self._render_hint()

    def _render_hint(self) -> None:
        """按状态渲染提示条：忙态优先；否则显示降级文案（state_warn）；都没有则隐藏。"""
        if self._busy:
            return  # 忙态由文字节奏驱动
        if self._degraded_text:
            self._set_hint(self._degraded_text, "state_warn")
        else:
            self._set_hint("", "text_hint")

    def _set_hint(self, text: str, color_key: str) -> None:
        """设置提示文案 + 现取语义色（**不缓存色值**）。"""
        self._hint.setText(text)
        color = self._tc(color_key, "#9A9A9A")
        self._hint.setStyleSheet(f"color: {color}; background: transparent;")
        self._hint.setVisible(bool(text))

    # ------------------------------------------------------------------
    # 只读态 / 刷新
    # ------------------------------------------------------------------
    def set_read_only(self, read_only: Any) -> None:
        """只读会话标记（可玩、不落盘；提示由 service 的 ``degraded`` 承担，不重复上屏）。"""
        self._read_only = bool(read_only)

    def _on_play_changed(self, *_args: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        """从服务查询面拉取选项 / 忙态 / 只读态（首帧 / ``on_enter`` / 切局）。"""
        try:
            choices = self._service.current_choices()
        except Exception:
            logger.debug("读取酒馆选项失败（忽略）", exc_info=True)
            choices = []
        self.set_choices(choices)
        try:
            self.set_busy(self._service.is_busy())
        except Exception:
            logger.debug("读取酒馆忙态失败（忽略）", exc_info=True)
        try:
            self.set_read_only(self._service.is_read_only())
        except Exception:
            logger.debug("读取酒馆只读态失败（忽略）", exc_info=True)

    # ------------------------------------------------------------------
    # 只读查询（测试 / 页面）
    # ------------------------------------------------------------------
    def choice_buttons(self) -> List[QPushButton]:
        """当前选项按钮列表。"""
        return list(self._choice_buttons)

    def send_button(self) -> QPushButton:
        """发送按钮（测试断言禁用态用）。"""
        return self._send_btn

    def input_edit(self) -> QPlainTextEdit:
        """自由输入框（测试断言禁用态 / 提交用）。"""
        return self._edit

    def hint_text(self) -> str:
        """当前行内提示文案。"""
        return self._hint.text()


# ===========================================================================
# 纯函数：选项形状归一（双形状兼容）
# ===========================================================================

#: 选项**缺 ``label``** 时的中性占位。
#: 单一来源口径 = :data:`gui.tavern.service.NEUTRAL_CHOICE_LABEL`（本控件属控件层，不 import
#: 服务层模块；两处取值由 ``tests/test_v22_widgets_core.py`` 断言恒等，防漂移）。
#: 不变量：按钮与玩家条**任何路径**都不得出现 ``choice_id`` 形态的机器名 ——
#: 缺中文名时给一句中性中文，**绝不**回落 ``value``（那正是机器名）。
_NEUTRAL_CHOICE_LABEL: str = "（未命名的动作）"


def _normalize_choices(payload: Any) -> List[dict]:
    """把 ``choices_changed`` 载荷归一为 ``[{"value", "label", "kind"}]``。

    兼容两种形状：
        * 真实 ``service.current_choices()``：``{"choice_id", "label"}``；
        * 兼容别名：``{"value", "text", "kind"}``。

    ★ 缺 ``label``（含**全空白**）时**中性化**：给 :data:`_NEUTRAL_CHOICE_LABEL`，
    **绝不**回落 ``value``（``value`` 是 router 用的机器名，回落会让 ``sit_down`` 这类
    下划线机器名上按钮）。口径与 ``service._choice_snapshot``（``.strip() or 中性``）一致。
    """
    out: List[dict] = []
    if not isinstance(payload, (list, tuple)):
        return out
    for item in payload:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("choice_id") or item.get("id")
        if not isinstance(value, str) or not value:
            continue
        raw_label = item.get("label") or item.get("text")
        label = raw_label.strip() if isinstance(raw_label, str) else ""
        if not label:
            label = _NEUTRAL_CHOICE_LABEL
        kind = item.get("kind")
        out.append({"value": value, "label": label, "kind": kind if isinstance(kind, str) else "choice"})
    return out
