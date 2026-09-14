"""tests/test_chat_bubble_utils.py —— 气泡渲染辅助函数测试。

覆盖 chat_bubble_utils.py 中所有纯函数。
"""
import pytest
from datetime import datetime


class TestStyleConstants:
    """样式常量测试。"""

    def test_highlight_style_gold(self):
        from gui.chat_bubble_utils import HIGHLIGHT_STYLE
        assert "FFD700" in HIGHLIGHT_STYLE

    def test_error_style_red(self):
        from gui.chat_bubble_utils import ERROR_STYLE
        assert "FF4444" in ERROR_STYLE

    def test_favorite_style_pink(self):
        from gui.chat_bubble_utils import FAVORITE_STYLE
        assert "FF69B4" in FAVORITE_STYLE

    def test_clear_style_empty(self):
        from gui.chat_bubble_utils import CLEAR_STYLE
        assert CLEAR_STYLE == ""

    def test_default_bubble_width(self):
        from gui.chat_bubble_utils import DEFAULT_MAX_BUBBLE_WIDTH
        assert DEFAULT_MAX_BUBBLE_WIDTH == 880


class TestFormatTimestamp:
    """时间戳格式化测试。"""

    def test_specific_datetime(self):
        from gui.chat_bubble_utils import format_timestamp
        dt = datetime(2024, 6, 15, 14, 30)
        assert format_timestamp(dt) == "14:30"

    def test_custom_format(self):
        from gui.chat_bubble_utils import format_timestamp
        dt = datetime(2024, 6, 15, 14, 30, 45)
        result = format_timestamp(dt, fmt="%H:%M:%S")
        assert result == "14:30:45"

    def test_none_uses_now(self):
        from gui.chat_bubble_utils import format_timestamp
        result = format_timestamp(None)
        assert isinstance(result, str)
        assert len(result) == 5  # "HH:MM"


class TestFormatRoleLabel:
    """角色标签格式化测试。"""

    def test_user_label(self):
        from gui.chat_bubble_utils import format_role_label
        assert format_role_label("user") == "我"

    def test_assistant_label(self):
        from gui.chat_bubble_utils import format_role_label
        assert format_role_label("assistant") == "AI"

    def test_system_label(self):
        from gui.chat_bubble_utils import format_role_label
        assert format_role_label("system") == "系统"

    def test_unknown_role_passthrough(self):
        from gui.chat_bubble_utils import format_role_label
        assert format_role_label("custom_role") == "custom_role"


class TestIsConsecutiveRole:
    """连续角色判断测试。"""

    def test_same_role_consecutive(self):
        from gui.chat_bubble_utils import is_consecutive_role
        assert is_consecutive_role("user", "user") is True

    def test_different_role_not_consecutive(self):
        from gui.chat_bubble_utils import is_consecutive_role
        assert is_consecutive_role("user", "assistant") is False

    def test_none_prev_not_consecutive(self):
        from gui.chat_bubble_utils import is_consecutive_role
        assert is_consecutive_role(None, "user") is False


class TestTruncateText:
    """文本截断测试。"""

    def test_short_unchanged(self):
        from gui.chat_bubble_utils import truncate_text
        assert truncate_text("hello") == "hello"

    def test_long_truncated(self):
        from gui.chat_bubble_utils import truncate_text
        result = truncate_text("a" * 100, max_len=10)
        assert result == "a" * 10 + "..."

    def test_newlines_flattened(self):
        from gui.chat_bubble_utils import truncate_text
        assert "\n" not in truncate_text("line1\nline2")


class TestBuildBubbleMetadata:
    """气泡 metadata 构造测试。"""

    def test_empty_metadata(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        meta = build_bubble_metadata()
        assert meta == {}

    def test_with_attachments(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        atts = [{"name": "file.py", "size": 100}]
        meta = build_bubble_metadata(attachments=atts)
        assert "attachments" in meta
        assert len(meta["attachments"]) == 1

    def test_with_model(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        meta = build_bubble_metadata(model="gpt-4")
        assert meta["model"] == "gpt-4"

    def test_zero_tokens_excluded(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        meta = build_bubble_metadata(tokens=0)
        assert "tokens" not in meta

    def test_positive_tokens_included(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        meta = build_bubble_metadata(tokens=150)
        assert meta["tokens"] == 150

    def test_combined_fields(self):
        from gui.chat_bubble_utils import build_bubble_metadata
        meta = build_bubble_metadata(model="deepseek", tokens=200, latency_ms=500)
        assert len(meta) == 3
        assert meta["model"] == "deepseek"
        assert meta["tokens"] == 200
        assert meta["latency_ms"] == 500


class TestFormatMessageCount:
    """消息计数格式化测试。"""

    def test_zero_messages(self):
        from gui.chat_bubble_utils import format_message_count
        assert format_message_count(0) == "暂无消息"

    def test_one_message(self):
        from gui.chat_bubble_utils import format_message_count
        assert format_message_count(1) == "1 条消息"

    def test_multiple_messages(self):
        from gui.chat_bubble_utils import format_message_count
        assert format_message_count(42) == "42 条消息"


class TestEstimateBubbleHeight:
    """气泡高度估算测试。"""

    def test_empty_text_minimum(self):
        from gui.chat_bubble_utils import estimate_bubble_height
        h = estimate_bubble_height("")
        assert h >= 32  # 最小高度

    def test_longer_text_taller(self):
        from gui.chat_bubble_utils import estimate_bubble_height
        short_h = estimate_bubble_height("hi")
        long_h = estimate_bubble_height("word " * 100)
        assert long_h > short_h

    def test_multiline_taller(self):
        from gui.chat_bubble_utils import estimate_bubble_height
        single = estimate_bubble_height("one line of text here")
        multi = estimate_bubble_height("line1\nline2\nline3\nline4\nline5")
        assert multi > single
