"""代码检查（lint）和重构建议命令。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR
from utils import _validate_file_path, _SKIP_DIRS


def register_lint_commands(router: CommandRouter) -> None:
    """注册代码检查和重构建议命令。"""

    # ── /lint ──
    @router.command(
        "lint",
        description="运行代码静态检查（flake8/pylint/mypy）",
        usage="/lint [file|dir] [--tool flake8|pylint|mypy]",
        category="开发者工具",
    )
    def cmd_lint(ctx: CommandContext) -> None:
        target = "."
        tool = "flake8"

        # 解析参数
        i = 0
        while i < len(ctx.args):
            arg = ctx.args[i]
            if arg == "--tool" and i + 1 < len(ctx.args):
                tool = ctx.args[i + 1]
                i += 2
            elif not arg.startswith("-"):
                target = arg
                i += 1
            else:
                i += 1

        if tool not in ("flake8", "pylint", "mypy"):
            print(R(f"❌ 不支持的检查工具: {tool}。可用: flake8, pylint, mypy"))
            return

        # 检查工具是否已安装
        tool_path = shutil.which(tool)
        if not tool_path:
            print(R(f"❌ 未找到 {tool}，请先安装: pip install {tool}"))
            return

        # 验证路径
        ok, msg = _validate_file_path(target, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return

        target_path = Path(target).resolve()
        if not target_path.exists():
            print(R(f"❌ 路径不存在: {target}"))
            return

        # 构建命令
        cmd = [tool]
        if tool == "flake8":
            cmd.extend(["--max-line-length=120", "--extend-ignore=E203,W503"])
        elif tool == "pylint":
            cmd.extend(["--disable=missing-docstring,invalid-name", "--max-line-length=120"])
        elif tool == "mypy":
            cmd.extend(["--ignore-missing-imports", "--show-error-codes"])
        cmd.append(str(target_path))

        print(C(f"🔍 正在运行 {tool}..."))
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            output = result.stdout + result.stderr
            if not output.strip():
                print(G(f"✅ {tool} 检查通过，未发现问题。"))
            else:
                print(Y(f"⚠️ {tool} 检查结果 (exit_code={result.returncode}):"))
                print(_format_lint_output(tool, output))
        except subprocess.TimeoutExpired:
            print(R(f"❌ {tool} 执行超时（>60秒）"))
        except Exception as e:
            print(R(f"❌ 运行 {tool} 失败: {e}"))

    # ── /refactor ──
    @router.command(
        "refactor",
        description="AI 生成代码重构建议（不修改文件）",
        usage="/refactor <file>",
        category="开发者工具",
    )
    def cmd_refactor(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /refactor <file>")
            return

        filepath = ctx.args[0]
        ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return

        p = Path(filepath).expanduser()
        if not p.exists():
            print(R(f"❌ 文件不存在: {filepath}"))
            return

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                original = f.read()
        except Exception as e:
            print(R(f"❌ 读取失败: {e}"))
            return

        if len(original) > 10000:
            print(Y(f"⚠️ 文件较大 ({len(original)} 字符)，将只分析前 10000 字符。"))
            original = original[:10000]

        # 复用 FileEditor.edit_file 的 AI 生成方案模式，但只输出建议不修改文件
        refactor_messages = [
            {"role": "system", "content": ctx.session.current_system},
            {"role": "user", "content": (
                f"请对以下代码进行重构审查，给出具体的重构建议（不要输出修改后的代码，只输出建议列表）。\n"
                f"请从以下维度分析：\n"
                f"1. 代码异味（Code Smell）\n"
                f"2. 命名规范\n"
                f"3. 函数/类设计（单一职责、长度等）\n"
                f"4. 可维护性改进\n"
                f"5. 性能优化建议（如有）\n\n"
                f"文件路径: {filepath}\n"
                f"```python\n{original}\n```\n\n"
                f"请用 Markdown 格式输出，每条建议给出具体行号或代码片段引用。"
            )},
        ]

        print(C("🤖 正在分析代码并生成重构建议..."))
        try:
            resp = ctx.api.chat(refactor_messages, max_tokens=ctx.cfg.api_max_tokens)
            suggestions = resp["choices"][0]["message"].get("content", "")
            from core import print_typed
            print_typed(suggestions, ctx.session.speed, prefix=C("\n[重构建议] "))
            print(G(f"\n✅ 分析完成: {filepath}"))
        except Exception as e:
            print(R(f"❌ 生成重构建议失败: {e}"))


def _format_lint_output(tool: str, output: str) -> str:
    """格式化 lint 输出，高亮关键信息。"""
    lines = output.strip().splitlines()
    formatted = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 高亮错误 vs 警告
        if ": error:" in stripped or " E" in stripped[:60]:
            formatted.append(R(stripped))
        elif ": warning:" in stripped or " W" in stripped[:60]:
            formatted.append(Y(stripped))
        else:
            formatted.append(stripped)
    return "\n".join(formatted[:100]) + ("\n... (更多输出已省略)" if len(lines) > 100 else "")
