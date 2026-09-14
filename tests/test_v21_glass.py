"""tests/test_v21_glass.py —— 域2 毛玻璃内核单测（V21-03 / 设计 §7.1 / §7.2）。

覆盖口径：
- ``detect_capability`` mock build（22621 / 22000 / 19045）+ 远程桌面 → kind/supported 正确
- 非 Windows（monkeypatch ``sys.platform``）→ none 且不抛
- ``safe_apply`` 非法 hwnd（0 / None / "abc"）→ False 且不抛
- ``remove`` 非法 hwnd → False
- DWM 常量值断言（38 / 1029 / 2 / 3 / 1 / 0x1000）
- 不支持环境**不发起** ``DwmSetWindowAttribute``（G-0 验收②）

⚠ 本测试不真机修改窗口材质（无真实窗口）；真机取证见 V21-17。
"""
import sys

import pytest

from gui import glass


# ---------------------------------------------------------------------------
# fixtures / 工具
# ---------------------------------------------------------------------------
@pytest.fixture
def local_win11(monkeypatch):
    """把探测环境固定为「本地非远程 Windows」（可在测试内覆盖 build）。"""
    monkeypatch.setattr(glass, "_is_windows", lambda: True)
    monkeypatch.setattr(glass, "is_remote_session", lambda: False)
    return monkeypatch


def _record_dwm(monkeypatch, *, ret: bool = True):
    """替换 ``_dwm_set_attribute`` 为记录桩，返回 calls 列表。"""
    calls = []

    def _fake(hwnd, attribute, value):
        calls.append((hwnd, attribute, value))
        return ret

    monkeypatch.setattr(glass, "_dwm_set_attribute", _fake)
    return calls


def _boom(*_args, **_kwargs):
    raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# ① 常量值断言（契约冻结）
# ---------------------------------------------------------------------------
def test_dwm_constants_frozen_values():
    assert glass.DWMWA_USE_IMMERSIVE_DARK_MODE == 20
    assert glass.DWMWA_SYSTEMBACKDROP_TYPE == 38
    assert glass.DWMWA_MICA_EFFECT == 1029
    assert glass.DWMSBT_AUTO == 0
    assert glass.DWMSBT_NONE == 1
    assert glass.DWMSBT_MAINWINDOW == 2
    assert glass.DWMSBT_TRANSIENTWINDOW == 3
    assert glass.DWMSBT_TABBEDWINDOW == 4
    assert glass.SM_REMOTESESSION == 0x1000


