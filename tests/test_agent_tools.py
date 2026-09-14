"""tests/test_agent_tools.py —— Agent 工具系统测试。

覆盖：
- 工具注册与 schema 生成
- L0/L1 授权逻辑（Fix 5: 安全白名单统一）
- 工具执行与错误处理
- workspace 白名单判定
"""
import json
import pytest
from unittest.mock import MagicMock


class TestAgentToolsRegistration:
    """工具注册测试。"""

    def test_builtin_tools_registered(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        names = tools.names()
        assert "read_file" in names
        assert "write_file" in names
        assert "list_dir" in names
        assert "run_python" in names
        assert "run_command" in names
        assert "web_search" in names
        assert "git_status" in names
        assert "git_diff" in names
        assert "git_commit" in names

    def test_schemas_return_valid_openai_format(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        schemas = tools.schemas()
        assert len(schemas) > 0
        for s in schemas:
            assert s["type"] == "function"
            assert "function" in s
            fn = s["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_tool_count_at_least_25(self, mock_cfg, logger):
        """v1.4.8: 工具生态扩充到 25+ 个。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        assert len(tools.names()) >= 25


class TestAgentToolsAuthorization:
    """授权逻辑测试。"""

    def test_l0_tools_auto_pass(self, mock_cfg, logger):
        """L0 只读工具不需要授权。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=None)
        # read_file 是 L0，execute 不应走授权
        result = tools.execute("list_dir", {"path": "."})
        parsed = json.loads(result)
        # list_dir 是 L0，不会返回 denied
        assert parsed["status"] != "denied"

    def test_l1_tools_denied_without_confirm(self, mock_cfg, logger, tmp_workspace):
        """L1 修改工具在无 confirm_fn 且目标不在 workspace 时应被拒绝。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=None)
        # write_file 到 workspace 外的路径
        result = tools.execute("write_file", {
            "path": "C:/Windows/System32/test.txt",
            "content": "test"
        })
        parsed = json.loads(result)
        assert parsed["status"] == "denied"

    def test_l1_tools_allowed_in_workspace(self, mock_cfg, logger, tmp_workspace):
        """L1 修改工具在 workspace 内应自动放行。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=None)
        target = str(tmp_workspace / "new_file.txt")
        result = tools.execute("write_file", {
            "path": target,
            "content": "hello world"
        })
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_l1_tools_confirm_fn_called(self, mock_cfg, logger):
        """L1 工具在 workspace 外应调用 confirm_fn。"""
        from agent_tools import AgentTools
        confirm_called = []

        def mock_confirm(desc, tool_name):
            confirm_called.append((desc, tool_name))
            return True  # 模拟用户同意

        tools = AgentTools(mock_cfg, logger, confirm_fn=mock_confirm)
        result = tools.execute("write_file", {
            "path": "C:/outside/workspace.txt",
            "content": "test"
        })
        assert len(confirm_called) == 1
        assert confirm_called[0][1] == "write_file"

    def test_session_authorization_reset(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        tools._session_authorized = True
        tools.reset_session_authorization()
        assert tools._session_authorized is False


class TestAgentToolsExecution:
    """工具执行测试。"""

    def test_unknown_tool_returns_error(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("nonexistent_tool", {})
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "未知工具" in parsed["message"]

    def test_list_dir_existing目录(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("list_dir", {"path": str(tmp_workspace)})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "hello.py" in parsed["message"]

    def test_list_dir_不存在(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("list_dir", {"path": "/nonexistent/path"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_run_python_sandbox(self, mock_cfg, logger):
        from agent_tools import AgentTools
        # run_python 是 L1，需要 confirm_fn 或 workspace 内路径
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        result = tools.execute("run_python", {"code": "print(1 + 1)"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "2" in parsed["message"]

    def test_run_python_blocks_import_os(self, mock_cfg, logger):
        """沙箱应阻止 os.system 等危险调用。"""
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        result = tools.execute("run_python", {"code": "import os; os.system('echo hacked')"})
        parsed = json.loads(result)
        assert parsed["status"] == "error"


class TestNewTools:
    """v1.4.8 新增工具测试。"""

    def test_file_search(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("file_search", {"path": str(tmp_workspace / "hello.py"), "pattern": "hello"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "L1" in parsed["message"]

    def test_file_info(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("file_info", {"path": str(tmp_workspace / "hello.py")})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "size_bytes" in parsed

    def test_hash_file(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("hash_file", {"path": str(tmp_workspace / "hello.py")})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "hash" in parsed

    def test_system_info(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("system_info", {})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "os" in parsed
        assert "python_version" in parsed

    def test_get_datetime(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("get_datetime", {})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "datetime" in parsed

    def test_count_text(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("count_text", {"text": "hello world\nthis is a test"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["lines"] == 2
        assert parsed["words"] == 6

    def test_validate_json_valid(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("validate_json", {"text": '{"key": "value"}'})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_validate_json_invalid(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("validate_json", {"text": '{invalid json'})
        parsed = json.loads(result)
        assert parsed["status"] == "error"

    def test_validate_yaml(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("validate_yaml", {"text": "name: test\nversion: 1.0"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_math_eval(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        result = tools.execute("math_eval", {"expression": "2**10 + 3*4"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert parsed["result"] == 1036

    def test_env_var(self, mock_cfg, logger):
        from agent_tools import AgentTools
        import os
        tools = AgentTools(mock_cfg, logger)
        # PATH 环境变量应该存在
        result = tools.execute("env_var", {"name": "PATH"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"

    def test_file_append(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        target = str(tmp_workspace / "append_test.txt")
        tools.execute("write_file", {"path": target, "content": "line1\n"})
        result = tools.execute("file_append", {"path": target, "content": "line2\n"})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        from pathlib import Path
        content = Path(target).read_text(encoding="utf-8")
        assert "line1" in content
        assert "line2" in content

    def test_file_move(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        from pathlib import Path
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        src = str(tmp_workspace / "move_src.txt")
        dst = str(tmp_workspace / "move_dst.txt")
        Path(src).write_text("test", encoding="utf-8")
        result = tools.execute("file_move", {"src": src, "dst": dst})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert Path(dst).exists()
        assert not Path(src).exists()

    def test_file_delete(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        from pathlib import Path
        tools = AgentTools(mock_cfg, logger, confirm_fn=lambda d, t: True)
        target = str(tmp_workspace / "delete_me.txt")
        Path(target).write_text("test", encoding="utf-8")
        result = tools.execute("file_delete", {"path": target})
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert not Path(target).exists()


class TestWhitelist:
    """workspace 白名单判定测试。"""

    def test_path_in_workspace(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        assert tools._in_whitelist(str(tmp_workspace / "file.txt"))

    def test_path_outside_workspace(self, mock_cfg, logger):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        assert not tools._in_whitelist("C:/Windows/System32/file.txt")

    def test_subdirectory_in_workspace(self, mock_cfg, logger, tmp_workspace):
        from agent_tools import AgentTools
        tools = AgentTools(mock_cfg, logger)
        sub = tmp_workspace / "a" / "b" / "c"
        assert tools._in_whitelist(str(sub / "file.txt"))
