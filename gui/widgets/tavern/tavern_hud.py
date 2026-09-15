"""gui/widgets/tavern/tavern_hud.py —— 酒馆顶部状态条（V22-07 / 域6）。

设计依据 ``docs/design-v22.md``：
    · §6.1/§6.2 顶部「章标题」条（``tavern_hud``）；
    · **R-A 硬约束 + Q4**：界面**零序号、零数值** —— 只显示**章标题**，**绝不**出现
      「第 N 夜 / 幕」这类序号，**绝不**出现计数 / 评分 / 进度数值；
      ``turn`` 字段**可用于内部逻辑**（如判断是否首拍），但**绝不当数字上屏**；
    · §6.3  颜色只走 ``theme_color`` 语义键（**禁在 ``__init__`` 缓存色值**）；
    · §7    ``read_only`` / ``busy`` 一眼可见用**状态点 / 文字**（**不用进度条**），
            状态点保持静态形态（不新增几何母题）。

============================  数据来源与接线契约（必读）  ============================
本控件**只经 TavernService 的信号**更新（不直接读写 store）：

信号（**本控件自行订阅**，页面**不要**再重复连接）：
    · ``hud_changed(dict)`` —— 载荷**双形状兼容**：
        · 真实 service：``{"chapter_title", "scene_id", "held_items", "read_only", "degraded"}``；
        · 兼容别名：``{"title" / "chapter", "scene", "held_items", "read_only", "busy", "turn"}``。
    · ``read_only_changed(bool)`` / ``busy_changed(bool)`` —— 状态点与状态文字。
    · ``play_changed(str)`` —— 切局 → 从查询面 :meth:`refresh` 重建。

**谁订阅 ``theme_engine.theme_changed``**：由**页面拥有者**（``PageTavern``）做总订阅，
收到后调用 :meth:`TavernHud.apply_theme`；本控件**不自行订阅** ``theme_changed``。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from gui.qt_compat import QFrame, QHBoxLayout, QLabel, QWidget, Qt

logger = logging.getLogger("maling.tavern.widgets.hud")

#: R-A 守卫用正则（**只作防御**：正常路径内容包已保证零序号 / 零数值）。
_ORDINAL_RE = re.compile(r"第\s*[0-9]+\s*[夜幕回合章节轮次]")
_PROGRESS_RE = re.compile(r"[0-9]+\s*/\s*[0-9]+")
_PERCENT_RE = re.compile(r"[0-9]+\s*%")
_DIGITS_RE = re.compile(r"[0-9]+")
_SEP_EDGE_RE = re.compile(r"^[\s·,，、\-—:：]+|[\s·,，、\-—]+$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

#: 主题语义键兜底值（仅 ``theme_color`` 不可用时使用）。
_COLOR_FALLBACKS: Dict[str, str] = {
    "bg_card": "#FFFFFF",
    "bg_light": "#F5F5F5",
    "divider": "#E8E8E8",
    "accent": "#FF6B9D",
    "text_secondary": "#888888",
    "text_hint": "#9A9A9A",
    "state_ok": "#4CAF50",
    "state_warn": "#A96A12",
}

_QSS_TEMPLATE: str = """
QFrame#tavern_hud {
    background-color: %(bg_card)s;
    border: 1px solid %(divider)s;
    border-radius: 10px;
}
QLabel#tavernHudChapter {
    color: %(accent)s;
    background: transparent;
}
QLabel#tavernHudScene {
    color: %(text_secondary)s;
    background: transparent;
}
QLabel#tavernHudItem {
    color: %(text_secondary)s;
    background-color: %(bg_light)s;
    border: 1px solid %(divider)s;
    border-radius: 10px;
    padding: 1px 8px;
}
QLabel#tavernHudStatus {
    color: %(text_hint)s;
    background: transparent;
}
"""

__all__ = ["TavernHud"]


class TavernHud(QFrame):
    """顶部状态条（``objectName = "tavern_hud"``）：章标题 + 场景 + 随身之物 + 状态点。

    公共 API（供页面装配）：
        * :meth:`apply_hud` —— 应用 ``hud_changed`` 载荷（双形状兼容）；
        * :meth:`set_read_only` / :meth:`set_busy` —— 状态点 / 状态文字；
        * :meth:`refresh` —— 从 ``service.current_hud()`` 拉取重建；
        * :meth:`apply_theme` —— 现取主题色重刷内联 QSS（页面在 ``theme_changed`` 时调用）；
        * :meth:`chapter_text` / :meth:`label_texts` —— 测试查询。
    """

    def __init__(self, service: Any, app_ctx: Any = None, parent: Optional[QWidget] = None) -> None:
        """构造顶部状态条。

        Args:
            service: ``TavernService``（或同名信号 / 方法的桩对象）。
            app_ctx: 应用上下文（本控件经 ``service.theme_color`` 取色，仅作兜底保留）。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self._service = service
        self._app_ctx = app_ctx
        self._read_only = False
        self._busy = False
        self._item_labels: List[QLabel] = []
        self.setObjectName("tavern_hud")
        self._build_ui()
        self._connect_service()
        self.apply_theme()
        self.refresh()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """搭建：章标题 → 场景 → 弹性空隙 → 随身之物 → 状态点 + 状态文字。"""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)

        self._chapter = QLabel("", self)
        self._chapter.setObjectName("tavernHudChapter")
        row.addWidget(self._chapter)

        self._scene = QLabel("", self)
        self._scene.setObjectName("tavernHudScene")
        self._scene.setVisible(False)
        row.addWidget(self._scene)

        row.addStretch(1)

        self._items_host = QWidget(self)
        self._items_host.setObjectName("tavernHudItems")
        self._items_layout = QHBoxLayout(self._items_host)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(6)
        self._items_host.setVisible(False)
        row.addWidget(self._items_host)

        self._dot = QLabel("", self)
        self._dot.setObjectName("tavernHudDot")
        self._dot.setFixedSize(8, 8)
        row.addWidget(self._dot)

        self._status = QLabel("", self)
        self._status.setObjectName("tavernHudStatus")
        row.addWidget(self._status)

    def _connect_service(self) -> None:
        """自行订阅 TavernService 的数据信号（页面**不要**重复连接）。"""
        for name, slot in (
            ("hud_changed", self.apply_hud),
            ("read_only_changed", self.set_read_only),
            ("busy_changed", self.set_busy),
            ("play_changed", self._on_play_changed),
        ):
            sig = getattr(self._service, name, None)
            if sig is None or not hasattr(sig, "connect"):
                continue
            try:
                sig.connect(slot)
            except Exception:
                logger.debug("订阅酒馆状态条信号失败: %s", name, exc_info=True)

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
                logger.debug("状态条取主题色失败: %s", key, exc_info=True)
        return fallback

    def apply_theme(self) -> None:
        """现取主题色重建内联 QSS（**不缓存色值**）；随后按当前状态重刷状态点。"""
        colors = {k: self._tc(k, v) for k, v in _COLOR_FALLBACKS.items()}
        try:
            self.setStyleSheet(_QSS_TEMPLATE % colors)
        except Exception:
            logger.debug("状态条应用主题样式失败（忽略）", exc_info=True)
        self._apply_status()

    # ------------------------------------------------------------------
    # 载荷应用
    # ------------------------------------------------------------------
    def apply_hud(self, payload: Any) -> None:
        """应用 ``hud_changed`` 载荷（双形状兼容；**零序号 / 零数值**）。"""
        data = payload if isinstance(payload, dict) else {}
        title = _first_str(data.get("chapter_title")) or _first_str(data.get("chapter")) \
            or _first_str(data.get("title"))
        scene = _first_str(data.get("scene_id")) or _first_str(data.get("scene"))

        self._chapter.setText(_sanitize(title))
        if _looks_human(scene):
            self._scene.setText(_sanitize(scene))
        else:
            self._scene.setText("")
        self._scene.setVisible(bool(self._scene.text()))

        self._set_items(data.get("held_items"))

        read_only = data.get("read_only")
        if isinstance(read_only, bool):
            self._read_only = read_only
        busy = data.get("busy")
        if isinstance(busy, bool):
            self._busy = busy
        # ``turn`` / ``degraded`` 仅内部语义（**不上屏**）：turn 绝不当数字显示。
        self._apply_status()

    def set_read_only(self, read_only: Any) -> None:
        """只读会话开关 → 状态点 / 状态文字。"""
        self._read_only = bool(read_only)
        self._apply_status()

    def set_busy(self, busy: Any) -> None:
        """生成中开关 → 状态点 / 状态文字。"""
        self._busy = bool(busy)
        self._apply_status()

    def _set_items(self, items: Any) -> None:
        """重建「随身之物」小标签（**零数值**）。"""
        while self._items_layout.count():
            entry = self._items_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._item_labels = []

        if isinstance(items, (list, tuple)):
            for name in items:
                if not isinstance(name, str) or not name:
                    continue
                text = _sanitize(name)
                if not text:
                    continue
                label = QLabel(text, self._items_host)
                label.setObjectName("tavernHudItem")
                self._items_layout.addWidget(label)
                self._item_labels.append(label)
        self._items_host.setVisible(bool(self._item_labels))

    def _apply_status(self) -> None:
        """按忙 / 只读状态设置状态点颜色与文字（**无进度条、无数字**）。"""
        if self._busy:
            self._status.setText("正在续写…")
            color = self._tc("state_warn", "#A96A12")
        elif self._read_only:
            self._status.setText("只读存档")
            color = self._tc("text_hint", "#9A9A9A")
        else:
            self._status.setText("")
            color = self._tc("state_ok", "#4CAF50")
        self._dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")

    def _on_play_changed(self, *_args: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        """从 ``service.current_hud()`` 拉取重建（首帧 / ``on_enter`` / 切局）。"""
        try:
            hud = self._service.current_hud()
        except Exception:
            logger.debug("读取酒馆状态条失败（忽略）", exc_info=True)
            hud = {}
        self.apply_hud(hud)
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
    def chapter_text(self) -> str:
        """当前章标题文本。"""
        return self._chapter.text()

    def label_texts(self) -> List[str]:
        """状态条内全部可见文本（章标题 / 场景 / 随身之物 / 状态文字）。"""
        texts = [self._chapter.text(), self._scene.text(), self._status.text()]
        texts.extend(label.text() for label in self._item_labels)
        return [t for t in texts if t]


# ===========================================================================
# 纯函数：R-A 文本守卫
# ===========================================================================

def _sanitize(text: Any) -> str:
    """清洗待上屏文本：去序号 / 进度 / 百分比 / **全部 ASCII 数字**（R-A 防御纵深）。

    正常路径内容包已保证零序号、零数值，本函数为**兜底守卫**：即便上游误传「第 3 夜」
    或进度数值，界面亦不会出现序号 / 数值（对齐 §6.2 / Q4）。
    """
    if not isinstance(text, str):
        return ""
    out = _ORDINAL_RE.sub("", text)
    out = _PROGRESS_RE.sub("", out)
    out = _PERCENT_RE.sub("", out)
    out = _DIGITS_RE.sub("", out)
    out = _SEP_EDGE_RE.sub("", out)
    return out.strip()


def _first_str(value: Any) -> str:
    """取首个非空字符串（否则空串）。"""
    return value.strip() if isinstance(value, str) else ""


def _looks_human(text: Any) -> bool:
    """场景是否适合上屏：含中日韩字、无 ASCII 数字、无下划线（否则视为机器 id，隐藏）。"""
    if not isinstance(text, str) or not text.strip():
        return False
    if _DIGITS_RE.search(text) or "_" in text:
        return False
    return bool(_CJK_RE.search(text))
