"""代码补全命令：/complete <file> [line] — AI 基于上下文续写/补全代码。"""

from __future__ import annotations

import re
from pathlib import Path

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C
from utils import _validate_file_path


def register_complete_commands(router: CommandRouter) -> None:
    """注册代码补全命令。"""

    @router.command(
        "complete",
        description="AI 代码补全/续写（基于上下文）",
        usage="/complete <file> [line_number]",
        category="开发者工具",
    )
    def cmd_complete(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /complete <file> [line_number]")
            print("说明: 如果不指定行号，则基于文件末尾续写；")
            print("      如果指定行号，则补全该行内容（光标位置用 <|mask|> 标记）")
            return

        filepath = ctx.args[0]
        line_num = None
        if len(ctx.args) >= 2:
            try:
                line_num = int(ctx.args[1])
                if line_num < 1:
                    line_num = 1
            except ValueError:
                print(R(f"❌ 行号必须是整数: {ctx.args[1]}"))
                return

        ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return

        p = Path(filepath).expanduser()
        if not p.exists():
            print(R(f"❌ 文件不存在: {filepath}"))
            return

        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(R(f"❌ 读取失败: {e}"))
            return

        lines = content.splitlines(keepends=True)

        if line_num is None:
            # 模式 1: 基于文件末尾续写
            _complete_continuation(ctx, filepath, content, lines)
        else:
            # 模式 2: 补全指定行
            _complete_inline(ctx, filepath, content, lines, line_num)


def _complete_continuation(ctx: CommandContext, filepath: str, content: str, lines: list) -> None:
    """基于文件末尾续写代码。"""
    # 取文件末尾上下文（最多 3000 字符）
    context = content[-3000:] if len(content) > 3000 else content

    # 尝试推断语言
    lang = _detect_language(filepath)

    complete_messages = [
        {"role": "system", "content": ctx.session.current_system},
        {"role": "user", "content": (
            f"请根据以下代码的上下文，在文件末尾继续编写代码。\n"
            f"要求：\n"
            f"1. 保持代码风格一致\n"
            f"2. 只输出需要追加的新代码，不要重复已有内容\n"
            f"3. 代码应当完整、可运行\n"
            f"4. 适当添加注释说明\n\n"
            f"文件路径: {filepath}\n"
            f"语言: {lang}\n"
            f"```\n{context}\n```\n\n"
            f"请继续编写："
        )},
    ]

    print(C(f"🤖 正在基于 {filepath} 上下文续写代码..."))
    try:
        resp = ctx.api.chat(complete_messages, max_tokens=ctx.cfg.api_max_tokens)
        result = resp["choices"][0]["message"].get("content", "")

        # 提取代码块
        code = _extract_code_block(result, lang)
        if code:
            print(C(f"\n[续写结果] {filepath}"))
            print(f"```\n{code}\n```")

            # 询问是否追加
            try:
                ans = input(Y("是否将续写内容追加到文件末尾？(Y/n): ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes", ""):
                with open(filepath, "a", encoding="utf-8") as f:
                    # 确保有换行分隔
                    if content and not content.endswith("\n"):
                        f.write("\n")
                    f.write(code)
                    if not code.endswith("\n"):
                        f.write("\n")
                print(G(f"✅ 已追加到 {filepath}"))
            else:
                print("已取消追加。")
        else:
            print(Y("⚠️ AI 未返回有效代码块，原始输出如下:"))
            print(result)
    except Exception as e:
        print(R(f"❌ 代码续写失败: {e}"))


def _complete_inline(ctx: CommandContext, filepath: str, content: str, lines: list, line_num: int) -> None:
    """补全指定行的代码内容。"""
    if line_num > len(lines):
        print(R(f"❌ 行号超出范围: {line_num} > {len(lines)}"))
        return

    target_line = lines[line_num - 1]

    # 检查是否有 mask 标记
    if "<|mask|>" not in target_line:
        print(Y(f"⚠️ 第 {line_num} 行没有 <|mask|> 标记。"))
        print(f"当前内容: {target_line.rstrip()}")
        print("提示: 在需要补全的位置插入 <|mask|> 标记，例如:")
        print('  result = calculate(<|mask|>)')
        print(f"\n将尝试基于整行内容智能补全...")

    # 取上下文（前后各 20 行）
    start = max(0, line_num - 21)
    end = min(len(lines), line_num + 20)
    context_lines = lines[start:end]

    # 标记目标行
    marked_context = []
    for i, line in enumerate(context_lines, start=start + 1):
        if i == line_num:
            marked_context.append(">>> " + line)
        else:
            marked_context.append(f"{i:4d} {line}")
    context_str = "".join(marked_context)

    lang = _detect_language(filepath)

    complete_messages = [
        {"role": "system", "content": ctx.session.current_system},
        {"role": "user", "content": (
            f"请补全以下代码中标记为 >>> 的行。\n"
            f"要求：\n"
            f"1. 只输出补全后的整行代码（不含行号）\n"
            f"2. 保持与上下文的逻辑一致性\n"
            f"3. 如果行中有 <|mask|> 标记，替换为合理的内容\n"
            f"4. 如果没有 <|mask|>，则完善该行使其完整可用\n\n"
            f"文件路径: {filepath}\n"
            f"语言: {lang}\n"
            f"```\n{context_str}\n```\n\n"
            f"请输出补全后的第 {line_num} 行："
        )},
    ]

    print(C(f"🤖 正在补全 {filepath} 第 {line_num} 行..."))
    try:
        resp = ctx.api.chat(complete_messages, max_tokens=ctx.cfg.api_max_tokens)
        result = resp["choices"][0]["message"].get("content", "")

        # 尝试提取代码行
        completed_line = _extract_single_line(result)
        if not completed_line:
            completed_line = result.strip().splitlines()[0] if result.strip() else ""

        if completed_line:
            print(C(f"\n[补全结果] 第 {line_num} 行:"))
            print(f"  原行: {target_line.rstrip()}")
            print(f"  补全: {completed_line}")

            try:
                ans = input(Y("是否替换该行？(Y/n): ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes", ""):
                lines[line_num - 1] = completed_line + ("\n" if not completed_line.endswith("\n") else "")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                print(G(f"✅ 已更新 {filepath} 第 {line_num} 行"))
            else:
                print("已取消替换。")
        else:
            print(Y("⚠️ AI 未返回有效补全结果。"))
    except Exception as e:
        print(R(f"❌ 代码补全失败: {e}"))


def _detect_language(filepath: str) -> str:
    """根据文件扩展名检测编程语言。"""
    ext_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".jsx": "JSX",
        ".tsx": "TSX",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".cpp": "C++",
        ".c": "C",
        ".h": "C/C++ Header",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".scala": "Scala",
        ".r": "R",
        ".m": "Objective-C/MATLAB",
        ".sh": "Shell",
        ".bash": "Bash",
        ".zsh": "Zsh",
        ".ps1": "PowerShell",
        ".sql": "SQL",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".less": "Less",
        ".vue": "Vue",
        ".svelte": "Svelte",
        ".dart": "Dart",
        ".lua": "Lua",
        ".perl": "Perl",
        ".pl": "Perl",
    }
    ext = Path(filepath).suffix.lower()
    return ext_map.get(ext, "未知")


def _extract_code_block(text: str, default_lang: str = "") -> str:
    """从 AI 响应中提取代码块内容。"""
    # 优先匹配指定语言的代码块
    patterns = [
        rf"```{default_lang.lower()}\n(.*?)\n```",
        r"```(?:\w+)?\n(.*?)\n```",
        r"```(.*?)```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return text.strip()


def _extract_single_line(text: str) -> str:
    """从 AI 响应中提取单行代码。"""
    # 尝试匹配反引号包裹的内容
    match = re.search(r"`([^`]+)`", text)
    if match:
        return match.group(1).strip()
    # 清理常见前缀
    lines = text.strip().splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith(("```", "- ", "* ", "#", ">")):
            return stripped
    return ""
