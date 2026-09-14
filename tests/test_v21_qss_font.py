# -*- coding: utf-8 -*-
"""V21 字体 QSS 出口修复单测（``gui/fonts.py::qss_font_family`` + 模板引号纪律）。

背景：QSS 模板原先把 ``${font_family}`` 整条包在一对引号里
（``font-family: "${font_family}";``），替换后 Qt 把整串当成**一个不存在的族名**
→ 整条链不解析 → 用户所选界面字体与图标字形均不生效（既有缺陷）。

本文件断言修复到位：
  · QSS 出口 ``qss_font_family`` 逐族加引号、通用族裸写；
  · ``load_theme`` 实际产出的 QSS 中 ``font-family:`` 后**不再出现「一对引号内含
    逗号」的形态**，且原 ``${font_family}`` 位置含 ``"remixicon"``（四套新风格各测）；
  · 七套主题 QSS 模板的等宽声明（21 处）同为可解析形态；
  · ``font_family_chain`` 返回格式零变更（供 test_v19_b 消费）；
  · **字号单一收口纪律**：``gui/**/*.py`` 不得在白名单外调用 ``setPointSize`` /
    ``setPixelSize``（会被 QSS 压掉、只留死行）—— 防止死字号再长回来的永久守卫。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import ast
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gui import fonts

ROOT = Path(__file__).resolve().parents[1]

# 四套「新风格」（v1.9 A 块）+ 三套旧风格
NEW_THEMES = ["ui_minimal", "ui_cream", "ui_night", "ui_whale"]
ALL_THEMES = ["cute", "minimal", "maid"] + NEW_THEMES

# 「一对引号内含逗号」= 整链被当单个族名的错误形态
_QUOTED_COMMA_RE = re.compile(r'font-family:\s*"[^"]*,[^"]*"')


@pytest.fixture
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _load_qss(monkeypatch, theme_name: str, choice: str = "resource_rounded") -> str:
    """用真实 theme_engine 产出一套主题的最终 QSS（字体选择固定以保确定性）。"""
    from gui.qt_compat import QApplication
    from gui.theme_engine import ThemeEngine

    app = QApplication.instance()
    assert app is not None, "需要 QApplication"

    engine = ThemeEngine()
    monkeypatch.setattr(engine, "_font_choice", lambda: choice)
    assert engine.load_theme(theme_name) is True
    return app.styleSheet()


# ---------------------------------------------------------------------------
# ① qss_font_family 纯函数形态
# ---------------------------------------------------------------------------
def test_qss_font_family_quotes_each_family_but_generic():
    out = fonts.qss_font_family("yahei", "body")
    assert out == '"Microsoft YaHei", "remixicon", sans-serif'
    # 通用族不加引号
    assert out.endswith("sans-serif")
    assert '"sans-serif"' not in out
    # 不存在「一对引号内含逗号」的形态
    assert _QUOTED_COMMA_RE.search("font-family: " + out + ";") is None


def test_qss_font_family_contains_icon_family_for_both_scopes():
    for scope in ("body", "title"):
        out = fonts.qss_font_family("resource_rounded", scope)
        assert '"remixicon"' in out, scope
        assert out.index('"remixicon"') < out.index("sans-serif"), scope
        assert out.count('"remixicon"') == 1, scope


def test_font_family_chain_format_unchanged_no_quotes():
    """旧出口格式零变更：裸链、无引号（test_v19_b 依赖 split/startswith）。"""
    chain = fonts.font_family_chain("yahei", "body")
    assert '"' not in chain
    assert chain.split(",")[0].strip() == "Microsoft YaHei"
    assert fonts.primary_family("yahei", "body") == "Microsoft YaHei"


# ---------------------------------------------------------------------------
# ② load_theme 产出的 QSS 不再有「引号包整链」，且含 "remixicon"
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("theme_name", NEW_THEMES)
def test_rendered_qss_family_is_parseable_and_has_remixicon(monkeypatch, qapp, theme_name):
    qss = _load_qss(monkeypatch, theme_name, "resource_rounded")

    assert "${font_family}" not in qss, theme_name
    assert "${font_title}" not in qss, theme_name
    assert not _QUOTED_COMMA_RE.search(qss), f"{theme_name}: QSS 中仍有引号包整链的 font-family"
    assert '"remixicon"' in qss, f"{theme_name}: 未渲染图标族"
    assert "sans-serif" in qss, theme_name


@pytest.mark.parametrize("theme_name", NEW_THEMES)
def test_rendered_qss_title_token_uses_qss_form(monkeypatch, qapp, theme_name):
    """标题占位符（base.qss:245）同样走 QSS 出口。"""
    qss = _load_qss(monkeypatch, theme_name, "huninn")
    for m in re.finditer(r"font-family:\s*([^;]+);", qss):
        value = m.group(1).strip()
        assert not (value.startswith('"') and value.endswith('"') and "," in value), \
            f"{theme_name}: 引号包整链 -> {value!r}"


# ---------------------------------------------------------------------------
# ③ 七套主题 QSS 模板：无引号包整链 + 等宽声明为可解析形态
# ---------------------------------------------------------------------------
def test_all_theme_templates_have_no_quoted_comma_family():
    for theme in ALL_THEMES:
        path = ROOT / "gui" / "themes" / f"{theme}.qss"
        text = path.read_text(encoding="utf-8")
        assert not _QUOTED_COMMA_RE.search(text), f"{theme}.qss 仍有引号包整链"


def test_base_qss_placeholders_unquoted():
    text = (ROOT / "gui" / "themes" / "base.qss").read_text(encoding="utf-8")
    assert "${font_family}" in text and "${font_title}" in text
    assert '"${font_family}"' not in text
    assert '"${font_title}"' not in text


def test_mono_declarations_are_parseable_in_all_themes():
    """等宽声明必须是逐族引号形态（既有死声明修复）。"""
    for theme in ALL_THEMES:
        text = (ROOT / "gui" / "themes" / f"{theme}.qss").read_text(encoding="utf-8")
        assert '"Consolas, JetBrains Mono, monospace"' not in text
        assert '"JetBrains Mono, Consolas, monospace"' not in text
    # 至少命中一处已修正的 mono 声明
    ui_minimal = (ROOT / "gui" / "themes" / "ui_minimal.qss").read_text(encoding="utf-8")
    assert 'font-family: "Consolas", "JetBrains Mono", monospace;' in ui_minimal


# ---------------------------------------------------------------------------
# ④ 全仓静态纪律：无「一对引号内含逗号」的 font-family（含代码侧与模板）
# ---------------------------------------------------------------------------
def _scan_font_family_offenders() -> list:
    """返回全仓 ``font-family`` 中「一对引号内含逗号」的命中（路径, 行号, 原文）。"""
    hits = []
    files = sorted((ROOT / "gui").rglob("*.py")) + sorted((ROOT / "gui" / "themes").glob("*.qss"))
    for path in files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _QUOTED_COMMA_RE.search(line):
                hits.append((str(path.relative_to(ROOT)), lineno, line.strip()))
    return hits


def test_no_quoted_comma_font_family_anywhere_in_repo():
    """全仓（gui/**/*.py + gui/themes/*.qss）不得再有整链被一对引号包住的 font-family。"""
    hits = _scan_font_family_offenders()
    assert not hits, "存在引号包整链的 font-family：" + "; ".join(
        f"{p}:{n} -> {s}" for p, n, s in hits
    )


# ---------------------------------------------------------------------------
# ⑤ _build_default_qss 兜底链：含图标族且在通用族之前
# ---------------------------------------------------------------------------
def test_build_default_qss_family_has_icon_before_generic():
    """无主题文件时的兜底 QSS 也必须走 QSS 出口，图标族在 generic 之前。"""
    from gui.theme_engine import ThemeEngine

    out = ThemeEngine._build_default_qss({"colors": {}, "font": {}})
    m = re.search(r"font-family:\s*([^;]+);", out)
    assert m, "兜底 QSS 未产出 font-family"
    value = m.group(1).strip()

    assert '"remixicon"' in value, f"兜底族链缺图标族 -> {value!r}"
    assert value.index('"remixicon"') < value.index("sans-serif"), value
    # 通用族裸写、无引号包整链
    assert '"sans-serif"' not in value
    assert not _QUOTED_COMMA_RE.search("font-family: " + value + ";")


# ---------------------------------------------------------------------------
# ⑥ 字号单一收口纪律（永久守卫）：gui/**/*.py 不得在白名单外设字号
#
# 背景：应用级 QSS 一旦声明 font-size 就压过代码 setFont（控件自身 setStyleSheet
# 更优先）。因此在受样式表约束的控件上调用 setPointSize / setPixelSize 不会生效，
# 只会在代码里留下误导后人的死行。字号统一由 base.qss 的 id 规则单点定义。
#
# 白名单（仅下列三处合法，理由各异——确需自绘字号时，请显式加入本表并说明理由）：
# ---------------------------------------------------------------------------
_FONT_SIZE_WHITELIST = {
    # gui/icons.py —— 图标字形**绘制路径**：把字形渲成 QPixmap 时按目标像素尺寸设字号，
    #                 不经 QSS，故必须保留（setPixelSize，两处）。
    "gui/icons.py",
    # gui/widgets/maid_pet.py —— 自绘宠物陪衬：setPixelSize(max(12, self._size // 2))
    #                 是按控件尺寸**计算**的动态值，非固定排版字号。
    "gui/widgets/maid_pet.py",
    # gui/widgets/message_bubble.py —— 自绘徽标：同为按尺寸计算的动态值（:203）；
    #                 该文件其余字号（代码块 #codeEditor）已由控件自身样式表接管。
    "gui/widgets/message_bubble.py",
}
# 只按 AST 判定：注释、字符串字面量、文档字符串里的同名文本不是 Call 节点，天然不命中。
_FONT_SIZE_ATTRS = frozenset({"setPointSize", "setPixelSize"})


