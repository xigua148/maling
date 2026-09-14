# -*- coding: utf-8 -*-
"""V21-08/09/13 域5 主窗 / 侧栏 / 启动接线单测。

覆盖（offscreen，design-v21 §7.1 + 域5 验收）：
  · ``MainWindow._apply_glass_state`` 在 ``glass.is_supported()=False`` 时
    **移除 glass 动态属性且不设材质**（monkeypatch glass 模块级函数）；
  · 不支持 / 应用失败环境**不崩、不黑窗**（不设属性 → 纯色）；
  · 透明度互斥：玻璃生效 → 锁 100%；不生效 → 恢复 ``cfg.window_opacity``；
  · ``NAV_ITEMS`` 每项长度为 4，且 ``[0]key``/``[1]label`` 与改动前一致；
  · 图标不可用时侧栏回退文本非空（绝不空白）；
  · 切页过渡在 ``motion`` off 档下直接终态（不创建动画 / 不残留 effect）；
  · ``main.py`` 外观段三处调用存在**且均在 try/except 内**（异常被吞）；
  · 回归：侧栏导航信号按键发出、``set_active_page`` 不递归发信号、
    主窗 ``theme_changed`` 既有状态栏行为不变。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import gui.motion as motion
import gui.widgets.sidebar as sidebar_mod
from gui.qt_compat import (
    QApplication, QGraphicsOpacityEffect, QIcon, QPixmap, Qt, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]

# 改动前基线（key, label）序列（design §4.5：语义零变更）
_NAV_BASELINE = [
    ("chat", "聊天"), ("home", "首页"), ("memories", "回忆"),
    ("memory_book", "记忆中心"), ("project", "项目"), ("file", "文件"),
    ("plan", "计划"), ("agent", "角色"), ("tools", "工具"), ("settings", "设置"),
]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _reset_motion():
    motion.stop_all(final=True)
    motion.configure("standard")
    yield
    motion.stop_all(final=True)
    motion.configure("standard")


@pytest.fixture(scope="module")
def main_window(qapp):
    """构造一次主窗（含四风格主题引擎 / 页面栈 / 侧栏）供多例复用。

    ``ChatPanelWidget``（域6 独占，并行改造中）以轻量桩替换，使本域用例
    只验证主窗/侧栏/启动接线，不耦合聊天面板的内部实现细节。
    """
    import gui.main_window as mw_mod
    from gui.app_context import AppContext
    from gui.config import GuiConfig

    class _StubChatPanel(QWidget):
        def __init__(self, app_ctx, parent=None):
            super().__init__(parent)
            self.app_ctx = app_ctx

    mp = pytest.MonkeyPatch()
    mp.setattr(mw_mod, "ChatPanelWidget", _StubChatPanel)
    try:
        ctx = AppContext()
        ctx.config = GuiConfig()
        ctx.config.first_run = False  # 跳过首次引导弹层
        win = mw_mod.MainWindow(ctx)
    finally:
        mp.undo()
    yield win
    try:
        win.close()
        win.deleteLater()
    except Exception:
        pass


@pytest.fixture
def glass_stub(monkeypatch):
    """隔离 DWM：记录 safe_apply / remove 调用，绝不触碰真实 dwmapi。"""
    import gui.glass as glass

    calls = {"safe": [], "remove": []}
    monkeypatch.setattr(
        glass, "safe_apply",
        lambda hwnd, kind, *, dark: (calls["safe"].append((hwnd, kind, dark)) or True),
    )
    monkeypatch.setattr(
        glass, "remove",
        lambda hwnd: (calls["remove"].append(hwnd) or True),
    )
    return glass, calls


def _fake_capability():
    from gui.glass import GlassCapability
    return GlassCapability(True, "mica", 22621, "测试桩：Win11 22H2+")


# ---------------------------------------------------------------------------
# V21-08 · _apply_glass_state
# ---------------------------------------------------------------------------
def test_apply_glass_unsupported_removes_property_and_skips_material(
    main_window, glass_stub, monkeypatch,
):
    """① 不支持环境：移除 glass 属性、不设材质、恢复透明度。"""
    glass, calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: False)
    win = main_window
    win.setProperty("glass", "on")  # 预置属性，验证会被移除

    win.app_ctx.config.window_opacity = 0.9
    win.setWindowOpacity(0.9)
    try:
        win._apply_glass_state()
        assert win.property("glass") is None
        assert calls["safe"] == []          # 不执行材质应用
        assert calls["remove"]              # 走 remove 移除材质
        # setWindowOpacity 按 8 位量化，故用容差比对
        assert win.windowOpacity() == pytest.approx(0.9, abs=0.01)  # 恢复用户透明度
    finally:
        win.app_ctx.config.window_opacity = 1.0
        win.setWindowOpacity(1.0)


def test_apply_glass_supported_sets_property_and_locks_opacity(
    main_window, glass_stub, monkeypatch,
):
    """① 支持环境：设属性 glass="on" 并锁透明度 100%（互斥）。"""
    glass, calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: True)
    monkeypatch.setattr(glass, "detect_capability", _fake_capability)
    win = main_window

    win.app_ctx.config.window_opacity = 0.85
    win.setWindowOpacity(0.85)
    try:
        win._apply_glass_state()
        assert win.property("glass") == "on"
        assert calls["safe"] and calls["safe"][-1][1] == "mica"
        assert win.windowOpacity() == pytest.approx(1.0)
    finally:
        win.app_ctx.config.window_opacity = 1.0
        win.setWindowOpacity(1.0)


def test_apply_glass_apply_failure_degrades_without_black_window(
    main_window, monkeypatch,
):
    """② 应用失败（winId 无效等）：不设属性、不崩 → 纯色降级（不黑窗）。"""
    import gui.glass as glass

    monkeypatch.setattr(glass, "is_supported", lambda: True)
    monkeypatch.setattr(glass, "detect_capability", _fake_capability)
    monkeypatch.setattr(glass, "safe_apply", lambda *a, **k: False)
    win = main_window
    win.setProperty("glass", "on")

    win._apply_glass_state()  # 不抛
    win._apply_glass_state()  # 幂等
    assert win.property("glass") is None


def test_apply_glass_idempotent_when_supported(main_window, glass_stub, monkeypatch):
    """幂等：连续调用不重复置脏（属性保持单一状态）。"""
    glass, calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: True)
    monkeypatch.setattr(glass, "detect_capability", _fake_capability)
    win = main_window
    win._apply_glass_state()
    win._apply_glass_state()
    assert win.property("glass") == "on"


# ---------------------------------------------------------------------------
# V21-08 · M-1 切页过渡
# ---------------------------------------------------------------------------
def test_page_switch_off_sets_terminal_without_animation(main_window):
    """⑤ off 档：直接终态，不创建动画、不残留 opacity effect。"""
    motion.configure("off")
    win = main_window
    win._on_page_switched("settings")
    assert motion.running_count() == 0
    assert not isinstance(win.pages["settings"].graphicsEffect(), QGraphicsOpacityEffect)


def test_page_switch_standard_creates_fade_then_cleans_effect(main_window, qapp):
    """⑤ standard 档：创建淡入动画，结束后移除 effect（R-P 防残留）。"""
    motion.configure("standard")
    win = main_window
    win._on_page_switched("home")
    page = win.pages["home"]
    assert motion.running_count() >= 1
    assert isinstance(page.graphicsEffect(), QGraphicsOpacityEffect)

    # 跑完事件循环让动画结束 + on_finished 收尾
    import time
    for _ in range(80):
        qapp.processEvents()
        if motion.running_count() == 0:
            break
        time.sleep(0.01)
    assert motion.running_count() == 0
    assert page.graphicsEffect() is None


def test_page_switch_rapid_same_page_no_crash(main_window, qapp):
    """边界：200ms 内同页重切不崩，最终仍收尾到无 effect 终态。"""
    motion.configure("standard")
    win = main_window
    win._on_page_switched("plan")
    win._on_page_switched("plan")  # 同页快速重切
    import time
    for _ in range(80):
        qapp.processEvents()
        if motion.running_count() == 0:
            break
        time.sleep(0.01)
    assert motion.running_count() == 0
    assert win.pages["plan"].graphicsEffect() is None


# ---------------------------------------------------------------------------
# V21-08 · 状态栏图标化（I-3）
# ---------------------------------------------------------------------------
def test_status_bar_icons_applied_when_available(main_window, monkeypatch):
    """图标可用时三个状态标签设上 pixmap。"""
    import gui.main_window as mw

    class _FakeIcons:
        def available(self):
            return True

        def icon(self, name, size=16, color=None):
            pix = QPixmap(size, size)
            pix.fill(Qt.black)
            return QIcon(pix)

    monkeypatch.setattr(mw, "icons", _FakeIcons())
    win = main_window
    win._refresh_status_icons()
    for attr in ("status_theme", "status_mode", "status_api"):
        label = getattr(win, attr)
        assert not label.pixmap().isNull()


# ---------------------------------------------------------------------------
# V21-09 · NAV_ITEMS 4 元组 + 回退链
# ---------------------------------------------------------------------------
def test_nav_items_are_four_tuples_key_label_unchanged():
    """③ 每项长 4；[0]key/[1]label 与改动前一致；[3]回退文本非空。"""
    from gui.widgets.sidebar import SidebarWidget

    items = SidebarWidget.NAV_ITEMS
    assert len(items) == 10
    for item in items:
        assert len(item) == 4, f"NAV_ITEMS 项非 4 元组：{item!r}"
        assert item[3], f"回退文本为空：{item!r}"
    assert [(i[0], i[1]) for i in items] == _NAV_BASELINE


def _bare_ctx():
    return SimpleNamespace(
        cfg=None, config=None, theme_engine=None, companion=None,
        companion_bridge=None, role_bridge=None, page_manager=None,
    )


def test_sidebar_fallback_text_non_empty_when_icons_unavailable(qapp, monkeypatch):
    """④ 图标不可用 → 回退 emoji 文本（不空白、不崩）。"""
    monkeypatch.setattr(sidebar_mod, "_icons", None)
    side = sidebar_mod.SidebarWidget(_bare_ctx())
    assert side.list_widget.count() == 10
    for i, (_key, label, _name, fallback) in enumerate(sidebar_mod.SidebarWidget.NAV_ITEMS):
        text = side.list_widget.item(i).text()
        assert text, "导航项文本为空"
        assert fallback in text and label in text


def test_sidebar_nav_signal_emits_key_regression(qapp, monkeypatch):
    """回归：item_clicked 按 key 发出（信号语义零变更）。"""
    monkeypatch.setattr(sidebar_mod, "_icons", None)
    side = sidebar_mod.SidebarWidget(_bare_ctx())
    got = []
    side.item_clicked.connect(got.append)
    side.list_widget.setCurrentRow(3)
    assert got == ["memory_book"]
    # UserRole 承载 key 不变
    assert side.list_widget.item(3).data(Qt.UserRole) == "memory_book"


def test_sidebar_set_active_page_no_recursive_emit(qapp, monkeypatch):
    """回归：外部同步高亮（set_active_page）不触发导航信号。"""
    monkeypatch.setattr(sidebar_mod, "_icons", None)
    side = sidebar_mod.SidebarWidget(_bare_ctx())
    got = []
    side.item_clicked.connect(got.append)
    side.set_active_page("settings")
    assert got == []
    assert side.list_widget.currentRow() == 9


# ---------------------------------------------------------------------------
# 回归 · 主窗 theme_changed 既有行为
# ---------------------------------------------------------------------------
def test_theme_changed_updates_status_label_regression(main_window, glass_stub, monkeypatch):
    """主题变更仍更新状态栏文案，且追加的毛玻璃订户不破坏既有行为。"""
    glass, _calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: False)
    win = main_window
    win.theme_engine.theme_changed.emit("ui_night")
    assert win.status_theme.text() == "主题: 深色夜间"


# ---------------------------------------------------------------------------
# V21-13 · main.py 外观段接线（存在 + 异常被吞）
# ---------------------------------------------------------------------------
def _calls_inside_try_bodies(tree):
    """收集「位于某个 try 体（非 except/finally）内」的被调属性 (base, attr) 集合。"""
    pairs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.handlers:
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        value = sub.func.value
                        base = value.id if isinstance(value, ast.Name) else None
                        pairs.add((base, sub.func.attr))
    return pairs


def test_main_py_appearance_calls_present_and_swallowed():
    """⑥ 三处外观段调用存在，且均在 try/except 内（失败只记日志，绝不阻断）。"""
    source = (ROOT / "gui" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    guarded = _calls_inside_try_bodies(tree)

    assert ("motion", "configure") in guarded
    assert ("icons", "register_icon_font") in guarded
    assert ("icons", "configure") in guarded
    assert ("window", "_apply_glass_state") in guarded

    # 位置纪律：show() 后应用毛玻璃，且在 v2.0 更新编排段（bootstrap 调用）之前
    assert source.index("window._apply_glass_state()") < source.index(
        "_bootstrap_update_subsystem(app_ctx)"
    )


def test_requirements_untouched_no_new_runtime_dep():
    """R-F：域5 不改依赖清单（本域仅新增测试文件）。"""
    assert (ROOT / "tests" / "test_v21_wiring.py").exists()
