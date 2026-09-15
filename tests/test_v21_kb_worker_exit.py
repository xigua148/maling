# -*- coding: utf-8 -*-
"""v2.1 知识库 worker「应用退出收口」测试（任务 #281 / design-v21 收口批）。

对齐 ``tests/test_v161_quit.py`` 范式：本地 ``qapp`` fixture（不依赖 pytest-qt）+
记录型假件；``QT_QPA_PLATFORM=offscreen``。

覆盖：
  ① worker 运行中退出不挂起（aboutToQuit → 幂等取消 + **有界** wait → 线程结束）
  ② ``stop()`` 幂等（连调两次不炸；``cancel()`` 幂等）
  ③ 退出收口后不再 emit / 退出挂接被解除（不泄漏连接）
  ④ 子进程崩溃守卫：应用退出时销毁承载运行中 worker 的对话框，进程须**干净退出**
     （修复前实测 fail-fast 0xC0000409；此为回归绊线——摘掉收口即红）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
QT_QPA = "offscreen"


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


def _patch_slow_index(monkeypatch, seconds: float, entered=None):
    """把 ``KnowledgeBase.index_directory`` 换成"打盹 seconds 秒"的阻塞调用。"""
    import helpers

    def slow(self, directory, *a, **k):
        if entered is not None:
            entered.set()
        time.sleep(seconds)
        return "indexed"

    monkeypatch.setattr(helpers.KnowledgeBase, "index_directory", slow)


# ---------------------------------------------------------------------------
# ② stop() / cancel() 幂等
# ---------------------------------------------------------------------------
class TestStopIdempotent:
    def test_stop_twice_not_started(self, qapp):
        from gui.widgets.kb_worker import KbSearchWorker
        w = KbSearchWorker("idx.json", "q")
        assert w.stop(wait_ms=0) is True
        assert w.stop(wait_ms=0) is True          # 幂等：连调两次不炸
        w.cancel()
        w.cancel()                                 # 幂等
        assert w.is_cancelled() is True

    def test_stop_twice_while_running(self, qapp, monkeypatch):
        from gui.widgets.kb_worker import KbIndexWorker
        _patch_slow_index(monkeypatch, 0.3)
        w = KbIndexWorker("idx.json", ".")
        w.start()
        assert w.stop() is True                    # 有界 wait → 结束
        assert w.stop() is True                    # 再次调用不炸
        assert not w.isRunning()


# ---------------------------------------------------------------------------
# ① worker 运行中退出不挂起
# ---------------------------------------------------------------------------
class TestQuitDoesNotHang:
    def test_about_to_quit_stops_running_worker_bounded(self, qapp, monkeypatch):
        from gui.widgets.kb_worker import KbIndexWorker
        entered = threading.Event()
        _patch_slow_index(monkeypatch, 0.8, entered)
        w = KbIndexWorker("idx.json", ".")
        w.start()
        assert _pump_until(qapp, entered.is_set, 2.0), "worker 未进入耗时调用"
        t0 = time.perf_counter()
        qapp.aboutToQuit.emit()                    # 应触发自我收口（有界 wait）
        dt = time.perf_counter() - t0
        assert not w.isRunning(), "退出收口后 worker 应立即结束"
        assert dt < 2.0, f"退出有界等待不得无限阻塞，实测 {dt:.3f}s"

    def test_stop_wait_zero_never_blocks(self, qapp, monkeypatch):
        """``stop(wait_ms=0)`` → 不等待直接返回（有界上界可为 0）。"""
        from gui.widgets.kb_worker import KbIndexWorker
        _patch_slow_index(monkeypatch, 0.4)
        w = KbIndexWorker("idx.json", ".")
        w.start()
        assert _pump_until(qapp, w.isRunning, 1.0)
        t0 = time.perf_counter()
        assert w.stop(wait_ms=0) is False          # 超时/不等待 → False
        assert (time.perf_counter() - t0) < 0.2
        assert w.stop() is True                    # 再给上界 → 收口成功


# ---------------------------------------------------------------------------
# ③ 退出收口后不再 emit / 解除挂接
# ---------------------------------------------------------------------------
class TestNoLateEmitAfterQuit:
    def test_no_emit_after_quit_and_hook_detached(self, qapp, monkeypatch):
        import helpers
        from gui.widgets.kb_worker import KbSearchWorker

        def slow(self, q, top_k=3, **k):
            time.sleep(0.5)
            return [("p", "c", 1.0)]

        monkeypatch.setattr(helpers.KnowledgeBase, "search", slow)
        seen = []
        w = KbSearchWorker("idx.json", "q")
        w.ok.connect(lambda payload: seen.append(payload))
        w.start()
        assert _pump_until(qapp, w.isRunning, 1.0)

        qapp.aboutToQuit.emit()
        assert not w.isRunning()
        _pump(qapp, 0.2)                           # 交付 run() 期间产生的合法信号
        n = len(seen)
        _pump(qapp, 0.4)                           # 再排空：收口后不得再有新增
        assert len(seen) == n, "退出收口后不得再 emit 到（将）销毁的对象"
        assert w._quit_app is None, "退出挂接应已解除（不泄漏连接）"

    def test_hook_removed_after_normal_finish(self, qapp, monkeypatch):
        from gui.widgets.kb_worker import KbIndexWorker
        _patch_slow_index(monkeypatch, 0.0)
        w = KbIndexWorker("idx.json", ".")
        w.start()
        assert _pump_until(qapp, lambda: not w.isRunning(), 2.0)
        _pump(qapp, 0.1)                           # 交付 queued finished → _on_finished
        assert w._quit_app is None, "自然结束应解除 aboutToQuit 挂接"


# ---------------------------------------------------------------------------
# ④ 子进程崩溃守卫：退出期销毁运行中 worker 的窗口 → 进程须干净退出
# ---------------------------------------------------------------------------
_CHILD_SRC = r'''
import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
from gui.qt_compat import QApplication
app = QApplication.instance() or QApplication([])
import helpers
def slow(self, directory, *a, **k):
    time.sleep(1.5)
    return "indexed"
helpers.KnowledgeBase.index_directory = slow
from gui.widgets.kb_dialog import KnowledgeBaseDialog
ctx = SimpleNamespace(cfg=SimpleNamespace(kb_index_file="kb_index_guard.json"),
                      config=None, theme_engine=None)
dlg = KnowledgeBaseDialog(ctx)
dlg.dir_edit.setText(".")
dlg._on_index()
w = dlg._worker
end = time.perf_counter() + 0.4
while time.perf_counter() < end:          # 热机：进入阻塞调用
    app.processEvents(); time.sleep(0.005)
if os.environ.get("KB_GUARD_NOFIX") == "1":
    w._disconnect_app_quit()              # 摘掉本次修复 → 复现修复前行为（受控正对照）
app.aboutToQuit.emit()                    # 真实停机序列（不触及 KB worker）
import shiboken6
shiboken6.delete(dlg)                     # 应用拆除时销毁窗口 ⇒ 连带销毁运行中的子 QThread
print("teardown-ok", flush=True)
'''


class TestQuitTeardownProcessGuard:
    def _run(self, nofix: bool):
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if nofix:
            env["KB_GUARD_NOFIX"] = "1"
        else:
            env.pop("KB_GUARD_NOFIX", None)
        return subprocess.run(
            [sys.executable, "-c", _CHILD_SRC], cwd=str(ROOT), env=env,
            capture_output=True, text=True, timeout=60,
        )

    def test_quit_teardown_exits_cleanly(self):
        """修复后：退出期销毁承载运行中 worker 的窗口 → rc=0，无 QThread 告警。"""
        proc = self._run(nofix=False)
        assert proc.returncode == 0, (
            f"退出期崩溃 rc={proc.returncode}（0xC0000409=3221226505）\n"
            f"stderr:\n{proc.stderr[-800:]}"
        )
        assert "QThread: Destroyed while thread is still running" not in (proc.stderr or "")
        assert "teardown-ok" in (proc.stdout or "")

    @pytest.mark.skipif(sys.platform != "win32", reason="fail-fast 仅 Windows 复现")
    def test_positive_control_nofix_reproduces(self):
        """受控正对照：摘掉退出收口 → 同一代码版本复现 fail-fast（证明守卫有效）。"""
        proc = self._run(nofix=True)
        assert proc.returncode != 0, (
            "受控正对照应崩溃（若未崩溃，说明本守卫无法捕获回归）"
        )
