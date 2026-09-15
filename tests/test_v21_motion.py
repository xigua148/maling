# -*- coding: utf-8 -*-
"""V21-02 域1 动效内核单测（``gui/motion.py``）。

覆盖 design-v21 §7.1「motion」行全部可自动化断言点：
  · ``duration()`` 三档取值 + 夹取 ≤ ``MAX_DURATION_MS`` + ``off`` → 0（纯函数）；
  · 非法 ``configure`` 回落 ``DEFAULT_LEVEL``；
  · ``enabled()`` 随档位与系统开关变化；
  · ``off`` 下 ``animate()`` 返回 ``None`` 且**未实例化** ``QPropertyAnimation``（R-Q）；
  · ``standard`` 下 ``animate()`` 返回对象，跑完 ``running_count()`` 归零；
  · ``stop_all(final=True)`` 收束终态 + 登记清空 + 回调触发；
  · 无 ``QApplication`` 时调用不崩（含子进程真验证）；
  · ``system_animations_enabled()`` 读取失败 / 非 Windows → ``True``。

v2.x 循环动效（``loop()`` / ``stop_loop()`` / ``loop_period_ms()``，design §4.2【循环动效】）：
  · ``loop_period_ms()`` 纯函数夹取 ``[800, 1600]`` + 缺省 1200；
  · ``off`` 档 / 系统关动画 → ``loop()`` 返回 ``None`` 且不启动驱动器；
  · 每 tick 校验 ``enabled()`` → 禁用**立即自停** + ``on_disabled`` 回调（响应式立即停）；
  · ``stop_all()`` 一并停全部循环；``stop_loop()`` 幂等；``_LOOPS`` 不泄漏；owner 销毁自停；
  · 循环与一次性动画登记**互相隔离**（``running_loop_count()`` vs ``running_count()``）。

> 循环用例**不依赖真事件循环**（仓库 QTest.qWait 嵌套事件循环有崩溃先例）：
> 相位推进直接调 ``motion._tick_loops(now=...)``，禁用自停亦经同一入口确定性触发。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import os
import re
import subprocess
import sys
import time
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import gui.motion as motion
from gui.qt_compat import (
    QApplication, QEasingCurve, QGraphicsOpacityEffect, QObject, Qt, Signal, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]

# 捕获真实实现（autouse fixture 会用桩替换模块属性，测真实函数时需还原）
_REAL_SYSTEM_ANIMATIONS_ENABLED = motion.system_animations_enabled


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_motion(monkeypatch):
    """每例前后复位档位 / 登记表；默认放行系统开关（单例可再覆盖）。"""
    motion.stop_all(final=True)
    motion.configure("standard")
    monkeypatch.setattr(motion, "system_animations_enabled", lambda: True)
    yield
    motion.stop_all(final=True)
    motion.configure("standard")


@pytest.fixture
def qapp():
    """本地 QApplication fixture（不依赖 pytest-qt）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _CountingAnim(motion.QPropertyAnimation):
    """统计实例化次数的 QPropertyAnimation 子类（R-Q：断言 off 不创建对象）。"""

    created = 0

    def __init__(self, *args, **kwargs):
        type(self).created += 1
        super().__init__(*args, **kwargs)


def _pump_until_idle(qapp, timeout_s=3.0):
    """驱动事件循环直到动画登记表清空（或超时）。"""
    deadline = time.time() + timeout_s
    while motion.running_count() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


# ---------------------------------------------------------------------------
# ① duration() 档位取值 + 夹取 + off→0（纯函数）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lvl,expected", [("off", 0), ("soft", 130), ("standard", 200)])
def test_duration_default_per_level(lvl, expected):
    motion.configure(lvl)
    assert motion.duration() == expected
    assert motion.duration(0) == expected


def test_duration_clamp_and_off_zero():
    motion.configure("standard")
    assert motion.duration(100) == 100
    assert motion.duration(220) == 220
    assert motion.duration(1000) == motion.MAX_DURATION_MS == 220
    assert motion.duration(10_000) == 220

    motion.configure("soft")
    assert motion.duration(50) == 50
    assert motion.duration(9999) == 220

    motion.configure("off")
    assert motion.duration() == 0
    assert motion.duration(1) == 0
    assert motion.duration(500) == 0
    assert motion.duration(1000) == 0


