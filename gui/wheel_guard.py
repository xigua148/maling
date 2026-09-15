# -*- coding: utf-8 -*-
"""滚轮守卫 —— 让「输入类」控件不再被滚轮误改（v2.1 P1）。

**问题**：``QComboBox`` / ``QAbstractSpinBox`` / ``QSlider`` 默认把滚轮事件当作
「调整值」。用户在设置页用滚轮翻页时，鼠标一经过这些控件就会**误改设置**。

**做法**：装一个应用级事件过滤器 —— 命中这三类控件时，把滚轮事件**转交给最近的
``QScrollArea``**（页面照常滚动），自己不改值；找不到滚动区就**丢弃**
（宁可不改，不可误改）。

**不受影响**：点击、键盘（方向键）、程序化 ``setValue`` / ``setCurrentIndex`` 全部照常。

实测（offscreen）：
  未聚焦 → 值 50→50、页面滚动 300→240；
  聚焦后 → 值 50→50、页面继续滚动；
  方向键 → 50→51（键盘仍可用）。

**总开关**：设置页「通用 → 滚轮不误改设置」即时切换（持久化到
``GuiConfig.wheel_guard_enabled``，默认开）；启动时 :func:`install` 会按该
配置初始化，运行中也可程序化调用 :func:`set_enabled`（快速 A/B 对比）。
置 ``False`` 即整体失效，行为等价于未安装该过滤器。
无 ``QApplication`` 也可安全 import（顶层不创建 Qt 对象）。
"""
from __future__ import annotations

import logging

from gui.qt_compat import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QEvent,
    QObject, QSlider,
)

logger = logging.getLogger("maid_coder.gui.wheel_guard")

__all__ = [
    "GUARDED_TYPES", "ENABLED", "set_enabled", "sync_from_config",
    "install", "uninstall",
]

#: 受守卫的控件类型（默认会「吞滚轮改值」的那些）
GUARDED_TYPES = (QComboBox, QAbstractSpinBox, QSlider)

#: 总开关（置 False → 过滤器直接放行，行为回到未装之前）
ENABLED: bool = True

#: 总开关是否已被**显式**设置过（调用 :func:`set_enabled` 即置 ``True``）。
#: 一旦显式设置，:func:`sync_from_config` 的启动期配置同步不再覆盖它 ——
#: 保证「启动按配置初始化」与「运行中即时切换」互不打架。
_EXPLICIT: bool = False


def _config_enabled() -> bool:
    """从持久化配置读取「滚轮守卫」总开关（缺省 ``True``）。

    惰性 import ``gui.config``（避免顶层依赖，无 ``QApplication`` 时同样可用）；
    任何读取失败（无配置文件 / 导入失败 / 缺键）一律返回 ``True`` —— 与既有
    ``ENABLED=True`` 默认一致，升级用户既有行为不变。
    """
    try:
        from gui.config import GuiConfig
        return bool(getattr(GuiConfig.load(), "wheel_guard_enabled", True))
    except Exception:
        logger.debug("静默降级：读取滚轮守卫配置失败，按默认开启", exc_info=True)
        return True


def set_enabled(flag: bool) -> None:
    """设置滚轮守卫总开关（设置页开关 / A-B 对比用）。

    写入即生效、无需重启：仅翻转模块级 :data:`ENABLED`，事件过滤器下一次命中
    滚轮事件即读取新值。``False`` 时过滤器**完全不拦截**，行为等价于未安装该
    过滤器（无半开状态）。设置后不会被启动期配置同步覆盖。

    Args:
        flag: ``True`` 启用守卫；``False`` 整体失效（滚轮回到控件默认行为）。
    """
    global ENABLED, _EXPLICIT
    ENABLED = bool(flag)
    _EXPLICIT = True


def sync_from_config() -> bool:
    """按持久化配置初始化总开关（应用启动时由 :func:`install` 触发）。

    仅在总开关**从未被显式设置**时生效：读 ``GuiConfig.wheel_guard_enabled``
    （缺省 ``True``）写回 :data:`ENABLED`；已显式设置过则原样返回、不覆盖，
    避免运行中的切换被启动期初始化打回。

    Returns:
        同步后的 :data:`ENABLED` 值。
    """
    global ENABLED
    if _EXPLICIT:
        return ENABLED
    ENABLED = _config_enabled()
    return ENABLED


class _WheelGuard(QObject):
    """应用级过滤器：把受守卫控件上的滚轮事件转交给最近的滚动区。"""

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 - Qt 回调命名
        if not ENABLED:
            return False
        try:
            if ev.type() != QEvent.Wheel or not isinstance(obj, GUARDED_TYPES):
                return False
            parent = obj.parent()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    # 交给滚动区 viewport → 页面照常滚动；自己不处理该事件
                    QApplication.sendEvent(parent.viewport(), ev)
                    return True
                parent = parent.parent()
            # 不在滚动区里（如对话框内）→ 直接丢弃：宁可不改，不可误改
            return True
        except Exception:
            logger.debug("静默降级：滚轮守卫中忽略异常", exc_info=True)
            return False


#: 已安装的过滤器（强引用防 GC；同一 app 只装一次）
_GUARD: "_WheelGuard | None" = None


def install(app=None) -> bool:
    """安装应用级滚轮守卫（幂等）。

    Args:
        app: ``QApplication``；缺省取当前实例。

    Returns:
        是否已处于「已安装」状态；无 ``QApplication`` 时返回 ``False``。
    """
    global _GUARD
    if _GUARD is not None:
        return True
    if app is None:
        app = QApplication.instance()
    if app is None:
        return False
    # 启动期按配置初始化总开关（总开关已被显式设置时 sync_from_config 不改动）；
    # 同步失败绝不阻断安装（R-Q：失败降级）。
    try:
        sync_from_config()
    except Exception:
        logger.debug("静默降级：滚轮守卫配置同步失败", exc_info=True)
    try:
        guard = _WheelGuard(app)
        app.installEventFilter(guard)
    except Exception:
        return False
    _GUARD = guard
    return True


def uninstall(app=None) -> None:
    """卸载滚轮守卫（回退用；幂等）。"""
    global _GUARD
    if _GUARD is None:
        return
    if app is None:
        app = QApplication.instance()
    try:
        if app is not None:
            app.removeEventFilter(_GUARD)
    except Exception:
        logger.debug("静默降级：卸载滚轮守卫中忽略异常", exc_info=True)
    _GUARD = None
