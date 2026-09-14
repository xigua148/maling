"""tests/test_utils.py —— utils 模块测试。

覆盖：
- _format_data YAML/JSON 格式化（Fix 1）
- _atomic_write_json 原子写入（Fix 7）
- Windows 平台兼容（Fix 3）
"""
import json
import os
import tempfile

import pytest


class TestFormatData:
    """_format_data 格式化测试（对应 Fix 1: _HAS_YAML 导入）。"""

    def test_format_yaml(self):
        from utils import _format_data
        yaml_text = "name: test\nversion: 1.0\nitems:\n  - apple\n  - banana\n"
        result = _format_data(yaml_text)
        assert result is not None
        assert "name" in str(result)

    def test_format_json(self):
        from utils import _format_data
        json_text = '{"name": "test", "version": 1.0}'
        result = _format_data(json_text)
        assert result is not None

    def test_format_plain_text_returns_none_or_original(self):
        from utils import _format_data
        plain = "这是一段普通文本"
        result = _format_data(plain)
        # 纯文本应返回 None 或原样
        assert result is None or isinstance(result, str)

    def test_format_empty_string(self):
        from utils import _format_data
        result = _format_data("")
        # 空字符串返回提示信息或 None
        assert result is None or isinstance(result, str)


class TestAtomicWriteJson:
    """_atomic_write_json 原子写入测试（对应 Fix 7）。"""

    def test_write_and_read(self, tmp_path):
        from utils import _atomic_write_json
        target = str(tmp_path / "test.json")
        data = {"messages": [{"role": "user", "content": "测试"}], "meta": {"v": 1}}
        _atomic_write_json(target, data)
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_overwrite_existing(self, tmp_path):
        from utils import _atomic_write_json
        target = str(tmp_path / "test.json")
        _atomic_write_json(target, {"old": True})
        _atomic_write_json(target, {"new": True})
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == {"new": True}

    def test_unicode_content(self, tmp_path):
        from utils import _atomic_write_json
        target = str(tmp_path / "test.json")
        data = {"text": "你好世界 🌍"}
        _atomic_write_json(target, data)
        with open(target, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["text"] == "你好世界 🌍"


class TestPlatformCompat:
    """Windows 平台兼容性测试（对应 Fix 3）。"""

    def test_no_top_level_resource_import(self):
        """resource 模块不应在顶层导入（Windows 不存在）。"""
        with open("utils.py", "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        for line in lines[:50]:
            stripped = line.strip()
            assert not stripped.startswith("import resource"), \
                "顶层不应 import resource（Windows 不兼容）"

    def test_sys_platform_check_exists(self):
        """存在 sys.platform 平台检测。"""
        with open("utils.py", "r", encoding="utf-8") as f:
            content = f.read()
        assert "sys.platform" in content

    def test_profile_code_no_crash_on_windows(self):
        """_profile_code 在 Windows 不报 resource 缺失。"""
        from utils import _profile_code
        result = _profile_code("x = sum(i*i for i in range(100))")
        assert "resource" not in str(result).lower() or "error" not in str(result).lower()
