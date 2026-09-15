"""v2.1 域8（V21-12）：记忆中心 + 其他页图标统一 / 深色复核测试。

覆盖（全部 offscreen）：
  ① 记忆中心 8 Tab 全部构造且图标位非空（图标字体可用时）；
  ② ``icons.available()`` 不可用 → 回落原 emoji 文本非空、不崩；
  ③ 各页（page_home/page_role/page_toolbox/page_plan/page_memories/page_help/
     page_memory_book）离屏构造不崩（图标可用 / 不可用两态）；
  ④ 图标取色一律走 ``theme_color``（spy 断言未硬编码色值）。

红线：本文件只做只读断言，不改任何业务数据；图标字体状态用 autouse fixture
事前/事后复位，绝不外泄到其它测试文件。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _icon_state():
    """本文件每个用例前后复位图标内核状态（防外泄 / 防被他文件影响）。"""
    from gui import icons
    icons._reset_state()
    yield
    icons._reset_state()
    try:
        icons.clear_cache()
    except Exception:
        pass


class _LiteCtx:
    """极简 ctx：无 theme_engine/companion → 取色走兜底；manager 显式注入。"""

    weekly = None
    session = None
    companion = None
    companion_bridge = None
    session_manager = None
    highlights = None
    diary = None


def _ctx(tmp_path):
    from highlights import HighlightsManager
    from weekly import WeeklyReviewManager
    ctx = _LiteCtx()
    ctx.highlights = HighlightsManager(filepath=str(tmp_path / "h.json"))
    ctx.weekly = WeeklyReviewManager(filepath=str(tmp_path / "w.json"))
    return ctx


def _enable_icons(monkeypatch, color_sink=None):
    """把图标内核替换为「始终可用」的确定性桩（不注册真实字体、零全局外泄）。"""
    from gui import icons
    from gui.qt_compat import QColor, QIcon, QPixmap

    def fake_icon(name, size=16, color=None):
        if color_sink is not None:
            color_sink.append(color)
        px = max(1, int(size))
        pm = QPixmap(px, px)
        pm.fill(QColor(color or "#000000"))
        return QIcon(pm)

    monkeypatch.setattr(icons, "available", lambda: True)
    monkeypatch.setattr(icons, "has", lambda name: True)
    monkeypatch.setattr(icons, "icon", fake_icon)


def _disable_icons(monkeypatch):
    from gui import icons
    monkeypatch.setattr(icons, "available", lambda: False)
    monkeypatch.setattr(icons, "has", lambda name: False)


# ---------------------------------------------------------------------------
# ① 记忆中心 8 Tab 图标位非空
# ---------------------------------------------------------------------------
def test_memory_book_8_tabs_have_icons(qapp, monkeypatch):
    _enable_icons(monkeypatch)
    from gui.pages.page_memory_book import PageMemoryBook
    page = PageMemoryBook(_ctx_stub())
    assert page.tabs.count() == 8
    for i in range(page.tabs.count()):
        assert not page.tabs.tabIcon(i).isNull(), f"Tab {i} 图标位为空"
        assert page.tabs.tabText(i).strip(), f"Tab {i} 文案为空"
    # 图标可用 → Tab 文案里的 emoji 已剥离
    joined = "".join(page.tabs.tabText(i) for i in range(page.tabs.count()))
    assert "📌" not in joined and "🌟" not in joined


def _ctx_stub():
    return SimpleNamespace(session=None, diary=None, weekly=None, highlights=None)


# ---------------------------------------------------------------------------
# ② 字体不可用 → 回落原 emoji，不空白、不崩
# ---------------------------------------------------------------------------
def test_memory_book_tabs_fallback_text_when_no_icons(qapp, monkeypatch):
    _disable_icons(monkeypatch)
    from gui.pages.page_memory_book import PageMemoryBook
    page = PageMemoryBook(_ctx_stub())
    assert page.tabs.count() == 8
    for i in range(page.tabs.count()):
        assert page.tabs.tabText(i).strip(), f"Tab {i} 回落后文案为空"
    assert page.tabs.tabText(4) == "回应约定 📌"
    assert page.tabs.tabText(5) == "共同经历 🌟"
    for i in range(page.tabs.count()):
        assert page.tabs.tabIcon(i).isNull()     # 无图标字体 → 不设图标（回落文本）


def test_memory_book_buttons_fallback_text_when_no_icons(qapp, monkeypatch):
    _disable_icons(monkeypatch)
    from gui.pages.page_memory_book import PageMemoryBook
    from gui.qt_compat import QPushButton
    page = PageMemoryBook(_ctx_stub())
    btn = page.pref_tab.findChild(QPushButton, "memoryBookBtn")
    assert btn is not None
    assert "添加偏好" in btn.text()              # 回落 emoji 文案非空
    assert btn.icon().isNull()


def test_memory_book_buttons_icon_and_clean_text_when_available(qapp, monkeypatch):
    _enable_icons(monkeypatch)
    from gui.pages.page_memory_book import PageMemoryBook
    from gui.qt_compat import QPushButton
    page = PageMemoryBook(_ctx_stub())
    btn = page.pref_tab.findChild(QPushButton, "memoryBookBtn")
    assert btn is not None
    assert btn.text() == "添加偏好"              # emoji 已剥离
    assert not btn.icon().isNull()


# ---------------------------------------------------------------------------
# ③ 各页离屏构造不崩（图标可用 / 不可用两态）
# ---------------------------------------------------------------------------
def _patch_storage_dirs(monkeypatch, tmp_path):
    import gui.pages.page_role as pr
    import gui.pages.page_plan as pp
    monkeypatch.setattr(pr, "DEFAULT_ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(pr, "ROLE_AVATARS_DIR", tmp_path / "roles" / "avatars")
    monkeypatch.setattr(pp, "DEFAULT_PLANS_DIR", tmp_path / "plans")


def _construct_all(tmp_path):
    from gui.pages.page_help import PageHelp
    from gui.pages.page_home import PageHome
    from gui.pages.page_memories import PageMemories
    from gui.pages.page_memory_book import PageMemoryBook
    from gui.pages.page_plan import PagePlan
    from gui.pages.page_role import PageRole
    from gui.pages.page_toolbox import PageToolbox
    ctx = _ctx(tmp_path)
    widgets = [
        PageHome(ctx), PageRole(ctx), PageToolbox(ctx), PagePlan(ctx),
        PageMemories(ctx), PageHelp(ctx), PageMemoryBook(ctx),
    ]
    for w in widgets:
        assert w is not None
    return widgets


def test_pages_construct_offscreen_no_icons(qapp, monkeypatch, tmp_path):
    _disable_icons(monkeypatch)
    _patch_storage_dirs(monkeypatch, tmp_path)
    _construct_all(tmp_path)


def test_pages_construct_offscreen_with_icons(qapp, monkeypatch, tmp_path):
    _enable_icons(monkeypatch)
    _patch_storage_dirs(monkeypatch, tmp_path)
    _construct_all(tmp_path)


# ---------------------------------------------------------------------------
# ④ 图标取色一律走 theme_color（未硬编码色值）
# ---------------------------------------------------------------------------
def test_icon_colors_come_from_theme_color(qapp, monkeypatch, tmp_path):
    palette = {
        "text": "#0a0a0a", "text_secondary": "#0e0e0e",
        "accent": "#0b0b0b", "info": "#0c0c0c", "warning": "#0d0d0d",
    }
    icon_colors = []
    _enable_icons(monkeypatch, color_sink=icon_colors)

    import gui.pages.page_memory_book as pmb
    seen_keys = []

    def spy_theme_color(app_ctx, key, fallback):
        seen_keys.append(key)
        return palette.get(key, fallback)

    monkeypatch.setattr(pmb, "theme_color", spy_theme_color)
    page = pmb.PageMemoryBook(_ctx_stub())
    page.refresh()   # 触发卡片 / 按钮 / Tab 图标全量重建
    assert icon_colors, "未渲染任何图标，断言无效"
    allowed = set(palette.values())
    for c in icon_colors:
        assert c in allowed, f"图标取色未走 theme_color（疑似硬编码）: {c}"
    assert seen_keys, "theme_color 未被调用"


def test_role_page_buttons_icon_color_from_theme_color(qapp, monkeypatch, tmp_path):
    palette = {
        "text": "#1a1a1a", "text_secondary": "#1e1e1e",
        "accent": "#1b1b1b", "info": "#1c1c1c", "warning": "#1d1d1d",
    }
    icon_colors = []
    _enable_icons(monkeypatch, color_sink=icon_colors)
    _patch_storage_dirs(monkeypatch, tmp_path)

    import gui.pages.page_role as pr
    monkeypatch.setattr(pr, "theme_color",
                        lambda app_ctx, key, fallback: palette.get(key, fallback))
    pr.PageRole(_ctx(tmp_path))
    assert icon_colors, "角色页未渲染任何图标"
    allowed = set(palette.values())
    for c in icon_colors:
        assert c in allowed, f"角色页图标取色未走 theme_color: {c}"


# ---------------------------------------------------------------------------
# ⑤ 角色信息输入框：页面级 QSS 不得截断主题输入色
# ---------------------------------------------------------------------------
def test_role_info_edits_refresh_theme_colors(qapp, monkeypatch, tmp_path):
    """三个角色信息输入框具名，并随 ThemeEngine 的活动色板重刷。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_role import PageRole

    _patch_storage_dirs(monkeypatch, tmp_path)
    engine = ThemeEngine()
    engine.load_theme("ui_whale")
    ctx = _ctx(tmp_path)
    ctx.theme_engine = engine
    page = PageRole(ctx)
    try:
        names = ("roleNameEdit", "roleDescriptionEdit", "roleGivenNameEdit")
        for attr, name in zip(("name_edit", "desc_edit", "given_name_edit"), names):
            edit = getattr(page, attr)
            assert edit.objectName() == name

        whale_qss = page.styleSheet()
        for name in names:
            assert f"QLineEdit#{name}" in whale_qss
        for color in (engine.get_color("text"), engine.get_color("text_hint"),
                      engine.get_color("bg_card"), engine.get_color("border")):
            assert color in whale_qss
        assert "placeholder-text-color:" in whale_qss

        engine.load_theme("ui_night")
        night_qss = page.styleSheet()
        assert night_qss != whale_qss
        for color in (engine.get_color("text"), engine.get_color("text_hint"),
                      engine.get_color("bg_card"), engine.get_color("border")):
            assert color in night_qss
    finally:
        QApplication.instance().setStyleSheet("")