# ---------------------------------------------------------------------------
# ② detect_capability：build → kind 判定
# ---------------------------------------------------------------------------
def test_detect_build_22621_mica_22h2_path(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    cap = glass.detect_capability()
    assert cap.supported is True
    assert cap.kind == "mica"
    assert cap.build == 22621
    assert "38" in cap.reason


def test_detect_build_22000_mica_21h2_private_path(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22000)
    cap = glass.detect_capability()
    assert cap.supported is True
    assert cap.kind == "mica"
    assert cap.build == 22000
    assert "1029" in cap.reason


def test_detect_build_22620_still_21h2_private_path(local_win11):
    """22620 < 22621 → 仍应走私有 attr=1029 路径。"""
    local_win11.setattr(glass, "_windows_build", lambda: 22620)
    cap = glass.detect_capability()
    assert cap.supported is True
    assert "1029" in cap.reason


def test_detect_build_19045_none_win10(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 19045)
    cap = glass.detect_capability()
    assert cap.supported is False
    assert cap.kind == "none"
    assert cap.build == 19045


def test_detect_build_21999_none_below_win11(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 21999)
    cap = glass.detect_capability()
    assert cap.supported is False
    assert cap.kind == "none"


def test_detect_remote_session_unsupported(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    local_win11.setattr(glass, "is_remote_session", lambda: True)
    cap = glass.detect_capability()
    assert cap.supported is False
    assert cap.kind == "none"
    assert "远程桌面" in cap.reason


def test_detect_non_windows_none_no_raise(monkeypatch):
    """非 Windows（monkeypatch sys.platform）→ none 且不抛。"""
    monkeypatch.setattr(sys, "platform", "linux")
    cap = glass.detect_capability()
    assert cap.supported is False
    assert cap.kind == "none"
    assert cap.build == 0
    assert "非 Windows" in cap.reason


def test_detect_exception_failsafe_none(monkeypatch):
    """探测内部异常 → 保守 none，不抛（fail-safe）。"""
    monkeypatch.setattr(glass, "_is_windows", _boom)
    cap = glass.detect_capability()
    assert cap.supported is False
    assert cap.kind == "none"
    assert cap.build == 0


def test_is_supported_projection(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    assert glass.is_supported() is True
    local_win11.setattr(glass, "_windows_build", lambda: 19045)
    assert glass.is_supported() is False


# ---------------------------------------------------------------------------
# ③ is_remote_session 保守语义
# ---------------------------------------------------------------------------
def test_is_remote_session_non_windows_true(monkeypatch):
    monkeypatch.setattr(glass, "_is_windows", lambda: False)
    assert glass.is_remote_session() is True


def test_is_remote_session_exception_true(monkeypatch):
    monkeypatch.setattr(glass, "_is_windows", lambda: True)

    class _Boom:
        def __getattr__(self, _name):
            raise RuntimeError("boom")

    monkeypatch.setattr(glass, "ctypes", _Boom())
    assert glass.is_remote_session() is True


# ---------------------------------------------------------------------------
# ④ apply_main_window / apply_dialog 分派
# ---------------------------------------------------------------------------
def test_apply_main_window_22h2_attr38_plus_dark(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    calls = _record_dwm(local_win11)
    assert glass.apply_main_window(1234, dark=True) is True
    assert calls[0] == (1234, glass.DWMWA_SYSTEMBACKDROP_TYPE, glass.DWMSBT_MAINWINDOW)
    assert (1234, glass.DWMWA_USE_IMMERSIVE_DARK_MODE, 1) in calls


def test_apply_main_window_21h2_private_1029(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22000)
    calls = _record_dwm(local_win11)
    assert glass.apply_main_window(1234, dark=False) is True
    assert calls[0] == (1234, glass.DWMWA_MICA_EFFECT, 1)
    assert (1234, glass.DWMWA_USE_IMMERSIVE_DARK_MODE, 0) in calls


def test_apply_dialog_22h2_transient_3(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    calls = _record_dwm(local_win11)
    assert glass.apply_dialog(77, dark=True) is True
    assert calls[0] == (77, glass.DWMWA_SYSTEMBACKDROP_TYPE, glass.DWMSBT_TRANSIENTWINDOW)


def test_apply_dialog_21h2_unsupported_no_dwm(local_win11):
    """21H2 无 Acrylic → 不发起 DWM 调用并返回 False。"""
    local_win11.setattr(glass, "_windows_build", lambda: 22000)
    calls = _record_dwm(local_win11)
    assert glass.apply_dialog(77, dark=True) is False
    assert calls == []


def test_apply_unsupported_win10_does_not_call_dwm(local_win11):
    """Win10 → 不发起 DwmSetWindowAttribute（G-0 验收②）。"""
    local_win11.setattr(glass, "_windows_build", lambda: 19045)
    calls = _record_dwm(local_win11)
    assert glass.apply_main_window(1234, dark=True) is False
    assert calls == []


def test_apply_remote_does_not_call_dwm(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    local_win11.setattr(glass, "is_remote_session", lambda: True)
    calls = _record_dwm(local_win11)
    assert glass.apply_main_window(1234, dark=True) is False
    assert calls == []


def test_apply_material_set_failure_returns_false(local_win11):
    """底层 DWM 返回失败 → False（不抛）。"""
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    _record_dwm(local_win11, ret=False)
    assert glass.apply_main_window(1234, dark=True) is False


def test_apply_invalid_hwnd_false_no_dwm(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    calls = _record_dwm(local_win11)
    for bad in (0, None, "abc", True, 1.5):
        assert glass.apply_main_window(bad, dark=True) is False
    assert calls == []


# ---------------------------------------------------------------------------
# ⑤ remove
# ---------------------------------------------------------------------------
def test_remove_22h2_sets_none_and_dark_off(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    calls = _record_dwm(local_win11)
    assert glass.remove(1234) is True
    assert calls[0] == (1234, glass.DWMWA_SYSTEMBACKDROP_TYPE, glass.DWMSBT_NONE)
    assert (1234, glass.DWMWA_USE_IMMERSIVE_DARK_MODE, 0) in calls


def test_remove_21h2_disables_private_1029(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22000)
    calls = _record_dwm(local_win11)
    assert glass.remove(1234) is True
    assert calls[0] == (1234, glass.DWMWA_MICA_EFFECT, 0)


def test_remove_win10_noop_returns_true(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 19045)
    _record_dwm(local_win11)
    assert glass.remove(1234) is True


def test_remove_invalid_hwnd_false_no_raise(local_win11):
    local_win11.setattr(glass, "_windows_build", lambda: 22621)
    calls = _record_dwm(local_win11)
    for bad in (0, None, "abc", True, 1.5):
        assert glass.remove(bad) is False
    assert calls == []


# ---------------------------------------------------------------------------
# ⑥ safe_apply：分派 + fail-safe
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [0, None, "abc", True, 1.5])
def test_safe_apply_invalid_hwnd_false_no_raise(bad, monkeypatch):
    monkeypatch.setattr(glass, "apply_main_window", _boom)
    monkeypatch.setattr(glass, "apply_dialog", _boom)
    assert glass.safe_apply(bad, "mica", dark=True) is False
    assert glass.safe_apply(bad, "acrylic", dark=False) is False


def test_safe_apply_dispatch_mica(monkeypatch):
    hit = []
    monkeypatch.setattr(glass, "apply_main_window",
                        lambda hwnd, *, dark: hit.append((("mica"), hwnd, dark)) or True)
    monkeypatch.setattr(glass, "apply_dialog",
                        lambda hwnd, *, dark: hit.append((("acrylic"), hwnd, dark)) or True)
    assert glass.safe_apply(11, "mica", dark=True) is True
    assert glass.safe_apply(22, "acrylic", dark=False) is True
    assert hit == [("mica", 11, True), ("acrylic", 22, False)]


def test_safe_apply_unknown_kind_false(monkeypatch):
    monkeypatch.setattr(glass, "apply_main_window", _boom)
    assert glass.safe_apply(11, "unknown", dark=True) is False


def test_safe_apply_swallows_apply_exception(monkeypatch):
    """分派实现抛异常 → safe_apply 仍返回 False（fail-safe 铁律）。"""
    monkeypatch.setattr(glass, "apply_main_window", _boom)
    assert glass.safe_apply(11, "mica", dark=True) is False
