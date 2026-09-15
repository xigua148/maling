# -*- coding: utf-8 -*-
"""#279 续回归：page_home「最近会话」接线（A）+ 矢量图标换肤（B）。

A. ``PageHome.session_selected`` 此前全仓零消费者 → 首页「最近会话」点了没反应。
   修复：列表源改为 ``session_manager`` 真实会话（``Qt.UserRole`` = session id），
   ``MainWindow`` 按 ``project_page.file_opened`` 同款范式消费 → 复用既有
   ``ChatPanelWidget._switch_to_session`` 切会话并回聊天主屏。

B. page_home 矢量图标颜色烤在 QPixmap 里、QSS 管不到 → 换肤后不变色。
   修复：在既有 ``_apply_theme`` 换肤入口按新主题色重建（沿用 page_role 范式）。

确定性：图标内核用**实心单色桩**（不注册真实字体）；真实 ``ThemeEngine``；GUI 一律
offscreen；起止不依赖墙钟。图标内核状态 autouse 前后复位，绝不外泄到其它测试文件。
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures / helpers
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
    from gui import icons
    icons._reset_state()
    yield
    icons._reset_state()
    try:
        icons.clear_cache()
    except Exception:
        pass


def _enable_icons(monkeypatch):
    """图标内核桩：始终可用、返回**实心单色** QIcon（颜色可直接读）。"""
    from gui import icons
    from gui.qt_compat import QColor, QIcon, QPixmap

    def fake_icon(name, size=16, color=None):
        px = max(1, int(size))
        pm = QPixmap(px, px)
        pm.fill(QColor(color or "#000000"))
        return QIcon(pm)

    monkeypatch.setattr(icons, "available", lambda: True)
    monkeypatch.setattr(icons, "has", lambda _name: True)
    monkeypatch.setattr(icons, "icon", fake_icon)


def _disable_icons(monkeypatch):
    from gui import icons
    monkeypatch.setattr(icons, "available", lambda: False)
    monkeypatch.setattr(icons, "has", lambda _name: False)


def _patch_storage_dirs(monkeypatch, tmp_path):
    import gui.pages.page_role as pr
    import gui.pages.page_plan as pp
    monkeypatch.setattr(pr, "DEFAULT_ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(pr, "ROLE_AVATARS_DIR", tmp_path / "roles" / "avatars")
    monkeypatch.setattr(pp, "DEFAULT_PLANS_DIR", tmp_path / "plans")


def _page_ctx(tmp_path, theme_engine=None, session_manager=None, session=None):
    from highlights import HighlightsManager
    from weekly import WeeklyReviewManager
    return SimpleNamespace(
        theme_engine=theme_engine, session=session, session_manager=session_manager,
        page_manager=None, config=None, companion=None, companion_bridge=None,
        role_bridge=None,
        highlights=HighlightsManager(filepath=str(tmp_path / "h.json")),
        weekly=WeeklyReviewManager(filepath=str(tmp_path / "w.json")),
        diary=None,
    )


def _icon_hex(icon, size=16):
    if icon is None or icon.isNull():
        return None
    c = icon.pixmap(size, size).toImage().pixelColor(0, 0)
    return "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())


def _label_hex(host, name):
    from gui.qt_compat import QLabel
    lbl = host.findChild(QLabel, name)
    if lbl is None:
        return None
    pm = lbl.pixmap()
    if pm is None or pm.isNull():
        return None
    c = pm.toImage().pixelColor(0, 0)
    return "#{:02x}{:02x}{:02x}".format(c.red(), c.green(), c.blue())


def _quick0(page):
    from gui.qt_compat import QPushButton
    btns = page.findChildren(QPushButton, "quickBtn")
    assert btns, "未找到快捷入口按钮"
    return btns[0]


# ===========================================================================
# A. 会话切换 —— 修复前 session_selected 零消费者、列表为消息行（无会话 id）
# ===========================================================================
def test_home_recent_sessions_lists_real_sessions_with_ids(qapp, monkeypatch, tmp_path):
    """有 session_manager → 列表 = 真实会话（名称文案 + UserRole 承载会话 id）。"""
    from gui.qt_compat import Qt
    from gui.session_manager import SessionManager
    from gui.pages.page_home import PageHome

    _patch_storage_dirs(monkeypatch, tmp_path)
    sm = SessionManager(sessions_dir=tmp_path / "sessions")
    a = sm.create_session("会话甲")
    b = sm.create_session("会话乙")
    sm.set_active(a.id)

    page = PageHome(_page_ctx(tmp_path, session_manager=sm))
    n = page.session_list.count()
    assert n >= 2, f"应列出真实会话，实际 {n} 条"
    texts = [page.session_list.item(i).text() for i in range(n)]
    assert any("会话甲" in t for t in texts) and any("会话乙" in t for t in texts), texts
    uids = {page.session_list.item(i).data(Qt.UserRole) for i in range(n)}
    assert {a.id, b.id} <= uids, f"条目未承载真实会话 id：{uids}"


def test_home_without_manager_keeps_message_fallback(qapp, monkeypatch, tmp_path):
    """无 session_manager（降级上下文）→ 仍走消息兜底（#279 语义不回退）。"""
    from gui.qt_compat import Qt
    from gui.pages.page_home import PageHome

    _patch_storage_dirs(monkeypatch, tmp_path)
    ctx = _page_ctx(tmp_path, session=SimpleNamespace(history=[
        {"role": "user", "content": "帮我写个排序函数"},
        {"role": "assistant", "content": "好的主人~"},
    ]))
    page = PageHome(ctx)
    n = page.session_list.count()
    assert n, "消息兜底不应为空"
    # 兜底消息行不承载会话 id（点击不应误发信号）
    assert all(not page.session_list.item(i).data(Qt.UserRole) for i in range(n))


