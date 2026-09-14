"""autostart.py —— v1.3 P2-5 开机自启（纯 stdlib winreg，幂等可逆）

设计（PRD §3.3 P2-5）：
  - 写/读/删 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` 的「MaLing」值；
    disable 精确删本应用自己的值、失败静默；enable 幂等。
  - frozen（PyInstaller 打包）环境：值 = sys.executable（桌面版 exe）。
  - source / venv 环境：写 `pythonw.exe` + `run.py`（Windows 下可用）；找不到 pythonw
    时返回可读说明（桌面版才可用），不写脏值。
  - 红线：默认关（由设置 UI 保证，本模块不做任何自动写入）；不做灰色默认勾选。
  - 顶层零第三方依赖（仅标准库 winreg/os/sys）；frozen hiddenimports 已收录 autostart。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("maid_coder.autostart")

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "MaLing"

_IS_WINDOWS = os.name == "nt"

# 模块级缓存：避免每次调用都重复 import winreg（非 Windows 降级禁用）
_winreg = None
if _IS_WINDOWS:
    try:
        import winreg  # type: ignore
    except Exception as _e:  # pragma: no cover - 非 Windows 无此模块
        logger.debug("winreg 不可用（开机自启降级禁用）: %s", _e)
        _winreg = None
    else:
        _winreg = winreg


def _run_command() -> Optional[str]:
    """组装要写入 Run 键的命令行；不可用时返回 None。

    - frozen：sys.executable（onedir/onefile 的 exe，自启即启动码铃）；
    - source/venv：`pythonw.exe <项目根>/run.py`（pythonw 免黑框）；无 pythonw 返回 None。
    """
    if getattr(sys, "frozen", False):
        exe = sys.executable
        return f'"{exe}"' if exe else None
    # 源码 / venv 环境
    py_dir = os.path.dirname(os.path.abspath(sys.executable or ""))
    pythonw = os.path.join(py_dir, "pythonw.exe")
    if not (pythonw and os.path.exists(pythonw)):
        return None
    # 项目根 = 本文件上一级（autostart.py 在项目根）
    root = Path(__file__).resolve().parent
    run_py = root / "run.py"
    if not run_py.exists():
        return None
    return f'"{pythonw}" "{run_py}"'


def available() -> bool:
    """运行环境是否支持开机自启（Windows + winreg 可用）。"""
    return _IS_WINDOWS and _winreg is not None


def is_enabled() -> bool:
    """Run 键里是否已存在本应用（MaLing）的值。"""
    if not available():
        return False
    try:
        with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0,
                             _winreg.KEY_READ) as key:
            try:
                _winreg.QueryValueEx(key, _RUN_VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except FileNotFoundError:
        return False
    except Exception as exc:  # 权限/损坏等异常 -> 视为未开启（失败静默）
        logger.warning("读取开机自启状态失败: %s", exc)
        return False


def enable() -> tuple[bool, str]:
    """开启开机自启（幂等）。返回 (ok, 提示)。"""
    if not available():
        return False, "仅 Windows 桌面版支持开机自启。"
    cmd = _run_command()
    if not cmd:
        return (False,
                "当前是源码/虚拟环境运行，找不到 pythonw.exe，请使用打包后的桌面版（MaLing.exe）开启自启。")
    try:
        with _winreg.CreateKeyEx(_winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0,
                                 _winreg.KEY_WRITE) as key:
            _winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, _winreg.REG_SZ, cmd)
        return True, "已开启开机自启（开机后码铃会随系统启动）。"
    except Exception as exc:
        logger.warning("写入开机自启失败: %s", exc)
        return False, f"开启开机自启失败：{exc}"


def disable() -> tuple[bool, str]:
    """关闭开机自启（精确删自己的值；不存在视为成功）。返回 (ok, 提示)。"""
    if not available():
        return False, "当前环境不支持开机自启。"
    try:
        with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0,
                             _winreg.KEY_WRITE) as key:
            try:
                _winreg.DeleteValue(key, _RUN_VALUE_NAME)
            except FileNotFoundError:
                pass  # 已不存在 -> 幂等成功
        return True, "已关闭开机自启。"
    except Exception as exc:  # 失败静默（不打扰用户；状态读取以 is_enabled 为准）
        logger.warning("删除开机自启失败: %s", exc)
        return False, "关闭开机自启失败（可在系统设置 → 启动应用里移除）。"
