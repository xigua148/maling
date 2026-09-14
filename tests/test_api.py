"""tests/test_api.py —— API 客户端测试。

覆盖：
- APIKeyRotator 多 Key 轮换
- chat_stream_with_tools 生成器存在
- chat_stream 兼容入口
"""
import pytest
from unittest.mock import MagicMock, patch


class TestAPIKeyRotator:
    """API Key 轮换测试。"""

    def test_single_key(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator(["sk-key1"])
        assert rotator.current_key == "sk-key1"

    def test_multiple_keys_rotate(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator(["sk-key1", "sk-key2", "sk-key3"])
        assert rotator.current_key == "sk-key1"
        rotator.rotate()
        assert rotator.current_key == "sk-key2"
        rotator.rotate()
        assert rotator.current_key == "sk-key3"
        rotator.rotate()
        assert rotator.current_key == "sk-key1"  # 循环

    def test_mark_failed_skips_key(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator(["sk-key1", "sk-key2"])
        rotator.mark_failed("sk-key1")
        assert rotator.current_key == "sk-key2"

    def test_all_failed_resets(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator(["sk-key1", "sk-key2"])
        rotator.mark_failed("sk-key1")
        rotator.mark_failed("sk-key2")
        # 全部失败后应重置
        assert rotator.current_key == "sk-key1"

    def test_empty_keys(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator([])
        assert rotator.current_key == ""

    def test_strip_whitespace(self):
        from api import APIKeyRotator
        rotator = APIKeyRotator(["  sk-key1  ", "  "])
        assert rotator.current_key == "sk-key1"
        assert len(rotator.keys) == 1  # 空白 key 被过滤


class TestAPIClientInterface:
    """APIClient 接口测试（不实际调用 API）。"""

    def test_chat_method_exists(self, mock_cfg, logger):
        from api import APIClient
        client = APIClient(mock_cfg, logger)
        assert hasattr(client, "chat")

    def test_chat_stream_method_exists(self, mock_cfg, logger):
        from api import APIClient
        client = APIClient(mock_cfg, logger)
        assert hasattr(client, "chat_stream")

    def test_chat_stream_with_tools_exists(self, mock_cfg, logger):
        """v1.4.7: chat_stream_with_tools 生成器应存在。"""
        from api import APIClient
        client = APIClient(mock_cfg, logger)
        assert hasattr(client, "chat_stream_with_tools")

    def test_chat_stream_chunks_exists(self, mock_cfg, logger):
        from api import APIClient
        client = APIClient(mock_cfg, logger)
        assert hasattr(client, "chat_stream_chunks")

    def test_headers_contain_auth(self, mock_cfg, logger):
        from api import APIClient
        client = APIClient(mock_cfg, logger)
        headers = client._headers()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")
