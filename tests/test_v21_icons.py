# -*- coding: utf-8 -*-
"""V21-04 域3 图标内核单测（``gui/icons.py`` + 构建产物契约）。

覆盖 design-v21 §7.1「icons」行全部可自动化断言点：
  · 名 → 码位映射；未知名字 ``has()`` / ``glyph()`` 返回 Falsy；
  · 缺字体资源 → ``available() == False`` 且 ``icon()`` 返回**空** ``QIcon`` 不崩；
  · manifest ↔ TTF 实际字形一致性（用标准库解析 TTF cmap，无需 fontTools）；
  · ``QPixmapCache`` 键含 color 与 theme（换色 / 换肤后取到不同缓存项）；
  · ``configure()`` 注入后 ``theme_changed`` 能清缓存；
  · 无 ``QApplication`` 时 import 与查询不崩（子进程真验证）。

GUI 用例统一 ``QT_QPA_PLATFORM=offscreen``。
"""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import gui.icons as icons
from gui.qt_compat import QIcon, QObject, Signal

ROOT = Path(__file__).resolve().parents[1]

# design-v21 §2 / §4.5 冻结的侧栏 10 项图标名（域5 直接沿用；少一个即域5 被卡）
_NAV_ICON_NAMES = [
    "chat", "home", "auto_awesome", "menu_book", "edit",
    "list", "person", "settings", "tune",
]


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
def _reset_icons():
    icons._reset_state()
    yield
    icons._reset_state()
    try:
        icons.clear_cache()
    except Exception:
        pass


class _FakeEngine(QObject):
    """最小主题引擎桩（含 theme_changed 信号 + 取色 + 主题名）。"""

    theme_changed = Signal(str)

    def __init__(self, name: str = "ui_minimal", color: str = "#112233"):
        super().__init__()
        self._name = name
        self._color = color

    def current_theme_name(self) -> str:
        return self._name

    def get_color(self, key: str, fallback=None) -> str:
        return self._color


def _fake_ctx(engine: _FakeEngine):
    return SimpleNamespace(theme_engine=engine)


def _opaque_colors(icon: "QIcon", size: int = 16) -> dict:
    """统计图标非透明像素的 ARGB 颜色分布（用于断言着色生效）。"""
    image = icon.pixmap(size, size).toImage()
    counts = {}
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 0:
                name = "#{:02x}{:02x}{:02x}".format(color.red(), color.green(), color.blue())
                counts[name] = counts.get(name, 0) + 1
    return counts


def _read_ttf_codepoints(path: Path) -> set:
    """用标准库解析 TTF ``cmap``（format 4 / 12）→ 支持的码位集合（不依赖 fontTools）。"""
    data = path.read_bytes()
    num_tables = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for i in range(num_tables):
        off = 12 + i * 16
        tag = data[off:off + 4]
        toffset, tlen = struct.unpack(">II", data[off + 8:off + 16])
        tables[tag] = (toffset, tlen)
    if b"cmap" not in tables:
        return set()
    cmap_off = tables[b"cmap"][0]
    n_sub = struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]
    sub_offsets = []
    for i in range(n_sub):
        pos = cmap_off + 4 + i * 8
        _plat, _enc, sub_rel = struct.unpack(">HHI", data[pos:pos + 8])
        sub_offsets.append(cmap_off + sub_rel)

    codepoints = set()
    for so in sub_offsets:
        fmt = struct.unpack(">H", data[so:so + 2])[0]
        if fmt == 4:
            seg_x2 = struct.unpack(">H", data[so + 6:so + 8])[0]
            seg = seg_x2 // 2
            if seg == 0:
                continue
            end_pos = so + 14
            ends = struct.unpack(f">{seg}H", data[end_pos:end_pos + seg_x2])
            start_pos = end_pos + seg_x2 + 2  # 跳过一个 reservedPad
            starts = struct.unpack(f">{seg}H", data[start_pos:start_pos + seg_x2])
            for start, end in zip(starts, ends):
                if start == 0xFFFF and end == 0xFFFF:
                    continue
                codepoints.update(range(start, end + 1))
        elif fmt == 12:
            n_groups = struct.unpack(">I", data[so + 12:so + 16])[0]
            group_pos = so + 16
            for g in range(n_groups):
                gpos = group_pos + g * 12
                sc, ec, _gi = struct.unpack(">III", data[gpos:gpos + 12])
                codepoints.update(range(sc, ec + 1))
    return codepoints


def _manifest() -> dict:
    path = icons._asset_path(icons._MANIFEST_FILE)
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# ① 缺资源 → 不可用 + 空 QIcon 不崩
# ---------------------------------------------------------------------------
def test_missing_font_resource_unavailable_and_null_icon(qapp, monkeypatch):
    monkeypatch.setattr(icons, "_asset_path", lambda filename: None)
    icons._reset_state()

    assert icons.available() is False
    assert icons.has("chat") is False
    assert icons.glyph("chat") is None

    rendered = icons.icon("chat", 16)
    assert isinstance(rendered, QIcon)
    assert rendered.isNull() is True