def test_max_duration_constant():
    assert motion.MAX_DURATION_MS == 220
    assert motion._DURATION_MS == {"off": 0, "soft": 130, "standard": 200}
    assert motion.LEVELS == ("off", "soft", "standard")
    assert motion.DEFAULT_LEVEL == "standard"


# ---------------------------------------------------------------------------
# ② 非法 configure 回落 standard
# ---------------------------------------------------------------------------
def test_configure_invalid_falls_back_to_default():
    motion.configure("bogus")
    assert motion.level() == motion.DEFAULT_LEVEL == "standard"
    motion.configure(None)
    assert motion.level() == "standard"
    motion.configure("")
    assert motion.level() == "standard"
    motion.configure("STANDARD")
    assert motion.level() == "standard"

    motion.configure("off")
    assert motion.level() == "off"
    motion.configure("soft")
    assert motion.level() == "soft"


# ---------------------------------------------------------------------------
# ③ enabled()
# ---------------------------------------------------------------------------
def test_enabled_off_is_false():
    motion.configure("off")
    assert motion.enabled() is False


def test_enabled_respects_system_switch(monkeypatch):
    motion.configure("standard")
    monkeypatch.setattr(motion, "system_animations_enabled", lambda: False)
    assert motion.enabled() is False

    monkeypatch.setattr(motion, "system_animations_enabled", lambda: True)
    assert motion.enabled() is True
    motion.configure("soft")
    assert motion.enabled() is True


# ---------------------------------------------------------------------------
# easing()
# ---------------------------------------------------------------------------
def test_easing_is_out_cubic():
    curve = motion.easing()
    assert isinstance(curve, QEasingCurve)
    assert curve.type() == QEasingCurve.OutCubic


# ---------------------------------------------------------------------------
# ④ off 下 animate() 返回 None 且不实例化任何动画对象（R-Q）
# ---------------------------------------------------------------------------
def test_off_animate_returns_none_without_object(qapp, monkeypatch):
    monkeypatch.setattr(motion, "QPropertyAnimation", _CountingAnim)
    _CountingAnim.created = 0
    motion.configure("off")

    w = QWidget()
    anim = motion.animate(w, b"windowOpacity", 0.0, 1.0)
    assert anim is None
    assert motion.running_count() == 0
    assert _CountingAnim.created == 0


def test_off_fade_returns_none_without_effect(qapp):
    motion.configure("off")
    w = QWidget()
    anim = motion.fade(w, to=1.0)
    assert anim is None
    assert w.graphicsEffect() is None
    assert motion.running_count() == 0


# ---------------------------------------------------------------------------
# ⑤ standard 下 animate() 返回对象，跑完 running_count() 归零
# ---------------------------------------------------------------------------
def test_standard_animate_returns_object_and_finishes(qapp, monkeypatch):
    monkeypatch.setattr(motion, "QPropertyAnimation", _CountingAnim)
    _CountingAnim.created = 0
    motion.configure("standard")

    w = QWidget()
    done = []
    anim = motion.animate(
        w, b"windowOpacity", 0.2, 1.0, on_finished=lambda: done.append(1)
    )
    assert anim is not None
    assert _CountingAnim.created == 1
    assert motion.running_count() == 1

    _pump_until_idle(qapp)
    assert motion.running_count() == 0
    assert done == [1]
    assert w.windowOpacity() == pytest.approx(1.0, abs=1e-3)


def test_standard_fade_animates_and_cleans_up(qapp):
    motion.configure("standard")
    w = QWidget()
    done = []
    anim = motion.fade(w, to=1.0, duration_ms=100, on_finished=lambda: done.append(1))
    assert anim is not None
    eff = w.graphicsEffect()
    assert isinstance(eff, QGraphicsOpacityEffect)
    assert motion.running_count() == 1

    _pump_until_idle(qapp)
    assert motion.running_count() == 0
    assert done == [1]
    assert eff.opacity() == pytest.approx(1.0, abs=1e-3)


