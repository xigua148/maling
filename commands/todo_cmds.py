"""Todo 相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext


def register_todo_commands(router: CommandRouter) -> None:
    """注册 Todo 命令。"""

    @router.command(
        "todo",
        description="Todo 管理（list/done/clear）",
        usage="/todo list|done <n>|clear",
        category="Todo",
    )
    def cmd_todo(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "list":
            print(ctx.session.todo_mgr.list_items())
        elif sub == "done" and len(ctx.args) >= 2:
            try:
                idx = int(ctx.args[1])
                print(ctx.session.todo_mgr.mark_done(idx))
            except ValueError:
                print("序号必须是数字。")
        elif sub == "clear":
            print(ctx.session.todo_mgr.clear())
        else:
            print("用法: /todo list|done <n>|clear")
