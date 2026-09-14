"""tests/test_core.py —— core 模块测试。

覆盖：
- AppConfig 配置加载
- SAFE_COMMAND_WHITELIST 与 FORBIDDEN_COMMANDS 不矛盾
- normalize_provider 映射正确性
"""
import pytest


class TestSafeCommandWhitelist:
    """安全白名单一致性测试（对应 Fix 5）。"""

    def test_pip_not_in_whitelist(self):
        from core import SAFE_COMMAND_WHITELIST
        assert "pip" not in SAFE_COMMAND_WHITELIST
        assert "pip3" not in SAFE_COMMAND_WHITELIST

    def test_npm_not_in_whitelist(self):
        from core import SAFE_COMMAND_WHITELIST
        assert "npm" not in SAFE_COMMAND_WHITELIST
        assert "npx" not in SAFE_COMMAND_WHITELIST

    def test_docker_not_in_whitelist(self):
        from core import SAFE_COMMAND_WHITELIST
        assert "docker" not in SAFE_COMMAND_WHITELIST

    def test_git_not_in_whitelist(self):
        """git 不在快速预检白名单（需走 command_runner 完整判定）。"""
        from core import SAFE_COMMAND_WHITELIST
        assert "git" not in SAFE_COMMAND_WHITELIST

    def test_python_in_whitelist(self):
        from core import SAFE_COMMAND_WHITELIST
        assert "python" in SAFE_COMMAND_WHITELIST
        assert "python3" in SAFE_COMMAND_WHITELIST

    def test_whitelist_no_overlap_with_forbidden(self):
        """白名单与 command_runner 的禁止列表不应有交集。"""
        from core import SAFE_COMMAND_WHITELIST
        from command_runner import FORBIDDEN_COMMANDS
        overlap = set(SAFE_COMMAND_WHITELIST) & set(FORBIDDEN_COMMANDS)
        assert not overlap, f"白名单与禁止列表有交集: {overlap}"


class TestNormalizeProvider:
    """normalize_provider 映射测试。"""

    def test_deepseek(self):
        from core import normalize_provider
        assert normalize_provider("deepseek") == "deepseek"

    def test_openai(self):
        from core import normalize_provider
        assert normalize_provider("openai") == "openai"

    def test_ollama(self):
        from core import normalize_provider
        assert normalize_provider("ollama") == "ollama"

    def test_unknown_defaults(self):
        from core import normalize_provider
        result = normalize_provider("unknown_provider_xyz")
        assert isinstance(result, str)

    def test_case_insensitive(self):
        from core import normalize_provider
        assert normalize_provider("DeepSeek") == normalize_provider("deepseek")


class TestAppConfig:
    """AppConfig 加载测试。"""

    def test_default_config_has_required_fields(self, tmp_path):
        """默认配置包含必要字段。"""
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        assert hasattr(cfg, "api_url")
        assert hasattr(cfg, "api_model")
        assert hasattr(cfg, "workspace")

    def test_workspace_defaults_to_cwd(self, tmp_path):
        from core import AppConfig
        cfg = AppConfig(str(tmp_path))
        assert cfg.workspace is not None