def test_fade_reuses_existing_effect(qapp):
    motion.configure("standard")
    w = QWidget()
    eff = QGraphicsOpacityEffect(w)
    w.setGraphicsEffect(eff)

    anim = motion.fade(w, to=0.5, duration_ms=100)
    assert anim is not None
    assert w.graphicsEffect() is eff
    motion.stop_all(final=True)


# ---------------------------------------------------------------------------
# ⑥ stop_all(final=True) 收束终态 + 登记清空 + 回调触发
# ---------------------------------------------------------------------------
def test_stop_all_final_converges_to_end_value(qapp):
    motion.configure("standard")
    w = QWidget()
    done = []
    anim = motion.animate(
        w, b"windowOpacity", 0.2, 1.0, duration_ms=200,
        on_finished=lambda: done.append(1),
    )
    assert anim is not None
    assert motion.running_count() == 1

    motion.stop_all(final=True)
    assert motion.running_count() == 0
    assert done == [1]
    assert w.windowOpacity() == pytest.approx(1.0, abs=1e-3)


def test_stop_all_non_final_clears_registry(qapp):
    motion.configure("standard")
    w = QWidget()
    anim = motion.animate(w, b"windowOpacity", 0.2, 1.0, duration_ms=200)
    assert anim is not None
    assert motion.running_count() == 1

    motion.stop_all(final=False)
    assert motion.running_count() == 0


def test_stop_all_when_empty_is_noop():
    assert motion.running_count() == 0
    motion.stop_all(final=True)
    assert motion.running_count() == 0


# ---------------------------------------------------------------------------
# ⑦ 无 QApplication 时调用不崩
# ---------------------------------------------------------------------------
def test_pure_functions_without_qapplication():
    """不创建 QApplication，纯函数与未实例化路径均不崩。"""
    motion.configure("off")
    assert motion.level() == "off"
    assert motion.duration() == 0
    assert motion.running_count() == 0
    motion.stop_all(final=True)

    motion.configure("bogus")
    assert motion.level() == "standard"
    assert motion.duration() == 200
    assert isinstance(motion.easing(), QEasingCurve)
    assert isinstance(motion.enabled(), bool)
    assert isinstance(motion.system_animations_enabled(), bool)


