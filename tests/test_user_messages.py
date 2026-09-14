"""tests/test_user_messages.py —— 用户友好消息转换测试。

覆盖：
- format_tool_error: 工具 JSON 错误 → 可读文本
- format_api_error: API 异常 → 用户提示
- format_agent_summary: 任务结果 → 友好汇总
- truncate_for_display: 长文本截断
"""
import json
import pytest


class TestFormatToolError:
    """工具错误格式化测试。"""

    def test_denied_status(self):
        from user_messages import format_tool_error
        result = format_tool_error("write_file", json.dumps({"status": "denied", "message": "用户拒绝授权"}))
        assert "拒绝" in result
        assert "🚫" in result

    def test_error_not_found(self):
        from user_messages import format_tool_error
        result = format_tool_error("read_file", json.dumps({"status": "error", "message": "文件不存在: /foo"}))
        assert "找不到" in result
        assert "❌" in result

    def test_error_permission(self):
        from user_messages import format_tool_error
        result = format_tool_error("write_file", json.dumps({"status": "error", "message": "无权限访问"}))
        assert "权限" in result

    def test_error_timeout(self):
        from user_messages import format_tool_error
        result = format_tool_error("run_command", json.dumps({"status": "error", "message": "操作超时"}))
        assert "超时" in result
        assert "⏰" in result

    def test_error_missing_dependency(self):
        from user_messages import format_tool_error
        result = format_tool_error("image_info", json.dumps({"status": "error", "message": "需要 Pillow 库"}))
        assert "依赖" in result
        assert "📦" in result

    def test_error_generic(self):
        from user_messages import format_tool_error
        result = format_tool_error("some_tool", json.dumps({"status": "error", "message": "未知错误"}))
        assert "出错" in result

    def test_invalid_json(self):
        from user_messages import format_tool_error
        result = format_tool_error("bad_tool", "not json at all")
        assert "无法解析" in result

    def test_ok_status_returns_message(self):
        from user_messages import format_tool_error
        result = format_tool_error("tool", json.dumps({"status": "ok", "message": "操作成功"}))
        assert "操作成功" in result


class TestFormatApiError:
    """API 错误格式化测试。"""

    def test_connection_error(self):
        from user_messages import format_api_error
        result = format_api_error(ConnectionError("Connection refused"))
        assert "网络" in result
        assert "🌐" in result

    def test_timeout_error(self):
        from user_messages import format_api_error
        result = format_api_error(TimeoutError("Request timeout"))
        assert "超时" in result
        assert "⏰" in result

    def test_401_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("401 Unauthorized"))
        assert "API Key" in result
        assert "🔑" in result

    def test_403_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("403 Forbidden"))
        assert "拒绝" in result

    def test_404_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("404 Not Found"))
        assert "找不到" in result

    def test_429_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("429 rate limit exceeded"))
        assert "限流" in result

    def test_500_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("500 Internal Server Error"))
        assert "服务器" in result

    def test_generic_error(self):
        from user_messages import format_api_error
        result = format_api_error(Exception("something weird"))
        assert "请求失败" in result

    def test_with_context(self):
        from user_messages import format_api_error
        # 用不匹配任何特殊模式的错误，确保走通用分支带出 context
        result = format_api_error(Exception("未知异常XYZ"), context="任务执行")
        assert "任务执行" in result


class TestFormatAgentSummary:
    """Agent 任务汇总格式化测试。"""

    def test_done_status(self):
        from user_messages import format_agent_summary
        result = format_agent_summary("done", "完成任务", [1, 2, 3], {})
        assert "完成" in result
        assert "✅" in result
        assert "3" in result

    def test_paused_status(self):
        from user_messages import format_agent_summary
        result = format_agent_summary("paused", "暂停任务", [1], {"current_blocker": "等待输入"})
        assert "暂停" in result
        assert "⏸️" in result
        assert "等待输入" in result

    def test_failed_status(self):
        from user_messages import format_agent_summary
        result = format_agent_summary("failed", "失败任务", [], {"current_blocker": "API 超时"})
        assert "未完成" in result
        assert "API 超时" in result


class TestTruncateForDisplay:
    """长文本截断测试。"""

    def test_short_text_unchanged(self):
        from user_messages import truncate_for_display
        text = "hello"
        assert truncate_for_display(text) == text

    def test_long_text_truncated(self):
        from user_messages import truncate_for_display
        text = "a" * 1000
        result = truncate_for_display(text, max_len=100)
        assert len(result) < len(text)
        assert "省略" in result

    def test_exact_max_len(self):
        from user_messages import truncate_for_display
        text = "a" * 500
        assert truncate_for_display(text, max_len=500) == text
