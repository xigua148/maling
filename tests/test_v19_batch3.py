# -*- coding: utf-8 -*-
"""v1.9 第三批测试（A 块：四套 UI 风格）。

小轮 1（V19-11 ~ V19-14）：
  ① 四条目增量 + 键位对齐（D-V19-09）：colors/colors_dark 同键、语义键齐备、
     dark_locked（仅 ui_night）/ brand_persona（仅 ui_whale）；
  ② 旧值读时映射（D-V19-10）：cute/maid→ui_cream、minimal→ui_minimal、未知→ui_minimal，
     load_theme 归一 + 回写配置；
  ③ 深色变体对照（D-V19-15）：A/B/D 关键 token 命中定稿表 + 用户气泡「同族深底」结构；
  ④ 三浅色 QSS 加载：无 ${...} 残留 token、D 风格含 qlineargradient 点缀；
  ⑤ is_dark_effective（D-V19-13/⚠-3）+ page_editor 明暗判断接入；
  ⑥ C 深色夜间进出收口 apply_night_lock（D-V19-11/Q-E2）；
  ⑦ GuiConfig 默认 ui_minimal + theme_mode_before_night 持久化；
  ⑧ 切换器三处落点（设置页/顶栏/onboarding）+ _switch_theme 补 save。

小轮 2（V19-15 ~ V19-17）：
  ⑨ ui_night.qss 肤感层：文件在、token 全注册、加载零残留、深色 tone 命中、无新图片资产；
  ⑩ D 风格自称 brand_persona_self（V19-16/Q-E3）：给定名→名字、空名→我、非 D 风格→None、
     人设标签永不进自称位；
  ⑪ 文案点接线：page_home（欢迎语/问候兜底）+ screen_watch_bar（状态 chip）+ 产品名不变。

隔离：Qt offscreen；GuiConfig 走 tmp_path（monkeypatch get_user_data_dir）；零真实 APPDATA。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from gui.qt_compat import QApplication  # noqa: E402
from gui.theme_engine import ThemeEngine, apply_night_lock  # noqa: E402


def _qapp():
    return QApplication.instance() or QApplication([])


def _isolate_config(monkeypatch, tmp_path):
    """把 GuiConfig 落盘目录指到 tmp_path，避免污染真实用户配置。"""
    import gui.config as config_mod
    monkeypatch.setattr(config_mod, "get_user_data_dir", lambda: tmp_path)


# ---------------------------------------------------------------------------
# ① 四条目增量 + 键位对齐（D-V19-09）
# ---------------------------------------------------------------------------
class TestThemeDefinitions:
    def test_four_ids_present(self):
        for tid in ("ui_minimal", "ui_cream", "ui_night", "ui_whale"):
            assert tid in ThemeEngine.THEME_DEFINITIONS

    def test_theme_ids_constant(self):
        assert ThemeEngine.THEME_IDS == ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
        assert ThemeEngine.DEFAULT_THEME_ID == "ui_minimal"

    def test_qss_file_present(self):
        for tid in ThemeEngine.THEME_IDS:
            assert ThemeEngine.THEME_DEFINITIONS[tid]["qss_file"] == f"themes/{tid}.qss"

    def test_colors_dark_key_aligned(self):
        for tid in ThemeEngine.THEME_IDS:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            assert set(td["colors"].keys()) == set(td["colors_dark"].keys()), tid

    def test_semantic_keys_registered(self):
        need = {"accent_light", "bubble_user_bg", "bubble_ai_bg", "bubble_user_text",
                "bubble_ai_text", "chat_bg", "chat_border", "pet_bubble_bg",
                "text_on_accent", "focus_accent", "code_bg", "code_text", "code_lang"}
        for tid in ThemeEngine.THEME_IDS:
            colors = ThemeEngine.THEME_DEFINITIONS[tid]["colors"]
            assert need <= set(colors.keys()), (tid, need - set(colors.keys()))

    def test_layout_tokens(self):
        for tid in ThemeEngine.THEME_IDS:
            layout = ThemeEngine.THEME_DEFINITIONS[tid]["layout"]
            assert {"radius_sm", "radius_md", "radius_lg", "radius_pill",
                    "spacing_xs", "spacing_sm", "spacing_md", "spacing_lg"} <= set(layout)

    def test_dark_locked_only_night(self):
        assert ThemeEngine.is_dark_locked("ui_night") is True
        for tid in ("ui_minimal", "ui_cream", "ui_whale"):
            assert ThemeEngine.is_dark_locked(tid) is False

    def test_brand_persona_only_whale(self):
        assert ThemeEngine.is_brand_persona("ui_whale") is True
        for tid in ("ui_minimal", "ui_cream", "ui_night"):
            assert ThemeEngine.is_brand_persona(tid) is False

    def test_old_three_still_retained(self):
        # R-D：旧三 QSS/条目保留（不删），只是 UI 不暴露
        for lid in ("cute", "minimal", "maid"):
            assert lid in ThemeEngine.THEME_DEFINITIONS


# ---------------------------------------------------------------------------
# ② 旧值读时映射（D-V19-10）
# ---------------------------------------------------------------------------
class TestLegacyMapping:
    def test_normalize_table(self):
        assert ThemeEngine.normalize_theme_id("cute") == "ui_cream"
        assert ThemeEngine.normalize_theme_id("maid") == "ui_cream"
        assert ThemeEngine.normalize_theme_id("minimal") == "ui_minimal"

    def test_normalize_unknown_falls_back_default(self):
        assert ThemeEngine.normalize_theme_id("bogus") == "ui_minimal"
        assert ThemeEngine.normalize_theme_id("") == "ui_minimal"

    def test_normalize_new_id_passthrough(self):
        for tid in ThemeEngine.THEME_IDS:
            assert ThemeEngine.normalize_theme_id(tid) == tid

    def test_load_legacy_maps_and_returns_true(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        assert eng.load_theme("cute") is True
        assert eng.current_theme_name() == "ui_cream"

    def test_load_unknown_falls_back(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        assert eng.load_theme("nonexistent-style") is True
        assert eng.current_theme_name() == "ui_minimal"

    def test_legacy_written_back_to_config(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        eng.load_theme("minimal")   # 旧值 → ui_minimal 回写
        from gui.config import GuiConfig
        assert GuiConfig.load().theme_name == "ui_minimal"


# ---------------------------------------------------------------------------
# ③ 深色变体对照（D-V19-15）
# ---------------------------------------------------------------------------
class TestDarkVariants:
    def _dark(self, tid):
        return ThemeEngine.THEME_DEFINITIONS[tid]["colors_dark"]

    def test_a_minimal_dark(self):
        d = self._dark("ui_minimal")
        assert d["bg"] == "#17171A"
        assert d["accent"] == "#FF5E93"
        assert d["bubble_user_bg"] == "#3A2430"
        assert d["bubble_user_text"] == "#F2DCE6"

    def test_b_cream_dark(self):
        d = self._dark("ui_cream")
        assert d["bg"] == "#201A17"
        assert d["accent"] == "#FF9FB2"
        assert d["bubble_user_bg"] == "#4A2F34"
        assert d["bubble_user_text"] == "#F7E4E8"

    def test_d_whale_dark(self):
        d = self._dark("ui_whale")
        assert d["bg"] == "#0E1A21"
        assert d["accent"] == "#4FC0DA"
        assert d["bubble_user_bg"] == "#12333E"
        assert d["bubble_user_text"] == "#E2F1F7"

    def test_bubble_not_accent_solid(self):
        # PM 阻塞项修正：深色用户气泡 ≠ 亮 accent 实底（同族深底）
        for tid in ("ui_minimal", "ui_cream", "ui_whale"):
            d = self._dark(tid)
            assert d["bubble_user_bg"] != d["accent"]

    def test_night_colors_equals_dark(self):
        td = ThemeEngine.THEME_DEFINITIONS["ui_night"]
        for k, v in td["colors"].items():
            assert td["colors_dark"][k] == v, k

    def test_night_light_palette_already_dark(self):
        # C 风格自身即深色：即便非深色模式下取色也是深底
        assert ThemeEngine.THEME_DEFINITIONS["ui_night"]["colors"]["bg"] == "#131114"


# ---------------------------------------------------------------------------
# ④ 三浅色 QSS 加载（无 token 残留 + D 渐变）
# ---------------------------------------------------------------------------
class TestQssLoading:
    def _load(self, monkeypatch, tmp_path, tid):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        assert eng.load_theme(tid) is True
        return QApplication.instance().styleSheet()

    def test_ab_whale_qss_exist(self):
        for fname in ("ui_minimal.qss", "ui_cream.qss", "ui_whale.qss"):
            assert (ROOT / "gui" / "themes" / fname).exists(), fname

    @pytest.mark.parametrize("tid", ["ui_minimal", "ui_cream", "ui_whale"])
    def test_no_leftover_tokens(self, monkeypatch, tmp_path, tid):
        qss = self._load(monkeypatch, tmp_path, tid)
        leftovers = sorted(set(re.findall(r"\$\{[A-Za-z0-9_]+\}", qss)))
        assert leftovers == [], tid

    @pytest.mark.parametrize("tid", ["ui_minimal", "ui_cream", "ui_whale"])
    def test_qss_substantial(self, monkeypatch, tmp_path, tid):
        qss = self._load(monkeypatch, tmp_path, tid)
        assert len(qss) > 4000

    def test_whale_has_gradient(self, monkeypatch, tmp_path):
        qss = self._load(monkeypatch, tmp_path, "ui_whale")
        assert "qlineargradient" in qss

    def test_whale_gradient_absent_in_minimal(self, monkeypatch, tmp_path):
        qss = self._load(monkeypatch, tmp_path, "ui_minimal")
        assert "qlineargradient" not in qss

    def test_theme_skin_changes_tokens(self, monkeypatch, tmp_path):
        # 同一选择器的取值随风格变化（验证肤感层真正生效，非共用文件）
        qa = self._load(monkeypatch, tmp_path, "ui_minimal")
        qb = self._load(monkeypatch, tmp_path, "ui_whale")
        assert qa != qb


# ---------------------------------------------------------------------------
# ⑤ is_dark_effective（D-V19-13 / ⚠-3）
# ---------------------------------------------------------------------------
class TestIsDarkEffective:
    def test_light_default(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_theme_mode("light")
        assert eng.is_dark_effective() is False

    def test_dark_mode(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_theme_mode("dark")
        assert eng.is_dark_effective() is True

    def test_page_editor_uses_engine(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        from gui.pages.page_editor import CodeHighlighter
        from gui.theme_engine import ThemeEngine as TE
        from PySide6.QtGui import QTextDocument
        eng = TE()
        eng.set_theme_mode("dark")
        doc = QTextDocument()          # 保持存活：highlighter 依附文档
        h = CodeHighlighter(doc, eng)
        assert h._is_dark is True
        eng.set_theme_mode("light")
        eng.load_theme("ui_minimal")   # 触发 theme_changed
        assert h._is_dark is False

    def test_page_editor_no_engine_conservative(self):
        _qapp()
        from gui.pages.page_editor import CodeHighlighter
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        h = CodeHighlighter(doc, None)
        assert h._is_dark is True     # 引擎缺失时保守深色


# ---------------------------------------------------------------------------
# ⑥ C 深色夜间进出收口（D-V19-11 / Q-E2）
# ---------------------------------------------------------------------------
class _Cfg:
    def __init__(self):
        self.theme_mode = "light"
        self.theme_mode_before_night = ""
        self.theme_name = "ui_minimal"
        self.font_family = "resource_rounded"
        self.custom_accent = ""


class TestNightLock:
    def test_enter_night_forces_dark(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        cfg = _Cfg()
        locked = apply_night_lock(eng, cfg, "ui_night")
        assert locked is True
        assert cfg.theme_mode == "dark"
        assert cfg.theme_mode_before_night == "light"
        eng.load_theme("ui_night")
        assert eng.is_dark_effective() is True

    def test_leave_night_restores(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        cfg = _Cfg()
        apply_night_lock(eng, cfg, "ui_night")
        locked = apply_night_lock(eng, cfg, "ui_cream")
        assert locked is False
        assert cfg.theme_mode == "light"
        assert cfg.theme_mode_before_night == ""

    def test_restore_system_mode(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        cfg = _Cfg()
        cfg.theme_mode = "system"
        apply_night_lock(eng, cfg, "ui_night")
        assert cfg.theme_mode_before_night == "system"
        apply_night_lock(eng, cfg, "ui_minimal")
        assert cfg.theme_mode == "system"

    def test_reenter_does_not_lose_original(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        cfg = _Cfg()          # 原 light
        apply_night_lock(eng, cfg, "ui_night")
        apply_night_lock(eng, cfg, "ui_night")   # 重进不应把 before 覆盖为 dark
        assert cfg.theme_mode_before_night == "light"
        apply_night_lock(eng, cfg, "ui_cream")
        assert cfg.theme_mode == "light"

    def test_non_night_noop_when_no_pending(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        cfg = _Cfg()
        apply_night_lock(eng, cfg, "ui_whale")
        assert cfg.theme_mode == "light"
        assert cfg.theme_mode_before_night == ""


# ---------------------------------------------------------------------------
# ⑦ GuiConfig 默认 + 持久化
# ---------------------------------------------------------------------------
class TestConfigDefaults:
    def test_default_theme_is_minimal(self):
        from gui.config import GuiConfig
        assert GuiConfig().theme_name == "ui_minimal"

    def test_default_theme_mode_before_night_empty(self):
        from gui.config import GuiConfig
        assert GuiConfig().theme_mode_before_night == ""

    def test_round_trip_before_night(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        from gui.config import GuiConfig
        cfg = GuiConfig()
        cfg.theme_name = "ui_night"
        cfg.theme_mode_before_night = "system"
        cfg.save()
        text = (tmp_path / "gui_config.json").read_text(encoding="utf-8")
        assert "theme_mode_before_night" in text
        assert GuiConfig.load().theme_mode_before_night == "system"


# ---------------------------------------------------------------------------
# ⑧ 切换器三处落点 + _switch_theme 补 save
# ---------------------------------------------------------------------------
class TestSwitcherWiring:
    def _read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_settings_has_four_style_selector(self):
        src = self._read("gui/pages/page_settings.py")
        assert "界面风格" in src
        assert "ThemeEngine.THEME_IDS" in src
        assert "_style_swatches" in src

    def test_settings_switch_theme_saves(self):
        src = self._read("gui/pages/page_settings.py")
        # _switch_theme 内应落 save（⚠-5 补缺口）
        seg = src.split("def _switch_theme", 1)[1].split("def ", 1)[0]
        assert "config.save()" in seg
        assert "apply_night_lock" in seg

    def test_chat_panel_style_entry(self):
        src = self._read("gui/widgets/chat_panel.py")
        assert "styleSwitchBtn" in src
        assert "_on_style_menu" in src
        assert "_apply_style_choice" in src

    def test_onboarding_four_styles(self):
        src = self._read("gui/pages/onboarding.py")
        assert "ThemeEngine.THEME_IDS" in src
        assert '"ui_minimal"' in src

    def test_main_window_four_labels(self):
        src = self._read("gui/main_window.py")
        for name in ("现代极简", "温暖奶油", "深色夜间", "鲸鱼娘深海"):
            assert name in src

    def test_no_user_visible_legacy_ids(self):
        # 设置页/onboarding 不得再把 cute/minimal/maid 当可见选项
        for rel in ("gui/pages/page_settings.py", "gui/pages/onboarding.py"):
            src = self._read(rel)
            assert 'addItem("活泼可爱风"' not in src
            assert '_select_theme("cute")' not in src
            assert 'self._switch_theme("cute")' not in src


# ---------------------------------------------------------------------------
# ⑨ 小轮 2 · V19-15：ui_night.qss 肤感层 + 深色渲染
# ---------------------------------------------------------------------------
class TestUiNightQss:
    def test_file_exists(self):
        assert (ROOT / "gui" / "themes" / "ui_night.qss").exists()

    def test_all_tokens_registered(self):
        """ui_night.qss 引用的 token 必须已在条目 colors/layout 注册（零裸 token）。"""
        entry = ThemeEngine.THEME_DEFINITIONS["ui_night"]
        registered = set(entry["colors"].keys()) | set(entry["layout"].keys())
        # 引擎替换链额外提供（字体位）
        extra = {"font_family", "font_title"}
        txt = (ROOT / "gui" / "themes" / "ui_night.qss").read_text(encoding="utf-8")
        used = {m for m in re.findall(r"\$\{([A-Za-z0-9_]+)\}", txt)}
        missing = sorted(used - registered - extra)
        assert missing == [], missing

    def test_loads_without_leftover(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        assert eng.load_theme("ui_night") is True
        qss = QApplication.instance().styleSheet()
        leftovers = sorted(set(re.findall(r"\$\{[A-Za-z0-9_]+\}", qss)))
        assert leftovers == []
        assert len(qss) > 4000

    def test_night_renders_dark_tones(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        eng.load_theme("ui_night")
        qss = QApplication.instance().styleSheet()
        # 深底值应出现在合成样式表（QSS 里大小写不敏感，统一小写比对）
        assert "#131114" in qss.lower()      # bg
        assert "qlineargradient" not in qss   # C 风格无 D 专属渐变

    def test_no_new_image_asset(self):
        # R-L/Non-goals：C 风格 QSS 不得引用新图片资产（无 url(...) 资源）
        txt = (ROOT / "gui" / "themes" / "ui_night.qss").read_text(encoding="utf-8")
        assert "url(" not in txt

    def test_qt_parse_no_warnings(self, monkeypatch, tmp_path):
        """四风格 QSS 经 Qt 解析无语法警告（自测要点：QSS 语法自检）。"""
        from PySide6.QtCore import qInstallMessageHandler
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        eng.set_custom_accent("")
        captured = []

        def _handler(mode, ctx, msg):
            if ("Could not parse" in msg) or ("Unknown property" in msg) or ("does not exist" in msg):
                captured.append(msg)

        prev = qInstallMessageHandler(_handler)
        try:
            for tid in ThemeEngine.THEME_IDS:
                eng.load_theme(tid)
                QApplication.instance().processEvents()
        finally:
            qInstallMessageHandler(prev)
        assert captured == [], captured


# ---------------------------------------------------------------------------
# ⑩ 小轮 2 · V19-16：D 风格文案随人设（brand_persona_self）
# ---------------------------------------------------------------------------
class TestBrandPersonaSelf:
    def _inject_role(self, monkeypatch, tmp_path, given="小鲸"):
        import gui.pages.page_role as page_role
        rm = page_role.RoleManager(roles_dir=Path(tmp_path))
        role = rm.create_role("温柔女仆", "desc")
        role.given_name = given
        rm.save_role(role)
        rm.set_default(role.id)
        monkeypatch.setattr(page_role, "RoleManager", lambda *a, **k: rm)
        return rm, role

    def _ctx(self, eng):
        class _Ctx:
            pass
        c = _Ctx()
        c.theme_engine = eng
        return c

    def test_d_style_uses_given_name(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        self._inject_role(monkeypatch, tmp_path, "小鲸")
        from gui.utils import brand_persona_self
        eng.load_theme("ui_whale")
        assert brand_persona_self(self._ctx(eng)) == "小鲸"

    def test_d_style_empty_name_falls_back(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        self._inject_role(monkeypatch, tmp_path, "")
        from gui.utils import brand_persona_self
        eng.load_theme("ui_whale")
        assert brand_persona_self(self._ctx(eng)) == "我"

    @pytest.mark.parametrize("tid", ["ui_minimal", "ui_cream", "ui_night"])
    def test_non_d_style_returns_none(self, monkeypatch, tmp_path, tid):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        self._inject_role(monkeypatch, tmp_path, "小鲸")
        from gui.utils import brand_persona_self
        eng.load_theme(tid)
        assert brand_persona_self(self._ctx(eng)) is None

    def test_no_engine_returns_none(self):
        from gui.utils import brand_persona_self

        class _Ctx:
            pass
        assert brand_persona_self(_Ctx()) is None

    def test_persona_label_never_used_as_self(self, monkeypatch, tmp_path):
        # given_name 为空且角色标签为「温柔女仆」→ 自称必须是「我」，绝不回落到人设标签
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        eng = ThemeEngine()
        self._inject_role(monkeypatch, tmp_path, "")   # name="温柔女仆"
        from gui.utils import brand_persona_self
        eng.load_theme("ui_whale")
        assert brand_persona_self(self._ctx(eng)) == "我"


# ---------------------------------------------------------------------------
# ⑪ 小轮 2 · V19-16：文案点接线（page_home / screen_watch_bar）
# ---------------------------------------------------------------------------
class TestBrandTextWiring:
    def _read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_page_home_wired(self):
        src = self._read("gui/pages/page_home.py")
        assert "brand_persona_self" in src
        assert "_refresh_welcome_label" in src
        assert "_set_greeting_fallback" in src
        assert "_connect_theme_brand" in src

    def test_screen_watch_bar_wired(self):
        src = self._read("gui/widgets/screen_watch_bar.py")
        assert "brand_persona_self" in src

    def test_product_identity_unchanged(self):
        # D-V19-14 边界：产品标识「码铃」永不随人设变
        for rel in ("gui/pages/page_home.py", "gui/widgets/screen_watch_bar.py",
                    "gui/utils.py"):
            src = self._read(rel)
            assert "码铃" in src

    def test_screen_watch_chip_persona_text(self, monkeypatch, tmp_path):
        _qapp()
        _isolate_config(monkeypatch, tmp_path)
        import gui.pages.page_role as page_role
        rm = page_role.RoleManager(roles_dir=Path(tmp_path))
        role = rm.create_role("猫娘", "desc")
        role.given_name = "小咪"
        rm.save_role(role)
        rm.set_default(role.id)
        monkeypatch.setattr(page_role, "RoleManager", lambda *a, **k: rm)

        eng = ThemeEngine()
        eng.set_custom_accent("")

        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.theme_engine = eng

        from gui.widgets.screen_watch_bar import ScreenWatchBar, STATE_RUNNING
        bar = ScreenWatchBar(ctx)
        bar.set_state(STATE_RUNNING)
        bar.set_stats(3, 100)

        eng.load_theme("ui_whale")
        bar._on_theme_changed()
        assert "小咪在看" in bar._status.text()

        eng.load_theme("ui_minimal")
        bar._on_theme_changed()
        assert "码铃在看" in bar._status.text()

