# -*- coding: utf-8 -*-
"""v2.2 退出崩溃修复：``PageProject.RefreshThread`` 应用退出自我收口测试。

缺陷（既存，非本轮引入）：``gui/pages/page_project.py`` 的 ``RefreshThread``
以 ``parent=页面自身`` 持有且**无任何停机路径**；关窗那一刻扫描线程仍在运行时，
Qt 在 teardown 析构「仍在运行的 QThread」→ ``QThread: Destroyed while thread is
still running`` → **Windows fail-fast 0xC0000409**（子进程退出码矩阵实测复现）。

修法：继承 :class:`gui.qt_exit_guard.ExitSafeQThread`（机制同 ``kb_worker`` v2.1 #281）
—— 自挂 ``aboutToQuit`` + 父控件 ``destroyed`` → 幂等有界 ``stop()`` → 超时 detach。

覆盖（对齐 ``tests/test_v21_kb_worker_exit.py`` 范式，不依赖 pytest-qt）：
  ① ``stop()`` 幂等 + 有界（``wait_ms=0`` 不阻塞）
  ② 运行中 emit ``aboutToQuit`` → 线程被有界停住；挂接随后解除
  ③ 自然结束 → 解除 ``aboutToQuit`` 挂接（不泄漏连接）
  ④ 子进程崩溃守卫：退出期销毁承载运行中线程的页面 → 进程须**干净退出**；
     受控正对照（摘掉收口）→ 复现 fail-fast，证明守卫有效。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def qapp():
    """本地 QApplication fixture（不依赖 pytest-qt）。"""
    from gui.qt_compat import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _pump(app, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def _pump_until(app, pred, timeout: float) -> bool:
    end = time.perf_counter() + timeout
    while time.perf_counter() < end and not pred():
        app.processEvents()
        time.sleep(0.005)
    return pred()


def _slow_walk(monkeypatch, seconds: float, entered=None):
    """把 ``os.walk`` 换成「打盹 seconds 秒」的慢扫描（RefreshThread.run 直接调它）。"""
    import gui.pages.page_project as pp

    def slow(path, *a, **k):
        if entered is not None:
            entered.set()
        time.sleep(seconds)
        return iter(())

    monkeypatch.setattr(pp.os, "walk", slow)


# ---------------------------------------------------------------------------
# ① stop() 幂等 + 有界
# ---------------------------------------------------------------------------
class TestStopIdempotent:
    def test_stop_not_started_is_true(self, qapp):
        from gui.pages.page_project import RefreshThread
        t = RefreshThread(".")
        assert t.stop(wait_ms=0) is True
        assert t.stop() is True            # 幂等：连调不炸

    def test_stop_wait_zero_never_blocks(self, qapp, monkeypatch):
        from gui.pages.page_project import RefreshThread
        _slow_walk(monkeypatch, 0.5)
        t = RefreshThread(".")
        t.start()
        assert _pump_until(qapp, t.isRunning, 1.0)
        t0 = time.perf_counter()
        assert t.stop(wait_ms=0) is False          # 不等待 → 超时语义
        assert (time.perf_counter() - t0) < 0.2
        assert t.stop() is True                    # 再给上界 → 收口成功
        assert t.stop() is True                    # 再次调用仍幂等


# ---------------------------------------------------------------------------
# ② 运行中退出不挂起
# ---------------------------------------------------------------------------
class TestQuitDoesNotHang:
    def test_about_to_quit_stops_running_thread_bounded(self, qapp, monkeypatch):
        import threading
        from gui.pages.page_project import RefreshThread
        entered = threading.Event()
        _slow_walk(monkeypatch, 0.8, entered)
        t = RefreshThread(".")
        t.start()
        assert _pump_until(qapp, entered.is_set, 2.0), "线程未进入慢扫描"
        t0 = time.perf_counter()
        qapp.aboutToQuit.emit()
        dt = time.perf_counter() - t0
        assert not t.isRunning(), "退出收口后线程应立即结束"
        assert dt < 2.0, f"退出有界等待不得无限阻塞，实测 {dt:.3f}s"
        assert t._quit_app is None, "退出挂接应已解除"


# ---------------------------------------------------------------------------
# ③ 自然结束 → 解除挂接
# ---------------------------------------------------------------------------
class TestHookDetached:
    def test_hook_removed_after_normal_finish(self, qapp, monkeypatch):
        from gui.pages.page_project import RefreshThread
        _slow_walk(monkeypatch, 0.0)
        t = RefreshThread(".")
        t.start()
        assert _pump_until(qapp, lambda: not t.isRunning(), 2.0)
        _pump(qapp, 0.1)
        assert t._quit_app is None, "自然结束应解除 aboutToQuit 挂接"

    def test_parent_destroyed_hook_stops_child_before_delete(self, qapp, monkeypatch):
        """父控件 ``destroyed`` 先于「连坐删子线程」emit → 子线程被停住。"""
        from gui.qt_compat import QWidget
        from gui.pages.page_project import RefreshThread
        _slow_walk(monkeypatch, 0.6)
        page = QWidget()
        t = RefreshThread(".", page)
        seen = []
        # 后连接 → 在收口槽之后触发，可观察到「子线程已被停住」（此刻子对象尚未删除）
        page.destroyed.connect(lambda *_: seen.append(t.isRunning()))
        t.start()
        assert _pump_until(qapp, t.isRunning, 1.0)
        import shiboken6
        shiboken6.delete(page)                 # 触发父控件 destroyed（不崩即通过）
        assert seen == [False], f"父控件析构时应抢先把子线程停住，实测 seen={seen}"


# ---------------------------------------------------------------------------
# ④ 子进程崩溃守卫
# ---------------------------------------------------------------------------
_CHILD_SRC = r'''
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from gui.qt_compat import QApplication, QWidget
app = QApplication.instance() or QApplication([])

import os as _os
_real_walk = _os.walk
def _slow_walk(path, *a, **k):          # 让扫描必然仍在跑（否则命中窗口过窄）
    time.sleep(1.0)
    return _real_walk(path, *a, **k)
_os.walk = _slow_walk

from gui.pages.page_project import RefreshThread
page = QWidget()
t = RefreshThread(".", page)
t.start()
time.sleep(0.05)
running = t.isRunning()
if os.environ.get("PROJECT_GUARD_NOFIX") == "1":     # 受控正对照：摘掉两条收口挂载
    try: t._disconnect_app_quit()
    except Exception: pass
    try: page.destroyed.disconnect(t._on_parent_destroyed)
    except Exception: pass
app.aboutToQuit.emit()                               # 真实停机序列
import shiboken6
shiboken6.delete(page)                               # 应用拆除时销毁承载页面
print("running_before=%s teardown-ok" % running, flush=True)
'''


class TestQuitTeardownProcessGuard:
    def _run(self, nofix: bool):
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["CODEBUDDY_SAFE_DELETE_ENABLED"] = "0"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if nofix:
            env["PROJECT_GUARD_NOFIX"] = "1"
        else:
            env.pop("PROJECT_GUARD_NOFIX", None)
        return subprocess.run(
            [sys.executable, "-c", _CHILD_SRC], cwd=str(ROOT), env=env,
            capture_output=True, text=True, timeout=60,
        )

    def test_quit_teardown_exits_cleanly(self):
        """修复后：退出期销毁承载运行中 RefreshThread 的页面 → rc=0，无 QThread 告警。"""
        proc = self._run(nofix=False)
        assert proc.returncode == 0, (
            f"退出期崩溃 rc={proc.returncode}（0xC0000409=3221226505）\n"
            f"stderr:\n{proc.stderr[-800:]}"
        )
        assert "QThread: Destroyed while thread is still running" not in (proc.stderr or "")
        assert "teardown-ok" in (proc.stdout or "")

    @pytest.mark.skipif(sys.platform != "win32", reason="fail-fast 仅 Windows 复现")
    def test_positive_control_nofix_reproduces(self):
        """受控正对照：摘掉收口 → 同一代码版本复现 fail-fast（证明守卫有效）。"""
        proc = self._run(nofix=True)
        assert proc.returncode != 0, (
            "受控正对照应崩溃（若未崩溃，说明本守卫无法捕获回归）"
        )
