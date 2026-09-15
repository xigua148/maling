# -*- coding: utf-8 -*-
"""#279 收口回归：两状态条 emoji→矢量字形（含字体不可用回落）+ 首页「最近会话」标题。

覆盖：
  · 免提状态条 ``state_texts`` / 按钮：图标可用 → 字形；不可用 → 原 emoji；
    例外 —— ``recognizing`` 按 #279 裁决**保留裸 ``👂``**（manifest 无「耳朵」语义名，
    复用 ``headphone`` 会与 ``listening`` 态 ``🎧→headphone`` 同名重复）；
  · 看屏状态条 ``_compose_text`` / 按钮：``👀`` → ``watch``（eye-line）；不可用 → 原 emoji；
  · 首页「最近会话」标题纳入 ``homeSectionTitle``（字号 17 / 换肤重刷）；
  · 首页最近会话清单：取**人名**（given_name / 主人）而非原始 ``role`` 令牌，
    且 ``system`` 行不展示、无历史时**无假会话**。

**确定性**：图标内核用桩（``icons.text_glyph`` 记录调用并返回固定字形），
不注册真实字体、前/后复位状态（autouse），绝不外泄到其它测试文件。
GUI 一律 offscreen；起止不依赖真事件循环。
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

GLYPH = "\ue900"   # 桩字形（PUA，模拟 remixicon 字形字符）
_TOFU = "\ufffd"   # 替换字符（方框/空白异常哨兵）


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
    """本文件每个用例前后复位图标内核状态（防外泄 / 防被其它文件影响）。"""
    from gui import icons
    icons._reset_state()
    yield
    icons._reset_state()
    try:
        icons.clear_cache()
    except Exception:
        pass


def _stub_text_glyph(monkeypatch, available: bool):
    """桩化 ``icons.text_glyph``：记录每次 ``(name, fallback)``；按 ``available`` 返回字形/原串。"""
    from gui import icons
    calls = []

    def fake(name, fallback):
        calls.append((name, fallback))
        return GLYPH if available else fallback

    monkeypatch.setattr(icons, "text_glyph", fake)
    return calls


def _ctx():
    """极简 app_ctx：无 theme_engine（取色走兜底，D 口吻自称回落「码铃」）。"""
    return SimpleNamespace(theme_engine=None)


# ---------------------------------------------------------------------------
# ① 免提状态条
# ---------------------------------------------------------------------------
def test_handsfree_state_texts_glyph_when_available(monkeypatch):
    calls = _stub_text_glyph(monkeypatch, available=True)
    from gui.widgets.handsfree_bar import state_texts

    texts = state_texts()

    # recognising 为裁决例外：始终保留裸 👂，不参与字形化断言
    assert texts["recognizing"] == "👂 听到了，正在识别…"

    for st, txt in texts.items():
        if st == "recognizing":
            continue
        assert GLYPH in txt, f"{st} 未出行字形：{txt!r}"
        assert txt.strip() and _TOFU not in txt

    # 已字符化的状态映射到对应已登记语义位
    assert ("voice", "🎙") in calls
    assert ("headphone", "🎧") in calls   # listening 态耳机语义贴切，保留
    assert ("send", "📨") in calls
    assert ("volume", "🔊") in calls
    # recognising 不再调用 text_glyph（避免与 listening 态 headphone 同名重复）
    assert ("headphone", "👂") not in calls
    # 已字符化 → 文案里不再残留对应 emoji
    assert "🎙" not in texts["idle"]


def test_handsfree_state_texts_fallback_emoji_when_unavailable(monkeypatch):
    _stub_text_glyph(monkeypatch, available=False)
    from gui.widgets.handsfree_bar import state_texts

    texts = state_texts()
    assert texts["recognizing"] == "👂 听到了，正在识别…"
    assert texts["idle"].startswith("免提未开启：点下方「🎙 免提」")
    assert texts["listening"].startswith("🎧 ")
    for txt in texts.values():
        assert txt.strip() and _TOFU not in txt


def test_handsfree_bar_widget_glyph_and_fallback(qapp, monkeypatch):
    from gui.widgets.handsfree_bar import HandsfreeBar

    _stub_text_glyph(monkeypatch, available=True)
    bar = HandsfreeBar(_ctx())
    assert GLYPH in bar._stop_btn.text(), "停止按钮未出行字形"
    bar.set_state("listening")
    assert GLYPH in bar._status.text() and "🎧" not in bar._status.text()
    # recognising 例外：即便图标字形可用，也保持裸 👂（#279 裁决）
    bar.set_state("recognizing")
    assert bar._status.text() == "👂 听到了，正在识别…"

    _stub_text_glyph(monkeypatch, available=False)
    bar2 = HandsfreeBar(_ctx())
    assert bar2._stop_btn.text() == "⏹ 停止免提"
    bar2.set_state("recognizing")
    assert bar2._status.text() == "👂 听到了，正在识别…"


# ---------------------------------------------------------------------------
# ② 看屏状态条
# ---------------------------------------------------------------------------
def test_screenwatch_glyph_when_available(qapp, monkeypatch):
    calls = _stub_text_glyph(monkeypatch, available=True)
    from gui.widgets.screen_watch_bar import (
        ScreenWatchBar, STATE_IDLE, STATE_RUNNING,
    )

    bar = ScreenWatchBar(_ctx())
    assert GLYPH in bar._peek_btn.text()
    assert GLYPH in bar._ask_btn.text()
    assert GLYPH in bar._close_btn.text()
    bar.set_state(STATE_IDLE)
    assert GLYPH in bar._status.text() and "👀" not in bar._status.text()
    bar.set_state(STATE_RUNNING)
    bar.set_stats(3, 1200)
    txt = bar._status.text()
    assert GLYPH in txt and "在看" in txt and "👀" not in txt
    # 👀 映射到已登记的 watch（eye-line）语义位
    assert ("watch", "👀") in calls


def test_screenwatch_fallback_emoji_when_unavailable(qapp, monkeypatch):
    _stub_text_glyph(monkeypatch, available=False)
    from gui.widgets.screen_watch_bar import (
        ScreenWatchBar, STATE_IDLE, STATE_RUNNING,
    )

    bar = ScreenWatchBar(_ctx())
    bar.set_state(STATE_IDLE)
    assert bar._status.text() == "👀 看屏未开启"
    bar.set_state(STATE_RUNNING)
    bar.set_stats(0, 0)
    assert bar._status.text().startswith("👀 码铃在看 · 已分析 0 帧")
    assert _TOFU not in bar._status.text()
    assert bar._peek_btn.text() == "📷 看一帧"
    assert bar._ask_btn.text() == "🔍 按当前屏提问"
    assert bar._close_btn.text() == "✕ 关"


# ---------------------------------------------------------------------------
# ③ 首页「最近会话」标题 —— 纳入 homeSectionTitle
# ---------------------------------------------------------------------------
def _home_ctx(tmp_path):
    from highlights import HighlightsManager
    from weekly import WeeklyReviewManager
    return SimpleNamespace(
        theme_engine=None, session=None, session_manager=None, page_manager=None,
        config=None, companion=None, companion_bridge=None, role_bridge=None,
        highlights=HighlightsManager(filepath=str(tmp_path / "h.json")),
        weekly=WeeklyReviewManager(filepath=str(tmp_path / "w.json")),
        diary=None,
    )


def test_home_recent_sessions_title_shares_section_objectname(qapp, tmp_path, monkeypatch):
    """「最近会话」标题必须与其它分区标题共用 ``homeSectionTitle``（字号 17 + 换肤重刷）。"""
    import gui.pages.page_role as pr
    import gui.pages.page_plan as pp
    monkeypatch.setattr(pr, "DEFAULT_ROLES_DIR", tmp_path / "roles")
    monkeypatch.setattr(pr, "ROLE_AVATARS_DIR", tmp_path / "roles" / "avatars")
    monkeypatch.setattr(pp, "DEFAULT_PLANS_DIR", tmp_path / "plans")

    from gui.qt_compat import QLabel
    from gui.pages.page_home import PageHome

    page = PageHome(_home_ctx(tmp_path))
    titles = page.findChildren(QLabel, "homeSectionTitle")
    assert any(lb.text() == "最近会话" for lb in titles), \
        "「最近会话」标题未纳入 homeSectionTitle（换肤不刷新 / 字号落到 14px）"


# ---------------------------------------------------------------------------
# ④ 首页最近会话清单 —— 取人名（非 role 令牌）+ 无假会话
# ---------------------------------------------------------------------------
def _home_stub(session):
    from gui.qt_compat import QListWidget
    return SimpleNamespace(session_list=QListWidget(),
                           app_ctx=SimpleNamespace(session=session))


def _items(stub):
    return [stub.session_list.item(i).text() for i in range(stub.session_list.count())]


def test_recent_sessions_use_speaker_names_not_role_tokens(qapp, monkeypatch):
    import gui.widgets.message_bubble as mb
    monkeypatch.setattr(mb, "resolve_default_speaker_name", lambda: "小铃")

    from gui.pages.page_home import PageHome

    stub = _home_stub(SimpleNamespace(history=[
        {"role": "system", "content": "你是一位温柔贴心的女仆型编程助手"},
        {"role": "user", "content": "帮我写个排序函数"},
        {"role": "assistant", "content": "好的主人~"},
    ]))
    PageHome._load_recent_sessions(stub)
    got = _items(stub)
    assert got == ["主人: 帮我写个排序函数...", "小铃: 好的主人~..."], got
    # 不得再出现原始 role 令牌，也不得把 system 提示词当头行
    for it in got:
        assert not it.startswith("system:")
        assert not it.startswith("assistant:")
        assert not it.startswith("user:")


def test_recent_sessions_truthful_empty_state(qapp):
    """无历史 / 仅 system → 真实空态（不再展示 5 条硬编码假会话）。"""
    from gui.pages.page_home import PageHome

    for sess in (
        None,
        SimpleNamespace(history=[]),
        SimpleNamespace(history=[{"role": "system", "content": "SYS-PROMPT"}]),
    ):
        stub = _home_stub(sess)
        PageHome._load_recent_sessions(stub)
        got = _items(stub)
        assert got == [], f"空/纯 system 历史不应产出条目：{got!r}"
        assert not any("代码审查讨论" in it for it in got)
