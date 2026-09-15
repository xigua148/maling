"""v2.2 酒馆字号收口守卫。

**为什么需要这个文件**（本轮实测暴露的缺陷类）：酒馆控件由两位实现者并行落地，
字号载体一度分裂成两种 ——

* ``gui/widgets/tavern/tavern_{hud,input,narrative}.py`` 把 ``font-size`` 混写在内联
  ``setStyleSheet`` 模板里；
* ``gui/widgets/tavern/tavern_{worldbook,plays,trace}.py`` 写进 ``gui/themes/base.qss``。

前者有真实回归风险：``tavern_input.py`` 的 ``_set_hint()`` 每次「降级提示」都重刷一次
内联样式，字号只能**跟着一起重写**；一旦某次漏写，就静默回落到全局 ``QWidget{font-size:14px}``，
外观悄悄退化且无任何报错。现统一为后者。

**项目口径**（长期约定 §二 字号 / ``docs/design-v22.md`` §6.4 字号 QSS 纪律）：
> 新增「需要字号」的控件 → **先给它 ``setObjectName``，再在 ``base.qss`` 加 id 规则**。

本文件守住两侧：
  ① ``gui/widgets/tavern/*.py`` 源码**零** ``font-size`` / ``font-weight`` /
     ``setPointSize`` / ``setPixelSize``；
  ② ``base.qss`` 为每个酒馆 ``objectName`` 提供了 ``font-size`` id 规则，
     且该规则**实际解析**到预期像素值（不被全局规则或主题文件压掉）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Set, Tuple

import pytest

from gui.theme_engine import ThemeEngine

_REPO = Path(__file__).resolve().parent.parent
_TAVERN_DIR = _REPO / "gui" / "widgets" / "tavern"
_BASE_QSS = _REPO / "gui" / "themes" / "base.qss"

#: 冻结契约：``#objectName -> (期望像素字号, 控件类别)``。
#: 类别 ∈ {``label``, ``button``, ``edit``}，仅用于解析校验时构造对应控件。
#: 11a = 世界书 / 我的故事 / 记录；11b = 叙述流 / 输入区 / 顶部 HUD。
TAVERN_FONT_PX: Dict[str, Tuple[int, str]] = {
    # --- 11a 世界书 / 我的故事 / 记录 ---
    "tavernPanelTitle": (17, "label"),
    "tavernPanelHint": (12, "label"),
    "tavernEntryTitle": (14, "label"),
    "tavernEntryKeys": (12, "label"),
    "tavernEntrySummary": (12, "label"),
    "tavernHitChip": (11, "label"),
    "tavernEmptyHint": (12, "label"),
    "tavernPlayTitle": (14, "label"),
    "tavernPlayMeta": (12, "label"),
    "tavernActiveChip": (11, "label"),
    "tavernTraceRole": (13, "label"),
    "tavernTraceField": (12, "label"),
    "tavernTraceReason": (12, "label"),
    "tavernEndingName": (12, "label"),  # 批次 D（E4）「走过的结尾」结局名
    "tavernPlayLoad": (12, "button"),
    "tavernPlayDelete": (12, "button"),
    # --- 11b 叙述流 / 输入区 / 顶部 HUD ---
    "tavernNarrativeText": (15, "label"),
    "tavernNarrativePlayer": (12, "label"),
    "tavernNarrativeEmpty": (13, "label"),
    "tavernChoiceBtn": (13, "button"),
    "tavernInputEdit": (14, "edit"),
    "tavernSendBtn": (14, "button"),
    "tavernInlineHint": (12, "label"),
    "tavernHudChapter": (15, "label"),
    "tavernHudScene": (12, "label"),
    "tavernHudItem": (11, "label"),
    "tavernHudStatus": (12, "label"),
    # --- 11c 酒馆页面（开局 / 终局出口） ---
    "tavernStartHint": (13, "label"),
    "tavernStartBtn": (14, "button"),
}

#: 需要加粗的 id（``font-weight: bold`` 同样收口在 base.qss）。
TAVERN_BOLD: Set[str] = {
    "tavernPanelTitle",
    "tavernEntryTitle",
    "tavernPlayTitle",
    "tavernTraceRole",
    "tavernSendBtn",
    "tavernHudChapter",
    "tavernStartBtn",
}

#: 字号写在 QSS，源码里出现这些即违规（``setPointSize(`` 有括号 → 只认真实调用）。
_FORBIDDEN_IN_SOURCE = ("font-size", "font-weight", "setPointSize(", "setPixelSize(")

#: 装配页（页面自建小部件也要守同一纪律）。
_PAGE_FILE = _REPO / "gui" / "pages" / "page_tavern.py"

#: 页面里**纯容器 / 无文字**的 id —— 它们不承载文字，故不需要 `font-size` 规则。
#: 这是**显式白名单**：新增一个「有文字的」控件却没配 QSS 规则时，下面的
#: :func:`test_page_object_names_have_font_rules` 会失败，从而把漂移挡在提交前。
_PAGE_CONTAINER_IDS = frozenset(
    {
        "tavernTabs",           # QTabWidget 容器
        "tavernTonightTab",     # 五个 Tab 的页面容器（QWidget）
        "tavernWorldbookTab",
        "tavernPlaysTab",
        "tavernCastTab",
        "tavernTraceTab",
        "tavernSettingsRow",    # QFrame 布局条
        "tavernCastCard",       # QFrame 卡容器
        "tavernStartPanel",     # QFrame 开局 / 终局入口容器（无文字）
    }
)

#: 控件层（``gui/widgets/tavern/*.py``）的**容器 / 装饰件** id 白名单（第五轮验证
#: P1 补）。此前漂移守卫只扫装配页，控件目录新挂的 id（如批次 D 的
#: ``tavernEndingName``）漏配 QSS 规则会静默回落全局 14px —— 本白名单 +
#: :func:`test_widget_object_names_are_covered` 把同一纪律闭合到控件侧。
_WIDGET_NON_TEXT_IDS = frozenset(
    {
        # --- 容器（QWidget / QFrame / QScrollArea，无自身文字）---
        "tavernPlaysPanel",       # PlaysPanel(QWidget) 自身
        "tavernTracePanel",       # TracePanel(QWidget) 自身
        "tavernWorldbookPanel",   # WorldbookPanel(QWidget) 自身
        "tavern_hud",             # TavernHud(QWidget) 自身
        "tavern_input",           # TavernInput(QWidget) 自身
        "tavern_narrative",       # TavernNarrative(QWidget) 自身
        "tavernChoicesRow",       # QWidget 选项行容器
        "tavernHudItems",         # QWidget 持有物行容器
        "tavernNarrativeBlock",   # QWidget 叙事块容器
        "tavernNarrativeBody",    # QWidget 叙事正文容器
        "tavernNarrativeScroll",  # QScrollArea 视口
        "tavernEndingsBox",       # QFrame「走过的结尾」小节容器
        "tavernTraceRow",         # QFrame 记录行容器
        "tavernEntryCard",        # QFrame 世界书条目卡
        "tavernPlayCard",         # QFrame 存档卡
        # --- 装饰件（QLabel 但零文字）---
        "tavernHudDot",           # 8×8 纯色状态点：QLabel("") + setFixedSize(8, 8)
    }
)


def _tavern_sources():
    """返回 ``[(文件名, 源码)]``：控件 + 装配页。缺失即失败（防止把守卫挂空）。"""
    files = sorted(p for p in _TAVERN_DIR.glob("*.py") if p.name != "__init__.py")
    assert files, f"未找到酒馆控件源码：{_TAVERN_DIR}"
    assert _PAGE_FILE.exists(), f"未找到酒馆装配页：{_PAGE_FILE}"
    pairs = [(p.name, p.read_text(encoding="utf-8")) for p in files]
    pairs.append(("gui/pages/page_tavern.py", _PAGE_FILE.read_text(encoding="utf-8")))
    return pairs


def _base_qss() -> str:
    return _BASE_QSS.read_text(encoding="utf-8")


def _rule_body(qss: str, object_name: str) -> str:
    """取出 ``#objectName { ... }`` 的规则体；找不到返回空串。"""
    for mm in re.finditer(r"#([A-Za-z_][A-Za-z0-9_]*)\s*\{([^}]*)\}", qss):
        if mm.group(1) == object_name:
            return mm.group(2)
    return ""


