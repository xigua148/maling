# -*- coding: utf-8 -*-
r"""v2.2.1「三个黑色的东西」修复守卫（用户原话驱动）。

用户诉求（本轮最高优先）：
  ① 「我箭头指向的那种黑框，不要」→ 计划页标题右侧 28×28 深色方块（WP1）；
  ② 「侧边栏换模块的时候会黑屏一下再切换……把黑屏这个也去了」（WP2）；
  ③ 「我说的是退出码铃时的那个弹窗，两个选项的黑框。**这个项目所有类似选定黑框的
     都可以不用存在**，原来的按压提示也够用的，这个黑框太丑了。」（WP3）

三条根因与本文件的对应：
  WP1 通用 `QPushButton { padding: 8px 20px; }`（四套肤感层同值）把 `setFixedSize`
      钉成 20~28px 的按钮内容区压成 ≤ 0 → 字形 / 图标结构上不可能绘制。
      实测：计划页 `+` 28×28 → 内容区 -12×12、字形 0/784；`padding: 0` → 28×28、20/784。
      修法：6 个 id 收在 `base.qss §1e-bis` 一条分组 id 规则里 `padding: 0px;`
      （id 特异性 > 类型选择器 ⇒ 稳压各主题；**不动**通用 QPushButton 的 padding）。
  WP2 毛玻璃开时 `#glassCentralOuter / #glassCentralSplitter / #glassPageStack` 是
      `background: transparent`，而切页走 `motion.fade(to=1.0)`（无 effect 时从 0.0 起）
      ⇒ 起帧整片未绘制 = 屏幕级纯黑 82.22%（glass=off 同一动作 0.03%）。
      修法：**在调用点**（`MainWindow._on_page_switched`）—— glass=on 该档一律不做
      透明度淡入并收掉全部页面淡入残留；glass=off 保留原有淡入。
      `gui/motion.py` 是冻结内核（签名即契约），签名与默认值零改动。
  WP3 `base.qss` 原 `QPushButton:focus { outline: 1px solid ${text}; }`，四套主题的
      `${text}` 都是**文字色**（浅色档近黑 #1C1C1E / #3D2E2A / #12303F）⇒ 鼠标点任意
      按钮都在按钮内缘贴出一圈近黑矩形（实测聚焦前后 134px、#C57792 → #1C1C1E）。
      修法：`keyboardNav` 动态属性分流 —— 鼠标零描边、键盘留一圈 `${text_on_accent}`；
      属性由 `MainWindow.eventFilter`（应用级，读 `QFocusEvent.reason()`）打。
      ⚠ 环色**必须**是 `${text_on_accent}`：Qt 的 outline 画在**按钮自己的填充上**，
        实测只有它四主题 × 明/暗全 ≥5.19:1；`${accent_text}` 只有 1.00~2.28:1
        （ui_night 因 accent_text ≡ primary 而**一个像素都画不出来**），
        v2.2.0 的 `${text}` 在暗色档只有 1.6~2.5:1。
      ⚠ `QSlider` 也纳入分流：它默认 focusPolicy = ClickFocus|TabFocus（实测 11），
        鼠标点一下就给焦点，其 `::handle` 的近黑描边同属这一类。

## QSS 解析口径（踩过坑，写在这里防复踩）
本仓所有 qss 都含 `${primary}` 这类占位符，其花括号会把朴素正则 `[^{}]*` 截断 ——
实测 `re.finditer(r"([^{}]+)\{([^{}]*)\}", qss)` 会**整条漏掉**带 `${token}` 声明体的规则
（`QPushButton[keyboardNav="true"]:focus` 就因此解析不到）。本文件统一用 `_qss_rules()`，
它逐字符扫描、把 `${...}` 当原子跳过。`tests/test_v22_1_contrast_qss.py::_focus_rule_decls`
用的是同一思路（先 `replace("${focus_accent}", "@FA@")` 再 `re.sub(r"\$\{[^}]*\}", "@TOKEN@")`）。

  WP5（三轮补漏）**第五判据**：内容区「有」不等于文字画得出来 ——
      浮窗底部三个扁平文字按钮（😊 表情 / 📤 导出 / 🎤 语音）`setFixedHeight(24)` 且
      自身 sheet **未声明 padding** ⇒ 回落应用级 `padding: 8px 20px` ⇒ 内容区 40×**8**，
      而 12px 字实际需要 **14** 行墨迹 ⇒ 上下各被硬裁（实测墨迹只占 8 行）。
      WP1/WP4 的判据（内容区任一边 ≤ 0 或 ≤ 4）**抓不到**它 —— 8 > 4，这就是它连漏两轮的原因。
      第五判据 = **内容区高 < 实测墨迹行数**；且必须做「加高 / 补 padding」反事实，
      否则分不清「真被裁」与「本来就不需要那么高」。
      ⚠ 门槛**不能**用 `QFontMetrics.height()`（行高 17 > 墨迹 14）—— 那会造成满屏假阳性；
        实测目标值：内容区 24、墨迹 14 行，故 `_MIN_INK_ROWS = 13`（留 1 行抗锯齿余量）。
      ⚠ **v2.2.2(retarget)**：用户 2026-09-16 指令「浮窗去掉表情，导出，语音」—— 那三个
        扁平文字按钮已从 `ChatWindow` 删除，三项功能保留在**聊天主面板**
        （导出 `#exportChatBtn` 32×28；表情 / 语音 `#quickActionBtn` 定高 28）。
        本判据的**样本随之搬到主面板**，且门槛由旧的固定值 `_MIN_INK_ROWS = 13` 改为
        **反事实**（放宽高度后墨迹行数不再变多 = 没裁字）—— 13 是 24px/12px 旧样本的
        标定值，主面板这组实测只有 9~10 行，照搬会得到假红。见 `_wp5_clip_fault()`。

全 offscreen、零网络、零真实用户目录写入。
"""
from __future__ import annotations

import os
import re
import tempfile
from collections import Counter
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402

from gui.qt_compat import (  # noqa: E402
    QApplication, QEvent, QGraphicsOpacityEffect, QHBoxLayout, QImage, QMessageBox,
    QPoint, QPushButton, QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget,
    Qt,
)
from PySide6.QtGui import QFocusEvent  # noqa: E402
from PySide6.QtWidgets import QStyle, QStyleOptionButton  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
BASE_QSS = ROOT / "gui" / "themes" / "base.qss"
_ISO = Path(tempfile.mkdtemp(prefix="maling_test_blackbox_"))

#: WP1 六处目标的 id（判据 = 内容区 ≤ 0）
WP1_IDS = (
    "planNewBtn",             # gui/pages/page_plan.py
    "newSessionBtn",          # gui/widgets/chat_panel_parts/ui_build.py
    "toggleSidebarBtn",       # gui/widgets/chat_panel_parts/ui_build.py
    "sessionTabsNewBtn",      # gui/widgets/session_tabs.py
    "attachmentChipRemove",   # gui/widgets/attachment_bar.py
    "feedbackSpark",          # gui/widgets/proactive_feedback.py
)
#: 六处的固定尺寸（不得被本修复改动）
WP1_SIZES = {
    "planNewBtn": (28, 28),
    "newSessionBtn": (24, 24),
    "toggleSidebarBtn": (20, 60),
    "sessionTabsNewBtn": (28, 24),
    "attachmentChipRemove": (20, 20),
    "feedbackSpark": (24, 20),
}
#: 环判据（「看得见」的下界，与 tests/test_v22_1_contrast_qss.py 的 _MIN_RING_PX 同口径）
_MIN_RING_PX = 40
#: 120x36 宿主按钮上 1px 环实测纯色 196 px，故宿主用例用更紧的判据
_MIN_RING_PX_HOST = 120
#: 滑杆手柄 2px 环实测 102~150 px
_MIN_SLIDER_RING_PX = 40
#: WCAG 1.4.11 非文本图形下界
_MIN_RATIO = 3.0
#: 键盘焦点属性
KBD_PROP = "keyboardNav"
#: `QTabBar::tab:selected:focus` 的近黑下划线是**允许**保留的例外：
#: `QTabBar` 默认 focusPolicy 实测为 TabFocus(1)（`QTabWidget` 的 tabBar 亦然）
#: → 鼠标点击根本不给焦点，那条规则只出现在键盘导航路径 = 该保留的可达性提示。
_ALLOWED_NEAR_BLACK_FOCUS = ("QTabBar::tab:selected:focus",)


