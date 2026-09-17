# -*- coding: utf-8 -*-
"""v2.2.3 内置 SillyTavern 页接线单测（``gui/pages/page_sillytavern.py``）。

覆盖（offscreen，方案 §7/§8/§9/§13）：
  1. 侧栏新增入口「Silly Tavern」——key/label 逐字正确、图标名已在 manifest 登记、
     **纯追加**（既有 11 项按原顺序逐项保留，v2.2 的 tavern 纯插入契约不受影响）；
  2. 页面构造是**惰性**的：``__init__`` 不起后端、不 import WebEngine（否则主窗构造
     就会拉起 ST 进程，每次开码铃白等 30~50 秒）；
  3. 首次 ``on_enter()`` 才启动：后台线程跑 ``backend.start()``，成功 → 建内嵌浏览器
     并加载 ``base_url``；失败 → **可读文案 + 重试按钮**，且退出码 ``3221226505``
     不外泄（转成「路径兼容问题」）；
  4. ``shutdown()`` 幂等：停线程 + 停 node 子进程，重复调用不重复停机；
  5. 主窗注册 + 退出链：``pages["sillytavern"]`` 存在、``closeEvent`` 会调页面 ``shutdown()``；
  6. 静态接线：``gui/main.py`` 在 ``QApplication`` 之前 import 一次 QtWebEngine；
     ``requirements_gui.txt`` 声明 ``PySide6-WebEngine``。

⚠ 本文件**不**真起 node、**不**真建 ``QWebEngineView``（用假后端 + 假视图接缝），
   故可在 offscreen / CI 环境稳定运行；真机启动验收见 ``_st_ui_report.md``。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QCloseEvent

import gui.motion as motion
import gui.pages.page_sillytavern as st_mod
import gui.widgets.sidebar as sidebar_mod
from gui.pages.page_sillytavern import (
    BOOT_TEXT,
    PATH_COMPAT_TEXT,
    STATE_FAILED,
    STATE_IDLE,
    STATE_READY,
    STATE_STARTING,
    PageSillyTavern,
)
from gui.qt_compat import QApplication, QWidget

ROOT = Path(__file__).resolve().parents[1]

#: 期望的侧栏入口（4 元组：key / label / icon_name / emoji 回退）。
_SILLYTAVERN_NAV_ITEM = ("sillytavern", "Silly Tavern", "question_answer", "\U0001F3AD")

#: v2.2.3 之前既有的 11 项 key（顺序冻结；本批只允许在其后**追加**）。
_BASELINE_KEYS = [
    "chat", "home", "memories", "memory_book", "project", "file",
    "plan", "tavern", "agent", "tools", "settings",
]


# ---------------------------------------------------------------------------
# fixtures / 工具
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_motion():
    """接线用例不关心过渡动画：动效置 off，收尾复位。"""
    motion.stop_all(final=True)
    motion.configure("off")
    yield
    motion.stop_all(final=True)
    motion.configure("standard")


class _FakeBackend:
    """假 ST 后端（接口与 ``TavernBackend`` 冻结签名一致）。"""

    def __init__(self, port: int = 8754, error: BaseException = None) -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}/"
        self.error = error
        self.start_calls = 0
        self.stop_calls = 0
        self.running = False

    def start(self):
        self.start_calls += 1
        if self.error is not None:
            raise self.error
        self.running = True
        return self.port, self.url

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False

    def is_running(self) -> bool:
        return self.running


class _FakeView(QWidget):
    """假内嵌浏览器（真 QWebEngineView 在 offscreen 下不稳定，且本文件只验证接线）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.urls = []

    def setUrl(self, url) -> None:  # noqa: N802 - 对齐 Qt 命名
        self.urls.append(url.toString())


def _bare_ctx():
    return SimpleNamespace(cfg=None, config=None, theme_engine=None)


