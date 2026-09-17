# -*- coding: utf-8 -*-
"""gui/diagnostics.py 单测（v2.2.5）。

重点在**安全**：诊断包会把配置一起带走，必须保证凭据类值绝不出包。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from gui.diagnostics import (
    build_bundle,
    collect_environment,
    collect_process_tree,
    redact_config,
    redact_text,
    tail_text_file,
)

SECRET = "sk-SECRET-VALUE-1234567890"

SAMPLE_CFG = f"""api:
  provider: deepseek
  key: {SECRET}
  url: https://api.deepseek.com/chat/completions
web_search:
  enabled: true
  bocha_api_key: ''
  # 注释里出现的 token 字样不应影响判断
output:
  debug: false
"""


class TestRedaction:
    def test_secret_value_is_removed_but_key_kept(self):
        out = redact_text(SAMPLE_CFG)
        assert SECRET not in out
        assert "key:" in out                      # 键名保留，便于定位
        assert "<redacted>" in out

    def test_non_sensitive_values_survive(self):
        out = redact_text(SAMPLE_CFG)
        assert "https://api.deepseek.com/chat/completions" in out
        assert "deepseek" in out
        assert "debug: false" in out

    def test_empty_value_is_also_redacted(self):
        out = redact_text("bocha_api_key: ''\n")
        assert "<redacted>" in out

    def test_indent_is_preserved(self):
        out = redact_text("  key: x\n")
        assert out.startswith("  key:")

    @pytest.mark.parametrize("k", ["token", "secret", "password", "credential",
                                   "auth", "access_key", "apiKey"])
    def test_common_sensitive_names(self, k):
        out = redact_text(f"{k}: leakme\n")
        assert "leakme" not in out

    def test_extra_keys_supported(self):
        out = redact_text("my_private_field: leakme\n", extra_keys=["my_private_field"])
        assert "leakme" not in out

    def test_non_string_passthrough(self):
        assert redact_text(None) is None  # type: ignore[arg-type]

    def test_comment_only_line_untouched(self):
        """注释行不参与脱敏（输出按行规整，故比较时不含尾换行）。"""
        line = "  # 这里的 token 字样是注释，不该被改写"
        assert redact_text(line) == line


class TestReaders:
    def test_redact_config_missing_file_is_readable(self, tmp_path):
        out = redact_config(tmp_path / "nope.yaml")
        assert "不存在" in out

    def test_tail_text_file_truncates_keeps_tail(self, tmp_path):
        p = tmp_path / "big.log"
        p.write_text("".join(f"line{i}\n" for i in range(500)), encoding="utf-8")
        out = tail_text_file(p, max_lines=10)
        assert "已截断" in out
        assert "line499" in out
        assert "line0\n" not in out

    def test_tail_text_file_missing_is_readable(self, tmp_path):
        assert "不存在" in tail_text_file(tmp_path / "nope.log")

    def test_tail_text_file_small_not_truncated(self, tmp_path):
        p = tmp_path / "s.log"
        p.write_text("a\nb\n", encoding="utf-8")
        assert tail_text_file(p, max_lines=10) == "a\nb\n"


class TestCollectors:
    def test_environment_has_key_fields(self):
        out = collect_environment()
        for field in ("码铃版本", "Python", "平台", "frozen", "进程 id"):
            assert field in out

    def test_process_tree_mentions_root_pid(self):
        import os

        out = collect_process_tree()
        assert f"根进程 pid={os.getpid()}" in out


class TestBundle:
    def _make(self, tmp_path, providers=None):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(SAMPLE_CFG, encoding="utf-8")
        log = tmp_path / "maid_debug.log"
        log.write_text("INFO hello\n" * 20, encoding="utf-8")
        return build_bundle(
            dest_dir=tmp_path / "out", providers=providers,
            log_path=log, config_path=cfg)

    def test_bundle_is_zip_with_expected_members(self, tmp_path):
        z = self._make(tmp_path)
        assert z.is_file() and z.suffix == ".zip"
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
        assert {"environment.txt", "processes.txt", "logs/app_log_tail.txt",
                "config.redacted.yaml", "manifest.json"} <= names

    def test_no_secret_anywhere_in_bundle(self, tmp_path):
        """**最重要的一条**：整包任何成员里都不许出现明文凭据。"""
        z = self._make(tmp_path)
        with zipfile.ZipFile(z) as zf:
            for name in zf.namelist():
                assert SECRET.encode() not in zf.read(name), f"泄露于 {name}"

    def test_provider_section_is_included(self, tmp_path):
        z = self._make(tmp_path, providers={"sillytavern_stdout": lambda: "ST 输出示例"})
        with zipfile.ZipFile(z) as zf:
            assert "ST 输出示例" in zf.read("runtime/sillytavern_stdout.txt").decode()

    def test_failing_provider_does_not_break_bundle(self, tmp_path):
        def boom():
            raise RuntimeError("采集炸了")

        z = self._make(tmp_path, providers={"bad": boom})
        with zipfile.ZipFile(z) as zf:
            assert "采集失败" in zf.read("runtime/bad.txt").decode()
            assert "environment.txt" in zf.namelist()   # 其余成员照旧

    def test_provider_name_is_sanitized(self, tmp_path):
        z = self._make(tmp_path, providers={"../evil name": lambda: "x"})
        with zipfile.ZipFile(z) as zf:
            assert all(".." not in n for n in zf.namelist())

    def test_manifest_lists_members(self, tmp_path):
        z = self._make(tmp_path)
        with zipfile.ZipFile(z) as zf:
            man = json.loads(zf.read("manifest.json").decode())
        assert "config.redacted.yaml" in man["members"]
        assert "脱敏" in man["note"]

    def test_default_dir_when_not_specified(self, monkeypatch, tmp_path):
        """不传 dest_dir 时应落到默认目录（此处用 monkeypatch 改写，避免污染真实目录）。"""
        import gui.diagnostics as diag

        monkeypatch.setattr(diag, "default_bundle_dir", lambda: tmp_path / "d")
        cfg = tmp_path / "c.yaml"
        cfg.write_text("api:\n  key: x\n", encoding="utf-8")
        z = diag.build_bundle(config_path=cfg, log_path=tmp_path / "none.log")
        assert z.parent == tmp_path / "d"
