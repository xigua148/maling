# -*- coding: utf-8 -*-
"""记忆册 `#memoryBookBtn` 文字色的**渲染级**回归守卫（v2.2.1 收口）。

## 缺陷（用户可感知）
`PageMemoryBook` 有 **5 个** `#memoryBookBtn`。v2.1 修复只覆盖了 1 个
（偏好 Tab「添加偏好」），另 4 个（导出 Markdown / 展开更早 / 添加约定 /
记下一位重要的人）落 `base.qss` 的 `color: ${accent}`（「填充/描边用」色）——
浅色三套主题下字形 vs 页面底仅 **3.051 / 2.057 / 2.966**，低于小字 AA 的 4.5:1。

## 为什么既有 2001 个用例拦不住
它们是**样式表字符串**断言或**setter 存值**断言（`findChild` 单实例 +
`tabTextColor` 那类）——两者都能「值对了但没上屏」。本项目已实测过
`setTabTextColor` 被主题 QSS `QTabBar::tab { color: }` 压制、从未上屏。
本文件因此只断言 **渲染出来的像素**。

## 三层防御（本文件逐层钉住）
1. **实例数**：`findChildren(QPushButton, "memoryBookBtn")` 必须 ≥ 5
   （防退回单实例 `findChild`，正是漏 4 个的直接成因）。
2. **逐实例渲染字形色**：切到该实例**所属 Tab** 后 `grab()`，按钮矩形内
   必须出现 `accent_text` 像素、且 `accent` 像素为 **0**；同时实测底色的
   对比度 ≥ 4.5。
3. **基线兜底**：一个**无任何内联样式**的裸 `#memoryBookBtn`（只吃
   `base.qss`）同样必须渲染 `accent_text` —— 钉住"下一个新增实例不会再踩"。
4. **按下态 `:pressed`**：该伪态**单独命中**时必须渲染 `text`，不得回落
   `accent_text`（回落值压在 `${bg_light}` 上仅 4.125/4.397/5.335/4.280，
   三套浅色 < 4.5）。实例侧与 base 基线各钉一头（控件级样式表会盖过 app 级
   `:pressed`，这是第 4 层存在的直接原因）。取法见 `_draw_pressed_alone`。

## 怎么把它玩坏（对抗性自检，执行方已跑过两轮）
· 破 (2)：注释掉 `page_memory_book.PageMemoryBook._apply_style` 末尾的
  `for _btn in self.findChildren(QPushButton, "memoryBookBtn")` 补色循环
  → 4 个实例回落 `base.qss` 的 `accent` → **变红**（实测 accent 像素
  416/192/192/320 → 断言 `cnt["accent"] == 0` 失败）。
· 破 (3)：把 `gui/themes/base.qss` 里共享规则体的 `color: ${accent_text};`
  改回 `color: ${accent};` → 裸按钮渲染 `accent` → **变红**。
· 破 (1)：把 `findChildren` 改回 `findChild`（或删掉任一实例）→ **变红**。
· 破 (4)：把 `base.qss` 的 `#secondaryBtn/#memoryBookBtn:pressed { color: ${text}; }`
  那一行删掉 → 裸控件那半边**变红**；把 `page_memory_book._apply_style` 里两条内联
  `:pressed { color: {text}; }` 删掉 → 5 个实例那半边**变红**（两边各自独立，互不兜底）。
（注：单改 (3) 不会让 (2) 变红 —— 5 个实例都有控件级内联样式，优先级更高。
这正是「三层」的意义：基线 + 实例级各钉一头。）

## 取像素口径（为什么不是一句 `page.grab()`）
offscreen 下**非当前** Tab 页从未被布局，即便 `setCurrentIndex` 到该页，
`mapTo()` 给出的仍是未激活的陈旧坐标 → 页面级 `grab()` 在按钮矩形内只能
取到一片纯底色（实测 `colors=1`）。故：
· **字形色**取控件自身 `btn.grab()`（权威：它只画自己，不受 Tab 激活与否影响）；
· **底色**取页面级 `pg.grab()` 在该矩形内的众数（= 按钮 `background: transparent`
  透出的那层底），用于算对比度。
两者互补，不做任何「样式表字符串」或 setter 存值断言。

不改产品代码；全部 offscreen、零网络、零真实用户目录写入。
"""
from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402

