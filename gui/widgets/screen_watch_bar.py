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
from gui import icons

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

        # 本控件用**类名选择器**给自己写底色/描边/圆角（见 ``_apply_theme`` 里的
        # ``ScreenWatchBar { background: ...; border: ...; border-radius: ... }``），
        # 但它是 Python 的 ``QWidget`` 子类 → Qt 不会自动置 ``WA_StyledBackground``
        # （详见 ``MainWindow._ensure_page_backgrounds`` 的实测表）。属性缺失时
        # ``QWidget::paintEvent`` 不发 ``PE_Widget`` → **底色、1px 描边、圆角三者
        # 全不绘制**（毛玻璃下链路已 transparent，直接呈透明列）。故构造期显式置位；
        # 仅补属性，不动任何 QSS / 配色 / 尺寸。
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(12, 2, 12, 2)
        self._row.setSpacing(8)

        # v2.x 落点③（阶段 B「融入度」复核后**回退**）：**不再新增指示图形**。
        # 原 ``LoopIndicator("ripple")`` 经复核判为**外来母题**（涟漪 = 声呐/雷达，
        # 码铃别处无此词汇），且与紧邻的 👀 **语义重复**；本控件原本亦无任何图形。
        # 故回到"👀 文案即指示"的克制形态。详见 ``_phaseB_report.md §2③``。
        # （已无循环动效 → 本控件不再有 hideEvent/showEvent 停启逻辑。）

        self._status = QLabel(self._compose_text())
        self._status.setObjectName("screenWatchStatus")
        self._status.setWordWrap(True)
        self._row.addWidget(self._status, 1)

        self._peek_btn = QPushButton(f"{icons.text_glyph('camera', '📷')} 看一帧")
        self._peek_btn.setObjectName("screenWatchBtn")
        self._peek_btn.setCursor(Qt.PointingHandCursor)
        self._peek_btn.setFixedHeight(24)
        self._peek_btn.setToolTip("马上采集一帧，让码铃看一眼当前屏幕（消耗少量 token）")
        self._peek_btn.clicked.connect(lambda: self.peek_requested.emit())
        self._row.addWidget(self._peek_btn)

        self._ask_btn = QPushButton(f"{icons.text_glyph('search', '🔍')} 按当前屏提问")
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

        self._close_btn = QPushButton(f"{icons.text_glyph('close', '✕')} 关")
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
        # v2.1(修复 #279)：👀 走 text_glyph（「在看/眼睛」语义 → 已登记的 eye-line 名
        # ``watch``）；图标字体不可用时原样回落 emoji。▶/⏸ 保留裸符号：manifest 未登记
        # 语义贴切的「播放/暂停」名（``motion``=play-circle-line 语义为「动效」、
        # ``stop``=stop-circle-line 语义为「停止」），硬套会引入误导 → 不凑。
        eye = icons.text_glyph("watch", "👀")
        if self._state == STATE_PAUSED:
            return "⏸ 看屏已暂停（已达单会话帧上限）· 已分析 {} 帧 · 点「▶ 续开」可继续".format(self._frames)
        if self._state == STATE_IDLE:
            return eye + " 看屏未开启"
        k = self._tokens / 1000.0
        token_txt = "≈{}k tokens".format(f"{k:.0f}" if k >= 10 else f"{k:.1f}") if k else "≈0k tokens"
        # v1.9(V19-16/D-V19-14): D 风格（ui_whale）状态 chip 自称随当前角色
        who = brand_persona_self(self.app_ctx) or "码铃"
        if self._ask_pending:
            return eye + " {}在看 · 已分析 {} 帧 · {} · {} 下一条将带上当前屏幕".format(
                who, self._frames, token_txt, icons.text_glyph("search", "🔍")
            )
        return eye + " {}在看 · 已分析 {} 帧 · {}".format(who, self._frames, token_txt)

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
            # 对比度修复（第4组）：本控件**没有**状态点图形 —— 旧名 ``dot`` 遗留至今，
            # 它唯一去向是 ``_btn_ss`` 第 3 参 → 只落 ``:checked`` 的**选中填充底**。
            # 该填充配 ``text_on_accent`` 实测 5.208/5.984/6.485/5.192（合格），
            # **不得**换成 accent_text：换后字底配对掉到 3.513/2.628/6.507/3.414
            # （ui_cream 连 3.0 都不过）；仓库 tests/test_v21_settings.py 亦明确
            # accent_text 是「文字用」色、当填充配深字只有 3.51，不可一色两用。
            checked_fill = theme_color(self.app_ctx, "accent", "#FF6B9D")
            if self._state == STATE_PAUSED:
                checked_fill = theme_color(self.app_ctx, "state_warn", "#E5A02E")
            elif self._state == STATE_IDLE:
                checked_fill = theme_color(self.app_ctx, "disabled_text", "#9E9E9E")
            text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
            text_on_accent = theme_color(self.app_ctx, "text_on_accent", "#FFFFFF")
            # 真正直接压在 surface_muted 上、且 <3:1 的是**按钮描边**：原取「填充用」
            # accent，实测 3.159/2.102/6.183/3.079（ui_cream 2.102 不过，非文字图形需 ≥3）
            # → 描边改用更深一档的「强调色系」accent_text（4.684/4.785/6.204/4.683）。
            # 只换描边取色键，**不碰**选中填充与字色配对。
            outline = theme_color(self.app_ctx, "accent_text", "#B45073")
            border = theme_color(self.app_ctx, "border", "#FFE4E1")
            bg = theme_color(self.app_ctx, "surface_muted", "#FFF9FA")
            self.setStyleSheet(
                f"ScreenWatchBar {{ background: {bg}; border: 1px solid {border};"
                f" border-radius: 10px; }}"
            )
            self._status.setStyleSheet(
                f"color: {text}; font-size: 11px; background: transparent;"
            )
            self._peek_btn.setStyleSheet(self._btn_ss(outline, text_on_accent, checked_fill))
            self._ask_btn.setStyleSheet(self._btn_ss(outline, text_on_accent, checked_fill))
            self._resume_btn.setStyleSheet(self._btn_ss(outline, text_on_accent, checked_fill))
            self._close_btn.setStyleSheet(self._btn_ss(outline, text_on_accent, checked_fill))
        except Exception:
            pass

    def _btn_ss(self, outline: str, on_accent: str, checked_fill: str) -> str:
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        # 对比度修复（hover 只换底、未声明 color）：`:hover` 不声明字色时，若按钮同时
        # 命中 `:checked`，字色会沿用 `:checked` 的 on_accent（四风格**恒深色**），
        # 而 hover 换上的 bg_light 是「随主题翻转」的淡填充 → 深色模式 / ui_night
        # 下深字落深底。实测悬停已选中：ui_minimal+dark 1.107、ui_night 明/暗 1.220、
        # ui_whale+dark 1.032（均 <4.5）。→ 显式补 `color: text`；text 正是 bg_light
        # 的配对文字键，同样随主题翻转（浅色 14.492/11.556/12.503/11.980，
        # 深色 13.160/11.561/12.503/11.575）。底色与常态均未动。
        text = theme_color(self.app_ctx, "text", "#6D4A85")
        return (
            f"QPushButton#screenWatchBtn {{"
            f"  background: transparent; border: 1px solid {outline}; border-radius: 10px;"
            f"  color: {text};"
            f"  font-size: 11px; padding: 2px 10px;"
            f"}}"
            f"QPushButton#screenWatchBtn:checked {{"
            f"  background: {checked_fill}; color: {on_accent}; border-color: {outline};"
            f"}}"
            f"QPushButton#screenWatchBtn:hover {{ background: {bg_light}; color: {text}; }}"
        )

    # v2.x 落点③回退后：本控件**已无循环动效**（涟漪已移除），故不再需要
    # hideEvent/showEvent 的"隐藏即停 / 显示复启"逻辑；主题变更由
    # ``_on_theme_changed`` 承接（`theme_changed` 信号）。
