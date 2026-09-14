"""文件编辑相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import R, G
from utils import _validate_file_path, _show_diff, _audit_log


def register_file_commands(router: CommandRouter) -> None:
    """注册文件编辑命令。"""

    @router.command(
        "read",
        description="读取文件内容",
        usage="/read <file>",
        category="文件编辑",
    )
    def cmd_read(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /read <file>")
            return
        ok, msg = _validate_file_path(ctx.args[0], ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return
        print(ctx.session.file_editor.read_file(ctx.args[0]))

    @router.command(
        "edit",
        description="让AI生成修改方案",
        usage="/edit <file> <自然语言描述>",
        category="文件编辑",
    )
    def cmd_edit(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            print("用法: /edit <file> <自然语言描述>")
            return
        filepath = ctx.args[0]
        ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
        if not ok:
            print(R(f"❌ {msg}"))
            return
        instruction = " ".join(ctx.args[1:])
        print(ctx.session.file_editor.edit_file(
            filepath, instruction, ctx.api, ctx.cfg, ctx.session.current_system, ctx.cfg.workspace
        ))
        _audit_log("edit", f"file={filepath}, instruction={instruction[:100]}")

    @router.command(
        "apply",
        description="确认应用修改",
        usage="/apply",
        category="文件编辑",
    )
    def cmd_apply(ctx: CommandContext) -> None:
        result = ctx.session.file_editor.apply()
        print(result)
        _audit_log("apply", f"result={result[:100]}")

    @router.command(
        "undo",
        description="撤销修改",
        usage="/undo [file]",
        category="文件编辑",
    )
    def cmd_undo(ctx: CommandContext) -> None:
        filepath = ctx.args[0] if ctx.args else None
        if filepath:
            ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
        print(ctx.session.file_editor.undo(filepath))

    @router.command(
        "diff",
        description="显示文件与 .bak 备份差异",
        usage="/diff <file>",
        category="开发者工具",
    )
    def cmd_diff(ctx: CommandContext) -> None:
        filepath = ctx.args[0] if ctx.args else None
        if filepath:
            ok, msg = _validate_file_path(filepath, ctx.cfg.workspace)
            if not ok:
                print(R(f"❌ {msg}"))
                return
            print(_show_diff(filepath))
        else:
            print("用法: /diff <filepath>")
