# -*- coding: utf-8 -*-
"""v2.0 检查层测试（design-v20 §5 批 A / 域1，V20-04）。

覆盖（全部纯函数、不依赖网络）：
- 频道表：stable/beta URL 不同、非法回落 stable、别名契约（R-D）；
- 节奏闸 should_check_now：首次 / 24h 内 / 超 24h / force / 脏值；
- 提示节奏 should_prompt：忽略同日不重弹、新版本恢复（L1-5 验收②③）；
- 形态自适应 asset_for_form：onedir→zip、onefile→exe、缺 assets→None（L2-7）；
- 强校验 has_valid_sha256：缺失 / 非 64hex → False（Q-U5）；
- URL 白名单 is_allowed_url：http/file/UNC/相对/`..` 注入/非白名单全拒（R-M）；
- 形态探测 detect_install_form：源码态 dev / onedir（D-V20-06）；
- 向后兼容 _valid_remote / evaluate_update：旧式 version.json（无 assets）仍可用（L1-4）；
- save_update_state 原子写 + 读回一致 + save_ignored_version 语义不变（D-V20-10）。

隔离：update_state 一律 monkeypatch get_user_data_dir → tmp_path，不动真实 %APPDATA%。
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gui.update_checker as u  # noqa: E402
from core import __version__  # noqa: E402

try:
    from gui.qt_compat import QApplication
    _HAS_QT = True
except Exception:  # 无 PySide6 环境 → UI 相关用例 skip
    QApplication = None
    _HAS_QT = False


@pytest.fixture(scope="module")
def qapp():
    if not _HAS_QT:
        pytest.skip("需要 PySide6 才能构造页面")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """把 update_state.json 落到 tmp_path（不触碰真实用户数据目录）。"""
    monkeypatch.setattr("gui.utils.get_user_data_dir", lambda: tmp_path)
    return tmp_path


_SHA64 = "a" * 64


# ---------------------------------------------------------------------------
# 频道与 URL 表（L1-3 / D-V20-07）
# ---------------------------------------------------------------------------
class TestChannelTable:
    def test_owner_single_constant(self):
        assert u.GITHUB_OWNER
        assert u.GITHUB_REPO == "maling"
        assert u.GITHUB_OWNER in u.CHANNEL_URLS["stable"]

    def test_stable_and_beta_differ(self):
        assert u.CHANNEL_URLS["stable"] != u.CHANNEL_URLS["beta"]
        assert "/main/version.json" in u.CHANNEL_URLS["stable"]
        assert "/main/beta/version.json" in u.CHANNEL_URLS["beta"]

    def test_all_channel_urls_https_and_allowed(self):
        for url in u.CHANNEL_URLS.values():
            assert url.startswith("https://")
            assert u.is_allowed_url(url)

    def test_resolve_channel_url_known(self):
        assert u.resolve_channel_url("stable") == u.CHANNEL_URLS["stable"]
        assert u.resolve_channel_url("beta") == u.CHANNEL_URLS["beta"]

    def test_resolve_channel_url_case_and_whitespace(self):
        assert u.resolve_channel_url("  BETA ") == u.CHANNEL_URLS["beta"]

    def test_resolve_channel_url_illegal_falls_back_stable(self):
        for bad in ("", None, "nightly", "1.0", "stable-x", "  "):
            assert u.resolve_channel_url(bad) == u.CHANNEL_URLS["stable"]

    def test_resolve_channel_normalizes(self):
        assert u.resolve_channel("beta") == "beta"
        assert u.resolve_channel("BOGUS") == "stable"
        assert u.resolve_channel(None) == "stable"

    def test_alias_contract(self):
        # R-D：常量名保留，取值升级为 stable 频道
        assert u.VERSION_JSON_URL == u.CHANNEL_URLS["stable"]
        assert u.VERSION_JSON_URLS is u.CHANNEL_URLS

    def test_effective_channel_priority(self):
        # GuiConfig 真值源 > state.channel > stable
        assert u.resolve_effective_channel("beta", "stable") == "beta"
        assert u.resolve_effective_channel("", "beta") == "beta"
        assert u.resolve_effective_channel("", "") == "stable"
        assert u.resolve_effective_channel("bogus", "beta") == "stable"


# ---------------------------------------------------------------------------
# 检查节奏闸（Q-U13 / D-V20-14）
# ---------------------------------------------------------------------------
class TestShouldCheckNow:
    def test_first_run_no_last_checked(self):
        assert u.should_check_now({}) is True
        assert u.should_check_now({"last_checked": ""}) is True
        assert u.should_check_now(None) is True

    def test_within_24h_skips(self):
        now = datetime(2026, 9, 10, 12, 0, 0)
        state = {"last_checked": (now - timedelta(hours=1)).isoformat()}
        assert u.should_check_now(state, now) is False

    def test_over_24h_checks(self):
        now = datetime(2026, 9, 10, 12, 0, 0)
        state = {"last_checked": (now - timedelta(hours=25)).isoformat()}
        assert u.should_check_now(state, now) is True

    def test_exactly_24h_checks(self):
        now = datetime(2026, 9, 10, 12, 0, 0)
        state = {"last_checked": (now - timedelta(hours=24)).isoformat()}
        assert u.should_check_now(state, now) is True

    def test_date_only_last_checked(self):
        now = datetime(2026, 9, 10, 23, 0, 0)
        assert u.should_check_now({"last_checked": "2026-09-10"}, now) is False
        assert u.should_check_now({"last_checked": "2026-09-08"}, now) is True

    def test_force_bypasses_gate(self):
        now = datetime(2026, 9, 10, 12, 0, 0)
        state = {"last_checked": (now - timedelta(minutes=5)).isoformat()}
        assert u.should_check_now(state, now, force=True) is True

    def test_dirty_last_checked_checks(self):
        assert u.should_check_now({"last_checked": "not-a-date"}) is True


# ---------------------------------------------------------------------------
# 提示节奏 / 忽略去重（L1-5 验收②③）
# ---------------------------------------------------------------------------
class TestShouldPrompt:
    def test_no_ignore_prompts(self):
        assert u.should_prompt({}, "2.0.0", "2026-09-10") is True

    def test_newer_than_ignored_recovers(self):
        state = {"ignored_version": "2.0.0", "last_prompt_date": "2026-09-10"}
        assert u.should_prompt(state, "2.0.1", "2026-09-10") is True

    def test_same_ignored_same_day_silent(self):
        state = {"ignored_version": "2.0.0", "last_prompt_date": "2026-09-10"}
        assert u.should_prompt(state, "2.0.0", "2026-09-10") is False

    def test_same_ignored_different_day_prompts(self):
        state = {"ignored_version": "2.0.0", "last_prompt_date": "2026-09-09"}
        assert u.should_prompt(state, "2.0.0", "2026-09-10") is True

    def test_older_than_ignored_same_day_silent(self):
        state = {"ignored_version": "2.0.1", "last_prompt_date": "2026-09-10"}
        assert u.should_prompt(state, "2.0.0", "2026-09-10") is False

    def test_dirty_ignore_prompts(self):
        assert u.should_prompt({"ignored_version": "xx"}, "2.0.0", "2026-09-10") is True


# ---------------------------------------------------------------------------
# 形态自适应（L2-7 / D-V20-06）
# ---------------------------------------------------------------------------
class TestAssetForForm:
    _REMOTE = {
        "assets": {
            "onedir": {"url": "https://github.com/o/r/releases/x.zip", "sha256": _SHA64},
            "single": {"url": "https://github.com/o/r/releases/x.exe", "sha256": _SHA64},
        }
    }

    def test_onedir_picks_zip(self):
        assert u.asset_for_form(self._REMOTE, "onedir") is self._REMOTE["assets"]["onedir"]

    def test_onefile_picks_single(self):
        assert u.asset_for_form(self._REMOTE, "onefile") is self._REMOTE["assets"]["single"]
        assert u.asset_for_form(self._REMOTE, "single") is self._REMOTE["assets"]["single"]

    def test_default_form_is_onedir(self):
        assert u.asset_for_form(self._REMOTE) is self._REMOTE["assets"]["onedir"]

    def test_dev_falls_back_onedir(self):
        # 形态探测失败/源码态（"dev"）→ 默认 onedir
        assert u.asset_for_form(self._REMOTE, "dev") is self._REMOTE["assets"]["onedir"]

    def test_missing_assets_returns_none(self):
        assert u.asset_for_form({"version": "2.0.0"}, "onedir") is None
        assert u.asset_for_form(None, "onedir") is None

    def test_accepts_assets_table_directly(self):
        assert u.asset_for_form(self._REMOTE["assets"], "onedir") is not None

    def test_partial_assets_returns_none(self):
        remote = {"assets": {"onedir": {"url": "https://github.com/o/r/x.zip"}}}
        assert u.asset_for_form(remote, "onefile") is None


# ---------------------------------------------------------------------------
# sha256 强校验（Q-U5 / R-M）
# ---------------------------------------------------------------------------
class TestHasValidSha256:
    def test_valid_lower_hex(self):
        assert u.has_valid_sha256({"sha256": _SHA64}) is True

    def test_valid_upper_hex(self):
        assert u.has_valid_sha256({"sha256": "A" * 64}) is True

    def test_missing_is_false(self):
        assert u.has_valid_sha256({}) is False
        assert u.has_valid_sha256({"sha256": ""}) is False
        assert u.has_valid_sha256({"sha256": None}) is False

    def test_wrong_length_is_false(self):
        assert u.has_valid_sha256({"sha256": "a" * 63}) is False
        assert u.has_valid_sha256({"sha256": "a" * 65}) is False

    def test_non_hex_is_false(self):
        assert u.has_valid_sha256({"sha256": "z" * 64}) is False

    def test_non_dict_is_false(self):
        assert u.has_valid_sha256(None) is False
        assert u.has_valid_sha256("a" * 64) is False


# ---------------------------------------------------------------------------
# URL 安全白名单（R-M / D-V20-11）
# ---------------------------------------------------------------------------
class TestIsAllowedUrl:
    def test_allowed_github_hosts(self):
        assert u.is_allowed_url(
            "https://github.com/o/r/releases/download/v2.0.0/x.zip")
        assert u.is_allowed_url(
            "https://objects.githubusercontent.com/a/b/c")
        assert u.is_allowed_url(
            "https://raw.githubusercontent.com/o/r/main/version.json")
        assert u.is_allowed_url(
            "https://codeload.github.com/o/r/zip/refs/heads/main")

    def test_rejects_http(self):
        assert u.is_allowed_url("http://github.com/x") is False

    def test_rejects_file_scheme(self):
        assert u.is_allowed_url("file:///c:/x.zip") is False

    def test_rejects_unc(self):
        assert u.is_allowed_url("\\\\server\\share\\x.zip") is False
        assert u.is_allowed_url("\\\\github.com\\x") is False

    def test_rejects_protocol_relative(self):
        assert u.is_allowed_url("//github.com/x.zip") is False

    def test_rejects_relative_path(self):
        assert u.is_allowed_url("releases/x.zip") is False
        assert u.is_allowed_url("./x.zip") is False
        assert u.is_allowed_url("/x.zip") is False

    def test_rejects_dotdot_injection(self):
        assert u.is_allowed_url("https://github.com/a/../evil/x.zip") is False
        assert u.is_allowed_url("https://github.com/../../etc/passwd") is False

    def test_rejects_non_whitelist_host(self):
        assert u.is_allowed_url("https://evil.com/x.zip") is False
        assert u.is_allowed_url("https://github.com.evil.com/x.zip") is False

    def test_rejects_empty_and_nonstring(self):
        assert u.is_allowed_url("") is False
        assert u.is_allowed_url(None) is False
        assert u.is_allowed_url(123) is False

    def test_extra_hosts_enables_custom_mirror(self):
        url = "https://mirror.example.cn/releases/x.zip"
        assert u.is_allowed_url(url) is False
        assert u.is_allowed_url(url, ["mirror.example.cn"]) is True
        # 大小写不敏感
        assert u.is_allowed_url(url, ["Mirror.Example.CN"]) is True

    def test_subdomain_of_allowed_base(self):
        assert u.is_allowed_url("https://gist.github.com/x") is True

    def test_extract_host(self):
        assert u.extract_host("https://raw.githubusercontent.com/o/r/main") == \
            "raw.githubusercontent.com"
        assert u.extract_host("not a url") == ""


# ---------------------------------------------------------------------------
# 形态探测（D-V20-06）
# ---------------------------------------------------------------------------
class TestDetectInstallForm:
    def test_source_mode_is_dev(self):
        # 测试环境为源码态（sys.frozen 未设）→ dev
        assert u.detect_install_form() == "dev"

    def test_onedir_when_internal_present(self, monkeypatch, tmp_path):
        exe = tmp_path / "maling.exe"
        exe.write_text("x", encoding="utf-8")
        (tmp_path / "_internal").mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe), raising=False)
        assert u.detect_install_form() == "onedir"

    def test_onefile_when_no_internal(self, monkeypatch, tmp_path):
        exe = tmp_path / "MaLing_single.exe"
        exe.write_text("x", encoding="utf-8")
        meipass = tmp_path / "_MEI12345"
        meipass.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe), raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        assert u.detect_install_form() == "onefile"


# ---------------------------------------------------------------------------
# 向后兼容：旧式 version.json（无 assets）仍按 L1 正常提示（L1-4 验收①）
# ---------------------------------------------------------------------------
class TestBackwardCompat:
    _OLD_REMOTE = {
        "version": "2.0.0",
        "channel": "stable",
        "released_at": "2026-09-20",
        "min_compatible": "1.0.0",
        "downloads": {"github": "https://github.com/o/r/releases/x.zip"},
        "notes": ["a", "b"],
    }

    def test_valid_remote_accepts_old_style(self):
        assert u._valid_remote(self._OLD_REMOTE) is not None

    def test_valid_remote_rejects_empty_downloads(self):
        # ⚠-5 硬伤复现：downloads 为空 → 恒 None（客户端永不提示）
        assert u._valid_remote({"version": "2.0.0", "downloads": {}}) is None

    def test_evaluate_update_old_style_prompts(self):
        result = u.evaluate_update(self._OLD_REMOTE, "1.9.0", None)
        assert result is not None
        assert result["kind"] == "update"
        assert result["version"] == "2.0.0"
        assert result["primary"] == "https://github.com/o/r/releases/x.zip"

    def test_asset_for_form_none_for_old_style(self):
        assert u.asset_for_form(self._OLD_REMOTE, "onedir") is None

    def test_evaluate_update_keeps_old_keys_and_appends_new(self):
        result = u.evaluate_update(self._OLD_REMOTE, "1.9.0", None)
        # 既有五键语义不变（R-D 零变更）
        assert {"kind", "version", "notes", "primary", "mirror"} <= set(result.keys())
        # v2.0 追加三键（纯增量）；旧式无 assets → 三键均为 None 且仍能正常提示
        assert {"assets", "min_updatable", "release_url"} <= set(result.keys())
        assert result["assets"] is None
        assert result["min_updatable"] is None
        assert result["release_url"] is None

    def test_evaluate_update_passes_through_new_fields(self):
        remote = dict(self._OLD_REMOTE, assets={"onedir": {"url": "https://github.com/o/r/x.zip"}},
                      min_updatable="2.0.0",
                      release_url="https://github.com/o/r/releases/tag/v2.0.0")
        result = u.evaluate_update(remote, "1.9.0", None)
        assert result["assets"] == remote["assets"]
        assert result["min_updatable"] == "2.0.0"
        assert result["release_url"] == "https://github.com/o/r/releases/tag/v2.0.0"

    def test_evaluate_update_reinstall_also_has_new_keys(self):
        remote = dict(self._OLD_REMOTE, min_compatible="2.0.0", min_updatable="2.5.0")
        result = u.evaluate_update(remote, "1.0.0", None)
        assert result["kind"] == "reinstall"
        assert result["min_updatable"] == "2.5.0"
        assert result["assets"] is None

    def test_reinstall_when_below_min_compatible(self):
        remote = dict(self._OLD_REMOTE, min_compatible="2.0.0")
        result = u.evaluate_update(remote, "1.0.0", None)
        assert result["kind"] == "reinstall"


# ---------------------------------------------------------------------------
# update_state 原子写（D-V20-10）
# ---------------------------------------------------------------------------
class TestUpdateStateIO:
    def test_save_then_load_roundtrip(self, isolated_state):
        u.save_update_state({"channel": "beta", "pending_version": "2.0.0"})
        state = u.load_update_state()
        assert state["channel"] == "beta"
        assert state["pending_version"] == "2.0.0"
        # 文件真实落盘且为合法 JSON
        raw = json.loads((isolated_state / "update_state.json").read_text(encoding="utf-8"))
        assert raw["channel"] == "beta"

    def test_save_merges_existing_keys(self, isolated_state):
        u.save_update_state({"ignored_version": "1.9.0"})
        u.save_update_state({"channel": "stable"})
        state = u.load_update_state()
        assert state["ignored_version"] == "1.9.0"
        assert state["channel"] == "stable"

    def test_no_temp_file_left_behind(self, isolated_state):
        u.save_update_state({"a": 1})
        leftovers = [p.name for p in isolated_state.iterdir() if ".tmp" in p.name]
        assert leftovers == []

    def test_save_ignored_version_semantics(self, isolated_state):
        u.save_ignored_version("2.0.0")
        state = u.load_update_state()
        assert state["ignored_version"] == "2.0.0"
        assert state["last_checked"]  # 语义保留：忽略时同时记 last_checked

    def test_save_update_state_non_dict_ignored(self, isolated_state):
        u.save_update_state(None)  # 不抛异常、不写文件
        assert not (isolated_state / "update_state.json").exists()

    def test_download_subdict_persists(self, isolated_state):
        u.save_update_state({"download": {"version": "2.0.0", "received": 123}})
        state = u.load_update_state()
        assert state["download"]["version"] == "2.0.0"
        assert state["download"]["received"] == 123


# ---------------------------------------------------------------------------
# UpdateChecker 调用面（不联网，仅构造/解析）
# ---------------------------------------------------------------------------
class TestUpdateCheckerApi:
    def test_default_url_resolves_stable(self):
        checker = u.UpdateChecker(channel="")
        assert checker.url == u.CHANNEL_URLS["stable"]
        assert checker.channel == "stable"

    def test_beta_channel_url(self):
        checker = u.UpdateChecker(channel="beta")
        assert checker.url == u.CHANNEL_URLS["beta"]

    def test_explicit_url_wins(self):
        checker = u.UpdateChecker(url="https://example.com/x.json", channel="beta")
        assert checker.url == "https://example.com/x.json"

    def test_three_state_constants(self):
        assert u.CHECK_UPDATE == "update"
        assert u.CHECK_LATEST == "latest"
        assert u.CHECK_FAILED == "failed"

    def test_kept_contract_symbols_exist(self):
        # R-D：既有契约符号零变更
        for name in ("evaluate_update", "format_update_text", "pick_download_link",
                     "load_update_state", "save_ignored_version", "_valid_remote",
                     "VERSION_JSON_URL", "CHECK_TIMEOUT_SECONDS"):
            assert hasattr(u, name)

    def test_version_json_local_contract(self):
        """本仓库 version.json 具备 v2.0 契约字段且旧字段不变。"""
        info = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        assert info["version"] == __version__
        assert info["channel"] in ("stable", "beta")
        # ⚠-5：downloads.github 必须非空（否则客户端永不提示）
        assert isinstance(info["downloads"].get("github"), str)
        assert info["downloads"]["github"].startswith("https://")
        assert u._valid_remote(info) is not None
        # 新字段
        assert "min_updatable" in info
        assert "release_url" in info
        for key in ("onedir", "single"):
            asset = info["assets"][key]
            assert u.is_allowed_url(asset["url"])
            assert isinstance(asset["filename"], str) and asset["filename"]


# ---------------------------------------------------------------------------
# 修正1：公开 last_remote（消除 main.py 对私有 _worker 的耦合）
# ---------------------------------------------------------------------------
class TestLastRemote:
    def test_initial_none(self):
        checker = u.UpdateChecker(channel="stable")
        assert checker.last_remote is None

    def test_saved_after_successful_fetch(self, isolated_state):
        checker = u.UpdateChecker(channel="stable")
        raw = {
            "version": "2.0.0",
            "downloads": {"github": "https://github.com/o/r/releases/x.zip"},
            "assets": {"onedir": {"url": "https://github.com/o/r/releases/x.zip"}},
            "min_updatable": "2.0.0",
            "release_url": "https://github.com/o/r/releases/tag/v2.0.0",
        }
        checker._on_fetched(raw)          # 直调，不联网
        assert checker.last_remote is raw
        assert checker.last_remote["assets"] == raw["assets"]

    def test_last_remote_is_read_only_property(self):
        checker = u.UpdateChecker(channel="stable")
        with pytest.raises(AttributeError):
            checker.last_remote = {"x": 1}  # type: ignore[misc]

    def test_worker_symbol_retained(self):
        # R-D：私有 _worker 保留，不删不改行为
        checker = u.UpdateChecker(channel="stable")
        assert hasattr(checker, "_worker")


# ---------------------------------------------------------------------------
# 修正3：last_install 提示（纯函数 + 设置页只读行）
# ---------------------------------------------------------------------------
class TestLastInstallHint:
    def test_rolled_back(self):
        assert u.last_install_hint({"last_install": {"result": "rolled_back"}})

    def test_failed(self):
        assert u.last_install_hint({"last_install": {"result": "failed"}})

    def test_success_hidden(self):
        assert u.last_install_hint({"last_install": {"result": "success"}}) == ""

    def test_missing_and_dirty(self):
        assert u.last_install_hint({}) == ""
        assert u.last_install_hint(None) == ""
        assert u.last_install_hint({"last_install": "x"}) == ""
        assert u.last_install_hint({"last_install": {"result": "weird"}}) == ""

    def test_no_numeric_anxiety_words(self):
        text = u.last_install_hint({"last_install": {"result": "failed"}})
        for bad in ("失败 1 次", "落后", "还剩", "第 1 次", "N 次"):
            assert bad not in text


@pytest.mark.skipif(not _HAS_QT, reason="需要 PySide6")
class TestSettingsLastInstallLine:
    def _make_page(self, monkeypatch, last_install):
        from types import SimpleNamespace
        monkeypatch.setattr("gui.update_checker.load_update_state",
                            lambda: {"last_install": last_install})
        from gui.config import GuiConfig
        from gui.pages.page_settings import PageSettings
        return PageSettings(SimpleNamespace(config=GuiConfig(), cfg=None))

    def test_rolled_back_line_visible(self, monkeypatch, qapp):
        page = self._make_page(monkeypatch, {"version": "2.0.0", "result": "rolled_back"})
        label = page.update_last_install_label
        assert label.text() == "上次更新未完成，可重试"
        assert label.isHidden() is False

    def test_success_line_hidden(self, monkeypatch, qapp):
        page = self._make_page(monkeypatch, {"version": "2.0.0", "result": "success"})
        label = page.update_last_install_label
        assert label.text() == ""
        assert label.isHidden() is True

