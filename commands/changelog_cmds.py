"""变更日志命令：/changelog generate [since] — 读取 git log，调用 AI 生成 CHANGELOG.md。"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C


def register_changelog_commands(router: CommandRouter) -> None:
    """注册变更日志生成命令。"""

    @router.command(
        "changelog",
        description="基于 git log 生成 CHANGELOG.md",
        usage="/changelog generate [since_tag_or_commit]",
        category="开发者工具",
    )
    def cmd_changelog(ctx: CommandContext) -> None:
        if not ctx.args or ctx.args[0] != "generate":
            print("用法: /changelog generate [since_tag_or_commit]")
            print("说明: 读取 git 提交历史，调用 AI 生成结构化 CHANGELOG。")
            print("      since 参数可以是标签名(v1.0.0)或 commit hash。")
            return

        since = ctx.args[1] if len(ctx.args) > 1 else ""

        if not _is_git_repo():
            print(R("❌ 当前目录不是 git 仓库"))
            return

        # 获取 git log
        commits = _get_git_commits(since)
        if not commits:
            if since:
                print(Y(f"⚠️ 从 {since} 之后没有提交记录"))
            else:
                print(Y("⚠️ 没有提交记录"))
            return

        print(C(f"📜 读取到 {len(commits)} 条提交记录，正在生成 CHANGELOG..."))

        # 构建提交摘要
        commit_summary = _format_commits_for_ai(commits)

        changelog_messages = [
            {"role": "system", "content": ctx.session.current_system},
            {"role": "user", "content": (
                f"请根据以下 git 提交记录，生成一份标准的 CHANGELOG.md 内容。\n"
                f"要求：\n"
                f"1. 使用 Keep a Changelog 格式（Added/Changed/Fixed/Removed/Deprecated/Security）\n"
                f"2. 将相似提交归类合并，不要逐条罗列\n"
                f"3. 每个变更条目简洁明了（一句话）\n"
                f"4. 如果提交信息中有版本号或标签，按版本分组\n"
                f"5. 在开头添加版本比较说明\n"
                f"6. 使用中文撰写变更说明\n\n"
                f"提交记录:\n"
                f"```\n{commit_summary}\n```\n\n"
                f"请输出 Markdown 格式的 CHANGELOG 内容（不需要 ``` 包裹）："
            )},
        ]

        try:
            resp = ctx.api.chat(changelog_messages, max_tokens=ctx.cfg.api_max_tokens)
            changelog = resp["choices"][0]["message"].get("content", "")

            # 清理可能的 markdown 代码块包裹
            changelog = _unwrap_code_block(changelog)

            # 添加头部信息
            header = _build_changelog_header(since, len(commits))
            full_changelog = header + "\n\n" + changelog

            print(C("\n[CHANGELOG 预览]\n"))
            print(full_changelog[:3000])
            if len(full_changelog) > 3000:
                print(Y("\n... (输出已截断，完整内容将写入文件)"))

            # 询问保存方式
            try:
                ans = input(Y("\n保存到 CHANGELOG.md？(Y/n/预览更多): ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"

            if ans in ("y", "yes", ""):
                _save_changelog(full_changelog)
                print(G("✅ CHANGELOG.md 已保存/更新"))
            elif ans in ("p", "preview", "预览"):
                from core import print_typed
                print_typed(full_changelog, ctx.session.speed, prefix="")
                try:
                    ans2 = input(Y("\n保存到 CHANGELOG.md？(Y/n): ")).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    ans2 = "n"
                if ans2 in ("y", "yes", ""):
                    _save_changelog(full_changelog)
                    print(G("✅ CHANGELOG.md 已保存/更新"))
                else:
                    print("已取消保存。")
            else:
                print("已取消保存。")

        except Exception as e:
            print(R(f"❌ 生成 CHANGELOG 失败: {e}"))


def _is_git_repo() -> bool:
    """检查当前目录是否为 git 仓库。"""
    return os.path.isdir(".git")


def _get_git_commits(since: str = "", max_count: int = 100) -> List[Tuple[str, str, str, str]]:
    """
    获取 git 提交记录。
    返回 [(hash, author, date, message)] 列表。
    """
    args = ["git", "log", f"--max-count={max_count}", "--pretty=format:%H|%an|%ad|%s", "--date=short"]
    if since:
        args.append(f"{since}..HEAD")

    try:
        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append((parts[0], parts[1], parts[2], parts[3]))
        return commits
    except Exception:
        return []


def _format_commits_for_ai(commits: List[Tuple[str, str, str, str]]) -> str:
    """将提交记录格式化为适合 AI 处理的文本。"""
    lines = []
    for commit_hash, author, date, message in commits:
        short_hash = commit_hash[:7]
        lines.append(f"[{short_hash}] {date} {author}: {message}")
    return "\n".join(lines)


def _build_changelog_header(since: str, commit_count: int) -> str:
    """构建 CHANGELOG 头部信息。"""
    lines = [
        "# 变更日志 (Changelog)",
        "",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if since:
        lines.append(f"范围: {since}..HEAD")
    lines.append(f"提交数量: {commit_count}")
    lines.append("")
    lines.append("---")
    return "\n".join(lines)


def _unwrap_code_block(text: str) -> str:
    """去除可能的 markdown 代码块包裹。"""
    text = text.strip()
    match = re.match(r"```(?:markdown|md)?\n(.*?)\n```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _save_changelog(content: str, filepath: str = "CHANGELOG.md") -> None:
    """保存 CHANGELOG，如果已存在则在顶部追加新版本内容。"""
    p = Path(filepath)
    if p.exists():
        try:
            existing = p.read_text(encoding="utf-8", errors="replace")
            # 在现有内容后追加，保留头部
            # 找到第一个二级标题之后插入新内容
            lines = existing.splitlines(keepends=True)
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.startswith("## "):
                    insert_idx = i
                    break
            # 新内容插入到第一个版本标题之前
            new_lines = lines[:insert_idx] + ["\n"] + content.splitlines(keepends=True) + ["\n"] + lines[insert_idx:]
            p.write_text("".join(new_lines), encoding="utf-8")
        except Exception:
            # 失败则直接覆盖
            p.write_text(content, encoding="utf-8")
    else:
        p.write_text(content, encoding="utf-8")