# ---------------------------------------------------------------------------
# ⑥ 任务 #278：矢量图标颜色随主题（真实 ThemeEngine，非构造期烤死）
# ---------------------------------------------------------------------------
def _solid_icon_hex(btn) -> str:
    """读按钮 QIcon 的实心像素色（测试桩图标为实心单色）。"""
    img = btn.icon().pixmap(14, 14).toImage()
    c = img.pixelColor(0, 0)
    return "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())


def _role_page_with_engine(monkeypatch, tmp_path, theme="ui_minimal"):
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_role import PageRole

    _patch_storage_dirs(monkeypatch, tmp_path)
    _enable_icons(monkeypatch)
    engine = ThemeEngine()
    engine.load_theme(theme)
    ctx = _ctx(tmp_path)
    ctx.theme_engine = engine
    return engine, PageRole(ctx)


def test_role_icons_recolor_follows_theme_switch(qapp, monkeypatch, tmp_path):
    """#278：切主题后角色页矢量图标颜色 = 新主题 accent（不再停留构造期旧色）。"""
    from gui.qt_compat import QApplication

    engine, page = _role_page_with_engine(monkeypatch, tmp_path, "ui_minimal")
    try:
        min_accent = engine.get_color("accent").lower()
        # 构造期即用当前主题色
        for btn in (page.new_btn, page.preset_new_btn,
                    page.export_card_btn, page.import_card_btn):
            assert _solid_icon_hex(btn) == min_accent

        engine.load_theme("ui_night")
        night_accent = engine.get_color("accent").lower()
        assert night_accent != min_accent, "两主题 accent 相同，断言无意义"
        # 切主题后图标必须用新主题色重建
        for btn in (page.new_btn, page.preset_new_btn,
                    page.export_card_btn, page.import_card_btn):
            assert _solid_icon_hex(btn) == night_accent, "切主题后图标仍是旧主题色"
    finally:
        QApplication.instance().setStyleSheet("")


