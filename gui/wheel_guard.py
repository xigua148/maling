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

**总开关**：:func:`set_enabled(False)` 即整体失效（快速 A/B 对比用）。
无 ``QApplication`` 也可安全 import（顶层不创建 Qt 对象）。
"""
from __future__ import annotations

import logging

from gui.qt_compat import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QEvent,
    QObject, QSlider,
)

logger = logging.getLogger("maid_coder.gui.wheel_guard")

__all__ = ["GUARDED_TYPES", "ENABLED", "set_enabled", "install", "uninstall"]

#: 受守卫的控件类型（默认会「吞滚轮改值」的那些）
GUARDED_TYPES = (QComboBox, QAbstractSpinBox, QSlider)

#: 总开关（置 False → 过滤器直接放行，行为回到未装之前）
ENABLED: bool = True


def set_enabled(flag: bool) -> None:
    """开关滚轮守卫（供设置项 / A-B 对比使用）。"""
    global ENABLED
    ENABLED = bool(flag)


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
