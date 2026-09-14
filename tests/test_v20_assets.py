"""tests/test_v20_assets.py —— v2.0 资产 / URL 契约测试（V20-05 附带，域2）。

docs/design-v20.md §4.1 + prd-v20.md §4.1 + Q-U2：
- **只读**断言仓库根 `version.json` 的 `assets` 结构（**不修改**该文件，域1 独占）；
- 产物命名规范 `MaLing_v<X.Y.Z>_win_onedir.zip` / `MaLing_v<X.Y.Z>_win_single.exe`；
- `.sha256` 内容格式 `<hash>  <filename>`（两空格）；
- R-M：所有 URL 必须 `https://`。

域1 尚未补完 `assets` 时，对应断言 **skip 并注明**（契约先立，字段后补）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gui import update_downloader as dl

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_JSON = REPO_ROOT / "version.json"

# R-M：默认允许的 GitHub 系域名（域名白名单权威在 gui.update_checker.is_allowed_url，
# 本测试只做"https-only"契约断言，不重复实现白名单）。
_HTTPS_RE = re.compile(r"^https://[^\s]+$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@pytest.fixture(scope="module")
def version_data() -> dict:
    assert VERSION_JSON.is_file(), f"version.json 不存在：{VERSION_JSON}"
    data = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# ---------------------------------------------------------------------------
# 命名规范 / .sha256 格式（纯契约，不依赖 version.json 是否补完）
# ---------------------------------------------------------------------------
class TestNamingContract:
    def test_asset_filename_convention(self):
        assert dl.asset_filename_for("2.0.0", "onedir") == "MaLing_v2.0.0_win_onedir.zip"
        assert dl.asset_filename_for("2.0.0", "onefile") == "MaLing_v2.0.0_win_single.exe"
        assert dl.ASSET_FILENAME_RE.match("MaLing_v2.0.0_win_onedir.zip")
        assert dl.ASSET_FILENAME_RE.match("MaLing_v12.34.56_win_single.exe")
        assert not dl.ASSET_FILENAME_RE.match("MaLing_v2.0.0_win.zip")
        assert not dl.ASSET_FILENAME_RE.match("maling_v2.0.0_win_onedir.zip")  # 大小写

    def test_sha256_file_format_roundtrip(self):
        digest = "0123456789abcdef" * 4  # 64 hex
        line = dl.sha256_file_line(digest, "MaLing_v2.0.0_win_onedir.zip")
        assert re.match(r"^[0-9a-f]{64}  \S+$", line)          # `<hash>  <filename>`
        assert line.count("  ") == 1                            # 恰两空格分隔
        assert dl.parse_sha256_file(line + "\n") == (
            digest, "MaLing_v2.0.0_win_onedir.zip"
        )
        assert dl.parse_sha256_file("not-a-hash  file.zip") is None


# ---------------------------------------------------------------------------
# version.json 契约（只读；缺失字段 → skip 并注明）
# ---------------------------------------------------------------------------
class TestVersionJsonContract:
    def test_basic_fields(self, version_data):
        assert isinstance(version_data.get("version"), str)
        assert re.match(r"^\d+\.\d+\.\d+$", version_data["version"])
        assert isinstance(version_data.get("channel"), str)

    def test_min_updatable_format_if_present(self, version_data):
        mu = version_data.get("min_updatable")
        if mu is None:
            pytest.skip("version.json 尚无 min_updatable（域1 待补，契约断言跳过）")
        assert re.match(r"^\d+\.\d+\.\d+$", mu)

    def test_downloads_github_present_when_published(self, version_data):
        downloads = version_data.get("downloads")
        github = downloads.get("github") if isinstance(downloads, dict) else None
        if not github:
            pytest.skip(
                "version.json.downloads.github 仍为空占位（⚠-5 发版硬闸，仅发布前填真实 URL）"
            )
        assert _HTTPS_RE.match(github), f"downloads.github 必须 https：{github}"

    def test_assets_contract(self, version_data):
        assets = version_data.get("assets")
        if not isinstance(assets, dict):
            pytest.skip("version.json 尚无 assets（域1 待补；契约断言按 §4.1 skip）")
        for kind in ("onedir", "single"):
            entry = assets.get(kind)
            if not isinstance(entry, dict):
                pytest.skip(f"assets.{kind} 缺失（域1 待补）")
            url = entry.get("url")
            assert isinstance(url, str) and _HTTPS_RE.match(url), (
                f"assets.{kind}.url 必须为 https：{url!r}"
            )
            mirror = entry.get("mirror")
            if mirror:
                assert _HTTPS_RE.match(mirror), f"assets.{kind}.mirror 必须为 https：{mirror!r}"
            sha = entry.get("sha256")
            if sha:
                assert _SHA256_RE.match(sha), f"assets.{kind}.sha256 必须 64 位 hex：{sha!r}"
            size = entry.get("size")
            if size is not None:
                assert isinstance(size, int) and size > 0
            filename = entry.get("filename")
            if filename:
                assert dl.ASSET_FILENAME_RE.match(filename), (
                    f"assets.{kind}.filename 不符 Q-U2 命名规范：{filename!r}"
                )

    def test_asset_url_matches_kind_filename(self, version_data):
        """url 末段应与该 kind 的命名规范一致（若已给出 url）。"""
        assets = version_data.get("assets")
        if not isinstance(assets, dict):
            pytest.skip("version.json 尚无 assets（域1 待补）")
        expect = {"onedir": "win_onedir.zip", "single": "win_single.exe"}
        for kind, suffix in expect.items():
            entry = assets.get(kind)
            if not isinstance(entry, dict):
                continue
            url = entry.get("url") or ""
            if not url:
                continue
            assert url.endswith(suffix), (
                f"assets.{kind}.url 末段应为 {suffix}：{url}"
            )

    def test_raw_version_json_not_modified_by_test(self):
        """把 version.json 的当前内容与读取时比对（只读保证）。"""
        before = VERSION_JSON.read_bytes()
        _ = json.loads(before.decode("utf-8"))
        assert VERSION_JSON.read_bytes() == before