def test_role_avatar_vector_icon_recolors_with_theme(qapp, monkeypatch, tmp_path):
    """#278：无图角色的矢量 ✨ 头像图标随 text_secondary 换肤刷新（非烤死）。"""
    from gui.qt_compat import QApplication
    from types import SimpleNamespace

    engine, page = _role_page_with_engine(monkeypatch, tmp_path, "ui_minimal")
    try:
        # 强制走「无头像资源 → 矢量 ✨」分支（随机 id 必无 assets）
        import gui.maid_avatar as ma
        monkeypatch.setattr(ma, "role_assets", lambda _rid: None)
        fake = SimpleNamespace(id="__probe_no_assets__", avatar=None)
        page._set_avatar_icon(fake)
        assert _solid_icon_hex(page.avatar_btn) == engine.get_color("text_secondary").lower()

        # 让刷新路径针对该无图角色重跑
        page._current_role_id = "__probe_no_assets__"
        monkeypatch.setattr(page.role_manager, "get_role", lambda _rid: fake)
        engine.load_theme("ui_night")
        assert _solid_icon_hex(page.avatar_btn) == engine.get_color("text_secondary").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_theme_refresh_does_not_touch_foreign_icons(qapp, monkeypatch, tmp_path):
    """#278：换肤重刷只作用于本页已知图标，绝不误改『外部/固定色』图标。"""
    from gui.qt_compat import QApplication, QPushButton
    from gui import icons

    engine, page = _role_page_with_engine(monkeypatch, tmp_path, "ui_minimal")
    try:
        # 一个不属于角色页刷新名单、且颜色固定（非主题驱动）的按钮
        foreign = QPushButton(page)
        foreign.setIcon(icons.icon("star", 14, "#010203"))
        fixed_before = _solid_icon_hex(foreign)

        engine.load_theme("ui_night")
        assert _solid_icon_hex(foreign) == fixed_before == "#010203"
    finally:
        QApplication.instance().setStyleSheet("")


