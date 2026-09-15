# -*- coding: utf-8 -*-
"""毛玻璃下「页面根 / 侧栏主题底色未绘制」缺陷的回归守卫（v2.1.1 收口）。

缺陷（用户实机截图）：
  ``SidebarWidget`` 及全部页面类都是 Python 层 ``QWidget`` 子类，metaobject 与
  ``QWidget`` 不同 → Qt 样式表引擎**不会**自动置 ``Qt::WA_StyledBackground``
  （实测 ``QWidget()`` / ``QSplitter`` 自动为 True，Python 子类恒为 False）。
  属性缺失时 ``QWidget::paintEvent`` 不画 ``PE_Widget``，主题 QSS 的
  ``SidebarWidget { background-color: ${bg_card} }`` 与全局
  ``QWidget { background-color: ${bg} }`` **完全不生效**，控件区域保持未绘制。

为什么只在毛玻璃下暴露：
  玻璃关 → 未绘制区透出 MainWindow 自绘的 ``${bg}``（观感正常）；
  玻璃开 → base.qss §1 把 ``glassCentralOuter`` / ``glassCentralSplitter`` /
  ``glassPageStack`` 置 ``background: transparent``（D-V21-04），链路再无底色
  可透 → 真机呈全透明（截图工具落成 RGB 后即纯黑）。

实测读数（offscreen + show + grab，1200x800，主题 ui_minimal）：
  · 修复前：侧栏矩形（0,0,180x778）黑/透明占比 79.8%；另在聊天面板左缘
    x=344..363 有一条 20px 全高黑缝（``ChatPanelWidget`` 自身未绘制）。
  · 修复后：侧栏黑占比 0.0%，主色 #FFFFFF（= ``bg_card``）；黑缝消失。
  · 用户实机截图（1202x832 RGB）交叉验证：黑列区间恰为 x=1..180（=侧栏矩形）
    与 x=346..365（=上述黑缝），与 offscreen 复现位置一致。

修复：``MainWindow._ensure_page_backgrounds()`` 为侧栏 + 全部页面根补
``WA_StyledBackground``（仅补属性，不动 QSS / 配色 / 布局）。

二轮扩展（同族缺陷收口，2026-09-15）：
  · **候选集口径改为「侧栏 ∪ ``self.pages`` ∪ ``page_stack`` 的直接子级」**。
    只听 ``self.pages`` 会漏掉**晚入栈的页根** —— ``OnboardingDialog`` 由
    ``_check_first_run()`` 在 ``_setup_pages()`` 之后才 ``page_stack.addWidget()``
    （见 ``_show_onboarding``），它不在 ``self.pages`` 里。实测玻璃开时
    未绘制 7.18% / 6.87%（两次采样），补位后 0.00%（4 风格一致）。
  · ``HandsfreeBar`` / ``ScreenWatchBar`` 用**类名选择器**给自己写
    底色 + 1px 描边 + 圆角，同为 Python 的 ``QWidget`` 子类 → 三者整体不绘制。
    二者已各自在 ``__init__`` 置位；本文件补守卫。
  · **不改**：``AttachmentBar``（置位会引入色偏：父级白卡透出消失，
    ``#EEF6FA:63% + #FFFFFF:37%`` → ``#EEF6FA:100%``）、``MaidPet``（根因是
    ``QSplitter`` 收编子控件 + ``setFixedSize(64,64)``，属布局缺陷，另案）、
    ``SessionTabsBar / LoopIndicator / ThinkingIndicator / ToolTracePanel /
    MaidAvatar``（只被通用 ``QWidget{background-color:${bg}}`` 命中，声明值恰等于
    所在页底色，无缺陷）。
"""
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui.qt_compat import QApplication, QPoint, Qt

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]

