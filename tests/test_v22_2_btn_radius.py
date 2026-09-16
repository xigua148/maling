# -*- coding: utf-8 -*-
r"""v2.2.2 守卫：「发送 / 确定 / 取消」类按钮方角 → 圆角。

用户原话（本轮诉求）：
  「发送，确定和取消按钮的框，**若是方形的**，能不能改成圆角，这样视觉效果平滑一点」

「若是方形的」= 条件式 ⇒ 先取证、再动手、只改实测为方角的那些。

## 根因（**真实平台 + show() 实测**，静态读 QSS 抓不到）

`Qt QSS 的 border-radius 只在 radius <= min(宽, 高) / 2 时才绘制，一旦超出就被整体
丢弃、按钮退回矩形`。本仓四套主题的 `radius_pill` = 24 / 24 / 26 / 24px，而
「发送 / 主操作 / 弹窗按钮」定高 29~40px（一半只有 14.5~20px）⇒ 各主题肤感层写的
`QPushButton#primaryBtn, QPushButton#sendBtn { border-radius: ${radius_pill}; }`
**写了等于没写**，实测四角完全矩形。

阈值矩阵（四角 3×3 采样，实测自 `_probe_nav_radius/probe_threshold.py`）：

    h=28  半径 ≤14 圆角 / ≥15 方角      h=35  半径 ≤17 圆角 / ≥18 方角
    h=33  半径 ≤16 圆角 / ≥17 方角      h=40  半径 ≤20 圆角 / ≥22 方角

## 修法（base.qss §1f 一条分组 id 规则，只声明 border-radius）

    QDialog QPushButton,
    QWidget QPushButton#sendBtn,
    QWidget QPushButton#primaryBtn,
    QWidget QPushButton#dangerBtn { border-radius: ${radius_sm}; }

`radius_sm` 四主题 = 8 / 10 / 8 / 10px，对 29~40px 按钮全部落在阈值之内。

⚠ 为什么选择器要带一个**类型祖先**（`QWidget …` / `QDialog …`）：
  各主题肤感层自带 `QPushButton#sendBtn` / `QPushButton#primaryBtn`（特异性 (1,0,1)）
  且声明 `${radius_pill}`，而 base.qss 排在肤感层**之前** ⇒ 同特异性的 base id 规则
  压不住它。补一个类型祖先把特异性抬到 (1,0,2) 才生效；`QDialog QPushButton` 为
  (0,0,2) > 通用 `QPushButton` (0,0,1)，一次覆盖各弹窗与 `QMessageBox`。
  此写法只需 base.qss 一处，**未改四份主题 qss、未动通用 `QPushButton`**。

⚠ 为什么**必须**是渲染级用例：本缺陷的全部证据只在像素上 —— 任何「QSS 里搜
  `border-radius`」的静态断言都会对改前的错误实现判绿（因为值确实写着）。

## 本文件承载的四类守卫

  ① 静态：§1f 规则在位、四支选择器齐全、**声明体只有 border-radius**（几何零位移的
     静态证据）、未铺开到通用 `QPushButton`、四份主题 qss 零改动；
  ② 渲染：用户点名的那组按钮在**四主题**下四角均为圆角（corner9 全 0）；
  ③ 对抗性：把 §1f 规则从应用级 QSS 里**摘掉** → 同一批按钮必须回落「方角」
     （证明规则是承重的、且判据不是空转）；再装回 → 必须可逆；
  ④ 反作用面：摘掉前后逐按钮比对 `pos` / `size`（**几何零位移**），且不在规则里的
     同排兄弟按钮（`chatSendBtn` / `stopBtn` / `exportChatBtn` / `planNewBtn` …）
     判定**逐项不变**（未误伤）。

⚠ 采样判据（四角几何，非「填色一致性」）：
  bg   = 按钮矩形外 4px 处四点的众数色（父容器底色）
  半径 = 「第 0 行第一个 != bg 的 x」−「中间行第一个 != bg 的 x」（四角对称，取最大）
  `max(四角) <= 1` → 方角(0)；否则圆角。
  这套判据对**渐变底**（ui_whale `#primaryBtn`）与**透明底 + 描边**（`#secondaryBtn`）
  同样成立 —— 判的是形状边界，不是颜色恒等。
  另记 corner9 = 该角 3×3 中「== 按钮中心众数色」的像素数（方角 = 9），作旁证。

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
    QApplication, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget, QPoint,
)
from PySide6.QtCore import QRect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
BASE_QSS = ROOT / "gui" / "themes" / "base.qss"

#: §1f 的选择器（归一化空白后逐支比对）
RULE_SELECTORS = (
    "QDialog QPushButton",
    "QWidget QPushButton#sendBtn",
    "QWidget QPushButton#primaryBtn",
    "QWidget QPushButton#dangerBtn",
)
#: §1f 声明体（**只允许**这一条声明 —— 多一条就可能是几何位移）
RULE_DECL = "border-radius: ${radius_sm};"
#: 摘掉规则时用的定位锚点（渲染后的 QSS 里 `${...}` 已被替换，此串保持不变）
RULE_ANCHOR = "QDialog QPushButton,"
#: 用户点名的那组目标：`(宿主标签, 判据)`；判据 = objectName 集合 或 文案集合
TARGET_SELECTORS = {
    "chat_panel": {"names": {"sendBtn"}},
    "page_plan": {"names": {"primaryBtn", "dangerBtn"}},
    "card_import_preview": {"names": {"cardPreviewOk", "cardPreviewCancel"}},
    "quit_confirm_msgbox": {"texts": {"退出", "再陪我一会"}},
}
#: 四主题 `radius_sm`（`theme_engine.THEME_DEFINITIONS[*]["layout"]["radius_sm"]`）
EXPECTED_RADIUS_SM = {"ui_minimal": 8, "ui_cream": 10, "ui_night": 8, "ui_whale": 10}
#: 目标按钮里最矮的一档（page_plan 的 `dangerBtn` / 弹窗按钮 = 29px）——
#: 半径必须 <= 它的 一半，否则又会被 Qt 丢弃
_MIN_TARGET_H = 29

_ISO = Path(tempfile.mkdtemp(prefix="maling_test_btnradius_"))


# ---------------------------------------------------------------------------
# QSS 解析（`${...}` 安全；朴素 `[^{}]*` 会被 `${token}` 的花括号截断）
# ---------------------------------------------------------------------------
def _qss_rules(text: str):
    """产出 ``[(selector, decl)]``；逐字符扫描，``${var}`` 当原子跳过。"""
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


def _norm(s: str) -> str:
    return " ".join(s.split())


def _flat_decl(s: str) -> str:
    return " ".join(s.split())


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


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _pump(n: int = 8) -> None:
    app = QApplication.instance()
    for _ in range(n):
        app.processEvents()


def _engine(theme: str):
    from gui.theme_engine import ThemeEngine
    engine = ThemeEngine()
    engine.load_theme(theme)
    _pump(6)
    return engine


def _ctx(engine):
    from gui.app_context import AppContext
    from gui.config import GuiConfig
    cfg = GuiConfig()
    cfg.first_run = False
    ctx = AppContext(config=cfg)
    ctx.theme_engine = engine
    return ctx


def _analyze(img, rect: QRect) -> dict:
    """四角几何采样（口径见模块 docstring）。"""
    x0, y0, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    res = {"w": w, "h": h, "verdict": "无法判定"}
    if w < 8 or h < 8:
        res["note"] = "矩形过小"
        return res

    def px(x, y):
        return img.pixel(x0 + x, y0 + y)

    cand = []
    for dx, dy in ((-4, h // 2), (w + 3, h // 2), (w // 2, -4), (w // 2, h + 3)):
        xx, yy = x0 + dx, y0 + dy
        if 0 <= xx < img.width() and 0 <= yy < img.height():
            cand.append(img.pixel(xx, yy))
    if not cand:
        res["note"] = "无外部采样点"
        return res
    bg = Counter(cand).most_common(1)[0][0]

    cfill = Counter()
    for dx in range(max(1, w // 4), max(2, w * 3 // 4)):
        for dy in range(max(1, h // 4), max(2, h * 3 // 4)):
            cfill[px(dx, dy)] += 1
    fill = cfill.most_common(1)[0][0]

    def fnb(y, rev=False):
        for x in (range(w - 1, -1, -1) if rev else range(w)):
            if px(x, y) != bg:
                return x
        return None

    def fnc(x, rev=False):
        for y in (range(h - 1, -1, -1) if rev else range(h)):
            if px(x, y) != bg:
                return y
        return None

    def d(a, b):
        return None if (a is None or b is None) else a - b

    vals = [v for v in (
        d(fnb(0), fnb(h // 2)), d(fnb(h // 2, True), fnb(h - 1, True)),
        d(fnc(0), fnc(w // 2)), d(fnc(h - 1), fnc(w // 2, True)),
    ) if v is not None]

    def blk(ox, oy):
        return sum(1 for i in range(3) for j in range(3) if px(ox + i, oy + j) == fill)

    res["corner9"] = [blk(0, 0), blk(w - 3, 0), blk(0, h - 3), blk(w - 3, h - 3)]
    res["fill_is_bg"] = fill == bg
    if not vals:
        res["verdict"] = "无法判定"
    elif max(vals) <= 1:
        res["verdict"] = "方角(0)"
    else:
        res["verdict"] = "圆角"
    res["max_delta"] = max(vals) if vals else None
    return res


def _measure_host(host, label: str) -> dict:
    """测宿主内全部可见按钮 → ``{(label, objectName, text): info}``。"""
    img = host.grab().toImage()
    dpr = img.devicePixelRatio() or 1.0
    out = {}
    for btn in host.findChildren(QPushButton):
        if not btn.isVisible() or btn.width() < 8 or btn.height() < 8:
            continue
        try:
            pos = btn.mapTo(host, QPoint(0, 0))
        except Exception:
            continue
        rect = QRect(int(round(pos.x() * dpr)), int(round(pos.y() * dpr)),
                     int(round(btn.width() * dpr)), int(round(btn.height() * dpr)))
        rect = rect.intersected(QRect(0, 0, img.width(), img.height()))
        if rect.width() < 8 or rect.height() < 8:
            continue
        info = _analyze(img, rect)
        info.update({"host": label, "objectName": btn.objectName() or "",
                     "text": (btn.text() or "").replace("\n", " "),
                     "pos": [pos.x(), pos.y()],
                     "size": [btn.width(), btn.height()]})
        out[(label, info["objectName"], info["text"])] = info
    return out


def _glass_stub():
    import gui.glass as glass
    originals = {}
    for name, fake in (
        ("is_supported", lambda: True),
        ("detect_capability", lambda: glass.GlassCapability(True, "mica", 22621, "test-stub")),
        ("safe_apply", lambda hwnd, kind, *, dark: True),
        ("remove", lambda hwnd: True),
    ):
        originals[name] = getattr(glass, name)
        setattr(glass, name, fake)
    return originals


def _build_hosts(ctx) -> list:
    """构造**真实控件**宿主（用户点名的那组 + 同排兄弟）。"""
    from gui.pages.page_plan import PagePlan
    from gui.widgets.card_import_preview import CardImportPreviewDialog
    from gui.widgets.chat_panel import ChatPanelWidget
    from gui.widgets.chat_window import ChatWindow

    hosts = []

    panel = ChatPanelWidget(ctx)
    panel.resize(760, 560)
    panel.show()
    _pump()
    hosts.append(("chat_panel", panel))

    plan = PagePlan(ctx)
    plan.resize(900, 620)
    plan.show()
    _pump()
    hosts.append(("page_plan", plan))

    card = {"name": "测试角色", "given_name": "小测", "description": "d",
            "system_prompt": "s", "personality": {"lively": 50},
            "opening_lines": ["a"], "example_dialogues": ["b"]}
    prev = CardImportPreviewDialog(card, existing_names=[], app_context=ctx)
    prev.resize(760, 560)
    prev.show()
    _pump()
    hosts.append(("card_import_preview", prev))

    box = QMessageBox()
    box.setWindowTitle("退出码铃？")
    box.setText("确定要退出码铃吗？\n\n退出后她就不会再主动问候你啦。")
    box.setIcon(QMessageBox.Question)
    box.addButton("退出", QMessageBox.AcceptRole)
    box.addButton("再陪我一会", QMessageBox.RejectRole)
    box.resize(420, 220)
    box.show()
    _pump()
    hosts.append(("quit_confirm_msgbox", box))

    originals = _glass_stub()
    try:
        from gui.config import GuiConfig
        cfg = GuiConfig()
        cfg.first_run = False
        cfg.auto_check = False
        cfg.tts_enabled = False
        cfg.pet_enabled = False
        cfg.glass_popups_enabled = False
        ctx2 = _ctx(ctx.theme_engine)
        cw = ChatWindow(ctx2)
        cw.resize(520, 720)
        cw.show()
        _pump(10)
        hosts.append(("chat_window", cw))
    finally:
        import gui.glass as glass
        for name, fn in originals.items():
            setattr(glass, name, fn)

    return hosts


def _close_hosts(hosts) -> None:
    for _label, host in hosts:
        try:
            host.close()
            host.deleteLater()
        except Exception:
            pass
    _pump(4)


def _snapshot(ctx) -> dict:
    """构造宿主 → 采样 → 关闭，返回 ``{(host, oid, text): info}``。"""
    hosts = _build_hosts(ctx)
    try:
        snap = {}
        for label, host in hosts:
            snap.update(_measure_host(host, label))
        return snap
    finally:
        _close_hosts(hosts)


def _is_target(key) -> bool:
    label, oid, text = key
    sel = TARGET_SELECTORS.get(label)
    if not sel:
        return False
    if "names" in sel and oid in sel["names"]:
        return True
    if "texts" in sel and text in sel["texts"]:
        return True
    return False


class _RuleRemoved:
    """临时把 §1f 规则从应用级 QSS 里摘掉（用完必须装回）。"""

    def __init__(self, qapp):
        self.qapp = qapp
        self.saved = ""

    def __enter__(self):
        self.saved = self.qapp.styleSheet()
        i = self.saved.find(RULE_ANCHOR)
        assert i >= 0, (
            f"应用级 QSS 里找不到 `{RULE_ANCHOR}` —— §1f 规则不在（或锚点已改名），"
            f"本文件的对抗性用例将无从成立")
        j = self.saved.find("}", i)
        assert j > i, f"`{RULE_ANCHOR}` 之后找不到规则结束花括号"
        self.qapp.setStyleSheet(self.saved[:i] + self.saved[j + 1:])
        _pump(8)
        return self

    def __exit__(self, *exc):
        self.qapp.setStyleSheet(self.saved)
        _pump(8)
        return False


# ===========================================================================
# ① 静态契约
# ===========================================================================
def _base_rule():
    """返回 base.qss 里的 §1f 规则 ``(selector, decl)``（找不到则 fail）。"""
    hits = [(s, d) for s, d in _qss_rules(BASE_QSS.read_text(encoding="utf-8"))
            if "#sendBtn" in s and "#primaryBtn" in s and "#dangerBtn" in s]
    assert hits, "base.qss 找不到 §1f 分组规则（含 #sendBtn + #primaryBtn + #dangerBtn 的那条）"
    assert len(hits) == 1, f"§1f 分组规则应唯一，实得 {len(hits)} 条：{[h[0] for h in hits]}"
    return hits[0]


def test_rule_present_with_exact_scope():
    """§1f 规则在位，且选择器**恰好**是这四支（多一支就是铺开了范围）。"""
    sel, _decl = _base_rule()
    parts = [_norm(p) for p in sel.split(",")]
    assert parts == list(RULE_SELECTORS), (
        f"§1f 选择器集合被改动：{parts} != {list(RULE_SELECTORS)}")


def test_rule_declares_only_border_radius():
    """**几何零位移的静态证据**：声明体只有 border-radius 一条。

    多一个 padding / min-width / min-height / font-size / background / color 都可能
    改变尺寸或底色 —— 本轮只许改圆角。
    """
    _sel, decl = _base_rule()
    assert _flat_decl(decl) == RULE_DECL, (
        f"§1f 的声明体不再是「只有 {RULE_DECL}」：{_flat_decl(decl)!r}")


def test_generic_qpushbutton_not_touched():
    """反向守卫：**不得**顺手铺开到通用 `QPushButton`。"""
    rules = _qss_rules(BASE_QSS.read_text(encoding="utf-8"))
    bad = [_norm(s) for s, d in rules
           if _norm(s) == "QPushButton" and "border-radius" in d]
    assert not bad, f"base.qss 出现了以通用 `QPushButton` 为选择器的圆角规则：{bad}"


def test_theme_layer_untouched():
    """四份主题 qss 零改动：`#primaryBtn/#sendBtn` 仍 `${radius_pill}`、通用仍 8px 20px。"""
    for theme in THEMES:
        text = (ROOT / "gui" / "themes" / f"{theme}.qss").read_text(encoding="utf-8")
        rules = {_norm(s): _flat_decl(d) for s, d in _qss_rules(text)}
        gen = rules.get("QPushButton", "")
        assert "border-radius: ${radius_pill};" in gen, (
            f"{theme}.qss 通用 QPushButton 的圆角被改动：{gen!r}")
        assert "padding: 8px 20px;" in gen, (
            f"{theme}.qss 通用 QPushButton 的 padding 被改动：{gen!r}")
        pair = rules.get("QPushButton#primaryBtn, QPushButton#sendBtn", "")
        assert "border-radius: ${radius_pill};" in pair, (
            f"{theme}.qss `#primaryBtn/#sendBtn` 的圆角被改动：{pair!r}")
        assert "padding: 8px 24px;" in pair, (
            f"{theme}.qss `#primaryBtn/#sendBtn` 的 padding 被改动：{pair!r}")
        assert "min-width: 80px;" in pair, (
            f"{theme}.qss `#primaryBtn/#sendBtn` 的 min-width 被改动：{pair!r}")


def test_radius_sm_token_within_half_height(qapp):
    """取值纪律：复用既有 `radius_sm`（不发明新数值），且必须 <= 目标按钮半高。"""
    from gui.theme_engine import ThemeEngine
    for theme, want in EXPECTED_RADIUS_SM.items():
        engine = ThemeEngine()
        engine.load_theme(theme)
        got = engine.get_layout_token("radius_sm")
        assert got == want, f"{theme}: radius_sm 实得 {got}，期望 {want}"
        assert got <= _MIN_TARGET_H / 2, (
            f"{theme}: radius_sm={got} > 最矮目标按钮半高 {_MIN_TARGET_H / 2} —— "
            f"Qt 会整体丢弃该圆角，修复失效")


def test_previous_fixes_not_disturbed():
    """不得碰上一轮刚修好的东西（§1e-bis / §5 / stopBtn padding）。

    v2.2.2：原第 4 项「浮窗扁平文字按钮的 QSS 串」已退役（宿主方法 `_flat_text_button_qss`
    随其调用方——浮窗那三个扁平文字按钮——一起被删除，留下的是零调用点死代码）；
    该不变量改由主面板那套承接，见 `tests/test_v22_1_blackbox_fixes.py` 的 WP5 两条用例。
    """
    base = BASE_QSS.read_text(encoding="utf-8")
    rules = {_norm(s): _flat_decl(d) for s, d in _qss_rules(base)}
    # §1e-bis：六个 id 的 padding 归零仍在同一条分组规则里
    wp1 = [d for s, d in rules.items()
           if all(f"QPushButton#{i}" in s for i in
                  ("planNewBtn", "newSessionBtn", "toggleSidebarBtn",
                   "sessionTabsNewBtn", "attachmentChipRemove", "feedbackSpark"))]
    assert wp1 and "padding: 0px;" in wp1[0], (
        f"§1e-bis 的 6 个 id `padding: 0px` 分组规则被动过：{wp1}")
    # §5：键盘焦点环仍是 text_on_accent，且鼠标路径仍是 none
    assert 'QPushButton[keyboardNav="true"]:focus' in base, "§5 键盘焦点规则缺失"
    assert "outline: 1px solid ${text_on_accent};" in base, "§5 焦点环取色被改动"
    assert re.search(r"QPushButton:focus\s*\{\s*outline:\s*none;\s*\}", base), (
        "§5 鼠标路径零描边规则缺失")
    # —— 已退役（v2.2.2）——
    # 原先此处断言：`gui/widgets/chat_window.py` 里扁平文字按钮 QSS 的首段字面量
    # `"QPushButton { background: transparent; border: none;"` 之后 200 字符内仍有
    # `" padding: 0px 20px;"`。它守的宿主方法 `_flat_text_button_qss`，其调用方
    # ——浮窗那三个扁平文字按钮（表情 / 导出 / 语音）——按用户 2026-09-16 指令删除
    # （浮窗与主面板各一套属"克隆体"，保留主面板那套），该方法随之成为**零调用点的
    # 死代码**并被一并删除 ⇒ 保留本段就变成「断言一段死代码存在」，属反模式，故整段退役。
    # ⚠ 不变量没丢，只是换了宿主：同一条「扁平文字按钮不被通用 padding 裁字」仍在
    #   **主面板**那套上守 —— `tests/test_v22_1_blackbox_fixes.py` 的
    #   `test_wp5_flat_text_buttons_not_clipped`（`#exportChatBtn` / `#quickActionBtn`，
    #   含「内容区高 ≥ 墨迹行数 + 放宽高度后墨迹不得变多」反事实）
    #   与 `test_wp5_flat_button_metric_is_not_vacuous`（非空转守卫）。
    # stopBtn 的 padding 仍 6px 16px（它靠 padding 撑版式）
    ub = (ROOT / "gui" / "widgets" / "chat_panel_parts" / "ui_build.py").read_text(
        encoding="utf-8")
    j = ub.find('_ss("stop_btn"')
    assert j >= 0 and "padding: 6px 16px;" in ub[j:j + 900], (
        "`#stopBtn` 的 `padding: 6px 16px` 被动过")


# ===========================================================================
# ② 渲染级：目标按钮在四主题下是圆角
# ===========================================================================
@pytest.mark.parametrize("theme", THEMES)
def test_named_buttons_are_rounded(qapp, isolated_env, theme):
    """用户点名的「发送 / 确定 / 取消」（含退出确认弹窗）四主题均为圆角。"""
    _engine(theme)
    ctx = _ctx(_engine(theme))
    snap = _snapshot(ctx)
    targets = {k: v for k, v in snap.items() if _is_target(k)}
    assert len(targets) == 8, (
        f"{theme}: 目标按钮实得 {len(targets)} 个（期望 8）—— 宿主里控件缺失/不可见时"
        f"本用例会静默失去意义，故写成硬计数。实得：{sorted(targets)}")
    bad = {k: (v["verdict"], v["corner9"], v["size"]) for k, v in targets.items()
           if v["verdict"] != "圆角"}
    assert not bad, f"{theme}: 以下目标按钮仍是方角 -> {bad}"


@pytest.mark.parametrize("theme", THEMES)
def test_rule_is_load_bearing(qapp, isolated_env, theme):
    """**对抗性**：摘掉 §1f → 目标全部回落方角（规则是承重的、判据非空转）。"""
    engine = _engine(theme)
    ctx = _ctx(engine)
    with_rule = {k: v for k, v in _snapshot(ctx).items() if _is_target(k)}
    assert len(with_rule) == 8, f"{theme}: 目标按钮计数异常 {len(with_rule)}"
    with _RuleRemoved(qapp):
        without = {k: v for k, v in _snapshot(ctx).items() if _is_target(k)}
    assert set(without) == set(with_rule), (
        f"{theme}: 摘掉规则后宿主结构变了（{sorted(set(with_rule) ^ set(without))}）——"
        f"几何/可见性对照失去意义")
    still_round = {k: (v["verdict"], v["corner9"]) for k, v in without.items()
                   if v["verdict"] != "方角(0)"}
    assert not still_round, (
        f"{theme}: 摘掉 §1f 后这些按钮**仍然**是圆角 -> 圆角另有来源，"
        f"本文件的判据无法证明 §1f 的作用：{still_round}")
    # 对照：摘掉前后都在规则外的同排兄弟，改前改后判定一致（未误伤）
    keys = [k for k in with_rule]
    assert keys, f"{theme}: 目标集合为空"


@pytest.mark.parametrize("theme", THEMES)
def test_geometry_zero_shift(qapp, isolated_env, theme):
    """**几何零位移**：摘掉 §1f 前后，每个按钮的 `pos` 与 `size` 逐项相同。"""
    engine = _engine(theme)
    ctx = _ctx(engine)
    a = _snapshot(ctx)
    with _RuleRemoved(qapp):
        b = _snapshot(ctx)
    assert set(a) == set(b), (
        f"{theme}: 两次构造的按钮集合不同：{sorted(set(a) ^ set(b))}")
    shift = {k: (a[k]["pos"], a[k]["size"], b[k]["pos"], b[k]["size"])
             for k in a
             if a[k]["pos"] != b[k]["pos"] or a[k]["size"] != b[k]["size"]}
    assert not shift, (
        f"{theme}: 加圆角后出现几何位移（形如 key: 加规则pos/size, 去规则pos/size）-> "
        f"{shift}")


@pytest.mark.parametrize("theme", THEMES)
def test_unrelated_buttons_verdict_unchanged(qapp, isolated_env, theme):
    """**未误伤**：不在 §1f 范围内的同排兄弟，摘掉规则前后判定逐项不变。

    覆盖 `chatSendBtn`（浮窗发送，自带控件级 20px 圆角）/ `stopBtn` / `exportChatBtn` /
    `newSessionBtn` / `toggleSidebarBtn` / `planNewBtn`（图标类，用户未点名）等。
    """
    engine = _engine(theme)
    ctx = _ctx(engine)
    a = {k: v for k, v in _snapshot(ctx).items() if not _is_target(k)}
    with _RuleRemoved(qapp):
        b = {k: v for k, v in _snapshot(ctx).items() if not _is_target(k)}
    changed = {k: (a[k]["verdict"], b[k]["verdict"]) for k in a
               if k in b and a[k]["verdict"] != b[k]["verdict"]}
    assert not changed, (
        f"{theme}: §1f 波及了未点名的按钮（摘掉规则后判定变了）-> {changed}")
    # 非空转：这组里必须有货，否则「未误伤」是空话
    assert len(a) >= 10, (
        f"{theme}: 非目标按钮只采到 {len(a)} 个 —— 样本太少，本用例证明力不足：{sorted(a)}")


@pytest.mark.parametrize("theme", THEMES)
def test_reversible_restore(qapp, isolated_env, theme):
    """摘掉再装回 → 目标按钮必须**重新变成圆角**（证明不是「改一次回不去」）。"""
    engine = _engine(theme)
    ctx = _ctx(engine)
    with _RuleRemoved(qapp):
        pass
    qss = qapp.styleSheet()
    assert RULE_ANCHOR in qss, "§1f 规则没有被装回应用级 QSS"
    snap = {k: v for k, v in _snapshot(ctx).items() if _is_target(k)}
    bad = {k: v["verdict"] for k, v in snap.items() if v["verdict"] != "圆角"}
    assert not bad, f"{theme}: 装回规则后仍未恢复圆角 -> {bad}"


# ===========================================================================
# ③ 采样判据自身的非空转守卫（正负对照）
# ===========================================================================
@pytest.mark.parametrize("theme", THEMES)
def test_sampler_discriminates_square_and_round(qapp, isolated_env, theme):
    """`radius 8px` → 圆角；`radius 40px`（36px 高按钮，超半高）→ 方角。

    若这条绿不了，上面所有「是圆角」的断言都可能是在空转。
    """
    _engine(theme)
    host = QWidget()
    host.setObjectName("samplerHost")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)
    r8 = QPushButton("r8")
    r8.setObjectName("samplerR8")
    r8.setFixedSize(140, 36)
    r8.setStyleSheet("QPushButton#samplerR8 { background: #3366CC; border: none;"
                     " border-radius: 8px; }")
    r40 = QPushButton("r40")
    r40.setObjectName("samplerR40")
    r40.setFixedSize(140, 36)
    r40.setStyleSheet("QPushButton#samplerR40 { background: #3366CC; border: none;"
                      " border-radius: 40px; }")
    lay.addWidget(r8)
    lay.addWidget(r40)
    host.resize(220, 130)
    host.show()
    _pump(10)
    snap = _measure_host(host, "sampler")
    host.close()
    host.deleteLater()
    _pump(4)
    v8 = snap[("sampler", "samplerR8", "r8")]["verdict"]
    v40 = snap[("sampler", "samplerR40", "r40")]["verdict"]
    c8 = snap[("sampler", "samplerR8", "r8")]["corner9"]
    c40 = snap[("sampler", "samplerR40", "r40")]["corner9"]
    assert v8 == "圆角", f"{theme}: radius=8/高36 竟被判 {v8}（corner9={c8}）"
    assert v40 == "方角(0)", f"{theme}: radius=40/高36 竟被判 {v40}（corner9={c40}）"
