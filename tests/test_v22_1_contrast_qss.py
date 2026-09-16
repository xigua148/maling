# -*- coding: utf-8 -*-
"""缺陷 A/B 对比度可达性修复的**渲染级**守卫（v2.2.1 收口）。

## 修了什么（只改 `gui/themes/ui_*.qss`，零色值改动）
缺陷 A（WCAG 1.4.11 非文本图形 ≥3:1）——输入框焦点圈取「填充/描边用」的
``${primary}``（≡ ``focus_accent``），四风格实测 vs 相邻面
**2.783 / 1.931 / 5.317 / 2.814**（三套浅色 <3:1）。改为「文字用」强调色
``${accent_text}``：四风格实测 **4.125 / 4.397 / 5.335 / 4.280**。
落点（每份主题 qss 各 4 处）：``ChatWindow QTextEdit#chatInput:focus`` /
``QTextEdit#chatInput:focus`` / ``QLineEdit:focus`` / ``QComboBox:focus``。

缺陷 B（选中态可辨性）——选中填充 = ``${primary}`` 时与相邻面同源退化
（cream 2.102、minimal 2.783~3.267）。修法：``accent`` 填充 + 1px
``accent_text`` 描边环。落点（每份各 4 处）：
``QTreeView#projectTreeView::item:selected`` / ``QComboBox QAbstractItemView::item:selected``
（**新增** 1px 环，padding 同步 −1px 保证尺寸零位移）、
``QCheckBox::indicator:checked`` / ``QTabBar::tab:selected``
（**就地换色**，边框宽度不变 → 零位移）。
其中 ``QComboBox QAbstractItemView::item:selected`` 在本 Qt 6.11.2 下**整条子控件规则
不被绘制**（实测弹层只吃到祖先规则与原生选中蓝），故本文件只担保其余 3 个落点。

## 为什么这种断言才拦得住
存量 2006 例里对焦点圈/选中态的断言若只读**样式表字符串**或 **setter 存值**，
「写对了但没上屏」拦不住（本项目已有 ``setTabTextColor`` 被 QSS 压制的前科）。
本文件一律取 **``grab()`` 出来的真实像素** 与 **真实布局几何**（``sizeHint`` / ``tabRect`` /
``visualRect`` 都是 Qt 真实计算值，不是 setter 存值）：
· 焦点态：``setFocus()`` + ``processEvents()`` 后取控件自身矩形内像素直方图；
· 选中态：真实 ``QTreeView`` / ``QTabBar`` / ``QCheckBox``。

## before 态怎么来的（不改产品代码、不依赖 git）
把**修前**那条规则按**同特异性、追加到 app 样式表末尾**（Qt 同特异性后写者胜，
见本仓 ``_verify_contrast/README_order_defect.md``）→ 得到与 v2.2.0 等价的渲染。
于是同一用例里同时拿到 before/after 的**渲染像素**与**几何**，
既证明「改后确实达标」，也证明「改前确实不达标」（守卫非空转）。

## 对抗性自检（已跑，6 项改坏→还原，见回传）
· 焦点环 ``${accent_text}`` 改回 ``${primary}`` → 焦点像素用例**变红**（accent_text=0）；
· 前提守卫：qss 锚点被改坏 → 锚点断言**变红**；
· ``QLineEdit:focus { border-color }`` 改成 ``border: 3px solid`` → 几何用例**变红**
  （fluid 宿主下 ``sizeHint`` 247x30 → 251x34；固定尺寸宿主则抓不到，故必须 fluid）；
· ``QTabBar::tab:selected`` 的 ``border`` 1px 改 3px → 几何用例**变红**
  （tabRect 高 28 → 30）；
· ``QTabBar::tab:hover`` 整块挪到 ``:selected`` 之后（同特异性后写者胜）→ 顺序守卫**变红**；
· 追加裸色值 ``QWidget { color: #FF00FF; }`` → 裸色断言**变红**。
· **抓不到的**（如实报告）：树项 ``::item:selected`` 的 ``padding: 3px 7px`` 在本 Qt 下
  与 ``4px 8px`` 渲染逐像素一致（padding 不进行高计算），故该 −1px 补偿无法被改红 ——
  它在本 Qt 下只是保险，几何零位移由行高规则本身保证。

不改产品代码；全 offscreen、零网络、零真实用户目录写入。

## ⑤ 追加：qss 侧「声明了 background 却未声明 color」的根因修复（同一文件，见文末）
按下组（7 个次级/幽灵按钮共用一块 ``:pressed``）与 ``ChatWindow QPushButton#chatSendBtn:disabled``
只声明背景、不声明字色 → 字色继承上层而漂移（按下态最差 **1.032**：ui_whale 深色的
``expandChatBtn:hover`` 把 accent 实底用的 ``text_on_accent`` 压在 ``bg_light`` 上；
禁用态最差 **1.214**：``#3A3A3A`` 上压暗色 ``text_on_accent``）。
修法沿用 ``:hover``/``:pressed`` 补 ``color`` 的同一先例：各补一行 ``color: ${text};``
（``text`` 在这两个底上四风格明暗实测 9.52~14.612）。零色值改动、零几何改动。
"""
from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402

from gui.qt_compat import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QImage, QLineEdit, QListWidget, QPlainTextEdit,
    QPoint, QPushButton, QTabBar, QTextEdit, QTreeView, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
QSS_FILES = tuple("themes/%s.qss" % t for t in THEMES)

#: WCAG 1.4.11 非文本图形下界。
_MIN_RATIO = 3.0
#: 判「像素里有没有这个色」的下界（1px 环在 240x32 控件上实测 ~540 px）。
_MIN_RING_PX = 40
_ISO = Path(tempfile.mkdtemp(prefix="maling_test_contrast_"))


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


@pytest.fixture(scope="module", autouse=True)
def _restore_default_theme(qapp, isolated_env):
    """模块跑完把 app 样式表复原成默认风格，避免污染后续测试文件。"""
    yield
    try:
        from gui.theme_engine import ThemeEngine
        ThemeEngine().load_theme(ThemeEngine.DEFAULT_THEME_ID)
        _pump(4)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _pump(n: int = 6) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


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
    tl = w.mapTo(container, QPoint(0, 0))
    return (tl.x(), tl.y(), w.width(), w.height())


def _hist(img, rect) -> Counter:
    """矩形内像素直方图（``constBits()`` 批量读；逐像素 ``pixelColor`` 慢一个量级）。"""
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
        cnt["#%02X%02X%02X" % (buf[i + 2], buf[i + 1], buf[i])] += 1
    return cnt


def _px(hist: Counter, colors) -> dict:
    return {k: hist.get(v.upper(), 0) for k, v in colors.items()}


def _dominant(hist: Counter) -> str:
    return hist.most_common(1)[0][0] if hist else ""


def _engine(theme: str):
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(4)
    return engine