def test_import_and_call_in_clean_interpreter():
    """子进程真验证：全新解释器仅 import + 调用，无 QApplication 不崩。"""
    code = (
        "import gui.motion as m\n"
        "assert m.running_count() == 0\n"
        "m.configure('standard')\n"
        "assert m.level() == 'standard'\n"
        "assert m.duration() == 200\n"
        "assert m.duration(9999) == 220\n"
        "assert type(m.easing()).__name__ == 'QEasingCurve'\n"
        "assert isinstance(m.enabled(), bool)\n"
        "assert isinstance(m.system_animations_enabled(), bool)\n"
        "m.configure('off')\n"
        "assert m.duration() == 0\n"
        "m.stop_all(final=True)\n"
        "assert m.running_count() == 0\n"
        "print('OK')\n"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


# ---------------------------------------------------------------------------
# ⑧ system_animations_enabled() 失败兜底
# ---------------------------------------------------------------------------
def test_system_flag_none_returns_true(monkeypatch):
    monkeypatch.setattr(motion, "system_animations_enabled", _REAL_SYSTEM_ANIMATIONS_ENABLED)
    monkeypatch.setattr(motion, "_read_system_animation_flag", lambda: None)
    assert motion.system_animations_enabled() is True


def test_system_flag_false_is_respected(monkeypatch):
    monkeypatch.setattr(motion, "system_animations_enabled", _REAL_SYSTEM_ANIMATIONS_ENABLED)
    monkeypatch.setattr(motion, "_read_system_animation_flag", lambda: False)
    assert motion.system_animations_enabled() is False


def test_system_flag_true(monkeypatch):
    monkeypatch.setattr(motion, "system_animations_enabled", _REAL_SYSTEM_ANIMATIONS_ENABLED)
    monkeypatch.setattr(motion, "_read_system_animation_flag", lambda: True)
    assert motion.system_animations_enabled() is True


def test_system_flag_non_windows_returns_none(monkeypatch):
    monkeypatch.setattr(motion, "system_animations_enabled", _REAL_SYSTEM_ANIMATIONS_ENABLED)
    monkeypatch.setattr(motion, "os", types.SimpleNamespace(name="posix"))
    assert motion._read_system_animation_flag() is None
    assert motion.system_animations_enabled() is True


def test_system_flag_ctypes_failure_returns_true(monkeypatch):
    if os.name != "nt":
        pytest.skip("非 Windows 已由非 NT 分支覆盖")

    import ctypes as _ctypes

    monkeypatch.setattr(motion, "system_animations_enabled", _REAL_SYSTEM_ANIMATIONS_ENABLED)

    class _Boom:
        def __getattr__(self, item):
            raise OSError("windll unavailable")

    monkeypatch.setattr(_ctypes, "windll", _Boom())
    assert motion.system_animations_enabled() is True


def test_system_flag_real_call_is_bool():
    assert isinstance(_REAL_SYSTEM_ANIMATIONS_ENABLED(), bool)


# ---------------------------------------------------------------------------
# ⑨ 循环动效：loop_period_ms() 纯函数
# ---------------------------------------------------------------------------
def test_loop_period_constants():
    assert motion.MIN_LOOP_PERIOD_MS == 800
    assert motion.MAX_LOOP_PERIOD_MS == 1600
    assert motion._DEFAULT_LOOP_PERIOD_MS == 1200


@pytest.mark.parametrize("base,expected", [
    (0, 1200),          # 缺省
    (-5, 1200),         # 非法（≤0）→ 缺省
    (300, 800),         # 低于下限 → 夹到 800
    (800, 800),         # 边界
    (1000, 1000),       # 区间内原样
    (1600, 1600),       # 边界
    (9999, 1600),       # 高于上限 → 夹到 1600
])
def test_loop_period_ms_clamp(base, expected):
    assert motion.loop_period_ms(base) == expected


def test_loop_period_ms_ignores_bool_and_non_numeric():
    assert motion.loop_period_ms(True) == 1200
    assert motion.loop_period_ms(None) == 1200
    assert motion.loop_period_ms("1200") == 1200


# ---------------------------------------------------------------------------
# ⑩ loop()：off / 系统关 / 非法 on_tick → 不启动、返回 None（R-Q）
# ---------------------------------------------------------------------------
def test_loop_off_returns_none_and_no_active_driver(qapp):
    motion.configure("off")
    w = QWidget()
    handle = motion.loop(w, lambda p: None)
    assert handle is None
    assert motion.running_loop_count() == 0
    assert (motion._DRIVER is None) or (not motion._DRIVER.isActive())


def test_loop_system_disabled_returns_none(qapp, monkeypatch):
    monkeypatch.setattr(motion, "system_animations_enabled", lambda: False)
    assert motion.loop(QWidget(), lambda p: None) is None
    assert motion.running_loop_count() == 0


def test_loop_bad_on_tick_returns_none(qapp):
    assert motion.loop(QWidget(), None) is None
    assert motion.loop(QWidget(), "not-callable") is None
    assert motion.running_loop_count() == 0


# ---------------------------------------------------------------------------
# ⑪ loop()：启动 / 周期夹取 / 驱动器唯一且按需启停
# ---------------------------------------------------------------------------
def test_loop_starts_registers_and_clamps_period(qapp):
    w = QWidget()
    handle = motion.loop(w, lambda p: None, period_ms=100)
    assert handle is not None
    assert handle.period_ms == 800                      # 夹到下限
    assert motion.running_loop_count() == 1
    assert motion._DRIVER is not None and motion._DRIVER.isActive()

    h2 = motion.loop(QWidget(), lambda p: None, period_ms=9999)
    assert h2.period_ms == 1600                          # 夹到上限
    h3 = motion.loop(QWidget(), lambda p: None)
    assert h3.period_ms == 1200                          # 缺省
    assert motion.running_loop_count() == 3


def test_loop_driver_stops_when_no_loops_left(qapp):
    h = motion.loop(QWidget(), lambda p: None)
    assert motion._DRIVER is not None and motion._DRIVER.isActive()
    motion.stop_loop(h)
    assert not motion._DRIVER.isActive()
    assert motion.running_loop_count() == 0


# ---------------------------------------------------------------------------
# ⑫ 相位推进：_tick_loops(now=...) 确定性（不依赖事件循环）
# ---------------------------------------------------------------------------
def test_loop_tick_advances_progress_deterministically(qapp):
    seen = []
    handle = motion.loop(QWidget(), lambda p: seen.append(p), period_ms=1000)
    assert handle is not None

    motion._tick_loops(now=handle.started_at + 0.00)
    motion._tick_loops(now=handle.started_at + 0.25)
    motion._tick_loops(now=handle.started_at + 0.50)
    assert seen[0] == pytest.approx(0.0)
    assert seen[1] == pytest.approx(0.25)
    assert seen[2] == pytest.approx(0.50)

    # 回绕：超过一个周期后回到同相位
    motion._tick_loops(now=handle.started_at + 1.25)
    assert seen[3] == pytest.approx(0.25)
    assert all(0.0 <= p < 1.0 for p in seen)


# ---------------------------------------------------------------------------
# ⑬ 响应式立即停：每 tick 校验 enabled()，禁用即自停 + on_disabled
# ---------------------------------------------------------------------------
def test_loop_self_stops_when_system_disabled_midway(qapp, monkeypatch):
    seen, disabled = [], []
    handle = motion.loop(
        QWidget(), lambda p: seen.append(p), on_disabled=lambda: disabled.append(1)
    )
    assert handle is not None and motion.running_loop_count() == 1

    monkeypatch.setattr(motion, "system_animations_enabled", lambda: False)
    motion._tick_loops(now=handle.started_at + 0.1)

    assert motion.running_loop_count() == 0
    assert disabled == [1]        # 落点被通知切静态形态
    assert seen == []             # 禁用当拍不再回调 on_tick


def test_loop_self_stops_when_level_switched_off(qapp):
    disabled = []
    handle = motion.loop(QWidget(), lambda p: None, on_disabled=lambda: disabled.append(1))
    assert handle is not None

    motion.configure("off")
    motion._tick_loops(now=handle.started_at + 0.1)

    assert motion.running_loop_count() == 0
    assert disabled == [1]


def test_loop_tick_with_no_loops_is_noop_and_stops_driver(qapp):
    motion._tick_loops(now=123.0)   # 空集合：静默
    assert motion.running_loop_count() == 0


# ---------------------------------------------------------------------------
# ⑭ stop_all() 一并停全部循环（含 on_disabled）
# ---------------------------------------------------------------------------
def test_stop_all_stops_all_loops_and_notifies(qapp):
    d1, d2 = [], []
    h1 = motion.loop(QWidget(), lambda p: None, on_disabled=lambda: d1.append(1))
    h2 = motion.loop(QWidget(), lambda p: None, on_disabled=lambda: d2.append(1))
    assert h1 is not None and h2 is not None
    assert motion.running_loop_count() == 2

    motion.stop_all(final=True)

    assert motion.running_loop_count() == 0
    assert d1 == [1] and d2 == [1]
    assert not motion._LOOPS
    assert motion._DRIVER is None or not motion._DRIVER.isActive()


def test_stop_all_non_final_stops_loops_without_notify(qapp):
    disabled = []
    motion.loop(QWidget(), lambda p: None, on_disabled=lambda: disabled.append(1))
    motion.stop_all(final=False)
    assert motion.running_loop_count() == 0
    assert disabled == []


# ---------------------------------------------------------------------------
# ⑮ stop_loop() 幂等 + 不泄漏 + 与动画登记互相隔离
# ---------------------------------------------------------------------------
def test_stop_loop_is_idempotent_and_leak_free(qapp):
    handle = motion.loop(QWidget(), lambda p: None)
    assert motion.running_loop_count() == 1

    motion.stop_loop(handle)
    assert motion.running_loop_count() == 0
    assert handle not in motion._LOOPS
    assert not motion._LOOPS

    # 重复 / 未知 / None 句柄：静默、不抛、不留登记
    motion.stop_loop(handle)
    motion.stop_loop(None)
    motion.stop_loop("bogus")
    motion.stop_loop(object())
    assert motion.running_loop_count() == 0
    assert not motion._LOOPS


def test_loop_does_not_touch_animation_registry(qapp):
    handle = motion.loop(QWidget(), lambda p: None)
    assert handle is not None
    assert motion.running_count() == 0        # 一次性动画登记不受污染
    assert motion.running_loop_count() == 1
    motion.stop_loop(handle)


def test_explicit_stop_loop_does_not_trigger_on_disabled(qapp):
    disabled = []
    handle = motion.loop(QWidget(), lambda p: None, on_disabled=lambda: disabled.append(1))
    motion.stop_loop(handle)
    assert disabled == []                      # 显式停 ≠ 因禁用而停


# ---------------------------------------------------------------------------
# ⑯ owner 销毁自动停（防泄漏）
# ---------------------------------------------------------------------------
def test_loop_owner_destroyed_autostops(qapp):
    try:
        import shiboken6
    except Exception:
        pytest.skip("shiboken6 不可用")

    w = QWidget()
    handle = motion.loop(w, lambda p: None)
    assert handle is not None and motion.running_loop_count() == 1

    shiboken6.delete(w)                        # 立即销毁 C++ 对象 → destroyed 信号

    assert motion.running_loop_count() == 0
    assert handle not in motion._LOOPS


# ---------------------------------------------------------------------------
# ⑰ 无 QApplication 时 loop() 不崩、不启动
# ---------------------------------------------------------------------------
def test_loop_without_qapplication_returns_none():
    """子进程真验证：无 QApplication 调 loop() 安全返回 None。"""
    code = (
        "import gui.motion as m\n"
        "m.configure('standard')\n"
        "assert m.loop(None, lambda p: None) is None\n"
        "assert m.running_loop_count() == 0\n"
        "print('OK')\n"
    )
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


# ---------------------------------------------------------------------------
# ⑱ 既有 R-P 债：控件"隐藏即停"（可执行证明）
#   · ThinkingIndicator —— 隐藏停循环 / 仅 _active 时复启（v2.x 落点①：timer → motion.loop）
#   · EmotionArcWidget  —— 呼吸表按可见性启停（v2.x 修复：QTimer → motion.loop，见 ⑲）
# ---------------------------------------------------------------------------
def test_thinking_indicator_hidden_stops_timer(qapp):
    from gui import motion
    from gui.widgets.thinking_indicator import ThinkingIndicator

    motion.configure("standard")
    w = ThinkingIndicator("AI 正在思考", app_context=None)
    base = motion.running_loop_count()
    w.start()
    assert w._active is True
    assert motion.running_loop_count() == base + 1      # 可见态在跑（文字节奏经 motion.loop）

    w.hide()                                            # ← 隐藏
    assert motion.running_loop_count() == base          # 隐藏即停（旧实现此处仍空转）

    w.show()                                            # 仍处活动态 → 复启
    assert motion.running_loop_count() == base + 1

    w.stop()                                            # 业务结束
    assert w._active is False
    assert motion.running_loop_count() == base
    w.show()
    assert motion.running_loop_count() == base          # 非活动态：显示也不复启


def test_thinking_indicator_off_is_static_not_blank(qapp):
    """落点① R-Q（阶段 B 回退后）：``off`` 档定格**静态纯文字省略号**，无几何图形、不空白。"""
    from gui import motion
    from gui.widgets.thinking_indicator import ThinkingIndicator
    from gui.widgets.loop_indicator import LoopIndicator

    motion.configure("off")
    try:
        w = ThinkingIndicator("AI 正在思考", app_context=None)
        w.start()
        assert motion.running_loop_count() == 0         # off 不起循环
        assert w._dots.text() == "…"                    # 静态纯文字省略号（非空白）
        # v2.1(UI)：文案改为「<当前角色名> 正在思考」，不再绑死 "AI"
        _t = w._label.text()
        assert _t.strip()
        assert _t.endswith("正在思考")
        assert w.findChild(LoopIndicator) is None       # 无自绘几何图形
    finally:
        motion.configure("standard")


def _arc_ring(cell):
    """从今日格样式表读出外圈色（``border: 2px solid <color>;``）。"""
    if cell is None:
        return None
    m = re.search(r"border:\s*2px solid\s+([^;]+);", cell.styleSheet())
    return m.group(1).strip() if m else None


def _emotion_arc(qapp, app_ctx=None):
    """构造 EmotionArcWidget 并注入今日情绪（今日格可呼吸）；WA_DontShowOnScreen。"""
    from datetime import datetime
    from gui.widgets.emotion_arc import EmotionArcWidget

    w = EmotionArcWidget(app_ctx=app_ctx)
    w.refresh_arc([{"time": datetime.now().isoformat(), "emotion": "happy"}])
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    return w


class _PagerStub(QObject):
    """最小 page_manager 桩：只提供既有 ``page_changed`` 信号。"""

    page_changed = Signal(str)


# ---------------------------------------------------------------------------
# ⑲ EmotionArcWidget：呼吸**迁 motion.loop**（修 D-V21-01 自建循环违例）
#   · 可见才呼吸 / 隐藏即停 / 重复 show-hide **幂等**（不产生多个循环）
#   · ``off`` 档不启动循环（无句柄、无活动循环、外圈定格透明 = 静态形态）
#   · 运行中切 ``off`` → on_disabled 触发 → 外圈被**强制切静态**（R-Q 硬要求）
#   · 节拍保真：**每周期翻转一次**（半周期 = 1 个 period；实测 ≈1600ms，贴原 1400ms）
#   · 自愈：off→非 off 且收到既有广播（page_changed）→ 自动恢复呼吸
# ---------------------------------------------------------------------------
def test_emotion_arc_loop_follows_visibility(qapp):
    """可见才呼吸：构造不启动 / 显示即启 / 隐藏即停；重复 show/hide 幂等。"""
    motion.configure("standard")
    base = motion.running_loop_count()
    w = _emotion_arc(qapp)
    # 不再 __init__ 即空转：构造后既无句柄也无循环。
    assert w._breath_handle is None
    assert motion.running_loop_count() == base

    w.show()
    assert w._breath_handle is not None
    assert motion.running_loop_count() == base + 1   # 可见才呼吸
    w.show()                                          # 重复 show 不重复起循环（幂等）
    assert motion.running_loop_count() == base + 1

    w.hide()
    assert w._breath_handle is None
    assert motion.running_loop_count() == base        # 隐藏即停
    w.hide()                                          # 重复 hide 不抛、不残留
    assert motion.running_loop_count() == base

    w.show()
    assert motion.running_loop_count() == base + 1   # 再次可见 → 复启
    w.hide()
    assert motion.running_loop_count() == base


def test_emotion_arc_off_creates_no_loop_and_is_static(qapp):
    """``off`` 档：``motion.loop`` 未创建（无句柄/无活动循环），外圈定格透明静态。"""
    motion.configure("off")
    try:
        w = _emotion_arc(qapp)
        w.show()
        assert w._breath_handle is None
        assert motion.running_loop_count() == 0
        assert w._breath_on is False
        assert _arc_ring(w._today_cell) == "transparent"   # 静态形态（非高亮）
    finally:
        motion.configure("standard")


def test_emotion_arc_disabled_switches_to_static(qapp):
    """最关键一条：运行中切 ``off`` → on_disabled → 外圈**强制切静态**（透明）。"""
    motion.configure("standard")
    w = _emotion_arc(qapp)
    w.show()
    assert motion.running_loop_count() == 1

    w._on_tick(0.2)                                    # 前半周期 → 高亮
    assert w._breath_on is True
    assert _arc_ring(w._today_cell) != "transparent"

    motion.configure("off")
    motion._tick_loops()                               # 每 tick 校验 enabled() → 立即自停并回调
    assert motion.running_loop_count() == 0
    assert w._breath_handle is None
    assert w._breath_on is False
    assert _arc_ring(w._today_cell) == "transparent"   # 强制静态（R-Q：不留动画残留）
    motion.configure("standard")


def test_emotion_arc_stop_all_switches_to_static(qapp):
    """``stop_all(final=True)``（退出 / 换肤 / 切 off）一并停并切静态。"""
    motion.configure("standard")
    w = _emotion_arc(qapp)
    w.show()
    assert motion.running_loop_count() == 1

    motion.stop_all(final=True)
    assert motion.running_loop_count() == 0
    assert w._breath_handle is None
    assert w._breath_on is False
    assert _arc_ring(w._today_cell) == "transparent"


def test_emotion_arc_period_flip_once_per_cycle(qapp):
    """节拍保真：外圈**每过一个周期翻转一次**（半周期 = 1 个 period，非每帧/半周期）。

    确定性：直接注入单调递增的相位序列（两次回绕 = 两个周期），断言恰好翻转两次、
    半周期内状态恒定 —— 与实测「半周期 ≈1600ms」口径一致。
    """
    motion.configure("standard")
    w = _emotion_arc(qapp)
    w.show()                                           # show → _on_tick(0.0) → 首帧高亮
    assert w._breath_on is True
    accent = _arc_ring(w._today_cell)
    assert accent != "transparent"

    states = []
    # 两个周期：相位在 [0,1) 内递增，跨周期回绕两次
    for p in (0.1, 0.5, 0.9, 0.0, 0.1, 0.5, 0.9, 0.0, 0.1):
        w._on_tick(p)
        states.append(w._breath_on)
    # 第 1 周期恒高亮；回绕 1 次 → 第 2 周期恒透明；回绕 2 次 → 回到高亮
    assert states == [True, True, True, False, False, False, False, True, True], states
    assert w._breath_period_n == 2                     # 单调递增：两次回绕 = 两个周期
    w._on_tick(0.2)                                    # 同一周期内不跳变
    assert _arc_ring(w._today_cell) == accent
    w.hide()


def test_emotion_arc_resumes_after_reenable_via_page_changed(qapp):
    """自愈：off（无句柄）→ 切回非 off 且收到既有广播（page_changed）→ 呼吸自动恢复。"""
    from types import SimpleNamespace

    pager = _PagerStub()
    motion.configure("off")
    w = _emotion_arc(qapp, app_ctx=SimpleNamespace(page_manager=pager))
    w.show()
    assert w._breath_handle is None                    # off 档：不启动、静态
    assert motion.running_loop_count() == 0

    motion.configure("standard")                       # 切回非 off（此刻仍无句柄）
    assert w._breath_handle is None
    assert motion.running_loop_count() == 0

    pager.page_changed.emit("memory_book")             # 既有广播到达 → 自愈恢复
    assert w._breath_handle is not None
    assert motion.running_loop_count() == 1

    pager.page_changed.emit("memory_book")             # 重复广播幂等
    assert motion.running_loop_count() == 1

    w.hide()
    assert motion.running_loop_count() == 0
    pager.page_changed.emit("memory_book")             # 隐藏时广播不启动（可见性守卫）
    assert motion.running_loop_count() == 0


def test_emotion_arc_no_pager_is_silent(qapp):
    """无 page_manager（app_ctx=None）时构造不崩、订阅静默跳过、显示即呼吸。"""
    motion.configure("standard")
    w = _emotion_arc(qapp)                             # app_ctx=None
    assert motion.running_loop_count() == 0            # 未 show：不启动
    w.show()
    assert motion.running_loop_count() == 1
    w.hide()
    assert motion.running_loop_count() == 0