def test_register_icon_font_returns_none_without_resource(monkeypatch):
    monkeypatch.setattr(icons, "_asset_path", lambda filename: None)
    icons._reset_state()
    assert icons.register_icon_font() is None
    assert icons.available() is False


# ---------------------------------------------------------------------------
# ② has / glyph 已登记 vs 未登记
# ---------------------------------------------------------------------------
def test_has_and_glyph_known_and_unknown():
    assert icons.has("chat") is True
    char = icons.glyph("chat")
    assert isinstance(char, str) and len(char) == 1
    assert ord(char) == _manifest()["chat"]

    for unknown in ("__not_an_icon__", "", None, 123):
        assert not icons.has(unknown)
        assert icons.glyph(unknown) is None


def test_iconset_and_dir_constants():
    assert icons.ICON_DIR_REL == "assets/icons"
    assert icons.ICONSET == "remix_icon"


# ---------------------------------------------------------------------------
# ③ manifest ↔ TTF 字形一致性
# ---------------------------------------------------------------------------
def test_manifest_covers_nav_and_is_well_formed():
    manifest = _manifest()
    assert manifest, "icons_manifest.json 缺失或为空（构建期脚本未产出？）"
    assert all(isinstance(v, int) and 0 < v <= 0x10FFFF for v in manifest.values())
    for name in _NAV_ICON_NAMES:
        assert name in manifest, f"侧栏图标名 {name!r} 未登记（域5 会被卡）"
    assert "settings" in manifest and "tune" in manifest


def test_manifest_codepoints_all_present_in_ttf():
    manifest = _manifest()
    ttf = icons._asset_path(icons._FONT_FILE)
    if not manifest or ttf is None or not ttf.exists():
        pytest.skip("构建产物缺失，跳过 TTF↔manifest 一致性")
    available_codepoints = _read_ttf_codepoints(ttf)
    assert available_codepoints, "TTF cmap 解析为空"
    missing = sorted(cp for cp in manifest.values() if cp not in available_codepoints)
    assert not missing, f"manifest 登记的码位未在 TTF 字形表中：{[hex(c) for c in missing]}"


@pytest.mark.skipif(
    not (ROOT / "gui" / "widgets" / "sidebar.py").exists(),
    reason="sidebar 不在树内",
)
def test_sidebar_nav_items_icon_names_covered():
    """sidebar 改为 4 元组后（域5），其 icon_name 必须都在 manifest 内。"""
    from gui.widgets.sidebar import SidebarWidget

    manifest = _manifest()
    for item in SidebarWidget.NAV_ITEMS:
        if len(item) < 4:
            pytest.skip("sidebar 仍为 3 元组（域5 未落点），跳过")
        icon_name = item[2]
        if icon_name is None:
            continue
        assert icon_name in manifest, f"NAV_ITEMS 图标名 {icon_name!r} 未登记"


# ---------------------------------------------------------------------------
# ④ 缓存键含 color / theme
# ---------------------------------------------------------------------------
def test_cache_key_includes_color_and_theme(qapp):
    assert icons.register_icon_font()
    engine = _FakeEngine(name="ui_minimal", color="#112233")
    icons.configure(_fake_ctx(engine))

    icons.icon("chat", 16, "#ff0000")
    icons.icon("chat", 16, "#00ff00")
    assert "chat|16|#ff0000|ui_minimal" in icons._cache_keys
    assert "chat|16|#00ff00|ui_minimal" in icons._cache_keys

    engine._name = "ui_night"
    icons.icon("chat", 16, "#ff0000")
    assert "chat|16|#ff0000|ui_night" in icons._cache_keys
    assert "chat|16|#ff0000|ui_minimal" != "chat|16|#ff0000|ui_night"


def test_render_color_follows_argument_and_theme(qapp):
    assert icons.register_icon_font()
    engine = _FakeEngine(color="#ff0000")
    icons.configure(_fake_ctx(engine))

    red = _opaque_colors(icons.icon("chat", 16, "#ff0000"))
    assert "#ff0000" in red, f"指定色未生效：{red}"

    # color=None → 唯一取色入口 theme_color(app_ctx, "text", fallback)
    engine._color = "#00ff00"
    green = _opaque_colors(icons.icon("chat", 16))
    assert "#00ff00" in green, f"活动色板取色未生效（应走 theme_color）：{green}"


def test_icon_dimensions_and_dpr(qapp):
    assert icons.register_icon_font()
    rendered = icons.icon("chat", 20)
    assert rendered.isNull() is False
    # QIcon 逻辑尺寸应贴近请求值（高 DPI 由 setDevicePixelRatio 适配）
    assert rendered.actualSize(rendered.pixmap(20, 20).size()).width() > 0
    pixmap = rendered.pixmap(20, 20)
    assert pixmap.devicePixelRatio() >= 1.0


