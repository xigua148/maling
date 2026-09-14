"""gui/pomodoro.py —— v1.4(A3) 番茄钟「她陪你专注」app 级单例控制器

范围（严格 v1.2 A10 / docs/design-v14.md D-V14-04~06）：只做「专注计时骨架」——
阶段（专注/休息）、时长可调（默认 25/5）、开始/暂停/跳过、剩余倒计时、到点提醒。
**不做**成绩/统计/连续天数/历史累计（R-A/R-E），无任何持久化成绩文件。

实现说明：
  - 参考 Wenlin-AI/Pomodoro-timer（MIT）仅讨论其计时交互形态（prd-v14 §6.2 调研），
    本实现为码铃自制轻量组件，未复制任何第三方代码（去 pygame/去 Obsidian/去历史
    session 文件），故许可面最小（A4 不登记源码）。
  - 状态机：idle -> focus -> break -> idle（休息结束回 idle，**不自动连班**，
    「想继续随时再按」，避免自律/打卡感，R-A）。
  - 到点提醒 = 独立用户请求通道（D-V14-05）：不走 proactive 四重闸；仅托盘静默气泡
    + 可选 TTS（守卫 tts_enabled & pomodoro_tts），无系统级弹窗。
  - 专注开始/结束接 companion 轻事件：开始 -> note_activity("focus")；到点/结束 ->
    note_activity(None)；自然完成一轮专注经 ingest_event("pomodoro_done") 记足迹
    （EVENT_TYPES 白名单已扩，非计分）。不碰 intimacy、不写成绩。
  - controller 随 app 退出即停（QTimer 随单例销毁），无后台持久计时。

外部使用：get_pomodoro_controller(app_ctx) 取单例；open_pomodoro(app_ctx) 打开/聚焦浮窗。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import QObject, QTimer, Signal

logger = logging.getLogger("maid_coder.gui")

PHASE_IDLE = "idle"
PHASE_FOCUS = "focus"
PHASE_BREAK = "break"

# 时长选择项（分钟）
_WORK_OPTIONS = (15, 20, 25, 30, 40, 50, 60)
_BREAK_OPTIONS = (3, 5, 10, 15, 20, 25)

_controller: Optional["PomodoroController"] = None


def get_pomodoro_controller(app_ctx) -> "PomodoroController":
    """app 级单例：随 app_ctx 复用；对话框入口与托盘共用同一控制器。"""
    global _controller
    if _controller is None or getattr(_controller, "app_ctx", None) is not app_ctx:
        _controller = PomodoroController(app_ctx)
    return _controller


def open_pomodoro(app_ctx):
    """打开/聚焦番茄钟浮窗（首页快捷入口与托盘「🍅 专注」共用）。"""
    ctrl = get_pomodoro_controller(app_ctx)
    dlg = ctrl.ensure_dialog()
    try:
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
    except Exception as exc:
        logger.warning("番茄钟浮窗显示失败: %s", exc)
    return dlg


class PomodoroController(QObject):
    """番茄钟逻辑控制器：1s QTimer 倒计时 + 状态机 + 到点独立提醒。"""

    # (phase, remaining_seconds)；paused 状态经 phase 文案由视图呈现
    state_changed = Signal(str, int)
    # 自然到点（skip/暂停不发）："focus"（专注结束进入休息）| "break"（休息结束回 idle）
    phase_finished = Signal(str)

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self.phase: str = PHASE_IDLE
        self.paused: bool = False
        self.remaining: int = 0
        self._dialog = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()  # 常驻轻 tick，仅 focus/break 时倒计时

    # ------------------------------------------------------------------
    # 时长配置（GuiConfig 持久化；运行中改动下一轮生效）
    # ------------------------------------------------------------------
    def _cfg_value(self, key: str, default: int) -> int:
        cfg = getattr(self.app_ctx, "config", None)
        if cfg is None:
            return default
        try:
            return max(1, int(getattr(cfg, key, default) or default))
        except (TypeError, ValueError):
            return default

    def work_seconds(self) -> int:
        return self._cfg_value("pomodoro_work_min", 25) * 60

    def break_seconds(self) -> int:
        return self._cfg_value("pomodoro_break_min", 5) * 60

    @property
    def work_min(self) -> int:
        return self.work_seconds() // 60

    @property
    def break_min(self) -> int:
        return self.break_seconds() // 60

    def set_durations(self, work_min: int, break_min: int) -> None:
        """保存专注/休息时长（用户调时长即存盘；运行中不打断当前一轮）。"""
        cfg = getattr(self.app_ctx, "config", None)
        if cfg is not None:
            try:
                cfg.pomodoro_work_min = max(1, int(work_min))
                cfg.pomodoro_break_min = max(1, int(break_min))
                cfg.save()
            except Exception as exc:
                logger.warning("番茄钟时长保存失败: %s", exc)
        if self.phase == PHASE_IDLE:
            self.state_changed.emit(self.phase, self.remaining)

    # ------------------------------------------------------------------
    # 用户操作
    # ------------------------------------------------------------------
    def start(self) -> None:
        """开始/继续：idle -> 新一轮专注；暂停态 -> 继续。"""
        if self.phase == PHASE_IDLE:
            self.phase = PHASE_FOCUS
            self.paused = False
            self.remaining = self.work_seconds()
            self._note_activity(PHASE_FOCUS)
        else:
            self.paused = False
        self.state_changed.emit(self.phase, self.remaining)

    def pause(self) -> None:
        """断点暂停（保留剩余时间）。"""
        if self.phase in (PHASE_FOCUS, PHASE_BREAK) and not self.paused:
            self.paused = True
            self.state_changed.emit(self.phase, self.remaining)

    def reset(self) -> None:
        """回到待机（不提醒、不记事件）。"""
        was_focus = self.phase == PHASE_FOCUS
        self._timer_started_cleanup()
        self.phase = PHASE_IDLE
        self.paused = False
        self.remaining = 0
        if was_focus:
            self._note_activity(None)
        self.state_changed.emit(self.phase, 0)

    def skip(self) -> None:
        """跳过当前阶段（静默推进一轮，不响铃）：focus -> break；break -> idle。"""
        if self.phase == PHASE_FOCUS:
            self.phase = PHASE_BREAK
            self.paused = False
            self.remaining = self.break_seconds()
            self._note_activity(None)
            self.state_changed.emit(self.phase, self.remaining)
        elif self.phase == PHASE_BREAK:
            self._timer_started_cleanup()
            self.phase = PHASE_IDLE
            self.paused = False
            self.remaining = 0
            self.state_changed.emit(self.phase, 0)

    # ------------------------------------------------------------------
    # 计时
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        if self.phase == PHASE_IDLE:
            return
        if self.paused:
            self.state_changed.emit(self.phase, self.remaining)
            return
        self.remaining -= 1
        if self.remaining <= 0:
            self._advance(natural=True)
        else:
            self.state_changed.emit(self.phase, self.remaining)

    def _advance(self, natural: bool) -> None:
        if self.phase == PHASE_FOCUS:
            self.phase = PHASE_BREAK
            self.paused = False
            self.remaining = self.break_seconds()
            self._note_activity(None)
            if natural:
                self.phase_finished.emit(PHASE_FOCUS)
                self._notify_focus_done()
            self.state_changed.emit(self.phase, self.remaining)
        elif self.phase == PHASE_BREAK:
            self._timer_started_cleanup()
            self.phase = PHASE_IDLE
            self.paused = False
            self.remaining = 0
            if natural:
                self.phase_finished.emit(PHASE_BREAK)
                self._notify_break_done()
            self.state_changed.emit(self.phase, 0)

    def _timer_started_cleanup(self) -> None:
        # 回 idle 时清剩余；常驻 timer 继续跑（_on_tick 见 idle 直接 return）
        self.remaining = 0

    # ------------------------------------------------------------------
    # 到点提醒（独立用户请求通道，D-V14-05）
    # ------------------------------------------------------------------
    def _notify_focus_done(self) -> None:
        """专注自然到点：托盘静默气泡 / 状态栏一行 + 可选 TTS + 记足迹（非计分）。"""
        title = "专注时间到啦"
        text = "这一轮码铃一直陪着你，歇一小会儿吧~"
        self._deliver_notice(title, text)
        self._maybe_speak("专注时间到啦，休息一下吧~")
        self._ingest_focus_done()

    def _notify_break_done(self) -> None:
        title = "休息时间到啦"
        text = "想继续专注的话，随时再按开始就好~"
        self._deliver_notice(title, text)
        self._maybe_speak("休息时间到啦，想继续就再按开始吧~")

    def _deliver_notice(self, title: str, text: str) -> None:
        """投递通道：优先托盘静默气泡；无托盘 -> 主窗可见则状态栏一行；皆无只记日志。"""
        tray = getattr(self.app_ctx, "tray_manager", None)
        if tray is not None and callable(getattr(tray, "notify_maid", None)):
            try:
                tray.notify_maid(title, text)
                return
            except Exception as exc:
                logger.warning("番茄钟托盘提醒失败: %s", exc)
        mw = getattr(self.app_ctx, "main_window", None)
        if mw is not None:
            try:
                status_bar = getattr(mw, "status_bar", None)
                visible = bool(getattr(mw, "isVisible", lambda: False)())
                if visible and status_bar is not None and callable(
                    getattr(status_bar, "showMessage", None)
                ):
                    status_bar.showMessage(f"{title}：{text}", 6000)
                    return
            except Exception as exc:
                logger.warning("番茄钟状态栏提醒失败: %s", exc)
        logger.info("番茄钟提醒（无可用展示通道）: %s - %s", title, text)

    def _maybe_speak(self, phrase: str) -> None:
        """可选语音：tts_enabled & pomodoro_tts 双守卫 + 可用性守卫（无语音设备静默）。"""
        cfg = getattr(self.app_ctx, "config", None)
        if not bool(getattr(cfg, "tts_enabled", False)):
            return
        if not bool(getattr(cfg, "pomodoro_tts", True)):
            return
        tts = getattr(self.app_ctx, "tts", None)
        if tts is None or not callable(getattr(tts, "speak", None)):
            return
        try:
            if getattr(tts, "available", True):
                tts.speak(phrase)
        except Exception as exc:
            logger.warning("番茄钟语音提醒失败: %s", exc)

    # ------------------------------------------------------------------
    # companion 轻事件（D-V14-06，非计分）
    # ------------------------------------------------------------------
    def _note_activity(self, state: Optional[str]) -> None:
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None or not callable(getattr(bridge, "note_activity", None)):
            return
        try:
            bridge.note_activity(state)
        except Exception as exc:
            logger.warning("番茄钟活动态通知失败: %s", exc)

    def _ingest_focus_done(self) -> None:
        companion = getattr(self.app_ctx, "companion", None)
        if companion is None or not callable(getattr(companion, "ingest_event", None)):
            return
        try:
            companion.ingest_event("pomodoro_done", source="pomodoro")
        except Exception as exc:
            logger.warning("companion ingest_event(pomodoro_done) 失败: %s", exc)

    # ------------------------------------------------------------------
    # 视图装配
    # ------------------------------------------------------------------
    def ensure_dialog(self):
        """懒建无状态浮窗视图（关闭=隐藏，计时继续；再开恢复显示）。"""
        if self._dialog is None:
            try:
                from gui.widgets.pomodoro_dialog import PomodoroDialog
                self._dialog = PomodoroDialog(self.app_ctx, controller=self, parent=None)
            except Exception as exc:
                logger.warning("番茄钟浮窗创建失败: %s", exc)
                self._dialog = None
        return self._dialog

    def shutdown(self) -> None:
        """app 退出卫生：停计时、回落活动态（幂等）。"""
        try:
            if self._timer is not None:
                self._timer.stop()
        except Exception:
            pass
        if self.phase != PHASE_IDLE:
            self._note_activity(None)
        self.phase = PHASE_IDLE
        self.paused = False
