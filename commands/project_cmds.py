"""/project 项目上下文感知命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import R, G
from utils import _validate_file_path


def register_project_commands(router: CommandRouter) -> None:
    """注册项目上下文命令。"""

    @router.command(
        "project",
        description="项目上下文管理",
        usage="/project index|status|add <file>",
        category="开发者工具",
    )
    def cmd_project(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /project index|status|add <file>")
            return
        sub = ctx.args[0]
        pc = ctx.session.project_ctx
        if sub == "index":
            print(pc.initialize(ctx.cfg.workspace))
        elif sub == "status":
            print(pc.get_status())
        elif sub == "add" and len(ctx.args) >= 2:
            file_pattern = ctx.args[1]
            # 路径安全检查
            ok, msg = _validate_file_path(file_pattern, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            print(pc.add_file(file_pattern))
        else:
            print("用法: /project index|status|add <file>")
