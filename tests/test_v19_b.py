# -*- coding: utf-8 -*-
"""v1.9 第二批测试（B 块：字体系统 V19-06 ~ V19-10）。

覆盖：
  ① 六字体 id 常量 + 默认值（Q-E6）+ 粉圆 title-only 标记（Q-E4）；
  ② 家族链 font_family_chain（body/title 两套 + fallback 尾 + 未知值回落）；
  ③ 粉圆 scope 守卫：body 场景强制回落资源圆体（单一收口）；
  ④ 注册优雅降级：缺字体文件不抛；真实字体文件 → applicationFontFamilies 取真实 family；
  ⑤ theme_engine 接入：${font_family} / ${font_title} 替换 + app.setFont 用链首 + 契约不变；
  ⑥ GuiConfig.font_family 零迁移（老配置无键 → 默认资源圆体）+ save/load round-trip；
  ⑦ spec datas/hiddenimports + base.qss ${font_title} + About 字体条目。

隔离：Qt offscreen；GuiConfig 走 tmp_path（monkeypatch get_user_data_dir）；零真实 APPDATA。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from gui import fonts  # noqa: E402
from gui.qt_compat import QApplication  # noqa: E402


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------
def _qapp():
    return QApplication.instance() or QApplication([])


def _find_system_ttf():
    """找一个可注册的系统 TTF/OTF 作为「真实字体」样本（找不到则 skip）。"""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in ("simkai.ttf", "simhei.ttf", "simfang.ttf", "Deng.ttf",
                 "simsun.ttc", "msyh.ttc"):
        p = windir / "Fonts" / name
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# ① 常量与默认值
# ---------------------------------------------------------------------------
class TestFontIds:
    def test_six_ids(self):
        assert set(fonts.FONT_IDS) == {
            "resource_rounded", "huninn", "youyuan", "yahei", "kaiti", "dengxian",
        }

    def test_choice_list_covers_all(self):
        assert set(fonts.FONT_CHOICES) == set(fonts.FONT_IDS)

    def test_default_is_resource_rounded(self):
        assert fonts.default_font_choice() == "resource_rounded"

    def test_bundled_flags(self):
        assert fonts.FONT_IDS["resource_rounded"]["bundled"] is True
        assert fonts.FONT_IDS["huninn"]["bundled"] is True
        assert fonts.FONT_IDS["yahei"]["bundled"] is False
        assert fonts.FONT_IDS["youyuan"]["qt_family"] == "YouYuan"

    def test_title_only_only_huninn(self):
        assert fonts.is_title_only("huninn") is True
        for fid in ("resource_rounded", "youyuan", "yahei", "kaiti", "dengxian"):
            assert fonts.is_title_only(fid) is False

    def test_labels_non_empty(self):
        for fid in fonts.FONT_IDS:
            assert fonts.font_choice_label(fid)

    def test_body_choices_exclude_huninn(self):
        assert "huninn" not in fonts.FONT_IDS_BODY
        assert "resource_rounded" in fonts.FONT_IDS_BODY


# ---------------------------------------------------------------------------
# ② 家族链
# ---------------------------------------------------------------------------
class TestFamilyChain:
    def test_body_chain_fallback_tail(self):
        chain = fonts.font_family_chain("yahei", "body")
        assert chain.startswith("Microsoft YaHei")
        assert chain.endswith("sans-serif")

    def test_unknown_choice_falls_back(self):
        assert fonts.font_family_chain("__nope__", "body") == \
            fonts.font_family_chain("resource_rounded", "body")

    def test_empty_choice_falls_back(self):
        assert fonts.font_family_chain(None, "body") == \
            fonts.font_family_chain("resource_rounded", "body")

    def test_chain_has_no_duplicate_families(self):
        chain = fonts.font_family_chain("yahei", "body").split(",")
        names = [c.strip() for c in chain]
        assert names == list(dict.fromkeys(names))

    def test_primary_family_is_head(self):
        assert fonts.primary_family("yahei", "body") == "Microsoft YaHei"


# ---------------------------------------------------------------------------
# ③ 粉圆 scope 守卫（Q-E4）
# ---------------------------------------------------------------------------
class TestHuninnScopeGuard:
    def test_huninn_body_falls_back_to_default(self):
        # 粉圆在正文场景强制回落资源圆体 → 与显式资源圆体链一致
        assert fonts.font_family_chain("huninn", "body") == \
            fonts.font_family_chain("resource_rounded", "body")

    def test_huninn_body_never_uses_huninn(self):
        chain = fonts.font_family_chain("huninn", "body")
        assert "huninn" not in chain.lower()

    def test_huninn_title_scope_allowed(self):
        # title 场景不回落（未注册时仍退雅黑，但不会退成 resource 语义）
        chain = fonts.font_family_chain("huninn", "title")
        assert chain.endswith("sans-serif")


# ---------------------------------------------------------------------------
# ④ 注册优雅降级
# ---------------------------------------------------------------------------
class TestRegistration:
    def test_resolve_font_path_points_to_assets_fonts(self):
        _qapp()
        p = fonts.resolve_font_path("whatever.ttf")
        assert p is not None
        assert p.name == "whatever.ttf"
        assert p.parent.name == "fonts"
        assert p.parent.parent.name == "assets"

    def test_frozen_mode_path_hit(self, monkeypatch, tmp_path):
        """frozen 态：sys._MEIPASS 下 assets/fonts/ 必须被命中（⚠-2 路径一致性）。"""
        _qapp()
        (tmp_path / "assets" / "fonts").mkdir(parents=True)
        (tmp_path / "assets" / "fonts" / "ResourceHanRoundedCN-Regular.ttf").write_bytes(b"x")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        p = fonts.resolve_font_path("ResourceHanRoundedCN-Regular.ttf")
        assert p is not None and p.exists()
        assert p == tmp_path / "assets" / "fonts" / "ResourceHanRoundedCN-Regular.ttf"

    def test_register_missing_files_does_not_raise(self, monkeypatch):
        _qapp()
        monkeypatch.setattr(fonts, "BUNDLED_FONTS", {
            "resource_rounded": {"files": ["__definitely_missing__.ttf"],
                                 "role": "body", "family_hint": "x"},
        })
        saved = dict(fonts._REGISTERED_FAMILIES)
        fonts._REGISTERED_FAMILIES.clear()
        try:
            result = fonts.register_bundled_fonts()   # 不抛
            assert "resource_rounded" not in result   # 缺文件 → 不注册
        finally:
            fonts._REGISTERED_FAMILIES.clear()
            fonts._REGISTERED_FAMILIES.update(saved)

    def test_register_real_font_reads_true_family(self, monkeypatch):
        _qapp()
        sample = _find_system_ttf()
        if sample is None:
            pytest.skip("无系统字体样本可注册")
        monkeypatch.setattr(fonts, "BUNDLED_FONTS", {
            "resource_rounded": {"files": ["sys.ttf"], "role": "body",
                                 "family_hint": "___no_match___"},
        })
        monkeypatch.setattr(fonts, "resolve_font_path", lambda rel: sample)
        saved = dict(fonts._REGISTERED_FAMILIES)
        fonts._REGISTERED_FAMILIES.clear()
        try:
            result = fonts.register_bundled_fonts()
            assert "resource_rounded" in result
            real = result["resource_rounded"]
            # 真实 family 由 Qt 返回，非文件名
            assert real and not real.endswith(".ttf")
            assert fonts.registered_family("resource_rounded") == real
            assert fonts.font_family_chain("resource_rounded", "body").startswith(real)
        finally:
            fonts._REGISTERED_FAMILIES.clear()
            fonts._REGISTERED_FAMILIES.update(saved)


# ---------------------------------------------------------------------------
# ⑤ theme_engine 接入（契约零变更）
# ---------------------------------------------------------------------------
class TestThemeEngineIntegration:
    def test_load_theme_replaces_font_tokens(self, monkeypatch):
        app = _qapp()
        from gui.theme_engine import ThemeEngine
        engine = ThemeEngine()
        monkeypatch.setattr(engine, "_font_choice", lambda: "yahei")
        assert engine.load_theme("cute") is True
        qss = app.styleSheet()
        assert "${font_family}" not in qss
        assert "${font_title}" not in qss
        assert "Microsoft YaHei" in qss

    def test_font_title_token_present_when_huninn(self, monkeypatch):
        app = _qapp()
        from gui.theme_engine import ThemeEngine
        engine = ThemeEngine()
        monkeypatch.setattr(engine, "_font_choice", lambda: "huninn")
        engine.load_theme("cute")
        # 粉圆未注册 → 标题链退雅黑；关键是无残留 token
        assert "${font_title}" not in app.styleSheet()

    def test_font_choice_reads_config(self, monkeypatch):
        _qapp()
        from gui.theme_engine import ThemeEngine
        import gui.config as config_mod
        engine = ThemeEngine()
        monkeypatch.setattr(config_mod.GuiConfig, "load",
                            classmethod(lambda cls: SimpleNamespace(font_family="kaiti")))
        assert engine._font_choice() == "kaiti"

    def test_font_choice_default_when_config_broken(self, monkeypatch):
        _qapp()
        from gui.theme_engine import ThemeEngine
        import gui.config as config_mod
        engine = ThemeEngine()

        def _boom(cls):
            raise RuntimeError("no config")

        monkeypatch.setattr(config_mod.GuiConfig, "load", classmethod(_boom))
        assert engine._font_choice() == fonts.default_font_choice()


# ---------------------------------------------------------------------------
# ⑥ GuiConfig 零迁移 + round-trip
# ---------------------------------------------------------------------------
class TestConfigPersistence:
    def test_default_is_resource_rounded(self):
        from gui.config import GuiConfig
        assert GuiConfig().font_family == "resource_rounded"

    def test_old_config_without_key_upgrades_to_default(self, monkeypatch, tmp_path):
        from gui.config import GuiConfig
        import gui.config as config_mod
        monkeypatch.setattr(config_mod, "get_user_data_dir", lambda: tmp_path)
        (tmp_path / "gui_config.json").write_text(
            '{"theme_name": "minimal", "font_size": 14}', encoding="utf-8")
        cfg = GuiConfig.load()
        assert cfg.font_family == "resource_rounded"   # Q-E6 自动升级

    def test_save_load_round_trip(self, monkeypatch, tmp_path):
        from gui.config import GuiConfig
        import gui.config as config_mod
        monkeypatch.setattr(config_mod, "get_user_data_dir", lambda: tmp_path)
        cfg = GuiConfig()
        cfg.font_family = "kaiti"
        cfg.save()
        assert "font_family" in (tmp_path / "gui_config.json").read_text(encoding="utf-8")
        assert GuiConfig.load().font_family == "kaiti"


# ---------------------------------------------------------------------------
# ⑦ spec / base.qss / About / main.py 落点
# ---------------------------------------------------------------------------
class TestWiringArtifacts:
    def test_spec_has_font_datas(self):
        text = (ROOT / "maid_coder_gui.spec").read_text(encoding="utf-8")
        assert "('gui/assets/fonts', 'assets/fonts')" in text

    def test_spec_has_fonts_hiddenimport(self):
        text = (ROOT / "maid_coder_gui.spec").read_text(encoding="utf-8")
        assert "'gui.fonts'" in text

    def test_base_qss_uses_font_title_token(self):
        text = (ROOT / "gui/themes/base.qss").read_text(encoding="utf-8")
        assert "${font_title}" in text

    def test_about_lists_both_fonts(self):
        from gui.pages import page_about
        blob = " ".join(page_about._THIRD_PARTY_ITEMS)
        assert "资源圆体" in blob and "粉圆" in blob
        assert "OFL" in blob

    def test_main_registers_fonts_before_mainwindow(self):
        text = (ROOT / "gui/main.py").read_text(encoding="utf-8")
        assert "register_bundled_fonts" in text
        assert text.index("register_bundled_fonts") < text.index("MainWindow(app_ctx)")

    def test_settings_has_font_combo(self):
        text = (ROOT / "gui/pages/page_settings.py").read_text(encoding="utf-8")
        assert "font_combo" in text and "_on_font_changed" in text


# ---------------------------------------------------------------------------
# ⑧ 已构建产物核对（字体文件未生成时自动跳过）
# ---------------------------------------------------------------------------
_FONT_DIR = ROOT / "gui" / "assets" / "fonts"


class TestBuiltArtifacts:
    def _have(self):
        return (_FONT_DIR / "ResourceHanRoundedCN-Regular.ttf").exists()

    def test_regular_and_medium_present(self):
        if not self._have():
            pytest.skip("字体子集未构建（先跑 tools/build_fonts.py）")
        assert (_FONT_DIR / "ResourceHanRoundedCN-Regular.ttf").stat().st_size > 500_000
        assert (_FONT_DIR / "ResourceHanRoundedCN-Medium.ttf").stat().st_size > 500_000

    def test_huninn_subset_present_and_small(self):
        if not self._have():
            pytest.skip("字体子集未构建")
        p = _FONT_DIR / "jf-openhuninn-subset.ttf"
        assert p.exists()
        assert p.stat().st_size < 1_500_000   # 标题子集应压到数百 KB 级

    def test_ofl_licenses_present(self):
        if not self._have():
            pytest.skip("字体子集未构建")
        assert (_FONT_DIR / "OFL-Resource-Han-Rounded.txt").exists()
        assert (_FONT_DIR / "OFL-jf-open-huninn.txt").exists()
        assert (ROOT / "docs" / "third_party_licenses" / "OFL-Resource-Han-Rounded.txt").exists()

    def test_registration_reads_true_families(self):
        if not self._have():
            pytest.skip("字体子集未构建")
        _qapp()
        saved = dict(fonts._REGISTERED_FAMILIES)
        fonts._REGISTERED_FAMILIES.clear()
        try:
            reg = fonts.register_bundled_fonts()
            assert "resource_rounded" in reg
            assert "huninn" in reg
            real_body = reg["resource_rounded"]
            assert real_body and not real_body.lower().endswith(".ttf")
            # 正文链以真实 family 开头；粉圆 body 场景回落资源圆体
            assert fonts.font_family_chain("resource_rounded", "body").startswith(real_body)
            assert fonts.font_family_chain("huninn", "body").startswith(real_body)
            # 标题链以粉圆真实 family 开头
            assert fonts.font_family_chain("huninn", "title").startswith(reg["huninn"])
        finally:
            fonts._REGISTERED_FAMILIES.clear()
            fonts._REGISTERED_FAMILIES.update(saved)

    def test_rare_char_fallback_chain_intact(self):
        if not self._have():
            pytest.skip("字体子集未构建")
        # 子集不含生僻字（龘 U+9F98 不在 GB2312）→ 依赖链尾雅黑回退，链必须含雅黑
        chain = fonts.font_family_chain("resource_rounded", "body")
        assert "Microsoft YaHei" in chain
