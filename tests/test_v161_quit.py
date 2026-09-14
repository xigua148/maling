# -*- coding: utf-8 -*-
"""v1.6.1 退出顺序加固测试（退出竞态 fail-fast 0xc0000409 加固）。

覆盖：
- _quit_stop_services 完整停机序列（顺序契约：先停事件源 QTimer/线程/音频，再动 UI 对象）
- 单步失败不阻断后续（每步 try/except 独立包裹）
- 幂等（托盘退出已停过一遍，aboutToQuit 再停无害）
- 组件缺失降级（属性不存在 / 方法不存在 → 静默跳过）
- 托盘退出路径 _on_quit（QUIT-tray → 组件停 → quit）与 QUIT-stop-* 日志轨迹
- aboutToQuit 信号接线（emit 真实信号触发停机序列）

全部使用记录型假组件 + SimpleNamespace ctx，无真实 worker/音频/写盘。
"""
import logging

import pytest

from gui.main import _quit_stop_services

QT_QPA = "offscreen"


@pytest.fixture
def qapp():
    """本地 QApplication fixture（不依赖 pytest-qt）。"""
    from gui.qt_compat import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 记录型假组件
# ---------------------------------------------------------------------------
class _Recorder:
    """按方法名记录调用顺序；fail=True 时抛错（测单步失败不阻断）。"""

    def __init__(self, order, name, fail=False, methods=("stop", "shutdown")):
        self._order = order
        self._name = name
        self._fail = fail
        for m in methods:
            setattr(self, m, self._make(m))

    def _make(self, meth):
        def _call(*args, **kwargs):
            self._order.append(f"{self._name}.{meth}")
            if self._fail:
                raise RuntimeError(f"{self._name} 停机失败（模拟）")
        return _call


class _FakeIcon:
    def __init__(self):
        self.hidden = False

    def hide(self):
        self.hidden = True


# ---------------------------------------------------------------------------
# _quit_stop_services：顺序 / 容错 / 幂等 / 缺失降级
# ---------------------------------------------------------------------------
class TestQuitStopServices:
    def _ctx(self, **overrides):
        from types import SimpleNamespace
        order = []
        ctx = SimpleNamespace(
            proactive_scheduler=_Recorder(order, "sched", methods=("stop",)),
            chat_service=_Recorder(order, "chat", methods=("shutdown",)),
            voice_conversation=_Recorder(order, "voice", methods=("shutdown", "stop")),
            tts=_Recorder(order, "tts", methods=("shutdown", "stop")),
            screen_watch=_Recorder(order, "screen", methods=("shutdown", "stop")),
        )
        for k, v in overrides.items():
            setattr(ctx, k, v)
        return ctx, order

    def test_stop_order_contract(self):
        """顺序契约：scheduler(QTimer) → chat(worker) → voice → tts → screen。"""
        ctx, order = self._ctx()
        _quit_stop_services(ctx)
        assert order == [
            "sched.stop", "chat.shutdown", "voice.shutdown",
            "tts.shutdown", "screen.shutdown",
        ], f"停机顺序不符契约: {order}"

    def test_step_failure_not_blocking(self):
        """单步抛错不阻断后续（每步独立 try/except）。"""
        from types import SimpleNamespace
        order = []
        ctx = SimpleNamespace(
            proactive_scheduler=_Recorder(order, "sched", fail=True, methods=("stop",)),
            chat_service=_Recorder(order, "chat", methods=("shutdown",)),
            voice_conversation=_Recorder(order, "voice", fail=True, methods=("shutdown",)),
            tts=_Recorder(order, "tts", methods=("shutdown",)),
            screen_watch=_Recorder(order, "screen", methods=("shutdown",)),
        )
        _quit_stop_services(ctx)  # 不应抛出
        # 失败步之后的步骤仍被执行
        assert "chat.shutdown" in order
        assert "tts.shutdown" in order
        assert "screen.shutdown" in order

    def test_idempotent(self):
        """托盘退出已停过一遍，aboutToQuit 再停无害（幂等）。"""
        ctx, order = self._ctx()
        _quit_stop_services(ctx)
        _quit_stop_services(ctx)
        assert order.count("sched.stop") == 2
        assert order.count("chat.shutdown") == 2

    def test_missing_components_ok(self):
        """组件属性缺失 → 全部静默跳过，不抛异常。"""
        from types import SimpleNamespace
        _quit_stop_services(SimpleNamespace())  # 空 ctx
        _quit_stop_services(SimpleNamespace(chat_service=None, tts=None))

    def test_method_missing_ok(self):
        """组件存在但缺 stop/shutdown 方法 → 静默跳过。"""
        from types import SimpleNamespace

        class _Bare:  # 无任何停机方法
            pass

        ctx, _ = self._ctx(proactive_scheduler=_Bare(), chat_service=_Bare())
        _quit_stop_services(ctx)

    def test_quit_stop_log_trail(self, caplog):
        """日志留 QUIT-stop-* 轨迹（延续 QUIT-* 命名惯例）。"""
        ctx, _ = self._ctx()
        with caplog.at_level(logging.INFO, logger="maid_coder.gui"):
            _quit_stop_services(ctx)
        msgs = " | ".join(r.getMessage() for r in caplog.records)
        for key in ("QUIT-stop-scheduler", "QUIT-stop-chat",
                    "QUIT-stop-voice", "QUIT-stop-tts", "QUIT-stop-screen"):
            assert key in msgs, f"日志缺 {key}: {msgs}"