def test_font_api_returns_family_and_pixel_size(qapp):
    family = icons.register_icon_font()
    assert family
    qfont = icons.font(18)
    assert qfont.pixelSize() == 18
    assert qfont.family() == family


# ---------------------------------------------------------------------------
# ⑤ configure 注入 + theme_changed 清缓存
# ---------------------------------------------------------------------------
def test_theme_changed_clears_cache(qapp):
    from gui.qt_compat import QPixmapCache

    assert icons.register_icon_font()
    engine = _FakeEngine()
    icons.configure(_fake_ctx(engine))

    icons.icon("chat", 16, "#abcdef")
    assert icons._cache_keys, "渲染后应有缓存键"
    key = icons._cache_keys[-1]
    cached = QPixmapCache.find(key)
    assert cached is not None and not cached.isNull()

    engine.theme_changed.emit("ui_night")
    assert icons._cache_keys == []
    after = QPixmapCache.find(key)
    assert after is None or after.isNull()


def test_configure_is_idempotent_and_optional(qapp):
    engine = _FakeEngine()
    icons.configure(_fake_ctx(engine))
    icons.configure(_fake_ctx(engine))
    assert icons._subscribed is True

    icons.configure(SimpleNamespace(theme_engine=None))  # 无引擎不崩
    icons.configure(None)  # 无 app_ctx 不崩


# ---------------------------------------------------------------------------
# 无 QApplication 不崩（子进程真验证）
# ---------------------------------------------------------------------------
def test_import_and_query_without_qapplication():
    code = (
        "import gui.icons as i\n"
        "print('IMPORT_OK', i.available(), i.has('chat'), bool(i.glyph('chat')))\n"
    )
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "IMPORT_OK False True True" in proc.stdout


# ---------------------------------------------------------------------------
# ⑥ text_glyph 文本内嵌便捷入口（D-V21-06 / §4.4.1）
# ---------------------------------------------------------------------------
def test_text_glyph_constant_is_icon_family_name():
    assert icons.FONT_FAMILY_NAME == "remixicon"


def test_text_glyph_available_returns_real_glyph(qapp):
    assert icons.register_icon_font()
    assert icons.available() and icons.has("add")
    char = icons.text_glyph("add", "\u2795")  # ➕
    assert char == icons.glyph("add")
    assert char != "\u2795"


def test_text_glyph_unavailable_returns_fallback():
    icons._reset_state()  # 造「图标字体未注册」不可用态
    assert icons.available() is False
    assert icons.text_glyph("add", "\u2795") == "\u2795"


def test_text_glyph_unknown_name_returns_fallback(qapp):
    assert icons.register_icon_font()
    assert icons.available()
    for unknown in ("__not_an_icon__", "", None, 123):
        assert icons.text_glyph(unknown, "fallback-text") == "fallback-text"


# ---------------------------------------------------------------------------
# ⑦ 家族链含图标回退族且在 generic 之前（§4.4.2）
# ---------------------------------------------------------------------------
def _chain_names(choice, scope):
    from gui import fonts
    return [c.strip() for c in fonts.font_family_chain(choice, scope).split(",")]


@pytest.mark.parametrize("scope", ["body", "title"])
def test_font_family_chain_contains_icon_family_before_generic(scope):
    names = _chain_names("resource_rounded", scope)
    assert icons.FONT_FAMILY_NAME in names, f"{scope} 链缺图标族：{names}"
    assert "sans-serif" in names, f"{scope} 链缺 generic 族：{names}"
    assert names.index(icons.FONT_FAMILY_NAME) < names.index("sans-serif")
    # 去重保序：图标族不重复
    assert names == list(dict.fromkeys(names))
    assert names.count(icons.FONT_FAMILY_NAME) == 1


def test_font_family_chain_yahei_body_order():
    from gui import fonts
    chain = fonts.font_family_chain("yahei", "body")
    names = [c.strip() for c in chain.split(",")]
    assert names[0] == "Microsoft YaHei"          # primary_family 契约不受影响
    assert fonts.primary_family("yahei", "body") == "Microsoft YaHei"
    assert chain.startswith("Microsoft YaHei")
    assert chain.endswith("sans-serif")
    assert names.index(icons.FONT_FAMILY_NAME) < names.index("sans-serif")
    assert names.index(icons.FONT_FAMILY_NAME) > names.index("Microsoft YaHei")


def test_font_family_chain_title_huninn_contains_icon_family():
    names = _chain_names("huninn", "title")
    assert icons.FONT_FAMILY_NAME in names
    assert "sans-serif" in names
    assert names.index(icons.FONT_FAMILY_NAME) < names.index("sans-serif")
