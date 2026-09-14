"""会话导出、环境查看、目录树命令。"""

from __future__ import annotations

import html
import json
import os
import textwrap
from datetime import datetime
from pathlib import Path

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR
from utils import _validate_file_path, _SKIP_DIRS


def register_export_commands(router: CommandRouter) -> None:
    """注册导出、环境、目录树命令。"""

    # ── /export ──
    @router.command(
        "export",
        description="导出会话为 md/txt/html 格式",
        usage="/export [md|txt|html] [filename]",
        category="会话管理",
    )
    def cmd_export(ctx: CommandContext) -> None:
        fmt = (ctx.args[0] if ctx.args else "md").lower()
        if fmt not in ("md", "txt", "html"):
            print(R("❌ 不支持的格式。用法: /export [md|txt|html] [filename]"))
            return
        filename = ctx.args[1] if len(ctx.args) > 1 else None

        # 复用 session.save() 的序列化逻辑
        data = {
            "session_id": ctx.session.session_id,
            "deep_mode": ctx.session.deep_mode,
            "coding_mode": ctx.session.coding_mode,
            "multi_mode": ctx.session.multi_mode,
            "speed": ctx.session.speed,
            "stream_mode": ctx.session.stream_mode,
            "turn_count": ctx.session.turn_count,
            "history": ctx.session.history,
        }

        out_name = filename or f"{ctx.session.session_id}_{fmt}"
        if not out_name.endswith(f".{fmt}"):
            out_name += f".{fmt}"

        ok, msg = _validate_file_path(out_name, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return

        try:
            if fmt == "md":
                content = _export_to_markdown(data)
            elif fmt == "txt":
                content = _export_to_text(data)
            else:  # html
                content = _export_to_html(data)

            with open(out_name, "w", encoding="utf-8") as f:
                f.write(content)
            print(G(f"✅ 会话已导出: {out_name} ({len(content)} 字符)"))
        except Exception as e:
            print(R(f"❌ 导出失败: {e}"))

    # ── /env ──
    @router.command(
        "env",
        description="查看关键环境变量",
        usage="/env [filter]",
        category="开发者工具",
    )
    def cmd_env(ctx: CommandContext) -> None:
        filter_keyword = ctx.args[0].lower() if ctx.args else ""
        env_items = sorted(os.environ.items())

        # 优先展示的关键变量
        priority_keys = {
            "DEEPSEEK_API_KEY", "MAID_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "PATH", "PYTHONPATH", "HOME", "USERPROFILE", "SHELL",
            "PYTHON_VERSION", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
            "LANG", "LC_ALL", "TERM",
            "OS", "PLATFORM", "PROCESSOR_ARCHITECTURE",
            "EDITOR", "GIT_EDITOR", "VISUAL",
        }

        lines = [C("🔧 环境变量:")]
        shown = set()

        # 先展示优先变量
        for key in sorted(priority_keys):
            val = os.environ.get(key, "")
            if not val:
                continue
            if filter_keyword and filter_keyword not in key.lower():
                continue
            displayed = _mask_sensitive(key, val)
            lines.append(f"  {key:<35} {displayed}")
            shown.add(key)

        # 再展示其他匹配的变量
        if filter_keyword:
            for key, val in env_items:
                if key in shown:
                    continue
                if filter_keyword in key.lower() or filter_keyword in val.lower():
                    displayed = _mask_sensitive(key, val)
                    lines.append(f"  {key:<35} {displayed}")
                    shown.add(key)

        if len(lines) == 1:
            lines.append("  (无匹配的环境变量)")
        lines.append(GR(f"\n共 {len(shown)} 个变量"))
        print("\n".join(lines))

    # ── /tree ──
    @router.command(
        "tree",
        description="显示目录树",
        usage="/tree [path] [--depth N]",
        category="开发者工具",
    )
    def cmd_tree(ctx: CommandContext) -> None:
        path = "."
        max_depth = 3

        # 解析参数
        i = 0
        while i < len(ctx.args):
            arg = ctx.args[i]
            if arg == "--depth" and i + 1 < len(ctx.args):
                try:
                    max_depth = int(ctx.args[i + 1])
                    if max_depth < 1:
                        max_depth = 1
                    if max_depth > 10:
                        max_depth = 10
                except ValueError:
                    pass
                i += 2
            elif not arg.startswith("-"):
                path = arg
                i += 1
            else:
                i += 1

        ok, msg = _validate_file_path(path, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return

        target = Path(path).resolve()
        if not target.is_dir():
            print(R(f"❌ 不是目录: {path}"))
            return

        lines = [C(f"📁 {target}")]
        _build_tree(target, target, lines, depth=0, max_depth=max_depth)
        print("\n".join(lines))


# ── 辅助函数 ──

def _export_to_markdown(data: dict) -> str:
    """将会话导出为 Markdown 格式。"""
    lines = [
        f"# 会话导出: {data.get('session_id', 'unknown')}",
        "",
        f"- 导出时间: {datetime.now().isoformat()}",
        f"- 深度模式: {'开' if data.get('deep_mode') else '关'}",
        f"- 编程模式: {'开' if data.get('coding_mode') else '关'}",
        f"- 多模型: {'开' if data.get('multi_mode') else '关'}",
        f"- 轮数: {data.get('turn_count', 0)}",
        "",
        "---",
        "",
    ]
    for msg in data.get("history", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "system":
            lines.append(f"**[系统]**\n\n{content}\n")
        elif role == "user":
            lines.append(f"**[用户]**\n\n{content}\n")
        elif role == "assistant":
            lines.append(f"**[助手]**\n\n{content}\n")
        elif role == "tool":
            lines.append(f"**[工具]**\n\n```\n{content}\n```\n")
        lines.append("")
    return "\n".join(lines)


def _export_to_text(data: dict) -> str:
    """将会话导出为纯文本格式。"""
    lines = [
        f"会话: {data.get('session_id', 'unknown')}",
        f"导出时间: {datetime.now().isoformat()}",
        f"深度模式: {'开' if data.get('deep_mode') else '关'}",
        f"编程模式: {'开' if data.get('coding_mode') else '关'}",
        f"多模型: {'开' if data.get('multi_mode') else '关'}",
        f"轮数: {data.get('turn_count', 0)}",
        "=" * 60,
        "",
    ]
    for msg in data.get("history", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content:
            continue
        lines.append(f"[{role.upper()}]")
        lines.append(textwrap.indent(content, "  "))
        lines.append("")
    return "\n".join(lines)


def _export_to_html(data: dict) -> str:
    """将会话导出为 HTML 格式。"""
    role_colors = {
        "system": "#666",
        "user": "#2196F3",
        "assistant": "#4CAF50",
        "tool": "#FF9800",
    }
    messages_html = []
    for msg in data.get("history", []):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if not content:
            continue
        color = role_colors.get(role, "#333")
        safe_content = html.escape(content).replace("\n", "<br>")
        messages_html.append(
            f'<div style="margin:12px 0;padding:10px;border-left:3px solid {color};background:#f9f9f9;">'
            f'<strong style="color:{color}">[{role.upper()}]</strong><br>'
            f'<pre style="margin:6px 0 0 0;white-space:pre-wrap;font-family:monospace;font-size:14px;">'
            f'{safe_content}</pre></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>会话导出: {html.escape(data.get('session_id', 'unknown'))}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; }}
h1 {{ color: #2196F3; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
.meta {{ color: #666; font-size: 14px; margin: 10px 0 20px; }}
</style>
</head>
<body>
<h1>会话导出: {html.escape(data.get('session_id', 'unknown'))}</h1>
<div class="meta">
导出时间: {datetime.now().isoformat()}<br>
深度模式: {'开' if data.get('deep_mode') else '关'} | 编程模式: {'开' if data.get('coding_mode') else '关'} | 多模型: {'开' if data.get('multi_mode') else '关'} | 轮数: {data.get('turn_count', 0)}
</div>
<hr>
{chr(10).join(messages_html)}
</body>
</html>"""


def _mask_sensitive(key: str, value: str) -> str:
    """对敏感值进行脱敏处理。"""
    sensitive_patterns = ("key", "token", "secret", "password", "passwd", "credential", "auth")
    if any(p in key.lower() for p in sensitive_patterns):
        if len(value) > 8:
            return value[:4] + "***" + value[-4:]
        return "***"
    if len(value) > 120:
        return value[:120] + "..."
    return value


def _build_tree(root: Path, current: Path, lines: list, depth: int, max_depth: int) -> None:
    """递归构建目录树。"""
    if depth >= max_depth:
        return
    try:
        entries = []
        for entry in current.iterdir():
            if entry.name.startswith(".") or entry.name in _SKIP_DIRS:
                continue
            entries.append(entry)
        entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))
    except (PermissionError, OSError):
        return

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        prefix = "    " * depth + ("└── " if is_last else "├── ")
        if entry.is_dir():
            lines.append(f"{prefix}📁 {entry.name}/")
            _build_tree(root, entry, lines, depth + 1, max_depth)
        else:
            size = entry.stat().st_size
            size_str = _human_readable_size(size)
            lines.append(f"{prefix}📄 {entry.name} ({size_str})")


def _human_readable_size(size: int) -> str:
    """将字节转换为人类可读格式。"""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