# ---------------------------------------------------------------------------
# aboutToQuit 信号接线（真实信号 emit 触发）
# ---------------------------------------------------------------------------
class TestAboutToQuitWiring:
    def test_signal_emit_triggers_sequence(self, qapp):
        """aboutToQuit.emit() 应触发 _quit_stop_services 完整序列。"""
        from types import SimpleNamespace
        order = []
        ctx = SimpleNamespace(
            proactive_scheduler=_Recorder(order, "sched", methods=("stop",)),
            chat_service=_Recorder(order, "chat", methods=("shutdown",)),
            voice_conversation=_Recorder(order, "voice", methods=("shutdown",)),
            tts=_Recorder(order, "tts", methods=("shutdown",)),
            screen_watch=_Recorder(order, "screen", methods=("shutdown",)),
        )
        qapp.aboutToQuit.connect(lambda: _quit_stop_services(ctx))
        try:
            qapp.aboutToQuit.emit()
            assert order == [
                "sched.stop", "chat.shutdown", "voice.shutdown",
                "tts.shutdown", "screen.shutdown",
            ]
        finally:
            qapp.aboutToQuit.disconnect()


# ---------------------------------------------------------------------------
# 托盘退出路径：QUIT-tray → save_window_state → chat.shutdown → goodnight →
# icon.hide → 各组件停 → QApplication.quit
# ---------------------------------------------------------------------------
class TestTrayQuitPath:
    def _fake_tray(self, ctx):
        """跳过 __init__（菜单/图标接线），仅注入 _on_quit 所需状态。"""
        from gui.tray_manager import TrayManager
        tray = TrayManager.__new__(TrayManager)
        tray.app_ctx = ctx
        tray._icon = _FakeIcon()
        return tray

    def test_tray_quit_stops_components(self, qapp):
        from types import SimpleNamespace
        order = []
        ctx = SimpleNamespace(
            quitting=False,
            main_window=None,
            proactive_scheduler=_Recorder(order, "sched", methods=("stop",)),
            idle_monitor=_Recorder(order, "idle", methods=("stop",)),
            hotkeys=_Recorder(order, "hotkeys", methods=("shutdown",)),
            tts=_Recorder(order, "tts", methods=("shutdown",)),
            chat_service=_Recorder(order, "chat", methods=("shutdown",)),
        )
        tray = self._fake_tray(ctx)
        tray._on_quit()  # QApplication.quit() 无 exec 时无副作用
        assert ctx.quitting is True
        assert tray._icon.hidden is True
        assert "chat.shutdown" in order
        for name in ("sched.stop", "idle.stop", "hotkeys.shutdown", "tts.shutdown"):
            assert name in order, f"托盘退出未停 {name}: {order}"

    def test_tray_quit_partial_missing_ok(self, qapp):
        """部分组件缺失 → 不抛异常，仍走完退出。"""
        from types import SimpleNamespace
        order = []
        ctx = SimpleNamespace(
            quitting=False,
            main_window=None,
            proactive_scheduler=_Recorder(order, "sched", methods=("stop",)),
            chat_service=_Recorder(order, "chat", methods=("shutdown",)),
        )
        tray = self._fake_tray(ctx)
        tray._icon = None  # 图标未建也不崩
        tray._on_quit()
        assert ctx.quitting is True
        assert "chat.shutdown" in order