def _wait_state(page: PageSillyTavern, qapp, target: str, timeout: float = 10.0) -> bool:
    """跑事件循环直到 ``page.state() == target``（真线程 + 真信号投递）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        qapp.processEvents()
        if page.state() == target:
            return True
        time.sleep(0.01)
    return page.state() == target


def _patch_view(monkeypatch) -> None:
    """把内嵌浏览器接缝换成假控件（不 import QtWebEngineWidgets）。"""
    monkeypatch.setattr(PageSillyTavern, "_create_view", lambda self: _FakeView(self))


# ---------------------------------------------------------------------------
# 1 · 侧栏入口（纯追加 + 图标已登记）
# ---------------------------------------------------------------------------
def test_sidebar_has_silly_tavern_entry_as_pure_appendix():
    """侧栏恰含「Silly Tavern」项，且既有 11 项按原顺序逐项保留（纯追加）。"""
    items = list(sidebar_mod.SidebarWidget.NAV_ITEMS)
    assert _SILLYTAVERN_NAV_ITEM in items, f"NAV_ITEMS 缺少该项：{_SILLYTAVERN_NAV_ITEM!r}"
    assert items[-1] == _SILLYTAVERN_NAV_ITEM, "新增入口应追加在末位（不动既有顺序）"

    keys = [item[0] for item in items]
    assert keys[:len(_BASELINE_KEYS)] == _BASELINE_KEYS, (
        f"既有导航项被改动 / 重排：{keys!r}")


def test_sidebar_entry_label_is_exact_user_string_and_icon_registered():
    """label 就是用户指定的字符串「Silly Tavern」（含空格，未译成中文）；图标名已登记。"""
    from gui import icons

    items = list(sidebar_mod.SidebarWidget.NAV_ITEMS)
    item = next(i for i in items if i[0] == "sillytavern")
    assert item[1] == "Silly Tavern", f"入口文案被改动：{item[1]!r}"
    assert item[2] == "question_answer" and icons.has("question_answer"), (
        "图标名必须是 icons_manifest.json 已登记的语义名")
    # 回退字符与旧「酒馆」项（🍷）不同 —— 图标字体不可用时两项仍可区分
    tavern = next(i for i in items if i[0] == "tavern")
    assert item[3] != tavern[3] and item[3]


# ---------------------------------------------------------------------------
# 2 · 惰性：构造不起后端
# ---------------------------------------------------------------------------
def test_construct_is_inert_until_enter(qapp, monkeypatch):
    """``__init__`` 只搭空壳：不创建后端、不起线程、状态 idle（否则主窗构造即起 ST）。"""
    def _boom():
        raise AssertionError("构造期不得创建 ST 后端（懒启动契约被破坏）")

    monkeypatch.setattr(st_mod, "make_backend", _boom)
    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        assert page.state() == STATE_IDLE
        assert page._backend is None and page._thread is None
        assert page.status.text() == BOOT_TEXT
        assert page.retry_btn.isHidden(), "未失败时不应显示重试按钮"
    finally:
        page.shutdown()


# ---------------------------------------------------------------------------
# 3 · 首次 on_enter 才启动（后台线程）
# ---------------------------------------------------------------------------
def test_first_enter_boots_in_background_and_loads_url(qapp, monkeypatch):
    """``on_enter()`` → 后台线程调 ``start()`` → 就绪后建视图并加载 base_url。"""
    backend = _FakeBackend(port=8754)
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
    _patch_view(monkeypatch)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        page.on_enter()
        # 启动中：状态提示在场、重试按钮不显示
        assert page.state() in (STATE_STARTING, STATE_READY)
        assert _wait_state(page, qapp, STATE_READY), f"未就绪：{page.state()}"
        assert backend.start_calls == 1
        assert isinstance(page._view, _FakeView)
        assert page._view.urls == [backend.url]
        assert page.status.isHidden(), "就绪后状态提示应隐藏"
        # 再次进入不应重复启动（幂等）
        page.on_enter()
        qapp.processEvents()
        assert backend.start_calls == 1
    finally:
        page.shutdown()


# ---------------------------------------------------------------------------
# 4 · 失败 → 可读文案 + 重试
# ---------------------------------------------------------------------------
def test_failure_hides_raw_exit_code_and_shows_retry(qapp, monkeypatch):
    """退出码 3221226505 不外泄：转成「路径兼容问题」可读文案 + 重试按钮。"""
    backend = _FakeBackend(error=RuntimeError("node exited with code 3221226505"))
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        page.on_enter()
        assert _wait_state(page, qapp, STATE_FAILED), f"未落到失败态：{page.state()}"
        text = page.status.text()
        assert text == PATH_COMPAT_TEXT
        assert "3221226505" not in text, "原始退出码不得直接丢给用户"
        assert not page.retry_btn.isHidden(), "失败后必须给「重试启动」"
    finally:
        page.shutdown()


def test_long_backend_diagnosis_is_clipped_in_status(qapp, monkeypatch):
    """超长后端诊断不撑爆状态区：截断 + 指向日志（完整原文进日志，界面留人话）。"""
    backend = _FakeBackend(error=RuntimeError(
        "SillyTavern 启动失败，子进程提前退出（退出码 0）。" + "x" * 5000))
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        page.on_enter()
        assert _wait_state(page, qapp, STATE_FAILED), f"未落到失败态：{page.state()}"
        text = page.status.text()
        assert text.startswith("酒馆启动失败：")
        assert text.endswith("（完整信息见日志）")
        assert len(text) <= 300 + len("…（完整信息见日志）")
    finally:
        page.shutdown()


def test_access_violation_codes_are_mapped_too(qapp, monkeypatch):
    """QA P2-1：``3221225477`` / ``0xC0000005``（ACCESS_VIOLATION）也必须映射为可读文案。

    该码的来源存疑（后端称会出现，QA 未复现），但**漏映射就是缺陷** —— 会把裸码丢给
    用户，违反本页「原始码不外泄」纪律，故作防御性覆盖。两种写法（十进制 / 十六进制、
    大小写）都要命中。
    """
    for raw in ("3221225477", "0xC0000005", "0xc0000005"):
        backend = _FakeBackend(error=RuntimeError(
            f"检测到 Node 进程异常终止（退出码 {raw} / 0xC0000005 ACCESS_VIOLATION）。"))
        monkeypatch.setattr(st_mod, "make_backend", lambda b=backend: b)

        page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
        try:
            page.on_enter()
            assert _wait_state(page, qapp, STATE_FAILED), f"未落到失败态：{page.state()}"
            text = page.status.text()
            assert text == PATH_COMPAT_TEXT, f"{raw!r} 未映射为可读文案：{text!r}"
            assert raw.lower() not in text.lower(), f"{raw!r} 仍出现在界面文案里"
        finally:
            page.shutdown()


def test_native_stack_trace_is_not_shown_to_user(qapp, monkeypatch):
    """QA P2-4：子进程 native stack trace / 地址行不得上屏（改为可读提示 + 指向日志）。"""
    raw = (
        "SillyTavern 启动失败，子进程提前退出（退出码 3）。\n"
        "----- Native stack trace -----\n"
        " 1: 0x00007ff6c1a2b3d4 node::Abort() [node.exe+0x1a2b3d4]\n"
        " 2: 0x00007ff6c1a2b5e6 node::Chdir(v8::FunctionCallbackInfo<v8::Value> const&)\n"
    )
    backend = _FakeBackend(error=RuntimeError(raw))
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        page.on_enter()
        assert _wait_state(page, qapp, STATE_FAILED), f"未落到失败态：{page.state()}"
        text = page.status.text()
        assert "stack trace" not in text.lower(), f"栈回溯头被展示：{text!r}"
        assert "0x0000" not in text.lower(), f"地址行被展示：{text!r}"
        assert text.startswith("酒馆启动失败：") and text.endswith("（完整信息见日志）"), text
        # 纯机器痕迹（头部无信息）→ 兜底可读文案
        assert st_mod.clip_status_text("----- Native stack trace -----\n 1: 0x00007ff6c1\n") \
            == st_mod.STACK_TRACE_TEXT
    finally:
        page.shutdown()


def test_retry_after_failure_recovers(qapp, monkeypatch):
    """重试：同一后端再启一次（环境修好后）→ 进入就绪态。

    重试复用同一个 ``TavernBackend`` 实例（方案 §7 骨架口径：失败后 ``_boot`` 再次
    ``backend.start()``，不重建后端对象）；故此处模拟「环境已修好」而非「换后端」。
    """
    backend = _FakeBackend(error=RuntimeError("boom"))
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
    _patch_view(monkeypatch)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    try:
        page.on_enter()
        assert _wait_state(page, qapp, STATE_FAILED)
        assert backend.start_calls == 1

        backend.error = None  # 环境修好
        page.retry()
        assert _wait_state(page, qapp, STATE_READY), f"重试未恢复：{page.state()}"
        assert backend.start_calls == 2, "重试应再启一次（不是原地假成功）"
        assert page.retry_btn.isHidden()
    finally:
        page.shutdown()


# ---------------------------------------------------------------------------
# 5 · shutdown 幂等（不留孤儿 node 进程的关键）
# ---------------------------------------------------------------------------
def test_shutdown_is_idempotent_and_stops_backend(qapp, monkeypatch):
    """``shutdown()`` 停后端且**只停一次**；重复调用不抛、不重复停机。"""
    backend = _FakeBackend()
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)
    _patch_view(monkeypatch)

    page = PageSillyTavern(_bare_ctx(), "Silly Tavern")
    page.on_enter()
    assert _wait_state(page, qapp, STATE_READY)

    page.shutdown()
    page.shutdown()
    assert backend.stop_calls == 1, "重复 shutdown 不得重复停机"
    assert backend.running is False
    assert page.state() == STATE_IDLE


# ---------------------------------------------------------------------------
# 6 · 主窗注册 + 退出链
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def main_window(qapp, tmp_path_factory):
    """构造一次主窗（含页面栈 / 侧栏 / 新页）。

    ``ChatPanelWidget``（域 6 独占）以轻量桩替换（沿用 ``test_v22_wiring.py`` 手法）；
    ``PageTavern`` 的存档目录改指 pytest 临时目录，避免污染真实用户存档。
    """
    import gui.main_window as mw_mod
    import gui.pages.page_tavern as page_tavern_mod
    from gui.app_context import AppContext
    from gui.config import GuiConfig

    class _StubChatPanel(QWidget):
        def __init__(self, app_ctx, parent=None):
            super().__init__(parent)
            self.app_ctx = app_ctx

    sandbox = tmp_path_factory.mktemp("st_wiring_sandbox")
    real_service = page_tavern_mod.TavernService
    mp = pytest.MonkeyPatch()
    mp.setattr(mw_mod, "ChatPanelWidget", _StubChatPanel)

    def _factory(app_ctx, *args, **kwargs):
        kwargs["base_dir"] = sandbox
        return real_service(app_ctx, *args, **kwargs)

    mp.setattr(page_tavern_mod, "TavernService", _factory)
    try:
        ctx = AppContext()
        ctx.config = GuiConfig()
        ctx.config.first_run = False  # 跳过首次引导弹层
        win = mw_mod.MainWindow(ctx)
    finally:
        mp.undo()
    # 收尾清理（conftest 的 _qt_widget_cleanup 会 close 本窗 → closeEvent → 保存窗口几何）
    # 会把**真实** GUI 配置改写掉；本文件不验证持久化，故置空该保存点（零副作用）。
    win.save_window_state = lambda: None
    yield win
    try:
        win.shutdown_sillytavern()
        win.deleteLater()
    except Exception:
        pass


def test_main_window_registers_page_under_sillytavern_key(main_window, qapp, monkeypatch):
    """主窗注册 key=``sillytavern``、标题=``Silly Tavern``，且导航可达该页。

    导航会触发页面的**懒启动**（``on_enter`` → ``boot``）—— 这里注入假后端，
    确保用例**绝不真起 node**；同时这正是「进入页面即启动」契约的实测点。
    """
    win = main_window
    page = win.pages["sillytavern"]
    assert isinstance(page, PageSillyTavern), f"页面类型异常：{type(page).__name__}"
    assert page.title == "Silly Tavern"

    backend = _FakeBackend(error=RuntimeError("test stub：不真起 node"))
    monkeypatch.setattr(st_mod, "make_backend", lambda: backend)

    pm = win.page_manager
    pm.navigate("sillytavern")
    assert pm.current_page_key() == "sillytavern"
    assert pm._stack.currentWidget() is page
    assert _wait_state(page, qapp, STATE_FAILED), f"未落到失败态：{page.state()}"
    # 启动发生在后台线程：计数须等状态落定后再读（thread.start() 立即返回）
    assert backend.start_calls == 1, "进入本页应触发一次后端启动（懒启动）"


def test_close_event_shuts_down_sillytavern(main_window, monkeypatch):
    """``MainWindow.closeEvent``（真退出路径）必须调页面 ``shutdown()``（防孤儿 node）。"""
    win = main_window
    page = win.pages["sillytavern"]
    calls = []
    monkeypatch.setattr(page, "shutdown", lambda: calls.append("page"))
    monkeypatch.setattr(win, "save_window_state", lambda: None)  # 不写真实配置

    win.closeEvent(QCloseEvent())
    assert calls == ["page"], "closeEvent 未收口内置 SillyTavern 页"


# ---------------------------------------------------------------------------
# 7 · 静态接线（启动顺序 + 依赖声明）
# ---------------------------------------------------------------------------
def test_main_py_imports_qtwebengine_before_qapplication():
    """方案 §13：``gui/main.py`` 必须在 ``QApplication`` 之前 import 一次 QtWebEngine。"""
    src = (ROOT / "gui" / "main.py").read_text(encoding="utf-8")
    idx_engine = src.index("PySide6.QtWebEngineWidgets")
    idx_app = src.index("app = QApplication(sys.argv)")
    assert idx_engine < idx_app, "QtWebEngine 必须早于 QApplication 创建（否则可能白屏）"


def test_requirements_declares_webengine_aligned_with_pyside6():
    """``requirements_gui.txt`` 声明 ``PySide6-WebEngine>=6.5``（与 PySide6 对齐）。"""
    text = (ROOT / "requirements_gui.txt").read_text(encoding="utf-8")
    assert "PySide6>=6.5" in text
    assert "PySide6-WebEngine>=6.5" in text, "缺少 PySide6-WebEngine 依赖声明"
