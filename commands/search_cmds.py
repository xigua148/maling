"""搜索相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import C


def register_search_commands(router: CommandRouter) -> None:
    """注册搜索命令。"""

    @router.command(
        "search",
        description="手动触发联网搜索",
        usage="/search <查询词>",
        category="搜索",
    )
    def cmd_search(ctx: CommandContext) -> None:
        if ctx.args:
            query = " ".join(ctx.args)
            print(C(f"🔍 正在搜索: {query}..."))
            results = ctx.session.web_search.search(query)
            print(ctx.session.web_search.format_results(results))
            ctx.session.stats.bump_mode("search")
        else:
            print("用法: /search <查询词>")
