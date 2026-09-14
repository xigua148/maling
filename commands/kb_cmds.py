"""知识库相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext


def register_kb_commands(router: CommandRouter) -> None:
    """注册知识库命令。"""

    @router.command(
        "kb",
        description="知识库操作（index/search/status）",
        usage="/kb index <dir>|search <query>|status",
        category="知识库",
    )
    def cmd_kb(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "index" and len(ctx.args) >= 2:
            print(ctx.session.kb.index_directory(ctx.args[1]))
        elif sub == "search" and len(ctx.args) >= 2:
            query = " ".join(ctx.args[1:])
            results = ctx.session.kb.search(query)
            if results:
                print("📚 检索结果:")
                for path, chunk, score in results:
                    print(f"  [{path}] (score: {score:.3f})")
                    print(f"    {chunk[:300]}")
            else:
                print("未找到相关内容。")
        elif sub == "status":
            print(ctx.session.kb.status())
        else:
            print("用法: /kb index <dir>|search <query>|status")