def _before_overrides(engine) -> str:
    """v2.2.0 修前规则（同特异性、追加到末尾 → 后写者胜），用于取 before 渲染。

    注意：id 选择器（``QTreeView#projectTreeView:focus``）特异性高于类型选择器
    （``QTreeView:focus``），故 before 侧必须**逐条照抄修前的选择器**，否则压不住修后规则。
    """
    c = engine.get_color
    p = c("primary", "#000000")
    pd = c("primary_dark", "#000000")
    bd = c("border", "#000000")
    card = c("bg_card", "#FFFFFF")
    fa = c("focus_accent", p)
    return "\n".join((
        f"ChatWindow QTextEdit#chatInput:focus {{ border-color: {p}; background: {card}; }}",
        f"QTextEdit#chatInput:focus {{ border-color: {p}; }}",
        f"QLineEdit:focus {{ border-color: {p}; }}",
        f"QComboBox:focus {{ border-color: {p}; }}",
        # ⑤-1：base/主题 通用焦点环的 v2.2.0 形态（取 ${focus_accent}）。
        # 必须排在下面 :checked / :selected 之前 —— 真实合成是 base.qss 在前、主题 qss 在后，
        # 主题的 QCheckBox::indicator:checked 因此压过 base 的 ::indicator:focus；顺序反了会
        # 把「修前」渲染成错的（我们踩过：勾选框 before 值变成 0，用例假红）。
        f"QWidget#settingsSection QComboBox#settingsAnimationCombo:focus "
        f"{{ border-color: {fa}; }}",
        f"QCheckBox:focus, QCheckBox::indicator:focus {{ border-color: {fa}; }}",
        f"QListWidget:focus, QListView:focus, QTreeView:focus "
        f"{{ border: 1px solid {fa}; }}",
        f"QListWidget#sessionList:focus, QTreeView#projectTreeView:focus "
        f"{{ border: 1px solid {fa}; }}",
        f"QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {fa}; }}",
        f"QPushButton#copyCodeBtn:focus {{ border-color: {fa}; }}",
        # 非焦点态（v2.2.0 原样）
        f"QCheckBox::indicator:checked {{ border-color: {pd}; }}",
        f"QTabBar::tab:selected {{ border: 1px solid {bd}; }}",
        "QTreeView#projectTreeView::item:selected { border: none; padding: 4px 8px; }",
        "QComboBox QAbstractItemView::item:selected { border: none; padding: 5px 8px; }",
    ))


@contextlib.contextmanager
def _state(engine, *, before: bool):
    """切到 before（= v2.2.0 等价）或 after（= 修后）渲染态；退出时无条件复原。"""
    app = QApplication.instance()
    real = app.styleSheet()
    if before:
        app.setStyleSheet(real + "\n" + _before_overrides(engine))
    _pump(6)
    try:
        yield
    finally:
        app.setStyleSheet(real)
        _pump(6)


# ---------------------------------------------------------------------------
# 控件宿主
# ---------------------------------------------------------------------------
class ChatWindow(QWidget):
    """仅用于命中 QSS 的 ``ChatWindow QTextEdit#chatInput:focus`` 祖先选择器。

    产品类是 ``gui.widgets.chat_window.ChatWindow``；QSS 类型选择器按
    ``metaObject()->className()`` 匹配（含子类），故同名测试类等价命中。
    """


def _focus_host(theme, *, window_kind: bool = False, fluid: bool = False):
    """``fluid=True`` → 控件**不给固定尺寸**，由布局按 ``sizeHint`` 定尺寸。

    几何用例必须用 fluid：``setFixedSize`` 会把控件钉死，边框变宽也推不动它，
    断言就退化成空转（实测：固定尺寸下把环从 1px 改到 3px，控件尺寸纹丝不动，
    只有 ``sizeHint`` 变了）。
    """
    engine = _engine(theme)
    host = ChatWindow() if window_kind else QWidget()
    host.resize(420 if window_kind else 560, 160 if window_kind else 340)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(18, 18, 18, 18)
    lay.setSpacing(12)
    widgets = {}
    if window_kind:
        te = QTextEdit()
        te.setObjectName("chatInput")
        if not fluid:
            te.setFixedSize(300, 48)
        lay.addWidget(te)
        widgets["chatwindow_chatinput"] = te
    else:
        le = QLineEdit()
        le.setObjectName("probeLineEdit")
        cb = QComboBox()
        cb.setObjectName("probeCombo")
        cb.addItems(["one", "two"])
        te = QTextEdit()
        te.setObjectName("chatInput")
        if not fluid:
            le.setFixedSize(240, 32)
            cb.setFixedSize(240, 32)
            te.setFixedSize(240, 44)
        for k, w in (("lineedit", le), ("combobox", cb), ("chatinput", te)):
            lay.addWidget(w)
            widgets[k] = w
    if fluid:
        lay.addStretch(1)
    host.show()
    _pump(10)
    return engine, host, widgets


# ---------------------------------------------------------------------------
# 前提守卫：令牌必须分家 + qss 锚点必须在位 + 无裸色（否则下面全是空转）
# ---------------------------------------------------------------------------
_FOCUS_ANCHORS = (
    "ChatWindow QTextEdit#chatInput:focus {\n    border-color: ${accent_text};\n",
    "QTextEdit#chatInput:focus {\n    border-color: ${accent_text};\n}",
    "QLineEdit:focus {\n    border-color: ${accent_text};\n}",
    "QComboBox:focus {\n    border-color: ${accent_text};\n}",
)
_SELECT_ANCHORS = (
    "QTreeView#projectTreeView::item:selected {\n"
    "    background-color: ${primary};\n"
    "    color: ${text_on_accent};\n"
    "    border: 1px solid ${accent_text};\n"
    "    padding: 3px 7px;\n}",
    "QComboBox QAbstractItemView::item:selected {\n"
    "    background-color: ${primary};\n"
    "    color: ${text_on_accent};\n"
    "    border: 1px solid ${accent_text};\n"
    "    padding: 4px 7px;\n}",
    "QCheckBox::indicator:checked {\n"
    "    background-color: ${primary};\n"
    "    border-color: ${accent_text};\n}",
    "QTabBar::tab:selected {\n"
    "    background-color: ${bg_card};\n"
    "    color: ${text};\n"
    "    border: 1px solid ${accent_text};\n"
    "    border-bottom: 2px solid ${primary};\n"
    "    margin-bottom: -1px;\n}",
)


def test_precondition_tokens_and_qss_anchors(qapp, isolated_env):
    from gui.theme_engine import ThemeEngine
    for theme in THEMES:
        engine = ThemeEngine()
        engine.load_theme(theme)
        primary = engine.get_color("primary", "").upper()
        accent_text = engine.get_color("accent_text", "").upper()
        assert primary and accent_text
        assert primary != accent_text, (
            f"{theme}: primary({primary}) == accent_text({accent_text})，"
            "本文件的像素判别断言会退化为空转")
        assert accent_text != engine.get_color("primary_dark", "").upper()

    for rel in QSS_FILES:
        qss = (ROOT / "gui" / rel).read_text(encoding="utf-8")
        for anchor in _FOCUS_ANCHORS + _SELECT_ANCHORS:
            assert anchor in qss, f"{rel}: 缺失修后锚点\n---\n{anchor}\n---"
        # 禁止裸色值：剥掉注释后不得残留 #RRGGBB 形态的硬编码色
        body = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)
        found = re.findall(r"(?<![\w#])#[0-9A-Fa-f]{6}\b", body)
        assert not found, f"{rel}: 出现裸色值 {found[:5]} —— 新增颜色必须走 ${{token}}"


# ---------------------------------------------------------------------------
# 缺陷 A：焦点圈渲染级守卫（4 主题 × 4 落点）
# ---------------------------------------------------------------------------
FOCUS_KINDS = ("lineedit", "combobox", "chatinput", "chatwindow_chatinput")


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("kind", FOCUS_KINDS)
def test_focus_ring_renders_accent_text(qapp, isolated_env, theme, kind):
    engine, host, widgets = _focus_host(theme, window_kind=(kind == "chatwindow_chatinput"))
    w = widgets[kind]
    accent_text = engine.get_color("accent_text", "").upper()
    primary = engine.get_color("primary", "").upper()
    tokens = {"accent_text": accent_text, "primary": primary}
    rect = _rect_in(host, w)

    w.setFocus()
    _pump(6)
    assert w.hasFocus(), f"{theme}/{kind}: 控件未拿到焦点，本用例无意义"

    with _state(engine, before=True):
        w.setFocus()
        _pump(6)
        before = _hist(host.grab().toImage(), rect)
    with _state(engine, before=False):
        w.setFocus()
        _pump(6)
        after = _hist(host.grab().toImage(), rect)

    assert before and after, f"{theme}/{kind}: 直方图为空（几何={rect}）"
    pxb, pxa = _px(before, tokens), _px(after, tokens)

    assert pxb["primary"] > 0 and pxb["accent_text"] == 0, (
        f"{theme}/{kind}: before 态焦点环不是 primary → 本用例对「修前」失去判别力。"
        f"before={pxb} 众数={before.most_common(4)}")
    assert pxa["accent_text"] >= _MIN_RING_PX, (
        f"{theme}/{kind}: 焦点态**没有**渲染 accent_text({accent_text}) → 焦点环未按修法上屏。"
        f"after={pxa} 众数={after.most_common(4)}")
    assert pxa["primary"] == 0, (
        f"{theme}/{kind}: 焦点态仍渲染 primary({primary}) {pxa['primary']} 个像素 → "
        f"焦点圈仍取「填充用」色。after={pxa} 众数={after.most_common(4)}")

    inside = _dominant(after)
    outer = _dominant(_hist(host.grab().toImage(), (0, 0, host.width(), host.height())))
    for label, adj in (("控件内底", inside), ("宿主底", outer)):
        if not adj or adj == accent_text:
            continue
        r = _ratio(accent_text, adj)
        assert r >= _MIN_RATIO, (
            f"{theme}/{kind}: accent_text({accent_text}) vs {label}({adj}) = {r} < {_MIN_RATIO}")


