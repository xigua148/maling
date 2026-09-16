# -*- coding: utf-8 -*-
r"""v2.2.2 守卫：侧边栏「工具 / 设置」两项的**图标**不得再写反。

用户原话（本轮诉求）：
  「把侧边栏工具前面的图标，和设置前面的图标调换一下」

现状核实（改前）：`NAV_ITEMS` 里 `tools` 的 `icon_name` 是 `settings`（齿轮）、
`settings` 的 `icon_name` 是 `tune`（滑杆）—— 语义确实写反。改法 = **只交换第 [2] 元**
（`icon_name`）：`tools → "tune"`、`settings → "settings"`。

随后配套（team-lead 追加任务 1）：交换 [2] 之后 [3] 回退 emoji 变得**语义不配对**
（工具=滑杆却回退 ⚙、设置=齿轮却回退 ⚑），故一并订正 [3]：
`tools → 🔧 U+1F527`、`settings → ⚙ U+2699`。

## 本文件承载的守卫

  ① 数据级：`NAV_ITEMS` 里 `tools` 的 `[2] == "tune"`、`settings` 的 `[2] == "settings"`；
  ② 不动项：`[0] key` / `[1] label` **逐字不变**，`NAV_ITEMS` 的**顺序**不变
     （第 1 项必须是 `chat` —— `sidebar.py` 靠 `setCurrentRow(0)` 做默认选中）；
     `[3] 回退 emoji` = 追加任务 1 订正后的 `U+1F527` / `U+2699`（不再允许回到 ⚑）；
  ③ 渲染级：四套主题下，列表项 `item.icon()` 实际画出的像素图**逐字节等于**
     同代码路径渲染的 `icons.icon("tune"/"settings", 18, 该行取色)`；
     并且**不等于**另一张候选图（证明判据不是空转）；
  ④ 回退路径未被波及：把 `icons.available()` 打桩为 False → 文本回落
     `"🔧  工具"` / `"⚙  设置"`，且图标置空（逐主题断言）；
  ⑤ 默认选中行 = 0 且 `key == "chat"`。

⚠ 与任务 2 同一条踩坑纪律：判据必须是**像素/逐字节**级别的，静态读 `NAV_ITEMS`
  只能证明「字符串对」，证明不了「屏幕上画的就是那一张」。

全 offscreen、零网络、零真实用户目录写入。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEBUDDY_SAFE_DELETE_ENABLED", "0")

import pytest  # noqa: E402

from gui.qt_compat import QApplication, QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
#: 期望的图标名（用户诉求的落点）
EXPECTED_ICON_NAME = {"tools": "tune", "settings": "settings"}
#: 期望的回退字符（追加任务 1 订正后：工具=扳手、设置=齿轮）
EXPECTED_FALLBACK = {"tools": 0x1F527, "settings": 0x2699}
#: 订正前的旧回退字符 —— 出现即说明回退 emoji 又变回语义不配对的状态
STALE_FALLBACK = {"tools": 0x2699, "settings": 0x2691}
#: 期望的 key → label（语义零变更）
EXPECTED_LABEL = {"tools": "工具", "settings": "设置"}
#: NAV_ITEMS 首项必须是 chat（sidebar.py 依赖 setCurrentRow(0) 做默认选中）
FIRST_ITEM_KEY = "chat"
_ISO = Path(tempfile.mkdtemp(prefix="maling_test_navicons_"))


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


@pytest.fixture(autouse=True)
def _isolate_icons_state():
    r"""本模块会注册图标字体、并读写 ``gui.icons`` 的全局单例 —— 收尾必须**按原值复位**。

    实测（**不是推测**，三条读数互相印证）：
      · `tests/test_v22_1_blackbox_fixes.py` 单跑：58 passed（其中
        `test_wp1_fixed_size_buttons_render_glyph[ui_night]` 绿）；
      · `tests/test_v22_1_blackbox_fixes.py` 紧接着本模块跑：该用例**变红**
        （`feedbackSpark: 内容区 24x20 字形=0`）；
      · `tests/test_v21_icons.py`（它的 autouse fixture 会 `icons._reset_state()`）
        紧接着 blackbox 跑：**仍绿**。

    机制：blackbox 的 `_wp1_widgets` 构造 `ProactiveFeedbackBar(..., None)` 时
    `icons.available()` 决定「矢量图标」还是「emoji 兜底」——
      未注册 → `_spark.setText("✨")`（emoji，深色底上可见）；
      已注册 → `icons.icon("auto_awesome", 14, None)`，而 `icons._app_ctx is None`
                ⇒ 取色回落 `#000000` ⇒ 深色主题（ui_night 宿主底色实测 #131114）上
                黑图标与底色最大通道差只有 19 < 30 ⇒ 墨迹判据量到 0。
    本模块**不该**把「图标已注册」这个全局态留给后面的模块，故按
    `tests/test_v21_icons.py` 的既有约定在前后各复位一次；
    收尾「先 `clear_cache()` 再 `_reset_state()`」—— 反过来的话本模块渲染期新增的
    缓存键既不在键表里、也清不掉，会一直留在 `QPixmapCache` 里。

    （黑色盒用例在「字体已注册 + 深色主题」下的那条边界已由 team-lead 追加任务 2
      独立处理：`tests/test_v22_1_blackbox_fixes.py` 现在自带
      `_deterministic_icons_state` 复位 fixture —— 本模块只负责**不泄漏**。）
    """
    from gui import icons
    icons._reset_state()
    yield
    try:
        icons.clear_cache()
    except Exception:
        pass
    icons._reset_state()


def _pump(n: int = 8) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def _img(pm) -> QImage:
    return pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)


def _diff(a: QImage, b: QImage) -> int:
    """两图总绝对差（ARGB 四通道求和）；0 = 逐字节相同，-1 = 尺寸不同。"""
    if a.size() != b.size():
        return -1
    tot = 0
    for y in range(a.height()):
        for x in range(a.width()):
            pa, pb = a.pixel(x, y), b.pixel(x, y)
            for sh in (0, 8, 16, 24):
                tot += abs(((pa >> sh) & 0xFF) - ((pb >> sh) & 0xFF))
    return tot


def _items():
    from gui.widgets.sidebar import SidebarWidget
    return list(SidebarWidget.NAV_ITEMS)


# ===========================================================================
# ① / ② 数据级
# ===========================================================================
def test_icon_names_swapped():
    """`tools → tune`、`settings → settings`（本轮诉求的落点）。"""
    got = {t[0]: t[2] for t in _items()}
    for key, want in EXPECTED_ICON_NAME.items():
        assert key in got, f"NAV_ITEMS 缺少 {key!r} 项"
        assert got[key] == want, (
            f"侧栏 {key} 的图标名实得 {got[key]!r}，期望 {want!r}"
            f"（写反了：工具应是滑杆 tune，设置应是齿轮 settings）")


def test_key_label_fallback_and_order_untouched():
    """`key` / `label` / 顺序 逐项不变；回退 emoji = 追加任务 1 的订正口径。"""
    items = _items()
    assert items[0][0] == FIRST_ITEM_KEY, (
        f"NAV_ITEMS 第 1 项被改动：{items[0][0]!r}（必须是 {FIRST_ITEM_KEY!r} —— "
        f"sidebar 靠 setCurrentRow(0) 做默认选中）")
    by_key = {t[0]: t for t in items}
    for key, label in EXPECTED_LABEL.items():
        assert by_key[key][1] == label, f"{key} 的 label 被改动：{by_key[key][1]!r}"
    for key, cp in EXPECTED_FALLBACK.items():
        fb = by_key[key][3]
        assert len(fb) == 1 and ord(fb) == cp, (
            f"{key} 的回退字符实得 U+{ord(fb):04X}，期望 U+{cp:04X}"
            f"（追加任务 1：工具应回退扳手 🔧、设置应回退齿轮 ⚙）")
        stale = STALE_FALLBACK[key]
        assert ord(fb) != stale, (
            f"{key} 的回退字符退回了旧值 U+{stale:04X}"
            f"（正是「矢量=滑杆/齿轮、回退=⚙/⚑」语义不配对的那个状态）")
    assert len(items) == len(set(t[0] for t in items)), "NAV_ITEMS 出现重复 key"


def test_two_fallbacks_are_distinct_and_paired():
    r"""两项回退字符互不相同，且各自与自己的矢量语义同族（判据非空转）。

    · 互不相同：若把两项都设成同一个字符（例如都回退 ⚙），上一条逐项断言仍会
      因「工具那条不匹配」而红 —— 但本用例额外把「两项不得相同」写死，
      避免将来有人把两条回退改成同一个「万能齿轮」蒙混过关。
    · 语义同族：设置的矢量是齿轮、回退也应是齿轮（U+2699 与 page_home 的
      「⚙ 模型设置」同字符）；工具的矢量是滑杆（无对应 emoji），回退取本仓既有的
      「工具类」约定 🔧（与 `gui/widgets/tool_trace.py` / `gui/chat_input_logic.py`
      的 `text_glyph('plugin', '🔧')` 一致），不得是齿轮。
    """
    by_key = {t[0]: t for t in _items()}
    tools_cp, settings_cp = ord(by_key["tools"][3]), ord(by_key["settings"][3])
    assert tools_cp != settings_cp, (
        f"工具与设置的回退字符相同（U+{tools_cp:04X}）—— 无法区分两项")
    assert settings_cp == 0x2699, (
        f"设置的回退字符应为齿轮 U+2699，实得 U+{settings_cp:04X}")
    assert tools_cp != 0x2699, (
        "工具的回退字符不该是齿轮（那是设置的本义）—— 语义不配对")


# ===========================================================================
# ③ / ④ / ⑤ 渲染级
# ===========================================================================
def _sidebar_rows(theme: str):
    """构造侧栏并返回 ``(sb, ctx, 每项快照)``；调用方负责 close。"""
    from gui import icons, theme_engine
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    from gui.widgets.sidebar import SidebarWidget
    from gui.utils import theme_color

    icons.register_icon_font()
    engine = theme_engine.ThemeEngine()
    engine.load_theme(theme)
    _pump(6)
    cfg = GuiConfig()
    cfg.first_run = False
    ctx = AppContext(config=cfg)
    ctx.theme_engine = engine

    sb = SidebarWidget(ctx)
    sb.resize(220, 760)
    sb.show()
    _pump(8)

    rows = {}
    cur = sb.list_widget.currentRow()
    for i in range(sb.list_widget.count()):
        it = sb.list_widget.item(i)
        sel = (i == cur)
        color = theme_color(ctx, "accent" if sel else "text",
                            "#FF6B9D" if sel else "#5D4037")
        rows[it.data(Qt.UserRole)] = {
            "icon": _img(it.icon().pixmap(QSize(18, 18))),
            "icon_name": it.data(Qt.UserRole + 1),
            "label": it.data(Qt.UserRole + 2),
            "fallback": it.data(Qt.UserRole + 3),
            "text": it.text(),
            "color": color,
            "selected": sel,
        }
    return sb, ctx, rows, cur


@pytest.mark.parametrize("theme", THEMES)
def test_rendered_glyph_matches_icon_name(qapp, isolated_env, theme):
    """四主题：`tools`/`settings` 两行**实际画出来的像素图**与**期望语义**一致。

    ⚠ 参考图取自 `EXPECTED_ICON_NAME`（**期望值**），不是 `item` 里的 `icon_name`
      —— 后者是自指的：把 icon_name 换回去时「画的 == 自己声明的」依然成立，
      那样本用例就成了空转（实测过，故改成对期望值取参考图）。
    """
    from gui import icons
    sb, _ctx, rows, _cur = _sidebar_rows(theme)
    try:
        for key, want_name in EXPECTED_ICON_NAME.items():
            r = rows[key]
            assert r["icon_name"] == want_name, (
                f"{theme}/{key}: item 里的 icon_name 实得 {r['icon_name']!r}，"
                f"期望 {want_name!r}")
            ref = _img(icons.icon(want_name, 18, r["color"]).pixmap(QSize(18, 18)))
            other_name = "settings" if want_name == "tune" else "tune"
            other = _img(icons.icon(other_name, 18, r["color"]).pixmap(QSize(18, 18)))
            assert _diff(ref, other) != 0, (
                f"{theme}/{key}: {want_name} 与 {other_name} 两张候选图居然一模一样 —— "
                f"本判据失去分辨力（空转），必须先修判据")
            assert _diff(r["icon"], ref) == 0, (
                f"{theme}/{key}: 实际画出的不是 {want_name!r} 的字形"
                f"（diff={_diff(r['icon'], ref)}）—— 图标写反/未生效")
            assert _diff(r["icon"], other) != 0, (
                f"{theme}/{key}: 实际画的是 {other_name!r}（写反了）")
            assert r["text"] == r["label"], (
                f"{theme}/{key}: 文本带有回退前缀 {r['text']!r} —— 矢量图标分支未生效")
    finally:
        sb.close()
        sb.deleteLater()
        _pump(4)


@pytest.mark.parametrize("theme", THEMES)
def test_fallback_path_unchanged(qapp, isolated_env, theme):
    r"""`icons.available()` 为假 → 文本回落 `"<emoji>  <label>"`，图标置空（逐主题）。

    断言按**订正后**的口径（工具 `"🔧  工具"` / 设置 `"⚙  设置"`），并且对
    **全部 11 项**都要求「回退字符在文本里 + label 在文本里 + 图标被置空」——
    只盯 tools/settings 两项会漏掉「回退分支整体失效」这一类破坏。
    """
    from gui.widgets import sidebar as sb_mod
    sb, _ctx, _rows, _cur = _sidebar_rows(theme)
    orig = sb_mod._icons.available
    try:
        sb_mod._icons.available = lambda: False
        sb2 = sb_mod.SidebarWidget(_ctx)
        sb2.resize(220, 760)
        _pump(4)
        got = {}
        for i in range(sb2.list_widget.count()):
            it = sb2.list_widget.item(i)
            got[it.data(Qt.UserRole)] = (it.text(), it.icon().isNull())
        sb2.deleteLater()
    finally:
        sb_mod._icons.available = orig

    # ① 用户点名的两项：逐字符等于「emoji + 两空格 + label」
    for key in ("tools", "settings"):
        text, is_null = got[key]
        assert is_null, f"{theme}/{key}: 回退路径下图标未置空"
        assert text == f"{chr(EXPECTED_FALLBACK[key])}  {EXPECTED_LABEL[key]}", (
            f"{theme}/{key}: 回退文本实得 {text!r}，"
            f"期望 {chr(EXPECTED_FALLBACK[key])} + 两空格 + {EXPECTED_LABEL[key]!r}")
    assert got["tools"][0] != got["settings"][0], (
        f"{theme}: 工具与设置的回退文本相同（{got['tools'][0]!r}）—— 两项无法区分")

    # ② 全部项：回退分支整体仍生效（不空白、不崩、图标置空）
    for key, label, _name, fallback in _items():
        text, is_null = got[key]
        assert is_null, f"{theme}/{key}: 回退路径下图标未置空"
        assert fallback in text and label in text, (
            f"{theme}/{key}: 回退文本 {text!r} 未同时含回退字符与 label")
    sb.close()
    sb.deleteLater()
    _pump(4)


@pytest.mark.parametrize("theme", THEMES)
def test_default_row_is_chat(qapp, isolated_env, theme):
    """默认选中行 = 0 且 key == `chat`（`setCurrentRow(0)` 契约）。"""
    sb, _ctx, rows, cur = _sidebar_rows(theme)
    try:
        assert cur == 0, f"{theme}: 默认选中行实得 {cur}（期望 0）"
        key = sb.list_widget.item(0).data(Qt.UserRole)
        assert key == FIRST_ITEM_KEY, f"{theme}: 默认选中项 key 实得 {key!r}"
    finally:
        sb.close()
        sb.deleteLater()
        _pump(4)


def test_manifest_has_both_icon_names():
    """前置条件：`tune` / `settings` 两个图标名都必须在 manifest 里且码位不同。"""
    man = json.loads((ROOT / "gui" / "assets" / "icons" /
                      "icons_manifest.json").read_text(encoding="utf-8"))
    for name in ("tune", "settings"):
        assert name in man, f"icons_manifest.json 缺少 {name!r}"
    assert man["tune"] != man["settings"], "tune 与 settings 码位相同 —— 判据无法分辨"
