"""gui/system_idle.py —— v1.3 P1-4 系统全局空闲检测（R-B 红线：只取毫秒数）

实现（docs/design-v13.md D-V13-03 / PRD P1-4）：
  - `GetLastInputInfo` 只返回「距上次系统键盘/鼠标输入的毫秒数」，**绝不读键鼠内容**
    （R-B 强制：不做在场感知/内容分析，仅把数值用于离开/恢复 crossing）。
  - SystemIdleMonitor(QObject)：QTimer 秒级轮询；状态机 present/away，away→present
    上升沿才 emit returned()（Idle 问候唯一触发点；不新起 scheduler 定时器）。
  - `last_input_age_ms()` 工具函数（供 P2-2 免提"任意输入打断"复用）。
  - API 不可用 / 非 Windows：模块内降级禁用并记日志，不影响主流程（A9 idle_hello 仍在）。
"""
from __future__ import annotations

import ctypes
import logging
import os
from typing import Optional

from gui.qt_compat import QObject, QTimer, Signal

logger = logging.getLogger("maid_coder.gui")

_IDLE_POLL_MS = 1000   # 秒级轮询
_AWAY = "away"
_PRESENT = "present"

# ---- 防御式加载 Win32 API（仅 Windows；非 Windows 一律降级禁用）----
_IDLE_OK = False
if os.name == "nt":
    try:
        from ctypes import wintypes

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        _GetLastInputInfo = ctypes.windll.user32.GetLastInputInfo
        _GetTickCount = ctypes.windll.kernel32.GetTickCount
        _IDLE_OK = True
    except Exception as _e:
        _IDLE_OK = False
        logger.debug("GetLastInputInfo 不可用（Idle 检测降级禁用）: %s", _e)


def last_input_age_ms() -> Optional[int]:
    """返回距上次系统输入（键盘/鼠标）的毫秒数；API 不可用返回 None。

    仅取毫秒数值，不接触任何按键/鼠标内容（R-B）。
    """
    if not _IDLE_OK:
        return None
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not _GetLastInputInfo(ctypes.byref(lii)):
            return None
        tick = int(_GetTickCount())
        age = tick - int(lii.dwTime)
        return max(0, age)
    except Exception as exc:
        logger.debug("GetLastInputInfo 调用失败: %s", exc)
        return None


class SystemIdleMonitor(QObject):
    """系统全局空闲监视器：离开阈值达标后恢复输入时触发一次 returned()。

    - away→present 上升沿才 emit（每次返回只欢迎一次，天然防刷）；
    - 阈值从 cfg.agent_proactive_system_idle_minutes 读（默认 30），构造时快照；
    - 由 GUI main.py 在启动后挂载，app 未运行即不触发（R-C）。
    """

    returned = Signal()
    """crossing 信号：系统空闲 >= 阈值后又出现用户输入。"""

    def __init__(self, app_ctx, parent: Optional[QObject] = None,
                 threshold_minutes: Optional[int] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        if threshold_minutes is None:
            cfg = getattr(app_ctx, "cfg", None)
            try:
                threshold_minutes = int(
                    getattr(cfg, "agent_proactive_system_idle_minutes", 30) or 30
                )
            except Exception:
                threshold_minutes = 30
        self.threshold_minutes = max(1, int(threshold_minutes or 30))
        self.threshold_ms = self.threshold_minutes * 60 * 1000
        self._state: str = _PRESENT  # 启动即视为在场（初始不发 returned）
        self._available: bool = _IDLE_OK
        self._timer: Optional[QTimer] = None
        if _IDLE_OK:
            try:
                self._timer = QTimer(self)
                self._timer.setInterval(_IDLE_POLL_MS)
                self._timer.timeout.connect(self._poll)
            except Exception:
                self._timer = None
                self._available = False
        if not self._available:
            logger.warning("系统空闲监视不可用（非 Windows / API 缺失），Idle 问候停用")

    @property
    def available(self) -> bool:
        return self._available and self._timer is not None

    def start(self) -> bool:
        if not self.available:
            return False
        self._timer.start()
        return True

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    # -- 轮询 --
    def _poll(self) -> None:
        try:
            age = last_input_age_ms()
        except Exception:
            age = None
        if age is None:
            return  # 单次失败不判，等待下一轮
        if age >= self.threshold_ms:
            if self._state != _AWAY:
                self._state = _AWAY
            return
        # 出现新输入
        if self._state == _AWAY:
            self._state = _PRESENT
            logger.info("系统空闲 %s 分钟后检测到主人回来，触发 Idle 问候判定", self.threshold_minutes)
            try:
                self.returned.emit()
            except Exception as exc:
                logger.warning("returned 广播异常（不影响监视）: %s", exc)
        else:
            self._state = _PRESENT
