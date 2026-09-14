"""tests/test_chat_helpers.py —— 聊天辅助函数测试。

覆盖 chat_helpers.py 中所有纯函数。
"""
import pytest


class TestBuildMatcher:
    """build_matcher 测试。"""

    def test_empty_query_returns_none(self):
        from gui.chat_helpers import build_matcher
        assert build_matcher("") is None

    def test_plain_text_case_insensitive(self):
        from gui.chat_helpers import build_matcher
        matcher = build_matcher("Hello")
        assert matcher is not None
        assert matcher("hello world") is True
        assert matcher("HELLO there") is True
        assert matcher("goodbye") is False

    def test_regex_valid(self):
        from gui.chat_helpers import build_matcher
        matcher = build_matcher(r"\d+", use_regex=True)
        assert matcher is not None
        assert matcher("abc123") is True
        assert matcher("no digits") is False

    def test_regex_invalid_returns_none(self):
        from gui.chat_helpers import build_matcher
        matcher = build_matcher("[invalid", use_regex=True)
        assert matcher is None


class TestHighlightStyle:
    """高亮样式测试。"""

    def test_highlight_not_empty(self):
        from gui.chat_helpers import highlight_style
        style = highlight_style()
        assert "FFD700" in style  # 金色

    def test_clear_is_empty(self):
        from gui.chat_helpers import clear_highlight_style
        assert clear_highlight_style() == ""


class TestTruncatePreview:
    """截断预览测试。"""

    def test_short_text_unchanged(self):
        from gui.chat_helpers import truncate_preview
        assert truncate_preview("hello") == "hello"

    def test_long_text_truncated(self):
        from gui.chat_helpers import truncate_preview
        text = "a" * 100
        result = truncate_preview(text, max_len=10)
        assert result == "a" * 10 + "..."

    def test_newlines_replaced(self):
        from gui.chat_helpers import truncate_preview
        assert truncate_preview("line1\nline2") == "line1 line2"


class TestFormatSearchResult:
    """搜索结果格式化测试。"""

    def test_basic_format(self):
        from gui.chat_helpers import format_search_result
        result = format_search_result("会话1", "user", "你好世界")
        assert "[会话1]" in result
        assert "user" in result
        assert "你好世界" in result

    def test_long_content_truncated(self):
        from gui.chat_helpers import format_search_result
        result = format_search_result("S", "assistant", "x" * 200)
        assert "..." in result


class TestFilterMessagesByRole:
    """消息角色过滤测试。"""

    def test_no_filter_returns_all(self):
        from gui.chat_helpers import filter_messages_by_role
        msgs = [("user", "hi", ""), ("assistant", "hello", "")]
        assert len(filter_messages_by_role(msgs)) == 2

    def test_filter_single_role(self):
        from gui.chat_helpers import filter_messages_by_role
        msgs = [("user", "hi", ""), ("assistant", "hello", ""), ("user", "again", "")]
        result = filter_messages_by_role(msgs, roles=["user"])
        assert len(result) == 2
        assert all(m[0] == "user" for m in result)

    def test_filter_empty_roles_list(self):
        from gui.chat_helpers import filter_messages_by_role
        msgs = [("user", "hi", "")]
        result = filter_messages_by_role(msgs, roles=[])
        assert len(result) == 0


class TestFormatExportPreview:
    """导出预览测试。"""

    def test_basic_preview(self):
        from gui.chat_helpers import format_export_preview
        msgs = [("user", "你好", ""), ("assistant", "你好啊", "")]
        result = format_export_preview(msgs)
        assert "我:" in result
        assert "AI:" in result

    def test_truncation_notice(self):
        from gui.chat_helpers import format_export_preview
        msgs = [(f"user", f"msg{i}", "") for i in range(10)]
        result = format_export_preview(msgs, max_msgs=3)
        assert "还有" in result


class TestParseCommandInput:
    """斜杠命令解析测试。"""

    def test_normal_text(self):
        from gui.chat_helpers import parse_command_input
        cmd, args = parse_command_input("hello world")
        assert cmd is None
        assert args == "hello world"

    def test_command_no_args(self):
        from gui.chat_helpers import parse_command_input
        cmd, args = parse_command_input("/clear")
        assert cmd == "clear"
        assert args == ""

    def test_command_with_args(self):
        from gui.chat_helpers import parse_command_input
        cmd, args = parse_command_input("/search keyword")
        assert cmd == "search"
        assert args == "keyword"


class TestEstimateReadingTime:
    """阅读时间估算测试。"""

    def test_short_text_min_one(self):
        from gui.chat_helpers import estimate_reading_time
        assert estimate_reading_time("hi") >= 1

    def test_longer_text_more_time(self):
        from gui.chat_helpers import estimate_reading_time
        short = estimate_reading_time("hello")
        long = estimate_reading_time(" ".join(["word"] * 200))
        assert long > short


class TestDetectCodeLanguage:
    """代码语言检测测试。"""

    def test_python_block(self):
        from gui.chat_helpers import detect_code_language
        assert detect_code_language("```python\nprint('hi')") == "python"

    def test_no_language(self):
        from gui.chat_helpers import detect_code_language
        assert detect_code_language("```\nsome code") == "text"

    def test_plain_text(self):
        from gui.chat_helpers import detect_code_language
        assert detect_code_language("just text") == "text"


class TestDetectExportFormat:
    """导出格式检测测试。"""

    def test_markdown(self):
        from gui.chat_helpers import detect_export_format
        assert detect_export_format("Markdown (*.md)") == "markdown"

    def test_txt(self):
        from gui.chat_helpers import detect_export_format
        assert detect_export_format("文本文件 (*.txt)") == "txt"

    def test_json_fallback(self):
        from gui.chat_helpers import detect_export_format
        assert detect_export_format("JSON (*.json)") == "json"

    def test_unknown_fallback(self):
        from gui.chat_helpers import detect_export_format
        assert detect_export_format("Whatever") == "json"


class TestNormalizeSessionName:
    """会话名称规范化测试。"""

    def test_normal_name(self):
        from gui.chat_helpers import normalize_session_name
        assert normalize_session_name("我的会话") == "我的会话"

    def test_empty_fallback(self):
        from gui.chat_helpers import normalize_session_name
        assert normalize_session_name("") == "聊天记录"

    def test_none_fallback(self):
        from gui.chat_helpers import normalize_session_name
        assert normalize_session_name(None) == "聊天记录"

    def test_whitespace_stripped(self):
        from gui.chat_helpers import normalize_session_name
        assert normalize_session_name("  test  ") == "test"

    def test_custom_default(self):
        from gui.chat_helpers import normalize_session_name
        assert normalize_session_name("", default="Default") == "Default"
