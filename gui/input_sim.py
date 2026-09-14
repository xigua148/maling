# -*- coding: utf-8 -*-
"""v1.4(B2) input_sim.py —— ctypes 键鼠模拟执行器（Windows，零第三方依赖 R-F）。

（design-v14 D-V14-13 / §2.5；坐标换算 = design-v14 共享知识 22 单点实现）

能力：
- move_to / click / double_click / right_click / type_text / hotkey；
- **坐标换算**：模型返回的 (x,y) 是送视觉图像像素 → 反算逻辑虚拟桌面坐标
  （image_to_logical，按 图像宽高 ↔ vr 宽高 等比）→ 命中屏 DPR → 物理像素
  （logical_to_physical）。混合 DPR 为已知近似边界（继承 P1-2），真机标定。

红线：
- 零第三方依赖（ctypes 标准库）；type 用 SendInput KEYEVENTF_UNICODE（支持 CJK）；
- **不做任何键鼠记录 / 输入日志**；仅作用于当前交互桌面（R-G）；
- hotkey/type 键白名单内才可执行（其余抛 ValueError，由上层「拒绝」反馈）。

测试：本模块顶层不做真实注入；NativeInputSimulator 可在非 Windows / 无会话桌面时
返回 False（availability() 探测）。Controller 允许注入 mock executor 验证调用序列。
"""
from __future__ import annotations

import logging
import os
import struct
import time
from typing import List, Optional, Tuple

logger = logging.getLogger("maid_coder.gui.input_sim")

_IS_WIN = os.name == "nt"

if _IS_WIN:  # 延迟取 user32（避免非 Windows import 即崩）
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
else:
    _user32 = None

# mouse_event 标志
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
# keybd_event / SendInput 标志
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

#: 修饰键 → VK（最小映射，白名单）
_MODIFIER_VK = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "meta": 0x5B, "windows": 0x5B,
}
_SPECIAL_VK = {
    "esc": 0x1B, "escape": 0x1B, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "insert": 0x2D, "capslock": 0x14, "printscreen": 0x2C,
}


def _key_vk(key: str) -> int:
    """把键名解析为 VK 码（字母/数字/F1-F24/修饰/特殊白名单）。非法抛 ValueError。"""
    k = (key or "").strip().lower()
    if not k:
        raise ValueError("空按键")
    if k in _MODIFIER_VK:
        return _MODIFIER_VK[k]
    if k in _SPECIAL_VK:
        return _SPECIAL_VK[k]
    if len(k) == 1 and k.isalpha():
        return ord(k.upper())
    if k.isdigit() and len(k) == 1:
        return ord(k)
    if len(k) >= 2 and k[0] == "f" and k[1:].isdigit():
        n = int(k[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    raise ValueError(f"不支持的键：{key}")


def image_to_logical(vr_x: int, vr_y: int, vr_w: int, vr_h: int,
                     img_w: int, img_h: int, px: float, py: float) -> Tuple[float, float]:
    """图像像素 → 逻辑虚拟桌面坐标（送视觉帧等比反算；知识 22 公式）。"""
    if img_w <= 0 or img_h <= 0 or vr_w <= 0 or vr_h <= 0:
        raise ValueError("无效的坐标换算参数")
    lx = vr_x + float(px) * vr_w / img_w
    ly = vr_y + float(py) * vr_h / img_h
    return lx, ly


def logical_to_physical(screen_geos: List[tuple], x: float, y: float) -> Optional[Tuple[int, int]]:
    """逻辑虚拟桌面坐标 → 命中屏物理像素（该屏 DPR 独立换算；知识 22 公式）。

    screen_geos: [(geo.x, geo.y, geo.w, geo.h, devicePixelRatio), ...]
    未命中任何屏幕返回 None（上层「不执行」）。
    """
    for gx, gy, gw, gh, dpr in (screen_geos or []):
        if gx <= x < gx + gw and gy <= y < gy + gh:
            dpr = max(1.0, float(dpr or 1.0))
            return int(round((x - gx) * dpr)), int(round((y - gy) * dpr))
    return None


def hotkey_to_vks(keys: List[str]) -> List[int]:
    """把白名单键名列表解析为 VK 序列（可含修饰键）。"""
    if not keys:
        raise ValueError("空快捷键")
    vks = [_key_vk(k) for k in keys]
    return vks


class NativeInputSimulator:
    """Windows ctypes 键鼠注入执行器（SendInput/mouse_event/SetCursorPos）。"""

    def __init__(self) -> None:
        self._u = _user32

    def available(self) -> bool:
        return self._u is not None

    def move_to(self, x: int, y: int) -> bool:
        """移动到物理像素坐标（虚拟桌面全局坐标，SetCursorPos）。"""
        if not self._available_or_raise():
            return False
        if not self._u.SetCursorPos(int(x), int(y)):
            return False
        return True

    def click(self, x: int, y: int, double: bool = False, right: bool = False) -> bool:
        if not self._available_or_raise():
            return False
        self._u.SetCursorPos(int(x), int(y))
        if right:
            down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
        else:
            down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
        presses = 2 if double else 1
        for _ in range(presses):
            self._u.mouse_event(down, 0, 0, 0, 0)
            self._u.mouse_event(up, 0, 0, 0, 0)
            time.sleep(0.03)
        return True

    def type_text(self, text: str, interval: float = 0.006) -> bool:
        """逐字符 SendInput KEYEVENTF_UNICODE（支持 CJK/emoji via UTF-16）。"""
        if not self._available_or_raise():
            return False
        text = (text or "")
        if not text:
            return True
        # UTF-16LE 编码为码元流，逐码元发 unicode 键
        units = text.encode("utf-16-le")
        for i in range(0, len(units) - 1, 2):
            wscan = struct.unpack("<H", units[i:i + 2])[0]
            self._send_unicode(wscan, down=True)
            self._send_unicode(wscan, down=False)
            if interval > 0:
                time.sleep(interval)
        return True

    def hotkey(self, keys: List[str]) -> bool:
        """按修饰顺序按下的组合键（如 ["ctrl","s"] / ["alt","f4"]）。"""
        if not self._available_or_raise():
            return False
        vks = hotkey_to_vks(keys)
        # 修饰键优先按下，其余后按；释放顺序相反
        mods = [v for v in vks if v in _MODIFIER_VK.values()]
        rest = [v for v in vks if v not in _MODIFIER_VK.values()]
        order = mods + rest
        for vk in order:
            self._key(vk, down=True)
        for vk in reversed(order):
            self._key(vk, down=False)
        return True

    # ------------------------------------------------------------------
    def _available_or_raise(self) -> bool:
        if self._u is None:
            logger.warning("input_sim: 非 Windows 环境无法注入键鼠")
            return False
        return True

    def _send_unicode(self, wscan: int, down: bool) -> None:
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]

        flags = _KEYEVENTF_UNICODE | (0 if down else _KEYEVENTF_KEYUP)
        inp = INPUT()
        inp.type = 1  # INPUT_KEYBOARD
        inp.union.ki.wVk = 0
        inp.union.ki.wScan = wscan & 0xFFFF
        inp.union.ki.dwFlags = flags
        self._u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def _key(self, vk: int, down: bool) -> None:
        flags = 0 if down else _KEYEVENTF_KEYUP
        self._u.keybd_event(vk, 0, flags, 0)
