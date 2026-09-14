"""码铃毛玻璃内核（v2.1 / 设计 D-V21-03 / D-V21-04 / D-V21-05）。

本模块契约见 ``docs/design-v21.md`` §4.3 —— **改动须先改设计文档**。

零依赖实现：``ctypes`` 直调 Windows DWM（``dwmapi`` / ``user32``），
无任何第三方库（R-F）。能力探测纯逻辑可 mock；**fail-safe 铁律**：
任何失败路径返回 ``False``，绝不抛异常；不可用环境调用方保持纯色 ``${bg}``
（不黑窗 / 不全透明 / 文字可读，G-1 验收②）。

无 ``QApplication`` 也可安全 import：顶层只做 ``os`` / ``sys`` / ``ctypes``
等标准库导入，``ctypes.windll`` **只在函数内访问**，非 Windows 下由
``os.name`` / ``sys.platform`` 早退。

v2.1 域2（V21-03）已按 §4.3 契约填充实现：常量与签名冻结不变，仅补实现体。
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# DWM / Win32 常量（唯一真值源；值与设计 D-V21-03 一致）
# ---------------------------------------------------------------------------
DWMWA_USE_IMMERSIVE_DARK_MODE = 20     # Win10 1903+ / Win11：深浅联动
DWMWA_SYSTEMBACKDROP_TYPE = 38         # Win11 22H2+（build >= 22621）
DWMWA_MICA_EFFECT = 1029               # Win11 21H2（build 22000..22620）私有 Mica 开关
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2                  # Mica  —— 主窗
DWMSBT_TRANSIENTWINDOW = 3             # Acrylic —— 浮层 / 对话框
DWMSBT_TABBEDWINDOW = 4                # Mica Alt（备用，本轮不用）
SM_REMOTESESSION = 0x1000

# Windows 11 版本号门槛（纯逻辑判定，供能力探测与材质分派共用）
_WIN11_21H2_BUILD = 22000              # 21H2 起有 Mica（私有 attr=1029）
_WIN11_22H2_BUILD = 22621              # 22H2 起有系统背景材质（attr=38）


@dataclass(frozen=True)
class GlassCapability:
    """毛玻璃能力探测结果（不可变；契约见设计 §4.3）。"""
    supported: bool
    kind: str          # "mica" | "acrylic" | "none"
    build: int
    reason: str


# ---------------------------------------------------------------------------
# 平台 / 注入点（**全部在函数调用期读取，便于 mock / monkeypatch**）
# ---------------------------------------------------------------------------
def _is_windows() -> bool:
    """当前是否 Windows 运行环境。

    同时校验 ``os.name`` 与 ``sys.platform``（任一不符即视为非 Windows），
    因此测试可 monkeypatch ``sys.platform`` / ``os.name`` 注入非 Windows 分支。
    """
    try:
        return os.name == "nt" and sys.platform.startswith("win")
    except Exception:
        return False


def _windows_build() -> int:
    """当前 Windows build 号；非 Windows 或取不到 → ``0``（可 mock）。"""
    if not _is_windows():
        return 0
    try:
        return int(sys.getwindowsversion().build)  # type: ignore[attr-defined]
    except Exception:
        return 0


def is_remote_session() -> bool:
    """是否远程桌面会话（``GetSystemMetrics(SM_REMOTESESSION=0x1000)``）。

    非 Windows 或调用异常 → **保守返回 ``True``**（视为不支持，宁降级不黑窗）。
    """
    if not _is_windows():
        return True
    try:
        # ctypes.windll 只在函数内访问（非 Windows 下 import 不崩）
        value = ctypes.windll.user32.GetSystemMetrics(SM_REMOTESESSION)
        return bool(value)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# 能力探测（纯逻辑可 mock）
# ---------------------------------------------------------------------------
def detect_capability() -> GlassCapability:
    """探测当前环境毛玻璃能力。

    ``os.name != "nt"`` → none；远程桌面 → none；``build >= 22621`` → mica（attr=38）；
    ``22000 <= build < 22621`` → mica（attr=1029）；否则 → none（Win10 及更旧降级纯色）。
    """
    try:
        if not _is_windows():
            return GlassCapability(False, "none", 0, "非 Windows：无 DWM 系统背景材质，降级纯色")
        if is_remote_session():
            return GlassCapability(
                False, "none", _windows_build(),
                "远程桌面会话：DWM 材质不可靠，降级纯色",
            )
        build = _windows_build()
        if build >= _WIN11_22H2_BUILD:
            return GlassCapability(
                True, "mica", build,
                "Windows 11 22H2+：支持 Mica / Acrylic（DWMWA_SYSTEMBACKDROP_TYPE=38）",
            )
        if build >= _WIN11_21H2_BUILD:
            return GlassCapability(
                True, "mica", build,
                "Windows 11 21H2：仅支持 Mica 私有开关（DWMWA_MICA_EFFECT=1029），Acrylic 不可用",
            )
        return GlassCapability(
            False, "none", build,
            "Windows 10 及更旧：无系统背景材质，降级纯色",
        )
    except Exception:
        return GlassCapability(False, "none", 0, "能力探测失败：保守降级纯色")


def is_supported() -> bool:
    """``detect_capability().supported`` 的布尔投影。"""
    try:
        return bool(detect_capability().supported)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# DWM 调用（统一封装；全部 try/except，失败返回 False 绝不抛）
# ---------------------------------------------------------------------------
def _valid_hwnd(hwnd: object) -> bool:
    """句柄合法性：非 ``None``、非 ``bool``、整数且非 0。"""
    if hwnd is None or isinstance(hwnd, bool):
        return False
    if not isinstance(hwnd, int):
        return False
    return hwnd != 0


def _dwm_set_attribute(hwnd: int, attribute: int, value: int) -> bool:
    """直调 ``dwmapi.DwmSetWindowAttribute``；瞬时返回，失败 → ``False``（不抛）。"""
    try:
        dwmapi = ctypes.windll.dwmapi  # ctypes.windll 只在函数内访问
        func = dwmapi.DwmSetWindowAttribute
        func.restype = ctypes.c_long
        func.argtypes = [
            ctypes.c_void_p,   # HWND
            ctypes.c_uint,     # DWORD dwAttribute
            ctypes.c_void_p,   # LPCVOID pvAttribute
            ctypes.c_uint,     # DWORD cbAttribute
        ]
        attr_value = ctypes.c_int(int(value))
        result = func(
            ctypes.c_void_p(int(hwnd)),
            ctypes.c_uint(int(attribute)),
            ctypes.cast(ctypes.byref(attr_value), ctypes.c_void_p),
            ctypes.c_uint(ctypes.sizeof(attr_value)),
        )
        return int(result) == 0
    except Exception:
        return False


def _apply_backdrop(hwnd: int, backdrop: int, *, dark: bool) -> bool:
    """按当前 build 分派材质属性；不支持环境**不发起 DWM 调用**即返回 ``False``。"""
    try:
        if not _valid_hwnd(hwnd):
            return False
        if not _is_windows() or is_remote_session():
            return False
        build = _windows_build()
        if build >= _WIN11_22H2_BUILD:
            ok = _dwm_set_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, backdrop)
        elif build >= _WIN11_21H2_BUILD:
            # 21H2 只有私有 Mica 开关；Acrylic（浮层）不可用 → 不发起调用
            if backdrop != DWMSBT_MAINWINDOW:
                return False
            ok = _dwm_set_attribute(hwnd, DWMWA_MICA_EFFECT, 1)
        else:
            return False
        if not ok:
            return False
        # 深浅联动：切深浅必须重设，否则材质色调不对（best-effort，不改变材质成功结论）
        _dwm_set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)
        return True
    except Exception:
        return False


def apply_main_window(hwnd: int, *, dark: bool) -> bool:
    """主窗 Mica：``DWMSBT_MAINWINDOW(2)``；21H2（build 22000..22620）走 ``1029``。

    ``dark`` 联动 ``DWMWA_USE_IMMERSIVE_DARK_MODE``。失败返回 ``False``。
    """
    return _apply_backdrop(hwnd, DWMSBT_MAINWINDOW, dark=dark)


def apply_dialog(hwnd: int, *, dark: bool) -> bool:
    """顶层对话框 Acrylic：``DWMSBT_TRANSIENTWINDOW(3)``。失败返回 ``False``。"""
    return _apply_backdrop(hwnd, DWMSBT_TRANSIENTWINDOW, dark=dark)


def remove(hwnd: int) -> bool:
    """移除材质：``DWMSBT_NONE(1)`` / 关 ``1029`` / 关 immersive dark。失败返回 ``False``。"""
    try:
        if not _valid_hwnd(hwnd):
            return False
        if not _is_windows():
            return False
        build = _windows_build()
        if build >= _WIN11_22H2_BUILD:
            ok = _dwm_set_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
        elif build >= _WIN11_21H2_BUILD:
            ok = _dwm_set_attribute(hwnd, DWMWA_MICA_EFFECT, 0)
        else:
            ok = True  # 本无材质，视作已处于纯色
        # 关深色联动（best-effort）
        _dwm_set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 0)
        return ok
    except Exception:
        return False


def safe_apply(hwnd: int, kind: str, *, dark: bool) -> bool:
    """按 ``kind`` 分派 apply（``"mica"`` → 主窗 / ``"acrylic"`` → 对话框）。

    全 try/except，失败返回 ``False``，**绝不抛**（G-0 验收②：不支持时不执行
    ``DwmSetWindowAttribute``）。
    """
    try:
        if not _valid_hwnd(hwnd):
            return False
        if kind == "mica":
            return apply_main_window(hwnd, dark=dark)
        if kind == "acrylic":
            return apply_dialog(hwnd, dark=dark)
        return False
    except Exception:
        return False
