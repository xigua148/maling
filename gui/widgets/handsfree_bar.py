# -*- coding: utf-8 -*-
"""免提状态条 —— v1.3 P2-2（design-v13 D-V13-07）

聊天面板顶部常驻的免提状态条：醒目标识 + 实时状态 + 「⏹ 停止」按钮。

- 对外只报状态、不发业务：状态/文案由 chat_panel 依据
  VoiceConversationController.state_changed / notice 驱动刷新；
  「⏹ 停止」按钮发出 stop_requested 信号，由面板回调 controller.stop()。
- 颜色全部经 theme_color() 取活动色板（深色模式可用），无裸硬编码。
- 主题切换（theme_changed）时自动重刷配色。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import QWidget, QHBoxLayout, QLabel, QPushButton, Signal, Qt
from gui.utils import theme_color
from gui import icons
from gui.widgets.loop_indicator import LoopIndicator


def state_texts() -> dict:
    """免提各状态文案（运行时构建：图标字形随图标字体可用性 / 主题自动定）。

    v2.1(D-V21-06): 状态图标改用 ``icons.text_glyph``，图标不可用时
    原样回落 emoji（不空白、不崩）。禁止改为模块级常量（启动期字体未注册）。
    """
    return {
        "idle": f"免提未开启：点下方「{icons.text_glyph('voice', '🎙')} 免提」即可开口发消息（说「暂停」或敲键盘会自动停下）",
        "listening": f"{icons.text_glyph('headphone', '🎧')} 免提中 · 我在听，主人直接说就好～（开始打字/动鼠标会自动暂停）",
        "recognizing": "👂 听到了，正在识别…",
        "sending": f"{icons.text_glyph('send', '📨')} 正在发送给码铃… 稍等一下下~",
        "speaking": f"{icons.text_glyph('volume', '🔊')} 码铃正在把回答读给主人听…",
    }


class HandsfreeBar(QWidget):
    """免提状态条：状态文案 + 常驻 ⏹ 停止（仅在免提激活期间可见）。"""

    stop_requested = Signal()

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._state: str = "idle"

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 2, 12, 2)
        self._row.setSpacing(8)

        # v2.x 落点②（阶段 B「融入度」复核后**回退**）：listening 态动效 =
        # **单点 ● 呼吸**（``LoopIndicator("pulse")``）。
        # 原 4 柱「弹跳柱条」经复核判为**外来母题** —— 柱条在通用软件里固定表示
        # "音频电平 / 录音"，与本控件自述"**非音频电平**"（见下 R-B/R-A）
        # **语义自相矛盾**；故回退为应用既有的"单点呼吸"语言
        # （也是本控件改造前的原貌）。详见 ``_phaseB_report.md §2②``。
        # R-P：隐藏即停（hideEvent → pause）；R-Q：off 档画**静态实心点**（不空白）。
        # R-B/R-A：仍为纯 UI 形态，**非音频电平**（无波形分析、无音量映射）。
        self._indicator = LoopIndicator("pulse", color="#FF6B9D", period_ms=1200)
        self._row.addWidget(self._indicator)

        self._status = QLabel(state_texts()["idle"])
        self._status.setObjectName("handsfreeStatus")
        self._status.setWordWrap(True)
        self._row.addWidget(self._status, 1)

        self._stop_btn = QPushButton(f"{icons.text_glyph('stop', '⏹')} 停止免提")
        self._stop_btn.setObjectName("handsfreeStopBtn")
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setFixedHeight(24)
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._row.addWidget(self._stop_btn)

        # 主题切换自刷配色
        engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
        if engine is not None and hasattr(engine, "theme_changed"):
            try:
                engine.theme_changed.connect(lambda _name: self._apply_theme())
            except Exception:
                pass

        self._apply_theme()
        self.set_state("idle")

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        texts = state_texts()
        self._state = state if state in texts else "idle"
        self._status.setText(texts.get(self._state, texts["idle"]))
        active = self._state != "idle"
        self._stop_btn.setVisible(active)
        self._apply_theme()
        # v2.x 落点②：4 柱循环仅 listening 态启停（经 motion.loop 收口）
        if self._state == "listening":
            self._indicator.start()
        else:
            self._indicator.stop()

    # ------------------------------------------------------------------
    # v2.x 落点②：R-P 隐藏即停（柱条循环停、保留 listening 意图，显示时复启）
    # ------------------------------------------------------------------
    def hideEvent(self, event) -> None:  # noqa: N802
        self._indicator.pause()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_theme()
        if self._state == "listening":
            self._indicator.resume()

    def set_notice(self, text: str) -> None:
        """一次性说明（识别失败/自动暂停等），2.4s 后回落为状态文案。"""
        if text:
            self._status.setText(text)
        try:
            from gui.qt_compat import QTimer
            QTimer.singleShot(2400, self._restore_from_notice)
        except Exception:
            pass

    def _restore_from_notice(self) -> None:
        try:
            if not self.isVisible():
                return
            texts = state_texts()
            self._status.setText(texts.get(self._state, texts["idle"]))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _on_stop_clicked(self) -> None:
        self.stop_requested.emit()

    def _apply_theme(self) -> None:
        try:
            idle_dot = theme_color(self.app_ctx, "disabled_text", "#9E9E9E")
            active_dot = theme_color(self.app_ctx, "accent", "#FF6B9D")
            text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
            text_on_accent = theme_color(self.app_ctx, "text_on_accent", "#FFFFFF")
            primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
            border = theme_color(self.app_ctx, "border", "#FFE4E1")
            dot = active_dot if self._state != "idle" else idle_dot
            bg = theme_color(self.app_ctx, "surface_muted", "#FFF9FA")
            self.setStyleSheet(
                f"HandsfreeBar {{ background: {bg}; border: 1px solid {border};"
                f" border-radius: 10px; }}"
            )
            self._indicator.set_color(dot)
            self._status.setStyleSheet(
                f"color: {text}; font-size: 11px; background: transparent;"
            )
            self._stop_btn.setStyleSheet(
                f"QPushButton#handsfreeStopBtn {{"
                f"  background: {primary}; color: {text_on_accent};"
                f"  border: none; border-radius: 10px; padding: 2px 12px; font-size: 11px;"
                f"}}"
                f"QPushButton#handsfreeStopBtn:hover {{"
                f"  background: {active_dot}; }}"
            )
        except Exception:
            pass
