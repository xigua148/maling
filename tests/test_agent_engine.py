"""tests/test_agent_engine.py —— AgentEngine 测试。

覆盖：
- 工具循环基本流程（mock API）
- 流式 content chunk 回调
- 取消检查
- 最大步数限制
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestAgentEngineBasic:
    """AgentEngine 基本流程测试。"""

    def test_engine_creation(self, mock_cfg, logger):
        from agent_engine import AgentEngine
        from agent_tools import AgentTools
        from api import APIClient

        api = APIClient(mock_cfg, logger)
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(api, mock_cfg, logger, tools=tools)
        assert engine.max_steps == 8  # 默认值

    def test_engine_custom_max_steps(self, mock_cfg, logger):
        from agent_engine import AgentEngine
        from agent_tools import AgentTools
        from api import APIClient

        api = APIClient(mock_cfg, logger)
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(api, mock_cfg, logger, tools=tools, max_steps=3)
        assert engine.max_steps == 3

    def test_engine_on_content_chunk_callback(self, mock_cfg, logger):
        """v1.4.7: on_content_chunk 回调应被接受。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools
        from api import APIClient

        chunks = []
        api = APIClient(mock_cfg, logger)
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(
            api, mock_cfg, logger, tools=tools,
            on_content_chunk=lambda c: chunks.append(c),
        )
        assert engine.on_content_chunk is not None


class TestAgentEngineWithMockAPI:
    """使用 mock API 的引擎测试。"""

    def _make_engine(self, mock_cfg, logger, api_responses):
        """构造 engine + mock API。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        mock_api = MagicMock()
        # api_responses: list of (content, tool_calls) tuples
        call_count = [0]

        def mock_chat_stream_with_tools(messages, **kwargs):
            idx = min(call_count[0], len(api_responses) - 1)
            content, tool_calls = api_responses[idx]
            call_count[0] += 1
            mock_api._last_stream_tool_calls = tool_calls or []
            mock_api._last_stream_usage = None
            # yield content deltas
            if content:
                for word in content.split():
                    yield word + " "

        mock_api.chat_stream_with_tools = mock_chat_stream_with_tools
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(mock_api, mock_cfg, logger, tools=tools, max_steps=4)
        return engine

    def test_no_tool_calls_returns_content(self, mock_cfg, logger):
        """模型直接返回文本（无工具调用）。"""
        engine = self._make_engine(mock_cfg, logger, [
            ("你好主人，有什么可以帮你的？", []),
        ])
        result = engine.run("你是女仆码铃。", [], "你好")
        assert "你好主人" in result

    def test_tool_call_then_final_answer(self, mock_cfg, logger, tmp_workspace):
        """模型先调工具，再基于结果回答。"""
        # 第一步：模型请求 list_dir
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "list_dir",
                "arguments": json.dumps({"path": str(tmp_workspace)}),
            },
        }
        engine = self._make_engine(mock_cfg, logger, [
            ("", [tool_call]),  # 第一轮：调工具
            ("目录里有 hello.py 文件。", []),  # 第二轮：最终回答
        ])
        events = []
        engine.on_event = lambda ev, data: events.append(ev)
        result = engine.run("列出文件", [], "看看有什么文件")
        assert "hello.py" in result
        assert "tool_call" in events
        assert "tool_done" in events
        assert "final" in events

    def test_max_steps_limit(self, mock_cfg, logger):
        """超过 max_steps 应返回收敛提示。"""
        tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "list_dir",
                "arguments": json.dumps({"path": "."}),
            },
        }
        # 每轮都返回 tool_call，永远不到 final
        engine = self._make_engine(mock_cfg, logger, [
            ("", [tool_call]),
        ])
        result = engine.run("test", [], "test")
        assert "超过上限" in result or "收敛" in result

    def test_cancel_check(self, mock_cfg, logger):
        """cancel_check 返回 True 时应取消。"""
        engine = self._make_engine(mock_cfg, logger, [
            ("你好", []),
        ])
        engine.cancel_check = lambda: True
        result = engine.run("test", [], "test")
        assert "已取消" in result