def _font_size_calls_in_source(source: str) -> list:
    """AST 解析源码，返回字号调用坐标 ``(lineno, col, segment)``（列 1 起）。

    只认真正的调用节点 ``X.setPointSize(...)`` / ``X.setPixelSize(...)``。用正则扫文本会
    把行尾注释、字符串字面量、文档字符串里的同名文本误判为调用（CI 假红），故一律走 AST。
    """
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _FONT_SIZE_ATTRS:
            out.append((
                node.lineno,
                node.col_offset + 1,
                ast.get_source_segment(source, node) or "",
            ))
    return out


def _scan_font_size_offenders(project_root: Path | None = None) -> list:
    """返回白名单外的字号调用：``(rel_path, lineno, col, segment)``。

    ``project_root`` 默认本仓根（扫描其 ``gui/**/*.py``）；回归用例可指向临时假树。
    """
    root = ROOT if project_root is None else project_root
    hits = []
    for path in sorted((root / "gui").rglob("*.py")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if rel in _FONT_SIZE_WHITELIST:
            continue
        source = path.read_text(encoding="utf-8")
        for lineno, col, segment in _font_size_calls_in_source(source):
            hits.append((rel, lineno, col, segment))
    return hits


def test_no_direct_font_size_outside_whitelist():
    """字号由 QSS 单点定义；在受样式表约束的控件上调用 setPointSize 会被压掉、只留死行。

    若确需自绘字号，请显式加入本白名单并说明理由。
    """
    hits = _scan_font_size_offenders()
    assert not hits, (
        "字号由 QSS 单点定义；在受样式表约束的控件上调用 setPointSize 会被压掉、只留死行。"
        "若确需自绘字号，请显式加入本白名单并说明理由。命中："
        + "; ".join(
            f"{p}:{n}:{c} -> {seg}" for p, n, c, seg in hits
        )
    )


def test_font_size_guard_ignores_comments_and_strings(tmp_path):
    """回归：AST 扫描只认真正的调用，不受注释/字符串字面量/文档字符串干扰。"""
    fake = tmp_path / "gui" / "pages"
    fake.mkdir(parents=True)
    (fake / "fake_page.py").write_text(
        '"""文档字符串：这里曾 setPointSize(9)、setPixelSize(9)。"""\n'
        'x = 1  # 行尾注释：这里曾 setPointSize(12)\n'
        'text = "字符串字面量 setPixelSize(7)"\n'
        'def go(font):\n'
        '    font.setPointSize(16)  # 越界真实调用\n'
        '    return None\n',
        encoding="utf-8",
    )

    hits = _scan_font_size_offenders(tmp_path)
    assert len(hits) == 1, f"应只抓到 1 处真实调用，实得 {hits}"
    rel, lineno, col, segment = hits[0]
    assert rel.endswith("gui/pages/fake_page.py"), rel
    assert lineno == 5, hits
    assert segment == "font.setPointSize(16)", segment
    assert col == 5, hits
