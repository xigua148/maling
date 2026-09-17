# -*- coding: utf-8 -*-
"""v2.2.5 内置酒馆页新增能力单测：大屏模式 / 复制诊断 / 三段式进度 / **启动预热状态机**。

为什么单独一份：这四项里前三项是 UI 接线，第四项（预热）是**用户完全看不见的状态机**——
"预热只启后端不建视图""预热进行中用户进入要立刻建视图"这两条一旦写错，表现是
"点开酒馆是空页"或"白占一个渲染进程"，而单元测试之外几乎发现不了。

本文件自备 fake（不 import 别的测试模块），只替换 `_create_view` / `_make_url` 两个
既有接缝，其余走真实 `PageSillyTavern` 代码路径。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from gui.pages import page_sillytavern as st_mod
from gui.pages.page_sillytavern import (
    BOOT_STAGE_TMPL,
    COPY_DIAG_TEXT,
    OPEN_BROWSER_TEXT,
    PROGRESS_STAGES,
    STATE_IDLE,
    STATE_READY,
    STATE_STARTING,
    PageSillyTavern,
)
from gui.qt_compat import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _FakeBackend:
    """假 ST 后端（与 TavernBackend 的冻结签名一致；多一个 tail_output 供进度用）。"""

    def __init__(self, port: int = 8754, tail: str = "") -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        self.tail = tail
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False

    def start(self):
        self.start_calls += 1
        self.running = True
        return self.port, self.url

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def tail_output(self) -> str:
        return self.tail


class _FakeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.urls = []

    def setUrl(self, url) -> None:  # noqa: N802 - 对齐 Qt 命名
        self.urls.append(url.toString())


def _ctx(warmup: bool = True, config: bool = True):
    """最小 app_context；``config=False`` 模拟"取不到配置"（应按开启处理）。"""
    cfg = SimpleNamespace(tavern_warmup=warmup) if config else None
    return SimpleNamespace(cfg=None, config=cfg, theme_engine=None,
                           diagnostics_providers={})


def _patch_view(monkeypatch):
    monkeypatch.setattr(PageSillyTavern, "_create_view",
                        lambda self: _FakeView(self))
    monkeypatch.setattr(PageSillyTavern, "_make_url",
                        lambda self, u: SimpleNamespace(toString=lambda: u))


def _wait(page: PageSillyTavern, qapp, target: str, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if page.state() == target:
            return True
        time.sleep(0.01)
    return page.state() == target


class TestButtons:
    def test_all_three_buttons_start_hidden(self, qapp):
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        try:
            assert page.retry_btn.isHidden()
            assert page.copy_btn.isHidden()
            assert page.open_btn.isHidden()
            assert page.open_btn.text() == OPEN_BROWSER_TEXT
            assert page.copy_btn.text() == COPY_DIAG_TEXT
        finally:
            page.shutdown()

    def test_ready_shows_only_open_button(self, qapp, monkeypatch):
        monkeypatch.setattr(st_mod, "make_backend", lambda: _FakeBackend())
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        try:
            page.on_enter()
            assert _wait(page, qapp, STATE_READY)
            assert not page.open_btn.isHidden(), "就绪后应给出大屏模式入口"
            assert page.retry_btn.isHidden() and page.copy_btn.isHidden()
        finally:
            page.shutdown()

    def test_failure_shows_copy_button_with_full_text(self, qapp, monkeypatch):
        """失败态：界面文案是裁剪过的，但剪贴板里必须是**完整原文**。"""
        long_reason = "酒馆启动失败：" + "细节" * 400
        monkeypatch.setattr(st_mod, "make_backend", lambda: _FakeBackend())
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        try:
            page._show_failure(long_reason)
            qapp.processEvents()
            assert not page.copy_btn.isHidden(), "失败后应能一键复制诊断"
            assert page.open_btn.isHidden()
            assert len(page.status.text()) < len(long_reason), "界面文案应被裁剪"
            page._copy_diagnostics()
            assert QApplication.clipboard().text() == long_reason, "剪贴板必须是完整原文"
        finally:
            page.shutdown()

    def test_open_in_browser_uses_seam(self, qapp, monkeypatch):
        """大屏模式：走可替换接缝，测试不真的拉起系统浏览器。"""
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        opened = []
        try:
            page._base_url = "http://127.0.0.1:8754/"
            import PySide6.QtGui as qtgui
            monkeypatch.setattr(qtgui.QDesktopServices, "openUrl",
                                staticmethod(lambda url: opened.append(url.toString())))
            page._open_in_browser()
            assert opened == ["http://127.0.0.1:8754/"]
            # 没有 base_url 时不该崩、也不该开
            page._base_url = ""
            page._open_in_browser()
            assert len(opened) == 1
        finally:
            page.shutdown()


class TestCopyToastLifetime:
    """「已复制」提示的 1.5 秒复位**不得**在页面销毁后仍执行。

    背景（真实踩过）：最初写法是裸 ``QTimer.singleShot(1500, lambda: self.copy_btn...)``，
    页面若在 1.5 秒内销毁，回调会访问已释放的 C++ 对象并抛
    ``RuntimeError: Internal C++ object already deleted``。**最坑的是它不在本用例报错** ——
    异常被抛进 Qt 事件循环，最后由 pytest-qt 算到**别的**用例头上，定位成本极高。

    修法：给 ``singleShot`` 传 context（这里是按钮本身），控件销毁即不再执行。
    这条测试把"跨过复位窗口再销毁页面"固定下来。
    """

    def test_toast_reset_does_not_fire_after_widget_destroyed(self, qapp):
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        page._show_failure("任意失败原文")
        page._copy_diagnostics()
        page.shutdown()
        page.deleteLater()
        qapp.processEvents()
        deadline = time.time() + 1.9           # 跨过 1500ms 的复位窗口
        while time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        # 若回调被错误执行，异常会被 pytest-qt 捕获并把本用例判失败 —— 无需额外断言。


class TestProgress:
    def _page_with_tail(self, tail: str):
        backend = _FakeBackend(tail=tail)
        page = PageSillyTavern(_ctx(), "Silly Tavern")
        page._backend = backend
        page._state = STATE_STARTING
        return page, backend

    def test_stage_advances_as_milestones_appear(self, qapp):
        page, backend = self._page_with_tail("")
        try:
            page._last_stage = 0
            page._poll_progress()
            assert page.status.text() != BOOT_STAGE_TMPL.format(
                stage=PROGRESS_STAGES[0][0]), "无里程碑时不该显示阶段文案"

            backend.tail = "Node version: v22.22.2"
            page._poll_progress()
            assert PROGRESS_STAGES[0][0] in page.status.text()

            backend.tail += "\nContent file user.css copied to ..."
            page._poll_progress()
            assert PROGRESS_STAGES[1][0] in page.status.text()

            backend.tail += "\nSillyTavern is listening on IPv4: 127.0.0.1:8754"
            page._poll_progress()
            assert PROGRESS_STAGES[2][0] in page.status.text()
        finally:
            page._state = STATE_IDLE
            page.shutdown()

    def test_stage_never_goes_backwards(self, qapp):
        """里程碑行可能被环形缓冲挤掉 —— 阶段只能前进，不能倒退。"""
        page, backend = self._page_with_tail("Node version: v22.22.2\nwebpack compiled")
        try:
            page._last_stage = 0
            page._poll_progress()
            reached = page._last_stage
            assert reached >= 2
            backend.tail = "Node version: v22.22.2"      # 后段里程碑"消失"
            page._poll_progress()
            assert page._last_stage == reached, "阶段不应回退"
        finally:
            page._state = STATE_IDLE
            page.shutdown()

    def test_poll_stops_when_not_starting(self, qapp):
        page, _backend = self._page_with_tail("Node version: v22.22.2")
        try:
            page._state = STATE_READY
            page._start_progress_poll()
            assert page._progress_timer is not None
            page._poll_progress()
            assert page._progress_timer is None, "非启动态应自动停表"
        finally:
            page._state = STATE_IDLE
            page.shutdown()


class TestWarmup:
    def test_warmup_boots_backend_but_not_view(self, qapp, monkeypatch):
        """**核心契约**：预热只把 node 拉起来，不创建内嵌浏览器视图。"""
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(warmup=True), "Silly Tavern")
        try:
            page.warmup()
            assert _wait(page, qapp, STATE_READY), f"预热未就绪：{page.state()}"
            assert backend.start_calls == 1
            assert page._view is None, "预热阶段不该创建视图（会白占渲染进程）"
            assert page.open_btn.isHidden(), "用户没进来，不该显示就绪态按钮"
        finally:
            page.shutdown()

    def test_enter_after_warmup_materializes_view(self, qapp, monkeypatch):
        """预热就绪后用户进入：只补建视图，**不重复启动**后端。"""
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(warmup=True), "Silly Tavern")
        try:
            page.warmup()
            assert _wait(page, qapp, STATE_READY)
            page.on_enter()
            qapp.processEvents()
            assert isinstance(page._view, _FakeView), "进入时应补建视图"
            assert page._view.urls == [backend.url]
            assert backend.start_calls == 1, "不该再启一个 node"
            assert not page.open_btn.isHidden()
        finally:
            page.shutdown()

    def test_enter_during_warmup_materializes_on_ready(self, qapp, monkeypatch):
        """预热**进行中**用户进入：就绪时必须建视图，否则用户盯着空页。"""
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(warmup=True), "Silly Tavern")
        try:
            page.warmup()
            assert page.state() in (STATE_STARTING, STATE_READY)
            page.on_enter()                       # 用户此刻进来了
            assert _wait(page, qapp, STATE_READY)
            assert isinstance(page._view, _FakeView), "用户已在看，就绪时必须建视图"
            assert backend.start_calls == 1
        finally:
            page.shutdown()

    def test_warmup_respects_disabled_switch(self, qapp, monkeypatch):
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        page = PageSillyTavern(_ctx(warmup=False), "Silly Tavern")
        try:
            page.warmup()
            qapp.processEvents()
            assert backend.start_calls == 0, "开关关闭时不该预热"
            assert page.state() == STATE_IDLE
        finally:
            page.shutdown()

    def test_warmup_defaults_on_when_config_missing(self, qapp, monkeypatch):
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(config=False), "Silly Tavern")
        try:
            page.warmup()
            assert _wait(page, qapp, STATE_READY), "取不到配置时按开启处理"
            assert backend.start_calls == 1
        finally:
            page.shutdown()

    def test_warmup_is_noop_when_already_started(self, qapp, monkeypatch):
        backend = _FakeBackend()
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        page = PageSillyTavern(_ctx(warmup=True), "Silly Tavern")
        try:
            page.on_enter()
            assert _wait(page, qapp, STATE_READY)
            page.warmup()                          # 用户已经进来了，预热应无操作
            qapp.processEvents()
            assert backend.start_calls == 1
        finally:
            page.shutdown()

    def test_warmup_registers_diagnostics_provider(self, qapp, monkeypatch):
        """预热也要注册诊断段 —— 否则"没打开过酒馆"时导出的包会缺 ST 输出。"""
        backend = _FakeBackend(tail="Node version: v22.22.2")
        monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
        _patch_view(monkeypatch)
        ctx = _ctx(warmup=True)
        page = PageSillyTavern(ctx, "Silly Tavern")
        try:
            page.warmup()
            assert _wait(page, qapp, STATE_READY)
            assert "sillytavern_stdout" in ctx.diagnostics_providers
            dump = ctx.diagnostics_providers["sillytavern_stdout"]()
            assert "Node version" in dump and "state=ready" in dump
        finally:
            page.shutdown()
