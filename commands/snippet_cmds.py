"""代码片段相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext


def register_snippet_commands(router: CommandRouter) -> None:
    """注册代码片段命令。"""

    @router.command(
        "snippet",
        description="代码片段管理（save/list/load/delete）",
        usage="/snippet save|list|load|delete <name>",
        category="代码片段",
    )
    def cmd_snippet(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""
        if sub == "save" and len(ctx.args) >= 2:
            last_assistant = None
            for m in reversed(ctx.session.history):
                if m.get("role") == "assistant" and m.get("content"):
                    last_assistant = m["content"]
                    break
            if last_assistant:
                extracted = ctx.session.snippet_mgr.extract_from_text(last_assistant)
                if extracted:
                    lang, code = extracted
                    print(ctx.session.snippet_mgr.save_snippet(ctx.args[1], code, lang))
                else:
                    print("最近回复中没有找到代码块。")
            else:
                print("没有可用的 assistant 回复。")
        elif sub == "list":
            print(ctx.session.snippet_mgr.list_snippets())
        elif sub == "load" and len(ctx.args) >= 2:
            code = ctx.session.snippet_mgr.load_snippet(ctx.args[1])
            if code:
                print(f"已加载片段 '{ctx.args[1]}':\n```\n{code[:500]}\n```")
            else:
                print(f"片段不存在: {ctx.args[1]}")
        elif sub == "delete" and len(ctx.args) >= 2:
            print(ctx.session.snippet_mgr.delete_snippet(ctx.args[1]))
        else:
            print("用法: /snippet save|list|load|delete <name>")