def _geo(host, w):
    """布局生效后的控件几何 (x, y, w, h, sizeHint.w, sizeHint.h)。"""
    lay = host.layout()
    if lay is not None:
        lay.activate()
    _pump(2)
    sh = w.sizeHint()
    return (w.x(), w.y(), w.width(), w.height(), sh.width(), sh.height())


@pytest.mark.parametrize("theme", THEMES)
def test_focus_ring_geometry_unchanged(qapp, isolated_env, theme):
    """焦点圈变化不得改变控件几何（只换 border-color，padding / border-width 不动）。

    取 fluid（布局驱动、非固定尺寸）宿主，断言聚焦前后
    ``x / y / 宽 / 高 / sizeHint`` 逐项不变。
    实测把 ``border-color`` 改成 ``border: 3px solid``（对抗性改坏）→
    ``sizeHint`` 立刻 +4px → 本用例变红，守卫非空转。
    """
    for window_kind, kinds in ((False, ("lineedit", "combobox", "chatinput")),
                               (True, ("chatwindow_chatinput",))):
        engine, host, widgets = _focus_host(theme, window_kind=window_kind, fluid=True)
        for kind in kinds:
            w = widgets[kind]
            w.clearFocus()
            _pump(4)
            unfocused = _geo(host, w)
            w.setFocus()
            _pump(6)
            assert w.hasFocus(), f"{theme}/{kind}: 控件未拿到焦点，本用例无意义"
            focused = _geo(host, w)
            assert focused == unfocused, (
                f"{theme}/{kind}: 聚焦前后几何变化（x, y, w, h, hint.w, hint.h）"
                f"{unfocused} → {focused}")


# ---------------------------------------------------------------------------
# 缺陷 B：选中态渲染级守卫（4 主题 × 4 落点）
# ---------------------------------------------------------------------------
SELECT_KINDS = ("tree_item", "tab", "checkbox")


class _Probe:
    """一个选中态探针：给出「取像素的控件」与「选中/相邻矩形」。"""

    __slots__ = ("engine", "host", "grabber", "rects")

    def __init__(self, engine, host, grabber, rects):
        self.engine = engine
        self.host = host
        self.grabber = grabber          # 取像素的控件（弹层视图 != 宿主）
        self.rects = rects              # (选中矩形, 相邻矩形 | None)

    def ring_hist(self) -> Counter:
        r = self.rects[0]
        return _hist(self.grabber.grab().toImage(), (r.x(), r.y(), r.width(), r.height()))

    def adjacent_color(self) -> str:
        adj = self.rects[1]
        if adj is not None and adj.width() > 0 and adj.height() > 0:
            h = _hist(self.grabber.grab().toImage(),
                      (adj.x(), adj.y(), adj.width(), adj.height()))
        else:
            h = _hist(self.grabber.grab().toImage(),
                      (0, 0, self.grabber.width(), self.grabber.height()))
        return _dominant(h)


