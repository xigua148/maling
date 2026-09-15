"""码铃动效内核（v2.1 / 设计 D-V21-01 / D-V21-02）。

本模块契约见 ``docs/design-v21.md`` §4.2 —— **改动须先改设计文档**。

单一收口点：切页 / 气泡入场 / 浮层出现消失 / 侧栏微交互等一切过渡
一律经本模块取时长、缓动与开关判定；**禁止落点散落
``QPropertyAnimation(...).start()`` 或硬编码 ``setDuration(<常量>)``**
（共享知识 §6.5 / M-0 验收②静态扫描）。

**两类动效（v2.x 增补）**：
  · **入场/退场过渡**（一次性）—— ``animate()`` / ``fade()``，时长夹取 ≤ ``MAX_DURATION_MS``(220ms)；
  · **进行中循环**—— ``loop()``，以**周期**计（夹取 800–1600ms），**不计入** 220ms 上限。
循环纪律：受 ``enabled()`` 门控（``off`` 档不启动）、**每 tick 校验 ``enabled()`` 禁用即自停**、
落点 **``hideEvent`` 隐藏即停**、``stop_all()`` 一并停、登记于独立 ``_LOOPS``（不污染 ``_RUNNING``）。

红线：
  · R-F 零新增运行时第三方依赖（仅 PySide6 内置 + 标准库）；
  · R-P 过渡总时长上限 ``MAX_DURATION_MS`` = 220ms；循环动效隐藏即停、不空转；
  · R-Q 效果可关（``off`` 档 / 系统减少动画）。

无 ``QApplication`` 也可安全 import：本模块顶层不创建任何 Qt 对象、
不读配置、不注册资源（循环驱动器亦为**惰性创建**）。

实现见域1（V21-02）；签名与常量由 V21-01 冻结，**不得改名 / 改参数 / 改默认值**。
"""
from __future__ import annotations

import ctypes
import logging
import os
import time
from typing import Optional

from gui.qt_compat import (
    QApplication, QEasingCurve, QGraphicsOpacityEffect, QPropertyAnimation,
    QTimer, Qt,
)

#: 模块级日志器（R-Q 静默降级统一记 ``debug``：属预期行为、非告警）
logger = logging.getLogger("maid_coder.gui.motion")

#: 热路径静默降级的"只记一次"去重键（**防日志刷屏**，见 :func:`_log_once`）
_LOGGED_ONCE: "set[str]" = set()


def _log_once(key: str, message: str) -> None:
    """热路径静默降级日志：同一 ``key`` 只记一次（**防日志刷屏**）。

    本模块多处 except 位于**每次 tick / 每帧**或**信号突发**路径 ——
    ``_tick_loops`` 的相位回调（~60fps）、驱动器启停、``destroyed`` /
    ``finished`` 信号收尾。若每次都 ``logger.debug`` 会随 tick 次数**线性增长**，
    故这里按 ``key`` 去重，保证**总日志条数有界**（不随 tick / 帧次数增长）。
    （本模块所有 except 均收口到本函数，口径统一。）

    ``exc_info=True``：本函数在 ``except`` 动态作用域内被调用，
    ``sys.exc_info()`` 仍能取到当前正在处理的异常，故不必显式传异常对象。
    """
    if key in _LOGGED_ONCE:
        return
    _LOGGED_ONCE.add(key)
    logger.debug(message, exc_info=True)


# ---------------------------------------------------------------------------
# 档位常量（唯一真值源；值与设计 §4.2 一致）
# ---------------------------------------------------------------------------
LEVELS = ("off", "soft", "standard")
DEFAULT_LEVEL = "standard"
MAX_DURATION_MS = 220
_DURATION_MS = {"off": 0, "soft": 130, "standard": 200}

# ---------------------------------------------------------------------------
# 循环动效常量（v2.x 增补；契约见 design §4.2【循环动效】/ D-V21-01）
# 周期 ≠ 时长：循环周期不计入 MAX_DURATION_MS（后者仅约束入场/退场过渡）
# ---------------------------------------------------------------------------
MIN_LOOP_PERIOD_MS = 800
MAX_LOOP_PERIOD_MS = 1600
_DEFAULT_LOOP_PERIOD_MS = 1200
_LOOP_TICK_MS = 16  # ~60fps 相位推进；驱动器唯一，非每循环一个定时器

# Windows 系统级动画开关（SPI_GETCLIENTAREAANIMATION）
_SPI_GETCLIENTAREAANIMATION = 0x1042

