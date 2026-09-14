"""tests/test_version.py —— 版本管理测试。

覆盖：
- 版本号从 version.json 单源读取
- 版本号格式正确
- get_version_info 返回完整 dict
"""
import pytest


class TestVersionModule:
    """版本模块测试。"""

    def test_get_version_returns_string(self):
        from version import get_version
        v = get_version()
        assert isinstance(v, str)
        assert len(v) > 0

    def test_version_format(self):
        """版本号应为 semver 格式（如 1.4.8）。"""
        from version import get_version
        v = get_version()
        parts = v.split(".")
        assert len(parts) >= 2
        for p in parts:
            assert p.isdigit()

    def test_get_version_info(self):
        from version import get_version_info
        info = get_version_info()
        assert isinstance(info, dict)
        assert "version" in info
        assert "released_at" in info

    def test_get_version_tuple(self):
        from version import get_version_tuple
        t = get_version_tuple()
        assert isinstance(t, tuple)
        assert len(t) >= 2
        assert all(isinstance(x, int) for x in t)

    def test_is_at_least(self):
        from version import is_at_least
        # 当前版本应 >= 1.0.0
        assert is_at_least(1, 0, 0)
        # 当前版本应 >= 自身
        from version import get_version_tuple
        t = get_version_tuple()
        assert is_at_least(t[0], t[1], t[2] if len(t) > 2 else 0)

    def test_get_app_title(self):
        from version import get_app_title
        title = get_app_title()
        assert "码铃" in title
        assert "MaLing" in title

    def test_version_consistent_with_core(self):
        """version.py 和 core.__version__ 应一致。"""
        from version import get_version
        from core import __version__
        assert get_version() == __version__


class TestConfigValidation:
    """配置校验测试。"""

    def test_validate_returns_list(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        warnings = cfg.validate()
        assert isinstance(warnings, list)

    def test_validate_warns_no_api_key(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        cfg.api_key = ""
        cfg.api_keys = []
        warnings = cfg.validate()
        assert any("API Key" in w for w in warnings)

    def test_validate_warns_bad_url(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        cfg.api_url = "not-a-url"
        warnings = cfg.validate()
        assert any("URL" in w for w in warnings)

    def test_validate_warns_bad_temperature(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        cfg.api_temperature = 5.0  # 超出 0-2 范围
        warnings = cfg.validate()
        assert any("temperature" in w.lower() for w in warnings)

    def test_validate_no_warnings_for_valid_config(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        cfg.api_key = "sk-test"
        cfg.api_url = "https://api.deepseek.com"
        cfg.api_temperature = 0.7
        cfg.api_max_tokens = 4096
        cfg.api_retry_times = 3
        cfg.agent_max_steps = 8
        warnings = cfg.validate()
        # 可能还有 workspace 不存在的警告，但不应有 API 相关警告
        api_warnings = [w for w in warnings if "API" in w or "temperature" in w.lower()]
        assert len(api_warnings) == 0

    def test_get_summary(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        summary = cfg.get_summary()
        assert isinstance(summary, dict)
        assert "provider" in summary
        assert "model" in summary
        assert "workspace" in summary