def _tree_host(theme):
    engine = _engine(theme)
    host = QWidget()
    host.resize(380, 240)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(16, 16, 16, 16)
    view = QTreeView()
    view.setObjectName("projectTreeView")
    model = QStandardItemModel()
    for r in range(3):
        model.appendRow([QStandardItem("row%d" % r)])
    view.setModel(model)
    view.setUniformRowHeights(False)
    lay.addWidget(view)
    host.show()
    _pump(10)
    view.selectionModel().setCurrentIndex(
        model.index(0, 0), QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    view.setFocus()
    _pump(8)
    return engine, host, view, model


def _tab_host(theme, current: int = 0):
    engine = _engine(theme)
    host = QWidget()
    host.resize(360, 140)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(16, 16, 16, 16)
    tb = QTabBar()
    tb.setObjectName("probeTabBar")
    tb.addTab("tab-a")
    tb.addTab("tab-b")
    tb.setCurrentIndex(current)
    lay.addWidget(tb)
    lay.addStretch(1)
    host.show()
    _pump(10)
    return engine, host, tb


def _checkbox_host(theme):
    """选中 / 未选中各一个复选框 —— 几何用例要「选中 vs 未选中」同尺寸。

    两者**文字必须一致**，否则 sizeHint 宽度差会被误判成「选中态位移」。
    """
    engine = _engine(theme)
    host = QWidget()
    host.resize(300, 140)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(16, 16, 16, 16)
    on = QCheckBox("enable")
    on.setObjectName("probeCheckOn")
    on.setChecked(True)
    off = QCheckBox("enable")
    off.setObjectName("probeCheckOff")
    lay.addWidget(on)
    lay.addWidget(off)
    lay.addStretch(1)
    host.show()
    _pump(10)
    return engine, host, on, off


def _selected_probe(theme, kind) -> _Probe:
    """``grabber`` 与 ``rects`` **必须同一坐标系**：

    ``QAbstractItemView.visualRect()`` 返回的是 **viewport 坐标**（实测 viewport 落在
    widget 的 (5,23)），若拿它去 ``view.grab()`` 上取像素会整体错位、把「环已上屏」
    误判成「环未上屏」。故此处一律 grab viewport / 控件自身，与 rects 同系。
    """
    if kind == "tree_item":
        engine, host, view, model = _tree_host(theme)
        return _Probe(engine, host, view.viewport(),
                      (view.visualRect(model.index(0, 0)),
                       view.visualRect(model.index(1, 0))))

    # 注：``QComboBox QAbstractItemView::item(:selected)`` 曾作为第 4 个探针，实测在
    # Qt 6.11.2 下 **该子控件规则根本不被绘制**（弹层视图只吃到祖先
    # ``QComboBox QAbstractItemView { background-color }`` 与原生选中蓝 #308CC6，
    # 换 delegate 静态重绘也画不出 token 色）→ 该处无像素可断言，故不再列入 SELECT_KINDS。
    # 对应 qss 规则仍按修法保留（其它 Qt 版本/真实平台可能生效），只是本文件不为其担保。

    if kind == "tab":
        engine, host, tb = _tab_host(theme)
        return _Probe(engine, host, tb, (tb.tabRect(0), tb.tabRect(1)))

    if kind == "checkbox":
        engine, host, on, _off = _checkbox_host(theme)
        return _Probe(engine, host, on, (on.rect(), None))

    raise AssertionError(kind)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("kind", SELECT_KINDS)
def test_selected_ring_renders_accent_text(qapp, isolated_env, theme, kind):
    probe = _selected_probe(theme, kind)
    rect = probe.rects[0]
    assert rect.width() > 0 and rect.height() > 0, (
        f"{theme}/{kind}: 选中矩形为空 {rect}（布局不可达，本用例无意义）")

    engine = probe.engine
    accent_text = engine.get_color("accent_text", "").upper()
    primary = engine.get_color("primary", "").upper()
    wrong = engine.get_color("primary_dark" if kind == "checkbox" else "border", "#000").upper()
    tokens = {"accent_text": accent_text, "primary": primary, "wrong": wrong}

    with _state(engine, before=True):
        before = probe.ring_hist()
    after = probe.ring_hist()

    assert before, f"{theme}/{kind}: before 直方图为空"
    pxb, pxa = _px(before, tokens), _px(after, tokens)
    assert pxb["accent_text"] == 0, (
        f"{theme}/{kind}: before 态已出现 accent_text → 本用例对「修前」失去判别力。before={pxb}")
    assert pxa["accent_text"] >= _MIN_RING_PX, (
        f"{theme}/{kind}: 选中项**没有**渲染 accent_text({accent_text}) → 描边环未上屏。"
        f"after={pxa} 众数={after.most_common(4)}")
    # 填充仍必须是 primary（换的只是环，不是选中底）；页签的选中底本就是 bg_card
    if kind != "tab":
        assert pxa["primary"] >= _MIN_RING_PX, (
            f"{theme}/{kind}: 选中项填充不再是 primary → 修法把「accent 填充」改掉了。after={pxa}")
    if kind == "checkbox":
        # 该处是「就地换色」，旧环色必须彻底消失
        assert pxa["wrong"] == 0 and pxb["wrong"] > 0, (
            f"{theme}/{kind}: 复选框选中环未换成 accent_text（旧 primary_dark 仍在 "
            f"{pxa['wrong']} 个像素 / before {pxb['wrong']} 个）")

    adj = probe.adjacent_color()
    r = _ratio(accent_text, adj)
    assert r >= _MIN_RATIO, (
        f"{theme}/{kind}: 选中环 accent_text({accent_text}) vs 相邻面({adj}) = {r} < {_MIN_RATIO}")


@pytest.mark.parametrize("theme", THEMES)
def test_selected_geometry_zero_shift(qapp, isolated_env, theme):
    """选中态加环不得改变几何：选中 / 未选中 / 修前(v2.2.0 等价) 三态必须同尺寸。

    实测（Qt 6.11.2）各落点对「环」的几何敏感度不同，如实记录：

    · **页签** ``QTabBar::tab`` 的 ``border`` 宽度直接进 tabRect 尺寸
      → 1px→3px 时 tabRect 高度 28→30，**守卫有效**（见对抗性自检）；
    · **复选框** ``::indicator`` 有显式 ``width/height: 18px``，环画在内部
      → 尺寸天然不动（改 3px 环也不动），本用例只能证明「选中≠未选中」；
    · **树项** ``::item`` 的 ``padding`` / ``border`` **不参与**行高计算
      （行高由 ``::item`` 基规则 + delegate sizeHint 决定）→ 实测
      ``padding: 3px 7px`` 与 ``padding: 4px 8px`` 渲染结果**逐像素完全一致**。
      故该项的 −1px padding 补偿在本 Qt 下是**无害的保险**，无法被改红。
    """
    # --- 页签：选中 / 未选中 / 修前 ---
    engine, host, tb = _tab_host(theme)
    tb.setCurrentIndex(0)
    _pump(6)
    sel = (tb.tabRect(0).width(), tb.tabRect(0).height())
    bar_sel = tb.height()
    tb.setCurrentIndex(1)
    _pump(6)
    unsel = (tb.tabRect(0).width(), tb.tabRect(0).height())
    bar_unsel = tb.height()
    assert sel == unsel, (
        f"{theme}/tab: 选中页签 {sel} ≠ 未选中页签 {unsel} —— 选中态出现尺寸位移")
    assert bar_sel == bar_unsel, (
        f"{theme}/tab: 切换选中改变了 QTabBar 高度 {bar_sel} → {bar_unsel}")
    with _state(engine, before=True):
        tb.setCurrentIndex(0)
        _pump(6)
        sel_before = (tb.tabRect(0).width(), tb.tabRect(0).height())
    assert sel == sel_before, (
        f"{theme}/tab: 选中页签相对 v2.2.0 位移 {sel_before} → {sel}")

    # --- 复选框：选中 vs 未选中（同一宿主内两个控件）---
    engine, host, on, off = _checkbox_host(theme)
    geo_on = (on.width(), on.height(), on.sizeHint().width(), on.sizeHint().height())
    geo_off = (off.width(), off.height(), off.sizeHint().width(), off.sizeHint().height())
    assert geo_on == geo_off, (
        f"{theme}/checkbox: 选中 {geo_on} ≠ 未选中 {geo_off}（w, h, hint.w, hint.h）")
    with _state(engine, before=True):
        _pump(6)
        geo_before = (on.width(), on.height(), on.sizeHint().width(), on.sizeHint().height())
    assert geo_on == geo_before, (
        f"{theme}/checkbox: 相对 v2.2.0 位移 {geo_before} → {geo_on}")

    # --- 树项：选中行 vs 未选中行 vs 修前 ---
    engine, host, view, model = _tree_host(theme)
    r0 = view.visualRect(model.index(0, 0))
    r1 = view.visualRect(model.index(1, 0))
    size0 = (r0.width(), r0.height())
    assert size0 == (r1.width(), r1.height()), (
        f"{theme}/tree_item: 选中行 {size0[0]}x{size0[1]} ≠ 未选中行 "
        f"{r1.width()}x{r1.height()} —— 选中/未选中出现尺寸位移")
    with _state(engine, before=True):
        _pump(6)
        rb = view.visualRect(model.index(0, 0))
    assert size0 == (rb.width(), rb.height()), (
        f"{theme}/tree_item: 选中行相对 v2.2.0 位移 {rb.width()}x{rb.height()} → "
        f"{size0[0]}x{size0[1]}")


# ---------------------------------------------------------------------------
# 顺序守卫：同特异性下 :hover 必须排在 :selected 之前
# ---------------------------------------------------------------------------
_HOVER_SELECT_PAIRS = (
    "QTreeView#projectTreeView::item",
    "QComboBox QAbstractItemView::item",
    "QTabBar::tab",
    "SidebarWidget QListWidget::item",
    "QListWidget#sessionList::item",
)


def test_hover_rules_precede_selected_rules(qapp, isolated_env):
    """Qt QSS 同特异性下后写者胜 —— ``:hover`` 若写在 ``:selected`` 之后会抹掉选中态。"""
    for rel in QSS_FILES:
        qss = (ROOT / "gui" / rel).read_text(encoding="utf-8")
        for base in _HOVER_SELECT_PAIRS:
            i_h = qss.find(base + ":hover")
            i_s = qss.find(base + ":selected")
            assert i_h >= 0 and i_s >= 0, f"{rel}: 选择器 {base} 的 :hover / :selected 未成对出现"
            assert i_h < i_s, (
                f"{rel}: `{base}:hover`(偏移 {i_h}) 排在 `{base}:selected`(偏移 {i_s}) 之后"
                " —— 同特异性后写者胜，选中态会被 hover 抹掉")


# ---------------------------------------------------------------------------
# ⑤-1：base.qss / 主题 qss 的「通用焦点环」——静态 + 渲染级双守卫
#
# v2.2.0 这些环取 ${focus_accent}（≡ primary）；浅色三套压在页面/卡片底色上实测
# 仅 1.931 ~ 2.814（<3:1，WCAG 1.4.11 非文本图形不达标）→ 统一改取 ${accent_text}。
# 注意范围：**只有 :focus 规则的声明体**改成 accent_text；
# :hover / :pressed / qlineargradient 的 stop 仍用 ${focus_accent}（另一类，不在本守卫判据内）。
# ---------------------------------------------------------------------------
RING_FILES = ("themes/base.qss",) + QSS_FILES

_RING_ANCHORS = {
    "themes/base.qss": (
        "QWidget#settingsSection QComboBox#settingsThemeCombo:focus,\n"
        "QWidget#settingsSection QComboBox#settingsAppearanceCombo:focus,\n"
        "QWidget#settingsSection QComboBox#settingsFontCombo:focus,\n"
        "QWidget#settingsSection QComboBox#settingsAnimationCombo:focus {\n"
        "    border-color: ${accent_text};\n}",
        "QCheckBox:focus,\nQCheckBox::indicator:focus {\n"
        "    border-color: ${accent_text};\n}",
        "QListWidget:focus,\nQListView:focus,\nQTreeView:focus {\n"
        "    border: 1px solid ${accent_text};\n}",
        "QListWidget#sessionList:focus,\nQTreeView#projectTreeView:focus {\n"
        "    border: 1px solid ${accent_text};\n}",
        "QTextEdit:focus,\nQPlainTextEdit:focus {\n"
        "    border: 1px solid ${accent_text};\n}",
    ),
    "themes/ui_whale.qss": (
        # v2.2.1 二轮订正：本段原为**全仓唯一**没走 `[keyboardNav="true"]` 门控的
        # :focus 规则（用户第 3 条原话「这个项目所有类似选定黑框的都可以不用存在」）。
        # 实测鼠标点击即 hasFocus()==True → 帧差 732~758 px、新色 #247A8F
        # （#expandChatBtn 落底仅 1.52:1，最扎眼）。现按 base.qss §5 / §9b 的同一口径
        # 加属性门控，**颜色 / 宽度 / 版式一字未动**，故此处的环令牌仍是 ${accent_text}。
        "QPushButton#quickBtn[keyboardNav=\"true\"]:focus,\n"
        "QPushButton#expandChatBtn[keyboardNav=\"true\"]:focus,\n"
        "QPushButton#quickReplyBtn[keyboardNav=\"true\"]:focus,\n"
        "QPushButton#quickActionBtn[keyboardNav=\"true\"]:focus,\n"
        "QPushButton#copyBtn[keyboardNav=\"true\"]:focus,\n"
        "QPushButton#copyCodeBtn[keyboardNav=\"true\"]:focus {\n"
        "    border-color: ${accent_text};\n}",
    ),
}

#: 二轮订正的反向守卫：ui_whale 那 6 个按钮的 `:focus` **不得**再出现无门控形态
#: （无门控 = 鼠标点一下也上环 = 用户点名的「选定黑框」）。
_WHALE_UNGATED_FOCUS_IDS = ("quickBtn", "expandChatBtn", "quickReplyBtn",
                            "quickActionBtn", "copyBtn", "copyCodeBtn")

#: **证伪记录 / 反向守卫**：代码编辑器底色是**深色**（浅色主题下也是 #2B2B33），
#: 该处**必须保留** ``${focus_accent}``。实测把这条也换成 ``${accent_text}``（压在浅底上的
#: 文字用暗色）后，比值从 4.296 / 6.49 / 4.326 掉到 2.898 / 2.85 / 2.844 → **反而破线**。
#: 即：焦点环取哪个令牌要**看它压在什么底上**，不能整类一刀切换键。
_CE_KEEP = ("QPlainTextEdit#codeEditorArea:focus {\n"
            "    border: 1px solid ${focus_accent};\n}")


def _focus_rule_decls(qss: str):
    """剥注释后产出「选择器含 :focus」的 (选择器, 声明体)。

    ``${...}`` 里的花括号必须先中和，否则 ``[^{}]*`` 会在 ``$`` 处断掉。
    中和顺序要在剥注释之后仍保留 ``@FA@`` 标记 —— 故先标 ``@FA@`` 再剥注释，
    于是**注释里**提到的 ``${focus_accent}`` 随注释一起消失，不会误报。
    """
    body = qss.replace("${focus_accent}", "@FA@")
    body = re.sub(r"\$\{[^}]*\}", "@TOKEN@", body)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", body)
            if ":focus" in m.group(1)]


