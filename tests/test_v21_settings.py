# -*- coding: utf-8 -*-
"""v2.1 域4（V21-05 / V21-06 / V21-07）测试。

覆盖：
  ① GuiConfig 6 个新键默认值（D-V21-10 / §4.1）；
  ② 旧存档（缺新键）加载 → 走类默认（零迁移；既有键零改动）；
  ③ 非法 animation_level → standard（读时归一）；
  ④ save → reload 保持；
  ⑤ 省电模式：开 → animation_level=off + glass_enabled=False 且快照正确；
     关 → 从快照恢复；
  ⑥ 设置页「外观与效果」区可见性 / 控件存在 / 分区标题改名（C-1/C-4）；
  ⑦ R-A 文案扫描（新设置项无数值化 / 催促语义）；
  ⑧ V21-07：系统深浅实时性（30s 回落轮询 + 原生事件监听装卸 + 去抖转调
     _poll_system_mode）；既有关闭契约回归（light/dark/system/ui_night 锁定）。

隔离：Qt offscreen；GuiConfig 落盘走 tmp_path（monkeypatch get_user_data_dir）；
更新区状态读取 monkeypatch（零真实文件依赖）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ctypes
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from gui.config import ANIMATION_LEVELS, GuiConfig  # noqa: E402
from gui.qt_compat import QApplication  # noqa: E402
from gui.theme_engine import (  # noqa: E402
    ThemeEngine, apply_night_lock, _SystemThemeEventFilter, _native_msg_id,
    _relative_luminance,
)

_NEW_KEYS = (
    "animation_level",
    "glass_enabled",
    "glass_popups_enabled",
    "power_save_mode",
    "animation_level_pre_power_save",
    "glass_enabled_pre_power_save",
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _isolate_config(monkeypatch, tmp_path):
    """把 GuiConfig 落盘目录指到 tmp_path，避免污染真实用户配置。"""
    import gui.config as config_mod
    monkeypatch.setattr(config_mod, "get_user_data_dir", lambda: tmp_path)


def _patch_update_state(monkeypatch):
    """更新区状态读取走空状态（零真实文件依赖）。"""
    monkeypatch.setattr("gui.update_checker.load_update_state", lambda: {})


def _make_page(monkeypatch, tmp_path, cfg=None):
    _isolate_config(monkeypatch, tmp_path)
    _patch_update_state(monkeypatch)
    from gui.pages.page_settings import PageSettings
    config = cfg if cfg is not None else GuiConfig()
    page = PageSettings(SimpleNamespace(config=config, cfg=None))
    return page, config


# ===========================================================================
# ① 6 个新键默认值
# ===========================================================================
class TestNewKeyDefaults:
    def test_animation_level_default(self):
        assert GuiConfig().animation_level == "standard"

    def test_glass_enabled_default(self):
        assert GuiConfig().glass_enabled is True

    def test_glass_popups_enabled_default(self):
        assert GuiConfig().glass_popups_enabled is True

    def test_power_save_mode_default(self):
        assert GuiConfig().power_save_mode is False

    def test_pre_power_save_snapshot_defaults(self):
        cfg = GuiConfig()
        assert cfg.animation_level_pre_power_save == "standard"
        assert cfg.glass_enabled_pre_power_save is True

    def test_animation_levels_value_domain(self):
        assert set(ANIMATION_LEVELS) == {"off", "soft", "standard"}


# ===========================================================================
# ② 旧存档缺键 → 类默认（零迁移）；既有键零改动
# ===========================================================================
class TestZeroMigration:
    def test_missing_new_keys_use_class_defaults(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        legacy = {
            "theme_name": "ui_cream",
            "font_size": 15,
            "window_opacity": 0.9,
            "theme_mode": "dark",
            "custom_accent": "#123456",
        }
        (tmp_path / "gui_config.json").write_text(
            json.dumps(legacy), encoding="utf-8")
        cfg = GuiConfig.load()
        # 既有键照旧读入
        assert cfg.theme_name == "ui_cream"
        assert cfg.font_size == 15
        assert abs(cfg.window_opacity - 0.9) < 1e-9
        assert cfg.theme_mode == "dark"
        assert cfg.custom_accent == "#123456"
        # 新键走类默认
        assert cfg.animation_level == "standard"
        assert cfg.glass_enabled is True
        assert cfg.glass_popups_enabled is True
        assert cfg.power_save_mode is False
        assert cfg.animation_level_pre_power_save == "standard"
        assert cfg.glass_enabled_pre_power_save is True

    def test_no_config_file_uses_defaults(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        cfg = GuiConfig.load()
        for key in _NEW_KEYS:
            assert getattr(cfg, key) == getattr(GuiConfig(), key)


# ===========================================================================
# ③ 非法 animation_level → standard
# ===========================================================================
class TestAnimationLevelNormalization:
    def test_illegal_value_normalized_on_load(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        (tmp_path / "gui_config.json").write_text(
            json.dumps({"animation_level": "hyper"}), encoding="utf-8")
        assert GuiConfig.load().animation_level == "standard"

    @pytest.mark.parametrize("lvl", ["off", "soft", "standard"])
    def test_legal_values_preserved(self, monkeypatch, tmp_path, lvl):
        _isolate_config(monkeypatch, tmp_path)
        (tmp_path / "gui_config.json").write_text(
            json.dumps({"animation_level": lvl}), encoding="utf-8")
        assert GuiConfig.load().animation_level == lvl

    def test_illegal_value_from_non_string(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        (tmp_path / "gui_config.json").write_text(
            json.dumps({"animation_level": 7}), encoding="utf-8")
        assert GuiConfig.load().animation_level == "standard"


# ===========================================================================
# ④ save → reload 保持
# ===========================================================================
class TestSaveReload:
    def test_roundtrip_all_new_keys(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        cfg = GuiConfig()
        cfg.animation_level = "soft"
        cfg.glass_enabled = False
        cfg.glass_popups_enabled = False
        cfg.power_save_mode = True
        cfg.animation_level_pre_power_save = "soft"
        cfg.glass_enabled_pre_power_save = False
        cfg.save()
        back = GuiConfig.load()
        assert back.animation_level == "soft"
        assert back.glass_enabled is False
        assert back.glass_popups_enabled is False
        assert back.power_save_mode is True
        assert back.animation_level_pre_power_save == "soft"
        assert back.glass_enabled_pre_power_save is False

    def test_save_writes_all_new_keys(self, monkeypatch, tmp_path):
        _isolate_config(monkeypatch, tmp_path)
        GuiConfig().save()
        data = json.loads((tmp_path / "gui_config.json").read_text(encoding="utf-8"))
        for key in _NEW_KEYS:
            assert key in data, key


# ===========================================================================
# ⑤ 省电模式（开 → 两项置关 + 快照；关 → 快照恢复）
# ===========================================================================
class TestPowerSaveMode:
    def test_on_disables_and_snapshots(self, monkeypatch, tmp_path, qapp):
        cfg = GuiConfig()
        cfg.animation_level = "soft"
        cfg.glass_enabled = True
        page, cfg = _make_page(monkeypatch, tmp_path, cfg)
        assert page.power_save_check.isChecked() is False

        page.power_save_check.setChecked(True)  # 触发即时生效

        assert cfg.power_save_mode is True
        assert cfg.animation_level == "off"
        assert cfg.glass_enabled is False
        assert cfg.animation_level_pre_power_save == "soft"
        assert cfg.glass_enabled_pre_power_save is True
        # UI 回显两键
        assert page.animation_combo.currentData() == "off"
        assert page.glass_check.isChecked() is False

    def test_off_restores_from_snapshot(self, monkeypatch, tmp_path, qapp):
        cfg = GuiConfig()
        cfg.animation_level = "soft"
        cfg.glass_enabled = True
        page, cfg = _make_page(monkeypatch, tmp_path, cfg)

        page.power_save_check.setChecked(True)
        page.power_save_check.setChecked(False)

        assert cfg.power_save_mode is False
        assert cfg.animation_level == "soft"
        assert cfg.glass_enabled is True
        assert page.animation_combo.currentData() == "soft"
        assert page.glass_check.isChecked() is True

    def test_persisted_after_toggle(self, monkeypatch, tmp_path, qapp):
        page, cfg = _make_page(monkeypatch, tmp_path)
        page.power_save_check.setChecked(True)
        back = GuiConfig.load()
        assert back.power_save_mode is True
        assert back.animation_level == "off"
        assert back.glass_enabled is False


# ===========================================================================
# ⑥ 设置页「外观与效果」区：分区标题 / 控件 / 文案存在
# ===========================================================================
class TestSettingsPageControls:
    def test_section_renamed(self, monkeypatch, tmp_path, qapp):
        from gui.qt_compat import QLabel
        page, _ = _make_page(monkeypatch, tmp_path)
        texts = [lbl.text() for lbl in page.findChildren(QLabel)]
        assert "外观与效果" in texts
        assert "外观主题" not in texts

    def test_effect_controls_exist_and_visible(self, monkeypatch, tmp_path, qapp):
        page, _ = _make_page(monkeypatch, tmp_path)
        for attr in ("animation_combo", "glass_check", "glass_popups_check",
                     "power_save_check", "opacity_slider"):
            widget = getattr(page, attr)
            assert widget is not None, attr
            assert widget.isHidden() is False, attr

    def test_animation_combo_three_levels(self, monkeypatch, tmp_path, qapp):
        page, _ = _make_page(monkeypatch, tmp_path)
        items = [page.animation_combo.itemData(i)
                 for i in range(page.animation_combo.count())]
        assert items == ["off", "soft", "standard"]

    def test_hint_labels_present(self, monkeypatch, tmp_path, qapp):
        page, _ = _make_page(monkeypatch, tmp_path)
        for attr in ("_animation_hint", "_glass_hint", "_power_save_hint",
                     "_opacity_glass_hint"):
            lbl = getattr(page, attr)
            assert lbl.text().strip(), attr

    def test_glass_hint_states_win10_degrade(self, monkeypatch, tmp_path, qapp):
        """毛玻璃须如实说明仅 Win11 生效、Win10 自动降级纯色（R-R 诚实）。"""
        page, _ = _make_page(monkeypatch, tmp_path)
        text = page._glass_hint.text()
        assert "Windows 11" in text
        assert "Windows 10" in text
        assert "纯色" in text


# ===========================================================================
# ⑦ R-A 文案扫描（新设置项无数值化 / 催促语义）
# ===========================================================================
_RA_BANNED = (
    "心情", "好感", "等级", "token", "Token", "TOKEN", "进度", "断签",
    "倒数", "评分", "落后", "卡顿", "还剩", "剩余", "欠费", "催",
)


def _new_section_texts(page):
    out = []
    for i in range(page.animation_combo.count()):
        out.append(page.animation_combo.itemText(i))
    out.append(page.glass_check.text())
    out.append(page.glass_popups_check.text())
    out.append(page.power_save_check.text())
    for attr in ("_animation_hint", "_glass_hint", "_power_save_hint",
                 "_opacity_glass_hint"):
        out.append(getattr(page, attr).text())
    return out


class TestRATextScan:
    def test_no_numeric_anxiety_words(self, monkeypatch, tmp_path, qapp):
        page, _ = _make_page(monkeypatch, tmp_path)
        for text in _new_section_texts(page):
            for bad in _RA_BANNED:
                assert bad not in text, (bad, text)


# ===========================================================================
# 设置页即时生效路径（写 cfg + save + 回调）
# ===========================================================================
class TestImmediateEffect:
    def test_animation_level_writes_config_and_triggers_motion(
            self, monkeypatch, tmp_path, qapp):
        page, cfg = _make_page(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(page, "_apply_motion_level", lambda lvl: calls.append(lvl))
        idx = page.animation_combo.findData("soft")
        page.animation_combo.setCurrentIndex(idx)
        assert cfg.animation_level == "soft"
        assert calls == ["soft"]
        assert GuiConfig.load().animation_level == "soft"

    def test_glass_toggle_writes_config(self, monkeypatch, tmp_path, qapp):
        page, cfg = _make_page(monkeypatch, tmp_path)
        page.glass_check.setChecked(False)
        assert cfg.glass_enabled is False
        assert GuiConfig.load().glass_enabled is False

    def test_glass_popups_toggle_writes_config(self, monkeypatch, tmp_path, qapp):
        page, cfg = _make_page(monkeypatch, tmp_path)
        page.glass_popups_check.setChecked(False)
        assert cfg.glass_popups_enabled is False
        assert GuiConfig.load().glass_popups_enabled is False


# ===========================================================================
# 透明度滑杆互斥联动（Q-V8 / D-V21-05）
# ===========================================================================
class TestOpacityGlassLinkage:
    def test_glass_on_supported_locks_slider(self, monkeypatch, tmp_path, qapp):
        import gui.glass as glass_mod
        monkeypatch.setattr(glass_mod, "is_supported", lambda: True)
        cfg = GuiConfig()
        cfg.glass_enabled = True
        page, _ = _make_page(monkeypatch, tmp_path, cfg)
        assert page.opacity_slider.isEnabled() is False
        assert page._opacity_glass_hint.isHidden() is False

    def test_glass_off_enables_slider(self, monkeypatch, tmp_path, qapp):
        import gui.glass as glass_mod
        monkeypatch.setattr(glass_mod, "is_supported", lambda: True)
        cfg = GuiConfig()
        cfg.glass_enabled = False
        page, _ = _make_page(monkeypatch, tmp_path, cfg)
        assert page.opacity_slider.isEnabled() is True
        assert page._opacity_glass_hint.isHidden() is True

    def test_glass_on_unsupported_keeps_slider_enabled(self, monkeypatch, tmp_path, qapp):
        import gui.glass as glass_mod
        monkeypatch.setattr(glass_mod, "is_supported", lambda: False)
        cfg = GuiConfig()
        cfg.glass_enabled = True
        page, _ = _make_page(monkeypatch, tmp_path, cfg)
        assert page.opacity_slider.isEnabled() is True
        assert page._opacity_glass_hint.isHidden() is True

    def test_toggle_glass_updates_linkage(self, monkeypatch, tmp_path, qapp):
        import gui.glass as glass_mod
        monkeypatch.setattr(glass_mod, "is_supported", lambda: True)
        cfg = GuiConfig()
        cfg.glass_enabled = False
        page, _ = _make_page(monkeypatch, tmp_path, cfg)
        assert page.opacity_slider.isEnabled() is True
        page.glass_check.setChecked(True)
        assert page.opacity_slider.isEnabled() is False


# ===========================================================================
# ⑧ V21-07：系统深浅实时性
# ===========================================================================
class _MSG_HEAD(ctypes.Structure):
    """伪 MSG 头（仅需 hwnd + message 两字段，用于断言消息号解析）。"""
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint)]


def _fake_msg(message_id: int) -> "_MSG_HEAD":
    """构造伪 MSG（调用方需持有返回值，保持内存有效）。"""
    msg = _MSG_HEAD()
    msg.hwnd = 0
    msg.message = message_id
    return msg


class TestNativeMsgParse:
    def test_reads_watched_ids(self):
        for mid in (0x001A, 0x031A, 0x0320):
            msg = _fake_msg(mid)
            assert _native_msg_id(ctypes.addressof(msg)) == mid

    def test_unwatched_and_invalid(self):
        msg = _fake_msg(0x0113)
        assert _native_msg_id(ctypes.addressof(msg)) == 0x0113  # WM_TIMER（非主题）
        assert _native_msg_id(0) == 0
        assert _native_msg_id(None) == 0


class TestSystemDarkRealtime:
    def test_poll_interval_shrunk_to_30s(self, qapp):
        eng = ThemeEngine()
        try:
            eng.set_theme_mode("system")
            assert eng._system_poll is not None
            assert eng._system_poll.interval() == 30 * 1000
        finally:
            eng.set_theme_mode("light")

    def test_listener_installed_only_in_system(self, qapp):
        eng = ThemeEngine()
        eng.set_theme_mode("system")
        assert eng._native_filter is not None
        eng.set_theme_mode("dark")
        assert eng._native_filter is None
        assert eng._system_poll is None
        eng.set_theme_mode("light")
        assert eng._native_filter is None

    def test_native_filter_dispatches_watched_message(self, qapp):
        eng = ThemeEngine()
        eng.set_theme_mode("system")
        try:
            flt = _SystemThemeEventFilter(eng)
            got = []
            eng._on_system_theme_message = lambda: got.append(1)
            m1 = _fake_msg(0x001A)
            # 命中主题消息 → 触发
            flt.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(m1))
            assert got == [1]
            # 非主题消息 → 不触发
            m2 = _fake_msg(0x0113)
            flt.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(m2))
            assert got == [1]
        finally:
            eng.set_theme_mode("light")

    def test_debounce_coalesces_multiple_messages(self, qapp, monkeypatch):
        """多次消息复用同一去抖定时器（合并为一次），timeout 即转调 _poll_system_mode。

        直接校验定时器状态 + 手动 emit timeout：不依赖真实事件循环（规避慢机下
        QTimer 投递不稳定的 flaky，且不对全局事件循环产生副作用）。
        """
        eng = ThemeEngine()
        eng.set_theme_mode("system")
        try:
            calls = []
            monkeypatch.setattr(eng, "_poll_system_mode", lambda: calls.append(1))
            for _ in range(3):
                eng._on_system_theme_message()
            timer = eng._theme_debounce
            assert timer is not None
            assert timer.isSingleShot() is True
            assert timer.isActive() is True
            # 三次消息只产生一个（被重启的）定时器 → 合并
            timer.timeout.emit()
            assert calls == [1]
        finally:
            eng.set_theme_mode("light")

    def test_light_dark_do_not_poll_or_listen(self, qapp):
        eng = ThemeEngine()
        eng.set_theme_mode("dark")
        assert eng._system_poll is None
        assert eng._native_filter is None
        eng.set_theme_mode("light")
        assert eng._system_poll is None
        assert eng._native_filter is None


# ===========================================================================
# R-D 契约回归：theme_engine 既有符号签名 / 语义零变更
# ===========================================================================
class TestThemeEngineContract:
    def test_method_signatures_unchanged(self):
        expected = {
            "load_theme": ["self", "theme_name"],
            "set_theme_mode": ["self", "mode"],
            "is_dark_effective": ["self"],
            "get_color": ["self", "color_key", "fallback"],
            "get_layout_token": ["self", "key", "fallback"],
            "current_theme_name": ["self"],
            "_active_palette": ["self", "theme_def", "theme_name"],
            "mode": ["self"],
        }
        for name, params in expected.items():
            got = list(inspect.signature(getattr(ThemeEngine, name)).parameters)
            assert got == params, (name, got)

    def test_module_level_signatures_unchanged(self):
        assert list(inspect.signature(
            __import__("gui.theme_engine", fromlist=["derive_accent_palette"])
            .derive_accent_palette).parameters) == ["accent_hex", "theme_name", "mode"]
        assert list(inspect.signature(apply_night_lock).parameters) == [
            "engine", "cfg", "theme_name"]

    def test_theme_changed_signal_single_str(self):
        # 信号仍存在且为单参（消费侧订阅依赖）
        assert hasattr(ThemeEngine, "theme_changed")

    def test_light_dark_semantics_unchanged(self, qapp):
        eng = ThemeEngine()
        eng.load_theme("ui_minimal")
        assert eng.set_theme_mode("dark") is True
        assert eng.mode() == "dark"
        assert eng.is_dark_effective() is True
        assert eng.set_theme_mode("light") is True
        assert eng.is_dark_effective() is False

    def test_ui_night_lock_unchanged(self, qapp):
        cfg = GuiConfig()
        eng = ThemeEngine()
        locked = apply_night_lock(eng, cfg, "ui_night")
        assert locked is True
        assert cfg.theme_mode == "dark"
        assert cfg.theme_mode_before_night == "light"
        # 离开 C 风格 → 恢复原模式并清空暂存
        assert apply_night_lock(eng, cfg, "ui_minimal") is False
        assert cfg.theme_mode == "light"
        assert cfg.theme_mode_before_night == ""

    def test_night_locked_theme_regression(self, qapp):
        """ui_night 强制深色（dark_locked）不受实时性改造影响。"""
        assert ThemeEngine.is_dark_locked("ui_night") is True
        assert ThemeEngine.is_dark_locked("ui_minimal") is False


# ===========================================================================
# 域4 后续（D-V21-16）：补齐 info / warning 语义色键
# ===========================================================================
_UI_THEMES = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class TestSemanticInfoWarning:
    def test_keys_registered_all_themes(self):
        for tid in _UI_THEMES:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            for key in ("info", "warning"):
                assert key in td["colors"], (tid, key)
                assert key in td["colors_dark"], (tid, key, "dark")

    def test_colors_dark_key_alignment_preserved(self):
        for tid in _UI_THEMES:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            assert set(td["colors"].keys()) == set(td["colors_dark"].keys()), tid

    def test_contrast_ge_3_to_1_all_8_combos(self):
        eng = ThemeEngine()
        for tid in _UI_THEMES:
            for mode in ("light", "dark"):
                eng._dark = (mode == "dark")
                pal = eng._active_palette(ThemeEngine.THEME_DEFINITIONS[tid], tid)
                for key in ("info", "warning"):
                    val = pal[key]
                    assert _contrast(val, pal["bg"]) >= 3.0, (tid, mode, key, "bg")
                    assert _contrast(val, pal["bg_card"]) >= 3.0, (tid, mode, key, "card")

    def test_light_not_lighter_than_text_secondary(self):
        """浅色风格下 info/warning 不得比 text_secondary 更浅（ui_night 为 dark_locked 深色主题，不适用）。"""
        eng = ThemeEngine()
        eng._dark = False
        for tid in ("ui_minimal", "ui_cream", "ui_whale"):
            pal = eng._active_palette(ThemeEngine.THEME_DEFINITIONS[tid], tid)
            ts = _relative_luminance(pal["text_secondary"])
            for key in ("info", "warning"):
                assert _relative_luminance(pal[key]) <= ts, (tid, key)

    def test_in_token_replacement_table(self):
        """info/warning 进入活动色板 → load_theme 的 ${...} 替换集合（QSS 可引用）。"""
        eng = ThemeEngine()
        eng._dark = False
        pal = eng._active_palette(ThemeEngine.THEME_DEFINITIONS["ui_minimal"], "ui_minimal")
        assert "info" in pal and "warning" in pal

    def test_load_theme_no_real_token_residue(self, qapp):
        """四风格 × 浅/深 各加载一次：返回 True，且残留的 ${ 全部是表头注释字面 ${...}。"""
        eng = ThemeEngine()
        for tid in _UI_THEMES:
            for mode in ("light", "dark"):
                eng.set_theme_mode(mode)
                assert eng.load_theme(tid) is True
                qss = QApplication.instance().styleSheet()
                assert qss.count("${") == qss.count("${...}"), (tid, mode)

    def test_text_hint_and_secondary_contrast(self):
        """小字可读性下限（替代原 test_existing_keys_untouched 的写死色值断言）。

        原断言写死 text_hint 色值，属 v2.1「只加键、不改既有键」时期的守卫；
        在本轮用户授权的可读性修复后已过期，且写死色值会导致以后每次调色都误报。
        改为守护真正重要的属性：hint ≥3.0（辅助文字）、secondary ≥4.0（次要正文），
        且 secondary 明显深于 hint（拉开 >0.5）以保住视觉层次。

        范围限定 _UI_THEMES（四风格）：cute/minimal/maid 为旧配置兼容主题（R-D），
        UI 不暴露、不在本轮可读性修复授权范围内，其旧 hint 约 2.0-2.2 未达标，
        纳入会让本断言失效；故按其「非用户可见」定位排除。
        """
        for tid in _UI_THEMES:
            colors = ThemeEngine.THEME_DEFINITIONS[tid]["colors"]
            bg = colors["bg"]
            ch = _contrast(colors["text_hint"], bg)
            cs = _contrast(colors["text_secondary"], bg)
            assert ch >= 3.0, (tid, "text_hint", colors["text_hint"], round(ch, 3))
            assert cs >= 4.0, (tid, "text_secondary", colors["text_secondary"], round(cs, 3))
            assert cs > ch + 0.5, (tid, "层次", round(cs, 3), round(ch, 3))

    def test_accent_text_contrast_ge_4_5_light_and_dark(self):
        """accent_text（「文字用」强调色）在浅/深底上都须满足小字 AA（≥4.5）。

        primary 是「填充用」色（大面积按钮底，配深字），为求「淡/柔」在浅底上仅约 3.05，
        达不到 12px 小字的 AA 门槛；两者用途相反、不能共用一个值（一色两用会顾此失彼：
        #B45073 当文字 4.52 达标，但当填充配深字只有 3.51）。故独立出 accent_text
        专供「浅底/深底上的小字」。属性化断言，不写死色值。
        """
        for tid in _UI_THEMES:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            for mode, key in (("light", "colors"), ("dark", "colors_dark")):
                pal = td[key]
                assert "accent_text" in pal, (tid, mode)
                c = _contrast(pal["accent_text"], pal["bg"])
                assert c >= 4.5, (tid, mode, pal["accent_text"], round(c, 3))

    def test_distinct_from_state_warn(self):
        """warning 与 state_warn 为邻近但独立键（不重复定义同一语义）。"""
        for tid in _UI_THEMES:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            assert "state_warn" in td["colors"]
            assert td["colors"]["warning"] != td["colors"]["state_warn"], tid


# ===========================================================================
# 域4 后续2（D-V21-17）：补齐 state_danger 语义色键（危险/破坏性操作）
# ===========================================================================
class TestSemanticStateDanger:
    def test_state_danger_declared_all_palettes(self):
        """四套新风格 × 明暗每个色板都须声明 state_danger（含旧三主题一并覆盖）。"""
        for tid in ThemeEngine.THEME_DEFINITIONS:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            assert "state_danger" in td["colors"], (tid, "light")
            assert "state_danger" in td["colors_dark"], (tid, "dark")

    def test_state_danger_distinct_from_state_warn(self):
        """危险色不得与警示色同值（否则不可区分）。"""
        for tid in ThemeEngine.THEME_DEFINITIONS:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            assert td["colors"]["state_danger"] != td["colors"]["state_warn"], (tid, "light")
            assert td["colors_dark"]["state_danger"] != td["colors_dark"]["state_warn"], (tid, "dark")

    def test_state_danger_contrast_ge_3_to_1(self):
        eng = ThemeEngine()
        for tid in ThemeEngine.THEME_DEFINITIONS:
            td = ThemeEngine.THEME_DEFINITIONS[tid]
            for mode, dark in (("light", False), ("dark", True)):
                eng._dark = dark
                pal = eng._active_palette(td, tid)
                val = pal["state_danger"]
                assert _contrast(val, pal["bg"]) >= 3.0, (tid, mode, "bg")
                assert _contrast(val, pal["bg_card"]) >= 3.0, (tid, mode, "card")

    def test_state_danger_in_active_palette(self):
        """state_danger 进入活动色板；消费侧 theme_color 不再走 fallback。"""
        eng = ThemeEngine()
        for tid in ("ui_minimal", "ui_cream", "ui_night", "ui_whale"):
            for dark in (False, True):
                eng._dark = dark
                assert "state_danger" in eng._active_palette(
                    ThemeEngine.THEME_DEFINITIONS[tid], tid)
