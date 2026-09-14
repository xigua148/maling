"""tests/test_chat_input_logic.py —— 输入处理纯逻辑测试。"""
import pytest


class TestShouldTriggerCommandPopup:
    """指令补全弹窗触发条件测试。"""

    def test_slash_prefix_triggers(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("/help") is True

    def test_slash_with_space_no_trigger(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("/help me") is False

    def test_normal_text_no_trigger(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("hello") is False

    def test_empty_text(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("") is False

    def test_multiline_first_line_slash(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("/cmd\nsecond line") is True

    def test_multiline_first_line_normal(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("hello\n/world") is False

    def test_slash_only(self):
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("/") is True


class TestComputeInputHeight:
    """输入框高度计算测试。"""

    def test_small_doc_uses_min_height(self):
        from gui.chat_input_logic import compute_input_height
        h = compute_input_height(doc_height=10, line_spacing=20)
        assert h >= 48  # min_height

    def test_large_doc_capped_at_max_lines(self):
        from gui.chat_input_logic import compute_input_height
        max_h = 20 * 6 + 16  # line_spacing * max_lines + padding
        h = compute_input_height(doc_height=10000, line_spacing=20)
        assert h <= max_h

    def test_medium_doc(self):
        from gui.chat_input_logic import compute_input_height
        h = compute_input_height(doc_height=100, line_spacing=20)
        assert 48 <= h <= 20 * 6 + 16


class TestFormatToolLabel:
    """工具标签映射测试。"""

    def test_known_tools(self):
        from gui.chat_input_logic import format_tool_label
        assert "写入" in format_tool_label("write_file")
        assert "Git" in format_tool_label("git_commit")
        assert "Python" in format_tool_label("run_python")

    def test_unknown_tool_passthrough(self):
        from gui.chat_input_logic import format_tool_label
        assert format_tool_label("custom_tool") == "custom_tool"


class TestFormatAgentEventStatus:
    """Agent 事件状态栏格式化测试。"""

    def test_llm_start(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("llm_start", {"step": 3})
        assert "3" in result
        assert "思考" in result

    def test_tool_call(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("tool_call", {"name": "read_file", "arguments": {"path": "/x"}})
        assert "read_file" in result
        assert "🔧" in result

    def test_tool_done_ok(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("tool_done", {"name": "read_file", "ok": True})
        assert "✅" in result

    def test_tool_done_fail(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("tool_done", {"name": "read_file", "ok": False})
        assert "❌" in result

    def test_tool_denied(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("tool_denied", {"name": "write_file"})
        assert "⛔" in result

    def test_max_steps(self):
        from gui.chat_input_logic import format_agent_event_status
        result = format_agent_event_status("max_steps", {})
        assert "⚠️" in result

    def test_unknown_event_returns_none(self):
        from gui.chat_input_logic import format_agent_event_status
        assert format_agent_event_status("unknown_event", {}) is None


class TestIsAgentFinalEvent:
    """Agent 收尾事件判断测试。"""

    def test_final(self):
        from gui.chat_input_logic import is_agent_final_event
        assert is_agent_final_event("final") is True

    def test_max_steps(self):
        from gui.chat_input_logic import is_agent_final_event
        assert is_agent_final_event("max_steps") is True

    def test_tool_call_not_final(self):
        from gui.chat_input_logic import is_agent_final_event
        assert is_agent_final_event("tool_call") is False


class TestFilterCommandsByPrefix:
    """指令前缀过滤测试。"""

    def test_matching_prefix(self):
        from gui.chat_input_logic import filter_commands_by_prefix
        cmds = [
            {"name": "/help", "description": "帮助"},
            {"name": "/hello", "description": "问候"},
            {"name": "/world", "description": "世界"},
        ]
        result = filter_commands_by_prefix(cmds, "/hel")
        assert len(result) == 2

    def test_case_insensitive(self):
        from gui.chat_input_logic import filter_commands_by_prefix
        cmds = [{"name": "/Help", "description": "帮助"}]
        result = filter_commands_by_prefix(cmds, "/hel")
        assert len(result) == 1

    def test_no_match(self):
        from gui.chat_input_logic import filter_commands_by_prefix
        cmds = [{"name": "/help", "description": "帮助"}]
        result = filter_commands_by_prefix(cmds, "/xyz")
        assert len(result) == 0
