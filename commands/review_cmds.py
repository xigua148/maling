"""代码评审命令：/review <file>|diff|last — AI 生成结构化评审报告。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C
from utils import _validate_file_path


def register_review_commands(router: CommandRouter) -> None:
    """注册代码评审命令。"""

    @router.command(
        "review",
        description="AI 代码评审（Critical/Major/Minor 分级）",
        usage="/review <file>|diff|last",
        category="开发者工具",
    )
    def cmd_review(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /review <file> | /review diff | /review last")
            return

        target = ctx.args[0]
        content = ""
        source_name = target

        if target == "diff":
            # 获取 git diff
            content = _get_git_diff()
            if not content:
                print(Y("⚠️ 没有检测到 git diff 变更。"))
                return
            source_name = "git diff"
        elif target == "last":
            # 获取最近 AI 回复中的代码块
            content = _get_last_code_block(ctx)
            if not content:
                print(Y("⚠️ 最近对话中没有找到代码块。"))
                return
            source_name = "最近代码块"
        else:
            # 读取文件
            ok, msg = _validate_file_path(target, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            p = Path(target).expanduser()
            if not p.exists():
                print(R(f"❌ 文件不存在: {target}"))
                return
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                print(R(f"❌ 读取失败: {e}"))
                return
            source_name = str(p)

        if len(content) > 12000:
            print(Y(f"⚠️ 内容较长 ({len(content)} 字符)，将只评审前 12000 字符。"))
            content = content[:12000]

        review_messages = [
            {"role": "system", "content": ctx.session.current_system},
            {"role": "user", "content": (
                f"请对以下代码进行结构化评审，按 Critical / Major / Minor 三级分类输出问题。\n"
                f"评审维度：\n"
                f"1. 安全性（注入、越界、敏感信息泄露等）\n"
                f"2. 正确性（逻辑错误、边界条件、并发问题等）\n"
                f"3. 可维护性（命名、复杂度、重复代码等）\n"
                f"4. 性能（算法复杂度、不必要的计算、内存泄漏等）\n"
                f"5. 规范（类型注解、文档、异常处理等）\n\n"
                f"输出格式要求：\n"
                f"- 每个问题标明级别 [Critical] / [Major] / [Minor]\n"
                f"- 给出具体行号或代码片段引用\n"
                f"- 给出改进建议（含示例代码）\n"
                f"- 最后给出整体评分（0-100）和一句话总结\n\n"
                f"来源: {source_name}\n"
                f"```\n{content}\n```"
            )},
        ]

        print(C(f"🤖 正在对 {source_name} 进行代码评审..."))
        try:
            resp = ctx.api.chat(review_messages, max_tokens=ctx.cfg.api_max_tokens)
            result = resp["choices"][0]["message"].get("content", "")
            from core import print_typed
            print_typed(result, ctx.session.speed, prefix=C("\n[代码评审] "))
            print(G(f"\n✅ 评审完成: {source_name}"))
        except Exception as e:
            print(R(f"❌ 生成评审报告失败: {e}"))


def _get_git_diff() -> str:
    """获取当前 git diff（含 staged 和 unstaged）。"""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return (result.stdout or "") + (staged.stdout or "")
    except Exception:
        return ""


def _get_last_code_block(ctx: CommandContext) -> str:
    """从最近 assistant 回复中提取代码块。"""
    last_assistant = None
    for m in reversed(ctx.session.history):
        if m.get("role") == "assistant" and m.get("content"):
            last_assistant = m["content"]
            break
    if not last_assistant:
        return ""
    extracted = ctx.session.code_sandbox.extract_code(last_assistant)
    if extracted:
        return extracted[1]
    return ""