# 判定「未绘制」的阈值：修复前 79.8% / 20px 全高黑缝；修复后 0.0%
_HOLE_RATIO_MAX = 0.01


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="module")
def glass_window(qapp):
    """构造真实 MainWindow（真实 ChatPanel）并强制玻璃生效；隔离用户配置目录。"""
    iso = tempfile.mkdtemp(prefix="maling_test_cfg_")
    saved_env = {}
    for key in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
        saved_env[key] = os.environ.get(key)
        os.environ[key] = iso

    import gui.glass as glass
    import gui.main_window as mw_mod
    from gui.app_context import AppContext
    from gui.config import GuiConfig

    originals = {}
    for name, fake in (
        ("is_supported", lambda: True),
        ("detect_capability", lambda: glass.GlassCapability(True, "mica", 22621, "test-stub")),
        ("safe_apply", lambda hwnd, kind, *, dark: True),
        ("remove", lambda hwnd: True),
    ):
        originals[name] = getattr(glass, name)
        setattr(glass, name, fake)

    try:
        ctx = AppContext()
        cfg = GuiConfig()
        cfg.first_run = False
        cfg.theme_name = "ui_minimal"
        cfg.theme_mode = "light"
        cfg.glass_enabled = True
        cfg.sidebar_visible = True
        cfg.window_opacity = 1.0
        ctx.config = cfg
        win = mw_mod.MainWindow(ctx)
        win.resize(1200, 800)
        win.show()
        for _ in range(6):
            qapp.processEvents()
        yield win
        try:
            win.close()
            win.deleteLater()
        except Exception:
            pass
        qapp.processEvents()
    finally:
        for name, fn in originals.items():
            setattr(glass, name, fn)
        for key, val in saved_env.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


# ---------------------------------------------------------------------------
# 前提守卫：QSS 规则必须仍在（否则下面「底色应被绘制」的断言会失去意义）
# ---------------------------------------------------------------------------
def test_sidebar_qss_rule_still_declares_background():
    qss = (ROOT / "gui" / "themes" / "ui_minimal.qss").read_text(encoding="utf-8")
    assert "SidebarWidget {" in qss
    assert "background-color: ${bg_card};" in qss


# ---------------------------------------------------------------------------
# ① 属性层：页面根 / 侧栏必须带 WA_StyledBackground
# ---------------------------------------------------------------------------
def _page_stack_children(win):
    """``page_stack`` 的直接子级 —— 守卫的权威候选集（含晚入栈页根）。"""
    stack = win.page_stack
    return [stack.widget(i) for i in range(stack.count())]


def test_page_roots_enable_styled_background(glass_window):
    win = glass_window
    assert win.property("glass") == "on", "前提失效：玻璃未生效，本用例无意义"
    assert win.sidebar.testAttribute(Qt.WA_StyledBackground), "侧栏未开启样式表底色"

    kids = _page_stack_children(win)
    # 口径守卫：候选集必须比 self.pages 更宽（否则晚入栈页根又会漏网）
    assert len(kids) >= len(win.pages), (
        f"page_stack 直接子级 {len(kids)} 少于 pages {len(win.pages)}，"
        "候选集口径判断失效")
    missing = [type(w).__name__ for w in kids
               if w is not None and not w.testAttribute(Qt.WA_StyledBackground)]
    assert not missing, f"以下 page_stack 直接子级未开启样式表底色：{missing}"


# ---------------------------------------------------------------------------
# ② 渲染层：侧栏矩形内不得出现「未绘制」像素（真回归守卫）
# ---------------------------------------------------------------------------
def _unpainted_ratio(win, widget):
    """控件矩形内「未绘制」像素占比：alpha=0（透明）或纯黑（RGB 截图下的表现）。"""
    pm = win.grab()
    img = pm.toImage()
    tl = widget.mapTo(win, QPoint(0, 0))
    geo = widget.geometry()
    hole = total = 0
    for y in range(max(0, tl.y()), min(tl.y() + geo.height(), pm.height()), 3):
        for x in range(max(0, tl.x()), min(tl.x() + geo.width(), pm.width()), 3):
            c = img.pixelColor(x, y)
            total += 1
            if c.alpha() == 0 or (c.red() == 0 and c.green() == 0 and c.blue() == 0):
                hole += 1
    return hole / max(1, total)


def _dominant_color(win, widget):
    from collections import Counter
    pm = win.grab()
    img = pm.toImage()
    tl = widget.mapTo(win, QPoint(0, 0))
    geo = widget.geometry()
    cnt = Counter()
    for y in range(max(0, tl.y()), min(tl.y() + geo.height(), pm.height()), 3):
        for x in range(max(0, tl.x()), min(tl.x() + geo.width(), pm.width()), 3):
            c = img.pixelColor(x, y)
            cnt["#%02X%02X%02X" % (c.red(), c.green(), c.blue())] += 1
    return cnt.most_common(1)[0][0]