# --------------------------------------------------------------------------- #
# ① 源码侧：酒馆控件 + 装配页一律不写字号
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "filename,src",
    _tavern_sources(),
    ids=[name for name, _ in _tavern_sources()],
)
def test_source_has_no_font_size(filename: str, src: str) -> None:
    """酒馆源码零 ``font-size`` / ``font-weight`` / ``setPointSize`` / ``setPixelSize``。"""
    for banned in _FORBIDDEN_IN_SOURCE:
        assert banned not in src, (
            f"{filename} 出现 `{banned}` —— 字号 / 字重只能写在 gui/themes/base.qss 的 "
            f"#tavern* id 规则里（design-v22 §6.4 / 长期约定「字号单一收口点」）"
        )


def test_no_tavern_font_size_in_any_theme_file() -> None:
    """四个主题肤感层不得声明酒馆字号（否则会压过 base.qss，形成第二处收口点）。"""
    themes_dir = _REPO / "gui" / "themes"
    offenders = []
    for path in sorted(themes_dir.glob("*.qss")):
        if path.name == "base.qss":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"#tavern[A-Za-z0-9_]*\s*\{[^}]*font-size", text):
            offenders.append(path.name)
    assert not offenders, f"主题文件不应声明酒馆字号：{offenders}"


# --------------------------------------------------------------------------- #
# ② QSS 侧：每个酒馆 id 都有字号规则（且字重符合契约）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("object_name", sorted(TAVERN_FONT_PX))
def test_base_qss_declares_tavern_font_size(object_name: str) -> None:
    """``base.qss`` 必须为每个酒馆 objectName 提供 ``font-size`` id 规则。"""
    want_px = TAVERN_FONT_PX[object_name][0]
    body = _rule_body(_base_qss(), object_name)
    assert body, f"base.qss 缺少 `#{object_name} {{ ... }}` 规则"
    found = re.search(r"font-size:\s*(\d+)px", body)
    assert found, f"`#{object_name}` 规则未声明 font-size"
    assert int(found.group(1)) == want_px, (
        f"`#{object_name}` 字号 {found.group(1)}px ≠ 契约 {want_px}px"
    )