# ---------------------------------------------------------------------------
# QSS 解析（`${...}` 安全）
# ---------------------------------------------------------------------------
def _qss_rules(text: str):
    """产出 ``[(selector, decl)]``；逐字符扫描，``${var}`` 当原子跳过。

    朴素 ``([^{}]+)\\{([^{}]*)\\}`` 会被 ``${token}`` 里的花括号截断（整条规则漏掉），
    故不能用。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, i, n, buf = [], 0, len(text), []
    while i < n:
        ch = text[i]
        if ch == "$" and i + 1 < n and text[i + 1] == "{":
            j = text.find("}", i + 2)
            if j == -1:
                buf.append(text[i:])
                break
            buf.append(text[i:j + 1])
            i = j + 1
            continue
        if ch == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                c = text[j]
                if c == "$" and j + 1 < n and text[j + 1] == "{":
                    k = text.find("}", j + 2)
                    j = (k + 1) if k != -1 else n
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                j += 1
            out.append(("".join(buf).strip(), text[i + 1:j - 1]))
            buf, i = [], j
            continue
        buf.append(ch)
        i += 1
    return out


def _wp1_padding_rules():
    """base.qss 里所有「把按钮 padding 归零」的规则（id 列表 → 选择器 / 声明体）。"""
    qss = BASE_QSS.read_text(encoding="utf-8")
    hits = []
    for sel, decl in _qss_rules(qss):
        ids = re.findall(r"QPushButton#(\w+)", sel)
        if ids and re.search(r"padding\s*:\s*0(px)?\s*;", decl):
            hits.append((ids, sel, decl))
    return qss, hits


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
    yield
    try:
        from gui.theme_engine import ThemeEngine
        ThemeEngine().load_theme(ThemeEngine.DEFAULT_THEME_ID)
        _pump(4)
    except Exception:
        pass


@pytest.fixture(scope="module", autouse=True)
def _font_chain_precondition(qapp):
    """把「本文件渲染判据所依赖的字体前置条件」显式建起来，收尾**按原值还原**。

    真因（二轮取证，三层实锤 —— 不是本文件写错，也不是 WP1 修复的问题）：

      ① 主题 QSS 的字体族链由 ``gui/fonts.font_family_chain()`` 产出，形态是
         ``"Resource Han Rounded CN", "Microsoft YaHei", "remixicon", sans-serif``
         —— 图标族被**有意**插在通用族 ``sans-serif`` 之前（D-V21-06：PUA 字形
         随文案流渲染）。此处的关键性质是「链是**逐族向下找**的」。
      ② 本机 offscreen 环境的 Qt 字库里**没有** Microsoft YaHei
         （``QFontDatabase.families()`` 初始为 ``[]``，同时报
         ``Cannot find font directory …/PySide6/lib/fonts``）⇒ 链上第 1 族查不到时
         Qt 会继续往下找。
      ③ 于是**只要进程内任何一个用例先把 remixicon 注册进 Qt**
         （``tests/test_v21_icons.py`` 有 8 处调 ``gui.icons.register_icon_font()``），
         第 2 族就命中，控件字体被解析成 ``remixicon``
         （实测 ``QFontInfo(w.font()).family() == 'remixicon'``）；而 remixicon
         只有 PUA 字形，ASCII / CJK **一个墨点都没有**
         （实测 ``horizontalAdvance('+')`` = 8、``'◀' / '✦'`` = 0，
         计划页 ``+`` 的渲染直方图从 ``{#C57792:752, #1C1C1E:32}`` 变成
         ``{#C57792:784}`` —— 只剩底色）
         ⇒ 本文件所有「字形像素 > 0」的判据**全部假红**。

      ⚠ 这是「跑序 + 本机字库」耦合出来的产物：装了雅黑的机器上、以及打包态
        （``gui/main.py`` 在造 MainWindow 之前就先 ``fonts.register_bundled_fonts()``）
        都不会出现。但它会让本文件的判据在**全量跑**里失去意义，必须修。

    修法（不弱化断言、不 skip、不放宽阈值）：按**产品自身的启动顺序**，先把内置
      文本字体注册进来，让族链第 1 族就是真实存在的 ``Resource Han Rounded CN``
      —— 这正是 ``gui/main.py`` 造 MainWindow 之前做的事，测试环境由此与产品一致，
      而**不是**给测试开后门。``_REGISTERED_FAMILIES`` 收尾按原值还原
      （与 ``tests/test_v19_b.py`` 同一套「保存 / 清空 / 还原」约定），
      确保后续用例看到的族链与本 fixture 执行前**逐字节一致**。
    """
    from gui import fonts
    saved = dict(fonts._REGISTERED_FAMILIES)
    registered = fonts.register_bundled_fonts()
    assert registered, (
        "字体前置条件建立失败：gui/assets/fonts/ 下内置文本字体一个都没注册上。"
        "此时主题族链首族必然落空（本机无雅黑），本文件的「字形像素 > 0」判据"
        "无从谈起 —— 宁可在这里炸，也不要让渲染判据静默失去意义。")
    try:
        yield
    finally:
        fonts._REGISTERED_FAMILIES.clear()
        fonts._REGISTERED_FAMILIES.update(saved)


@pytest.fixture(autouse=True)
def _deterministic_icons_state(qapp):
    r"""把 ``gui.icons`` 的**进程级单例态**复位到确定态，收尾按原值还原。

    为什么必须显式复位（本机实测，非推测）：

      ``gui.icons`` 是模块级单例（``_registered_family`` / ``_manifest`` /
      ``_app_ctx`` / ``_subscribed`` / ``_cache_keys``），注册一次就**不会**按窗口
      复位。而本文件的 WP1 判据里 `feedbackSpark` 的构造期就要读它
      （`gui/widgets/proactive_feedback.py:61-71`）::

          if icons.available():
              spark_icon = icons.icon("auto_awesome", 14, None)   # 矢量图标
          else:
              self._spark.setText("✨")                            # emoji 兜底

      于是同一份断言会**随跑序**走两条不同分支：

        · 图标字体**未注册**（本文件单跑时的自然态）→ emoji ``✨``
          ⇒ 四主题都看得见，用例绿；
        · 图标字体**已注册**（前面任何模块调过
          ``gui.icons.register_icon_font()``，如 ``tests/test_v21_icons.py``
          与 ``tests/test_v22_2_nav_icons.py``）→ 矢量图标，而
          ``icons.configure(app_ctx)`` 从未被调用 ⇒ ``icons._app_ctx is None``
          ⇒ ``icon(name, size, None)`` 取色回落 ``#000000``
          ⇒ 深色主题（ui_night 宿主底色实测 ``#131114``）上黑图形与底色最大通道差
          只有 19 < 判据阈值 30 ⇒ ``feedbackSpark: 内容区 24x20 字形=0`` 假红。

      这正是 team-lead 的**权威全量回归**所依赖的守卫，不能依赖模块顺序。

    修法（不弱化断言、不 skip、不删用例）：按 ``tests/test_v21_icons.py`` 与
      ``tests/test_v22_2_nav_icons.py`` 的既有约定，在每个用例前后复位 / 还原这五个
      单例变量 —— 本文件由此看到的 ``icons`` 态与「单跑」时**逐字节相同**，
      且**不把**自己的态留给后面的模块。

    ⚠ 复位会让 ``feedbackSpark`` 走 emoji 兜底分支，矢量图标分支的覆盖由新增用例
      ``test_wp1_vector_icon_path_renders_glyph`` **显式**补回（两条都测，不是二选一）。
    """
    from gui import icons
    saved = (icons._registered_family, icons._manifest, icons._app_ctx,
             icons._subscribed, list(icons._cache_keys))
    icons._reset_state()
    assert icons.available() is False, (
        "复位后 icons.available() 仍为真 —— 本 fixture 的确定性前提不成立")
    try:
        yield
    finally:
        # 先清掉本文件渲染期间**新增**的图标缓存键，再按原值还原键表 ——
        # 顺序反了会让还原后的 `_cache_keys` 被 `clear_cache()` 又清空一次。
        try:
            icons.clear_cache()
        except Exception:
            pass
        icons._registered_family = saved[0]
        icons._manifest = saved[1]
        icons._app_ctx = saved[2]
        icons._subscribed = saved[3]
        icons._cache_keys[:] = saved[4]      # 实测 `_cache_keys` 是 list（不是 set）


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _pump(n: int = 6) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def _engine(theme: str):
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(4)
    return engine


def _lum(c: str) -> float:
    r, g, b = (int(c[1:][i:i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _f(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * _f(r) + 0.7152 * _f(g) + 0.0722 * _f(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hist(img: QImage, rect) -> Counter:
    """矩形内像素直方图（``constBits`` 批量读）。"""
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


def _rect_of(container, w, pad: int = 0):
    tl = w.mapTo(container, QPoint(0, 0))
    return (tl.x() - pad, tl.y() - pad, w.width() + 2 * pad, w.height() + 2 * pad)


def _inner_glyph(img: QImage, rect, ratio: float = 0.28):
    """内区（避圆角边缘）里与底色差 >30 的像素数 —— 即字形 / 图标像素。"""
    x0, y0, w, h = rect
    ix, iy = max(2, int(w * ratio)), max(2, int(h * ratio))
    c = _hist(img, (x0 + ix, y0 + iy, max(1, w - 2 * ix), max(1, h - 2 * iy)))
    if not c:
        return 0
    modal = c.most_common(1)[0][0]

    def _d(a, b):
        a, b = int(a[1:], 16), int(b[1:], 16)
        return max(abs(((a >> s) & 0xFF) - ((b >> s) & 0xFF)) for s in (0, 8, 16))

    return sum(v for k, v in c.items() if _d(k, modal) > 30)


def _frame_diff(a: QImage, b: QImage, rect, thresh: int = 20):
    """两帧在 rect 内的差异像素与新色 / 旧色分布。"""
    x0, y0, w, h = rect
    new: Counter = Counter()
    old: Counter = Counter()
    n = 0
    for y in range(max(0, y0), min(b.height(), y0 + h)):
        for x in range(max(0, x0), min(b.width(), x0 + w)):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            if (abs(pa.red() - pb.red()) + abs(pa.green() - pb.green())
                    + abs(pa.blue() - pb.blue())) > thresh:
                n += 1
                new["#%02X%02X%02X" % (pb.red(), pb.green(), pb.blue())] += 1
                old["#%02X%02X%02X" % (pa.red(), pa.green(), pa.blue())] += 1
    return n, new, old


def _force_kbd(w, kbd: bool) -> None:
    """按 `MainWindow.eventFilter` 的口径物化 `keyboardNav`（用于不依赖主窗的渲染用例）。"""
    w.setProperty(KBD_PROP, bool(kbd))
    style = w.style()
    style.unpolish(w)
    style.polish(w)
    _pump(6)


# ---------------------------------------------------------------------------
# 共享：真实 MainWindow（毛玻璃 stubbed 为 on）—— WP2 与 WP3 都要它
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def glass_window(qapp, isolated_env):
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
        cfg = GuiConfig()
        cfg.first_run = False
        cfg.theme_name = "ui_minimal"
        cfg.theme_mode = "light"
        cfg.glass_enabled = True
        cfg.auto_check = False
        cfg.tts_enabled = False
        cfg.pet_enabled = False
        ctx = AppContext(config=cfg)
        win = mw_mod.MainWindow(ctx)
        win.resize(1200, 800)
        win.show()
        _pump(8)
        yield win
        try:
            win.close()
            win.deleteLater()
        except Exception:
            pass
        _pump(4)
    finally:
        for name, fn in originals.items():
            setattr(glass, name, fn)


# ===========================================================================
# WP1 —— 定尺寸按钮内容区归零
# ===========================================================================
def test_wp1_padding_rule_present_and_grouped():
    """6 个 id 必须收在 base.qss 的**同一条**分组 id 规则里 `padding: 0px;`。"""
    qss, hits = _wp1_padding_rules()
    assert hits, "base.qss 未找到任何把按钮 padding 归零的 id 规则"
    target = next((h for h in hits if "planNewBtn" in h[0]), None)
    assert target, f"base.qss 未找到含 #planNewBtn 的 padding 归零规则（找到 {[h[0] for h in hits]}）"
    ids, sel, decl = target
    assert sorted(ids) == sorted(WP1_IDS), (
        f"§1e-bis 分组规则的 id 集合与 WP1 六处不一致：{ids}")
    assert re.search(r"padding\s*:\s*0(px)?\s*;", decl), f"未把 padding 归零：{decl!r}"
    # 「唯一收口点」= 语义不变量：base.qss 里所有**声明了 padding** 的规则中，命中
    # 这 6 个 id 任一的必须**恰好只有上面那条分组规则**。
    # 旧判据是「id 字符串在全文只出现 1 次」——那是实现细节，会被无关改动误伤：
    # §1g 为抬高特异性写了 `QWidget QPushButton#planNewBtn`（base.qss 排在四份主题
    # qss 之前，同特异性的 base id 规则压不住主题层，理由见 base.qss §1f/§1g 注释），
    # 它**只声明 border-radius**、与 padding 无关，却把计数顶成 2。
    # 真正要守的是「这 6 个 id 的 padding 归零只有一个收口点」，故改为：先剥掉注释
    # （§1f/§1g 注释里就引用了 `#planNewBtn` / `#toggleSidebarBtn`），再逐条规则取
    # 「声明块含 padding」且「选择器命中这 6 个 id 之一」者，断言条数 == 1。
    # 选择器用 `#id` 子串口径，故能认出 `QWidget QPushButton#xxx` 这类带类型祖先的写法。
    qss_nc = re.sub(r"/\*.*?\*/", "", qss, flags=re.S)  # 明确的去注释步骤
    padding_rules = []
    for sel, decl in _qss_rules(qss_nc):
        if not re.search(r"\bpadding\b", decl):
            continue
        hit = [oid for oid in WP1_IDS if re.search(rf"#{oid}\b", sel)]
        if hit:
            padding_rules.append((hit, sel.strip(), decl.strip()))
    assert len(padding_rules) == 1, (
        "base.qss 里对这 6 个 id 声明 padding 的规则应恰好 1 条（§1e-bis 唯一收口），"
        f"实际 {len(padding_rules)} 条：{[(h, s) for h, s, _ in padding_rules]}")
    only_ids, _, only_decl = padding_rules[0]
    assert sorted(only_ids) == sorted(WP1_IDS), (
        f"唯一收口规则的 id 集合与 WP1 六处不一致：{only_ids}")
    assert re.search(r"padding\s*:\s*0(px)?\s*;", only_decl), (
        f"唯一收口规则未把 padding 归零：{only_decl!r}")


def test_wp1_generic_button_padding_untouched():
    """守卫「没改通用 QPushButton 的 padding」——四套肤感层仍是 8px 20px。"""
    for theme in THEMES:
        path = ROOT / "gui" / "themes" / f"{theme}.qss"
        rules = [d for s, d in _qss_rules(path.read_text(encoding="utf-8"))
                 if s.strip() == "QPushButton"]
        assert rules, f"{theme}.qss 找不到通用 QPushButton 规则（口径判断失效）"
        assert re.search(r"padding\s*:\s*8px\s+20px\s*;", rules[0]), (
            f"{theme}.qss 通用 QPushButton 的 padding 被改动了：{rules[0]!r}")


def test_wp1_source_object_names_present():
    """缺 id 的三处必须补上（否则 §1e-bis 命中不了）。"""
    checks = (
        (ROOT / "gui" / "pages" / "page_plan.py", "planNewBtn"),
        (ROOT / "gui" / "widgets" / "chat_panel_parts" / "ui_build.py", "newSessionBtn"),
        (ROOT / "gui" / "widgets" / "chat_panel_parts" / "ui_build.py", "toggleSidebarBtn"),
        (ROOT / "gui" / "widgets" / "session_tabs.py", "sessionTabsNewBtn"),
        (ROOT / "gui" / "widgets" / "attachment_bar.py", "attachmentChipRemove"),
        (ROOT / "gui" / "widgets" / "proactive_feedback.py", "feedbackSpark"),
    )
    for path, oid in checks:
        text = path.read_text(encoding="utf-8")
        assert f'setObjectName("{oid}")' in text, f"{path.name} 缺少 setObjectName({oid!r})"


def _wp1_widgets(theme: str):
    """构造 6 处**真实控件**，返回 (host, [(id, widget)])。"""
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.pages.page_plan import PagePlan
    from gui.widgets.attachment_bar import _Chip, AttachmentData
    from gui.widgets.chat_panel import ChatPanelWidget
    from gui.widgets.proactive_feedback import ProactiveFeedbackBar
    from gui.widgets.session_tabs import SessionTabsBar
    from gui.theme_engine import ThemeEngine

    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(4)
    cfg = GuiConfig()
    cfg.first_run = False
    ctx = AppContext(config=cfg)
    ctx.theme_engine = engine

    plan = PagePlan(ctx)
    plan.resize(900, 620)
    panel = ChatPanelWidget(ctx)
    panel.resize(760, 520)
    tabs = SessionTabsBar(ctx)
    tabs.resize(420, 34)
    chip = _Chip(AttachmentData(name="a.txt", path=str(ROOT / "version.json"),
                                size=1234, ext=".txt"), ctx)
    chip.resize(200, 38)
    bar = ProactiveFeedbackBar("s", "sc", None)
    bar.resize(320, 30)

    host = QWidget()
    host.setObjectName("wp1Host")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(8)
    for p in (plan, panel, tabs, chip, bar):
        lay.addWidget(p)
    widgets = [
        ("planNewBtn", plan.new_btn),
        ("newSessionBtn", panel.new_session_btn),
        ("toggleSidebarBtn", panel.toggle_sidebar_btn),
        ("sessionTabsNewBtn", tabs.new_btn),
        ("attachmentChipRemove", chip._remove_btn),
        ("feedbackSpark", bar._spark),
    ]
    host.resize(1000, 1400)
    host.ensurePolished()
    lay.activate()
    for p in (plan, panel, tabs, chip, bar):
        if p.layout() is not None:
            p.layout().activate()
    _pump(12)
    host.grab()
    _pump(4)
    return host, widgets


@pytest.mark.parametrize("theme", THEMES)
def test_wp1_fixed_size_buttons_render_glyph(qapp, isolated_env, theme):
    """渲染级：6 处内容区 > 0 且内区字形 / 图标像素 > 0（四主题）。"""
    host, widgets = _wp1_widgets(theme)
    img = host.grab().toImage()
    bad = []
    for oid, w in widgets:
        opt = QStyleOptionButton()
        w.initStyleOption(opt)
        cr = w.style().subElementRect(QStyle.SE_PushButtonContents, opt, w)
        glyph = _inner_glyph(img, _rect_of(host, w))
        if cr.width() <= 0 or cr.height() <= 0 or glyph <= 0:
            bad.append(f"{oid}: 内容区={cr.width()}x{cr.height()} 字形={glyph}")
    try:
        host.close()
        host.deleteLater()
    except Exception:
        pass
    assert not bad, f"{theme}: 定尺寸按钮仍不可见 -> {bad}"


@pytest.mark.parametrize("theme", THEMES)
def test_wp1_vector_icon_path_renders_glyph(qapp, isolated_env, theme):
    r"""矢量图标分支**也要**看得见 —— 复位带来的覆盖缺口在此显式补回。

    `_deterministic_icons_state` 把 `gui.icons` 复位到「未注册」的确定态（= 本文件
    单跑时的自然态），于是 WP1 的 `feedbackSpark` 走 emoji 兜底分支。本用例按
    **产品自身的启动顺序**（`gui/main.py:1640` 的 `icons.configure(app_ctx)`，加上
    字体注册）显式建立矢量态，证明矢量分支同样画得出可见图形 ——
    两条路径都测，不是二选一（不弱化、不 skip、不删任何既有用例）。

    ⚠ 这里 `icons.configure(ctx)` 是**必需**的：不注入 app_ctx 时
      `icons.icon(name, size, None)` 取色回落 `#000000`，深色主题（ui_night 宿主
      底色实测 `#131114`）上不可见 —— 那正是复位前那条「随跑序变红」的机制本身。
      复位把不确定性**收口**掉了，本用例把矢量分支**重新钉住**。
    """
    from gui import icons
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.theme_engine import ThemeEngine
    from gui.widgets.proactive_feedback import ProactiveFeedbackBar

    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(4)
    cfg = GuiConfig()
    cfg.first_run = False
    ctx = AppContext(config=cfg)
    ctx.theme_engine = engine

    family = icons.register_icon_font()
    assert family, "图标字体注册失败 —— 矢量分支在这里无从谈起（前置条件不成立）"
    icons.configure(ctx)                       # 与 gui/main.py:1640 同款
    assert icons.available(), "register_icon_font() 之后 available() 仍为假"

    bar = ProactiveFeedbackBar("s", "sc", None)
    bar.resize(320, 30)
    host = QWidget()
    host.setObjectName("wp1VectorHost")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.addWidget(bar)
    host.resize(400, 90)
    host.ensurePolished()
    lay.activate()
    _pump(10)
    try:
        spark = bar._spark
        assert spark is not None, "非 persistent 模式下 _spark 应存在"
        assert (spark.width(), spark.height()) == WP1_SIZES["feedbackSpark"], (
            f"{theme}: feedbackSpark 尺寸被改动 "
            f"{(spark.width(), spark.height())} != {WP1_SIZES['feedbackSpark']}")
        assert not spark.icon().isNull(), (
            f"{theme}: feedbackSpark 未走矢量图标分支（icon 为空）—— 本用例前提不成立")
        assert spark.text() == "", (
            f"{theme}: feedbackSpark 带了回退文本 {spark.text()!r} —— 未走矢量分支")
        img = host.grab().toImage()
        glyph = _inner_glyph(img, _rect_of(host, spark))
        assert glyph > 0, (
            f"{theme}: 矢量图标分支下 feedbackSpark 字形={glyph}（图标颜色与底色撞了"
            f"或未绘制）—— 矢量路径失去了可见性覆盖")
    finally:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass
        _pump(4)


@pytest.mark.parametrize("theme", THEMES)
def test_wp1_geometry_and_control_sheets_untouched(qapp, isolated_env, theme):
    """只收 padding：尺寸不变、控件级 sheet 里不得出现第二处 padding 收口点。"""
    host, widgets = _wp1_widgets(theme)
    try:
        for oid, w in widgets:
            assert (w.width(), w.height()) == WP1_SIZES[oid], (
                f"{theme}/{oid}: 尺寸被改动 {(w.width(), w.height())} != {WP1_SIZES[oid]}")
            assert "padding" not in w.styleSheet(), (
                f"{theme}/{oid}: 控件级 sheet 里出现了 padding —— "
                f"本修复统一走 base.qss 的 id 规则，不得出现第二处收口点：{w.styleSheet()!r}")
    finally:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass


def test_wp1_metric_detects_padding_defect(qapp, isolated_env):
    """**非空转守卫**：通用 padding 下的同尺寸按钮必须被判「内容区 ≤ 0 且无字形」。"""
    _engine("ui_minimal")
    host = QWidget()
    lay = QHBoxLayout(host)
    b = QPushButton("+")
    b.setObjectName("wp1ControlNoRule")     # 不在 §1e-bis 白名单里
    b.setFixedSize(28, 28)
    lay.addWidget(b)
    host.resize(120, 60)
    host.ensurePolished()
    lay.activate()
    _pump(8)
    img = host.grab().toImage()
    opt = QStyleOptionButton()
    b.initStyleOption(opt)
    cr = b.style().subElementRect(QStyle.SE_PushButtonContents, opt, b)
    glyph = _inner_glyph(img, _rect_of(host, b))
    host.close()
    # 判据是**内容区任意一边 ≤ 0**：28×28 上通用 padding 左右各吃 20px → 宽 -12
    # （高仍为 12，因为上下 8+8=16 < 28）。任一边非正 ⇒ 字形无处可画。
    assert cr.width() <= 0 or cr.height() <= 0, (
        f"判据失效：通用 padding 下内容区竟是 {cr.width()}x{cr.height()}（应至少一边 ≤ 0）")
    assert glyph == 0, f"判据失效：通用 padding 下竟画出 {glyph} 个字形像素"


# ===========================================================================
# WP2 —— 毛玻璃切页黑屏
# ===========================================================================
def _page_of(win, key):
    return win.pages.get(key)


def test_wp2_glass_on_skips_page_fade(glass_window, monkeypatch):
    """毛玻璃开：切页**不得**走 motion.fade，且不得留下任何 opacity effect。"""
    import gui.motion as motion
    win = glass_window
    assert win.property("glass") == "on", "前提失效：玻璃未生效，本用例无意义"

    calls = []
    real_fade = motion.fade

    def _spy(*a, **kw):
        calls.append((a, kw))
        return real_fade(*a, **kw)

    monkeypatch.setattr(motion, "fade", _spy)
    win.page_manager.navigate("settings")
    _pump(6)
    win.page_manager.navigate("plan")
    _pump(6)
    page = _page_of(win, "plan")
    assert not calls, f"glass=on 时仍调用了 motion.fade（{len(calls)} 次）→ 会复现起帧黑屏"
    assert page.graphicsEffect() is None, "glass=on 切页后新页仍挂着 opacity effect"
    assert not win._page_fade_anims, "glass=on 切页后仍留有在跑的淡入动画"


def test_wp2_glass_off_keeps_page_fade(glass_window, monkeypatch):
    """毛玻璃关：淡入必须保住（v2.1 动效特性不得被本次修复削掉）。"""
    import gui.motion as motion
    win = glass_window
    win.setProperty("glass", None)
    _pump(4)
    calls = []
    real_fade = motion.fade

    def _spy(*a, **kw):
        calls.append(kw.get("to"))
        return real_fade(*a, **kw)

    monkeypatch.setattr(motion, "fade", _spy)
    try:
        win.page_manager.navigate("settings")
        _pump(6)
        win.page_manager.navigate("home")
        _pump(6)
        assert calls, "glass=off 时不再调用 motion.fade → 淡入被误删"
    finally:
        win.setProperty("glass", "on")
        _pump(4)


def test_wp2_drop_page_fades_clears_leftover(glass_window):
    """切页中途残留（opacity<1 的 effect）必须被 _drop_page_fades 收干净。"""
    win = glass_window
    win.page_manager.navigate("plan")
    _pump(6)
    page = _page_of(win, "plan")
    eff = QGraphicsOpacityEffect(page)
    eff.setOpacity(0.0)
    page.setGraphicsEffect(eff)
    assert page.graphicsEffect() is not None
    win._page_fade_anims[page] = type("_FakeAnim", (), {"stop": staticmethod(lambda: None)})()
    win._drop_page_fades()
    assert page.graphicsEffect() is None, "残留的 opacity effect 未被移除 → 页面会停在半透明"
    assert not win._page_fade_anims, "_page_fade_anims 未清空"


def test_wp2_candidates_cover_stack_children(glass_window):
    """口径守卫：_drop_page_fades 的候选集必须覆盖 page_stack 直接子级（含晚入栈页）。"""
    win = glass_window
    stack = win.page_stack
    assert isinstance(stack, QStackedWidget)
    kids = [stack.widget(i) for i in range(stack.count())]
    assert len(kids) >= len(win.pages), (
        f"page_stack 子级 {len(kids)} < pages {len(win.pages)} → 候选集口径判断失效")


# ===========================================================================
# WP3 —— 焦点黑框
# ===========================================================================
def test_wp3_qss_focus_rules_in_place():
    """base.qss 的两条新规则必须在位，且旧近黑规则不得复活。"""
    qss = BASE_QSS.read_text(encoding="utf-8")
    assert re.search(r"QPushButton:focus\s*\{\s*outline:\s*none;\s*\}", qss), (
        "base.qss 缺少 `QPushButton:focus { outline: none; }`（鼠标路径零描边的前提）")
    assert re.search(
        r'QPushButton\[keyboardNav="true"\]:focus\s*\{\s*'
        r"outline:\s*1px solid \$\{text_on_accent\};\s*\}", qss), (
        'base.qss 缺少 `QPushButton[keyboardNav="true"]:focus { outline: 1px solid '
        "${text_on_accent}; }`（键盘可达性的唯一落点）")
    assert "outline: 1px solid ${text};" not in qss, (
        "base.qss 仍残留以 text 描边的按钮焦点规则（旧规则复活 → 鼠标点击又会出现黑框）")
    assert not re.search(r"^\s*QSlider::handle:horizontal:focus\s*\{", qss, re.M), (
        "base.qss 仍有无条件生效的 `QSlider::handle:horizontal:focus` 规则 —— "
        "QSlider 默认 ClickFocus，鼠标一点就会出现近黑描边")
    assert re.search(
        r'QSlider\[keyboardNav="true"\]::handle:horizontal:focus\s*\{\s*'
        r"border:\s*2px solid \$\{text_on_accent\};\s*\}", qss), (
        "base.qss 缺少滑杆手柄的键盘焦点环规则")


def test_wp3_no_near_black_button_frame_anywhere():
    """全仓 qss 横扫：`:focus` 规则不得再以 `${text}` 给**可按下的控件**画框。

    唯一豁免 = `QTabBar::tab:selected:focus`（下划线；且 `QTabBar` 鼠标点击不给焦点）。
    """
    offenders = []
    for path in sorted((ROOT / "gui" / "themes").glob("*.qss")):
        for sel, decl in _qss_rules(path.read_text(encoding="utf-8")):
            flat = " ".join(sel.split())
            if ":focus" not in flat:
                continue
            if not re.search(r"(outline|border)[^:;]*:\s*[^;]*\$\{text\}", decl):
                continue
            if any(a in flat for a in _ALLOWED_NEAR_BLACK_FOCUS):
                continue
            offenders.append(f"{path.name} :: {flat}")
    assert not offenders, f"仍有近黑焦点框：{offenders}"


def _focus_host(theme: str):
    """两按钮宿主（真实应用级 QSS；`keyboardNav` 由用例按 eventFilter 的口径物化）。"""
    engine = _engine(theme)
    host = QWidget()
    host.setObjectName("wp3Host")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(16)
    b1 = QPushButton("确定")
    b1.setFixedSize(120, 36)
    b2 = QPushButton("取消")
    b2.setFixedSize(120, 36)
    lay.addWidget(b1)
    lay.addWidget(b2)
    host.resize(340, 96)
    host.show()
    host.activateWindow()
    _pump(10)
    return engine, host, b1, b2


@pytest.mark.parametrize("theme", THEMES)
def test_wp3_mouse_focus_no_ring(qapp, isolated_env, theme):
    """鼠标路径：**未聚焦态 ↔ 鼠标聚焦态逐像素相同**（0 差异 = 零描边、零位移）。"""
    _engine, host, b1, b2 = _focus_host(theme)
    b2.setFocus(Qt.MouseFocusReason)
    _pump(6)
    img0 = host.grab().toImage()
    b1.setFocus(Qt.MouseFocusReason)
    assert b1.hasFocus(), f"{theme}: 按钮没拿到焦点 → 本用例是假阴性，无意义"
    _force_kbd(b1, False)
    img1 = host.grab().toImage()
    n, new, _ = _frame_diff(img0, img1, _rect_of(host, b1, pad=3))
    host.close()
    assert n == 0, (f"{theme}: 鼠标聚焦后出现 {n} 个像素变化 "
                    f"{[(c, v) for c, v in new.most_common(3)]}（应为 0）")


@pytest.mark.parametrize("theme", THEMES)
def test_wp3_keyboard_focus_ring_visible_and_contrasting(qapp, isolated_env, theme):
    """键盘路径：仍有一圈可见指示，且颜色是 `${text_on_accent}`、对底色 ≥3:1。"""
    engine, host, b1, b2 = _focus_host(theme)
    ring = engine.get_color("text_on_accent", "").upper()
    assert ring, f"{theme}: 取不到 text_on_accent 令牌"
    b2.setFocus(Qt.MouseFocusReason)
    _pump(6)
    img0 = host.grab().toImage()
    b1.setFocus(Qt.TabFocusReason)
    assert b1.hasFocus(), f"{theme}: 按钮没拿到焦点 → 本用例是假阴性，无意义"
    _force_kbd(b1, True)
    img1 = host.grab().toImage()
    n, new, old = _frame_diff(img0, img1, _rect_of(host, b1, pad=3))
    host.close()
    acc = new.get(ring, 0)
    assert acc >= _MIN_RING_PX_HOST, (
        f"{theme}: 键盘焦点环未按 text_on_accent({ring}) 上屏（{acc} px < "
        f"{_MIN_RING_PX_HOST}）；实际新色 {[(c, v) for c, v in new.most_common(4)]}")
    under = old.most_common(1)[0][0]
    assert _ratio(ring, under) >= _MIN_RATIO, (
        f"{theme}: 键盘焦点环 {ring} 压在 {under} 上只有 {_ratio(ring, under):.2f}:1 "
        f"（< {_MIN_RATIO}）→ 键盘用户看不见")


@pytest.mark.parametrize("theme", THEMES)
def test_wp3_slider_mouse_focus_no_ring(qapp, isolated_env, theme):
    """滑杆（默认 ClickFocus）鼠标路径同样必须是逐像素零变化。"""
    _engine(theme)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(24, 24, 24, 24)
    s1, s2 = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
    for s in (s1, s2):
        s.setRange(0, 100)
        s.setValue(40)
        s.setFixedHeight(28)
        lay.addWidget(s)
    host.resize(360, 120)
    host.show()
    host.activateWindow()
    _pump(10)
    s2.setFocus(Qt.MouseFocusReason)
    _pump(6)
    img0 = host.grab().toImage()
    s1.setFocus(Qt.MouseFocusReason)
    assert s1.hasFocus(), f"{theme}: 滑杆没拿到焦点 → 本用例是假阴性，无意义"
    _force_kbd(s1, False)
    img1 = host.grab().toImage()
    n, new, _ = _frame_diff(img0, img1, _rect_of(host, s1, pad=4))
    host.close()
    assert n == 0, (f"{theme}: 滑杆鼠标聚焦后出现 {n} 个像素变化 "
                    f"{[(c, v) for c, v in new.most_common(3)]}（应为 0）")


@pytest.mark.parametrize("theme", THEMES)
def test_wp3_slider_keyboard_ring_visible(qapp, isolated_env, theme):
    """滑杆键盘路径：手柄上必须出现 `${text_on_accent}` 环（环宽 2px，纯像素 ≥40）。"""
    engine = _engine(theme)
    ring = engine.get_color("text_on_accent", "").upper()
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(24, 24, 24, 24)
    s1, s2 = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
    for s in (s1, s2):
        s.setRange(0, 100)
        s.setValue(40)
        s.setFixedHeight(28)
        lay.addWidget(s)
    host.resize(360, 120)
    host.show()
    host.activateWindow()
    _pump(10)
    s2.setFocus(Qt.MouseFocusReason)
    _pump(6)
    img0 = host.grab().toImage()
    s1.setFocus(Qt.TabFocusReason)
    assert s1.hasFocus(), f"{theme}: 滑杆没拿到焦点 → 本用例是假阴性，无意义"
    _force_kbd(s1, True)
    img1 = host.grab().toImage()
    n, new, _ = _frame_diff(img0, img1, _rect_of(host, s1, pad=4))
    host.close()
    acc = new.get(ring, 0)
    assert acc >= _MIN_SLIDER_RING_PX, (
        f"{theme}: 滑杆键盘焦点环未按 text_on_accent({ring}) 上屏（{acc} px < "
        f"{_MIN_SLIDER_RING_PX}）；实际新色 {[(c, v) for c, v in new.most_common(4)]}")


def test_wp3_event_filter_materialises_property(glass_window):
    """属性必须被**物化**（不能停在不存在的 None），且只在真变化时重刷。"""
    win = glass_window
    b = QPushButton("probe")
    b.setObjectName("wp3PropProbe")
    _pump(4)
    ev_tab = QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason)
    assert win.eventFilter(b, ev_tab) is False, "事件过滤器不得不吞事件"
    assert b.property(KBD_PROP) is True
    ev_mouse = QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason)
    win.eventFilter(b, ev_mouse)
    assert b.property(KBD_PROP) is False, "鼠标焦点未把属性落回 False"
    ev_short = QFocusEvent(QEvent.FocusIn, Qt.ShortcutFocusReason)
    win.eventFilter(b, ev_short)
    assert b.property(KBD_PROP) is True, "助记键焦点应视为键盘导航"
    ev_other = QFocusEvent(QEvent.FocusIn, Qt.ActiveWindowFocusReason)
    win.eventFilter(b, ev_other)
    assert b.property(KBD_PROP) is False, "窗口激活焦点不应算键盘导航"

    # 非空转关键点：**首次**焦点就是鼠标时必须把属性物化成 False。
    # 若把写入条件退回 ``bool(cur) != kbd``，``bool(None) != False`` 为假 → 漏写 →
    # 属性停在 None（QSS 同样的确不命中，但「鼠标路径被显式判定过」这件事就没被证明）。
    b_mouse = QPushButton("probe-mouse-first")
    win.eventFilter(b_mouse, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
    assert b_mouse.property(KBD_PROP) is False, (
        f"首次焦点即鼠标：keyboardNav 停在 {b_mouse.property(KBD_PROP)!r}（期望 False）")


def test_wp3_event_filter_covers_slider(glass_window):
    """`QSlider` 必须在过滤器的管辖类型里（否则滑杆那条规则永远不会命中）。"""
    win = glass_window
    s = QSlider(Qt.Horizontal)
    s.setObjectName("wp3SliderProbe")
    win.eventFilter(s, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert s.property(KBD_PROP) is True
    win.eventFilter(s, QFocusEvent(QEvent.FocusIn, Qt.MouseFocusReason))
    assert s.property(KBD_PROP) is False
    # 反向：不该被管的类型不得被写属性
    other = QWidget()
    win.eventFilter(other, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
    assert other.property(KBD_PROP) is None, "非白名单控件被误写 keyboardNav"


def test_wp3_exit_dialog_buttons(qapp, isolated_env, glass_window):
    """用户实拍场景：退出确认弹窗两个按钮 —— 鼠标无框、键盘有细环。"""
    engine = _engine("ui_minimal")
    ring = engine.get_color("text_on_accent", "").upper()
    box = QMessageBox()
    box.setWindowTitle("退出码铃？")
    box.setText("确定要退出码铃吗？\n\n退出后她就不会再主动问候你啦。")
    box.setIcon(QMessageBox.Question)
    yes_btn = box.addButton("退出", QMessageBox.AcceptRole)
    no_btn = box.addButton("再陪我一会", QMessageBox.RejectRole)
    box.show()
    box.activateWindow()
    _pump(10)

    # 鼠标聚焦 → 零描边
    no_btn.setFocus(Qt.MouseFocusReason)
    _pump(6)
    f0 = box.grab().toImage()
    yes_btn.setFocus(Qt.MouseFocusReason)
    assert yes_btn.hasFocus(), "退出弹窗按钮没拿到焦点 → 本用例无意义"
    _force_kbd(yes_btn, False)
    f1 = box.grab().toImage()
    n, new, _ = _frame_diff(f0, f1, _rect_of(box, yes_btn, pad=3))
    assert n == 0, f"退出弹窗按钮鼠标聚焦后出现 {n} 像素描边：{new.most_common(3)}"

    # 键盘聚焦（对照帧 = 同一按钮鼠标聚焦态）→ 细环 text_on_accent
    no_btn.setFocus(Qt.MouseFocusReason)
    _pump(8)
    g0 = box.grab().toImage()
    no_btn.setFocus(Qt.TabFocusReason)
    _force_kbd(no_btn, True)
    g1 = box.grab().toImage()
    n2, new2, _ = _frame_diff(g0, g1, _rect_of(box, no_btn, pad=3))
    box.close()
    acc = new2.get(ring, 0)
    assert acc >= _MIN_RING_PX, (
        f"退出弹窗键盘焦点环未上屏为 text_on_accent({ring})：{new2.most_common(4)}")


def test_wp3_metric_detects_old_rule(qapp, isolated_env):
    """**非空转守卫**：把旧规则写回控件级 sheet，渲染判据必须抓得到（近黑环）。"""
    engine = _engine("ui_minimal")
    near_black = engine.get_color("text", "").upper()
    host = QWidget()
    lay = QHBoxLayout(host)
    b1 = QPushButton("测试")
    b1.setObjectName("wp3OldRule")
    b1.setFixedSize(120, 36)
    b2 = QPushButton("别处")
    b2.setFixedSize(120, 36)
    lay.addWidget(b1)
    lay.addWidget(b2)
    b1.setStyleSheet(f"QPushButton#wp3OldRule:focus {{ outline: 1px solid {near_black}; }}")
    host.resize(330, 90)
    host.show()
    host.activateWindow()
    _pump(10)
    b2.setFocus(Qt.MouseFocusReason)
    _pump(6)
    img0 = host.grab().toImage()
    b1.setFocus(Qt.MouseFocusReason)
    _pump(8)
    img1 = host.grab().toImage()
    n, new, _ = _frame_diff(img0, img1, _rect_of(host, b1, pad=3))
    host.close()
    assert n > 0, "判据失效：旧规则（近黑描边）都没画出来 → 本组守卫在空转"
    assert new.get(near_black, 0) >= _MIN_RING_PX_HOST, (
        f"判据失效：旧规则描边颜色不是近黑 {near_black}：{new.most_common(3)}")


# ===========================================================================
# WP4（二轮补漏）—— 同类「定尺寸按钮被通用 padding 撑爆内容区」的剩余实例
# ===========================================================================
# 用户原话（二轮）：独立聊天浮窗一打开，标题栏与动作栏是「一整排空白方块」。
# 判据与 WP1 **同一条**（`SE_PushButtonContents` 任一边 ≤ 0），外加二轮新发现的
# **内容区残条**子类：44×36 的表情按钮内容区只剩 `2×18`，严格「字形 == 0」会漏判
# —— 残条态实测仍能挤出 4~11 个字形像素。故判据扩为
# `w <= 0 or h <= 0 or w <= 4 or h <= 4`（**只在残条仍无字形的实例上**成立）。
#
# ⚠ 反向证据 —— 这是**不许**顺手铺开 `padding: 0` 的原因（二轮实测）：
#   · 主窗 `sendBtn`（128×40）靠 `padding: 8px 24px` + `min-width: 80px` 撑版式，
#     补 `padding: 0` 后内容区反而变坏（实测字形 214 → 0）；
#   · `exportChatBtn` / `tabModeBtn` / `expandChatBtn` / 主窗 `stopBtn` **本来就**
#     自带 `padding: 0px`（`ui_build._ss("tab_mode_btn"/"expand_btn"/"export_btn"/"stop_btn")`），
#     实测字形 22~94 px —— 它们从来不是本类缺陷，**一个字都不许动**。
# 所以本轮只对「实测内容区 ≤0 或残条且字形 ≈0」的实例加守卫，并补一条静态守卫
# 钉住「两处源文件里对应控件的控件级 sheet 都显式声明了 padding 归零」防回退。
#
# 布局契约（二轮实测，不得改动）：
#   ChatWindow 标题栏 `pin_btn`/`attach_btn` 28×28，`min_btn`/`max_btn`/`close_btn` 32×26，
#   发送/停止 40×40；两处表情面板各 12 个 44×36；主窗 `styleSwitchBtn` 32×28。
_WP4_SIZES = {
    "titlebar.pin_btn": (28, 28),
    "titlebar.attach_btn": (28, 28),
    "titlebar.min_btn": (32, 26),
    "titlebar.max_btn": (32, 26),
    "titlebar.close_btn": (32, 26),
    "send_btn": (40, 40),
    "stop_btn": (40, 40),
    "emoji": (44, 36),
    "styleSwitchBtn": (32, 28),
}
#: 「内容区残条」上界：任一边 ≤ 此值即视为被 padding 吃掉（WP1 判据的扩展子类）
_WP4_SLIVER = 4
#: 浮窗侧**必须仍在被测**的控件（v2.2.2 retarget）。
#: 背景：按用户 2026-09-16 指令「浮窗去掉表情，导出，语音」，原先在浮窗上的三个扁平文字
#: 按钮（`ChatWindow.emoji_btn` / `export_btn` / `voice_btn`）已删除，功能保留在聊天主面板。
#: 本清单是**删完之后**浮窗上剩下的全部图标位 —— 用「每一个都必须出现、且确实被量到」
#: 替代「按 id 取唯一实例」，防止将来有人缩减清单让断言静默变窄（少测 = 覆盖静默丢失）。
_WP4_CHAT_WINDOW_TITLEBAR = ("pin_btn", "attach_btn", "min_btn", "max_btn", "close_btn")
_WP4_CHAT_WINDOW_REQUIRED = (
    *["titlebar." + a for a in _WP4_CHAT_WINDOW_TITLEBAR],
    "send_btn",
    "stop_btn",
)
#: `_wp4_chat_window()` 应产出的控件总数 —— **按现状实测写死**。
#: v2.2.2(retarget·用户 2026-09-16 指令「浮窗表情入口 + 面板一并移除」)：浮窗那个表情面板
#: （12 格 QPushButton）已删除 ⇒ 5 个标题栏 + 发送 + 停止 = **7**（原为 19 = 7 + 12 格）。
#: ⚠ 不得为了让旧数字 19 过关而放宽本断言 —— 那正是「把守卫改弱」。
#: 那 12 格的不变量由**主面板自己那套表情面板**继续承担（`ChatPanelWidget.EMOJIS`
#: 同样是 12 格 44×36，见 `test_wp4_main_panel_emoji_grid_render_glyph` 与
#: `test_wp4_main_panel_emoji_grid_sheet_declares_zero_padding`）。
_WP4_CHAT_WINDOW_ITEM_COUNT = 7
#: **主面板**自己那套表情面板的格子数（retarget 的承接方）：`ChatPanelWidget.EMOJIS`
#: 实测 12 项，与浮窗被删的那 12 格**同数量同契约**（44×36）。按现状写死，不写成
#: `len(panel.EMOJIS)` —— 否则产品侧少放几个 emoji 时断言会跟着"自动通过"。
_WP4_PANEL_EMOJI_COUNT = 12
#: WP4 静态守卫锚点：(相对仓库路径, 源码锚点, 锚点后检索窗口字符数)
#: 窗口逐个卡到「刚好覆盖该控件自己的 sheet、且够不到邻座控件」的宽度
#: （实测各锚点距其 `padding: 0px` 的字符距离：799 / 472 / 1722 / 966 / 670 /
#:   397 / 335 / 267 / 75；窗口取略大于该距离且小于「到下一个 padding 的距离」），
#: 避免窗口过大导致邻座控件的 `padding: 0px` 把这一条假绿。
_WP4_SHEET_ANCHORS = (
    ("gui/widgets/chat_window.py", "_idle_tool_button_qss(self, hover_color_key: str)", 1000),
    ("gui/widgets/chat_window.py", "_pinned_tool_button_qss(self)", 700),
    ("gui/widgets/chat_window.py", "def _apply_title_button_theme(self)", 2000),
    # v2.2.2(retarget)：原在此处的两条锚点 —— `self.emoji_panel = QWidget()`(窗口 1100) 与
    #   `for _b in self.emoji_panel.findChildren(QPushButton)`(窗口 500) —— 钉的是**浮窗那个
    #   表情面板**；用户 2026-09-16 指令「浮窗表情入口 + 面板一并移除」后这些行将不存在。
    #   同样的不变量（表情格子必须 padding 归零）已改钉到**主面板自己那套表情面板**上，
    #   见 `test_wp4_main_panel_emoji_grid_sheet_declares_zero_padding()`（且那条更强：
    #   除 `padding: 0px` 外还断言 sheet **确实下发给**格子，不是定义了没人用）。
    ("gui/widgets/chat_window.py", "self.stop_btn.setStyleSheet(", 800),
    ("gui/widgets/chat_window.py", "self.send_btn.setStyleSheet(", 600),
    ("gui/widgets/chat_panel_parts/ui_build.py", "_emoji_css = (", 400),
    ("gui/widgets/chat_panel_parts/ui_build.py", '_ss("style_btn"', 200),
)


def test_wp4_control_sheets_declare_zero_padding():
    """静态：WP4 每个落点的控件级 sheet 都必须显式 `padding: 0px`（防回退）。"""
    for rel, anchor, span in _WP4_SHEET_ANCHORS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        idx = text.find(anchor)
        assert idx >= 0, f"{rel}: 找不到锚点 {anchor!r}（口径判断失效）"
        seg = text[idx:idx + span]
        assert re.search(r"padding\s*:\s*0px\s*;", seg), (
            f"{rel}: 锚点 {anchor!r} 之后的控件级 sheet 没有把 padding 归零 —— "
            f"该控件会被应用级通用 `QPushButton` 的 `padding: 8px 20px` 重新撑爆内容区")


def test_wp4_sibling_buttons_untouched():
    """反向守卫：**不是**本类缺陷的同排兄弟按钮不得被顺手改。

    同排 32×28 的三个兄弟（`tab_mode_btn` / `expand_btn` / `export_btn`）与
    `style_btn` 本就各自声明 `padding: 0px`；而**大按钮** `sendBtn`(128×40)、
    `stopBtn`(84×40) 是刻意保留 padding 撑版式的反例（实测字形 72 / 94 px，合格），
    谁把它们归零谁就把内容区弄坏。
    """
    text = (ROOT / "gui" / "widgets" / "chat_panel_parts" / "ui_build.py").read_text(
        encoding="utf-8")
    for name in ("tab_mode_btn", "expand_btn", "export_btn", "style_btn"):
        i = text.find(f'_ss("{name}"')
        assert i >= 0, f"ui_build.py 找不到 _ss({name!r})"
        seg = text[i:i + 900]
        assert re.search(r"padding\s*:\s*0px\s*;", seg), (
            f"_ss({name!r}) 的 sheet 丢了 padding 归零 —— 该按钮 32×28，"
            f"会被通用 padding 压掉内容区")
    # 反向：大按钮必须**保留**自己的 padding
    i = text.find('_ss("stop_btn"')
    assert i >= 0, "ui_build.py 找不到 _ss('stop_btn')"
    assert re.search(r"padding\s*:\s*6px\s+16px\s*;", text[i:i + 900]), (
        "`#stopBtn`(84×40) 的 padding 被改动了 —— 它靠 padding: 6px 16px 撑版式，"
        "实测字形 94 px 本就合格，不属于本类缺陷")
    base = BASE_QSS.read_text(encoding="utf-8")
    assert not re.search(r"QPushButton#sendBtn\s*\{[^}]*padding\s*:\s*0", base), (
        "base.qss 把主窗 `#sendBtn` 的 padding 归零了 —— 实测该按钮会从 72 个字形"
        "像素掉到 0（反向证据：128×40 靠 padding + min-width 撑版式）")


def _wp4_chat_window(theme: str):
    """真 `ChatWindow`（停止按钮显式打开）→ ``(cw, [(标签, 控件)])``。

    v2.2.2(retarget·用户 2026-09-16 指令「浮窗表情入口 + 面板一并移除」)：原先这里会
    `cw.emoji_panel.setVisible(True)` 去强开那个面板、再枚举它的 12 格 —— 面板已删，
    强开与那 12 格一并摘掉（那 12 格的不变量改由**主面板自己那套表情面板**承担，
    见 `test_wp4_main_panel_emoji_grid_render_glyph`）。清单不缩水的守卫不靠「本函数
    会返回什么」，而靠调用方的 `_WP4_CHAT_WINDOW_ITEM_COUNT` == 7 + 必需项齐全。
    """
    import gui.glass as glass
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.theme_engine import ThemeEngine
    from gui.widgets.chat_window import ChatWindow

    originals = {}
    for name, fake in (
        ("is_supported", lambda: True),
        ("detect_capability", lambda: gui_glass_cap()),
        ("safe_apply", lambda hwnd, kind, *, dark: True),
        ("remove", lambda hwnd: True),
    ):
        originals[name] = getattr(glass, name)
        setattr(glass, name, fake)
    try:
        cfg = GuiConfig()
        cfg.first_run = False
        cfg.auto_check = False
        cfg.tts_enabled = False
        cfg.pet_enabled = False
        cfg.glass_popups_enabled = False
        engine = ThemeEngine()
        engine.load_theme(theme)
        _pump(4)
        ctx = AppContext(config=cfg)
        ctx.theme_engine = engine
        cw = ChatWindow(ctx)
        cw.resize(520, 720)
        cw.show()
        cw.stop_btn.setVisible(True)      # 未生成中默认隐藏，但要量它的内容区
        _pump(10)
        _activate_deep(cw)
        cw.grab()
        _pump(4)
        items = [(f"titlebar.{a}", getattr(cw, a)) for a in _WP4_CHAT_WINDOW_TITLEBAR]
        items.append(("send_btn", cw.send_btn))
        items.append(("stop_btn", cw.stop_btn))
        return cw, items
    finally:
        for name, fn in originals.items():
            setattr(glass, name, fn)


def gui_glass_cap():
    import gui.glass as glass
    return glass.GlassCapability(True, "mica", 22621, "test-stub")


def _activate_deep(w):
    """逐层 activate 布局（否则内部控件尺寸是未布局的陈旧值）。"""
    for _ in range(3):
        lay = w.layout()
        if lay is not None:
            lay.activate()
        for c in w.findChildren(QWidget):
            cl = c.layout()
            if cl is not None:
                cl.activate()
        _pump(4)


@pytest.mark.parametrize("theme", THEMES)
def test_wp4_chat_window_controls_render_glyph(qapp, isolated_env, theme):
    """渲染级：独立浮窗标题栏 / 动作栏 / 表情面板**无空白方块**（四主题）。

    v2.2.2(retarget)：用户 2026-09-16 指令「浮窗去掉表情，导出，语音」后，浮窗上原先
    被本类判据覆盖的 `emoji_btn` / `export_btn` / `voice_btn` 已不存在 —— 但它们**从未**
    出现在本用例的清单里（本用例覆盖的是标题栏五个、发送 / 停止、表情面板 12 个）。
    为免「清单被悄悄改窄」使本用例静默失去覆盖，这里显式钉住：
    ① 控件总数 == `_WP4_CHAT_WINDOW_ITEM_COUNT`；② 必须项一个不少；③ 必须项不得被
    「不可见 ⇒ continue」跳过（跳过等于没量）。
    """
    cw, items = _wp4_chat_window(theme)
    labels = [lab for lab, _ in items]
    assert len(items) == _WP4_CHAT_WINDOW_ITEM_COUNT, (
        f"{theme}: 浮窗被测控件数 {len(items)} != {_WP4_CHAT_WINDOW_ITEM_COUNT} —— "
        f"清单被改动（少测即失去覆盖）：{labels}")
    missing = [lab for lab in _WP4_CHAT_WINDOW_REQUIRED if lab not in labels]
    assert not missing, f"{theme}: 浮窗清单丢了 {missing}（实得 {labels}）"
    img = cw.grab().toImage()
    bad, skipped = [], []
    for label, w in items:
        if not w.isVisibleTo(cw):
            skipped.append(label)
            continue
        opt = QStyleOptionButton()
        w.initStyleOption(opt)
        cr = w.style().subElementRect(QStyle.SE_PushButtonContents, opt, w)
        glyph = _inner_glyph(img, _rect_of(cw, w))
        if (cr.width() <= _WP4_SLIVER or cr.height() <= _WP4_SLIVER) or glyph <= 0:
            bad.append(f"{label}: 内容区={cr.width()}x{cr.height()} 字形={glyph}")
    try:
        cw.close()
        cw.deleteLater()
    except Exception:
        pass
    not_measured = [lab for lab in _WP4_CHAT_WINDOW_REQUIRED if lab in skipped]
    assert not not_measured, (
        f"{theme}: 以下浮窗控件不可见 ⇒ 根本没被量到（覆盖静默丢失）：{not_measured}")
    assert not bad, f"{theme}: 浮窗仍有空白方块 -> {bad}"


@pytest.mark.parametrize("theme", THEMES)
def test_wp4_chat_window_geometry_untouched(qapp, isolated_env, theme):
    """只收 padding：浮窗各控件尺寸必须仍是布局契约值。

    v2.2.2(retarget)：先钉住「清单没缩水」（总数 7 + 必须项都在），否则清单一空
    `for` 循环就对空集恒真 —— 那正是本类断言最容易被静默改弱的形态。
    表情面板 12 格的 44×36 契约改由 `test_wp4_main_panel_emoji_grid_render_glyph`
    在主面板那套上继续守（`_WP4_SIZES["emoji"]` 仍是同源契约值）。
    """
    cw, items = _wp4_chat_window(theme)
    labels = [lab for lab, _ in items]
    assert len(items) == _WP4_CHAT_WINDOW_ITEM_COUNT, (
        f"{theme}: 浮窗被测控件数 {len(items)} != {_WP4_CHAT_WINDOW_ITEM_COUNT} —— "
        f"清单被改动（少测即失去覆盖）：{labels}")
    missing = [lab for lab in _WP4_CHAT_WINDOW_REQUIRED if lab not in labels]
    assert not missing, f"{theme}: 浮窗清单丢了 {missing}（实得 {labels}）"
    try:
        for label, w in items:
            assert (w.width(), w.height()) == _WP4_SIZES[label], (
                f"{theme}/{label}: 尺寸被改动 {(w.width(), w.height())} != {_WP4_SIZES[label]}")
    finally:
        try:
            cw.close()
            cw.deleteLater()
        except Exception:
            pass


def test_wp4_chat_window_removed_flat_buttons_absent(qapp, isolated_env):
    """**固化用户决定**：浮窗上不再有「表情 / 导出 / 语音」三个扁平文字按钮。

    用户 2026-09-16 指令：**浮窗去掉表情，导出，语音**。三项功能保留在聊天主面板
    （导出 `#exportChatBtn`、表情 / 语音 `#quickActionBtn`），故浮窗侧这三个属性
    **必须不存在** —— 将来若被手滑加回来，本用例必须红（而不是只靠「清单里没有」这种
    会静默漂移的口径）。

    同时反向钉住「功能真的还在主面板」：主面板那三个控件必须仍可取到，否则就成了
    「两边都没有」——那才是真丢失。
    """
    cw, _items = _wp4_chat_window("ui_minimal")
    host = panel = None
    try:
        for attr in ("emoji_btn", "export_btn", "voice_btn"):
            assert not hasattr(cw, attr), (
                f"ChatWindow 又出现了 {attr} —— 用户 2026-09-16 指令是浮窗去掉这三项，"
                f"功能保留在聊天主面板（#exportChatBtn / #quickActionBtn）")
        host, panel = _wp5_panel("ui_minimal")
        for attr, _label, oid in _WP5_PANEL_FLAT_ATTRS:
            assert getattr(panel, attr, None) is not None, (
                f"主面板也没有 {attr} —— 三个入口两边都丢了（用户只要求去掉浮窗那一套）")
    finally:
        for w in (host, cw):
            if w is None:
                continue
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass


def test_wp4_chat_window_emoji_panel_absent(qapp, isolated_env):
    """**固化用户决定**：浮窗上不再有那个 12 格表情面板（`ChatWindow.emoji_panel`）。

    用户 2026-09-16 指令：浮窗表情入口（`emoji_btn`）**连同它那个面板一并移除**；
    表情功能保留在聊天主面板自己的表情面板上（`ChatPanelWidget.emoji_panel`，
    `ui_build.py:281-293` 构造，`#quickActionBtn` 开它、`_emoji_css` 给格子补 `padding:0`）。
    浮窗那 12 格在入口删掉后已**无任何路径可达**（面板 `setVisible(False)` 且不再有人
    调 `setVisible(True)`），留着只是死代码 —— 故此处钉死「属性不存在」，
    将来有人手滑加回来必须变红。

    同时反向钉住「功能真的还在主面板」：主面板那套表情面板与它的 12 格必须仍可取到，
    否则就成了「两边都没有」——那才是真丢失。
    """
    cw, _items = _wp4_chat_window("ui_minimal")
    host = panel = None
    try:
        assert not hasattr(cw, "emoji_panel"), (
            "ChatWindow 又出现了 emoji_panel —— 用户 2026-09-16 指令是浮窗表情入口与"
            "面板一并移除，功能保留在聊天主面板自己的表情面板上")
        host, panel = _wp4_panel_with_emoji("ui_minimal")
        grid = panel.emoji_panel.findChildren(QPushButton)
        assert len(grid) == _WP4_PANEL_EMOJI_COUNT, (
            f"主面板表情面板的格子数 {len(grid)} != {_WP4_PANEL_EMOJI_COUNT} —— "
            f"面板两边都丢了？")
    finally:
        for w in (host, cw):
            if w is None:
                continue
            try:
                w.close()
                w.deleteLater()
            except Exception:
                pass


def test_wp4_main_panel_emoji_grid_sheet_declares_zero_padding():
    """静态：主面板表情面板的格子控件级 sheet **必须**把 padding 归零（retarget 承接）。

    原先这条不变量钉在浮窗那个表情面板上（`chat_window.py` 的
    `self.emoji_panel = QWidget()` / `for _b in self.emoji_panel.findChildren(...)` 两条锚点）；
    浮窗面板按用户 2026-09-16 指令删除后，同样的不变量改钉**主面板自己那套**：
    格子 44×36，若 sheet 不归零 padding，通用 `QPushButton{padding:8px 20px}` 会把内容区
    压成 2×18、emoji 只剩 4~11 个像素（"一排空白方块"）。

    ⚠ 比旧锚点更强：除 `padding: 0px` 外，还断言该 sheet **确实下发给**格子
    （`_ssw(_b, _emoji_css)`）—— 防止「定义了 `_emoji_css` 却没人用」那种假绿。
    """
    text = (ROOT / "gui/widgets/chat_panel_parts/ui_build.py").read_text(encoding="utf-8")
    i = text.find("_emoji_css = (")
    assert i >= 0, "ui_build.py 找不到 `_emoji_css`（口径判断失效）"
    assert re.search(r"padding\s*:\s*0px\s*;", text[i:i + 400]), (
        "主面板表情格子的 `_emoji_css` 丢了 padding 归零 —— 44×36 的格子会被通用 "
        "`padding: 8px 20px` 压掉内容区")
    j = text.find("for _b in _emoji_panel.findChildren(QPushButton):")
    assert j >= 0, "ui_build.py 找不到表情格子的 sheet 下发点（口径判断失效）"
    assert re.search(r"_ssw\(\s*_b\s*,\s*_emoji_css\s*\)", text[j:j + 300]), (
        "`_emoji_css` 没有下发给表情面板的格子（定义了没人用 = 假绿）")


@pytest.mark.parametrize("theme", THEMES)
def test_wp4_main_panel_style_switch_btn_render_glyph(qapp, isolated_env, glass_window, theme):
    """主窗 `styleSwitchBtn`（🎨，32×28）—— 二轮前主窗里**唯一**的空白方块。

    量法用**控件自身** `grab()`（不是整窗 grab）：整窗图上该按钮可能被面板裁切／
    覆盖，实测会得到「内容区正常但字形 0」的假红（二轮踩过）。
    """
    from gui.theme_engine import ThemeEngine
    ThemeEngine().load_theme(theme)
    _pump(6)
    try:
        glass_window.page_manager.navigate("chat")
    except Exception:
        pass
    _activate_deep(glass_window)
    _pump(6)
    btn = None
    for p in glass_window.findChildren(QWidget):
        if p.__class__.__name__ == "ChatPanelWidget":
            btn = getattr(p, "style_btn", None)
            break
    assert btn is not None, "主窗里找不到 ChatPanelWidget.style_btn（口径判断失效）"
    assert btn.isVisibleTo(glass_window), (
        "styleSwitchBtn 当前不可见 —— 量到的尺寸是陈旧值，本用例会假红/假绿")
    opt = QStyleOptionButton()
    btn.initStyleOption(opt)
    cr = btn.style().subElementRect(QStyle.SE_PushButtonContents, opt, btn)
    glyph = _inner_glyph(btn.grab().toImage(), (0, 0, btn.width(), btn.height()))
    assert (btn.width(), btn.height()) == _WP4_SIZES["styleSwitchBtn"], (
        f"{theme}: styleSwitchBtn 尺寸被改动 {(btn.width(), btn.height())}")
    assert cr.width() > _WP4_SLIVER and cr.height() > _WP4_SLIVER, (
        f"{theme}: styleSwitchBtn 内容区被 padding 吃掉 {cr.width()}x{cr.height()}")
    assert glyph > 0, f"{theme}: styleSwitchBtn（🎨）一个字形像素都没画出来（字形={glyph}）"


# ===========================================================================
# WP5（三轮补漏）—— 第五判据：内容区高度 < 文字实际所需高度（= 部分裁切）
# ===========================================================================
# 为什么 WP1/WP4 的判据抓不到这一类：
#   WP1/WP4 判的是「内容区任一边 ≤ 0 或 ≤ 4」。而浮窗底部三个扁平文字按钮
#   （`emoji_btn` / `export_btn` / `voice_btn`）`setFixedHeight(24)` 且自身 sheet
#   **没有声明 padding** ⇒ 回落应用级 `QPushButton { padding: 8px 20px; }` ⇒
#   内容区实测 `40×8`：8 既 > 0 也 > 4，**两轮判据全部判它合格**。
#   但 12px 字实际需要 14 行墨迹（`QFontMetrics.height()` = 17）⇒ 上下各被硬裁，
#   实测墨迹只占内容区里的 8 行（补 `padding: 0px 20px` 后 14 行）。
#
# 第五判据 = **内容区高 < 实测墨迹行数**。三个必须遵守的口径：
#   ① 阈值**不能**取 `QFontMetrics.height()`：行高 17 > 墨迹 14，拿它当门槛会把
#      `sidebarBottomBtn`（内容区 16、墨迹 15、**没被裁**）判成缺陷 —— 假阳性满屏。
#      故用**实测墨迹行数**本身；本文用例取 `_MIN_INK_ROWS = 13`（14 留 1 行余量）。
#   ② 必须做**反事实**（补 padding / 加高控件，看墨迹行数是否变多），否则分不清
#      「真被裁」与「这控件本来就不需要那么高」。
#   ③ 墨迹像素的取色口径必须是「**被测区域自己的众数色**」：用整图众数会把按钮自身
#      底色 / 描边 / 圆角渗色算成墨迹；不裁内容区同理。有描边 / 圆角的按钮还要再取
#      **内容区横向中带**，否则 `border-radius` 的弧线会穿过内容区左右两侧、报出
#      「每一行都有墨迹」（`exportChatBtn` 32×28 上实测踩过）。
#
# 覆盖面（比前两轮更全，见 `_fix_blackbox/sweep5_before.txt`）：主窗 14 个页面键 +
# 独立浮窗 + 7 个对话框 × 四主题 × 明暗，**除 about 页那个按钮外无第二处命中**。
#
# ⚠ 一个**本判据自身**的已知假阳性（已定性，**不是**缺陷，不要再当缺陷报）：
#   `WIN:agent primaryBtn`（'保存角色'，128×36）在 **ui_whale/dark** 上会被算成
#   「内容区 80×20、墨迹 20 行铺满」。真因是 ui_whale.qss 给 `#primaryBtn` 画的是
#   **对角渐变**（`ui_whale.qss:577-584`，`qlineargradient(x1:0,y1:0,x2:1,y2:1,
#   stop:0 ${primary}, stop:1 ${focus_accent})`）⇒ 内容区里**没有**占多数的填充色，
#   众数票落到了文字色 `${text_on_accent}`（实测只占 15%）⇒ 自然「每一行都有差异」。
#   定性读数（`_fix_blackbox/primary_btn.txt`）：同一按钮改用「**整按钮**众数色」取纸色，
#   四档（ui_whale/ui_minimal × 明/暗）**一致**为**墨迹 14 行 / 内容区 20 行**、
#   bbox 59×14（= `textWidth` 60），即文字完整画得出来 ⇒ 无裁切、不需要改任何代码。
#
# ⚠ **v2.2.2(retarget)**：本段开头说的那三个浮窗扁平文字按钮（`emoji_btn` / `export_btn` /
#   `voice_btn`）已按用户 2026-09-16 指令「浮窗去掉表情，导出，语音」**删除**，三项功能
#   保留在聊天主面板。故本判据的样本搬到主面板（`#exportChatBtn` 32×28 / `#quickActionBtn`
#   定高 28），判据本体也从「固定门槛 `_MIN_INK_ROWS = 13`」改为**反事实**
#   （放宽高度后墨迹行数不得变多）：13 是 24px 定高 + 12px 字 + 中文文案那一档的标定值，
#   主面板这组实测只有 9~10 行，照搬会得到假红。实现见 `_wp5_clip_fault()`。
_MIN_INK_ROWS = 13
#: WP5(retarget) 主面板扁平文字按钮：(`ChatPanelWidget` 属性名, 文案, 来源 objectName)。
#: v2.2.2(用户指令 2026-09-16「浮窗去掉表情，导出，语音」)：三项功能从独立浮窗搬到聊天
#: 主面板 —— 导出 = `#exportChatBtn`（32×28，控件级 sheet 自带 `padding: 0`）；
#: 表情 / 语音 = `#quickActionBtn`（定高 28，无控件级 sheet，主题层 `padding: 2px 8px`）。
#: ⚠ 表情与语音**共用** objectName `quickActionBtn`（不是唯一 id）⇒ 只能按属性名取控件，
#:   不许写「按 id 取唯一实例」的断言。
_WP5_PANEL_FLAT_ATTRS = (
    ("export_btn", "📤 导出", "exportChatBtn"),
    ("emoji_btn", "😊 表情", "quickActionBtn"),
    ("voice_btn", "🎤 语音", "quickActionBtn"),
)
#: 反事实放宽的高度（px）。实测（四主题一致，曲线见 `_release_v220/_qa_wp1/probe_ink_curve.txt`）：
#: `#quickActionBtn` 定高 28 → 内容区 22 / 墨迹 9；加高 16px 后墨迹**仍是 9**
#: `#exportChatBtn`  32×28 → 内容区 26 / 墨迹 10；加高 16px 后墨迹**仍是 10**
#: ⇒ 「放宽高度后墨迹不再变多」可用来判「没被纵向裁字」。
_WP5_HEADROOM = 16
#: 四种底衬（深浅各半）：任何字色至少在其中一种上能拉开 >30 的通道差
_INK_BACKDROPS = ((0x80, 0x80, 0x80), (0x10, 0x10, 0x10),
                  (0xEF, 0xEF, 0xEF), (0xFF, 0xFF, 0xFF))


def _color_dist(a: str, b: str) -> int:
    a2, b2 = int(a[1:], 16), int(b[1:], 16)
    return max(abs(((a2 >> s) & 0xFF) - ((b2 >> s) & 0xFF)) for s in (0, 8, 16))


def _ink_rows(w, band: bool = False) -> int:
    """把控件渲染到四种底衬，数「有墨迹的**行数**」（取四档里最多的一次）。

    ``band=True`` 时只统计**内容区横向中带（中间 50%）**，用于有描边 / 圆角的按钮。
    """
    from PySide6.QtGui import QColor

    best = 0
    for rgb in _INK_BACKDROPS:
        img = QImage(max(1, w.width()), max(1, w.height()),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(*rgb))
        w.render(img)
        img = img.convertToFormat(QImage.Format_RGB32)
        iw, ih = img.width(), img.height()
        if band:
            opt = QStyleOptionButton()
            w.initStyleOption(opt)
            cr = w.style().subElementRect(QStyle.SE_PushButtonContents, opt, w)
            cw_, ch_ = max(0, cr.width()), max(0, cr.height())
            x0 = max(0, cr.x()) + cw_ // 4
            bw = max(1, cw_ // 2)
            y0, bh = max(0, cr.y()), ch_
        else:
            x0, y0, bw, bh = 0, 0, iw, ih
        bw, bh = min(bw, iw - x0), min(bh, ih - y0)
        if bw <= 0 or bh <= 0:
            continue
        hist: Counter = Counter()
        cache = {}
        for y in range(y0, y0 + bh):
            for x in range(x0, x0 + bw):
                c = img.pixelColor(x, y)
                h = "#%02X%02X%02X" % (c.red(), c.green(), c.blue())
                cache[(x, y)] = h
                hist[h] += 1
        modal = hist.most_common(1)[0][0]
        n = 0
        for y in range(y0, y0 + bh):
            if any(_color_dist(cache[(x, y)], modal) > 30 for x in range(x0, x0 + bw)):
                n += 1
        best = max(best, n)
    return best


def _contents_rect(w):
    opt = QStyleOptionButton()
    w.initStyleOption(opt)
    return w.style().subElementRect(QStyle.SE_PushButtonContents, opt, w)


def _relayout(w) -> None:
    """刷新 ``w`` 的父布局并泵事件（钉高 / 还原后都要调，否则量到的是陈旧尺寸）。"""
    p = w.parentWidget()
    lay = p.layout() if p is not None else None
    if lay is not None:
        lay.activate()
    _pump(4)


def _pin_height(b, h: int):
    """把控件高**钉到 ``h``**（含布局刷新）；返回原 ``(min, max)`` 以便还原。"""
    saved = (b.minimumHeight(), b.maximumHeight())
    b.setMinimumHeight(h)
    b.setMaximumHeight(h)
    _relayout(b)
    return saved


def _unpin_height(b, saved) -> None:
    b.setMinimumHeight(saved[0])
    b.setMaximumHeight(saved[1])
    _relayout(b)


def _ink_rows_at_height(b, h: int, band: bool = True):
    """钉高到 ``h`` 时量 ``(墨迹行数, 内容区矩形)``；量完**必定还原** min/max。

    必须还原：同一个控件会被本段多个用例复用，改了 min/max 不还原会污染后续读数。
    """
    saved = _pin_height(b, h)
    try:
        return _ink_rows(b, band=band), _contents_rect(b)
    finally:
        _unpin_height(b, saved)


def _wp5_panel(theme: str):
    """真 `ChatPanelWidget`（与 `_wp1_widgets` 同口径）→ ``(host, panel)``。

    需要连主面板自己的表情面板一起量时用 `_wp4_panel_with_emoji(theme)`（它会打开面板
    并把宿主加高）。
    """
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.theme_engine import ThemeEngine
    from gui.widgets.chat_panel import ChatPanelWidget

    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(4)
    cfg = GuiConfig()
    cfg.first_run = False
    ctx = AppContext(config=cfg)
    ctx.theme_engine = engine
    panel = ChatPanelWidget(ctx)
    panel.resize(760, 520)
    host = QWidget()
    host.setObjectName("wp5PanelHost")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(panel)
    host.resize(780, 560)
    host.show()
    lay.activate()
    if panel.layout() is not None:
        panel.layout().activate()
    _pump(12)
    _activate_deep(host)
    host.grab()
    _pump(4)
    return host, panel


def _wp4_panel_with_emoji(theme: str):
    """`_wp5_panel(theme)` + 打开主面板**自己的**表情面板 → ``(host, panel)``。

    v2.2.2(retarget)：浮窗那个表情面板被删后，12 格表情的不变量由此处承载。
    打开 12 格后内容变高，故把宿主窗口一并加高，避免格子被挤出可视区造成假红。
    """
    host, panel = _wp5_panel(theme)
    panel.emoji_panel.setVisible(True)
    host.resize(800, 900)
    _pump(12)
    _activate_deep(host)
    host.grab()
    _pump(4)
    return host, panel


def _wp5_clip_fault(b):
    """**第五判据本体**：合格返回 ``None``，被纵向裁字返回原因字符串。

    口径 = ① 内容区**宽高都**没被 padding 吃掉（> `_WP4_SLIVER`）；② 内容区高 ≥ 墨迹行数；
    ③ **反事实**：把高度放宽 `_WP5_HEADROOM` px 后墨迹行数**不得变多**（变多 ⇒ 当前高度
    正在把字裁掉）。
    ⚠ 宽也要查：`#exportChatBtn`(32×28) 一旦丢掉 `padding: 0px`，回落的通用
      `padding: 8px 20px` 会把内容区**宽**先压成 ≤0（高还有 10），只守高度会漏。
    ⚠ 不用固定门槛：旧的 `_MIN_INK_ROWS = 13` 是 24px 定高 + 12px 字那一档的标定值，
      主面板这组实测 9~10 行，照搬会假红。
    ⚠ 也不能只看「墨迹 > 0」：**部分**裁字（如 9 行掉到 7 行）墨迹仍 > 0，
      只有反事实那条才抓得住 —— 这正是 `test_wp5_flat_button_metric_is_not_vacuous`
      要证明的能力。
    """
    cr = _contents_rect(b)
    ink = _ink_rows(b, band=True)
    if cr.width() <= _WP4_SLIVER or cr.height() <= 0 or ink <= 0:
        return (f"内容区={cr.width()}x{cr.height()} 墨迹={ink} 行"
                f"（内容区被吃成残条 / 一个字形都画不出来）")
    ink_gen, cr_gen = _ink_rows_at_height(b, b.height() + _WP5_HEADROOM, band=True)
    if cr.height() < ink or ink < ink_gen:
        return (f"内容区={cr.width()}x{cr.height()} 墨迹={ink} 行；"
                f"放宽 {_WP5_HEADROOM}px 后内容区高 {cr_gen.height()}、墨迹={ink_gen} 行"
                f"（fm.height={b.fontMetrics().height()}）")
    return None


@pytest.mark.parametrize("theme", THEMES)
def test_wp5_flat_text_buttons_not_clipped(qapp, isolated_env, theme):
    """渲染级：主面板扁平文字按钮（导出 / 表情 / 语音）**不被纵向裁字**（四主题）。

    v2.2.2(retarget·用户指令 2026-09-16「浮窗去掉表情，导出，语音」)：这三个入口原先在
    独立浮窗上（`ChatWindow.emoji_btn` / `export_btn` / `voice_btn`，`setFixedHeight(24)`，
    正是 WP1/WP4 判据的盲区 —— 内容区 `40×8` 既非 ≤0 也非 ≤4，连漏两轮）。三按钮已删、
    功能保留在聊天主面板，故本判据随入口**搬到主面板那一套**（`#exportChatBtn` 32×28、
    `#quickActionBtn` 定高 28），覆盖不缩水；浮窗侧「这三个确实没了」由新建的
    `test_wp4_chat_window_removed_flat_buttons_absent` 反向钉住。
    """
    host, panel = _wp5_panel(theme)
    bad = []
    try:
        for attr, label, oid in _WP5_PANEL_FLAT_ATTRS:
            b = getattr(panel, attr, None)
            assert b is not None, f"{theme}: ChatPanelWidget 没有 {attr}（口径判断失效）"
            assert b.objectName() == oid, (
                f"{theme}: {attr} 的 objectName 是 {b.objectName()!r}，期望 {oid!r}"
                f"（口径判断失效）")
            assert b.isVisibleTo(host), (
                f"{theme}: {label}(#{oid}) 当前不可见 —— 量到的是陈旧尺寸，本用例会假红/假绿")
            why = _wp5_clip_fault(b)
            if why is not None:
                bad.append(f"{label}(#{oid}) {why}")
    finally:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass
    assert not bad, (
        f"{theme}: 主面板扁平文字按钮仍被纵向裁字 -> {bad}；"
        f"判据见 `_wp5_clip_fault()`（内容区高 ≥ 墨迹行数 + 放宽高度后墨迹不得变多）")


@pytest.mark.parametrize("theme", THEMES)
def test_wp4_main_panel_emoji_grid_render_glyph(qapp, isolated_env, theme):
    """渲染级：**主面板**自己那套表情面板的 12 格不出现空白方块（四主题）。

    v2.2.2(retarget·用户 2026-09-16 指令「浮窗表情入口 + 面板一并移除」)：原先那 12 格
    在浮窗面板上（`ChatWindow.emoji_panel`，`_wp4_chat_window` 会强开它）；面板已删，
    同样的 12 格不变量改由**主面板那套**承担 —— 格子数、44×36 契约、
    「sheet 把 padding 归零」三项一一对位（见
    `test_wp4_main_panel_emoji_grid_sheet_declares_zero_padding`）。

    ⚠ 量法用**整窗 grab 后裁切**（`_inner_glyph(host.grab(), _rect_of(host, b))`），
      **不用**子控件单独 `grab()`：本仓实测子控件单 grab 不可信（同一组标题栏键
      单 grab 得 1/17/12，整窗裁切得 22/54/86）。
    """
    host, panel = _wp4_panel_with_emoji(theme)
    try:
        grid = panel.emoji_panel.findChildren(QPushButton)
        assert len(grid) == _WP4_PANEL_EMOJI_COUNT, (
            f"{theme}: 主面板表情面板格子数 {len(grid)} != {_WP4_PANEL_EMOJI_COUNT} "
            f"—— 清单被改窄会让下面的循环对空集恒真")
        assert panel.emoji_panel.isVisibleTo(host), (
            f"{theme}: 表情面板没打开 —— 量到的是陈旧尺寸，本用例会假红/假绿")
        img = host.grab().toImage()
        bad = []
        for i, b in enumerate(grid):
            assert b.isVisibleTo(host), (
                f"{theme}/emoji[{i:02d}]: 格子不可见 ⇒ 根本没被量到（覆盖静默丢失）")
            assert (b.width(), b.height()) == _WP4_SIZES["emoji"], (
                f"{theme}/emoji[{i:02d}]: 尺寸被改动 {(b.width(), b.height())} "
                f"!= {_WP4_SIZES['emoji']}")
            cr = _contents_rect(b)
            glyph = _inner_glyph(img, _rect_of(host, b))
            if (cr.width() <= _WP4_SLIVER or cr.height() <= _WP4_SLIVER) or glyph <= 0:
                bad.append(f"emoji[{i:02d}] {b.text()!r}: 内容区={cr.width()}x{cr.height()} "
                           f"字形={glyph}")
        assert not bad, f"{theme}: 主面板表情面板仍有空白方块 -> {bad}"
    finally:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass


def test_wp5_flat_button_metric_is_not_vacuous(qapp, isolated_env):
    """**非空转守卫**：判据本体必须抓得住「**部分**裁字」（而不是只能抓全黑）。

    v2.2.2(retarget)：样本换成**主面板真实控件** `#quickActionBtn`（`emoji_btn`，定高 28，
    主题层 `padding: 2px 8px`）。实测曲线（ui_minimal / ui_whale 一致，
    `_release_v220/_qa_wp1/probe_ink_curve.txt`）：
        h=28 → 内容区 22 / 墨迹 9   ← 自然档，判据必须判**合格**
        h=14 → 内容区  8 / 墨迹 7   ← **部分裁字**（墨迹仍 > 0，就是「8 > 4」那类盲区）
        h= 6 → 内容区  0 / 墨迹 0
    本用例用**同一个判据函数** `_wp5_clip_fault()` 对上面三档各判一次：自然档须合格，
    人为压矮的两档须报红。若判据退化成「只看墨迹 = 0」，h=14 这一档就会漏 ⇒ 本用例红。
    """
    host, panel = _wp5_panel("ui_minimal")
    try:
        b = panel.emoji_btn
        assert b.isVisibleTo(host), "emoji_btn 不可见 —— 量到的是陈旧尺寸（口径失效）"
        ink_nat = _ink_rows(b, band=True)
        why_nat = _wp5_clip_fault(b)
        ink_after = _ink_rows(b, band=True)
        saved = _pin_height(b, 14)
        ink_partial = _ink_rows(b, band=True)
        why_partial = _wp5_clip_fault(b)
        _unpin_height(b, saved)
        saved = _pin_height(b, 6)
        ink_zero = _ink_rows(b, band=True)
        why_zero = _wp5_clip_fault(b)
        _unpin_height(b, saved)
        ink_restored = _ink_rows(b, band=True)
    finally:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass
    # ① 自然档：不许报红；且钉高不能污染读数
    assert why_nat is None, f"判据对**自然高度**的按钮就报红 —— 样本不可用：{why_nat}"
    assert ink_after == ink_nat, (
        f"钉高没还原干净：还原后墨迹 {ink_after} 行 != 自然 {ink_nat} 行")
    assert ink_restored == ink_nat, (
        f"钉高没还原干净：恢复后墨迹 {ink_restored} 行 != 自然 {ink_nat} 行")
    # ② **部分**裁字档：必须先证明这真是一档「部分」裁字（不是全黑），再证明判据报红
    assert 0 < ink_partial < ink_nat, (
        f"口径失效：压到 14px 后墨迹 {ink_partial} 行（自然 {ink_nat} 行）—— "
        f"没复现出「部分被裁」这一档，判据只能抓全黑就测不出来了")
    assert why_partial is not None, (
        f"判据失效：压到 14px 只画出 {ink_partial}/{ink_nat} 行墨迹，"
        f"判据却判**合格** —— 部分裁字漏检")
    # ③ 全黑档也必须报红（下限能力）
    assert ink_zero == 0, f"口径失效：压到 6px 仍画出 {ink_zero} 行墨迹（预期 0）"
    assert why_zero is not None, "判据失效：内容区已为 0，判据却判合格"


def test_wp5_about_page_short_button_not_clipped(qapp, isolated_env, glass_window):
    """about 页「检查更新」：页面必须落在滚动容器里，否则被挤成 96×17 → 零字形。

    这是全仓**唯一**一处「内容区高 < 墨迹高」的真缺陷（见 `_fix_blackbox/sweep5_before.txt`），
    根因不是 padding 而是**页面没有滚动区**（内容最小高 ~1156px vs 页面 875px）。
    """
    from gui.theme_engine import ThemeEngine

    ThemeEngine().load_theme("ui_minimal")
    _pump(6)
    glass_window.resize(1200, 800)
    _pump(6)
    glass_window.page_manager.navigate("about")
    _pump(10)
    page = None
    for p in glass_window.findChildren(QWidget):
        if p.__class__.__name__ == "PageAbout":
            page = p
            break
    assert page is not None, "主窗里找不到 PageAbout（口径判断失效）"
    btn = None
    for b in page.findChildren(QPushButton):
        if b.text() == "检查更新":
            btn = b
            break
    assert btn is not None, "about 页找不到「检查更新」按钮"
    in_scroll = False
    cur = btn.parentWidget()
    while cur is not None and cur is not glass_window:
        if isinstance(cur, QScrollArea):
            in_scroll = True
            break
        cur = cur.parentWidget()
    cr = _contents_rect(btn)
    ink = _ink_rows(btn, band=True)
    assert in_scroll, (
        "about 页内容没有落在 QScrollArea 内 —— 页面被竖向挤压后，页内最矮的按钮"
        "会重新塌成 96×17（内容区 56×1、零字形）")
    assert (btn.width(), btn.height()) == (96, 35), (
        f"「检查更新」尺寸被改动 {(btn.width(), btn.height())}（期望 96×35）")
    assert cr.height() >= _MIN_INK_ROWS and ink >= _MIN_INK_ROWS, (
        f"「检查更新」仍被裁字：内容区={cr.width()}x{cr.height()} 墨迹={ink} 行")
