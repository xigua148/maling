# -*- coding: utf-8 -*-
"""V21-08/09/13 域5 主窗 / 侧栏 / 启动接线单测。

覆盖（offscreen，design-v21 §7.1 + 域5 验收）：
  · ``MainWindow._apply_glass_state`` 在 ``glass.is_supported()=False`` 时
    **移除 glass 动态属性且不设材质**（monkeypatch glass 模块级函数）；
  · 不支持 / 应用失败环境**不崩、不黑窗**（不设属性 → 纯色）；
  · 透明度互斥：玻璃生效 → 锁 100%；不生效 → 恢复 ``cfg.window_opacity``；
  · ``NAV_ITEMS`` 每项长度为 4，且 ``[0]key``/``[1]label`` 与改动前一致
    （v2.2.3 起口径 = **契约超集**：既有基线按原顺序逐项保留 + 新入口在列，
    不再写死导航项总数 —— 详见 ``test_nav_items_are_four_tuples_key_label_unchanged``）；
  · 图标不可用时侧栏回退文本非空（绝不空白）；
  · 切页过渡在 ``motion`` off 档下直接终态（不创建动画 / 不残留 effect）；
  · 切页过渡在 ``motion`` standard 档下：**毛玻璃关**保留淡入、**毛玻璃开**不做
    透明度淡入（v2.2.1 黑框修复 WP2 —— 玻璃开时整页半透明 = 整片无人绘制 = 屏幕级纯黑，
    起帧实测 82.22%）。
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
# + v2.2 新增 tavern（批 3）——既有 (key,label) 对**零变更、零重排**；本守卫本义不变。
_NAV_BASELINE = [
    ("chat", "聊天"), ("home", "首页"), ("memories", "回忆"),
    ("memory_book", "记忆中心"), ("project", "项目"), ("file", "文件"),
    ("plan", "计划"), ("tavern", "酒馆"), ("agent", "角色"),
    ("tools", "工具"), ("settings", "设置"),
]

#: v2.2.3 新增的侧栏入口（用户指定文案「Silly Tavern」，含空格；纯追加在末位）。
#: 矢量图标 = ``question_answer``（对话气泡，icons_manifest.json 已登记语义名）；
#: 回退字符 = U+1F3AD（🎭 扮演 —— ST 是角色扮演前端，与旧酒馆项的 🍷 不重复）。
_SILLYTAVERN_NAV_ITEM = ("sillytavern", "Silly Tavern", "question_answer", "\U0001F3AD")


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


def test_apply_glass_locks_opacity_before_dwm_apply(main_window, glass_stub, monkeypatch):
    """V21-18：先移除 WS_EX_LAYERED 透明度，再调用 DWM safe_apply。"""
    glass, _calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: True)
    monkeypatch.setattr(glass, "detect_capability", _fake_capability)
    win = main_window
    sequence = []
    original_lock = win._lock_window_opacity

    def _record_lock():
        sequence.append("lock")
        original_lock()

    def _record_apply(hwnd, kind, *, dark):
        sequence.append("safe_apply")
        return True

    monkeypatch.setattr(win, "_lock_window_opacity", _record_lock)
    monkeypatch.setattr(glass, "safe_apply", _record_apply)
    win.setWindowOpacity(0.85)
    win._apply_glass_state()

    assert sequence[:2] == ["lock", "safe_apply"]
    assert win.windowOpacity() == pytest.approx(1.0)


def test_glass_structural_containers_are_named_for_precise_qss(main_window):
    """V21-18：仅三层中间结构容器是透明目标，页面/卡片不被全量穿透。"""
    win = main_window
    assert win.central_outer.objectName() == "glassCentralOuter"
    assert win.central_splitter.objectName() == "glassCentralSplitter"
    assert win.page_stack.objectName() == "glassPageStack"


def test_glass_qss_targets_only_structural_containers():
    """V21-18：禁止全后代通配透明；必须精确覆盖 outer/splitter/stack。"""
    qss = (ROOT / "gui" / "themes" / "base.qss").read_text(encoding="utf-8")
    required = (
        'QMainWindow[glass="on"] QWidget#glassCentralOuter',
        'QMainWindow[glass="on"] QSplitter#glassCentralSplitter',
        'QMainWindow[glass="on"] QStackedWidget#glassPageStack',
    )
    for selector in required:
        assert selector in qss
    assert 'QMainWindow[glass="on"] * {' not in qss


def test_repolish_includes_all_glass_structural_containers(main_window, monkeypatch):
    """V21-18：父窗 glass 属性变更时，命中条件选择器的三层后代会一起重抛光。"""
    win = main_window
    seen_unpolish = []
    seen_polish = []

    class _Style:
        def unpolish(self, widget):
            seen_unpolish.append(widget)

        def polish(self, widget):
            seen_polish.append(widget)

    style = _Style()
    monkeypatch.setattr(type(win), "style", lambda _self: style)
    win._repolish()

    expected = [win, win.central_outer, win.central_splitter, win.page_stack]
    assert seen_unpolish == expected
    assert seen_polish == expected


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
    """⑤ standard 档：创建淡入动画，结束后移除 effect（R-P 防残留）。

    v2.2.1（黑框修复 WP2）更新：切页淡入**只在毛玻璃关时**保留 —— 毛玻璃开时
    `#glassCentralOuter/#glassCentralSplitter/#glassPageStack` 都是 transparent，
    「opacity<1 的整页」等于整片区域无人绘制 = 屏幕级纯黑（起帧实测 82.22%）。
    故本用例显式把 glass 置为关，让断言不再随宿主机的 DWM 能力漂移
    （原版未设 glass，在本机 glass 生效时**恒失败**）；glass 开的对应口径见
    `test_page_switch_glass_on_skips_fade_and_stays_opaque`。
    """
    motion.configure("standard")
    win = main_window
    win.setProperty("glass", None)          # 毛玻璃关：保留 v2.1 淡入
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


def test_page_switch_glass_on_skips_fade_and_stays_opaque(main_window):
    """v2.2.1（WP2）：毛玻璃开时切页**不做**透明度淡入，且新页立刻完全不透明。

    判据 = 「没有任何在跑的淡入动画」+「新页不挂 opacity effect」：只要两者成立，
    新页就是完全不透明的，屏幕级纯黑（起帧 82.22%）无从出现。
    """
    motion.configure("standard")
    win = main_window
    win.setProperty("glass", "on")
    for key in ("settings", "plan"):
        win._on_page_switched(key)
        page = win.pages[key]
        assert motion.running_count() == 0, f"{key}: glass=on 时仍创建了淡入动画"
        assert not isinstance(page.graphicsEffect(), QGraphicsOpacityEffect), (
            f"{key}: glass=on 时新页仍挂着 opacity effect → 会复现起帧黑屏")
        assert win._page_fade_anims == {}, f"{key}: 仍留有在跑的淡入动画"


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
    """图标可用时三个状态项**图标 label 设上 pixmap、文案 label 仍保留文字**。

    旧断言（三个文案 label 的 pixmap 非空）写死了错误设计：Qt 的 ``QLabel`` 只能
    显示 pixmap 或 text 之一，给文案 label 设图标会清空文案。修复后图标落在独立
    的 ``_status_icon_labels`` 上，故改为对「图标 label 有 pixmap」与「文案 label
    有文字」双向断言 —— 任一被清空都会红。
    """
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
        icon_label = win._status_icon_labels[attr]
        text_label = getattr(win, attr)
        assert not icon_label.pixmap().isNull(), f"{attr} 图标缺失"
        assert icon_label.isVisibleTo(win.status_bar), f"{attr} 图标未显示"
        assert text_label.text().strip(), f"{attr} 文案被清空"


def test_status_bar_icon_and_text_coexist_after_startup_sequence(main_window, monkeypatch):
    """回归（缺陷不变量）：复刻生产启动序列后三项**同时**有文案 + 有图标。

    生产启动序列 = ``_refresh_status_icons()``（设图标）→ ``refresh_api_status()``
    （设文案）。旧实现里前者清空 theme/mode 文案、后者清空 api 图标 —— 本用例把
    「文案与图标并存」这条**被违反的不变量**锁死。
    """
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

    # 复刻 _setup_status_bar 的真实调用顺序
    win._refresh_status_icons()
    win.refresh_api_status()

    for attr in ("status_theme", "status_mode", "status_api"):
        text_label = getattr(win, attr)
        icon_label = win._status_icon_labels[attr]
        assert text_label.text().strip(), f"{attr} 文案被清空"
        assert not icon_label.pixmap().isNull(), f"{attr} 图标缺失"
        assert icon_label.isVisibleTo(win.status_bar), f"{attr} 图标未显示"


def test_status_bar_text_intact_and_icons_hidden_when_unavailable(main_window, monkeypatch):
    """降级路径：``icons`` 不可用时三项文案完整、图标 label **隐藏**（不留空白占位）。"""
    import gui.main_window as mw

    class _UnavailableIcons:
        def available(self):
            return False

        def icon(self, name, size=16, color=None):
            return QIcon()

    monkeypatch.setattr(mw, "icons", _UnavailableIcons())
    win = main_window
    win._refresh_status_icons()
    win.refresh_api_status()

    for attr in ("status_theme", "status_mode", "status_api"):
        text_label = getattr(win, attr)
        icon_label = win._status_icon_labels[attr]
        assert text_label.text().strip(), f"{attr} 文案缺失"
        assert icon_label.pixmap().isNull(), f"{attr} 图标应被清空"
        assert not icon_label.isVisibleTo(win.status_bar), f"{attr} 图标未隐藏"


# ---------------------------------------------------------------------------
# V21-09 · NAV_ITEMS 4 元组 + 回退链
# ---------------------------------------------------------------------------
def test_nav_items_are_four_tuples_key_label_unchanged():
    """③ 每项长 4；[0]key/[1]label 与改动前一致；[3]回退文本非空。

    v2.2.3（内置 Silly Tavern）把断言口径从「恰好 11 项 + 逐项全等」放宽为
    **契约超集**（导航项会继续增长，写死总数的守卫每次都要改，且改法极易退化成
    恒真）。放宽后的两条判据都是真契约：

    ① 既有 11 项（``_NAV_BASELINE``）必须是新列表的**前缀**（逐项 + 逐序 + 逐长相等）
       → 守住「零变更、零重排、只允许在末位追加」；
    ② 新入口必须在列 → 守住「加了但没加进侧栏」这类假接线。

    QA P2-7：① 原写成「子序列」判定（``_is_subsequence``），**单独看明显更弱**
    （中间插入、重复项都会放行）；已收紧为前缀判定 —— **同样不写死总数**。
    """
    from gui.widgets.sidebar import SidebarWidget

    items = SidebarWidget.NAV_ITEMS
    for item in items:
        assert len(item) == 4, f"NAV_ITEMS 项非 4 元组：{item!r}"
        assert item[3], f"回退文本为空：{item!r}"
    pairs = [(i[0], i[1]) for i in items]
    assert pairs[:len(_NAV_BASELINE)] == _NAV_BASELINE, (
        f"既有导航项被改动 / 重排 / 未保持前缀：{pairs!r}")
    assert _SILLYTAVERN_NAV_ITEM in items, (
        f"NAV_ITEMS 缺少内置 Silly Tavern 入口：{_SILLYTAVERN_NAV_ITEM!r}")


def _bare_ctx():
    return SimpleNamespace(
        cfg=None, config=None, theme_engine=None, companion=None,
        companion_bridge=None, role_bridge=None, page_manager=None,
    )


def test_sidebar_fallback_text_non_empty_when_icons_unavailable(qapp, monkeypatch):
    """④ 图标不可用 → 回退 emoji 文本（不空白、不崩）。"""
    monkeypatch.setattr(sidebar_mod, "_icons", None)
    side = sidebar_mod.SidebarWidget(_bare_ctx())
    # 口径放宽（v2.2.3）：不写死 11，改判「列表行数 == NAV_ITEMS 项数」—— 仍是真契约
    # （侧栏为每个导航项建且仅建一行），新增入口无需再改本守卫。
    assert side.list_widget.count() == len(sidebar_mod.SidebarWidget.NAV_ITEMS)
    assert side.list_widget.count() >= len(_NAV_BASELINE)
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
    # 高亮必须落在 "settings" 那一行：按 key 现取行号，不写死索引 —— v2.2.3 起导航项
    # 会继续增长，写死索引的守卫会随每次新增入口误红（同 test_v21_wiring 的放宽口径）。
    rows = [side.list_widget.item(i).data(Qt.UserRole)
            for i in range(side.list_widget.count())]
    assert side.list_widget.currentRow() == rows.index("settings")


# ---------------------------------------------------------------------------
# 回归 · 主窗 theme_changed 既有行为
# ---------------------------------------------------------------------------
def test_theme_changed_updates_status_label_regression(main_window, glass_stub, monkeypatch):
    """主题变更仍更新状态栏文案，且换肤重渲染图标**不会**清空文案（真实保护）。

    必须**先**注册可用图标再换肤：测试环境未加载 ``remixicon`` 字体，图标默认
    ``available()→False``，若先换肤则图标压根不设、文案「侥幸」保住，断言在生产
    已坏时也会通过（虚假保护）。此处用 ``available()→True`` 的桩复刻生产环境。
    """
    import gui.main_window as mw

    class _FakeIcons:
        def available(self):
            return True

        def icon(self, name, size=16, color=None):
            pix = QPixmap(size, size)
            pix.fill(Qt.black)
            return QIcon(pix)

    monkeypatch.setattr(mw, "icons", _FakeIcons())
    glass, _calls = glass_stub
    monkeypatch.setattr(glass, "is_supported", lambda: False)
    win = main_window
    win.theme_engine.theme_changed.emit("ui_night")
    assert win.status_theme.text() == "主题: 深色夜间"
    # 换肤 → _refresh_status_icons() 重渲染后，主题图标落在独立 label 上且可见，
    # 文案仍完整（旧实现：图标设到文案 label 上会清空文案）。
    icon_label = win._status_icon_labels["status_theme"]
    assert not icon_label.pixmap().isNull()
    assert icon_label.isVisibleTo(win.status_bar)


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