# ---------------------------------------------------------------------------
# MainWindow 集成：点击条目 → 真的切到该会话 + 回聊天主屏
# ---------------------------------------------------------------------------
def _build_win(monkeypatch, tmp_path, sm, theme="ui_minimal"):
    import gui.main_window as mw_mod
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.qt_compat import QWidget

    _patch_storage_dirs(monkeypatch, tmp_path)

    class _RecPanel(QWidget):
        """桩聊天面板：承载真实 session_manager + 记录 _switch_to_session（复刻真实语义）。"""

        def __init__(self, app_ctx, parent=None):
            super().__init__(parent)
            self.app_ctx = app_ctx
            self.session_manager = getattr(app_ctx, "session_manager", None)
            self.switch_calls: list = []

        def _switch_to_session(self, session_id):
            self.switch_calls.append(session_id)
            if self.session_manager is not None:
                self.session_manager.set_active(session_id)

    monkeypatch.setattr(mw_mod, "ChatPanelWidget", _RecPanel)
    ctx = AppContext()
    ctx.config = GuiConfig()
    ctx.config.first_run = False
    ctx.config.theme_name = theme
    ctx.session_manager = sm
    try:
        monkeypatch.setattr(ctx.config, "save", lambda *a, **k: None)
    except Exception:
        pass
    return mw_mod.MainWindow(ctx)


def test_home_session_selected_has_consumer_static_guard():
    """守卫：MainWindow 必须消费 session_selected（防再次「零消费者」）。"""
    src = (ROOT / "gui" / "main_window.py").read_text(encoding="utf-8")
    assert "session_selected.connect(" in src, "session_selected 无消费者（回归！）"
    assert "_on_home_session_selected" in src


