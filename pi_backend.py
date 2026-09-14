"""pi_backend.py —— Pi 编程引擎试点后端（v1.7.2 T1）。

把 earendil-works/pi（coding-agent v0.85.1，RPC 模式）作为码铃"编程引擎"的
可选执行内核：JSONL stdin/stdout 子进程 + 事件流映射 + 授权桥。

设计要点（对齐 docs/pi-eval-2026-09-09.md 实测结论）：
- 版本锁定 Pi 0.85.1（启动时检测，不符报错引导安装，防 RPC 协议漂移）；
- 模型接入：复用码铃 AppConfig（试点仅支持 DeepSeek provider），API key 只经
  环境变量注入子进程，绝不写日志/落盘（红线 R-K）；
- 门禁：启动参数固定携带 `-e pi_gateway/maling_gate.js` + MALING_GATE_WORKSPACE
  环境变量，授权确认经 confirm_fn 桥接到 GUI 授权弹窗（复用 ChatService 的
  agent_authorization_requested 机制），拒绝/超时/无渠道一律 fail-safe；
- 事件映射：message_update(text_delta) → 流式 chunk；tool_execution_start/end →
  码铃 EVT_TOOL_CALL / EVT_TOOL_DONE；agent_settled → 任务完成（usage 汇总）；
- 进程生命周期：启动握手 20s 超时；prompt 期间崩溃自动重启 1 次并重发任务。
- managed 任务（C3 规划 / C2 自愈 / 断点恢复）本期仍走内置 AgentEngine，
  Pi 无对应物——试点范围明确排除（UI 已注明）。
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("maid_coder.pi_backend")

# ---- 版本锁定（docs/pi-eval-2026-09-09.md：RPC 协议随版本可能变化）----
PI_REQUIRED_VERSION = "0.85.1"
PI_PACKAGE = "@earendil-works/pi-coding-agent"
PI_INSTALL_HINT = (
    f"未检测到可用的 Pi {PI_REQUIRED_VERSION} 运行时。"
    "分发包应自带 _internal/pi_runtime（node.exe + pi 依赖树）；"
    "若缺失，可手工安装：\n"
    f"  npm install -g --ignore-scripts @earendil-works/pi-coding-agent@{PI_REQUIRED_VERSION}\n"
    "或重新运行 copy_pi_runtime.py 收集内置运行时。"
)

# 启动后等待 RPC 应答的上限（秒）
STARTUP_TIMEOUT_S = 20.0
# prompt 泵单次 get 阻塞（秒）——轮询取消/停止的最小粒度
PUMP_TICK_S = 0.2
# 进程崩溃后自动重启次数上限（评测结论：重启 1 次）
MAX_RESTARTS = 1

GATE_PATH = Path(__file__).resolve().parent / "pi_gateway" / "maling_gate.js"


# ----------------------------------------------------------------------
# 定位与版本检测
# ----------------------------------------------------------------------
def _bundled_runtime_dirs() -> List[Path]:
    """内置 runtime 的候选目录（按优先序）：
    - 打包态：pi_backend 位于 <app>/_internal/ → _internal/pi_runtime
    - 源码态：<repo>/_internal/pi_runtime
    """
    here = Path(__file__).resolve().parent
    return [here / "pi_runtime", here / "_internal" / "pi_runtime"]


def find_bundled_pi_runtime() -> Optional[Tuple[Path, Path]]:
    """定位内置 runtime，返回 (node.exe, cli.js)；无则 None。"""
    for base in _bundled_runtime_dirs():
        node_exe = base / "node.exe"
        cli_js = base / "node_modules" / PI_PACKAGE / "dist" / "bundle" / "cli.js"
        if node_exe.exists() and cli_js.exists():
            return node_exe, cli_js
    return None


def find_pi_executable() -> Optional[str]:
    """在 PATH 中定位 pi（Windows 为 pi.cmd shim，PATHEXT 自动解析）。"""
    return shutil.which("pi") or shutil.which("pi.cmd") or shutil.which("pi.exe")


def resolve_pi_launch() -> Tuple[List[str], str]:
    """解析 Pi 启动前缀（v1.7.3 路径优先级）：
    ① 内置 _internal/pi_runtime（node.exe + cli.js）—— 分发包开箱即用；
    ② 系统 PATH 的 pi.cmd —— 向后兼容已自装用户；
    ③ 都没有 → 抛错引导。
    返回 (启动前缀参数列表, 供日志/提示的描述)。
    """
    bundled = find_bundled_pi_runtime()
    if bundled is not None:
        node_exe, cli_js = bundled
        return [str(node_exe), str(cli_js)], f"内置 runtime: {node_exe.parent}"
    pi_path = find_pi_executable()
    if pi_path:
        return [pi_path], f"系统 PATH: {pi_path}"
    raise RuntimeError(PI_INSTALL_HINT)


def check_pi_version(launch_prefix: List[str], timeout: float = 15.0) -> Tuple[bool, str]:
    """运行 `<launch_prefix> --version` 校验版本锁定。返回 (ok, 版本或错误信息)。"""
    try:
        proc = subprocess.run(
            launch_prefix + ["--version"], capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        version = (proc.stdout or "").strip()
    except Exception as e:
        return False, f"`pi --version` 执行失败: {e}"
    if not version:
        return False, "`pi --version` 无输出（安装可能不完整）"
    if version != PI_REQUIRED_VERSION:
        return False, (
            f"Pi 版本不符: 检测到 {version}，要求 {PI_REQUIRED_VERSION}。\n{PI_INSTALL_HINT}"
        )
    return True, version


# ----------------------------------------------------------------------
# 事件映射（纯函数，可单测）：RPC 事件 → 码铃语义回调
# ----------------------------------------------------------------------
def map_rpc_event(ev: dict, on_chunk: Callable[[str], None],
                  on_tool_call: Callable[[str, dict], None],
                  on_tool_done: Callable[[str, dict], None],
                  state: Dict) -> None:
    """把一条 Pi RPC 事件翻译成码铃回调。state 由调用方持有并跨事件复用
    （累计 usage、记录最终文本/stopReason）。"""
    etype = ev.get("type")

    if etype == "message_update":
        delta = (ev.get("assistantMessageEvent") or {})
        if delta.get("type") == "text_delta":
            text = delta.get("delta") or ""
            if text:
                state["chunks"] = state.get("chunks", 0) + 1
                on_chunk(text)

    elif etype == "tool_execution_start":
        name = ev.get("toolName") or ""
        on_tool_call(name, {"step": state.get("turns", 0), "name": name,
                            "arguments": ev.get("args") or {}})

    elif etype == "tool_execution_end":
        name = ev.get("toolName") or ""
        result = ev.get("result") or {}
        summary = ""
        for block in (result.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text":
                summary = str(block.get("text") or "")
                break
        on_tool_done(name, {"name": name, "ok": not ev.get("isError"),
                            "summary": summary[:200]})

    elif etype == "turn_end":
        state["turns"] = state.get("turns", 0) + 1

    elif etype == "message_end":
        msg = ev.get("message") or {}
        if msg.get("role") == "assistant":
            state["stop_reason"] = msg.get("stopReason")
            usage = msg.get("usage") or {}
            acc = state.setdefault("usage", {"input": 0, "output": 0,
                                             "cacheRead": 0, "cacheWrite": 0})
            for key in acc:
                acc[key] += int(usage.get(key) or 0)
            if state.get("stop_reason") == "stop":
                text = "".join(
                    c.get("text", "") for c in (msg.get("content") or [])
                    if isinstance(c, dict) and c.get("type") == "text")
                if text:
                    state["final_text"] = text


# ----------------------------------------------------------------------
# RPC 会话（阻塞式，供 QThread worker / 测试调用）
# ----------------------------------------------------------------------
class PiRpcSession:
    """一个 `pi --mode rpc` 子进程的完整生命周期管理。"""

    def __init__(self, cfg, workspace: str,
                 confirm_fn: Optional[Callable[[str, str], bool]] = None,
                 on_chunk: Optional[Callable[[str], None]] = None,
                 on_tool_call: Optional[Callable[[str, dict], None]] = None,
                 on_tool_done: Optional[Callable[[str, dict], None]] = None,
                 pi_path: Optional[str] = None):
        self.cfg = cfg
        self.workspace = str(workspace)
        self.confirm_fn = confirm_fn
        self.on_chunk = on_chunk or (lambda chunk: None)
        self.on_tool_call = on_tool_call or (lambda name, data: None)
        self.on_tool_done = on_tool_done or (lambda name, data: None)
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._state: Dict = {}
        self._restarts_used = 0

    # ---- 环境与启动参数 ----
    def _build_env(self) -> Dict[str, str]:
        provider = (getattr(self.cfg, "api_provider", "") or "deepseek").lower()
        if provider != "deepseek":
            raise RuntimeError(
                f"Pi 编程引擎试点当前仅支持 DeepSeek 厂商，当前配置: {provider}。"
                "请先在 设置 → API 切换为 DeepSeek，或把编程引擎切回「内置 Agent」。")
        key = (getattr(self.cfg, "api_key", "") or "").strip()
        if not key:
            keys = getattr(self.cfg, "api_keys", None) or []
            key = next((k.strip() for k in keys if k and k.strip()), "")
        if not key:
            raise RuntimeError("未配置 API Key，无法启动 Pi 编程引擎（设置 → API）。")
        env = dict(os.environ)
        env["DEEPSEEK_API_KEY"] = key          # 只进子进程环境，不落日志
        env["PI_SKIP_VERSION_CHECK"] = "1"
        env["PI_OFFLINE"] = "1"                # 关闭启动期联网（更新检查/遥测）
        env["PYTHONIOENCODING"] = "utf-8"
        env["MALING_GATE_WORKSPACE"] = self.workspace  # 门禁工作区白名单
        return env

    def _build_args(self) -> List[str]:
        prefix, _desc = self._launch
        model = (getattr(self.cfg, "api_model", "") or "deepseek-v4-flash").strip()
        return prefix + [
            "--mode", "rpc", "--no-session",
            # 确定性加载：只带码铃门禁扩展，禁用其余发现机制与上下文文件
            "--no-extensions", "-e", str(GATE_PATH),
            "--no-skills", "--no-prompt-templates", "--no-themes",
            "--no-context-files",
            "--provider", "deepseek", "--model", model,
        ]

    # ---- 生命周期 ----
    def start(self, timeout: float = STARTUP_TIMEOUT_S) -> None:
        """启动子进程并完成 get_state 握手（超时/即死均报可读错误）。"""
        self._launch = resolve_pi_launch()
        prefix, desc = self._launch
        ok, info = check_pi_version(prefix)
        if not ok:
            raise RuntimeError(info)
        if not GATE_PATH.exists():
            raise RuntimeError(f"门禁扩展缺失: {GATE_PATH}（分发包需含 pi_gateway）")
        env = self._build_env()
        args = self._build_args()
        logger.info("启动 Pi RPC 子进程: %s (%s, workspace=%s)", prefix, desc, self.workspace)
        self._proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", env=env, cwd=self.workspace, bufsize=1,
        )
        self._lines = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # 握手：get_state 应答即就绪（同时兜底捕获启动即崩）
        deadline = time.time() + timeout
        self._send({"type": "get_state"})
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"Pi 子进程启动即退出（exit={self._proc.returncode}）。"
                    f"stderr: {self._stderr_tail()}")
            try:
                line = self._lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                raise RuntimeError(
                    f"Pi 子进程输出流中断。stderr: {self._stderr_tail()}")
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "response" and ev.get("command") == "get_state":
                logger.info("Pi RPC 就绪（session=%s）",
                            (ev.get("data") or {}).get("sessionId"))
                return
        self.stop()
        raise RuntimeError(f"Pi RPC 启动握手超时（{timeout:.0f}s）。stderr: {self._stderr_tail()}")

    def _read_loop(self) -> None:
        """后台线程：stdout → 队列（严格 LF 分帧，协议要求不用 Unicode 分隔符切分）。"""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._lines.put(line)
        except Exception:
            pass
        self._lines.put(None)  # EOF 哨兵

    def _stderr_tail(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            # 非阻塞不可行——stderr 只在进程退出后读取（启动即死场景）
            return (self._proc.stderr.read() or "")[:500].replace("\n", " ")
        except Exception:
            return ""

    # ---- 收发 ----
    def _send(self, cmd: dict) -> None:
        if self._proc is None or self._proc.stdin is None or self._proc.poll() is not None:
            raise RuntimeError("Pi 子进程未在运行")
        try:
            self._proc.stdin.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except Exception as e:
            raise RuntimeError(f"Pi 子进程写入失败（可能已退出）: {e}")

    def _handle_ui_request(self, ev: dict) -> None:
        """extension_ui_request：confirm → 码铃授权弹窗桥；其余对话框一律取消。"""
        rid = ev.get("id")
        method = ev.get("method")
        if method == "confirm" and self.confirm_fn is not None:
            title = str(ev.get("title") or "码铃授权确认")
            message = str(ev.get("message") or "")
            try:
                allowed = bool(self.confirm_fn(f"{title}\n{message}", "pi_tool"))
            except Exception:
                logger.exception("授权桥异常，按拒绝处理（fail-safe）")
                allowed = False
            self._send({"type": "extension_ui_response", "id": rid,
                        "confirmed": allowed})
            return
        if method == "confirm":
            self._send({"type": "extension_ui_response", "id": rid, "confirmed": False})
        else:
            self._send({"type": "extension_ui_response", "id": rid, "cancelled": True})

    def _pump_until_settled(self, cancel_check: Callable[[], bool]) -> Dict:
        """消费事件直到 agent_settled / EOF；返回本任务状态（文本/usage/stop_reason）。"""
        state: Dict = {}
        aborted_sent = False
        while True:
            if cancel_check() and not aborted_sent:
                try:
                    self._send({"type": "abort"})
                except RuntimeError:
                    pass
                aborted_sent = True
            try:
                line = self._lines.get(timeout=PUMP_TICK_S)
            except queue.Empty:
                continue
            if line is None:
                state["process_died"] = True
                return state
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "extension_ui_request":
                try:
                    self._handle_ui_request(ev)
                except RuntimeError:
                    state["process_died"] = True
                    return state
                continue
            map_rpc_event(ev, self.on_chunk, self.on_tool_call,
                          self.on_tool_done, state)
            if ev.get("type") == "agent_settled":
                return state

    # ---- 对外主入口 ----
    def prompt(self, message: str,
               cancel_check: Optional[Callable[[], bool]] = None) -> Dict:
        """发送一条任务并阻塞到 agent_settled。

        崩溃自动重启：prompt 期间子进程意外退出且重启额度未用完 → 重启会话
        并原样重发一次（MAX_RESTARTS=1）；再次失败则抛错。
        返回 {"text", "usage", "stop_reason", "aborted"}。
        """
        cancel_check = cancel_check or (lambda: False)
        if self._proc is None:
            self.start()
        self._send({"type": "prompt", "message": message})
        state = self._pump_until_settled(cancel_check)
        if state.get("process_died"):
            if self._restarts_used < MAX_RESTARTS:
                self._restarts_used += 1
                logger.warning("Pi 子进程中途退出，自动重启（第 %s 次）并重发任务",
                               self._restarts_used)
                self.stop()
                self.start()
                self._send({"type": "prompt", "message": message})
                state = self._pump_until_settled(cancel_check)
            if state.get("process_died"):
                raise RuntimeError("Pi 子进程中途退出且自动重启后再次失败。")
        text = state.get("final_text", "")
        if state.get("stop_reason") == "aborted":
            text = text or "（已取消）"
        return {
            "text": text,
            "usage": state.get("usage", {}),
            "stop_reason": state.get("stop_reason", ""),
            "aborted": state.get("stop_reason") == "aborted",
        }

    def abort(self) -> None:
        """请求中断当前任务（等价 RPC abort 命令）。"""
        try:
            self._send({"type": "abort"})
        except RuntimeError:
            pass

    def stop(self) -> None:
        """停机：关 stdin → terminate → kill（幂等）。"""
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        logger.info("Pi RPC 子进程已停止")

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