@pytest.mark.parametrize("object_name", sorted(TAVERN_BOLD))
def test_base_qss_bold_matches_contract(object_name: str) -> None:
    """契约里标粗的 id 必须在 ``base.qss`` 里有 ``font-weight: bold``。"""
    body = _rule_body(_base_qss(), object_name)
    assert body, f"base.qss 缺少 `#{object_name}` 规则"
    assert re.search(r"font-weight:\s*bold", body), f"`#{object_name}` 应声明 font-weight: bold"


def test_bold_set_is_subset_of_contract() -> None:
    """防止加粗集合里出现未登记 id（漏掉字号契约）。"""
    assert TAVERN_BOLD <= set(TAVERN_FONT_PX)


def test_page_object_names_have_font_rules() -> None:
    """装配页里每个 ``setObjectName("tavern…")`` 要么有字号规则，要么在容器白名单里。

    这是**防止漂移**的那一条：页面新增一个有文字的控件（如 ``tavernCastLine``）却忘了
    配 ``base.qss`` 规则时，字号会静默回落到全局 14px —— 本用例把它挡在提交前。
    纯容器（``QTabWidget`` / 各 Tab 的 ``QWidget`` / ``QFrame``）无文字，见
    ``_PAGE_CONTAINER_IDS`` 显式白名单。
    """
    src = _PAGE_FILE.read_text(encoding="utf-8")
    qss = _base_qss()
    names = sorted(set(re.findall(r'setObjectName\("([^"]+)"\)', src)))
    assert names, "装配页未发现任何 setObjectName（守卫被挂空）"

    tavern_names = [n for n in names if n.startswith("tavern")]
    assert tavern_names, "装配页未发现任何 `tavern*` objectName（守卫被挂空）"

    missing = []
    for name in tavern_names:
        if name in _PAGE_CONTAINER_IDS:
            continue
        if not re.search(r"font-size:", _rule_body(qss, name)):
            missing.append(name)
    assert not missing, (
        f"装配页这些 objectName 既不在容器白名单、也不在 base.qss 里有 font-size 规则：{missing}"
        f" —— 请补 `base.qss` §11c 规则，或（若确为无文字的容器）加入 `_PAGE_CONTAINER_IDS` 并说明理由"
    )


def test_container_whitelist_has_no_stale_entries() -> None:
    """容器白名单不得残留页面已不再使用的 id（防止白名单悄悄腐化）。"""
    src = _PAGE_FILE.read_text(encoding="utf-8")
    used = set(re.findall(r'setObjectName\("([^"]+)"\)', src))
    stale = sorted(_PAGE_CONTAINER_IDS - used)
    assert not stale, f"_PAGE_CONTAINER_IDS 里这些 id 页面已不再使用，请删除：{stale}"


