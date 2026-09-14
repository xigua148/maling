"""gui/hotkeys.py —— v1.3 P1-3 全局热键（ctypes RegisterHotKey + QAbstractNativeEventFilter）

设计（docs/design-v13.md D-V13-01 / PRD P1-3）：
  - Win32 `RegisterHotKey`（hwnd=NULL，注册到当前线程消息队列）+ Qt 原生事件过滤器
    接收 WM_HOTKEY：零第三方依赖、无需全局钩子、精确；
  - HotkeyManager 统一注册两类动作：
      toggle      默认 Ctrl+Alt+M  → 主窗显示/隐藏（main_window.toggle_visibility）
      screenshot  默认 Ctrl+Alt+S  → 调 chat_panel.capture_screenshot
  - 注册失败（被占用/不支持组合）→ 静默降级：保留管理器、记 reason、emit 状态信号，
    设置页可改键后重注册；绝不让注册失败阻断启动。
  - 组合串格式与 QKeySequence 对齐（"Ctrl+Alt+M"），设置页 QKeySequenceEdit 采集。
"""
from __future__ import annotations

import ctypes
import logging
import os
from typing import Callable, Dict, Optional

from gui.qt_compat import QObject, Signal

logger = logging.getLogger("maid_coder.gui")

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# ---- 防御式加载 Win32 热键 API（仅 Windows）----
_WIN_OK = False
if os.name == "nt":
    try:
        from ctypes import wintypes

        _user32 = ctypes.WinDLL("user32", use_last_error=True)
        _user32.RegisterHotKey.argtypes = [
            wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT
        ]
        _user32.RegisterHotKey.restype = wintypes.BOOL
        _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        _user32.UnregisterHotKey.restype = wintypes.BOOL

        _WIN_OK = True
    except Exception as _e:
        _WIN_OK = False
        logger.debug("RegisterHotKey API 不可用（全局热键停用）: %s", _e)


# ---------------------------------------------------------------------------
# 组合串解析/格式化（"Ctrl+Alt+M" 风格，与 QKeySequence.toString 对齐）
# ---------------------------------------------------------------------------
_MOD_TOKEN = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "ctl": MOD_CONTROL,
    "alt": MOD_ALT, "option": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN,
}


def _mod_token(token: str) -> Optional[int]:
    return _MOD_TOKEN.get(token.lower().strip())


def parse_hotkey_combo(combo: str):
    """解析 "Ctrl+Alt+M" -> (fsModifiers, vk) 或 (None, 原因)。"""
    text = (combo or "").strip()
    if not text:
        return None, "空热键"
    parts = [p.strip() for p in text.replace("+", " ").split() if p.strip()]
    if not parts:
        return None, "空热键"
    key_token = parts[-1].lower()
    mods = 0
    for tok in parts[:-1]:
        m = _mod_token(tok)
        if m is None:
            return None, f"不支持的修饰键: {tok}"
        mods |= m
    # 键本体：字母 / 数字 / F1..F24
    vk = None
    if len(key_token) == 1 and key_token.isalpha():
        vk = ord(key_token.upper())
    elif len(key_token) == 1 and key_token.isdigit():
        vk = ord(key_token)
    elif key_token.startswith("f") and key_token[1:].isdigit():
        n = int(key_token[1:])
        if 1 <= n <= 24:
            vk = 0x6F + n  # VK_F1=0x70
    if vk is None:
        return None, f"不支持的按键: {key_token}"
    return (mods | MOD_NOREPEAT, vk), None


# ---------------------------------------------------------------------------
# Qt 原生事件过滤器（WM_HOTKEY 分发）
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QAbstractNativeEventFilter

    class _HotkeyNativeFilter(QAbstractNativeEventFilter):
        def __init__(self, manager):
            super().__init__()
            self._mgr = manager

        def nativeEventFilter(self, eventType, message):  # noqa: N802
            if eventType != b"windows_generic_MSG":
                return False
            try:
                from ctypes import wintypes
                if message is None:
                    return False
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    return self._mgr._dispatch(int(msg.wParam))
            except Exception as exc:
                logger.debug("WM_HOTKEY 解析失败（可忽略）: %s", exc)
            return False

    _NATIVE_FILTER_OK = True
except Exception:
    _NATIVE_FILTER_OK = False
    _HotkeyNativeFilter = None


