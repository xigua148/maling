# -*- coding: utf-8 -*-
"""v1.4(B1b) 看屏状态条 chip —— 「👀 码铃在看 · 本会话已分析 N 帧 · ≈xk tokens」。

（design-v14 §2.4 / §5 B1b；仿 handsfree_bar 状态条先例，纯展示 + 按钮信号，不发业务）

- 对外只报状态与按钮：状态文案/帧数/消耗由 chat_panel 依据 ScreenWatchService
  watch_state_changed / stats_changed / paused 等驱动刷新；按钮仅发信号由面板接业务。
- 成本可见 = 帧数 + token 估算（本会话运行时读数，内存不落盘）；无数值/进度/养成墙（R-A）；
- 颜色全部 theme_color()（深色模式可用），theme_changed 自刷；
- v1.9(V19-16)：D 风格（ui_whale）下「码铃在看」的自称位随当前角色 given_name（界面口吻）。
- 折叠细账不另做：帧数/消耗在状态文案一行内，保证窄宽度不换行（elide 由面板 label 处理）。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import QWidget, QHBoxLayout, QLabel, QPushButton, Signal, Qt
from gui.utils import theme_color, brand_persona_self

STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_IDLE = "idle"


class ScreenWatchBar(QWidget):
    """看屏状态条：状态文案 + 📷 看一帧 / 🔍 按屏提问 / ▶ 续开 / ✕ 关闭。"""

    #: 一键关（停采弃帧）
    stop_requested = Signal()
    #: 看一帧（即时采集→送视觉）
    peek_requested = Signal()
    #: 按当前屏提问（toggle：点亮 = 下一条消息带当前屏帧）
    ask_screen_toggled = Signal(bool)
    #: 帧上限暂停后「续开」（重置会话计数重启）
    resume_requested = Signal()

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._state = STATE_IDLE
        self._frames = 0
        self._tokens = 0
        self._ask_pending = False

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 2, 12, 2)
        self._row.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._row.addWidget(self._dot)

        self._status = QLabel(self._compose_text())
        self._status.setObjectName("screenWatchStatus")
        self._status.setWordWrap(True)
        self._row.addWidget(self._status, 1)

        self._peek_btn = QPushButton("📷 看一帧")
        self._peek_btn.setObjectName("screenWatchBtn")
        self._peek_btn.setCursor(Qt.PointingHandCursor)
        self._peek_btn.setFixedHeight(24)
        self._peek_btn.setToolTip("马上采集一帧，让码铃看一眼当前屏幕（消耗少量 token）")
        self._peek_btn.clicked.connect(lambda: self.peek_requested.emit())
        self._row.addWidget(self._peek_btn)

        self._ask_btn = QPushButton("🔍 按当前屏提问")
        self._ask_btn.setObjectName("screenWatchBtn")
        self._ask_btn.setCursor(Qt.PointingHandCursor)
        self._ask_btn.setFixedHeight(24)
        self._ask_btn.setCheckable(True)
        self._ask_btn.setToolTip("点亮后，下一条发给码铃的消息会自动带上当前屏幕截图")
        self._ask_btn.toggled.connect(self._on_ask_toggled)
        self._row.addWidget(self._ask_btn)

        self._resume_btn = QPushButton("▶ 续开")
        self._resume_btn.setObjectName("screenWatchBtn")
        self._resume_btn.setCursor(Qt.PointingHandCursor)
        self._resume_btn.setFixedHeight(24)
        self._resume_btn.setToolTip("重置本会话帧计数后继续看屏")
        self._resume_btn.clicked.connect(lambda: self.resume_requested.emit())
        self._resume_btn.setVisible(False)
        self._row.addWidget(self._resume_btn)

        self._close_btn = QPushButton("✕ 关")
        self._close_btn.setObjectName("screenWatchBtn")
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.setFixedHeight(24)
        self._close_btn.setToolTip("关闭看屏，立即停采并丢弃内存帧")
        self._close_btn.clicked.connect(lambda: self.stop_requested.emit())
        self._row.addWidget(self._close_btn)

        engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
        if engine is not None and hasattr(engine, "theme_changed"):
            try:
                engine.theme_changed.connect(lambda _name: self._on_theme_changed())
            except Exception:
                pass

        self._apply_theme()
        self.set_state(STATE_IDLE)

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def set_state(self, state: str) -> None:
        """running / paused / idle；状态文案 + 按钮可用性随状态刷新。"""
        self._state = state if state in (STATE_RUNNING, STATE_PAUSED, STATE_IDLE) else STATE_IDLE
        self._refresh_buttons()
        self._refresh_text()
        self._apply_theme()

    def set_stats(self, frames: int, tokens: int) -> None:
        self._frames = max(0, int(frames or 0))
        self._tokens = max(0, int(tokens or 0))
        self._refresh_text()

    def set_ask_pending(self, pending: bool) -> None:
        """外部同步「按屏提问」点亮态（发送后自动熄灭）。"""
        pending = bool(pending)
        if pending == self._ask_pending:
            return
        self._ask_btn.blockSignals(True)
        try:
            self._ask_btn.setChecked(pending)
        finally:
            self._ask_btn.blockSignals(False)
        self._ask_pending = pending
        self._refresh_text()

    def ask_pending(self) -> bool:
        return self._ask_pending

    def state(self) -> str:
        return self._state

    def set_notice(self, text: str) -> None:
        """一次性说明（自动暂停等），2.6s 后回落为状态文案。"""
        if text:
            self._status.setText(text)
        try:
            from gui.qt_compat import QTimer
            QTimer.singleShot(2600, self._restore_text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_ask_toggled(self, checked: bool) -> None:
        self._ask_pending = bool(checked)
        self._refresh_text()
        try:
            self.ask_screen_toggled.emit(self._ask_pending)
        except Exception:
            pass

    def _compose_text(self) -> str:
        if self._state == STATE_PAUSED:
            return "⏸ 看屏已暂停（已达单会话帧上限）· 已分析 {} 帧 · 点「▶ 续开」可继续".format(self._frames)
        if self._state == STATE_IDLE:
            return "👀 看屏未开启"
        k = self._tokens / 1000.0
        token_txt = "≈{}k tokens".format(f"{k:.0f}" if k >= 10 else f"{k:.1f}") if k else "≈0k tokens"
        # v1.9(V19-16/D-V19-14): D 风格（ui_whale）状态 chip 自称随当前角色
        who = brand_persona_self(self.app_ctx) or "码铃"
        if self._ask_pending:
            return "👀 {}在看 · 已分析 {} 帧 · {} · 🔍 下一条将带上当前屏幕".format(who, self._frames, token_txt)
        return "👀 {}在看 · 已分析 {} 帧 · {}".format(who, self._frames, token_txt)

    def _on_theme_changed(self) -> None:
        """主题切换：重刷配色 + 状态 chip 口吻（D 风格自称即时生效）。"""
        self._apply_theme()
        self._refresh_text()

    def _refresh_text(self) -> None:
        try:
            self._status.setText(self._compose_text())
        except RuntimeError:
            pass

    def _refresh_buttons(self) -> None:
        active = self._state == STATE_RUNNING
        paused = self._state == STATE_PAUSED
        self._peek_btn.setVisible(active)
        self._ask_btn.setVisible(active)
        self._resume_btn.setVisible(paused)
        # 关闭按钮始终可见（暂停态也允许关闭回到完全停采）

    def _restore_text(self) -> None:
        try:
            if not self.isVisible():
                return
            self._refresh_text()
        except RuntimeError:
            pass

    def _apply_theme(self) -> None:
        try:
            dot = theme_color(self.app_ctx, "accent", "#FF6B9D")
            if self._state == STATE_PAUSED:
                dot = theme_color(self.app_ctx, "state_warn", "#E5A02E")
            elif self._state == STATE_IDLE:
                dot = theme_color(self.app_ctx, "disabled_text", "#9E9E9E")
            text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
            text_on_accent = theme_color(self.app_ctx, "text_on_accent", "#FFFFFF")
            primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
            border = theme_color(self.app_ctx, "border", "#FFE4E1")
            bg = theme_color(self.app_ctx, "surface_muted", "#FFF9FA")
            self.setStyleSheet(
                f"ScreenWatchBar {{ background: {bg}; border: 1px solid {border};"
                f" border-radius: 10px; }}"
            )
            self._dot.setStyleSheet(f"color: {dot}; font-size: 10px;")
            self._status.setStyleSheet(
                f"color: {text}; font-size: 11px; background: transparent;"
            )
            self._peek_btn.setStyleSheet(self._btn_ss(primary, text_on_accent, dot))
            self._ask_btn.setStyleSheet(self._btn_ss(primary, text_on_accent, dot))
            self._resume_btn.setStyleSheet(self._btn_ss(primary, text_on_accent, dot))
            self._close_btn.setStyleSheet(self._btn_ss(primary, text_on_accent, dot))
        except Exception:
            pass

    def _btn_ss(self, primary: str, on_accent: str, accent: str) -> str:
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        return (
            f"QPushButton#screenWatchBtn {{"
            f"  background: transparent; border: 1px solid {primary}; border-radius: 10px;"
            f"  color: {theme_color(self.app_ctx, 'text', '#6D4A85')};"
            f"  font-size: 11px; padding: 2px 10px;"
            f"}}"
            f"QPushButton#screenWatchBtn:checked {{"
            f"  background: {accent}; color: {on_accent}; border-color: {accent};"
            f"}}"
            f"QPushButton#screenWatchBtn:hover {{ background: {bg_light}; }}"
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_theme()