def test_role_avatar_style_uses_theme_keys(qapp, monkeypatch, tmp_path):
    """#278：头像按钮配色不再硬编码，改取主题语义键并随换肤刷新。"""
    from gui.qt_compat import QApplication

    engine, page = _role_page_with_engine(monkeypatch, tmp_path, "ui_minimal")
    try:
        qss = page.avatar_btn.styleSheet()
        # 旧硬编码粉系色值必须消失
        for stale in ("#FFF0F5", "#C48A9C", "#FFB6C1", "#FFE4EC"):
            assert stale not in qss, f"头像按钮仍残留硬编码色 {stale}"
        assert engine.get_color("accent_light") in qss
        assert engine.get_color("accent_text") in qss
        assert engine.get_color("accent") in qss

        engine.load_theme("ui_night")
        night_qss = page.avatar_btn.styleSheet()
        assert night_qss != qss
        assert engine.get_color("accent_light") in night_qss
        assert engine.get_color("accent_text") in night_qss
    finally:
        QApplication.instance().setStyleSheet("")


# ---------------------------------------------------------------------------
# ⑦ 任务 #291：8 处图标换肤统一收口（真实 ThemeEngine + 实心单色桩图标）
# ---------------------------------------------------------------------------
def _stub_icons_engine(monkeypatch, engine):
    """桩图标：``color=None`` 时按引擎 ``text`` **动态**取色（复现真实 ``icons.icon``
    语义，使 ``color=None`` 的落点也能被观测）。实心单色、零字体依赖、确定性。"""
    from gui import icons
    from gui.qt_compat import QColor, QIcon, QPixmap

    def fake_icon(name, size=16, color=None):
        c = color
        if c is None:
            c = engine.get_color("text", "#000000")
        px = max(1, int(size))
        pm = QPixmap(px, px)
        pm.fill(QColor(c or "#000000"))
        return QIcon(pm)

    monkeypatch.setattr(icons, "available", lambda: True)
    monkeypatch.setattr(icons, "has", lambda name: True)
    monkeypatch.setattr(icons, "icon", fake_icon)


def _icon_hex(icon, size=16) -> str:
    """读 QIcon 的实心像素色（桩图标为实心单色）。"""
    img = icon.pixmap(size, size).toImage()
    c = img.pixelColor(0, 0)
    return "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())


def _pixmap_hex(pm) -> str:
    img = pm.toImage()
    c = img.pixelColor(0, 0)
    return "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())