def test_sidebar_background_is_painted_under_glass(glass_window):
    win = glass_window
    ratio = _unpainted_ratio(win, win.sidebar)
    assert ratio <= _HOLE_RATIO_MAX, (
        f"侧栏矩形未绘制占比 {ratio:.1%}（修复前实测 79.8%）—— 主题底色又被跳过绘制")
    # 底色应为当前主题的 bg_card（ui_minimal 浅色 = #FFFFFF），而不是透出的 ${bg}
    expected = win.theme_engine.get_color("bg_card", "#FFFFFF")
    assert _dominant_color(win, win.sidebar) == expected.upper()


def test_chat_panel_has_no_unpainted_seam_under_glass(glass_window):
    """聊天面板自身未绘制 → 会话列表与聊天区之间会出现 20px 全高黑缝。"""
    win = glass_window
    panel = win.pages["chat"]
    ratio = _unpainted_ratio(win, panel)
    assert ratio <= _HOLE_RATIO_MAX, (
        f"聊天主屏未绘制占比 {ratio:.1%}（修复前实测 1.6%，为 x=344..363 全高黑缝）")


def test_other_pages_have_no_unpainted_area_under_glass(glass_window):
    """除主屏外的重灾区页面（help/about/memories/memory_book/project）逐页核对。"""
    win = glass_window
    bad = {}
    for key in ("help", "about", "memories", "memory_book", "project"):
        page = win.pages[key]
        win.page_stack.setCurrentWidget(page)
        for _ in range(3):
            QApplication.processEvents()
        ratio = _unpainted_ratio(win, page)
        if ratio > _HOLE_RATIO_MAX:
            bad[key] = ratio
    win.page_stack.setCurrentWidget(win.pages["chat"])
    for _ in range(2):
        QApplication.processEvents()
    assert not bad, "以下页面在毛玻璃下存在未绘制区域：" + ", ".join(
        f"{k}={v:.1%}" for k, v in bad.items())


# ---------------------------------------------------------------------------
# ②a 晚入栈页根：OnboardingDialog（首次启动）—— 治类不治例的守卫
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def first_run_window(qapp, glass_window):
    """首次启动（``first_run=True``）的真实 MainWindow：onboarding 会晚入栈。"""
    import gui.main_window as mw_mod
    from gui.config import GuiConfig

    win = glass_window
    saved = {}
    cfg = win.app_ctx.config
    for key in ("first_run",):
        saved[key] = getattr(cfg, key, None)
    try:
        cfg.first_run = True
        # 复用同一 app_ctx 另建一窗：走完整 __init__（含 _check_first_run → 入栈）
        win2 = mw_mod.MainWindow(win.app_ctx)
        win2.resize(1200, 800)
        win2.show()
        for _ in range(8):
            qapp.processEvents()
        yield win2
        try:
            win2.close()
            win2.deleteLater()
        except Exception:
            pass
        qapp.processEvents()
    finally:
        cfg.first_run = saved["first_run"]


def test_late_added_page_root_is_covered(first_run_window):
    """``OnboardingDialog`` 不在 ``self.pages`` 里，必须靠 page_stack 子级口径覆盖。"""
    win = first_run_window
    assert win.property("glass") == "on", "前提失效：玻璃未生效，本用例无意义"

    ob = getattr(win, "onboarding", None)
    assert ob is not None, "前提失效：first_run=True 却没有 onboarding 页"
    assert ob in _page_stack_children(win), "onboarding 未入页面栈"
    assert ob not in set(win.pages.values()), (
        "onboarding 竟然在 self.pages 里 —— 本用例已无法证明「晚入栈漏网」被堵住")

    win.page_stack.setCurrentWidget(ob)
    for _ in range(4):
        QApplication.processEvents()

    # 先测渲染（撤掉修复时能直接给出百分比读数），最后再断言属性，诊断信息更可用
    ratio = _unpainted_ratio(win, ob)
    assert ratio <= _HOLE_RATIO_MAX, (
        f"onboarding 页未绘制占比 {ratio:.1%}（修复前实测 7.18%）—— 晚入栈页根又漏网")
    assert ob.testAttribute(Qt.WA_StyledBackground), "晚入栈页根未开启样式表底色"