# ---------------------------------------------------------------------------
# 模块级状态（顶层不创建 Qt 对象；_RUNNING 防 GC 双保险）
# ---------------------------------------------------------------------------
_LEVEL = DEFAULT_LEVEL
_RUNNING: "set[QPropertyAnimation]" = set()
_CALLBACKS: "dict[QPropertyAnimation, object]" = {}
# 循环登记表（独立于 _RUNNING：循环永不 finished，不经 _cleanup 路径）
_LOOPS: "set[_LoopHandle]" = set()
# 模块级共享驱动器（惰性创建；顶层不创建任何 Qt 对象）
_DRIVER: "Optional[QTimer]" = None


# ---------------------------------------------------------------------------
# 档位 / 开关
# ---------------------------------------------------------------------------
def configure(level: str) -> None:
    """设置动效档位（启动期 + 设置页切换时调用）；非法值回落 ``DEFAULT_LEVEL``。

    签名冻结（design §4.2）。若新档为 ``off``，调用方另需 ``stop_all(final=True)``
    收束进行中动画（D-V21-01）。
    """
    global _LEVEL
    _LEVEL = level if level in LEVELS else DEFAULT_LEVEL


def level() -> str:
    """当前动效档位（``off`` / ``soft`` / ``standard``）。"""
    return _LEVEL


def enabled() -> bool:
    """是否应播放动效：``level() != "off"`` 且 ``system_animations_enabled()``。"""
    return level() != "off" and system_animations_enabled()


def _read_system_animation_flag() -> Optional[bool]:
    """读系统"显示动画"开关；读不到返回 ``None``（判定用真值留给调用方）。

    非 Windows / 调用失败 → ``None``，绝不抛异常。
    """
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        flag = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0
        )
        if not ok:
            return None
        return bool(flag.value)
    except Exception:
        return None


def system_animations_enabled() -> bool:
    """系统级"显示动画"开关（Windows ``SPI_GETCLIENTAREAANIMATION`` 等价物）。

    读不到（非 Windows / 调用失败）→ 返回 ``True``（保守：不误关用户动效）。
    纯逻辑可 mock（M-0 验收③：无 ``QApplication`` 时调用不崩）。
    """
    flag = _read_system_animation_flag()
    return True if flag is None else bool(flag)


# ---------------------------------------------------------------------------
# 时长 / 缓动（单一收口）
# ---------------------------------------------------------------------------
def duration(base_ms: int = 0) -> int:
    """单一收口取时长：``off`` → 0；否则 ``min(base_ms or _DURATION_MS[level], MAX_DURATION_MS)``。

    各动效落点禁止硬编码毫秒上限（M-0 验收②静态扫描）。
    """
    lvl = level()
    if lvl == "off":
        return 0
    default = _DURATION_MS.get(lvl, _DURATION_MS[DEFAULT_LEVEL])
    if isinstance(base_ms, bool):
        base_ms = 0
    base = base_ms if isinstance(base_ms, (int, float)) and base_ms > 0 else default
    return int(min(base, MAX_DURATION_MS))


def _default_easing() -> QEasingCurve:
    """默认缓动曲线工厂（``easing`` 参数会遮蔽同名函数，故内部分流到此）。"""
    return QEasingCurve(QEasingCurve.OutCubic)


def easing() -> QEasingCurve:
    """默认缓动曲线（``OutCubic``，克制；对齐视觉稿 cubic-bezier(.4,0,.2,1) 家族）。"""
    return _default_easing()


# ---------------------------------------------------------------------------
# 动画实例化（GC 双保险）
# ---------------------------------------------------------------------------
def _forget(anim: "QPropertyAnimation") -> None:
    """仅从登记表移除（``destroyed`` 兜底，不触发回调）。"""
    try:
        _RUNNING.discard(anim)
        _CALLBACKS.pop(anim, None)
    except Exception:
        # destroyed 信号突发路径 → 只记一次，避免批量销毁时刷屏
        _log_once("forget", "从动画登记表移除失败，已忽略")


def _cleanup(anim: "QPropertyAnimation") -> None:
    """动画结束后：去登记 + 回调；幂等（重复调用只生效一次）。"""
    if anim not in _RUNNING:
        return
    _RUNNING.discard(anim)
    cb = _CALLBACKS.pop(anim, None)
    if cb is not None:
        try:
            cb()
        except Exception:
            # finished 信号突发路径 → 只记一次
            _log_once("cleanup-cb", "动画结束回调执行失败，已忽略")


def animate(widget, prop: bytes, start, end, *, duration_ms: Optional[int] = None,
            easing=None, on_finished=None) -> "QPropertyAnimation | None":
    """在 ``widget`` 上对 ``prop`` 属性做 ``start → end`` 过渡。

    ``enabled() == False`` 时**不实例化任何动画对象**，返回 ``None``；
    否则 ``QPropertyAnimation(widget, prop, widget)`` 并注册进模块级 ``_RUNNING``
    防 GC，``finished`` / ``destroyed`` 时移除（D-V21-01）。
    """
    if not enabled():
        return None

    anim = QPropertyAnimation(widget, prop, widget)
    anim.setDuration(duration(duration_ms if duration_ms is not None else 0))
    anim.setEasingCurve(easing if easing is not None else _default_easing())
    anim.setStartValue(start)
    anim.setEndValue(end)

    _RUNNING.add(anim)
    if on_finished is not None:
        _CALLBACKS[anim] = on_finished

    anim.finished.connect(lambda a=anim: _cleanup(a))
    anim.destroyed.connect(lambda *_: _forget(anim))
    anim.start()
    return anim


