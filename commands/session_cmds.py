"""会话管理相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import G, R, Y
from managers import SessionManager, sanitize_session_name
from utils import _audit_log


def register_session_commands(router: CommandRouter) -> None:
    """注册会话管理命令。"""

    @router.command(
        "save",
        description="保存会话",
        usage="/save [name]",
        category="会话管理",
    )
    def cmd_save(ctx: CommandContext) -> None:
        name = ctx.args[0] if ctx.args else None
        filename = ctx.session.save(name)
        print(G(f"✅ 会话已保存: {filename}"))

    @router.command(
        "load",
        description="加载会话",
        usage="/load [name]",
        category="会话管理",
    )
    def cmd_load(ctx: CommandContext) -> None:
        name = ctx.args[0] if ctx.args else None
        if ctx.session.load(name):
            print(G(f"✅ 会话已加载: {name or 'default'}.json"))
        else:
            print(R(f"⚠️ 未找到会话文件: {name or 'default'}.json"))

    @router.command(
        "session",
        description="会话管理（list/switch/new/delete）",
        usage="/session list|switch <name>|new <name>|delete <name>",
        category="会话管理",
    )
    def cmd_session(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "list":
            sessions = SessionManager.list_sessions()
            if sessions:
                print("📁 会话列表:")
                for s in sessions:
                    marker = G(" *") if s == f"{ctx.session.session_id}.json" else ""
                    print(f"  - {s[:-5]}{marker}")
            else:
                print("暂无会话文件。")
        elif sub == "switch" and len(ctx.args) >= 2:
            safe_name = sanitize_session_name(ctx.args[1])
            ctx.session.save()
            ctx.session.session_id = safe_name
            if ctx.session.load(safe_name):
                print(G(f"✅ 已切换到会话: {safe_name}"))
            else:
                try:
                    ans = input(Y(f"⚠️ 会话 '{safe_name}' 不存在。是否新建？（Y/n）: "))
                except (EOFError, KeyboardInterrupt):
                    ans = "n"
                if ans.strip().lower() in ("y", "yes", ""):
                    ctx.session.clear()
                    ctx.session.save()
                    print(G(f"✅ 已创建新会话: {safe_name}"))
                else:
                    ctx.session.session_id = "default"
                    ctx.session.load("default")
                    print("已取消，保持当前会话。")
        elif sub == "new" and len(ctx.args) >= 2:
            safe_name = sanitize_session_name(ctx.args[1])
            ctx.session.save()
            ctx.session.session_id = safe_name
            ctx.session.clear()
            ctx.session.save()
            print(G(f"✅ 已创建新会话: {safe_name}"))
        elif sub == "delete" and len(ctx.args) >= 2:
            print(SessionManager.delete_session(ctx.args[1]))
            _audit_log("session_delete", f"name={ctx.args[1]}")
        else:
            print("用法: /session list|switch <name>|new <name>|delete <name>")

    @router.command(
        "clear",
        description="清空对话历史",
        usage="/clear",
        category="会话管理",
    )
    def cmd_clear(ctx: CommandContext) -> None:
        ctx.session.clear()
        print(G("✅ 已清空对话记忆"))
