"""tests/test_integration.py —— 集成测试。

覆盖：
- Agent 引擎 + 工具链端到端流程（mock API）
- 多轮工具调用 → 最终回答
- 错误恢复（工具失败 → 引擎自纠）
- 流式 content chunk 传递
- 配置校验 → 引擎启动完整链路
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


class TestAgentEngineIntegration:
    """Agent 引擎 + 工具链集成测试。"""

    def _make_mock_api(self, responses):
        """构造 mock API，按顺序返回 responses。"""
        mock_api = MagicMock()
        call_count = [0]

        def mock_chat_stream_with_tools(messages, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            content, tool_calls = responses[idx]
            call_count[0] += 1
            mock_api._last_stream_tool_calls = tool_calls or []
            mock_api._last_stream_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
            if content:
                for word in content.split():
                    yield word + " "

        mock_api.chat_stream_with_tools = mock_chat_stream_with_tools
        return mock_api

    def test_full_loop_read_then_answer(self, mock_cfg, logger, tmp_workspace):
        """完整流程：模型调 read_file → 读结果 → 给出回答。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        # 准备测试文件
        test_file = tmp_workspace / "greeting.txt"
        test_file.write_text("你好世界", encoding="utf-8")

        tool_call = {
            "id": "call_1", "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": str(test_file)}),
            }
        }
        mock_api = self._make_mock_api([
            ("", [tool_call]),
            ("文件内容是 你好世界。", []),
        ])
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(mock_api, mock_cfg, logger, tools=tools, max_steps=4)

        result = engine.run("你是助手。", [], "读一下 greeting.txt")
        assert "你好世界" in result

    def test_multi_tool_calls_sequential(self, mock_cfg, logger, tmp_workspace):
        """多步工具调用：list_dir → read_file → 回答。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        (tmp_workspace / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_workspace / "b.txt").write_text("bbb", encoding="utf-8")

        call_list_dir = {
            "id": "call_1", "type": "function",
            "function": {
                "name": "list_dir",
                "arguments": json.dumps({"path": str(tmp_workspace)}),
            }
        }
        call_read_file = {
            "id": "call_2", "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": str(tmp_workspace / "a.txt")}),
            }
        }
        mock_api = self._make_mock_api([
            ("", [call_list_dir]),
            ("", [call_read_file]),
            ("目录里有 a.txt 和 b.txt，a.txt 内容是 aaa。", []),
        ])
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(mock_api, mock_cfg, logger, tools=tools, max_steps=6)

        events = []
        engine.on_event = lambda ev, data: events.append(ev)
        result = engine.run("助手", [], "看看目录和 a.txt")
        assert "a.txt" in result
        assert "aaa" in result
        assert events.count("tool_call") == 2
        assert events.count("tool_done") == 2

    def test_tool_error_recovery(self, mock_cfg, logger):
        """工具执行失败后引擎继续（模型重新尝试）。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        # 第一次调用不存在的文件 → 失败；第二次调用存在的文件 → 成功
        call_bad = {
            "id": "call_1", "type": "function",
            "function": {
                "name": "read_file",
                "arguments": json.dumps({"path": "/nonexistent/file.txt"}),
            }
        }
        call_good = {
            "id": "call_2", "type": "function",
            "function": {
                "name": "list_dir",
                "arguments": json.dumps({"path": "."}),
            }
        }
        mock_api = self._make_mock_api([
            ("", [call_bad]),
            ("", [call_good]),
            ("文件不存在，但目录列表已获取。", []),
        ])
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(mock_api, mock_cfg, logger, tools=tools, max_steps=6)
        result = engine.run("助手", [], "读文件")
        assert "目录列表" in result or "获取" in result

    def test_streaming_content_chunks(self, mock_cfg, logger):
        """流式 content chunk 应被实时推送。"""
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        chunks_received = []
        mock_api = self._make_mock_api([
            ("你好 主人 有什么 可以 帮你的", []),
        ])
        tools = AgentTools(mock_cfg, logger)
        engine = AgentEngine(
            mock_api, mock_cfg, logger, tools=tools,
            on_content_chunk=lambda c: chunks_received.append(c),
        )
        result = engine.run("助手", [], "你好")
        assert len(chunks_received) > 0
        assert "你好" in result

    def test_config_validation_integration(self, tmp_path, logger):
        """配置校验 → 引擎启动完整链路。"""
        from core import AppConfig
        from agent_tools import AgentTools
        from agent_engine import AgentEngine
        from api import APIClient

        cfg = AppConfig(str(tmp_path))
        cfg.api_key = "sk-test"
        cfg.workspace = str(tmp_path)

        warnings = cfg.validate()
        api_warnings = [w for w in warnings if "API Key" in w]
        assert len(api_warnings) == 0  # 有 key 不应报警

        api = APIClient(cfg, logger)
        tools = AgentTools(cfg, logger)
        engine = AgentEngine(api, cfg, logger, tools=tools)
        assert engine.max_steps > 0


class TestToolChainIntegration:
    """工具链协作测试。"""

    def test_write_then_read(self, mock_cfg, logger, tmp_workspace):
        """write_file → read_file 闭环。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        target = str(tmp_workspace / "test_rt.txt")
        r1 = tools.execute("write_file", {"path": target, "content": "hello integration"})
        assert json.loads(r1)["status"] == "ok"
        r2 = tools.execute("read_file", {"path": target})
        assert "hello integration" in r2

    def test_file_search_after_write(self, mock_cfg, logger, tmp_workspace):
        """write_file → file_search 闭环。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        target = str(tmp_workspace / "searchable.txt")
        tools.execute("write_file", {"path": target, "content": "line1\nfoobar\nline3"})
        r = tools.execute("file_search", {"path": target, "pattern": "foobar"})
        parsed = json.loads(r)
        assert parsed["status"] == "ok"
        assert "L2" in parsed["message"]

    def test_math_then_validate(self, mock_cfg, logger):
        """math_eval → validate_json 闭环。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        r1 = tools.execute("math_eval", {"expression": "2**10"})
        parsed = json.loads(r1)
        assert parsed["result"] == 1024
        # 用 validate_json 验证 math_eval 返回的是合法 JSON
        r2 = tools.execute("validate_json", {"text": r1})
        assert json.loads(r2)["status"] == "ok"

    def test_system_info_and_datetime(self, mock_cfg, logger):
        """system_info + get_datetime 联动。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        r1 = tools.execute("system_info", {})
        r2 = tools.execute("get_datetime", {})
        p1 = json.loads(r1)
        p2 = json.loads(r2)
        assert p1["status"] == "ok"
        assert p2["status"] == "ok"
        assert "os" in p1
        assert "datetime" in p2


class TestAPIKeyRotationIntegration:
    """API Key 轮换集成测试。"""

    def test_rotator_with_client(self, mock_cfg, logger):
        """APIKeyRotator 与 APIClient 集成。"""
        from api import APIClient, APIKeyRotator
        rotator = APIKeyRotator(["sk-key1", "sk-key2"])
        mock_cfg.api_keys = ["sk-key1", "sk-key2"]
        client = APIClient(mock_cfg, logger)
        # 客户端应使用 rotator 的当前 key
        headers = client._headers()
        assert "Authorization" in headers