def test_no_focus_rule_uses_focus_accent(qapp, isolated_env):
    """⑤-1 静态守卫：``:focus`` 规则的声明体里不得再有 ``${focus_accent}``。

    唯一豁免见 ``_CE_KEEP``：``QPlainTextEdit#codeEditorArea:focus`` 的底色是深色，
    取 ``${focus_accent}`` 才达标（改 ``${accent_text}`` 实测反而 <3:1）。
    豁免名单**写死且只此一条**，新增违规仍会被拦下。
    """
    allowed = {"QPlainTextEdit#codeEditorArea:focus"}
    for rel in RING_FILES:
        qss = (ROOT / "gui" / rel).read_text(encoding="utf-8")
        rules = _focus_rule_decls(qss)
        assert rules, f"{rel}: 未解析到任何 :focus 规则（解析器失效，本守卫会空转）"
        bad = [sel for sel, decl in rules if "@FA@" in decl and sel not in allowed]
        assert not bad, (
            f"{rel}: 仍有 :focus 规则取 ${{focus_accent}}（非文本图形浅色 <3:1）-> {bad}")


def test_generic_ring_anchors_in_place(qapp, isolated_env):
    """静态：通用焦点环的修后锚点必须在位（否则渲染用例会因「规则不存在」而误判）。"""
    for rel, anchors in _RING_ANCHORS.items():
        qss = (ROOT / "gui" / rel).read_text(encoding="utf-8")
        for a in anchors:
            assert a in qss, f"{rel}: 缺失通用焦点环锚点\n---\n{a}\n---"


def test_whale_button_focus_ring_is_keyboard_gated(qapp, isolated_env):
    """二轮反向守卫：ui_whale 那 6 个按钮不得退回「鼠标点一下就上环」的无门控形态。

    判据取「选择器含该 id、含 :focus、且不含 keyboardNav」——只看形态，不看颜色，
    与 base.qss §5 / §9b 同一口径（用户诉求是「所有类似选定黑框都不要」，与颜色无关）。
    """
    qss = (ROOT / "gui" / "themes" / "ui_whale.qss").read_text(encoding="utf-8")
    bad = [sel for sel, _decl in _focus_rule_decls(qss)
           if ":focus" in sel and "keyboardNav" not in sel
           and any(f"#{oid}" in sel for oid in _WHALE_UNGATED_FOCUS_IDS)]
    assert not bad, (
        "ui_whale: 以下 :focus 规则已退回无门控形态 —— 鼠标点击就会贴出选定框，"
        f"与用户「所有类似选定黑框都不要」相悖：{bad}")
    gated = [sel for sel, _decl in _focus_rule_decls(qss) if "keyboardNav" in sel]
    assert gated, (
        "ui_whale: 一个 keyboardNav 门控的 :focus 规则都没有 —— 键盘可达性被整段删掉了"
        "（本订正只允许「加属性门控」，不允许「删规则」）")


RING_KINDS = ("settings_combo", "checkbox", "treeview", "treeview_project",
              "listwidget", "plaintextedit", "textedit", "copy_code_btn")
#: ``#copyCodeBtn`` 只在 ui_whale 写了焦点规则；其余三套该控件落基类规则，无从断言
_RING_KIND_ONLY = {"copy_code_btn": ("ui_whale",)}