def fade(widget, *, to: float = 1.0, duration_ms: Optional[int] = None,
         on_finished=None) -> "QPropertyAnimation | None":
    """对 ``widget`` 做不透明度淡入 / 淡出（``QGraphicsOpacityEffect`` 便捷封装）。

    已存在 effect 则复用，不叠加；``enabled() == False`` 时返回 ``None``。
    """
    if not enabled():
        return None

    eff = widget.graphicsEffect()
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(eff)
        start = 0.0
    else:
        start = eff.opacity()

    return animate(
        eff, b"opacity", start, float(to),
        duration_ms=duration_ms, on_finished=on_finished,
    )


def stop_all(final: bool = True) -> None:
    """把 ``_RUNNING`` 中所有动画立即收束到终态并停止（切 ``off`` 时调用）。

    v2.x：**一并停掉 ``_LOOPS`` 中全部循环**（退出 / 换肤 / 切 ``off`` 统一收口）；
    ``final=True`` 时回调各循环 ``on_disabled`` → 落点切静态形态。
    """
    for anim in list(_RUNNING):
        try:
            if final:
                anim.setCurrentTime(anim.duration())
            anim.stop()
        except RuntimeError:
            # C++ 侧对象已销毁（收束期批量停 → 只记一次）
            _log_once("stop-all-runtime", "停止动画时 C++ 对象已销毁，已忽略")
    if final:
        for anim in list(_RUNNING):
            _cleanup(anim)
    _RUNNING.clear()
    _CALLBACKS.clear()
    _stop_all_loops(notify=bool(final))


def running_count() -> int:
    """当前在跑的动画数量（测试用；仅一次性动画，不含循环）。"""
    return len(_RUNNING)


# ---------------------------------------------------------------------------
# 循环动效（v2.x 增补 / 契约见 design §4.2【循环动效】）
# ---------------------------------------------------------------------------
class _LoopHandle:
    """循环动效句柄（不透明，非 Qt 对象）。

    外部只应经 :func:`stop_loop` 操作；``period_ms`` / ``started_at`` 暴露给
    测试做确定性断言。
    """

    __slots__ = ("owner", "on_tick", "on_disabled", "period_ms", "started_at")

    def __init__(self, owner, on_tick, on_disabled, period_ms: int, started_at: float):
        self.owner = owner
        self.on_tick = on_tick
        self.on_disabled = on_disabled
        self.period_ms = period_ms
        self.started_at = started_at


def loop_period_ms(base_ms: int = 0) -> int:
    """循环周期单一收口：非法 / ``<=0`` → 默认 ``1200``；夹取到 ``[800, 1600]``。

    与 :func:`duration`（一次性过渡 ≤220ms）**并列且语义不同**：本函数产出"周期"
    而非"时长"，**不计入** ``MAX_DURATION_MS``（D-V21-01 循环动效裁决）。
    """
    if isinstance(base_ms, bool):
        base_ms = 0
    base = base_ms if isinstance(base_ms, (int, float)) and base_ms > 0 else _DEFAULT_LOOP_PERIOD_MS
    return int(min(max(base, MIN_LOOP_PERIOD_MS), MAX_LOOP_PERIOD_MS))


def _ensure_driver() -> "Optional[QTimer]":
    """惰性创建并启动模块级共享驱动器（多循环共用一个 QTimer，最省）。"""
    global _DRIVER
    if _DRIVER is None:
        try:
            _DRIVER = QTimer()
            _DRIVER.setInterval(_LOOP_TICK_MS)
            try:
                _DRIVER.setTimerType(Qt.PreciseTimer)
            except Exception:
                # 驱动器创建期一次性路径（_ensure_driver 每个循环启动都会走）→ 只记一次
                _log_once("driver-timer-type", "设置驱动器精确定时器类型失败，已忽略")
            _DRIVER.timeout.connect(_tick_loops)
        except Exception:
            _DRIVER = None
    if _DRIVER is not None:
        try:
            if not _DRIVER.isActive():
                _DRIVER.start()
        except RuntimeError:
            # 循环频繁启停路径 → 只记一次
            _log_once("driver-start", "启动动效驱动器失败，已忽略")
    return _DRIVER


