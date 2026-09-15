# -*- coding: utf-8 -*-
"""聊天面板「停止生成 / 导出」两按钮：**取色令牌化 + 换肤跟随性**的渲染级守卫（v2.2.1）。

## 缺陷（用户可感知）
1. `chat_panel_parts/ui_build.py` 的 `#stopBtn`（输入区「停止生成」）：字色是裸
   `#FFFFFF`，落裸 `#FF6B6B` 实底上**四套主题一致只有 2.775**（< 小字 AA 4.5）——
   白字压在浅红上几乎不可辨。**同一个缺陷在别处已修好**（`chat_window.py` 的
   `#chatStopBtn` 已把裸 `#FFFFFF` 改成 `text_on_accent`），本文件把 `#stopBtn`
   钉到同一修法上，防它再退回裸白字。
2. 同文件 `#exportChatBtn`（顶栏「导出」）：常态字色裸 `#4A90D9`、描边裸 `#A8C8E8`、
   hover 实底裸 `#4A90D9` + 裸 `#FFFFFF` 字 —— 与全站强调色体系脱节。
3. **根本问题**：这两处样式是**控件级 `setStyleSheet()` 内联硬编码**，在 `_init_ui`
   调用的那一刻求值一次 ⇒ 切主题**不会重刷**。四套皮肤下这两个按钮恒为同一支蓝 /
   同一块浅红，与所在主题无关。

## 修法（本轮）
把两处内联样式**收口到唯一取色入口 `_apply_chat_theme()`** 的令牌下发：
常态字色与描边 → `accent_text`（落页底 `bg`）；hover 实底 → `accent` 填充 +
`text_on_accent` 字色；`#stopBtn` 字色 → `text_on_accent`。底色 `#FF6B6B` /
`#FF5252` 与 `chat_window.#chatStopBtn` 同值（同一交互的两个入口），属既有裸值残留。

## 为什么既有 2000+ 个用例拦不住
它们是**样式表字符串**断言或 **setter 存值**断言 —— 两者都能「值对了但没上屏」，
更拦不住「构造时对了、换肤后没跟上」。本文件因此只断言**渲染出来的像素**。

## 三层防御（本文件逐层钉住）
1. **跟随性**：8 档主题（4 风格 × 明暗）逐档静态重绘 `CE_PushButton` 取像素，断言
   渲染色 == **该档**令牌（`accent_text` / `accent` / `text_on_accent`），且旧裸色
   `#4A90D9` / `#A8C8E8` / `#FFFFFF` 像素为 **0**。
2. **换肤生命周期**：同一控件实例上做 8 档循环 → 每档都跟随；**回切**到首档后像素
   直方图必须与首档**逐像素一致**（无残留）；重复调用 `_apply_chat_theme()` 幂等。
3. **对照组（证伪）**：把两处下发退回「构造期那份样式表」= 复现「内联样式求值一次」
   的缺陷态 → 断言渲染色**停在首档、不再等于当前档令牌**。这证明第 1/2 层的断言真的
   在测跟随性，而不是恒真。

## 取像素口径（为什么不是一句 `grab()`）
· **不用 `show()`**（遵守本机约定：判渲染文字走 `resize()` + `ensurePolished()` +
  `layout().activate()` + `processEvents()`）；取像素走 `QStyle::CE_PushButton` **静态
  重绘**到「显式指定的不透明底布」上 —— 比 `grab()` 更确定：`grab()` 在
  `background: transparent` 的按钮上会给出 alpha=0 的底，文字抗锯齿像素被预乘污染，
  取不到精确颜色。静态重绘把背景、状态（`:hover`）都握在手里，颜色可精确比对。
· 状态覆盖：常态（`State_None`）与 `:hover`（`State_MouseOver`）分别取值
  （实测 `State_MouseOver` 能精确命中 QSS `:hover` 规则：修前得 `#4A90D9` 实底，
  修后得 `accent` 实底）。`:pressed` 两按钮均未声明单独规则，不另设断言。
· 图标通道：`icons.available()` 置 False 走**产品已声明的 emoji 文本回退路径**，
  使「QSS `color` 通道」可被确定性地像素取到（图标字体可用时字形色由
  `icons.icon(color=...)` 决定，另有静态键断言钉住 hover 取色键）。

## 本机/主题侧一处已修项 + 一处既有残值（见回传「需 owner 决策」）
· ~~`ui_cream` **深色**档的 `text_on_accent = #FFFFFF` 与 `accent = #FF9FB2` 组合只有
  1.935~~ —— **已由 owner 授权定点修复**（`gui/theme_engine.py` 深色覆盖表：cream 深色
  `text_on_accent` 由 `#FFFFFF` 改为 `#1C1C1E`，对齐 minimal；改后 vs primary=8.794、
  vs primary_dark=6.820）。本文件此前的「既有异常」豁免与登记用例已同步撤除，改为
  **正向回归守卫** `test_ui_cream_dark_text_on_accent_readable`：谁把 cream 深色字色改回
  浅色（含 `#FFFFFF`）即变红。
· `#stopBtn` 实底 `#FF6B6B` 仍是裸字面量（与 `chat_window.#chatStopBtn` 同值同源）。

## 怎么把它玩坏（对抗性自检，已实跑）
· 破第 1/2 层：把 `ui_build._apply_chat_theme` 里 `_ss("export_btn", ...)` /
  `_ss("stop_btn", ...)` 两处下发删掉 → 两按钮回落 app 级 QSS（实底变 `accent`）→
  `#FF6B6B` / `#A8C8E8` 计数断言**变红**。
· 破第 3 层（对照组自身）：`test_control_group_*` 若把 patch 改成「照常下发」→
  断言 `h[at1] == 0` 变红（对照组失效即报警）。
· 破「跟随性」的判别力：把令牌改回裸色（`color: #FFFFFF` / `border: #A8C8E8`）→
  8 档像素**逐档相同**，`test_static_*` 与档内令牌断言**变红**。
· 破 hover 图标键：`_TITLE_ICON_HOVER_KEY["export_btn"]` 改回 `"bg_card"` →
  `test_static_*` **变红**。

不改产品代码；全部零网络、零真实用户目录写入（`isolated_env` 把 HOME/APPDATA 指到临时目录）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QStyle, QStyleOptionButton  # noqa: E402

from gui.qt_compat import QApplication, QColor, QImage, QPainter  # noqa: E402

#: 主题循环：4 风格（THEME_IDS）× 明暗两模式 = 8 档（含深浅模式，≥5 档要求）。
_CYCLE = (
    ("ui_minimal", "light"), ("ui_cream", "light"),
    ("ui_night", "light"), ("ui_whale", "light"),
    ("ui_minimal", "dark"), ("ui_cream", "dark"),
    ("ui_night", "dark"), ("ui_whale", "dark"),
)
#: 小字 AA 阈值（WCAG 2.1）。
_MIN_RATIO = 4.5
#: `#stopBtn` 实底（与 chat_window.#chatStopBtn 同值；既有裸值残留）。
_STOP_FILL = "#FF6B6B"
_STOP_FILL_HOVER = "#FF5252"
#: 修复前的裸硬编码色（必须从渲染像素与源码里消失）。
_STALE_BLUE = "#4A90D9"
_STALE_BORDER = "#A8C8E8"
#: 主题色值异常档（已清空：cream 深色 text_on_accent 白字缺陷已修，全部 8 档一律走
#: 数值门槛断言；若再出现破坏对比的色值，这里**不再豁免**，断言会直接变红）。
_KNOWN_THEME_DATA_ANOMALY = set()

_ISO = Path(tempfile.mkdtemp(prefix="maling_test_chatbtn_"))


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
    """把用户目录指到临时目录（禁止读写真实 ``~/.maid_coder``）。"""
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


def _lum(hx: str) -> float:
    def _ch(v: int) -> float:
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    h = str(hx).lstrip("#")[:6]
    return (0.2126 * _ch(int(h[0:2], 16)) + 0.7152 * _ch(int(h[2:4], 16))
            + 0.0722 * _ch(int(h[4:6], 16)))


def _ratio(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    return round((max(a, b) + 0.05) / (min(a, b) + 0.05), 3)


def _hist(img: QImage) -> Counter:
    """整图精确像素直方图（走 ``constBits()`` 批量读，逐像素 ``pixelColor`` 慢一个量级）。"""
    sub = img.convertToFormat(QImage.Format_RGB32)
    buf = bytes(sub.constBits())
    cnt: Counter = Counter()
    for i in range(0, img.width() * img.height() * 4, 4):
        # Format_RGB32 小端：B G R A
        cnt["#%02X%02X%02X" % (buf[i + 2], buf[i + 1], buf[i])] += 1
    return cnt


def _draw(btn, backdrop: str, hover: bool = False, text: str | None = None) -> Counter:
    """把按钮**静态重绘**到「显式不透明底布」上，返回精确像素直方图。

    ``hover=True`` → 带 ``State_MouseOver``（精确命中 QSS ``:hover`` 规则）；
    ``text`` → 覆盖本次绘制的文本（用于把 emoji 回退字形的彩色字体这一外部变量
    隔离掉，专测「字色通道」）。
    """
    img = QImage(btn.size(), QImage.Format_ARGB32)
    img.fill(QColor(backdrop))
    painter = QPainter(img)
    opt = QStyleOptionButton()
    opt.rect = btn.rect()
    opt.text = btn.text() if text is None else text
    opt.icon = btn.icon()
    opt.iconSize = btn.iconSize()
    opt.state |= QStyle.State_Enabled
    if hover:
        opt.state |= QStyle.State_MouseOver
    QApplication.instance().style().drawControl(QStyle.CE_PushButton, opt, painter, btn)
    painter.end()
    return _hist(img)


def _sig(*counters: Counter) -> tuple:
    """直方图签名（可 == / != 比较；用于幂等与「回切不残留」的逐像素比对）。"""
    return tuple(tuple(sorted(c.items())) for c in counters)


class _Cfg:
    """最小 GuiConfig 替身。"""

    glass_popups_enabled = True
    agent_enabled = False
    web_search_enabled_gui = False
    chat_intent_mode = "auto"
    manual_scene = ""
    manual_scene_date = ""


def _ctx(engine):
    """真实 ThemeEngine + 最小 ctx 桩（与项目既有探针口径一致）。"""
    ctx = SimpleNamespace(theme_engine=engine)
    ctx.config = _Cfg()
    ctx.cfg = _Cfg()
    for k in ("chat_service", "session_manager", "gui_session", "companion",
              "companion_bridge", "role_bridge", "tts", "highlights", "diary",
              "weekly", "tavern", "memories", "glass"):
        setattr(ctx, k, None)
    ctx.session = SimpleNamespace(history=[])
    return ctx


def _engine(theme: str, mode: str):
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.set_theme_mode(mode)
    engine.load_theme(theme)
    return engine


def _panel(theme: str, mode: str):
    """构造面板并按本机口径就绪（**不 show()**：判渲染像素不需要上屏）。"""
    from gui.widgets.chat_panel import ChatPanelWidget
    engine = _engine(theme, mode)
    p = ChatPanelWidget(_ctx(engine))
    p.resize(760, 820)
    p.ensurePolished()
    lay = p.layout()
    if lay is not None:
        lay.activate()
    _pump(6)
    return engine, p


def _tokens(engine) -> dict:
    return {
        "bg": engine.get_color("bg", "#000000"),
        "accent": engine.get_color("accent", "#000000").upper(),
        "accent_text": engine.get_color("accent_text", "#000000").upper(),
        "on_accent": engine.get_color("text_on_accent", "#000000").upper(),
    }


def _assert_tokens(engine, panel, theme: str, mode: str) -> None:
    """核心跟随性断言：两按钮的**渲染色**必须是**当前档**的令牌，旧裸色像素必须为 0。"""
    tk = _tokens(engine)
    eb, sb = panel.export_btn, panel.stop_btn

    # --- 导出：常态（字色 + 描边通道 = accent_text）---
    n = _draw(eb, tk["bg"])
    assert n[tk["accent_text"]] > 0, (
        f"{theme}/{mode}: #exportChatBtn 常态**没有**渲染 accent_text({tk['accent_text']}) "
        f"→ 未跟随当前档令牌。众数={n.most_common(4)}")
    assert n[_STALE_BLUE] == 0, (
        f"{theme}/{mode}: #exportChatBtn 常态仍渲染旧裸色 {_STALE_BLUE}"
        f"({n[_STALE_BLUE]} px) → 内联裸色未被令牌替换。众数={n.most_common(4)}")
    assert n[_STALE_BORDER] == 0, (
        f"{theme}/{mode}: #exportChatBtn 描边仍渲染旧裸色 {_STALE_BORDER}"
        f"({n[_STALE_BORDER]} px) → 换肤仍不跟随。众数={n.most_common(4)}")
    assert _ratio(tk["accent_text"], tk["bg"]) >= _MIN_RATIO, (
        f"{theme}/{mode}: accent_text vs 页底 {tk['bg']} = "
        f"{_ratio(tk['accent_text'], tk['bg'])} < {_MIN_RATIO}")

    # --- 导出：hover（实底 accent + 字色 text_on_accent）---
    h = _draw(eb, tk["bg"], hover=True, text="X")
    fills = h[tk["accent"]]
    assert fills >= 200, (
        f"{theme}/{mode}: #exportChatBtn hover 实底不是 accent({tk['accent']})"
        f"（该色像素仅 {fills}）→ hover 未跟随主题。众数={h.most_common(4)}")
    assert h[tk["on_accent"]] > 0, (
        f"{theme}/{mode}: #exportChatBtn hover 未渲染 text_on_accent({tk['on_accent']})"
        f" → hover 字色未跟随。众数={h.most_common(4)}")
    assert h[_STALE_BLUE] == 0, (
        f"{theme}/{mode}: #exportChatBtn hover 仍渲染旧裸色 {_STALE_BLUE}"
        f"({h[_STALE_BLUE]} px)。众数={h.most_common(4)}")
    if tk["on_accent"] != "#FFFFFF":
        assert h["#FFFFFF"] == 0, (
            f"{theme}/{mode}: #exportChatBtn hover 仍渲染裸白字 #FFFFFF"
            f"({h['#FFFFFF']} px)。众数={h.most_common(4)}")
    if (theme, mode) not in _KNOWN_THEME_DATA_ANOMALY:
        assert _ratio(tk["on_accent"], tk["accent"]) >= _MIN_RATIO, (
            f"{theme}/{mode}: hover 字色 text_on_accent vs accent = "
            f"{_ratio(tk['on_accent'], tk['accent'])} < {_MIN_RATIO}")

    # --- 停止：常态（实底 #FF6B6B + 字色 text_on_accent）---
    sn = _draw(sb, tk["bg"])
    assert sn[_STOP_FILL] > 0, (
        f"{theme}/{mode}: #stopBtn 实底不是 {_STOP_FILL}（该色像素 {sn[_STOP_FILL]}）"
        f" → 下发未生效（回落 app 级 QSS 会变成 accent）。众数={sn.most_common(4)}")
    assert sn[tk["on_accent"]] > 0, (
        f"{theme}/{mode}: #stopBtn **没有**渲染 text_on_accent({tk['on_accent']}) → "
        f"未跟随当前档令牌。众数={sn.most_common(4)}")
    if tk["on_accent"] != "#FFFFFF":
        assert sn["#FFFFFF"] == 0, (
            f"{theme}/{mode}: #stopBtn 仍渲染裸白字 #FFFFFF（{sn['#FFFFFF']} px）→ "
            f"#FF6B6B 实底上的白字缺陷回归。众数={sn.most_common(4)}")
    if (theme, mode) not in _KNOWN_THEME_DATA_ANOMALY:
        assert _ratio(tk["on_accent"], _STOP_FILL) >= _MIN_RATIO, (
            f"{theme}/{mode}: 停止按钮字色 vs {_STOP_FILL} = "
            f"{_ratio(tk['on_accent'], _STOP_FILL)} < {_MIN_RATIO}")

    # --- 停止：hover ---
    sh = _draw(sb, tk["bg"], hover=True)
    assert sh[_STOP_FILL_HOVER] > 0, (
        f"{theme}/{mode}: #stopBtn hover 实底不是 {_STOP_FILL_HOVER}"
        f"（该色像素 {sh[_STOP_FILL_HOVER]}）。众数={sh.most_common(4)}")
    assert sh[tk["on_accent"]] > 0, (
        f"{theme}/{mode}: #stopBtn hover 未渲染 text_on_accent({tk['on_accent']})"
        f" → hover 字色未跟随。众数={sh.most_common(4)}")


# ---------------------------------------------------------------------------
# 前提守卫：测试不能变成空转
# ---------------------------------------------------------------------------
def test_precondition_tokens_differ_and_stale_literals_not_tokens(qapp, isolated_env):
    """令牌必须逐档可分辨，且旧裸色不得恰好等于某档令牌（否则像素断言失去判别力）。"""
    seen = set()
    for theme, mode in _CYCLE:
        tk = _tokens(_engine(theme, mode))
        assert tk["accent_text"] not in (_STALE_BLUE, _STALE_BORDER, "#FFFFFF"), (
            f"{theme}/{mode}: accent_text={tk['accent_text']} 与旧裸色同值，"
            "本文件的像素判别断言将退化为空转")
        assert tk["on_accent"] != _STALE_BORDER
        assert tk["accent"] != _STALE_BLUE, (
            f"{theme}/{mode}: accent={tk['accent']} 恰为旧裸蓝，hover 判别力下降")
    for theme, mode in _CYCLE[:4]:
        seen.add(_tokens(_engine(theme, mode))["accent_text"])
    assert len(seen) >= 3, f"四风格浅色档的 accent_text 只有 {len(seen)} 种不同值：{seen}"


# ---------------------------------------------------------------------------
# ① 跟随性：8 档（4 风格 × 明暗）逐档渲染像素 == 该档令牌
# ---------------------------------------------------------------------------
def test_render_follows_theme_8_styles(qapp, isolated_env, monkeypatch):
    import gui.icons as icons
    # 走产品已声明的 emoji 文本回退路径 → 使 QSS `color` 通道可被确定性取到像素。
    monkeypatch.setattr(icons, "available", lambda: False)

    for theme, mode in _CYCLE:
        engine, p = _panel(theme, mode)
        try:
            assert p.export_btn.styleSheet(), (
                f"{theme}/{mode}: #exportChatBtn 无内联样式 → 未由 _apply_chat_theme 下发")
            assert p.stop_btn.styleSheet(), f"{theme}/{mode}: #stopBtn 无内联样式"
            _assert_tokens(engine, p, theme, mode)
        finally:
            p.deleteLater()
            _pump(2)


# ---------------------------------------------------------------------------
# ② 换肤生命周期：循环跟随 / 回切不残留 / 重复下发幂等
# ---------------------------------------------------------------------------
def test_theme_cycle_follows_restores_and_is_idempotent(qapp, isolated_env, monkeypatch):
    import gui.icons as icons
    monkeypatch.setattr(icons, "available", lambda: False)

    theme0, mode0 = _CYCLE[0]
    engine, p = _panel(theme0, mode0)
    try:
        _assert_tokens(engine, p, theme0, mode0)
        first = _sig(_draw(p.export_btn, _tokens(engine)["bg"]),
                     _draw(p.stop_btn, _tokens(engine)["bg"]))

        for theme, mode in _CYCLE[1:]:
            engine.set_theme_mode(mode)
            engine.load_theme(theme)
            _pump(6)
            # 每档都必须重新跟随（构造期那一份不会残留）
            _assert_tokens(engine, p, theme, mode)
            cur = _sig(_draw(p.export_btn, _tokens(engine)["bg"]),
                       _draw(p.stop_btn, _tokens(engine)["bg"]))
            assert cur != first, (
                f"{theme}/{mode}: 渲染像素与首档 {theme0}/{mode0} 完全相同 → 换肤未重刷")

        # 回切到首档：必须与首档逐像素一致（无残留）
        engine.set_theme_mode(mode0)
        engine.load_theme(theme0)
        _pump(6)
        assert _sig(_draw(p.export_btn, _tokens(engine)["bg"]),
                    _draw(p.stop_btn, _tokens(engine)["bg"])) == first, (
            "回切首档后渲染像素与首档不一致 → 换肤存在残留")

        # 幂等：重复下发逐像素一致（setStyleSheet 是整体覆盖，不是追加）
        base = _sig(_draw(p.export_btn, _tokens(engine)["bg"]),
                    _draw(p.stop_btn, _tokens(engine)["bg"]))
        for _ in range(2):
            p._apply_chat_theme()
            _pump(2)
            assert _sig(_draw(p.export_btn, _tokens(engine)["bg"]),
                        _draw(p.stop_btn, _tokens(engine)["bg"])) == base, (
                "重复调用 _apply_chat_theme() 改变了渲染像素 → 非幂等（样式叠加）")
    finally:
        p.deleteLater()
        _pump(2)


# ---------------------------------------------------------------------------
# ③ 对照组（证伪）：把「下发」退回构造期那一份 → 颜色不再跟随
# ---------------------------------------------------------------------------
def test_control_group_stale_dispatch_stops_following_theme(qapp, isolated_env, monkeypatch):
    """对照组建模「内联样式在调用那一刻求值一次」的缺陷态：

    patch `_apply_chat_theme` 使两按钮在换肤后仍写回**构造期那一份**样式表 ——
    这正是本缺陷的成因。此时断言必须**变红**（渲染色停在首档、不等于当前档令牌），
    从而证明第 ①/② 层的断言真的在测「跟随性」，而不是恒真。
    """
    import gui.icons as icons
    monkeypatch.setattr(icons, "available", lambda: False)

    from gui.widgets.chat_panel_parts import ui_build as ub
    real = ub.ChatUiBuildMixin._apply_chat_theme
    stale: dict = {}

    def _stale_dispatch(self) -> None:
        real(self)
        if not stale:
            stale["export"] = self.export_btn.styleSheet()
            stale["stop"] = self.stop_btn.styleSheet()
        else:  # 换肤后依旧写回构造期那一份 = 内联裸色「求值一次」的缺陷态
            self.export_btn.setStyleSheet(stale["export"])
            self.stop_btn.setStyleSheet(stale["stop"])

    monkeypatch.setattr(ub.ChatUiBuildMixin, "_apply_chat_theme", _stale_dispatch)

    theme0, mode0 = ("ui_minimal", "light")
    theme1, mode1 = ("ui_whale", "light")
    engine, p = _panel(theme0, mode0)
    try:
        tk0 = _tokens(engine)
        assert _draw(p.export_btn, tk0["bg"])[tk0["accent_text"]] > 0, (
            "对照组的**前提**不成立：构造期就没拿到首档令牌（patch 没生效？）")

        engine.set_theme_mode(mode1)
        engine.load_theme(theme1)
        _pump(6)
        tk1 = _tokens(engine)
        assert tk0["accent_text"] != tk1["accent_text"], "两档 accent_text 相同，对照组无判别力"
        assert tk0["on_accent"] != tk1["on_accent"], "两档 text_on_accent 相同，对照组无判别力"

        h = _draw(p.export_btn, tk1["bg"])
        s = _draw(p.stop_btn, tk1["bg"])
        # 证伪 ①：导出按钮的渲染色停在**首档**令牌
        assert h[tk1["accent_text"]] == 0, (
            "对照组失效：换肤后导出按钮竟渲染了当前档 accent_text —— 说明 patch 未拦到下发，"
            "第 ① 层断言可能恒真")
        assert h[tk0["accent_text"]] > 0, (
            f"对照组失效：换肤后导出按钮既非当前档也非首档令牌（众数={h.most_common(4)}）")
        # 证伪 ②：停止按钮的字色停在**首档**令牌
        assert s[tk1["on_accent"]] == 0, "对照组失效：换肤后停止按钮竟渲染了当前档 text_on_accent"
        assert s[tk0["on_accent"]] > 0, (
            f"对照组失效：换肤后停止按钮既非当前档也非首档令牌（众数={s.most_common(4)}）")
    finally:
        p.deleteLater()
        _pump(2)


def test_control_group_empty_dispatch_stops_following_theme(qapp, isolated_env, monkeypatch):
    """对照组的第二形态：把两处下发**整段置空** → 回落 app 级 QSS（实底变 accent、
    描边变 primary），同样不再等于本轮声明的令牌。"""
    import gui.icons as icons
    monkeypatch.setattr(icons, "available", lambda: False)

    from gui.widgets.chat_panel_parts import ui_build as ub
    real = ub.ChatUiBuildMixin._apply_chat_theme

    def _empty_dispatch(self) -> None:
        real(self)
        self.export_btn.setStyleSheet("")
        self.stop_btn.setStyleSheet("")

    monkeypatch.setattr(ub.ChatUiBuildMixin, "_apply_chat_theme", _empty_dispatch)

    engine, p = _panel("ui_minimal", "light")
    try:
        tk = _tokens(engine)
        h = _draw(p.export_btn, tk["bg"])
        s = _draw(p.stop_btn, tk["bg"])
        # 置空后：描边不再是 accent_text、停止按钮实底不再是 #FF6B6B
        assert h[tk["accent_text"]] == 0, (
            f"对照组失效：置空下发后导出按钮仍渲染 accent_text（众数={h.most_common(4)}）")
        assert s[_STOP_FILL] == 0, (
            f"对照组失效：置空下发后停止按钮仍渲染 {_STOP_FILL}（众数={s.most_common(4)}）")
    finally:
        p.deleteLater()
        _pump(2)


# ---------------------------------------------------------------------------
# ④ 主题色值回归守卫：cream 深色 text_on_accent 必须是「落在浅强调实底上的深字」
# ---------------------------------------------------------------------------
def test_ui_cream_dark_text_on_accent_readable(qapp, isolated_env):
    """`ui_cream` 深色档 `text_on_accent` 必须是深字，且对全部实底 ≥4.5。

    历史缺陷：该档写死 `#FFFFFF`，落 `accent=#FF9FB2` 只有 **1.935**，白字在浅粉实底上
    基本不可读。owner 授权定点改为 `#1C1C1E`（对齐 minimal）后，本用例从「登记异常」
    翻转为**正向守卫**：谁改回 `#FFFFFF`（或任何浅色字），第 1/2 条断言立刻变红。
    """
    engine = _engine("ui_cream", "dark")
    on_accent = engine.get_color("text_on_accent", "#000000").upper()
    accent = engine.get_color("accent", "#000000").upper()
    primary = engine.get_color("primary", "#000000").upper()
    primary_dark = engine.get_color("primary_dark", "#000000").upper()
    warn = engine.get_color("state_warn", "#000000").upper()
    # ① 必须不再是白字（复现缺陷的唯一已知因）
    assert on_accent != "#FFFFFF", (
        f"ui_cream/深色档 text_on_accent 又回到白字 {on_accent} → 浅粉实底上不可读的缺陷回归")
    # ② 必须是对「浅实底」而言的深字（相对亮度低于 WCAG 黑白交叉点 0.1791）
    assert _lum(on_accent) < 0.1791, (
        f"ui_cream/深色档 text_on_accent={on_accent} 亮度 "
        f"{_lum(on_accent):.4f} ≥ 0.1791 → 不是深字，落浅强调实底会不可读")
    # ③ 全部实底落点 ≥4.5（小字 AA）
    for bg, tag in ((accent, "accent"), (primary, "primary"),
                    (primary_dark, "primary_dark"), (warn, "state_warn")):
        r = _ratio(on_accent, bg)
        assert r >= _MIN_RATIO, (
            f"ui_cream/深色档 text_on_accent({on_accent}) vs {tag}({bg}) = {r} < {_MIN_RATIO}")


# ---------------------------------------------------------------------------
# ⑤ 静态：收口位置 + 旧裸色清零 + hover 图标取色键对齐
# ---------------------------------------------------------------------------
def _hex_literals(node) -> set:
    """AST 里所有**字符串常量**中的裸色字面量（忽略注释与文档串，避免误伤说明文字）。"""
    import ast
    import re
    pat = re.compile(r"#[0-9A-Fa-f]{6}")
    out: set = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.update(m.group(0).upper() for m in pat.finditer(n.value))
    return out


def _ss_call_node(tree, attr: str):
    """取 `_ss("<attr>", ...)` 调用的 AST 节点。"""
    import ast
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_ss"
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == attr):
            return n
    return None


def test_static_single_entry_and_no_stale_literals(qapp, isolated_env):
    import ast

    src_path = ROOT / "gui" / "widgets" / "chat_panel_parts" / "ui_build.py"
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    # 模块内字符串常量不得再有旧裸蓝 / 旧裸描边（注释里作为「旧值」提及不算）
    mod_lits = _hex_literals(tree)
    assert _STALE_BLUE not in mod_lits, f"ui_build.py 的字符串常量仍残留旧裸色 {_STALE_BLUE}"
    assert _STALE_BORDER not in mod_lits, f"ui_build.py 的字符串常量仍残留旧裸色 {_STALE_BORDER}"

    # 构造期 setStyleSheet 必须已删除（否则换肤不会重刷）
    assert "export_btn.setStyleSheet" not in src, "导出按钮仍有构造期内联样式"
    assert "stop_btn.setStyleSheet" not in src, "停止按钮仍有构造期内联样式"

    # 两处下发必须在唯一取色入口 `_apply_chat_theme` 内
    anchor = src.index("def _apply_chat_theme")
    for attr in ("export_btn", "stop_btn"):
        assert src.index(f'_ss("{attr}"') > anchor, f'_ss("{attr}") 不在 _apply_chat_theme 内'
        node = _ss_call_node(tree, attr)
        assert node is not None, f"未找到 _ss(\"{attr}\", ...) 下发"
        lits = _hex_literals(node)
        assert "#FFFFFF" not in lits, f"_ss(\"{attr}\") 下发体仍有裸白字：{sorted(lits)}"
        assert _STALE_BLUE not in lits, f"_ss(\"{attr}\") 下发体仍有旧裸蓝：{sorted(lits)}"
        assert _STALE_BORDER not in lits, f"_ss(\"{attr}\") 下发体仍有旧裸描边：{sorted(lits)}"
    # 停止按钮只允许与 chat_window.#chatStopBtn 同值的两个既有裸值残留
    assert _hex_literals(_ss_call_node(tree, "stop_btn")) <= {_STOP_FILL, _STOP_FILL_HOVER}, (
        "停止按钮下发体引入了新的裸色")

    # hover 图标取色键必须与 QSS hover 前景（text_on_accent）对齐
    from gui.widgets.chat_panel import ChatPanelWidget
    key = ChatPanelWidget._TITLE_ICON_HOVER_KEY
    assert key["export_btn"] == "text_on_accent", (
        f"export_btn hover 图标取色键={key['export_btn']!r}，与 QSS hover 前景 text_on_accent 不一致")
    assert key["expand_btn"] == "text_on_accent", (
        f"expand_btn hover 图标取色键={key['expand_btn']!r}（同类配对，同一修法）")