# --------------------------------------------------------------------------- #
# ②b QSS 侧：控件目录（gui/widgets/tavern/）的 id 同样必须被覆盖
# --------------------------------------------------------------------------- #
def _widget_object_names() -> Set[str]:
    """控件目录全部 ``setObjectName`` 值（不含装配页）。"""
    files = sorted(p for p in _TAVERN_DIR.glob("*.py") if p.name != "__init__.py")
    assert files, f"未找到酒馆控件源码：{_TAVERN_DIR}"
    names: Set[str] = set()
    for p in files:
        names |= set(re.findall(r'setObjectName\("([^"]+)"\)', p.read_text(encoding="utf-8")))
    return names


def test_widget_object_names_are_covered() -> None:
    """控件层每个 ``tavern*`` id 要么在 :data:`TAVERN_FONT_PX` 契约里（且 QSS 有
    ``font-size``），要么在 :data:`_WIDGET_NON_TEXT_IDS` 容器/装饰件白名单里。

    第五轮验证 P1：此前的漂移守卫只扫装配页，导致批次 D 新增的
    ``QLabel#tavernEndingName`` 漏配规则、静默回落全局 14px。本用例把同一纪律
    闭合到控件侧 —— 新增有文字的控件却忘配 QSS 时，提交前即失败。
    """
    names = _widget_object_names()
    assert names, "控件目录未发现任何 setObjectName（守卫被挂空）"
    qss = _base_qss()
    missing = []
    for name in sorted(names):
        if name in _WIDGET_NON_TEXT_IDS:
            continue
        if name not in TAVERN_FONT_PX:
            missing.append(f"{name}(不在字号契约)")
            continue
        if not re.search(r"font-size:", _rule_body(qss, name)):
            missing.append(f"{name}(契约有但 base.qss 无 font-size 规则)")
    assert not missing, (
        f"控件层这些 objectName 既无字号覆盖也不在白名单：{missing} —— "
        f"请补 TAVERN_FONT_PX + base.qss §11a/11b 规则，"
        f"或（确为无文字的容器/装饰件）加入 _WIDGET_NON_TEXT_IDS 并注明类型依据"
    )


def test_widget_container_whitelist_has_no_stale_entries() -> None:
    """控件白名单不得腐化：每个条目必须仍出现在**控件目录**的 objectName 里。

    注意口径：控件 id 可以出现在装配页（例如页面复用同名容器），所以判据是
    「控件目录 ∪ 装配页」的并集；只要整个酒馆域不再使用该 id，就必须删条目。
    """
    used = _widget_object_names() | set(
        re.findall(r'setObjectName\("([^"]+)"\)', _PAGE_FILE.read_text(encoding="utf-8"))
    )
    stale = sorted(_WIDGET_NON_TEXT_IDS - used)
    assert not stale, f"_WIDGET_NON_TEXT_IDS 里这些 id 酒馆域已不再使用，请删除：{stale}"


# --------------------------------------------------------------------------- #
# ③ 解析侧：id 规则实际生效（不被全局 QWidget{font-size:14px} 或主题压掉）
# --------------------------------------------------------------------------- #
def _make(kind: str):
    from gui.qt_compat import QLabel, QPlainTextEdit, QPushButton

    return {"label": QLabel, "button": QPushButton, "edit": QPlainTextEdit}[kind]


def _px(widget) -> float:
    f = widget.font()
    if f.pixelSize() > 0:
        return float(f.pixelSize())
    return round(f.pointSizeF() * 96.0 / 72.0, 1)


@pytest.mark.parametrize("theme_name", ["ui_minimal", "ui_cream", "ui_night", "ui_whale"])
def test_tavern_font_sizes_resolve(qapp, theme_name: str) -> None:
    """四主题下逐个 objectName 实测字号 == 契约值（含浅 / 深两态）。"""
    engine = ThemeEngine()
    assert engine.load_theme(theme_name) is True

    original = qapp.styleSheet()
    try:
        baseline = _make("label")()
        baseline.ensurePolished()
        assert abs(_px(baseline) - 14.0) < 0.6, "全局基线字号应为 14px（守卫前提被破坏）"

        for object_name, (want_px, kind) in sorted(TAVERN_FONT_PX.items()):
            w = _make(kind)()
            w.setObjectName(object_name)
            w.ensurePolished()
            got = _px(w)
            assert abs(got - want_px) < 0.6, (
                f"[{theme_name}] `#{object_name}` 实测 {got}px ≠ 契约 {want_px}px"
                f"（base.qss id 规则被压掉或未加载）"
            )
    finally:
        # load_theme 会改写 QApplication 全局样式表；还原，避免污染后续用例。
        qapp.setStyleSheet(original)