# ---------------------------------------------------------------------------
# ②b 两个状态条：类名选择器自写「底色 + 1px 描边 + 圆角」三者整体不绘制
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def bars_host(qapp, glass_window):
    """把两个状态条挂进独立宿主窗口并强制显示（它们平时默认隐藏）。"""
    from gui.qt_compat import QWidget, QVBoxLayout
    from gui.widgets.handsfree_bar import HandsfreeBar
    from gui.widgets.screen_watch_bar import ScreenWatchBar

    host = QWidget()
    host.resize(1000, 200)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    # 复用已 load_theme 的 app_ctx（新建 AppContext 会让 theme_color 回落默认值）
    hb = HandsfreeBar(glass_window.app_ctx)
    sb = ScreenWatchBar(glass_window.app_ctx)
    hb.setVisible(True)
    sb.setVisible(True)
    lay.addWidget(hb)
    lay.addWidget(sb)
    host.show()
    for _ in range(6):
        qapp.processEvents()
    yield host, hb, sb
    try:
        host.close()
        host.deleteLater()
    except Exception:
        pass
    qapp.processEvents()


@pytest.mark.parametrize("key", ["handsfree", "watchbar"])
def test_status_bars_paint_own_background_and_border(bars_host, key):
    """底色/描边/圆角三者都要真正画出来，而不是透出宿主底色。"""
    host, hb, sb = bars_host
    bar = hb if key == "handsfree" else sb

    ratio = _unpainted_ratio(host, bar)
    assert ratio <= _HOLE_RATIO_MAX, f"{type(bar).__name__} 未绘制占比 {ratio:.1%}"

    engine = hb.app_ctx.theme_engine
    expected_bg = engine.get_color("surface_muted", "").upper()
    expected_border = engine.get_color("border", "").upper()
    assert expected_bg and expected_border, "前提失效：取不到 surface_muted / border 声明值"

    from collections import Counter
    img = host.grab().toImage()
    tl = bar.mapTo(host, QPoint(0, 0))
    geo = bar.rect()
    cnt = Counter()
    for y in range(max(0, tl.y()), min(tl.y() + geo.height(), img.height())):
        for x in range(max(0, tl.x()), min(tl.x() + geo.width(), img.width())):
            c = img.pixelColor(x, y)
            cnt["#%02X%02X%02X" % (c.red(), c.green(), c.blue())] += 1
    dominant = cnt.most_common(1)[0][0]
    assert dominant == expected_bg, (
        f"{type(bar).__name__} 主色 {dominant} ≠ 声明底色 {expected_bg}"
        "（说明仍在透出宿主/父级底色，自身底色未绘制）")
    # 1px 描边：矩形周长像素里应命中声明 border 色（圆角会少几个角像素，故只给 >0）
    assert cnt.get(expected_border, 0) > 0, (
        f"{type(bar).__name__} 未画出声明描边 {expected_border} —— border 被跳过绘制")
    assert bar.testAttribute(Qt.WA_StyledBackground), (
        f"{type(bar).__name__} 未开启样式表底色 —— 底色/描边/圆角会被整体跳过绘制")


# ---------------------------------------------------------------------------
# ③ 换肤 / 深浅切换 / 玻璃开关后仍保持（属性不被重新 polish 抹掉）
# ---------------------------------------------------------------------------
def test_background_attribute_survives_theme_and_glass_toggle(glass_window):
    win = glass_window
    engine = win.theme_engine
    try:
        engine.load_theme("ui_night")  # 深色主题
        for _ in range(4):
            QApplication.processEvents()
        assert win.sidebar.testAttribute(Qt.WA_StyledBackground)
        ratio = _unpainted_ratio(win, win.sidebar)
        assert ratio <= _HOLE_RATIO_MAX, f"换深色后侧栏未绘制占比 {ratio:.1%}"
        expected = engine.get_color("bg_card", "#1C1920")
        assert _dominant_color(win, win.sidebar) == expected.upper()

        win.app_ctx.config.glass_enabled = False
        win._apply_glass_state()
        QApplication.processEvents()
        assert win.property("glass") is None, "玻璃关应移除 glass 属性"
        assert _unpainted_ratio(win, win.sidebar) <= _HOLE_RATIO_MAX
    finally:
        win.app_ctx.config.glass_enabled = True
        engine.load_theme("ui_minimal")
        win._apply_glass_state()
        for _ in range(4):
            QApplication.processEvents()
    assert win.property("glass") == "on"
    assert _unpainted_ratio(win, win.sidebar) <= _HOLE_RATIO_MAX
