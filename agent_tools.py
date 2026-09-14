"""agent_tools.py —— 工具注册表（码铃 Agent 化的核心新模块）

把代码库现有能力（FileEditor / GitHelper / CodeSandbox / WebSearch）
统一封装成 OpenAI function calling 工具，集中注册、集中管理。

设计要点（对应《码铃Agent化改造蓝图》D1/D2）：
- 工具执行方式：常规工具（read/write/git）进程内直接调用，只有 run_python 走沙箱；
- 权限分级：L0 只读自动放行；L1 修改需授权（会话级一次 / 白名单目录自动放行）；
- 每个 handler 返回 str，统一 `{"status":"ok|error",...}` 结构，
  便于模型理解与 AgentEngine 回写。

本文件是纯新增，不修改任何现有模块。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core import AppConfig

# ---------------------------------------------------------------------------
ToolHandler = Callable[..., str]


class AgentTools:
    """工具注册表：提供 OpenAI function schema 列表 + 按名分发执行。

    D2 授权策略：L0 只读自动放行；L1 修改类工具调用 authorize() 判断：
    - 目标路径命中白名单目录（workspace）→ 自动放行
    - 否则要求 confirm_fn 返回 True（GUI 弹窗 / CLI 输入 Y/n）
    """

    def __init__(self, cfg: AppConfig, logger: logging.Logger,
                 confirm_fn: Optional[Callable[[str, str], bool]] = None):
        self.cfg = cfg
        self.logger = logger
        # confirm_fn(action_desc, tool_name) -> bool；None = 仅白名单目录（workspace）内自动放行，
        # 白名单外的修改类工具一律拒绝（无确认渠道即无授权渠道，fail-safe）
        self.confirm_fn = confirm_fn
        self._tools: Dict[str, dict] = {}
        self._session_authorized: bool = False     # D2: 会话级一次授权
        self._register_builtin_tools()

    # ----- 授权 ----------------------------------------------------------
    def authorize(self, tool_name: str, args: dict, action_desc: str) -> bool:
        """L1 工具的授权判断。安全默认：返回 True 才允许执行。

        判定顺序：
        1. 目标路径命中白名单目录（workspace）→ 放行；
        2. 本会话已授权 → 放行；
        3. 配置了 confirm_fn → 弹确认，用户同意则本会话放行；
        4. 其余一律拒绝（无确认渠道 = 无授权渠道，宁可拒绝不可误放）。
        """
        # 白名单目录自动放行：目标在 workspace 内则直接放行
        target = str(args.get("path") or args.get("filepath") or "")
        if target and self._in_whitelist(target):
            return True
        # v1.5.0: 白名单取参按工具名映射 —— file_move 的参数是 src/dst，
        # 旧实现只读 path/filepath 导致白名单预检对它永不命中（全落授权弹窗，
        # 安全预检形同虚设）。src 与 dst **都**在白名单内才自动放行。
        if tool_name == "file_move":
            src = str(args.get("src") or "")
            dst = str(args.get("dst") or "")
            if src and dst and self._in_whitelist(src) and self._in_whitelist(dst):
                return True
        if self._session_authorized:
            return True
        if self.confirm_fn is not None:
            ok = self.confirm_fn(action_desc, tool_name)
            if ok:
                self._session_authorized = True  # D2: 会话级一次授权
            return ok
        # 无确认渠道：拒绝修改类工具，避免越权
        self.logger.warning("agent 工具 %s 无确认函数且目标不在白名单，已拒绝: %s", tool_name, action_desc[:80])
        return False

    def _in_whitelist(self, path_str: str) -> bool:
        """判断路径是否位于白名单目录（workspace 及其子目录）。

        v1.7.2(T4): 相对路径一律按 cfg.workspace 解析（此前按进程 cwd 解析，
        headless/集成场景 cwd≠workspace 时会把白名单内的相对路径误判越界，
        触发 fail-safe 拒绝循环）。GUI 运行态 cwd==workspace，行为不变。
        """
        try:
            p = Path(path_str).expanduser()
            if not p.is_absolute():
                p = Path(self.cfg.workspace).expanduser() / p
            p = p.resolve()
        except Exception:
            return False
        ws = Path(self.cfg.workspace).expanduser().resolve()
        try:
            p.relative_to(ws)
            return True
        except ValueError:
            return False

    def reset_session_authorization(self) -> None:
        """新会话开始时调用，清空会话级授权。"""
        self._session_authorized = False

    def _resolve_in_ws(self, path_str: str) -> Path:
        """v1.7.2(T4): 路径解析统一口径 —— 相对路径一律按 cfg.workspace 解析。

        与 _in_whitelist 同一规则，保证「授权判定」与「实际读写落盘」指向同一
        文件（否则 headless 场景会出现授权判 workspace、写盘落 cwd 的错位）。
        GUI 运行态 cwd==workspace，行为不变。
        """
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = Path(self.cfg.workspace).expanduser() / p
        return p.resolve()

    # ----- 注册 ----------------------------------------------------------
    def register(self, name: str, description: str, parameters: dict, handler: ToolHandler,
                 level: str = "L0", auth_mode: str = "auto") -> None:
        """注册一个工具。

        auth_mode: "auto"（默认）＝ L1 工具由 execute() 先统一走 authorize()；
                   "self" ＝ 工具 handler 内部自行处理授权/白名单判定
                   （run_command 用：命令白名单命中才执行，白名单外拒绝即拒绝不进弹窗，
                    越界目录才调用 authorize()，需要区分阶段故不能套用 execute 的通用授权）。
        """
        self._tools[name] = {
            "schema": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            "handler": handler,
            "level": level,
            "auth_mode": auth_mode,
        }

    def schemas(self) -> List[dict]:
        """返回 OpenAI tools 参数（供 api.chat / chat_stream 的 tools= 使用）。"""
        return [t["schema"] for t in self._tools.values()]

    def names(self) -> List[str]:
        return list(self._tools.keys())

    def execute(self, name: str, arguments: dict) -> str:
        """按名分发执行。找不到工具 / 未授权 / 异常都返回结构化错误，让模型自纠。"""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"status": "error", "message": f"未知工具: {name}"}, ensure_ascii=False)
        try:
            # 通用授权仅在 auth_mode=="auto" 时先执行；auth_mode=="self"（run_command）
            # 由 handler 内部先做命令/语法白名单判定、仅在目录越界时才调用 authorize()。
            if tool["level"] == "L1" and tool.get("auth_mode", "auto") == "auto":
                desc = f"调用 {name}({json.dumps(arguments, ensure_ascii=False)[:100]})"
                if not self.authorize(name, arguments, desc):
                    return json.dumps({"status": "denied", "message": f"用户未授权执行 {name}，请先征得同意或用只读工具完成。"}, ensure_ascii=False)
            result = tool["handler"](**arguments)
            return result if isinstance(result, str) else str(result)
        except TypeError as e:
            return json.dumps({"status": "error", "message": f"工具 {name} 参数错误: {e}"}, ensure_ascii=False)
        except Exception as e:
            self.logger.exception("工具 %s 执行异常", name)
            return json.dumps({"status": "error", "message": f"工具 {name} 执行失败: {e}"}, ensure_ascii=False)

    # ----- 内置工具注册 --------------------------------------------------
    def _register_builtin_tools(self) -> None:
        # 延迟 import，避免顶层 import 连带拉入重依赖
        from editors import FileEditor
        from helpers import CodeSandbox, GitHelper, WebSearch
        from command_runner import CommandRunner, SAFETY_TAG

        editor = FileEditor(self.logger)
        sandbox = CodeSandbox(self.cfg.code_exec_timeout)
        search = WebSearch(self.cfg.web_search_max_results)
        runner = CommandRunner(self.cfg, self.logger)
        self._command_runner = runner
        ws = self.cfg.workspace

        # ========== L0 只读工具 ==========
        self.register(
            "read_file", "读取指定文件内容，返回文件纯文本内容（非 JSON），超长自动截断到 3000 字符。路径可为绝对路径或相对 workspace 的路径。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}},
             "required": ["path"]},
            lambda path: editor.read_file(path, ws),
            level="L0",
        )

        self.register(
            "list_dir", "列出目录下文件名与类型（不递归）。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径，默认 workspace"}}},
            lambda path=None: self._list_dir(path or ws),
            level="L0",
        )

        self.register(
            "git_status", "查看当前 Git 仓库状态。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "仓库目录，默认 workspace"}}},
            lambda path=None: GitHelper.status(path or ws),
            level="L0",
        )

        self.register(
            "git_diff", "查看未提交的改动 diff。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "仓库目录，默认 workspace"}}},
            lambda path=None: GitHelper.diff(path or ws),
            level="L0",
        )

        self.register(
            "web_search", "联网搜索最新信息（需 ddgs 依赖，未装则返回提示）。",
            {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}},
             "required": ["query"]},
            lambda query: self._format_search(search, query),
            level="L0",
        )

        # --- v1.4.8 新增 L0 工具 ---
        self.register(
            "file_search", "在文件内容中搜索匹配正则表达式的行（类似 grep）。返回匹配行及行号。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "文件路径"},
                            "pattern": {"type": "string", "description": "正则表达式"},
                            "max_lines": {"type": "integer", "description": "最大返回行数（默认 50）"}},
             "required": ["path", "pattern"]},
            lambda path, pattern, max_lines=50: self._file_search(path, pattern, max_lines),
            level="L0",
        )

        self.register(
            "file_info", "获取文件元数据：大小、修改时间、创建时间、编码等。",
            {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}},
             "required": ["path"]},
            lambda path: self._file_info(path),
            level="L0",
        )

        self.register(
            "hash_file", "计算文件的哈希值（支持 md5/sha1/sha256），用于校验文件完整性。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "文件路径"},
                            "algorithm": {"type": "string", "description": "哈希算法（md5/sha1/sha256，默认 sha256）"}},
             "required": ["path"]},
            lambda path, algorithm="sha256": self._hash_file(path, algorithm),
            level="L0",
        )

        self.register(
            "http_get", "获取指定 URL 的页面内容（纯文本，最大 10000 字符）。",
            {"type": "object",
             "properties": {"url": {"type": "string", "description": "HTTP/HTTPS URL"},
                            "max_chars": {"type": "integer", "description": "最大返回字符数（默认 10000）"}},
             "required": ["url"]},
            lambda url, max_chars=10000: self._http_get(url, max_chars),
            level="L0",
        )

        self.register(
            "system_info", "获取系统信息：操作系统、Python 版本、内存、CPU、磁盘空间等。",
            {"type": "object", "properties": {}},
            lambda: self._system_info(),
            level="L0",
        )

        self.register(
            "get_datetime", "获取当前日期和时间（可指定时区或格式）。",
            {"type": "object",
             "properties": {"format": {"type": "string", "description": "日期格式（默认 %Y-%m-%d %H:%M:%S）"}}},
            lambda format="%Y-%m-%d %H:%M:%S": self._get_datetime(format),
            level="L0",
        )

        self.register(
            "count_text", "统计文本的行数、单词数、字符数。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "要统计的文本"}},
             "required": ["text"]},
            lambda text: self._count_text(text),
            level="L0",
        )

        self.register(
            "validate_json", "验证 JSON 语法是否正确，返回错误位置（如有）。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "要验证的 JSON 文本"}},
             "required": ["text"]},
            lambda text: self._validate_json(text),
            level="L0",
        )

        self.register(
            "validate_yaml", "验证 YAML 语法是否正确，返回错误位置（如有）。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "要验证的 YAML 文本"}},
             "required": ["text"]},
            lambda text: self._validate_yaml(text),
            level="L0",
        )

        self.register(
            "math_eval", "安全计算数学表达式（支持四则运算、幂、三角函数等，不可执行代码）。",
            {"type": "object",
             "properties": {"expression": {"type": "string", "description": "数学表达式，如 '2**10 + sin(pi/4)'"}},
             "required": ["expression"]},
            lambda expression: self._math_eval(expression),
            level="L0",
        )

        self.register(
            "env_var", "读取环境变量值（只读，不可修改）。",
            {"type": "object",
             "properties": {"name": {"type": "string", "description": "环境变量名"}},
             "required": ["name"]},
            lambda name: self._env_var(name),
            level="L0",
        )

        self.register(
            "list_processes", "列出当前系统进程（名称、PID、内存占用），按内存降序。",
            {"type": "object",
             "properties": {"top_n": {"type": "integer", "description": "返回前 N 个进程（默认 20）"}}},
            lambda top_n=20: self._list_processes(top_n),
            level="L0",
        )

        # ========== L1 修改工具（需授权） ==========
        self.register(
            "write_file", "创建或覆写一个文件（写入前自动备份 .bak）。注意这是破坏性操作。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "目标文件绝对路径或 workspace 相对路径"},
                            "content": {"type": "string", "description": "完整文件内容"}},
             "required": ["path", "content"]},
            lambda path, content: self._write_file(path, content),
            level="L1",
        )

        self.register(
            "git_commit", "暂存全部改动并提交。",
            {"type": "object", "properties": {"message": {"type": "string", "description": "commit message"}},
             "required": ["message"]},
            lambda message: GitHelper.commit(message, ws),
            level="L1",
        )

        # ---------- exec：代码执行（AST 沙箱） ----------
        self.register(
            "run_python", "在 AST 白名单沙箱内执行一段 Python 代码（不能访问文件系统/网络，仅供计算验证）。",
            {"type": "object", "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}},
             "required": ["code"]},
            lambda code: self._format_sandbox(sandbox, code),
            level="L1",
        )

        # ---------- exec：进程级命令执行（run_command，非沙箱） ----------
        self.register(
            "run_command",
            "在独立进程中执行白名单命令并回读 stdout/stderr（用于跑测试/脚本验证修改）。"
            f"【{SAFETY_TAG}】—— 仅放行解释器 python/python3/pytest/node 运行 workspace 内脚本/测试；"
            "argv 直传禁 shell（管道/重定向/元字符一律拒绝）；pip/npm/git/bash 等命令会直接被拒绝（不会弹授权）。"
            "命令语法或目标路径不合规时返回 denied，请勿重复尝试或改写绕过；"
            "修改代码请用 write_file，查看失败详情后再复跑本工具。",
            {"type": "object",
             "properties": {"command": {"type": "string", "description": "要执行的命令（argv 直传，如：python tests/test_utils.py 或 pytest -q -x tests/）"},
                            "cwd": {"type": "string", "description": "运行目录（可选，默认取目标所在项目根或 workspace）"}},
             "required": ["command"]},
            lambda command, cwd=None: self._run_command(command, cwd),
            level="L1",
            auth_mode="self",
        )

        # --- v1.4.8 新增 L1 工具 ---
        self.register(
            "file_move", "移动或重命名文件/目录。",
            {"type": "object",
             "properties": {"src": {"type": "string", "description": "源路径"},
                            "dst": {"type": "string", "description": "目标路径"}},
             "required": ["src", "dst"]},
            lambda src, dst: self._file_move(src, dst),
            level="L1",
        )

        self.register(
            "file_delete", "删除文件（不可恢复，谨慎使用）。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "要删除的文件路径"}},
             "required": ["path"]},
            lambda path: self._file_delete(path),
            level="L1",
        )

        self.register(
            "file_append", "向文件末尾追加内容（不覆盖已有内容）。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "文件路径"},
                            "content": {"type": "string", "description": "要追加的内容"}},
             "required": ["path", "content"]},
            lambda path, content: self._file_append(path, content),
            level="L1",
        )

        self.register(
            "clipboard_write", "将文本复制到系统剪贴板。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "要复制的文本"}},
             "required": ["text"]},
            lambda text: self._clipboard_write(text),
            level="L1",
        )

        # --- v1.4.8 新增高级工具 ---
        self.register(
            "sqlite_query", "在 SQLite 数据库上执行只读查询（SELECT）。",
            {"type": "object",
             "properties": {"db_path": {"type": "string", "description": "SQLite 数据库文件路径"},
                            "query": {"type": "string", "description": "SQL 查询语句（仅 SELECT）"}},
             "required": ["db_path", "query"]},
            lambda db_path, query: self._sqlite_query(db_path, query),
            level="L0",
        )

        self.register(
            "regex_test", "测试正则表达式匹配（返回匹配结果，不修改文件）。",
            {"type": "object",
             "properties": {"pattern": {"type": "string", "description": "正则表达式"},
                            "text": {"type": "string", "description": "待匹配文本"},
                            "flags": {"type": "string", "description": "标志（i=忽略大小写, m=多行, s=点号匹配换行）"}},
             "required": ["pattern", "text"]},
            lambda pattern, text, flags="": self._regex_test(pattern, text, flags),
            level="L0",
        )

        self.register(
            "text_transform", "文本变换：大小写转换、排序、去重、反转等。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "待变换文本"},
                            "operation": {"type": "string", "description": "操作类型：upper/lower/title/sort/sort_reverse/unique/reverse/lines_count"}},
             "required": ["text", "operation"]},
            lambda text, operation: self._text_transform(text, operation),
            level="L0",
        )

        self.register(
            "base64_encode", "将文本编码为 Base64。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "待编码文本"}},
             "required": ["text"]},
            lambda text: self._base64_encode(text),
            level="L0",
        )

        self.register(
            "base64_decode", "将 Base64 解码为文本。",
            {"type": "object",
             "properties": {"text": {"type": "string", "description": "Base64 文本"}},
             "required": ["text"]},
            lambda text: self._base64_decode(text),
            level="L0",
        )

        self.register(
            "image_info", "获取图片元数据（尺寸、格式、模式）。需要 Pillow 库。",
            {"type": "object",
             "properties": {"path": {"type": "string", "description": "图片文件路径"}},
             "required": ["path"]},
            lambda path: self._image_info(path),
            level="L0",
        )

    # ----- handler 私有实现 -----
    @staticmethod
    def _list_dir(path: str) -> str:
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"目录不存在: {path}"}, ensure_ascii=False)
        if p.is_file():
            return json.dumps({"status": "error", "message": f"是文件而非目录: {path}"}, ensure_ascii=False)
        entries = []
        try:
            for child in sorted(p.iterdir()):
                kind = "dir" if child.is_dir() else "file"
                entries.append(f"{kind}\t{child.name}")
        except PermissionError as e:
            return json.dumps({"status": "error", "message": f"无权限访问: {e}"}, ensure_ascii=False)
        body = "\n".join(entries) if entries else "(空目录)"
        return json.dumps({"status": "ok", "message": f"📂 {path}:\n{body}"}, ensure_ascii=False)

    @staticmethod
    def _format_search(search, query: str) -> str:
        results = search.search(query)
        return search.format_results(results)

    @staticmethod
    def _format_sandbox(sandbox, code: str) -> str:
        r = sandbox.run_python(code)
        msg = f"exit_code={r['exit_code']}\n[stdout]\n{r['stdout']}\n[stderr]\n{r['stderr']}"
        status = "ok" if r["exit_code"] == 0 and not r["stderr"] else "error"
        return json.dumps({"status": status, "message": msg}, ensure_ascii=False)

    def _run_command(self, command: str, cwd: Optional[str] = None) -> str:
        """run_command handler（auth_mode="self"）：白名单命中才执行，越界目录走 authorize。

        流程：CommandRunner 预检 →
          denied（命令/语法/路径白名单外，拒绝即拒绝，不进授权弹窗）→ 原样返回；
          auth（显式 cwd 越出 workspace，命令本身全合法）→ authorize()（GUI 弹窗 /
            无渠道即拒）；
          allow → 独立进程执行。
        返回结构化 JSON（含 status/exit_code/stdout/stderr/耗时与 SAFETY_TAG 诚实标注）。
        """
        from command_runner import SAFETY_TAG, build_run_command_action_desc, result_to_text
        runner = getattr(self, "_command_runner", None)
        if runner is None:  # 防御：runner 未初始化（理论不发生）
            return json.dumps({"status": "error", "message": "run_command 执行器未初始化"},
                              ensure_ascii=False)

        def _auth_cb(target_path: str) -> bool:
            desc = build_run_command_action_desc(command or "", target_path)
            # 复用 authorize()：目标(cwd)越出 ws 不在白名单 → 走 confirm_fn；
            # 无确认渠道时 authorize() 会记日志并返回 False（fail-safe）。
            return self.authorize("run_command", {"path": target_path, "command": command or ""}, desc)

        res = runner.run(command or "", cwd=cwd or "", auth_fn=_auth_cb)
        status = res.get("status", "error")
        if status == "denied":
            reason = res.get("reason") or res.get("stderr") or "命令被拒绝"
            self.logger.warning("run_command 被拒绝: %s", reason)
            return json.dumps({"status": "denied", "reason": reason,
                               "message": f"{reason}（{SAFETY_TAG}）"}, ensure_ascii=False)
        # ok / error：完整结构化输出返回模型，便于 C2 自愈基于 exit_code/stderr 判断
        payload = {
            "status": status,
            "exit_code": res.get("exit_code"),
            "stdout": res.get("stdout", ""),
            "stderr": res.get("stderr", ""),
            "timed_out": bool(res.get("timed_out")),
            "elapsed_seconds": res.get("elapsed_seconds"),
            "cwd": res.get("cwd", ""),
            "command": res.get("command", ""),
            "environment": res.get("environment", SAFETY_TAG),
            "message": result_to_text(res),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _write_file(self, path: str, content: str) -> str:
        """原子写文件：先写 .tmp 再替换，并保留一份 .bak。

        v1.7.2(T4): 相对路径按 workspace 解析（与授权白名单同一口径）。
        """
        try:
            p = self._resolve_in_ws(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            bak = p.with_suffix(p.suffix + ".bak")
            if p.exists():
                bak.write_text(p.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            p.write_text(content, encoding="utf-8")
            return json.dumps({"status": "ok", "message": f"已写入 {p}（备份: {bak.name if bak.exists() else '无'}）"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"写入失败: {e}"}, ensure_ascii=False)

    # ----- v1.4.8 新增工具 handler -----

    @staticmethod
    def _file_search(path: str, pattern: str, max_lines: int = 50) -> str:
        """文件内容搜索（类似 grep）。"""
        import re
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"文件不存在: {path}"}, ensure_ascii=False)
        if not p.is_file():
            return json.dumps({"status": "error", "message": f"不是文件: {path}"}, ensure_ascii=False)
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return json.dumps({"status": "error", "message": f"正则表达式错误: {e}"}, ensure_ascii=False)
        matches = []
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        matches.append(f"L{i}: {line.rstrip()}")
                        if len(matches) >= max_lines:
                            break
        except Exception as e:
            return json.dumps({"status": "error", "message": f"读取失败: {e}"}, ensure_ascii=False)
        if not matches:
            return json.dumps({"status": "ok", "message": f"未找到匹配 '{pattern}' 的行"}, ensure_ascii=False)
        body = "\n".join(matches)
        truncated = f"（还有更多，最多显示 {max_lines} 行）" if len(matches) >= max_lines else ""
        return json.dumps({"status": "ok", "message": f"找到 {len(matches)} 处匹配{truncated}:\n{body}"}, ensure_ascii=False)

    @staticmethod
    def _file_info(path: str) -> str:
        """文件元数据。"""
        import os, datetime
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"路径不存在: {path}"}, ensure_ascii=False)
        stat = p.stat()
        info = {
            "path": str(p),
            "is_file": p.is_file(),
            "is_dir": p.is_dir(),
            "size_bytes": stat.st_size,
            "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        }
        if p.is_file():
            info["extension"] = p.suffix
            info["stem"] = p.stem
        return json.dumps({"status": "ok", **info}, ensure_ascii=False)

    @staticmethod
    def _hash_file(path: str, algorithm: str = "sha256") -> str:
        """文件哈希。"""
        import hashlib
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"文件不存在: {path}"}, ensure_ascii=False)
        if not p.is_file():
            return json.dumps({"status": "error", "message": f"不是文件: {path}"}, ensure_ascii=False)
        algo = algorithm.lower()
        if algo not in ("md5", "sha1", "sha256"):
            return json.dumps({"status": "error", "message": f"不支持的算法: {algorithm}，支持 md5/sha1/sha256"}, ensure_ascii=False)
        h = hashlib.new(algo)
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"读取失败: {e}"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "algorithm": algo, "hash": h.hexdigest(), "file": str(p)}, ensure_ascii=False)

    @staticmethod
    def _http_get(url: str, max_chars: int = 10000) -> str:
        """HTTP GET 获取页面内容。"""
        try:
            import requests
            resp = requests.get(url, timeout=15, headers={"User-Agent": "MaLing-Agent/1.4.8"})
            resp.raise_for_status()
            text = resp.text[:max_chars]
            if len(resp.text) > max_chars:
                text += f"\n...（已截断，原始长度 {len(resp.text)} 字符）"
            return json.dumps({"status": "ok", "url": url, "status_code": resp.status_code,
                               "content_length": len(resp.text), "content": text}, ensure_ascii=False)
        except ImportError:
            return json.dumps({"status": "error", "message": "需要 requests 库，请运行 pip install requests"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"HTTP 请求失败: {e}"}, ensure_ascii=False)

    @staticmethod
    def _system_info() -> str:
        """系统信息。"""
        import sys, os, platform
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "platform": platform.platform(),
            "python_version": sys.version,
            "architecture": platform.machine(),
            "processor": platform.processor() or "unknown",
            "hostname": platform.node(),
            "cwd": os.getcwd(),
        }
        try:
            import shutil
            total, used, free = shutil.disk_usage("/")
            info["disk_total_gb"] = round(total / (1024**3), 1)
            info["disk_free_gb"] = round(free / (1024**3), 1)
        except Exception:
            pass
        try:
            import psutil
            mem = psutil.virtual_memory()
            info["memory_total_gb"] = round(mem.total / (1024**3), 1)
            info["memory_available_gb"] = round(mem.available / (1024**3), 1)
            info["cpu_count"] = psutil.cpu_count()
        except ImportError:
            # v1.5.0: psutil 缺失时 stdlib 降级兜底（platform + os），防裸环境空字段
            try:
                info["cpu_count"] = os.cpu_count()
            except Exception:
                pass
            try:
                if sys.platform == "win32":
                    import ctypes

                    class _MEMORYSTATUSEX(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]

                    stat = _MEMORYSTATUSEX()
                    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
                    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                        info["memory_total_gb"] = round(stat.ullTotalPhys / (1024**3), 1)
                        info["memory_available_gb"] = round(stat.ullAvailPhys / (1024**3), 1)
            except Exception:
                pass
        return json.dumps({"status": "ok", **info}, ensure_ascii=False)

    @staticmethod
    def _get_datetime(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """当前日期时间。"""
        import datetime
        now = datetime.datetime.now()
        try:
            formatted = now.strftime(fmt)
        except Exception:
            formatted = now.isoformat()
        return json.dumps({"status": "ok", "datetime": formatted, "timestamp": int(now.timestamp())}, ensure_ascii=False)

    @staticmethod
    def _count_text(text: str) -> str:
        """文本统计。"""
        lines = text.count("\n") + 1
        chars = len(text)
        words = len(text.split())
        return json.dumps({"status": "ok", "lines": lines, "words": words, "characters": chars}, ensure_ascii=False)

    @staticmethod
    def _validate_json(text: str) -> str:
        """JSON 语法验证。"""
        try:
            json.loads(text)
            return json.dumps({"status": "ok", "message": "JSON 语法正确"}, ensure_ascii=False)
        except json.JSONDecodeError as e:
            return json.dumps({"status": "error", "message": f"JSON 语法错误: {e}",
                               "line": e.lineno, "column": e.colno}, ensure_ascii=False)

    @staticmethod
    def _validate_yaml(text: str) -> str:
        """YAML 语法验证。"""
        try:
            import yaml
            yaml.safe_load(text)
            return json.dumps({"status": "ok", "message": "YAML 语法正确"}, ensure_ascii=False)
        except ImportError:
            return json.dumps({"status": "error", "message": "需要 pyyaml 库"}, ensure_ascii=False)
        except yaml.YAMLError as e:
            msg = str(e)
            return json.dumps({"status": "error", "message": f"YAML 语法错误: {msg}"}, ensure_ascii=False)

    @staticmethod
    def _math_eval(expression: str) -> str:
        """安全数学计算。"""
        import math, ast
        # 安全白名单：只允许数学运算
        allowed_names = {k: getattr(math, k) for k in dir(math) if not k.startswith('_')}
        allowed_names.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow})
        try:
            # 先 AST 检查，确保没有危险调用
            tree = ast.parse(expression, mode='eval')
            for node in ast.walk(tree):
                if isinstance(node, (ast.Call, ast.Attribute)):
                    # 只允许 math 模块的属性
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                        if node.value.id != 'math':
                            return json.dumps({"status": "error", "message": "表达式包含不允许的操作"}, ensure_ascii=False)
            result = eval(expression, {"__builtins__": {}}, allowed_names)
            return json.dumps({"status": "ok", "expression": expression, "result": result}, ensure_ascii=False)
        except SyntaxError as e:
            return json.dumps({"status": "error", "message": f"表达式语法错误: {e}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"计算失败: {e}"}, ensure_ascii=False)

    @staticmethod
    def _env_var(name: str) -> str:
        """读取环境变量。"""
        import os
        value = os.environ.get(name)
        if value is None:
            return json.dumps({"status": "error", "message": f"环境变量 '{name}' 未设置"}, ensure_ascii=False)
        return json.dumps({"status": "ok", "name": name, "value": value}, ensure_ascii=False)

    @staticmethod
    def _list_processes(top_n: int = 20) -> str:
        """列出进程。"""
        try:
            import psutil
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'memory_percent']):
                try:
                    info = p.info
                    procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x.get('memory_percent', 0) or 0, reverse=True)
            top = procs[:top_n]
            lines = [f"{p['pid']:>8}  {p['memory_percent']:>6.1f}%  {p['name']}" for p in top]
            body = "\n".join(lines)
            return json.dumps({"status": "ok", "message": f"PID      MEM%  NAME\n{body}"}, ensure_ascii=False)
        except ImportError:
            # v1.5.0: psutil 缺失时 stdlib 降级 —— Windows 用 tasklist 兜底（按内存排序）
            import sys as _sys
            if _sys.platform == "win32":
                try:
                    import csv, io as _io, subprocess as _sp
                    out = _sp.run(
                        ["tasklist", "/fo", "csv", "/nh"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                    )
                    rows = list(csv.reader(_io.StringIO(out.stdout or "")))
                    procs = []
                    for row in rows:
                        if len(row) >= 5 and row[1].strip().isdigit():
                            # "Mem Usage" 形如 "123,456 K"
                            mem_kb = 0
                            try:
                                mem_kb = int(re.sub(r"[^\d]", "", row[4]) or 0)
                            except Exception:
                                pass
                            procs.append((int(row[1]), mem_kb, row[0]))
                    if not procs:
                        raise RuntimeError("tasklist 无输出")
                    procs.sort(key=lambda x: x[1], reverse=True)
                    total_kb = sum(p[1] for p in procs) or 1
                    lines = [
                        f"{pid:>8}  {mem / total_kb * 100:>6.1f}%  {name}"
                        for pid, mem, name in procs[:top_n]
                    ]
                    return json.dumps({"status": "ok", "engine": "tasklist",
                                       "message": "PID      MEM%  NAME\n" + "\n".join(lines)},
                                      ensure_ascii=False)
                except Exception as e:
                    return json.dumps({"status": "error",
                                       "message": f"需要 psutil 库（stdlib 降级也失败: {e}），请运行 pip install psutil"},
                                      ensure_ascii=False)
            return json.dumps({"status": "error", "message": "需要 psutil 库，请运行 pip install psutil"}, ensure_ascii=False)

    def _file_move(self, src: str, dst: str) -> str:
        """移动/重命名文件。v1.7.2(T4): 相对路径按 workspace 解析。"""
        s = self._resolve_in_ws(src)
        d = self._resolve_in_ws(dst)
        if not s.exists():
            return json.dumps({"status": "error", "message": f"源路径不存在: {src}"}, ensure_ascii=False)
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            s.rename(d)
            return json.dumps({"status": "ok", "message": f"已移动: {src} → {dst}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"移动失败: {e}"}, ensure_ascii=False)

    def _file_delete(self, path: str) -> str:
        """删除文件。v1.7.2(T4): 相对路径按 workspace 解析。"""
        p = self._resolve_in_ws(path)
        if not p.exists():
            return json.dumps({"status": "error", "message": f"文件不存在: {path}"}, ensure_ascii=False)
        if not p.is_file():
            return json.dumps({"status": "error", "message": f"不是文件（可能是目录）: {path}"}, ensure_ascii=False)
        try:
            p.unlink()
            return json.dumps({"status": "ok", "message": f"已删除: {path}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"删除失败: {e}"}, ensure_ascii=False)

    def _file_append(self, path: str, content: str) -> str:
        """追加内容到文件。v1.7.2(T4): 相对路径按 workspace 解析。"""
        p = self._resolve_in_ws(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
            return json.dumps({"status": "ok", "message": f"已追加到 {p}（{len(content)} 字符）"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"追加失败: {e}"}, ensure_ascii=False)

    @staticmethod
    def _clipboard_write(text: str) -> str:
        """复制到剪贴板。"""
        try:
            import subprocess
            if subprocess.os.name == 'nt':
                process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
            else:
                # Linux/Mac
                process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                process.communicate(text.encode('utf-8'))
            return json.dumps({"status": "ok", "message": f"已复制到剪贴板（{len(text)} 字符）"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"剪贴板操作失败: {e}"}, ensure_ascii=False)

    # ----- v1.4.8 高级工具 handler -----

    @staticmethod
    def _sqlite_query(db_path: str, query: str) -> str:
        """SQLite 只读查询。"""
        import sqlite3
        p = Path(db_path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"数据库不存在: {db_path}"}, ensure_ascii=False)
        # 安全检查：只允许 SELECT
        q = query.strip().upper()
        if not q.startswith("SELECT"):
            return json.dumps({"status": "error", "message": "仅支持 SELECT 查询，禁止修改操作"}, ensure_ascii=False)
        try:
            conn = sqlite3.connect(str(p))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            result = [dict(row) for row in rows[:100]]  # 最多返回 100 行
            conn.close()
            return json.dumps({"status": "ok", "columns": columns, "rows": result,
                               "row_count": len(result), "truncated": len(rows) > 100}, ensure_ascii=False)
        except sqlite3.Error as e:
            return json.dumps({"status": "error", "message": f"SQL 错误: {e}"}, ensure_ascii=False)

    @staticmethod
    def _regex_test(pattern: str, text: str, flags: str = "") -> str:
        """正则测试。"""
        import re
        flag_map = {'i': re.IGNORECASE, 'm': re.MULTILINE, 's': re.DOTALL}
        flag = 0
        for f in flags.lower():
            if f in flag_map:
                flag |= flag_map[f]
        try:
            regex = re.compile(pattern, flag)
            matches = []
            for m in regex.finditer(text):
                matches.append({"match": m.group(), "start": m.start(), "end": m.end(),
                                "groups": list(m.groups()) if m.groups() else []})
                if len(matches) >= 50:
                    break
            return json.dumps({"status": "ok", "match_count": len(matches), "matches": matches[:50]},
                              ensure_ascii=False)
        except re.error as e:
            return json.dumps({"status": "error", "message": f"正则错误: {e}"}, ensure_ascii=False)

    @staticmethod
    def _text_transform(text: str, operation: str) -> str:
        """文本变换。"""
        ops = {
            "upper": lambda t: t.upper(),
            "lower": lambda t: t.lower(),
            "title": lambda t: t.title(),
            "sort": lambda t: "\n".join(sorted(t.splitlines())),
            "sort_reverse": lambda t: "\n".join(sorted(t.splitlines(), reverse=True)),
            "unique": lambda t: "\n".join(dict.fromkeys(t.splitlines())),
            "reverse": lambda t: t[::-1],
            "lines_count": lambda t: str(len(t.splitlines())),
        }
        if operation not in ops:
            return json.dumps({"status": "error", "message": f"未知操作: {operation}，支持: {', '.join(ops.keys())}"},
                              ensure_ascii=False)
        result = ops[operation](text)
        return json.dumps({"status": "ok", "result": result}, ensure_ascii=False)

    @staticmethod
    def _base64_encode(text: str) -> str:
        """Base64 编码。"""
        import base64
        encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
        return json.dumps({"status": "ok", "encoded": encoded}, ensure_ascii=False)

    @staticmethod
    def _base64_decode(text: str) -> str:
        """Base64 解码。"""
        import base64
        try:
            decoded = base64.b64decode(text).decode('utf-8')
            return json.dumps({"status": "ok", "decoded": decoded}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"解码失败: {e}"}, ensure_ascii=False)

    @staticmethod
    def _image_info(path: str) -> str:
        """图片元数据。"""
        p = Path(path).expanduser()
        if not p.exists():
            return json.dumps({"status": "error", "message": f"文件不存在: {path}"}, ensure_ascii=False)
        try:
            from PIL import Image
            img = Image.open(p)
            info = {
                "status": "ok",
                "format": img.format,
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
                "size_bytes": p.stat().st_size,
            }
            img.close()
            return json.dumps(info, ensure_ascii=False)
        except ImportError:
            return json.dumps({"status": "error", "message": "需要 Pillow 库，请运行 pip install Pillow"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"读取图片失败: {e}"}, ensure_ascii=False)
