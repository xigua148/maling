# -*- coding: utf-8 -*-
"""v2.1 域9（UI-P2）：投影层次试点 ``gui/elevation.py`` 单测。

覆盖：
  ① ``parse_css_shadow`` 全形态解析（标准 / 只有颜色 / none / 非法 / inset / 非字符串）；
  ② CSS blur → Qt blur 的 **/2** 换算与下限夹取；
  ③ ``current_shadow`` 对「缺失 / 非法 / 引擎抛错」三种情况的静默降级；
  ④ ``apply_card_shadow`` 挂载 + level 倍率 + 已有 opacity effect 不接管；
  ⑤ 换肤（``theme_changed``）后阴影**颜色随之更新**，不残留旧色；
  ⑥ 主题无 ``shadow`` → 换肤后把已挂阴影**摘掉**（不残留）；
  ⑦ ``ENABLED=False`` 总开关 / ``widget=None`` → 无副作用；
  ⑧ 控件销毁后登记自动回收（``mounted_count`` 归零，无泄漏）；
  ⑨ 首页真实构造（注入引擎）→ 挂载 4 处；无引擎 → 静默跳过 0 处。

红线：只做只读断言 + 离屏控件，不写业务数据、不改主题定义、不改字号。
GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui import elevation
from gui.qt_compat import (
    QApplication, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QObject, Signal,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _FakeEngine(QObject):
    """极简主题引擎桩：只提供 ``get_color`` + ``theme_changed``，零副作用。"""

    theme_changed = Signal(str)

    def __init__(self, shadow: str = "0 6px 20px rgba(255,143,163,0.13)"):
        super().__init__()
        self._shadow = shadow

    def get_color(self, key: str, fallback: str = "") -> str:
        if key == "shadow" and self._shadow:
            return self._shadow
        return fallback


@pytest.fixture(autouse=True)
def _clean_state():
    """每个用例前后清空模块级登记与开关，杜绝用例间外泄。"""
    elevation._REGISTRY.clear()
    saved_engine = elevation._ENGINE
    saved_bound = elevation._BOUND_ENGINE_ID
    elevation._ENGINE = None
    elevation._BOUND_ENGINE_ID = None
    elevation.ENABLED = True
    yield
    elevation._REGISTRY.clear()
    elevation._ENGINE = saved_engine
    elevation._BOUND_ENGINE_ID = saved_bound
    elevation.ENABLED = True


# ---------------------------------------------------------------------------
# ① CSS box-shadow 解析
# ---------------------------------------------------------------------------
def test_parse_standard():
    parsed = elevation.parse_css_shadow("0 1px 3px rgba(0,0,0,0.05)")
    assert parsed is not None
    off_x, off_y, css_blur, color = parsed
    assert (off_x, off_y, css_blur) == (0.0, 1.0, 3.0)
    assert color.alphaF() == pytest.approx(0.05, abs=0.005)


def test_parse_cream_geometry():
    parsed = elevation.parse_css_shadow("0 6px 20px rgba(255,143,163,0.13)")
    assert parsed is not None
    off_x, off_y, css_blur, color = parsed
    assert (off_x, off_y, css_blur) == (0.0, 6.0, 20.0)
    assert (color.red(), color.green(), color.blue()) == (255, 143, 163)


def test_parse_color_only_uses_default_geometry():
    """旧主题只有颜色没有几何 → 落缺省 (0, 1) / blur 3。"""
    parsed = elevation.parse_css_shadow("rgba(255,182,193,0.15)")
    assert parsed is not None
    off_x, off_y, css_blur, color = parsed
    assert (off_x, off_y, css_blur) == (
        elevation._DEFAULT_OFFSET_X, elevation._DEFAULT_OFFSET_Y,
        elevation._DEFAULT_CSS_BLUR,
    )
    assert color.isValid()


@pytest.mark.parametrize("bad", [
    "none", "", "   ", None, 123, 4.5, [], {},
    "inset 0 1px 3px rgba(0,0,0,0.5)", "rgba(300,0,0,0.5)", "transparent",
])
def test_parse_invalid_returns_none(bad):
    """非法 / 缺失 / 内阴影 → 返回 None（静默跳过，绝不抛异常）。"""
    assert elevation.parse_css_shadow(bad) is None


# ---------------------------------------------------------------------------
# ② CSS blur → Qt blur 换算
# ---------------------------------------------------------------------------
def test_qt_blur_is_half_of_css_blur():
    """CSS blur ≈ 2×stdDev、Qt blurRadius ≈ stdDev ⇒ qt = css / 2。"""
    assert elevation.qt_blur_radius(20.0) == pytest.approx(10.0)
    assert elevation.qt_blur_radius(3.0) == pytest.approx(1.5)


@pytest.mark.parametrize("css_blur", [0.0, -5.0, 0.4])
def test_qt_blur_has_lower_bound(css_blur):
    assert elevation.qt_blur_radius(css_blur) >= elevation._MIN_QT_BLUR


def test_qt_blur_bad_input_falls_back():
    assert elevation.qt_blur_radius("x") >= elevation._MIN_QT_BLUR


# ---------------------------------------------------------------------------
# ③ current_shadow 静默降级
# ---------------------------------------------------------------------------
def test_current_shadow_ok():
    eng = _FakeEngine("0 2px 12px rgba(0,0,0,0.35)")
    parsed = elevation.current_shadow(eng)
    assert parsed is not None
    assert parsed[2] == 12.0


@pytest.mark.parametrize("raw", ["", "not-a-shadow", "#zzz"])
def test_current_shadow_missing_or_invalid(raw):
    assert elevation.current_shadow(_FakeEngine(raw)) is None


def test_current_shadow_engine_raises():
    class _Boom:
        theme_changed = None

        def get_color(self, key, fallback=""):
            raise RuntimeError("boom")

    assert elevation.current_shadow(_Boom()) is None


def test_current_shadow_no_engine():
    assert elevation.current_shadow(None) is None
    assert elevation.current_shadow(object()) is None


# ---------------------------------------------------------------------------
# ④ apply_card_shadow 挂载
# ---------------------------------------------------------------------------
def test_apply_mounts_effect(qapp):
    eng = _FakeEngine()
    w = QFrame()
    assert elevation.apply_card_shadow(w, level=1, engine=eng) is True
    eff = w.graphicsEffect()
    assert isinstance(eff, QGraphicsDropShadowEffect)
    assert eff.blurRadius() == pytest.approx(10.0)          # css 20 → qt 10
    assert eff.offset().y() == pytest.approx(6.0)
    assert elevation.mounted_count() == 1


def test_apply_level_scales(qapp):
    eng = _FakeEngine()
    w1, w2 = QFrame(), QFrame()
    elevation.apply_card_shadow(w1, level=1, engine=eng)
    elevation.apply_card_shadow(w2, level=2, engine=eng)
    b1 = w1.graphicsEffect().blurRadius()
    b2 = w2.graphicsEffect().blurRadius()
    assert b2 == pytest.approx(b1 * elevation._LEVEL_SCALE[2])


def test_apply_illegal_level_falls_back_to_one(qapp):
    eng = _FakeEngine()
    w = QFrame()
    assert elevation.apply_card_shadow(w, level=99, engine=eng) is True
    assert w.graphicsEffect().blurRadius() == pytest.approx(10.0)


def test_apply_skips_when_no_shadow(qapp):
    w = QFrame()
    assert elevation.apply_card_shadow(w, engine=_FakeEngine("")) is False
    assert w.graphicsEffect() is None
    assert elevation.mounted_count() == 0


def test_apply_skips_when_existing_opacity_effect(qapp):
    """动效层已挂 opacity effect → 本层不接管（两类效果互斥）。"""
    w = QFrame()
    w.setGraphicsEffect(QGraphicsOpacityEffect(w))
    assert elevation.apply_card_shadow(w, engine=_FakeEngine()) is False
    assert isinstance(w.graphicsEffect(), QGraphicsOpacityEffect)


def test_apply_reuses_existing_drop_shadow(qapp):
    """重复挂载同一控件 → 复用 effect，不叠加。"""
    eng = _FakeEngine()
    w = QFrame()
    assert elevation.apply_card_shadow(w, engine=eng) is True
    first = w.graphicsEffect()
    assert elevation.apply_card_shadow(w, engine=eng) is True
    assert w.graphicsEffect() is first
    assert elevation.mounted_count() == 1


# ---------------------------------------------------------------------------
# ⑤⑥ 换肤刷新
# ---------------------------------------------------------------------------
def test_theme_switch_updates_shadow_color(qapp):
    eng = _FakeEngine("0 6px 20px rgba(255,143,163,0.13)")
    w = QFrame()
    assert elevation.apply_card_shadow(w, level=1, engine=eng) is True
    assert w.graphicsEffect().color().name() == "#ff8fa3"

    eng._shadow = "0 2px 12px rgba(0,0,0,0.35)"
    eng.theme_changed.emit("ui_night")

    eff = w.graphicsEffect()
    assert isinstance(eff, QGraphicsDropShadowEffect), "换肤后仍须挂着阴影"
    assert eff.color().name() == "#000000", "阴影颜色须随主题更新，不能残留旧色"
    assert eff.blurRadius() == pytest.approx(6.0)


def test_theme_without_shadow_removes_effect(qapp):
    eng = _FakeEngine()
    w = QFrame()
    assert elevation.apply_card_shadow(w, engine=eng) is True

    eng._shadow = ""
    eng.theme_changed.emit("no_shadow_theme")

    assert w.graphicsEffect() is None, "新主题无 shadow → 摘掉，绝不残留旧色"


def test_refresh_all_returns_count(qapp):
    eng = _FakeEngine()
    ws = [QFrame() for _ in range(3)]
    for w in ws:
        elevation.apply_card_shadow(w, engine=eng)
    assert elevation.refresh_all("ui_cream") == 3
    eng._shadow = ""
    assert elevation.refresh_all("ui_cream") == 0


# ---------------------------------------------------------------------------
# ⑦ 总开关 / 空参
# ---------------------------------------------------------------------------
def test_enabled_switch_off(qapp):
    eng = _FakeEngine()
    w = QFrame()
    elevation.ENABLED = False
    assert elevation.apply_card_shadow(w, engine=eng) is False
    assert w.graphicsEffect() is None


@pytest.mark.parametrize("widget", [None, "not-a-widget"])
def test_apply_invalid_widget(qapp, widget):
    assert elevation.apply_card_shadow(widget, engine=_FakeEngine()) is False


def test_apply_with_app_ctx(qapp):
    eng = _FakeEngine()
    w = QFrame()
    assert elevation.apply_card_shadow(w, app_ctx=SimpleNamespace(theme_engine=eng)) is True
    assert isinstance(w.graphicsEffect(), QGraphicsDropShadowEffect)


def test_apply_without_engine_is_silent(qapp):
    w = QFrame()
    assert elevation.apply_card_shadow(w) is False
    assert w.graphicsEffect() is None


# ---------------------------------------------------------------------------
# ⑧ 生命周期 / 回退
# ---------------------------------------------------------------------------
def test_widget_destroyed_cleans_registry(qapp):
    eng = _FakeEngine()
    w = QFrame()
    elevation.apply_card_shadow(w, engine=eng)
    assert elevation.mounted_count() == 1
    w.setParent(None)
    del w
    assert elevation.mounted_count() == 0, "控件销毁后登记必须回收（弱引用，不泄漏）"


def test_remove_card_shadow(qapp):
    eng = _FakeEngine()
    w = QFrame()
    elevation.apply_card_shadow(w, engine=eng)
    assert elevation.remove_card_shadow(w) is True
    assert w.graphicsEffect() is None
    assert elevation.mounted_count() == 0
    assert elevation.remove_card_shadow(w) is False, "幂等"


# ---------------------------------------------------------------------------
# ⑨ 真实页面挂载（试点范围：首页 4 处）
# ---------------------------------------------------------------------------
def test_page_home_mounts_four_cards(qapp):
    from gui.pages.page_home import PageHome

    eng = _FakeEngine()
    ctx = SimpleNamespace(
        theme_engine=eng, session=None, session_manager=None, companion=None,
        companion_bridge=None, weekly=None, highlights=None, diary=None,
    )
    home = PageHome(ctx)
    try:
        assert elevation.mounted_count() == 4, "试点范围：房间卡 + 3 张状态卡"
        for card in (home.room_card, home.token_card,
                     home.network_card, home.project_card):
            assert isinstance(card.graphicsEffect(), QGraphicsDropShadowEffect)
    finally:
        home.setParent(None)


def test_page_home_without_engine_mounts_nothing(qapp):
    from gui.pages.page_home import PageHome

    home = PageHome(SimpleNamespace())
    try:
        assert elevation.mounted_count() == 0, "无主题引擎 → 静默跳过，界面照常"
        assert home.room_card.graphicsEffect() is None
    finally:
        home.setParent(None)


# ---------------------------------------------------------------------------
# ⑩ 代码纪律（静态）：不硬编码颜色 / 不改字号
# ---------------------------------------------------------------------------
def test_module_has_no_hardcoded_colors_and_no_font_size():
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "gui", "elevation.py")
    with open(src, "r", encoding="utf-8") as fh:
        text = fh.read()
    # 只查**真实调用**（带左括号），避免误伤文档里对红线的说明文字
    for banned in ("setPointSize(", "setPixelSize(", "setFont("):
        assert banned not in text, f"elevation 不得触碰字号（{banned}）"
    assert 'QColor("#' not in text, "取色一律走主题 shadow 变量，禁止硬编码色值"
    assert "QGraphicsDropShadowEffect" in text