def _ring_host(theme):
    engine = _engine(theme)
    host = QWidget()
    host.resize(420, 720)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(20, 20, 20, 20)
    lay.setSpacing(10)
    ws = {}

    sec = QWidget()
    sec.setObjectName("settingsSection")
    sl = QVBoxLayout(sec)
    sl.setContentsMargins(0, 0, 0, 0)
    sc = QComboBox()
    sc.setObjectName("settingsAnimationCombo")
    sc.addItems(["off", "on"])
    sc.setFixedHeight(32)
    sl.addWidget(sc)
    ws["settings_combo"] = sc
    lay.addWidget(sec)

    chk = QCheckBox("x")
    chk.setFixedHeight(24)
    lay.addWidget(chk)
    ws["checkbox"] = chk

    tv = QTreeView()
    tv.setFixedHeight(56)
    lay.addWidget(tv)
    ws["treeview"] = tv

    tvp = QTreeView()
    tvp.setObjectName("projectTreeView")
    tvp.setFixedHeight(56)
    lay.addWidget(tvp)
    ws["treeview_project"] = tvp

    lw = QListWidget()
    lw.setFixedHeight(56)
    lay.addWidget(lw)
    ws["listwidget"] = lw

    pte = QPlainTextEdit()
    pte.setFixedHeight(56)
    lay.addWidget(pte)
    ws["plaintextedit"] = pte

    te = QTextEdit()
    te.setFixedHeight(56)
    lay.addWidget(te)
    ws["textedit"] = te

    ce = QPlainTextEdit()
    ce.setObjectName("codeEditorArea")
    ce.setFixedHeight(56)
    lay.addWidget(ce)
    ws["code_editor"] = ce

    pb = QPushButton("")
    pb.setObjectName("copyCodeBtn")
    pb.setFixedHeight(30)
    lay.addWidget(pb)
    ws["copy_code_btn"] = pb

    lay.addStretch(1)
    host.show()
    _pump(12)
    return engine, host, ws


def _ring_probe(w, kind, *, kbd_nav: bool = False) -> Counter:
    """取「聚焦态」像素直方图。

    ``kbd_nav=True`` 时先按**产品口径**把控件标成键盘导航焦点
    （``keyboardNav="true"`` 动态属性 + unpolish/polish，即 ``MainWindow.eventFilter``
    在 Tab/Shift+Tab/助记键路径上做的事），再 ``setFocus()``。

    ⚠ 为什么两态取法不同（而不是「顺手都加上属性」）：
      · **before（v2.2.0 等价态）**：当时的 :focus 规则**无门控** —— 鼠标点一下或程序性
        焦点都会上环。故 before 侧**不设**该属性才是对 v2.2.0 的忠实模拟；
      · **after（v2.2.1）**：通用焦点环已按「焦点来源」分流
        （``base.qss`` §5；``ui_whale.qss`` 那 6 个按钮同口径），QPushButton 的环
        **只在键盘导航时**出现。若 after 侧仍用程序性焦点取，会取不到环 ——
        那不是「环没了」，是**探针没走键盘路径**。
      · 两态断言彼此独立（before：focus_accent 在 / accent_text 不在；
        after：accent_text 在 / focus_accent 不在），不做 before↔after 的直接对比，
        故不构成「改了条件的 before 拿去比 after」的弱化。
    """
    if kbd_nav:
        w.setProperty("keyboardNav", "true")
        w.style().unpolish(w)
        w.style().polish(w)
    w.setFocus()
    _pump(6)
    assert w.hasFocus(), f"{kind}: 控件未拿到焦点，本用例无意义"
    if kbd_nav:
        assert w.property("keyboardNav") == "true", (
            f"{kind}: keyboardNav 属性没打上（unpolish/polish 失效）→ 本用例会假红")
    return _hist(w.grab().toImage(), (0, 0, w.width(), w.height()))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("kind", RING_KINDS)
def test_generic_ring_renders_accent_text(qapp, isolated_env, theme, kind):
    only = _RING_KIND_ONLY.get(kind)
    if only and theme not in only:
        pytest.skip(f"{kind} 仅在 {'/'.join(only)} 有焦点规则")

    engine, host, ws = _ring_host(theme)
    w = ws[kind]
    accent_text = engine.get_color("accent_text", "").upper()
    focus_accent = engine.get_color("focus_accent", "").upper()
    tokens = {"accent_text": accent_text, "focus_accent": focus_accent}

    with _state(engine, before=True):
        before = _ring_probe(w, kind)
    after = _ring_probe(w, kind, kbd_nav=True)

    assert before and after, f"{theme}/{kind}: 直方图为空（几何 {w.width()}x{w.height()}）"
    pxb, pxa = _px(before, tokens), _px(after, tokens)
    assert pxb["focus_accent"] > 0 and pxb["accent_text"] == 0, (
        f"{theme}/{kind}: before 态焦点环不是 focus_accent → 本条对「修前」失去判别力。"
        f"before={pxb} 众数={before.most_common(4)}")
    assert pxa["accent_text"] >= _MIN_RING_PX, (
        f"{theme}/{kind}: 聚焦后**没有**渲染 accent_text({accent_text}) → 通用焦点环未上屏。"
        f"after={pxa} 众数={after.most_common(4)}")
    # 判据用「不足一条环」而非「必须为 0」：四风格里 focus_accent ≡ primary，控件上
    # 可能本就有零星 primary 像素（下拉箭头 / 抗锯齿），真环则是数百像素量级。
    assert pxa["focus_accent"] < _MIN_RING_PX, (
        f"{theme}/{kind}: 聚焦后仍渲染 focus_accent({focus_accent}) {pxa['focus_accent']} px"
        f"（≥ 环判据 {_MIN_RING_PX}）→ 该处 :focus 没换成 accent_text。after={pxa}")

    # 相邻面取**宿主底**：环画在控件边框上，紧邻的是宿主页面底。
    # （不用控件自身 grab 的众数 —— 无底色控件 grab 出来是纯黑，会把低对比度伪装成高对比度。）
    adj = _dominant(_hist(host.grab().toImage(), (0, 0, host.width(), host.height())))
    if adj and adj != accent_text:
        r = _ratio(accent_text, adj)
        assert r >= _MIN_RATIO, (
            f"{theme}/{kind}: 焦点环 accent_text({accent_text}) vs 宿主底({adj}) = {r} "
            f"< {_MIN_RATIO}")


@pytest.mark.parametrize("theme", THEMES)
def test_code_editor_keeps_focus_accent_and_stays_legible(qapp, isolated_env, theme):
    """**证伪记录的反向守卫**：代码编辑器焦点环必须保留 ``${focus_accent}``，且 ≥3:1。

    该编辑器底色是深色（浅色主题下实测也是 ``#2B2B33``）：``focus_accent`` 相对它
    4.296 / 6.49 / 4.326（≥3，本来就达标），换成「压在浅底上的文字用」暗色
    ``accent_text`` 后掉到 2.898 / 2.85 / 2.844 → 反而破线。
    本用例同时锁死「文件里是 focus_accent」与「上屏确实是 focus_accent 且对比度达标」。
    """
    for rel in QSS_FILES:
        qss = (ROOT / "gui" / rel).read_text(encoding="utf-8")
        assert _CE_KEEP in qss, (
            f"{rel}: 代码编辑器焦点环不再是 ${{focus_accent}} —— 该处底色为深色，"
            "换成 accent_text 会掉到 <3:1")
        assert _CE_KEEP.replace("${focus_accent}", "${accent_text}") not in qss, (
            f"{rel}: 代码编辑器焦点环被改成了 ${{accent_text}}（实测 <3:1）")

    engine, host, ws = _ring_host(theme)
    w = ws["code_editor"]
    focus_accent = engine.get_color("focus_accent", "").upper()
    accent_text = engine.get_color("accent_text", "").upper()
    h = _ring_probe(w, "code_editor")
    px = _px(h, {"focus_accent": focus_accent, "accent_text": accent_text})
    assert px["focus_accent"] >= _MIN_RING_PX, (
        f"{theme}/code_editor: 焦点环未上屏为 focus_accent。after={px} 众数={h.most_common(4)}")
    assert px["accent_text"] < _MIN_RING_PX, (
        f"{theme}/code_editor: 出现 accent_text 环 {px['accent_text']} px → 该处被误换键")
    inside = _dominant(h)
    assert inside and inside != focus_accent, (
        f"{theme}/code_editor: 取不到编辑器底色（众数即环色 {inside}），本条无意义")
    r = _ratio(focus_accent, inside)
    assert r >= _MIN_RATIO, (
        f"{theme}/code_editor: focus_accent({focus_accent}) vs 编辑器底({inside}) = {r} < {_MIN_RATIO}")


