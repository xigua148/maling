"""tests/test_chat_stream_state.py —— 流式输出状态管理测试。"""
import pytest


class TestStreamState:
    """StreamState 状态机测试。"""

    def test_initial_state(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        assert s.buffer == ""
        assert s.is_streaming is False
        assert s.bubble_created is False
        assert s.needs_new_bubble is False

    def test_start(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        assert s.is_streaming is True
        assert s.buffer == ""
        assert s.activity == "thinking"
        assert s.needs_new_bubble is True

    def test_append_chunk(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        s.append_chunk("hello ")
        s.append_chunk("world")
        assert s.buffer == "hello world"

    def test_mark_bubble_created(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        assert s.needs_new_bubble is True
        s.mark_bubble_created()
        assert s.bubble_created is True
        assert s.needs_new_bubble is False

    def test_finish(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        s.append_chunk("test")
        usage = s.finish({"total_tokens": 100})
        assert s.is_streaming is False
        assert s.bubble_created is False
        assert s.activity is None
        assert usage["total_tokens"] == 100

    def test_cancel(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        s.cancel()
        assert s.is_streaming is False
        assert s.activity is None

    def test_fail(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        s.fail()
        assert s.is_streaming is False

    def test_agent_trace_lifecycle(self):
        from gui.chat_stream_state import StreamState
        s = StreamState()
        assert s.is_agent_tracing is False
        s.start_agent_trace()
        assert s.is_agent_tracing is True
        s.end_agent_trace()
        assert s.is_agent_tracing is False

    def test_full_lifecycle(self):
        """完整流式生命周期。"""
        from gui.chat_stream_state import StreamState
        s = StreamState()
        # 开始
        s.start()
        assert s.needs_new_bubble is True
        # 首个 chunk → 创建气泡
        s.append_chunk("Hello")
        s.mark_bubble_created()
        assert s.needs_new_bubble is False
        # 后续 chunks
        s.append_chunk(" World")
        assert s.buffer == "Hello World"
        # 结束
        usage = s.finish({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert usage["total_tokens"] == 15
        assert s.is_streaming is False


class TestComputeStreamInsertIndex:
    """流式气泡插入索引测试。"""

    def test_normal_case(self):
        from gui.chat_stream_state import compute_stream_insert_index
        assert compute_stream_insert_index(10) == 8  # 10-2

    def test_one_item(self):
        from gui.chat_stream_state import compute_stream_insert_index
        assert compute_stream_insert_index(1) == 0  # max(0, -1) → 0

    def test_two_items(self):
        from gui.chat_stream_state import compute_stream_insert_index
        assert compute_stream_insert_index(2) == 0  # 2-2=0

    def test_empty(self):
        from gui.chat_stream_state import compute_stream_insert_index
        assert compute_stream_insert_index(0) == 0


class TestFormatUsageSummary:
    """用量摘要格式化测试。"""

    def test_empty_usage(self):
        from gui.chat_stream_state import format_usage_summary
        assert format_usage_summary({}) == "无用量数据"

    def test_with_tokens(self):
        from gui.chat_stream_state import format_usage_summary
        result = format_usage_summary({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
        assert "10" in result
        assert "5" in result
        assert "15" in result

    def test_cancelled(self):
        from gui.chat_stream_state import format_usage_summary
        result = format_usage_summary({"cancelled": True})
        assert "已取消" in result

    def test_none_usage(self):
        from gui.chat_stream_state import format_usage_summary
        assert format_usage_summary(None) == "无用量数据"
