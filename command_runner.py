# -*- coding: utf-8 -*-
"""command_runner.py —— C1 进程级命令执行器（码铃 v1.2 run_command 安全边界）

对应 docs/design-v12.md D3 判定表（权威验收标准）。与 CodeSandbox 的边界：
- run_python = 纯计算 AST 沙箱（进程内禁文件/网络）；
- run_command = **进程级真实执行**（独立子进程，可读写文件/联网/长任务），
  白名单 + 授权但**非沙箱**。工具描述与授权文案必须诚实，标注：
  「独立进程运行 · 非沙箱 · 受白名单约束」。

判定表（D3 定稿，拒绝即拒绝、不进授权弹窗；仅路径越界一类走 L1 授权）：
+------------------+----------------------------------------------+-----------------------------------+
| 维度             | 允许                                          | 拒绝                              |
+------------------+----------------------------------------------+-----------------------------------+
| 首 token         | python / python3 / pytest / node             | pip/pip3/npm/npx/git/shell(bash/sh |
| (解释器白名单)    |                                              | cmd/powershell)/sudo/系统命令及    |
|                  |                                              | core.DANGEROUS_COMMANDS 命中项     |
| 语法形态         | argv 直传（shlex.split），无 shell           | 含任一 shell 元字符               |
|                  |                                              | ; | & < > $ ` ( ) 换行 等          |
| python 参数      | <ws 内脚本相对路径>；-B / -u；-m pytest ...  | -c / -i / -m pip / -m 非 pytest    |
|                  |                                              | 模块 / 其它未知选项               |
| pytest 参数      | <ws 内测试路径>；-q / -x / --tb=short；      | 目录外路径；--pdb 等交互选项；     |
|                  | -k <表达式>                                  | 其它未知选项                       |
| node 参数        | <ws 内 .js 路径>（可带脚本参数）             | -e 等任意选项                      |
| 路径             | resolve 后仍在 workspace 内（含 .. 段拒绝、  | 含 .. / symlink 逃逸 / 越出 ws    |
|                  | symlink 逃逸拒绝）                           |                                    |
| 越界（唯一授权） | 命令/语法全合法，但显式 cwd 越出 workspace    | 无授权渠道(confirm_fn=None)一律拒  |
| 超时             | 超时 kill 进程树，返回部分输出                |                                    |
| 截断             | stdout/stderr 各截断 8k（合计 16k）           |                                    |
| 并发             | 每个实例一把 threading.Lock，同会话同时一个   | 跨进程互斥不做（v1.2 文档标注）    |
|                  | 子进程（进程内互斥）                         |                                    |
+------------------+----------------------------------------------+-----------------------------------+

运行目录规则（C1-2）：cwd 缺省取 workspace 或「含 .git/pyproject.toml/package.json
的最近祖先且仍在 ws 内」；显式 cwd 必须在 workspace 内（越界走 L1 授权）。
路径 token 在选定 cwd 下做相对重写，保证 `argv 直传` 命中的是同一绝对文件。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core import AppConfig, DANGEROUS_COMMANDS

# ---------------------------------------------------------------------------
# 判定表常量
# ---------------------------------------------------------------------------
# 允许的解释器/命令首 token（D3 定稿；不开放配置，调整需代码 review）
# ⚠ 本集合是命令安全的**权威真值源**（AGENTS.md §2.2）。core.SAFE_COMMAND_WHITELIST
# 仅作快速预检，必须为本集合的子集；修改本处必须同步 core/__init__.py 的预检白名单。
ALLOWED_COMMANDS = {"python", "python3", "pytest", "node"}

# 明确拒绝的首 token（即使落到 basename 判定也优先给出针对性提示）
FORBIDDEN_COMMANDS = {
    "pip", "pip3", "pipx", "npm", "npx", "yarn", "pnpm",
    "git", "bash", "sh", "cmd", "powershell", "pwsh", "sudo",
    "apt", "apt-get", "yum", "dnf", "brew", "docker", "make", "cmake",
    "curl", "wget", "rm", "mv", "cp", "del", "rmdir", "taskkill",
    "systemctl", "service", "ping", "telnet", "ssh", "scp",
}

# shell 元字符集合：任一出现在命令原文即拒绝（含换行/管道/重定向/命令替换/子 shell）
_SHELL_META_CHARS = set(";&|<>$`()\r\n\x00")

# python 顶层仅放行的选项（其余 -x 选项一律拒绝）
_PY_ALLOWED_FLAGS = {"-B", "-u"}
# pytest 仅放行的选项
_PYTEST_ALLOWED_FLAGS = {"-q", "-x", "--tb=short"}
_PYTEST_K_FLAG = "-k"

# node 顶层不允许任何选项（-e/-p/-i/--eval 等全拒）；脚本扩展名
_NODE_ALLOWED_SUFFIXES = (".js",)

# 单条命令最大长度（防超长参数注入，R4）
MAX_COMMAND_CHARS = 4096

# 输出截断：stdout/stderr 各 8k（D3：合计 16k）
OUTPUT_LIMIT_CHARS = 8000

# 诚实标注（D3/README 口径统一）
SAFETY_TAG = "独立进程运行 · 非沙箱 · 受白名单约束"

# 项目根判定标记
_PROJECT_MARKERS = (".git", "pyproject.toml", "package.json")


# ---------------------------------------------------------------------------
def _clip(text: str, limit: int = OUTPUT_LIMIT_CHARS) -> Tuple[str, bool]:
    """截断到 limit 字符；超出时在尾部补一行提示。返回 (文本, 是否被截断)。"""
    if text is None:
        return "", False
    text = str(text)
    if len(text) <= limit:
        return text, False
    tail = f"\n…[输出过长，已截断：共 {len(text)} 字符，仅保留前 {limit} 字符]…"
    return text[:limit] + tail, True


def _tokenize(text: str) -> List[str]:
    """Windows argv 分词：双/单引号仅用于分组含空格参数，反斜杠一律按字面保留。

    与 shlex 的区别：不把反斜杠当转义符（Windows 路径需保留 \\），
    引号闭合后剥离。命令不经 shell（argv 直传），因此这是正确的语义。
    """
    tokens: List[str] = []
    cur: List[str] = []
    quote: Optional[str] = None
    for ch in text:
        if quote is not None:
            if ch == quote:
                quote = None
            else:
                cur.append(ch)
        elif ch in ("'", '"'):
            quote = ch
        elif ch.isspace():
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if quote is not None:
        raise ValueError("引号未闭合，无法解析命令")
    if cur:
        tokens.append("".join(cur))
    return tokens


# ---------------------------------------------------------------------------
class CommandRunner:
    """C1 进程执行器：白名单/语法校验 → 路径校验 → argv 直传执行。

    - 每个实例一把互斥锁：同一进程同一会话同时只跑一个子进程（C1-2 P1）；
    - 独立子进程（无 shell=True）、超时 kill、stdout/stderr 截断防爆；
    - 返回结构化结果；「非沙箱」语义通过返回字段 SAFETY_TAG 传达给上层。
    """

    def __init__(self, cfg: AppConfig, logger: Optional[logging.Logger] = None):
        self.cfg = cfg
        self.logger = logger or logging.getLogger("maid_coder.command_runner")
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 对外主入口
    # ------------------------------------------------------------------
    def run(self, command: str, cwd: str = "",
            auth_fn: Optional[Callable[[str], bool]] = None,
            timeout: Optional[int] = None) -> Dict[str, object]:
        """白名单校验通过后执行命令并返回结构化结果。

        返回 dict 字段：status(ok|error|denied) / exit_code / stdout / stderr /
        timed_out / elapsed_seconds / cwd / reason(拒绝时) / environment(诚实标注)。

        cwd: 可选显式运行目录（必须在 workspace 内；越界走 auth_fn 授权）。
        auth_fn: Callable[[str], bool] —— 唯一越界授权渠道（显式 cwd 越出 ws 时
                以 cwd 绝对路径为参调用；返回 True 才放行）。None = 无渠道，越界即拒。
        timeout: 覆盖 cfg.agent_command_timeout（自测用；生产走配置）。
        """
        t0 = time.monotonic()
        pf = self._preflight(command, cwd)
        base = {"command": (command or "").strip(), "environment": SAFETY_TAG}

        # 1) 命令/语法/路径白名单拒绝（拒绝即拒绝，不进授权）
        if pf["verdict"] == "deny":
            reason = pf.get("reason", "命令不在允许范围")
            self.logger.warning("run_command 拒绝（%s）: %s", reason, (command or "")[:120])
            return {**base, "status": "denied", "exit_code": None,
                    "stdout": "", "stderr": reason, "timed_out": False,
                    "elapsed_seconds": round(time.monotonic() - t0, 3),
                    "cwd": str(pf.get("cwd") or ""), "reason": reason}

        # 2) 唯一越界授权点：显式 cwd 越出 workspace，且命令/语法全合法
        if pf["verdict"] == "auth":
            if auth_fn is None:
                reason = "运行目录越出 workspace 且无授权渠道（confirm_fn 未配置），已拒绝。"
                self.logger.warning("run_command 越界拒绝（无渠道）: %s", (command or "")[:120])
                return {**base, "status": "denied", "exit_code": None,
                        "stdout": "", "stderr": reason, "timed_out": False,
                        "elapsed_seconds": round(time.monotonic() - t0, 3),
                        "cwd": str(pf.get("cwd") or ""), "reason": reason}
            ok = False
            try:
                ok = bool(auth_fn(str(pf.get("cwd") or "")))
            except Exception as e:  # 授权回调异常按拒绝处理（fail-safe）
                self.logger.exception("run_command 授权回调异常: %s", e)
            if not ok:
                reason = "运行目录越出 workspace，用户未授权，已拒绝。"
                return {**base, "status": "denied", "exit_code": None,
                        "stdout": "", "stderr": reason, "timed_out": False,
                        "elapsed_seconds": round(time.monotonic() - t0, 3),
                        "cwd": str(pf.get("cwd") or ""), "reason": reason}

        argv: List[str] = pf["argv"]
        cwd_abs = Path(pf["cwd"]).resolve()
        time_limit = timeout if timeout is not None else self._timeout()

        # 3) 会话级互斥 + 独立子进程执行（锁内跑，进程自身有超时兜底）
        with self._lock:
            try:
                self.logger.info("run_command 执行: %s (cwd=%s, timeout=%ss)",
                                 " ".join(argv), cwd_abs, time_limit)
                raw = self._execute(argv, cwd_abs, time_limit)
            except Exception as e:  # 启动/执行异常统一兜底
                self.logger.exception("run_command 执行异常: %s", e)
                return {**base, "status": "error", "exit_code": None,
                        "stdout": "", "stderr": f"命令执行失败: {e}", "timed_out": False,
                        "elapsed_seconds": round(time.monotonic() - t0, 3),
                        "cwd": str(cwd_abs), "reason": str(e)[:200]}

        stdout, stderr, rc, timed_out, elapsed = raw
        stdout, _ = _clip(stdout)
        stderr, _ = _clip(stderr)
        status = "ok" if (not timed_out and rc == 0) else "error"
        return {**base, "status": status, "exit_code": rc,
                "stdout": stdout, "stderr": stderr, "timed_out": timed_out,
                "elapsed_seconds": round(elapsed, 3), "cwd": str(cwd_abs)}

    # ------------------------------------------------------------------
    # 白名单预检
    # ------------------------------------------------------------------
    def _preflight(self, command: str, cwd_arg: str) -> Dict[str, object]:
        """命令 + 语法 + 路径三重白名单校验。

        返回 verdict: "allow"（ws 内自动放行）| "auth"（显式 cwd 越界，唯一授权点）
        | "deny"（拒绝即拒绝，不进弹窗）；以及 argv/cwd/reason。
        """
        cmd = (command or "").strip()
        reason, deny_ctx = self._basic_deny(cmd)
        if reason:
            return {"verdict": "deny", "reason": reason, **deny_ctx}

        ws = self._workspace()
        # ---- 语法形态：argv 直传（禁 shell 元字符）----
        bad = self._first_meta(cmd)
        if bad:
            return {"verdict": "deny", "reason": f"命令含 shell 元字符 {bad!r}，run_command 仅支持 argv 直传（无 shell/管道/重定向）"}
        try:
            tokens = _tokenize(cmd)
        except ValueError as e:
            return {"verdict": "deny", "reason": f"命令无法解析: {e}"}
        if not tokens:
            return {"verdict": "deny", "reason": "命令为空"}

        # ---- 危险命令特征二次兜底（DANGEROUS_COMMANDS 命中即拒）----
        for pattern in DANGEROUS_COMMANDS:
            try:
                if re.search(pattern, cmd, re.IGNORECASE):
                    return {"verdict": "deny", "reason": f"命令命中危险模式 {pattern}"}
            except re.error:
                continue

        # ---- 解释器白名单（首 token）----
        exe, reason = self._resolve_interpreter(tokens[0])
        if reason:
            return {"verdict": "deny", "reason": reason}
        argv = [exe] + tokens[1:]

        # ---- 解释器参数白名单 + 路径白名单 ----
        classify, reason = self._classify_args(exe, argv[1:], ws)
        if reason:
            return {"verdict": "deny", "reason": reason}

        # ---- 运行目录 ----
        cwd_abs = self._pick_cwd(classify, cwd_arg, ws)
        if isinstance(cwd_abs, tuple):  # (error_type, reason, value)
            etype, reason, value = cwd_abs
            if etype == "auth":
                # 唯一授权点：命令/语法/路径全合法，仅显式 cwd 越界。
                # 放行则把 ws 内路径 token 重写到该 cwd 的相对/绝对形式后执行。
                cwd_p = Path(value).resolve() if Path(value).is_absolute() else Path(value)
                argv = self._rewrite_paths(argv, classify["path_idx"], cwd_p)
                return {"verdict": "auth", "reason": reason, "cwd": value,
                        "argv": argv}
            return {"verdict": "deny", "reason": reason}

        # ---- 路径 token 相对重写到选定 cwd（保持 argv 直传命中同一绝对文件）----
        argv = self._rewrite_paths(argv, classify["path_idx"], cwd_abs)
        return {"verdict": "allow", "reason": "", "argv": argv, "cwd": str(cwd_abs)}

    # ------------------------------------------------------------------
    # 各类校验子步骤
    # ------------------------------------------------------------------
    def _basic_deny(self, cmd: str) -> Tuple[str, dict]:
        """与路径无关的显性拒绝：空命令 / 命令过长 / 首 token 黑名单。"""
        if not cmd:
            return "命令为空", {}
        if len(cmd) > MAX_COMMAND_CHARS:
            return f"命令过长（>{MAX_COMMAND_CHARS} 字符）", {}
        head = cmd.split(None, 1)[0].lower() if cmd.split(None, 1) else ""
        # 提取可执行名（去引号/去路径/去扩展名），便于识别绝对路径解释器
        base = Path(head.strip("\"'")).name.lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base in FORBIDDEN_COMMANDS:
            return f"命令首 token {head!r} 在黑名单中（pip/shell/git 等一律拒绝）", {}
        return "", {}

    @staticmethod
    def _first_meta(text: str) -> Optional[str]:
        """返回第一个 shell 元字符（含换行/管道/重定向等），无则 None。"""
        for ch in text:
            if ch in _SHELL_META_CHARS:
                return ch
        return None

    def _resolve_interpreter(self, token: str) -> Tuple[Optional[str], str]:
        """解释器白名单解析：返回 (绝对路径 argv0, 拒绝原因)。"""
        low = token.lower()
        has_sep = ("/" in token) or ("\\" in token)
        if not has_sep:
            # PATH 名称形式：仅接受白名单名
            base = low
            if base.endswith(".exe"):
                base = base[:-4]
            if base not in ALLOWED_COMMANDS:
                return None, f"命令不在白名单: {token!r}（仅允许 {'/'.join(sorted(ALLOWED_COMMANDS))}）"
            resolved = shutil.which(token)
            if not resolved:
                return None, f"解释器不在 PATH 中: {token!r}"
            # 拒绝 .bat/.cmd 垫片（CreateProcess 不能无 shell 直接执行）
            if Path(resolved).suffix.lower() in (".bat", ".cmd"):
                return None, f"解释器 {token!r} 解析为脚本垫片 {resolved}，拒绝无 shell 执行"
            return resolved, ""
        # 带路径形式：仅接受绝对路径且 basename 在白名单
        p = Path(token)
        if not p.is_absolute():
            return None, f"带路径的解释器仅支持绝对路径: {token!r}"
        base = p.name.lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base not in ALLOWED_COMMANDS:
            return None, f"解释器路径 {token!r} 的 basename 不在白名单（仅允许 {'/'.join(sorted(ALLOWED_COMMANDS))}）"
        if not p.exists():
            return None, f"解释器不存在: {token!r}"
        return str(p), ""

    def _classify_args(self, exe: str, rest: List[str], ws: Path) -> Tuple[dict, str]:
        """解释器参数白名单 + 路径白名单校验。

        返回 (classify, 拒绝原因)。classify 含:
        - primary: Optional[Path] 主目标（脚本/测试路径）绝对路径
        - path_idx: List[int]   需相对重写的路径 token 下标（相对 rest，即 argv[1:]）
        - mode: python / pytest / node
        """
        base = Path(exe).name.lower().removesuffix(".exe")
        if base in ("python", "python3"):
            return self._classify_python(rest, ws)
        if base == "pytest":
            return self._classify_pytest_args(rest, ws, mode="pytest")
        if base == "node":
            return self._classify_node(rest, ws)
        return {"primary": None, "path_idx": []}, f"不支持的解释器: {base}"

    # ----- python -----
    def _classify_python(self, rest: List[str], ws: Path) -> Tuple[dict, str]:
        path_idx: List[int] = []
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok in _PY_ALLOWED_FLAGS:
                i += 1
                continue
            if tok == "-m":
                if i + 1 >= len(rest):
                    return {"primary": None, "path_idx": []}, "python -m 缺少模块名"
                mod = rest[i + 1]
                if mod != "pytest":
                    return {"primary": None, "path_idx": []}, f"python -m 仅允许 pytest（收到 {mod!r}），禁止任意模块执行"
                # 剩余按 pytest 参数规则校验（inner.path_idx 相对切片起点，需平移 i+2）
                inner, reason = self._classify_pytest_args(rest[i + 2:], ws, mode="python -m pytest")
                if reason:
                    return {"primary": None, "path_idx": []}, reason
                shifted = [k + (i + 2) for k in inner["path_idx"]]
                return {"primary": inner["primary"], "path_idx": shifted,
                        "mode": "pytest"}, ""
            if tok in ("-c", "-i"):
                label = "内联代码执行" if tok == "-c" else "交互模式"
                return {"primary": None, "path_idx": []}, f"python 参数 {tok} 被拒绝（{label}）"
            if tok.startswith("-"):
                return {"primary": None, "path_idx": []}, f"python 不允许的选项 {tok!r}（仅放行 -B/-u/-m pytest/脚本路径）"
            # 首个位置参数 = 脚本路径；其后位置参数一律视为脚本参数原样保留
            ok, reason, abs_path = self._resolve_path_token(tok, ws)
            if not ok:
                return {"primary": None, "path_idx": []}, f"python 脚本路径无效: {reason}"
            path_idx.append(i)
            return {"primary": abs_path, "path_idx": path_idx, "mode": "python"}, ""
        # 没有任何脚本目标 → 拒绝（防交互式解释器/空转）
        return {"primary": None, "path_idx": []}, "python 缺少脚本路径（仅允许运行 ws 内脚本或 -m pytest）"

    # ----- pytest / python -m pytest 共用 -----
    def _classify_pytest_args(self, rest: List[str], ws: Path, mode: str) -> Tuple[dict, str]:
        path_idx: List[int] = []
        primary: Optional[Path] = None
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok in _PYTEST_ALLOWED_FLAGS:
                i += 1
                continue
            if tok == _PYTEST_K_FLAG:
                if i + 1 >= len(rest):
                    return {"primary": None, "path_idx": []}, f"{mode} -k 缺少表达式"
                i += 2  # -k 表达式已由元字符扫描兜底，原样保留
                continue
            if tok.startswith("-"):
                return {"primary": None, "path_idx": []}, f"{mode} 不允许的选项 {tok!r}（仅放行 -q/-x/--tb=short/-k/测试路径）"
            # 位置参数 = 测试路径（可多个；支持 file.py::case 选择器）
            raw_path = str(tok).partition("::")[0]
            ok, reason, abs_path = self._resolve_path_token(raw_path, ws)
            if not ok:
                return {"primary": None, "path_idx": []}, f"{mode} 测试路径无效: {reason}"
            path_idx.append(i)
            if primary is None:
                primary = abs_path
            i += 1
        if primary is None:
            # 裸 pytest：以 ws 为隐式目标（cwd 内收集，仍在 ws 内）
            return {"primary": ws, "path_idx": path_idx, "mode": "pytest"}, ""
        return {"primary": primary, "path_idx": path_idx, "mode": "pytest"}, ""

    # ----- node -----
    def _classify_node(self, rest: List[str], ws: Path) -> Tuple[dict, str]:
        path_idx: List[int] = []
        for i, tok in enumerate(rest):
            if tok.startswith("-"):
                return {"primary": None, "path_idx": []}, f"node 不允许任何选项（{tok!r}），仅放行 ws 内 .js 脚本"
            ok, reason, abs_path = self._resolve_path_token(tok, ws)
            if not ok:
                return {"primary": None, "path_idx": []}, f"node 脚本路径无效: {reason}"
            if abs_path.suffix.lower() not in _NODE_ALLOWED_SUFFIXES:
                return {"primary": None, "path_idx": []}, f"node 仅支持 .js 脚本（收到 {abs_path.name!r}）"
            path_idx.append(i)
            return {"primary": abs_path, "path_idx": path_idx, "mode": "node"}, ""
        return {"primary": None, "path_idx": []}, "node 缺少 .js 脚本路径"

    def _resolve_path_token(self, raw: str, ws: Path) -> Tuple[bool, str, Path]:
        """路径 token 白名单校验。

        规则：相对路径按 workspace 解析；拒绝含 `..` 段 / symlink 逃逸 /
        越出 workspace；允许 ws 内不存在但父路径合理的 token（不存在外链拒绝由
        resolve 越界兜底）。返回 (ok, reason, abs_path)。
        """
        raw = raw.strip().strip("\"'")
        if not raw:
            return False, "空路径", Path()
        if ".." in raw.replace("\\", "/").split("/"):
            return False, "路径含父目录引用 ..，拒绝", Path()
        p = Path(raw)
        try:
            if p.is_absolute():
                resolved = p.resolve()
            else:
                resolved = (ws / p).resolve()
        except (OSError, RuntimeError) as e:
            return False, f"路径解析失败: {e}", Path()
        try:
            resolved.relative_to(ws)
        except ValueError:
            return False, f"路径越出 workspace: {raw}", Path()
        return True, "", resolved

    # ----- 运行目录 -----
    def _pick_cwd(self, classify: dict, cwd_arg: str, ws: Path):
        """运行目录规则：显式 cwd > 主目标最近项目根 > workspace。

        显式 cwd 越出 ws → ('auth', reason, cwd_abs)（唯一授权点）；
        其余非法 → ('deny', reason)；正常返回 Path。
        """
        if cwd_arg and str(cwd_arg).strip():
            ok, reason, cwd_abs = self._resolve_path_token(str(cwd_arg).strip(), ws)
            if not ok:
                if "越出 workspace" in reason:
                    try:
                        cwd_abs = Path(str(cwd_arg).strip()).expanduser().resolve()
                    except Exception:
                        cwd_abs = Path(str(cwd_arg).strip()).expanduser()
                    return ("auth", reason, str(cwd_abs))
                return ("deny", reason)
            if not cwd_abs.is_dir():
                return ("deny", f"指定的运行目录不存在: {cwd_abs}")
            return cwd_abs
        primary = classify.get("primary")
        if primary is None:
            return ws
        return self._nearest_project_root(primary, ws)

    def _nearest_project_root(self, target: Path, ws: Path) -> Path:
        """cwd 缺省规则：主目标所在目录向上找最近的含项目标记的祖先且仍在 ws 内。"""
        start = target if target.is_dir() else target.parent
        cur = start
        try:
            while True:
                for m in _PROJECT_MARKERS:
                    if (cur / m).exists():
                        return cur
                if cur == ws or ws not in cur.parents:
                    break
                cur = cur.parent
        except (OSError, RuntimeError):
            pass
        return ws

    def _rewrite_paths(self, argv: List[str], path_idx: List[int], cwd_abs: Path) -> List[str]:
        """把已解析的绝对路径 token 重写为相对 cwd 的路径（跨盘则保留绝对）。

        path_idx 是相对 rest（argv[1:]）的下标（_classify_* 返回值），此处平移 +1。
        相对路径 token 按 ws 根解析后重写为相对 cwd，保证 argv 直传命中同一绝对文件。
        """
        if not path_idx:
            return argv
        out = list(argv)
        ws = self._workspace()
        for idx in path_idx:
            real = idx + 1  # argv[0] 是解释器绝对路径
            if real >= len(out):
                continue
            tok = str(out[real])
            raw_path = tok.partition("::")[0]
            ok, _, abs_path = self._resolve_path_token(raw_path, ws)
            if not ok:
                continue  # 不应发生（已预检），保守保留原文
            sel = tok[len(raw_path):] if raw_path else ""
            try:
                rel = os.path.relpath(abs_path, cwd_abs)
            except ValueError:
                rel = str(abs_path)
            out[real] = rel + sel
        return out

    # ------------------------------------------------------------------
    # 执行子过程（互斥锁外不做，锁内由 run() 调用）
    # ------------------------------------------------------------------
    def _execute(self, argv: List[str], cwd_abs: Path, timeout: int) -> Tuple[str, str, Optional[int], bool, float]:
        """独立子进程执行 + 超时 kill 进程树。返回 (stdout, stderr, exit_code, timed_out, elapsed)。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("PYTHONUTF8", "1")
        posix = os.name != "nt"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)  # 防控制台弹窗(R3)
        t0 = time.monotonic()
        proc = subprocess.Popen(
            argv, cwd=str(cwd_abs),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            env=env,
            creationflags=creationflags,
            start_new_session=posix,  # POSIX: 独立会话，超时可整组 kill
        )
        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_tree(proc, posix)
            try:
                out, err = proc.communicate(timeout=15)
            except Exception:
                out, err = "", "(进程已超时 kill，输出不可读)"
            rc = proc.returncode
            if rc is None:
                rc = -1
            self.logger.warning("run_command 超时(%ss)，已 kill 进程树 pid=%s", timeout, proc.pid)
        elapsed = time.monotonic() - t0
        return (out or ""), (err or ""), rc, timed_out, elapsed

    @staticmethod
    def _kill_tree(proc: subprocess.Popen, posix: bool) -> None:
        """超时 kill 进程树：POSIX 用进程组 SIGKILL；Windows 用 taskkill /T。"""
        try:
            if posix:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except Exception:
                    proc.kill()
            else:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                    )
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _workspace(self) -> Path:
        ws = Path(self.cfg.workspace or ".").expanduser()
        if not ws.is_absolute():
            ws = (Path.cwd() / ws)
        return ws.resolve()

    def _timeout(self) -> int:
        try:
            t = int(getattr(self.cfg, "agent_command_timeout", 30) or 30)
        except (TypeError, ValueError):
            t = 30
        return max(1, min(t, 1800))


