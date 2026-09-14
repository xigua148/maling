"""tests/test_pi_backend.py —— Pi 编程引擎试点（v1.7.2 T1/T2/T4）测试。

覆盖：
- T4 回归：AgentTools 授权白名单相对路径按 workspace 解析（cwd≠workspace）
- T1 单元：版本检测 / 环境注入（key 不落日志）/ 启动参数 / 事件映射
- T3 单元：ApiWorker 引擎分流（agent / pi 两路径）
- T1/T2 端到端（真实 pi 子进程 + 真实 API）：默认跳过，设 MALING_PI_E2E=1
  且本机装有 Pi 0.85.1、配置了 DeepSeek key 时启用（生命周期 / 门禁拒绝与允许）。
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pi_backend  # noqa: E402

PI_E2E = os.environ.get("MALING_PI_E2E") == "1"


# ======================================================================
# T4: cwd≠workspace 时相对路径按 workspace 解析（回归）
# ======================================================================
class TestWhitelistWorkspaceRelative:
    def test_write_file_relative_inside_workspace_with_mismatched_cwd(
            self, mock_cfg, logger, monkeypatch, tmp_path):
        """cwd 与 workspace 不同目录时，模型写 workspace 内相对路径不应被误拒。

        背景（docs/pi-eval-2026-09-09.md 步骤三）：旧实现 Path(path).resolve()
        相对进程 cwd 解析，headless 集成时触发 fail-safe 拒绝循环。
        """
        from agent_tools import AgentTools

        # workspace 设为 tmp_path/proj（深层目录），进程 cwd 留在 tmp_path（workspace 外）
        ws = tmp_path / "proj"
        ws.mkdir()
        mock_cfg.workspace = str(ws)
        monkeypatch.chdir(tmp_path)  # cwd ≠ cfg.workspace

        tools = AgentTools(mock_cfg, logger, confirm_fn=None)
        assert tools._in_whitelist("analyze.py") is True
        assert tools._in_whitelist("sub/dir/file.py") is True
        # workspace 外的相对路径（向上穿越）仍必须拒绝
        assert tools._in_whitelist("../outside.txt") is False
        # 绝对路径越界（cwd 侧文件）仍必须拒绝
        assert tools._in_whitelist(str(tmp_path / "evil.py")) is False

        result = tools.execute("write_file", {"path": "analyze.py",
                                              "content": "print(1)"})
        payload = json.loads(result)
        assert payload.get("status") == "ok"
        assert (ws / "analyze.py").exists()

    def test_gui_mode_unchanged(self, mock_cfg, logger, tmp_workspace,
                                monkeypatch):
        """GUI 运行态（cwd==workspace）行为不变（回归守卫）。"""
        from agent_tools import AgentTools

        monkeypatch.chdir(tmp_workspace)
        tools = AgentTools(mock_cfg, logger, confirm_fn=None)
        assert tools._in_whitelist("hello.py") is True


# ======================================================================
# T1: pi_backend 单元
# ======================================================================
class TestPiVersionAndEnv:
    def test_version_ok(self):
        with patch("pi_backend.subprocess.run") as run:
            run.return_value = MagicMock(stdout="0.85.1\n", returncode=0)
            ok, info = pi_backend.check_pi_version(["pi"])
        assert ok and info == "0.85.1"

    def test_version_mismatch_guides_install(self):
        with patch("pi_backend.subprocess.run") as run:
            run.return_value = MagicMock(stdout="0.99.0\n", returncode=0)
            ok, info = pi_backend.check_pi_version(["pi"])
        assert not ok
        assert "0.85.1" in info and "npm install" in info

    def test_version_missing_output(self):
        with patch("pi_backend.subprocess.run") as run:
            run.return_value = MagicMock(stdout="", returncode=0)
            ok, info = pi_backend.check_pi_version(["pi"])
        assert not ok

    def test_build_env_injects_key_without_leaking(self, mock_cfg):
        """key 只进环境变量；环境字典不得出现在日志（此处校验注入正确性）。"""
        session = pi_backend.PiRpcSession(mock_cfg, workspace=".")
        env = session._build_env()
        assert env["DEEPSEEK_API_KEY"] == "sk-test-key"
        assert env["MALING_GATE_WORKSPACE"] == "."
        assert env["PI_SKIP_VERSION_CHECK"] == "1"
        assert env["PI_OFFLINE"] == "1"

    def test_build_env_rejects_non_deepseek(self, mock_cfg):
        mock_cfg.api_provider = "openai"
        session = pi_backend.PiRpcSession(mock_cfg, workspace=".")
        with pytest.raises(RuntimeError, match="DeepSeek"):
            session._build_env()

    def test_build_args_pins_gate_and_version_flags(self, mock_cfg):
        session = pi_backend.PiRpcSession(mock_cfg, workspace=".")
        session._launch = (["C:/fake/pi.cmd"], "test")
        args = session._build_args()
        assert "--mode" in args and "rpc" in args
        assert str(pi_backend.GATE_PATH) in args          # 门禁固定加载
        assert "--no-extensions" in args                  # 禁其它发现机制
        assert mock_cfg.api_model in args                 # 与码铃同模型

    def test_build_args_bundled_prefix(self, mock_cfg):
        """内置 runtime 时启动前缀 = node.exe + cli.js。"""
        session = pi_backend.PiRpcSession(mock_cfg, workspace=".")
        session._launch = (["C:/rt/node.exe", "C:/rt/cli.js"], "内置 runtime")
        args = session._build_args()
        assert args[:2] == ["C:/rt/node.exe", "C:/rt/cli.js"]
        assert "--mode" in args


class TestBundledRuntimePriority:
    """v1.7.3: 内置 runtime 优先于系统 PATH。"""

    def _fake_bundled(self, tmp_path, monkeypatch):
        base = tmp_path / "pi_runtime"
        pkg = base / "node_modules" / "@earendil-works" / "pi-coding-agent"
        (pkg / "dist" / "bundle").mkdir(parents=True)
        (base / "node.exe").write_text("node")
        (pkg / "dist" / "bundle" / "cli.js").write_text("//cli")
        monkeypatch.setattr(pi_backend, "_bundled_runtime_dirs",
                            lambda: [base])
        return base

    def test_bundled_wins_over_path(self, tmp_path, monkeypatch):
        self._fake_bundled(tmp_path, monkeypatch)
        monkeypatch.setattr(pi_backend.shutil, "which", lambda name: "C:/sys/pi.cmd")
        prefix, desc = pi_backend.resolve_pi_launch()
        assert prefix[0].endswith("node.exe")
        assert "node_modules" in prefix[1]
        assert "内置" in desc

    def test_falls_back_to_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pi_backend, "_bundled_runtime_dirs", lambda: [])
        monkeypatch.setattr(pi_backend.shutil, "which", lambda name: "C:/sys/pi.cmd")
        prefix, desc = pi_backend.resolve_pi_launch()
        assert prefix == ["C:/sys/pi.cmd"]

    def test_neither_found_raises_with_guidance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pi_backend, "_bundled_runtime_dirs", lambda: [])
        monkeypatch.setattr(pi_backend.shutil, "which", lambda name: None)
        with pytest.raises(RuntimeError, match="pi_runtime"):
            pi_backend.resolve_pi_launch()

    def test_incomplete_bundled_falls_back(self, tmp_path, monkeypatch):
        """缺 cli.js 的残缺内置目录不得命中（须完整 node.exe + cli.js）。"""
        base = tmp_path / "pi_runtime"
        base.mkdir()
        (base / "node.exe").write_text("node")  # 缺 cli.js
        monkeypatch.setattr(pi_backend, "_bundled_runtime_dirs",
                            lambda: [base])
        monkeypatch.setattr(pi_backend.shutil, "which", lambda name: "C:/sys/pi.cmd")
        prefix, desc = pi_backend.resolve_pi_launch()
        assert prefix == ["C:/sys/pi.cmd"]

    def test_gate_file_exists(self):
        assert pi_backend.GATE_PATH.exists()


class TestMapRpcEvent:
    def _state(self):
        return {"usage": {"input": 0, "output": 0, "cacheRead": 0,
                          "cacheWrite": 0}}

    def test_text_delta_maps_to_chunk(self):
        chunks = []
        state = self._state()
        pi_backend.map_rpc_event(
            {"type": "message_update",
             "assistantMessageEvent": {"type": "text_delta", "delta": "你好"}},
            chunks.append, lambda *a: None, lambda *a: None, state)
        assert chunks == ["你好"]

    def test_tool_events_map_to_maling_semantics(self):
        calls, dones = [], []
        state = self._state()
        pi_backend.map_rpc_event(
            {"type": "tool_execution_start", "toolName": "read",
             "args": {"path": "a.txt"}},
            lambda *_: None, lambda n, d: calls.append(d), lambda *a: None, state)
        pi_backend.map_rpc_event(
            {"type": "tool_execution_end", "toolName": "read", "isError": False,
             "result": {"content": [{"type": "text", "text": "内容"}]}},
            lambda *_: None, lambda *a: None, lambda n, d: dones.append(d), state)
        assert calls[0]["name"] == "read"
        assert dones[0]["ok"] is True and dones[0]["summary"] == "内容"

    def test_final_text_and_usage_accumulate(self):
        state = self._state()
        chunks = []
        ev = {"type": "message_end",
              "message": {"role": "assistant", "stopReason": "stop",
                          "content": [{"type": "text", "text": "完成"}],
                          "usage": {"input": 10, "output": 5,
                                    "cacheRead": 3, "cacheWrite": 0}}}
        pi_backend.map_rpc_event(ev, chunks.append, lambda *a: None,
                                 lambda *a: None, state)
        assert state["final_text"] == "完成"
        assert state["usage"] == {"input": 10, "output": 5,
                                  "cacheRead": 3, "cacheWrite": 0}
        ev2 = json.loads(json.dumps(ev))
        ev2["message"]["usage"]["input"] = 7
        pi_backend.map_rpc_event(ev2, chunks.append, lambda *a: None,
                                 lambda *a: None, state)
        assert state["usage"]["input"] == 17  # 跨轮累计


# ======================================================================
# T3: ApiWorker 引擎分流
# ======================================================================
class TestEngineDispatch:
    def _worker(self, coding_engine):
        from gui.chat_service import ApiWorker
        app_ctx = MagicMock()
        app_ctx.config = MagicMock(coding_engine=coding_engine)
        app_ctx.cfg = MagicMock(api_provider="deepseek", api_key="sk-x")
        # 走真实构造器（初始化 QObject 信号），api 用 MagicMock 不发网络请求
        worker = ApiWorker(api=MagicMock(), messages=[],
                           task_config={"task_type": "agent",
                                        "user_text": "写个脚本"},
                           app_ctx=app_ctx)
        return worker

    def test_pi_engine_routes_to_pi_backend(self, monkeypatch):
        worker = self._worker("pi")
        hit = {}
        monkeypatch.setattr(worker, "_run_pi_agent",
                            lambda: hit.setdefault("engine", "pi"))
        monkeypatch.setattr(worker, "_run_agent",
                            lambda: hit.setdefault("engine", "agent"))
        worker.thinking_indicator.emit(True)
        worker.run()
        assert hit["engine"] == "pi"

    def test_default_engine_keeps_builtin(self, monkeypatch):
        worker = self._worker("agent")
        hit = {}
        monkeypatch.setattr(worker, "_run_pi_agent",
                            lambda: hit.setdefault("engine", "pi"))
        monkeypatch.setattr(worker, "_run_agent",
                            lambda: hit.setdefault("engine", "agent"))
        worker.thinking_indicator.emit(True)
        worker.run()
        assert hit["engine"] == "agent"


# ======================================================================
# T1/T2 端到端（真实子进程 + 真实 API；默认跳过）
# ======================================================================
def _real_cfg():
    """从码铃开发副本 gui/config.yaml 读取真实 AppConfig（key 不打印）。"""
    from core import AppConfig
    cfg = AppConfig.load(ROOT / "gui" / "config.yaml")
    cfg.agent_max_steps = 12
    return cfg


def _load_key_from_gui_config() -> str:
    import re
    text = (ROOT / "gui" / "config.yaml").read_text(encoding="utf-8")
    m = re.search(r"key:\s*['\"]?([^'\"\n]+)", text)
    return (m.group(1).strip() if m else "")


requires_pi_e2e = pytest.mark.skipif(
    not PI_E2E, reason="端到端用例需 MALING_PI_E2E=1 + 本机 Pi 0.85.1 + DeepSeek key")


@pytest.mark.usefixtures("tmp_workspace")
class TestPiEndToEnd:
    @requires_pi_e2e
    def test_lifecycle_prompt_and_tool(self, tmp_workspace, logger):
        """T1 生命周期：启动 → 纯对话（流式）→ 工具调用 → 停止。"""
        cfg = _real_cfg()
        cfg.workspace = str(tmp_workspace)
        chunks, tools = [], []
        session = pi_backend.PiRpcSession(
            cfg, workspace=str(tmp_workspace),
            confirm_fn=lambda desc, tool: True,  # 生命周期测试不测门禁，确认一律放行
            on_chunk=chunks.append,
            on_tool_call=lambda n, d: tools.append(("call", n)),
            on_tool_done=lambda n, d: tools.append(("done", n)),
        )
        try:
            session.start()
            assert session.is_alive()
            result = session.prompt(
                f"请在当前目录创建 note.txt（内容为 MALING_PI_OK），"
                f"然后用 read 工具读回并告诉我内容。",
                cancel_check=lambda: False)
            assert result["stop_reason"] == "stop"
            assert "MALING_PI_OK" in result["text"]
            assert len(tools) >= 2  # 至少一次工具调用 + 一次工具完成
            assert result["usage"]["output"] > 0
        finally:
            session.stop()
        assert not session.is_alive()

    @requires_pi_e2e
    def test_abort(self, tmp_workspace):
        """T1 停止：流式中途 abort → stopReason=aborted。"""
        cfg = _real_cfg()
        cfg.workspace = str(tmp_workspace)
        session = pi_backend.PiRpcSession(
            cfg, workspace=str(tmp_workspace),
            confirm_fn=lambda desc, tool: True,
            on_chunk=lambda chunk: stopped["chunks"].append(chunk))
        try:
            session.start()
            stopped = {"flag": False, "chunks": []}

            def cancel():
                if len(stopped["chunks"]) >= 5:
                    stopped["flag"] = True
                return stopped["flag"]

            result = session.prompt(
                "请写一篇 3000 字的中国古代建筑史文章，直接写正文。",
                cancel_check=cancel)
            assert result["aborted"] is True
        finally:
            session.stop()

    @requires_pi_e2e
    def test_bundled_runtime_e2e_no_system_pi(self, tmp_workspace, monkeypatch):
        """T1 打包态模拟：禁用系统 PATH 中的 node/pi，仅靠内置 runtime 完成任务。

        证明分发用户无需 npm install——PATH 被隔离后 shutil.which("pi") 必然
        miss，resolve_pi_launch 只能命中 _internal/pi_runtime。
        """
        bundled = pi_backend.find_bundled_pi_runtime()
        if bundled is None:
            pytest.skip("本机未收集 _internal/pi_runtime（先跑 copy_pi_runtime.py）")
        cfg = _real_cfg()
        cfg.workspace = str(tmp_workspace)
        # 隔离 PATH：只留系统目录（node/pi 都不在其中）→ 系统安装不可达
        monkeypatch.setenv("PATH", os.pathsep.join([
            r"C:\Windows\System32", r"C:\Windows"]))
        assert pi_backend.find_pi_executable() is None, "PATH 隔离失败"
        prefix, desc = pi_backend.resolve_pi_launch()
        assert "node.exe" in prefix[0] and "内置" in desc

        chunks, tools = [], []
        session = pi_backend.PiRpcSession(
            cfg, workspace=str(tmp_workspace),
            on_chunk=chunks.append,
            on_tool_call=lambda n, d: tools.append(("call", n)),
            on_tool_done=lambda n, d: tools.append(("done", n)),
        )
        try:
            session.start()
            result = session.prompt(
                "在当前目录创建 bundled.txt（内容 BUNDLED_OK），用 read 读回并告诉我内容。",
                cancel_check=lambda: False)
            assert result["stop_reason"] == "stop"
            assert "BUNDLED_OK" in result["text"]
            assert len(tools) >= 2
            assert len(chunks) > 0  # 流式 chunk 真实到达
        finally:
            session.stop()

    @requires_pi_e2e
    def test_gate_deny_and_allow(self, tmp_workspace, logger):
        """T2 门禁端到端：越界写路径弹 confirm，拒绝→block、允许→执行。"""
        cfg = _real_cfg()
        cfg.workspace = str(tmp_workspace)
        outside = Path(str(tmp_workspace)) / ".." / "gate_outside_target.txt"

        def make_confirm(allow):
            return lambda desc, tool: allow

        def run_task(allow: bool) -> dict:
            session = pi_backend.PiRpcSession(
                cfg, workspace=str(tmp_workspace),
                confirm_fn=make_confirm(allow))
            try:
                session.start()
                outside.unlink(missing_ok=True)
                return session.prompt(
                    f"请用 write 工具把文件 \"{outside.resolve()}\" 的内容写成 GATE_E2E，"
                    "完成后只回复 done。", cancel_check=lambda: False)
            finally:
                session.stop()

        # 拒绝：工具被 block，目标文件不得产生
        denied = run_task(False)
        assert not outside.resolve().exists(), "拒绝后越界文件不应被写入"
        assert "done" not in denied["text"].lower() or "拒绝" in denied["text"] or \
            denied.get("stop_reason") == "stop"

        # 允许：确认后正常执行
        allowed = run_task(True)
        assert outside.resolve().exists(), "允许后越界文件应被写入"
        assert "GATE_E2E" in outside.resolve().read_text(encoding="utf-8")