def _stop_driver() -> None:
    """停驱动器（保留对象供复用）；幂等。"""
    if _DRIVER is None:
        return
    try:
        if _DRIVER.isActive():
            _DRIVER.stop()
    except RuntimeError:
        # 亦可达于 _tick_loops 空转分支（每 tick 可达）→ 只记一次，避免刷屏
        _log_once("driver-stop", "停止动效驱动器失败，已忽略")


def loop(owner, on_tick, *, period_ms: Optional[int] = None,
         on_disabled=None) -> "Optional[_LoopHandle]":
    """启动一个**循环动效**（周期 800–1600ms）。

    ``enabled() == False`` → **不启动、不创建定时器、返回 ``None``**，落点保持
    既有静态形态（R-Q）。否则登记进独立集合 ``_LOOPS`` 并起用共享驱动器；
    每个 tick 回调 ``on_tick(progress)``（``progress ∈ [0,1)``）。

    **两条停用路径（对照，务必区分，勿误用）**：

    ① **因禁用而停** —— ``enabled()`` 变 ``False``（档位切 ``off`` / 系统关动画 /
       ``stop_all()``）：**必然**触发 ``on_disabled()``（``notify=True``）。
       **这是落点"必须切静态形态"的时刻**：``off`` 档下若仍留动画残留即违反 R-Q，
       故落点须在此把自绘 / 指示复位为 §7 静态帧（off ≠ 空白）。

    ② **落点显式 :func:`stop_loop`** —— 主动收束（状态结束 / ``hideEvent`` 隐藏）：
       **不**触发 ``on_disabled()``。此时落点自己掌握去向（隐藏 / 显示终态文案），
       无需静态形态再插一脚；两条路径混用会让终态被静态形态二次覆盖。

    ``owner``：循环归属对象（通常是控件）。若具备 ``destroyed`` 信号（``QObject``），
    其销毁时自动 :func:`stop_loop`（防泄漏）。
    """
    if not enabled():
        return None
    try:
        if QApplication.instance() is None:
            return None
    except Exception:
        return None
    if not callable(on_tick):
        return None

    handle = _LoopHandle(
        owner, on_tick, on_disabled,
        loop_period_ms(period_ms if period_ms is not None else 0),
        time.monotonic(),
    )
    _LOOPS.add(handle)
    if owner is not None and hasattr(owner, "destroyed"):
        try:
            owner.destroyed.connect(lambda *_: stop_loop(handle))
        except Exception:
            # 循环频繁启停路径 → 只记一次
            _log_once("loop-connect", "连接 owner.destroyed 自动停循环失败，已忽略")
    _ensure_driver()
    return handle


def stop_loop(handle) -> None:
    """停止单个循环；**幂等**。未知 / ``None`` 句柄静默返回。

    显式停止**不**触发 ``on_disabled``（那是"因禁用而停"的专用回调）。
    """
    try:
        if handle not in _LOOPS:
            return
    except TypeError:
        return
    _LOOPS.discard(handle)
    if not _LOOPS:
        _stop_driver()


def running_loop_count() -> int:
    """当前在跑的循环数量（测试用）。"""
    return len(_LOOPS)


def _stop_all_loops(notify: bool) -> None:
    """停全部循环；``notify=True`` 时逐个回调 ``on_disabled``（落点切静态形态）。"""
    entries = list(_LOOPS)
    _LOOPS.clear()
    _stop_driver()
    if not notify:
        return
    for entry in entries:
        cb = entry.on_disabled
        if cb is None:
            continue
        try:
            cb()
        except Exception:
            # 批量停循环路径 → 只记一次
            _log_once("stop-all-loops-cb", "循环 on_disabled 回调执行失败，已忽略")


def _tick_loops(now: Optional[float] = None) -> None:
    """驱动器回调：推进全部循环相位。

    **每次 tick 校验** ``enabled()`` —— 为 ``False`` 则全部循环**立即自停**并回调
    ``on_disabled``（D-V21-01「响应式立即停」）。``now`` 仅供测试注入，
    生产走 ``time.monotonic()``（无事件循环也可确定性断言）。
    """
    if not _LOOPS:
        _stop_driver()
        return
    if not enabled():
        _stop_all_loops(notify=True)
        return
    if now is None:
        now = time.monotonic()
    for entry in list(_LOOPS):
        if entry not in _LOOPS:
            continue  # 前一回调中已被 stop_loop 摘除
        period = entry.period_ms
        if period <= 0:
            progress = 0.0
        else:
            elapsed_ms = (now - entry.started_at) * 1000.0
            progress = (elapsed_ms % period) / period
        try:
            entry.on_tick(progress)
        except Exception:
            # ⚠ 热路径：每个 tick（~60fps）× 每个循环都会走到 → 只记一次，严防刷屏
            _log_once("tick-on-tick", "循环 on_tick 回调执行失败，已忽略")