# ---------------------------------------------------------------------------
# ⑤ 根因扫描：qss 侧「声明了 background 却未声明 color」两条规则补显式字色令牌
# ---------------------------------------------------------------------------
#: 小字 AA 下界。
_MIN_TEXT_RATIO = 4.5
#: 判「字被画成这个色」的下界（实测一个 11 字标签 ~588 px；环形守卫同量级取 40）。
_MIN_GLYPH_PX = 40
#: 7 个次级/幽灵按钮共用同一块 ``:pressed`` 规则（按下底 = ``${bg_light}``）。
_PRESSED_SELECTORS = (
    "QPushButton#quickBtn", "QPushButton#expandChatBtn",
    "QPushButton#quickReplyBtn", "QPushButton#quickActionBtn",
    "QPushButton#copyBtn", "QPushButton#copyCodeBtn",
    "QPushButton#sidebarBottomBtn",
)
_PRESSED_ANCHOR = "QPushButton#sidebarBottomBtn:pressed {"
_SEND_ANCHOR = "ChatWindow QPushButton#chatSendBtn:disabled {"
_SEND_TARGET = "ChatWindow QPushButton#chatSendBtn"
#: 修前按下态「实际生效」的字色令牌（层叠口径实测，见回传 evidence6.md）。
_BEFORE_PRESSED_TOKENS = {sel: "primary_dark" for sel in _PRESSED_SELECTORS}
_BEFORE_PRESSED_TOKENS["QPushButton#sidebarBottomBtn"] = "text_secondary"
#: 修前禁用态继承自 accent 实底规则的字色。
_SEND_BEFORE_TOKEN = "text_on_accent"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def _block(text: str, anchor: str) -> str:
    """按锚点取出 ``SEL { ... }`` 规则块原文。

    ⚠ 不能用 ``text.index("}")`` —— 声明里的 ``${bg_light}`` 自带一对花括号，
    会被当成块结束（我们踩过：块被截到 ``${bg_light`` 就断了）。
    """
    i = text.index(anchor)
    k = text.index("{", i) + 1
    while k < len(text):
        if text.startswith("${", k):
            k = text.index("}", k) + 1
            continue
        if text[k] == "}":
            return text[i:k + 1]
        k += 1
    raise AssertionError(f"{anchor}: 找不到规则块结束花括号")


def _prop(decl: str, prop: str):
    """取声明里 ``prop: ${token};`` / ``prop: #RRGGBB;`` 的值（先剥注释）。

    ``_parse_rules`` 会把 ``${tok}`` 掩成 ``@tok@``（否则 ``${..}`` 的花括号会把
    规则切错——我们踩过），故这里把 ``@tok@`` 还原成 ``${tok}`` 一并返回。
    """
    m = re.search(r"(?<!-)\b%s\s*:\s*([^;]+);" % re.escape(prop),
                  _strip_comments(decl))
    if not m:
        return None
    return re.sub(r"^@([\w-]+)@$", r"${\1}", m.group(1).strip())


def _bg_prop(decl: str):
    return _prop(decl, "background") or _prop(decl, "background-color")


def _parse_rules(qss: str):
    """把样式表切成 ``(选择器, 声明块)`` 顺序表。

    ⚠ 必须先把 ``${tok}`` 掩成 ``@tok@``：令牌花括号会被 ``[^{}]*`` 当成规则块边界，
    导致选择器列表被切碎（我们踩过：7 个选择器的按下组被解析成 ``border-color: $``）。
    """
    qss = re.sub(r"\$\{([^}]*)\}", r"@\1@", _strip_comments(qss))
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", qss):
        for s in m.group(1).split(","):
            s = " ".join(s.split())
            if s:
                out.append((s, m.group(2)))
    return out


def _specificity(sel: str):
    """Qt 口径近似：``(#id, .class/:pseudo, type)``。"""
    ids = sel.count("#")
    cls = len(re.findall(r"\.[\w-]+", sel)) + sel.count(":") - sel.count("::")
    types = len(re.findall(r"(?:^|[\s>])([A-Za-z_][\w]*)", sel))
    return (ids, cls, types)


def _split_selector(sel: str):
    m = re.match(r"^(?P<anc>.*?)(?P<ty>[A-Za-z_][\w]*)(?:#(?P<id>[^:\s]+))?"
                 r"(?P<st>(?::(?!:)[\w-]+)*)$", sel)
    if not m:
        return None
    return (m.group("ty"), m.group("id"),
            set(re.findall(r":([\w-]+)", m.group("st"))), m.group("anc").strip())


def _winner_decl(rules, target: str, active, host=None):
    """按 Qt 层叠（特异性 → 后写者胜）求 ``target`` 在 ``active`` 伪类下的生效声明。"""
    tk = _split_selector(target)
    best = None
    for i, (sel, decl) in enumerate(rules):
        rk = _split_selector(sel)
        if rk is None:
            continue
        rty, roid, rstates, ranc = rk
        ty, oid, tstates, _ = tk
        if rty and rty != ty:
            continue
        if roid and roid != oid:
            continue
        if not rstates <= (active | tstates):
            continue
        if ranc and (host is None or ranc.split()[-1] != host):
            continue
        key = (_specificity(sel), i)
        if best is None or key > best[0]:
            best = (key, decl)
    return best[1] if best else None


@contextlib.contextmanager
def _mode(theme: str, dark: bool):
    """切到指定明暗模式取令牌值；退出时把模式与主题还原。"""
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.load_theme(theme)
    prev = "dark" if engine.is_dark_effective() else "light"
    engine.set_theme_mode("dark" if dark else "light")
    engine.load_theme(theme)
    _pump(4)
    try:
        yield engine
    finally:
        engine.set_theme_mode(prev)
        engine.load_theme(theme)
        _pump(4)


@contextlib.contextmanager
def _state_rootcause(engine, *, before: bool):
    """``before=True`` → 把修前「生效字色」按同特异性追加到末尾，复现 v2.2.0 渲染。"""
    app = QApplication.instance()
    real = app.styleSheet()
    if before:
        c = engine.get_color
        extra = [f"{sel}:pressed {{ color: {c(tok, '#000000')}; }}"
                 for sel, tok in _BEFORE_PRESSED_TOKENS.items()]
        extra.append(f"{_SEND_TARGET}:disabled "
                     f"{{ color: {c(_SEND_BEFORE_TOKEN, '#000000')}; }}")
        app.setStyleSheet(real + "\n" + "\n".join(extra))
    _pump(6)
    try:
        yield
    finally:
        app.setStyleSheet(real)
        _pump(6)


def _button_host(name: str, *, window_kind: bool = False):
    host = ChatWindow() if window_kind else QWidget()
    host.resize(280, 72)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(12, 12, 12, 12)
    btn = QPushButton("Quick Reply")
    btn.setObjectName(name)
    lay.addWidget(btn)
    host.show()
    _pump(6)
    return host, btn