def _engine_ctx(engine, **kw):
    ctx = SimpleNamespace(theme_engine=engine)
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def test_memories_clear_btn_icon_recolors(qapp, monkeypatch, tmp_path):
    """#291 page_memories：清除按钮图标随换肤重刷（text_secondary）。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_memories import PageMemories
    from highlights import HighlightsManager

    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    ctx = _engine_ctx(engine, highlights=HighlightsManager(filepath=str(tmp_path / "h.json")))
    page = PageMemories(ctx)
    try:
        assert _icon_hex(page.clear_btn.icon(), 14) == engine.get_color("text_secondary").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(page.clear_btn.icon(), 14) == engine.get_color("text_secondary").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_memory_book_tab_buttons_recolor(qapp, monkeypatch, tmp_path):
    """#291 page_memory_book：各分区操作按钮图标随换肤重刷（accent）。"""
    from gui.qt_compat import QApplication, QPushButton
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_memory_book import PageMemoryBook

    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    ctx = _engine_ctx(engine, session=None, diary=None, weekly=None, highlights=None)
    page = PageMemoryBook(ctx)
    add_btn = page.pref_tab.findChild(QPushButton, "memoryBookBtn")
    try:
        assert add_btn is not None
        assert _icon_hex(add_btn.icon(), 14) == engine.get_color("accent").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(add_btn.icon(), 14) == engine.get_color("accent").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_plan_milestone_icon_recolors(qapp, monkeypatch, tmp_path):
    """#291 page_plan：里程碑树图标随换肤重刷（accent）。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    import gui.pages.page_plan as pp

    monkeypatch.setattr(pp, "DEFAULT_PLANS_DIR", tmp_path / "plans")
    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    page = pp.PagePlan(_engine_ctx(engine))
    plan = page.plan_manager.create_plan("探针")
    plan.milestones.append(pp.Milestone(id="m1", name="M1", tasks=[]))
    page._load_plans()
    try:
        it = page.milestone_tree.topLevelItem(0)
        assert it is not None
        assert _icon_hex(it.icon(0), 16) == engine.get_color("accent").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(page.milestone_tree.topLevelItem(0).icon(0), 16) == engine.get_color("accent").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_toolbox_category_icon_recolors(qapp, monkeypatch, tmp_path):
    """#291 page_toolbox：左侧分类图标随换肤重刷（text）。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_toolbox import PageToolbox

    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    page = PageToolbox(_engine_ctx(engine))
    try:
        assert _icon_hex(page.tool_list.item(0).icon(), 16) == engine.get_color("text").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(page.tool_list.item(0).icon(), 16) == engine.get_color("text").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_help_title_icon_recolors(qapp, monkeypatch, tmp_path):
    """#291 page_help：标题图标随换肤重刷（text）—— 本页此前无换肤订阅。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_help import PageHelp

    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    page = PageHelp(_engine_ctx(engine))
    label = page._title_icon_label
    try:
        assert label is not None, "标题图标 label 未创建"
        assert _pixmap_hex(label.pixmap()) == engine.get_color("text").lower()
        engine.load_theme("ui_night")
        assert _pixmap_hex(page._title_icon_label.pixmap()) == engine.get_color("text").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_proactive_feedback_spark_recolors(qapp, monkeypatch, tmp_path):
    """#291 proactive_feedback：✨ 火花图标随换肤重刷（text，color=None 路径）。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.widgets.proactive_feedback import ProactiveFeedbackBar

    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    bar = ProactiveFeedbackBar("主题", "idle_hello", None)
    bar.set_app_ctx(_engine_ctx(engine))
    try:
        assert _icon_hex(bar._spark.icon(), 14) == engine.get_color("text").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(bar._spark.icon(), 14) == engine.get_color("text").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_sidebar_nav_icon_follows_theme_guard(qapp, monkeypatch, tmp_path):
    """回归守卫：sidebar 导航图标在 #291 清单中判为『已跟随』—— 钉死该行为防退化。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.widgets.sidebar import SidebarWidget

    _patch_storage_dirs(monkeypatch, tmp_path)
    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    side = SidebarWidget(_engine_ctx(engine, cfg=None))
    try:
        assert _icon_hex(side.list_widget.item(1).icon(), 16) == engine.get_color("text").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(side.list_widget.item(1).icon(), 16) == engine.get_color("text").lower()
    finally:
        QApplication.instance().setStyleSheet("")


def test_chat_panel_title_icon_follows_theme_guard(qapp, monkeypatch, tmp_path):
    """回归守卫：chat_panel 顶栏图标在 #291 清单中判为『已跟随』—— 钉死防退化。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine
    from gui.widgets.chat_panel import ChatPanelWidget
    import gui.motion as motion

    old_level = motion.level()
    try:
        motion.configure("off")
    except Exception:
        pass
    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    _stub_icons_engine(monkeypatch, engine)
    ctx = _engine_ctx(
        engine, config=SimpleNamespace(glass_popups_enabled=True),
        chat_service=None, session_manager=None, companion_bridge=None,
        companion=None, tts=None, gui_session=None, glass=None,
        session=SimpleNamespace(history=[]),
    )
    panel = ChatPanelWidget(ctx)
    btns = list(getattr(panel, "_icon_buttons", {}).keys())
    try:
        assert btns, "顶栏无矢量图标按钮"
        b = btns[0]
        assert _icon_hex(b.icon(), 16) == engine.get_color("text").lower()
        engine.load_theme("ui_night")
        assert _icon_hex(b.icon(), 16) == engine.get_color("text").lower()
    finally:
        QApplication.instance().setStyleSheet("")
        try:
            motion.configure(old_level)
        except Exception:
            pass