# ---------------------------------------------------------------------------
# 授权文案 / 结果序列化辅助
# ---------------------------------------------------------------------------
def build_run_command_action_desc(command: str, target_path: str) -> str:
    """run_command 越界授权弹窗文案（诚实标注非沙箱）。"""
    cmd_short = command[:160] if command else ""
    return (f"运行命令（运行目录越出 workspace，进程级真实执行，非沙箱）:\n"
            f"  {cmd_short}\n"
            f"  越界目录: {target_path}\n"
            f"  ⚠ {SAFETY_TAG} —— 该进程可读写文件/联网，请确认运行目录可信。")


def result_to_text(res: dict) -> str:
    """把 run() 结构化结果拼成模型易读文本（status 语义与 agent_tools 对齐）。"""
    lines = [
        f"status={res.get('status')} exit_code={res.get('exit_code')} "
        f"timed_out={res.get('timed_out')} 耗时={res.get('elapsed_seconds')}s",
        f"环境: {res.get('environment', SAFETY_TAG)}",
        f"cwd: {res.get('cwd') or ''}",
        "[stdout]",
        str(res.get("stdout") or ""),
        "[stderr]",
        str(res.get("stderr") or ""),
    ]
    if res.get("reason"):
        lines.insert(0, f"拒绝原因: {res.get('reason')}")
    return "\n".join(lines)


def rules_summary() -> str:
    """白名单判定表文本摘要（供工具描述/设置页等引用）。"""
    return (
        f"仅放行解释器: {'/'.join(sorted(ALLOWED_COMMANDS))}；"
        "拒绝: pip/git/shell(bash/cmd/powershell)/sudo 等及一切危险命令模式；"
        "argv 直传禁 shell（管道/重定向/元字符/换行均拒）；"
        "目标与运行目录须在 workspace 内（越界需授权）；"
        f"{SAFETY_TAG}。"
    )


if __name__ == "__main__":  # pragma: no cover 简易手动冒烟
    import sys
    _cfg = AppConfig(workspace=sys.argv[1] if len(sys.argv) > 1 else ".",
                     agent_command_timeout=5)
    _r = CommandRunner(_cfg)
    _res = _r.run(sys.argv[2] if len(sys.argv) > 2 else "python -B --version")
    print(json.dumps(_res, ensure_ascii=False, indent=2))