def _glyph_hist(host, w, *, press: bool = False, disabled: bool = False) -> Counter:
    """真实交互后取控件矩形内像素直方图（``QTest`` 真发鼠标事件，非 setter 存值）。"""
    w.setEnabled(not disabled)
    if press:
        QTest.mousePress(w, Qt.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(w.width() // 2, w.height() // 2))
    _pump(6)
    img = host.grab().toImage()
    tl = w.mapTo(host, QPoint(0, 0))
    hist = _hist(img, (tl.x(), tl.y(), w.width(), w.height()))
    if press:
        QTest.mouseRelease(w, Qt.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(w.width() // 2, w.height() // 2))
        _pump(4)
    return hist


@pytest.mark.parametrize("theme", THEMES)
def test_root_cause_rules_declare_text(qapp, isolated_env, theme):
    """两条规则必须**显式**声明 ``color: ${text}``，且该声明在层叠里真的胜出。"""
    rel = "themes/%s.qss" % theme
    text = (ROOT / "gui" / rel).read_text(encoding="utf-8")
    rules = _parse_rules((ROOT / "gui/themes/base.qss").read_text(encoding="utf-8")
                         + "\n" + text)

    for anchor, bg_tok in ((_PRESSED_ANCHOR, "bg_light"), (_SEND_ANCHOR, "disabled_bg")):
        blk = _block(text, anchor)
        assert _prop(blk, "color") == "${text}", (
            f"{rel}: `{anchor}` 未显式声明 color: ${{text}} —— 该规则只声明背景，"
            f"字色会继承上层而漂移（实测按下态最差 1.032 / 禁用态最差 1.214 < 4.5）")
        assert _bg_prop(blk) == "${%s}" % bg_tok, (
            f"{rel}: `{anchor}` 底色不再是 ${{{bg_tok}}}（{_bg_prop(blk)}）")

    # 层叠口径：该态下真正胜出的 color 必须来自这两条新声明（含「hover 后写者胜」的顺序坑）
    for target, active, host in ((_PRESSED_SELECTORS[2], {"pressed"}, None),
                                 (_SEND_TARGET, {"disabled"}, "ChatWindow")):
        decl = _winner_decl(rules, target, active, host)
        assert decl is not None, f"{rel}: {target} 在 {active} 下取不到任何 color 声明"
        assert _prop(decl, "color") == "${text}", (
            f"{rel}: {target} 在 {sorted(active)} 下生效的 color 是 "
            f"{_prop(decl, 'color')}，不是 ${{text}} —— 新声明没赢（被更后写的同特异性规则压住）")


@pytest.mark.parametrize("dark", (False, True))
@pytest.mark.parametrize("theme", THEMES)
def test_root_cause_fix_ratio_never_regresses(qapp, isolated_env, theme, dark):
    """修后 ``text`` 在两个底上均 ≥4.5，且**不低于**修前已达标档（禁「修一档坏一档」）。

    ⚠ 朴素地讲：本条是**令牌可达性**守卫，只测「``text`` 在这两个底上够不够」，
    不解析 qss 文件 —— 把文件里的 ``${text}`` 改成别的令牌它**不会**变红。
    「文件里到底写的哪个令牌、且在层叠里胜出」由 ``test_root_cause_rules_declare_text``
    担保，「上屏」由两条渲染级用例担保；三条必须一起看（对抗性自检已逐项验证分工）。
    """
    mode = "深色" if dark else "浅色"
    with _mode(theme, dark) as engine:
        def c(k):
            return engine.get_color(k, "").upper()

        cases = (
            ("按下组", "bg_light",
             {sel: _BEFORE_PRESSED_TOKENS[sel] for sel in _PRESSED_SELECTORS}),
            ("发送禁用态", "disabled_bg", {_SEND_TARGET: _SEND_BEFORE_TOKEN}),
        )
        for label, bg_key, befores in cases:
            bg = c(bg_key)
            after = _ratio(c("text"), bg)
            assert after >= _MIN_TEXT_RATIO, (
                f"{theme}/{mode} {label}: text({c('text')}) vs {bg_key}({bg}) = {after} "
                f"< {_MIN_TEXT_RATIO}")
            for sel, tok in befores.items():
                before = _ratio(c(tok), bg)
                assert after >= min(before, _MIN_TEXT_RATIO), (
                    f"{theme}/{mode} {label} {sel}: 修后 {after} 低于修前 {before}"
                    f"（把该档原本达标的对比度改坏了）")


@pytest.mark.parametrize("theme", THEMES)
def test_pressed_state_glyph_renders_text(qapp, isolated_env, theme):
    """**渲染级**：真按下去，字必须被画成 ``${text}``；修前态则画成旧字色（证伪）。

    ⚠ 本 Qt（6.11.2）在 ``State_Sunken`` 下会对按钮文字额外画一层 **1px 阴影**，
    该阴影取主题的 ``text``（实测四风格都是：ui_whale 浅色 ``text``=#12303F 而上屏的
    阴影正是 #12303F，而按钮自身的 QSS 字色是 ``text_secondary``/``primary_dark``）。
    因此**修前**态里也会出现 ``text`` 的像素（实测 480 px 阴影 vs 220 px 字身），
    单看「有没有 text」会自欺 —— 这里改用两条可判别的判据：
    ① 旧字色的字身像素（修前 ~220 px）在修后必须消失；
    ② ``text`` 像素数必须按「一个字身」的量级增长（480 → 700）。
    """
    engine = _engine(theme)
    text_c = engine.get_color("text", "").upper()
    old_toks = ("primary_dark", "text_secondary")     # 修前按下态两种可能的生效字色
    old_cs = {engine.get_color(t, "").upper() for t in old_toks}

    host, btn = _button_host("quickReplyBtn")
    with _state_rootcause(engine, before=True):
        hb = _glyph_hist(host, btn, press=True)
    ha = _glyph_hist(host, btn, press=True)

    assert hb and ha, f"{theme}/quickReplyBtn: 直方图为空（几何 {btn.width()}x{btn.height()}）"
    assert any(hb.get(x, 0) >= _MIN_GLYPH_PX for x in old_cs), (
        f"{theme}/quickReplyBtn: before 态没画出任何一个旧字色{old_cs} → 取不到修前渲染。"
        f"众数={hb.most_common(4)}")
    for x in old_cs:
        assert ha.get(x, 0) < _MIN_GLYPH_PX, (
            f"{theme}/quickReplyBtn: 按下后仍渲染旧字色({x}) {ha.get(x, 0)} px → 该处没换键")
    assert ha.get(text_c, 0) - hb.get(text_c, 0) >= _MIN_GLYPH_PX, (
        f"{theme}/quickReplyBtn: text({text_c}) 像素没有按一个字身的量级增长 —— "
        f"after={ha.get(text_c, 0)} before={hb.get(text_c, 0)}（差额应 ≈ 字身像素）。"
        f"after 众数={ha.most_common(4)}")
    host.hide()


@pytest.mark.parametrize("dark", (False, True))
@pytest.mark.parametrize("theme", THEMES)
def test_send_disabled_glyph_renders_text(qapp, isolated_env, theme, dark):
    """**渲染级**：``ChatWindow`` 下的禁用发送按钮，字必须被画成 ``${text}``。

    浅色档 ``text`` ≡ ``text_on_accent``（如 ui_minimal 两者都是 #1C1C1E）→ 修前修后
    同色，本条**无法判别**（也正说明该档没有回归，由比值用例的 min() 断言担保），
    故按模式参数化并对同色档显式 skip。
    """
    mode = "深色" if dark else "浅色"
    with _mode(theme, dark) as engine:
        text_c = engine.get_color("text", "").upper()
        old_c = engine.get_color(_SEND_BEFORE_TOKEN, "").upper()
        if text_c == old_c:
            pytest.skip(f"{theme}/{mode}: text ≡ {_SEND_BEFORE_TOKEN}({text_c})，该档无判别力"
                        "（改与不改同色，回归由比值用例担保）")

        host, btn = _button_host("chatSendBtn", window_kind=True)
        with _state_rootcause(engine, before=True):
            hb = _glyph_hist(host, btn, disabled=True)
        ha = _glyph_hist(host, btn, disabled=True)

        assert hb.get(old_c, 0) >= _MIN_GLYPH_PX, (
            f"{theme}/{mode}/chatSendBtn@disabled: before 态未复现继承字色({old_c}) → "
            f"本条失去判别力。众数={hb.most_common(4)}")
        assert ha.get(text_c, 0) >= _MIN_GLYPH_PX, (
            f"{theme}/{mode}/chatSendBtn@disabled: 禁用后**没有**渲染 text({text_c}) → "
            f"补的 color 未上屏。text={ha.get(text_c, 0)}px 众数={ha.most_common(4)}")
        assert ha.get(old_c, 0) < _MIN_GLYPH_PX, (
            f"{theme}/{mode}/chatSendBtn@disabled: 禁用后仍是继承字色({old_c}) "
            f"{ha.get(old_c, 0)} px")
        host.hide()