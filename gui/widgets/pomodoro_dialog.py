"""gui/widgets/pomodoro_dialog.py —— v1.4(A3) 番茄钟浮窗视图（「她陪你专注」）

docs/design-v14.md D-V14-04：无状态视图（逻辑全在 gui/pomodoro.PomodoroController），
关闭 = 隐藏、计时继续（controller 持有状态）；再开恢复显示。范围严格 A10 口径：
不做成绩/统计/连续天数/任何历史累计（R-A/R-E）。

UI：阶段名 + 大字剩余时间 + 专注/休息时长选择 + 开始/暂停/跳过 + 中性说明
（到点只轻轻提醒，不记成绩）。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import (
    QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QComboBox, QFrame, Qt, QFont,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# 与 gui/pomodoro.py 保持同源（避免环 import，仅此两个表重复列出）
_WORK_OPTIONS = (15, 20, 25, 30, 40, 50, 60)
_BREAK_OPTIONS = (3, 5, 10, 15, 20, 25)


class PomodoroDialog(QDialog):
    """番茄钟浮窗（非 modal；关闭即隐藏，计时不中断）。"""

    def __init__(self, app_ctx, controller=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        # 兼容：无外部 controller 时懒建 app 级单例
        if controller is None:
            from gui.pomodoro import get_pomodoro_controller
            controller = get_pomodoro_controller(app_ctx)
        self.controller = controller
        self.setWindowTitle("🍅 她陪你专注")
        self.setModal(False)
        self.resize(360, 320)
        self.setMinimumSize(340, 300)

        self._build_ui()
        self._sync(controller.phase, controller.remaining)
        controller.state_changed.connect(self._sync)
        controller.phase_finished.connect(lambda _ph: None)  # 展示随 state_changed 刷新
        self._apply_theme()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self.phase_label = QLabel("未开始")
        self.phase_label.setObjectName("pomPhase")
        pf = self.phase_label.font()
        pf.setPointSize(13)
        pf.setBold(True)
        self.phase_label.setFont(pf)
        self.phase_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.phase_label)

        self.time_label = QLabel("25:00")
        self.time_label.setObjectName("pomTime")
        tf = QFont()
        tf.setPointSize(44)
        tf.setBold(True)
        self.time_label.setFont(tf)
        self.time_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.time_label)

        sub = QLabel("她陪你专注 · 到点只轻轻提醒，不记成绩")
        sub.setObjectName("pomSub")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # 时长设置卡
        card = QFrame()
        card.setObjectName("pomCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(8)
        row.addWidget(QLabel("专注"))
        self.work_box = QComboBox()
        for v in _WORK_OPTIONS:
            self.work_box.addItem(f"{v} 分钟", v)
        row.addWidget(self.work_box)
        row.addStretch()
        row.addWidget(QLabel("休息"))
        self.break_box = QComboBox()
        for v in _BREAK_OPTIONS:
            self.break_box.addItem(f"{v} 分钟", v)
        row.addWidget(self.break_box)
        outer.addWidget(card)

        # 按钮行
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.start_btn = QPushButton("开始专注")
        self.start_btn.setObjectName("pomBtnPrimary")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        btns.addWidget(self.start_btn, 1)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setObjectName("pomBtn")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.clicked.connect(self._on_pause)
        btns.addWidget(self.pause_btn, 1)
        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setObjectName("pomBtn")
        self.skip_btn.setCursor(Qt.PointingHandCursor)
        self.skip_btn.clicked.connect(self._on_skip)
        btns.addWidget(self.skip_btn, 1)
        outer.addLayout(btns)

        tail = QLabel("时长改动下一轮生效 · 随码铃一起关闭即停")
        tail.setObjectName("pomTail")
        tail.setAlignment(Qt.AlignCenter)
        tail.setWordWrap(True)
        outer.addWidget(tail)

        outer.addStretch()

        self.work_box.currentIndexChanged.connect(self._on_duration_changed)
        self.break_box.currentIndexChanged.connect(self._on_duration_changed)

    def _apply_theme(self) -> None:
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QDialog {{ background: {bg}; color: {text}; }}"
            f"QLabel#pomPhase {{ color: {accent}; background: transparent; }}"
            f"QLabel#pomTime {{ color: {accent}; background: transparent; }}"
            f"QLabel#pomSub, QLabel#pomTail {{ color: {secondary}; font-size: 11px;"
            f" background: transparent; }}"
            f"QFrame#pomCard {{ background: {bg_light}; border: 1px solid {divider};"
            f" border-radius: 10px; }}"
            f"QPushButton#pomBtnPrimary {{ background: {accent}; color: #FFFFFF;"
            f" border: none; border-radius: 8px; padding: 8px 10px; font-size: 13px; }}"
            f"QPushButton#pomBtnPrimary:hover {{ background: {primary}; }}"
            f"QPushButton#pomBtn {{ background: {bg_light}; color: {accent};"
            f" border: 1px solid {primary}; border-radius: 8px; padding: 8px 10px;"
            f" font-size: 13px; }}"
            f"QPushButton#pomBtn:hover {{ background: {primary}; color: #FFFFFF; }}"
        )

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        self.controller.start()
        self._sync(self.controller.phase, self.controller.remaining)

    def _on_pause(self) -> None:
        self.controller.pause()
        self._sync(self.controller.phase, self.controller.remaining)

    def _on_skip(self) -> None:
        self.controller.skip()
        self._sync(self.controller.phase, self.controller.remaining)

    def _on_duration_changed(self, *_args) -> None:
        self.controller.set_durations(
            int(self.work_box.currentData()),
            int(self.break_box.currentData()),
        )
        if self.controller.phase == "idle":
            self._sync(self.controller.phase, self.controller.remaining)

    def _sync(self, phase: str, remaining: int) -> None:
        """按 controller 状态刷新展示（含隐藏期间后台到点）。"""
        try:
            idx = list(_WORK_OPTIONS).index(self.controller.work_min)
            if self.work_box.currentIndex() != idx:
                self.work_box.blockSignals(True)
                self.work_box.setCurrentIndex(idx)
                self.work_box.blockSignals(False)
        except ValueError:
            pass
        try:
            idx = list(_BREAK_OPTIONS).index(self.controller.break_min)
            if self.break_box.currentIndex() != idx:
                self.break_box.blockSignals(True)
                self.break_box.setCurrentIndex(idx)
                self.break_box.blockSignals(False)
        except ValueError:
            pass

        phase_names = {
            "idle": "未开始",
            "focus": "专注中",
            "break": "休息一下",
        }
        text = phase_names.get(phase, "未开始")
        if phase != "idle" and self.controller.paused:
            text += " · 已暂停"
        self.phase_label.setText(text)

        total = max(remaining, 0)
        mm, ss = divmod(total, 60)
        self.time_label.setText(f"{mm:02d}:{ss:02d}")

        if phase == "idle":
            self.start_btn.setText("开始专注")
            self.pause_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
        else:
            running = not self.controller.paused
            self.start_btn.setText("继续" if self.controller.paused else "正在专注")
            self.start_btn.setEnabled(self.controller.paused)
            self.pause_btn.setEnabled(running)
            self.skip_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # 关闭语义：隐藏而非销毁（计时继续；再开恢复显示）
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