# ---------------------------------------------------------------------------
# HotkeyManager
# ---------------------------------------------------------------------------
class HotkeyManager(QObject):
    """全局热键管理器：注册/注销/改键；失败静默降级 + 状态信号。

    - hotkey_registered(name, ok)：每次注册尝试后的结果（供状态栏/设置提示）。
    """

    hotkey_registered = Signal(str, bool)   # (name, ok)

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._entries: Dict[str, dict] = {}
        self._by_id: Dict[int, str] = {}
        self._next_id = 1
        self._filter = None
        self._installed = False
        self._win_ok = bool(_WIN_OK and _NATIVE_FILTER_OK)
        if not self._win_ok:
            logger.warning("全局热键管理器不可用（仅 Windows + Qt 原生过滤器可用时生效）")

    @property
    def available(self) -> bool:
        return self._win_ok

    def _install(self) -> bool:
        if self._installed or not self._win_ok or _HotkeyNativeFilter is None:
            return self._installed
        try:
            from gui.qt_compat import QApplication
            app = QApplication.instance()
            if app is None:
                return False
            self._filter = _HotkeyNativeFilter(self)
            app.installNativeEventFilter(self._filter)
            self._installed = True
        except Exception as exc:
            logger.warning("原生事件过滤器安装失败（全局热键停用）: %s", exc)
            self._win_ok = False
        return self._installed

    # -- 对外 API --
    def register(self, name: str, combo: str, callback: Callable[[], None]) -> bool:
        """注册（或替换同名）热键。返回是否成功；失败原因经 entry.state 查询。"""
        if not self._win_ok:
            self._record(name, combo, callback, False, "当前平台不支持全局热键")
            return False
        parsed, err = parse_hotkey_combo(combo)
        if err is not None:
            self._record(name, combo, callback, False, err)
            return False
        mods, vk = parsed
        if name in self._entries:
            self.unregister(name)
        if not self._install():
            self._record(name, combo, callback, False, "原生事件过滤器未就绪")
            return False
        hk_id = self._next_id
        self._next_id += 1
        err = None
        try:
            ok = bool(_user32.RegisterHotKey(None, hk_id, mods, vk))
        except Exception as exc:
            ok = False
            err = str(exc)
        if ok:
            self._entries[name] = {
                "combo": combo, "callback": callback, "id": hk_id,
                "ok": True, "reason": "",
            }
            self._by_id[hk_id] = name
            logger.info("全局热键已注册: %s = %s", name, combo)
        else:
            last = 0
            try:
                last = ctypes.get_last_error()
            except Exception:
                pass
            if err is None:
                err = f"注册被拒绝（可能被占用，错误码 {last}）"
            self._record(name, combo, callback, False, err)
        self.hotkey_registered.emit(name, ok)
        return ok

    def _record(self, name, combo, callback, ok: bool, reason: str) -> None:
        self._entries[name] = {
            "combo": combo, "callback": callback, "id": 0,
            "ok": ok, "reason": reason,
        }
        logger.warning("全局热键 %s=%s 注册失败: %s", name, combo, reason)
        self.hotkey_registered.emit(name, ok)

    def unregister(self, name: str) -> None:
        entry = self._entries.pop(name, None)
        if entry is None:
            return
        hk_id = entry.get("id") or 0
        self._by_id.pop(hk_id, None)
        if hk_id and self._win_ok:
            try:
                _user32.UnregisterHotKey(None, hk_id)
            except Exception:
                pass

    def change_combo(self, name: str, combo: str, callback: Optional[Callable[[], None]] = None) -> bool:
        """设置页改键：注销旧键并以新组合注册（回调保持或换新）。"""
        old = self._entries.get(name)
        if callback is None and old is not None:
            callback = old.get("callback")
        self.unregister(name)
        if callback is None:
            return False
        return self.register(name, combo, callback)

    def state(self, name: str) -> dict:
        """查询注册状态：(ok, combo, reason)。"""
        entry = self._entries.get(name)
        if entry is None:
            return {"ok": False, "combo": "", "reason": "未注册"}
        return {"ok": bool(entry.get("ok")), "combo": entry.get("combo", ""),
                "reason": entry.get("reason", "")}

    def _dispatch(self, hk_id: int) -> bool:
        name = self._by_id.get(hk_id)
        if name is None:
            return False
        entry = self._entries.get(name)
        if entry is None:
            return False
        cb = entry.get("callback")
        if cb is None:
            return True
        try:
            cb()
        except Exception as exc:
            logger.warning("全局热键 %s 回调异常: %s", name, exc)
        return True

    def shutdown(self) -> None:
        for name in list(self._entries.keys()):
            self.unregister(name)
        self._entries.clear()
        self._by_id.clear()
        if self._installed:
            try:
                from gui.qt_compat import QApplication
                app = QApplication.instance()
                if app is not None and self._filter is not None:
                    app.removeNativeEventFilter(self._filter)
            except Exception:
                pass
        self._installed = False
        self._filter = None