def test_home_click_switches_active_session_and_navigates(qapp, monkeypatch, tmp_path):
    """端到端：点击「最近会话」→ 面板切到该会话 + 回聊天主屏。"""
    from gui.qt_compat import Qt
    from gui.session_manager import SessionManager

    sm = SessionManager(sessions_dir=tmp_path / "sessions")
    a = sm.create_session("会话甲")
    b = sm.create_session("会话乙")
    sm.set_active(a.id)

    win = _build_win(monkeypatch, tmp_path, sm)
    try:
        page = win.pages["home"]
        idx = next(i for i in range(page.session_list.count())
                   if page.session_list.item(i).data(Qt.UserRole) == b.id)
        before = sm.active_session.id
        page.session_list.itemClicked.emit(page.session_list.item(idx))
        qapp.processEvents()

        assert sm.active_session.id == b.id, "未切到目标会话"
        assert b.id != before
        assert win.chat_panel.switch_calls == [b.id], "未被既有切换路径消费"
        assert win.page_stack.currentWidget() is win.chat_panel, "未回聊天主屏"
    finally:
        win.close()


def test_home_click_missing_session_no_crash_with_feedback(qapp, monkeypatch, tmp_path):
    """异常路径：目标会话不存在 → 不崩、不切换、给出可见提示。"""
    from gui.session_manager import SessionManager

    sm = SessionManager(sessions_dir=tmp_path / "sessions")
    a = sm.create_session("会话甲")
    sm.set_active(a.id)

    win = _build_win(monkeypatch, tmp_path, sm)
    try:
        page = win.pages["home"]
        page.session_selected.emit("__不存在的会话 id__")
        qapp.processEvents()
        assert sm.active_session.id == a.id, "不应切换"
        assert win.chat_panel.switch_calls == [], "不应调用切换"
        assert "找不到" in win.status_bar.currentMessage(), "缺少克制反馈"
    finally:
        win.close()


# ===========================================================================
# B. 矢量图标换肤 —— 修复前换肤后图标不变色
# ===========================================================================
def test_home_icons_recolor_follows_theme_switch(qapp, monkeypatch, tmp_path):
    """换肤后 page_home 各矢量图标颜色 = 新主题 ``text`` 语义色（非烤死旧色）。"""
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_home import PageHome
    from gui.qt_compat import QApplication

    _patch_storage_dirs(monkeypatch, tmp_path)
    _enable_icons(monkeypatch)
    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    page = PageHome(_page_ctx(tmp_path, theme_engine=engine))
    try:
        min_text = engine.get_color("text").lower()
        assert _icon_hex(_quick0(page).icon()) == min_text
        assert _icon_hex(page.model_entry_btn.icon()) == min_text
        assert _label_hex(page.token_card, "statusCardIcon") == min_text
        assert _label_hex(page.cards["deep"], "toggleCardIcon") == min_text

        engine.load_theme("ui_night")
        night_text = engine.get_color("text").lower()
        assert night_text != min_text, "两主题 text 相同，断言无意义"
        assert _icon_hex(_quick0(page).icon()) == night_text, "快捷入口图标停在旧色"
        assert _icon_hex(page.model_entry_btn.icon()) == night_text, "模型入口图标停在旧色"
        assert _label_hex(page.token_card, "statusCardIcon") == night_text, "状态卡图标停在旧色"
        assert _label_hex(page.cards["deep"], "toggleCardIcon") == night_text, "模式卡图标停在旧色"
    finally:
        QApplication.instance().setStyleSheet("")


def test_home_icons_fallback_no_crash_when_unavailable(qapp, monkeypatch, tmp_path):
    """图标字体不可用 → 换肤重建回落原 emoji 文案，不空白、不崩。"""
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_home import PageHome
    from gui.qt_compat import QApplication, QLabel

    _patch_storage_dirs(monkeypatch, tmp_path)
    _disable_icons(monkeypatch)
    engine = ThemeEngine()
    engine.load_theme("ui_minimal")
    page = PageHome(_page_ctx(tmp_path, theme_engine=engine))
    try:
        engine.load_theme("ui_night")  # 触发换肤重建（应静默回落）
        btn = _quick0(page)
        assert btn.icon().isNull(), "无图标字体时不应设图标"
        assert btn.text().strip(), "回落文案不应为空"
        lbl = page.cards["deep"].findChild(QLabel, "toggleCardIcon")
        assert lbl is not None and lbl.text().strip(), "模式卡图标回落文案为空"
    finally:
        QApplication.instance().setStyleSheet("")