from gui.qt_compat import (  # noqa: E402
    QApplication, QColor, QHBoxLayout, QImage, QPainter, QPoint, QPushButton,
    QScrollArea, Qt, QWidget,
)

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
#: 小字 AA 阈值（WCAG 2.1）。
_MIN_RATIO = 4.5
#: 实例数下界（v2.2.0 实测 5：导出 / 展开更早 / 添加约定 / 记下一位重要的人 / 添加偏好）。
_MIN_INSTANCES = 5
_ISO = Path(tempfile.mkdtemp(prefix="maling_test_mbcolor_"))


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(scope="module")
def isolated_env():
    """把用户目录指到临时目录（禁止写真实 ``~/.maid_coder``）。"""
    keys = ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = str(_ISO)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _pump(n: int = 6) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def _hex(color) -> str:
    return "#%02X%02X%02X" % (color.red(), color.green(), color.blue())


def _lum(hx: str) -> float:
    def _ch(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    h = hx.lstrip("#")[:6]
    return (0.2126 * _ch(int(h[0:2], 16)) + 0.7152 * _ch(int(h[2:4], 16))
            + 0.0722 * _ch(int(h[4:6], 16)))


def _ratio(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 3)


def _rect_in(container, w):
    """控件在 container 坐标系下的矩形（须先 show() + 切到所属 Tab）。"""
    tl = w.mapTo(container, QPoint(0, 0))
    return (tl.x(), tl.y(), w.width(), w.height())


def _hist(img, rect) -> Counter:
    """矩形内像素直方图。走 `constBits()` 批量读（逐像素 `pixelColor` 在本文件会慢一个量级）。"""
    x0, y0, w, h = rect
    x0, y0 = max(0, x0), max(0, y0)
    w = min(img.width() - x0, w)
    h = min(img.height() - y0, h)
    if w <= 0 or h <= 0:
        return Counter()
    sub = img.copy(x0, y0, w, h).convertToFormat(QImage.Format_RGB32)
    buf = bytes(sub.constBits())
    cnt: Counter = Counter()
    for i in range(0, w * h * 4, 4):
        # Format_RGB32 小端：B G R A
        cnt["#%02X%02X%02X" % (buf[i + 2], buf[i + 1], buf[i])] += 1
    return cnt


def _px(hist: Counter, colors) -> dict:
    return {k: hist.get(v.upper(), 0) for k, v in colors.items()}


def _reveal(pg, btn) -> None:
    """把 btn 所在 Tab 切为当前 —— 非当前 Tab 的控件几何不可信。"""
    w = btn.parentWidget()
    while w is not None:
        if isinstance(w, QScrollArea):
            i = pg.tabs.indexOf(w)
            if i >= 0:
                pg.tabs.setCurrentIndex(i)
                _pump(6)
                return
        w = w.parentWidget()


def _ctx(theme: str):
    """真实 ThemeEngine + 最小 ctx 桩（与项目既有探针口径一致）。"""
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.load_theme(theme)
    ctx = SimpleNamespace(theme_engine=engine)
    ctx.cfg = SimpleNamespace(
        kb_index_file=str(_ISO / "kb.json"), todos_file=str(_ISO / "todos.json"),
        api_key="", api_provider="openai", agent_enabled=False,
    )
    for k in ("session", "companion", "companion_bridge", "session_manager",
              "highlights", "diary", "weekly", "tavern", "memories"):
        setattr(ctx, k, None)
    return engine, ctx


def _build_page(theme: str):
    from gui.pages.page_memory_book import PageMemoryBook
    engine, ctx = _ctx(theme)
    pg = PageMemoryBook(ctx)
    pg.resize(900, 660)
    pg.show()
    _pump(8)
    pg.refresh()
    _pump(8)
    return engine, pg


# ---------------------------------------------------------------------------
# 前提守卫：测试不能变成空转
# ---------------------------------------------------------------------------
def test_precondition_tokens_differ_per_theme(qapp, isolated_env):
    """`accent` 与 `accent_text` 必须逐套主题**不同**，否则下面的计数断言失去判别力。"""
    from gui.theme_engine import ThemeEngine
    for theme in THEMES:
        engine = ThemeEngine()
        engine.load_theme(theme)
        accent = engine.get_color("accent", "#000000")
        accent_text = engine.get_color("accent_text", "#000000")
        assert accent != accent_text, (
            f"{theme}: accent={accent} 与 accent_text={accent_text} 同值，"
            "本文件的像素判别断言将退化为空转")
        assert engine.get_color("bg", "#000000").startswith("#")


# ---------------------------------------------------------------------------
# ① 实例数：5 个（防退回单实例 findChild）
# ---------------------------------------------------------------------------
def test_memory_book_btn_instance_count(qapp, isolated_env):
    for theme in THEMES:
        engine, pg = _build_page(theme)
        try:
            btns = pg.findChildren(QPushButton, "memoryBookBtn")
            assert len(btns) >= _MIN_INSTANCES, (
                f"{theme}: 只找到 {len(btns)} 个 #memoryBookBtn（应 ≥ {_MIN_INSTANCES}）。"
                "用 findChild 取单实例正是 v2.1 漏修 4 个的成因，禁止退回。"
                f"实得文案={[b.text().strip() for b in btns]}")
        finally:
            pg.hide()
            pg.deleteLater()
            _pump(3)


# ---------------------------------------------------------------------------
# ② 逐实例：渲染字形色必须 = accent_text，且 accent 像素为 0（真回归守卫）
# ---------------------------------------------------------------------------
def test_each_memory_book_btn_renders_accent_text(qapp, isolated_env):
    for theme in THEMES:
        engine, pg = _build_page(theme)
        try:
            accent = engine.get_color("accent", "#000000")
            accent_text = engine.get_color("accent_text", "#000000")
            colors = {"accent": accent, "accent_text": accent_text,
                      "text": engine.get_color("text", "#000000")}
            btns = pg.findChildren(QPushButton, "memoryBookBtn")
            assert len(btns) >= _MIN_INSTANCES, f"{theme}: 实例数 {len(btns)} < {_MIN_INSTANCES}"

            for i, b in enumerate(btns):
                label = b.text().strip() or f"#{i}"
                # 底色：页面级 grab（按钮 background: transparent → 透出页面底）
                _reveal(pg, b)
                b.setAttribute(Qt.WA_UnderMouse, False)
                _pump(4)
                page_hist = _hist(pg.grab().toImage(), _rect_in(pg, b))
                assert page_hist, f"{theme}/{label}: 按钮矩形内无像素（几何={_rect_in(pg, b)}）"
                bg = page_hist.most_common(1)[0][0]
                # 字形色：控件自身 grab（权威渲染值，不受 Tab 是否激活影响）
                own_hist = _hist(b.grab().toImage(), (0, 0, b.width(), b.height()))
                px = _px(own_hist, colors)
                assert px["accent_text"] > 0, (
                    f"{theme}/{label}: 控件渲染像素里**没有** accent_text({accent_text}) → "
                    f"实际渲染色并非 accent_text。tokens={px} 底={bg} "
                    f"控件众数={own_hist.most_common(3)}")
                assert px["accent"] == 0, (
                    f"{theme}/{label}: 控件渲染像素里出现 accent({accent}) {px['accent']} 个 → "
                    f"文字仍取「填充用」色。tokens={px} 底={bg} 控件众数={own_hist.most_common(3)}")
                assert _ratio(accent_text, bg) >= _MIN_RATIO, (
                    f"{theme}/{label}: accent_text vs 实测底 {bg} = "
                    f"{_ratio(accent_text, bg)} < {_MIN_RATIO}")
        finally:
            pg.hide()
            pg.deleteLater()
            _pump(3)


# ---------------------------------------------------------------------------
# ③ 基线兜底：裸 #memoryBookBtn（无内联样式）也必须渲染 accent_text
# ---------------------------------------------------------------------------
def test_base_qss_baseline_memory_book_btn(qapp, isolated_env):
    """钉住 `base.qss` 的基线：新实例即使漏补内联色，也不该落回 accent。"""
    from gui.theme_engine import ThemeEngine
    for theme in THEMES:
        engine = ThemeEngine()
        engine.load_theme(theme)
        accent = engine.get_color("accent", "#000000")
        accent_text = engine.get_color("accent_text", "#000000")
        colors = {"accent": accent, "accent_text": accent_text}

        host = QWidget()
        host.resize(360, 80)
        host.setStyleSheet("QWidget { background: %s; }" % engine.get_color("bg", "#FFFFFF"))
        lay = QHBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        btn = QPushButton("导出 Markdown")
        btn.setObjectName("memoryBookBtn")
        btn.setFixedSize(160, 30)
        lay.addWidget(btn)
        host.show()
        _pump(10)
        try:
            assert btn.styleSheet() == "", "本用例要求裸按钮（只吃 base.qss），不得带内联样式"
            hist = _hist(host.grab().toImage(), _rect_in(host, btn))
            bg = hist.most_common(1)[0][0] if hist else "n/a"
            px = _px(hist, colors)
            assert px["accent_text"] > 0, (
                f"{theme}: 裸 #memoryBookBtn（走 base.qss）未渲染 accent_text({accent_text}) → "
                f"base.qss 基线已回归 accent。tokens={px} 底={bg} 众数={hist.most_common(3)}")
            assert px["accent"] == 0, (
                f"{theme}: 裸 #memoryBookBtn 渲染出 accent({accent}) {px['accent']} 个像素 → "
                f"base.qss 的文字色仍是 ${'{'}accent{'}'}。tokens={px} 底={bg}")
        finally:
            host.hide()
            host.deleteLater()
            _pump(3)


# ---------------------------------------------------------------------------
# ④ 按下态：`:pressed` **单独命中** 时也必须渲染 text（不得回落 accent_text）
# ---------------------------------------------------------------------------
def _draw_pressed_alone(btn, backdrop):
    """`QStyle::State_Sunken`（**不带** `State_MouseOver`）静态重绘，取「`:pressed` 单独命中」的渲染像素。

    取法说明（不谎称实测）：
      · offscreen 下真事件 `QTest.mousePress()` **也能**驱动 `:pressed`（实测裸控件得
        text=380 / accent_text=0），但它必然**同时**带上 `:hover`（鼠标就在控件上），
        而 `#memoryBookBtn:hover { color: text }` 会掩盖 `:pressed` 是否真被声明 ——
        即"真事件"验不出本条要验的东西。
      · 故改用 `drawControl(CE_PushButton)` + `State_Sunken`，语义精确等于
        "`:pressed` 单独命中"（键盘 Space 按下聚焦按钮即此态）。
      · 画布预填主题 `${bg}`：`background: transparent` 的实例（偏好 Tab 那个）透出真底。
    """
    from PySide6.QtWidgets import QStyle, QStyleOptionButton
    img = QImage(btn.size(), QImage.Format_ARGB32)
    img.fill(QColor(backdrop))
    painter = QPainter(img)
    opt = QStyleOptionButton()
    opt.rect = btn.rect()
    opt.text = btn.text()
    opt.icon = btn.icon()
    opt.iconSize = btn.iconSize()
    opt.state |= QStyle.State_Sunken | QStyle.State_Enabled
    QApplication.instance().style().drawControl(QStyle.CE_PushButton, opt, painter, btn)
    painter.end()
    return _hist(img, (0, 0, btn.width(), btn.height()))


def _assert_pressed_text(theme, label, hist, engine):
    bg = hist.most_common(1)[0][0] if hist else "n/a"
    colors = {"accent": engine.get_color("accent", "#000000"),
              "accent_text": engine.get_color("accent_text", "#000000"),
              "text": engine.get_color("text", "#000000")}
    px = _px(hist, colors)
    assert px["text"] > 0, (
        f"{theme}/{label}: `:pressed` 单独命中时未渲染 text({colors['text']}) → 该伪态没拿到 "
        f"`color: ${{text}}`，回落到常态 accent_text。tokens={px} 底={bg} 众数={hist.most_common(3)}")
    assert px["accent_text"] == 0, (
        f"{theme}/{label}: `:pressed` 单独命中时仍渲染 accent_text({colors['accent_text']}) "
        f"{px['accent_text']} 个像素，压在底 {bg} 上 = {_ratio(colors['accent_text'], bg)} < 4.5。"
        f"tokens={px} 众数={hist.most_common(3)}")
    assert px["accent"] == 0, (
        f"{theme}/{label}: `:pressed` 渲染出 accent({colors['accent']}) {px['accent']} 个像素")
    assert _ratio(colors["text"], bg) >= _MIN_RATIO, (
        f"{theme}/{label}: text vs 实测底 {bg} = {_ratio(colors['text'], bg)} < {_MIN_RATIO}")


def test_memory_book_btn_pressed_alone_renders_text(qapp, isolated_env):
    """5 个实例 + 裸控件，在 `:pressed` 单独命中下都必须渲染 `text`。

    缺陷：`base.qss` 的 `#secondaryBtn/#memoryBookBtn:pressed` 只换底 `${bg_light}` 不给
    `color` → 回落常态 `accent_text`，落 `${bg_light}` 上 4.125 / 4.397 / 5.335 / 4.280
    （三套浅色 < 4.5）。修法：base 补 `color: ${text}`，**并且**页面级实例的控件级样式表
    也必须补 —— 否则控件级常态 `color: accent_text` 会盖过 app 级 `:pressed`。
    """
    engine, pg = None, None
    for theme in THEMES:
        engine, pg = _build_page(theme)
        try:
            backdrop = engine.get_color("bg", "#FFFFFF")
            btns = pg.findChildren(QPushButton, "memoryBookBtn")
            assert len(btns) >= _MIN_INSTANCES, f"{theme}: 实例数 {len(btns)} < {_MIN_INSTANCES}"
            for i, b in enumerate(btns):
                label = b.text().strip() or f"#{i}"
                _assert_pressed_text(theme, label, _draw_pressed_alone(b, backdrop), engine)
        finally:
            pg.hide()
            pg.deleteLater()
            _pump(3)

    # 裸控件（只吃 base.qss，无内联）—— 钉 base.qss 基线本身
    from gui.theme_engine import ThemeEngine
    for theme in THEMES:
        engine = ThemeEngine()
        engine.load_theme(theme)
        backdrop = engine.get_color("bg", "#FFFFFF")
        host = QWidget()
        host.resize(360, 80)
        host.setStyleSheet("QWidget { background: %s; }" % engine.get_color("bg_light", "#FFFFFF"))
        lay = QHBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        btn = QPushButton("导出 Markdown")
        btn.setObjectName("memoryBookBtn")
        btn.setFixedSize(160, 30)
        lay.addWidget(btn)
        host.show()
        _pump(10)
        try:
            assert btn.styleSheet() == "", "本用例要求裸按钮（只吃 base.qss）"
            _assert_pressed_text(theme, "裸控件(base.qss)", _draw_pressed_alone(btn, backdrop), engine)
        finally:
            host.hide()
            host.deleteLater()
            _pump(3)
