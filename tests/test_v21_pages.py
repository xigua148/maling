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
