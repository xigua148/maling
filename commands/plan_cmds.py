"""/plan 多文件协同编辑命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import R, G
from core.plan_engine import PlanEngine
from utils import _validate_file_path


def register_plan_commands(router: CommandRouter) -> None:
    """注册多文件协同编辑命令。"""

    @router.command(
        "plan",
        description="多文件协同编辑",
        usage="/plan <需求描述>|preview|apply [--all|--index N]|reject",
        category="开发者工具",
    )
    def cmd_plan(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /plan <需求>|preview|apply|reject")
            return
        store = ctx.session.plan_store
        sub = ctx.args[0]
        if sub in ("preview", "apply", "reject"):
            if sub == "preview":
                print(store.preview())
            elif sub == "apply":
                if "--all" in ctx.args:
                    print(store.apply_all(ctx.cfg.workspace))
                elif "--index" in ctx.args:
                    idx = ctx.args.index("--index")
                    try:
                        n = int(ctx.args[idx + 1]) if idx + 1 < len(ctx.args) else -1
                    except (ValueError, IndexError):
                        print(R("❌ --index 后需跟有效的数字"))
                        return
                    print(store.apply_one(n, ctx.cfg.workspace))
                else:
                    # 交互式逐个确认
                    pending = store.list_pending()
                    if not pending:
                        print("当前没有待应用的修改方案。")
                        return
                    for i, ch in enumerate(pending):
                        try:
                            ans = input(f"应用 {ch.filepath}? [Y/n/skip all]: ").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            print("\n已取消")
                            return
                        if ans in ("", "y", "yes"):
                            print(store.apply_one(i, ctx.cfg.workspace))
                        elif ans in ("skip all", "sa"):
                            break
            elif sub == "reject":
                print(store.reject())
                store.clear()
        else:
            # 主命令: 分析需求并生成方案
            requirement = " ".join(ctx.args)
            engine = PlanEngine(ctx.api, ctx.cfg, ctx.session.project_ctx)
            changes = engine.analyze(requirement, ctx.session.history)
            if changes:
                store.load(changes)
                print(G(f"✅ 已生成 {len(changes)} 个文件的修改方案，输入 /plan preview 查看"))
            else:
                print(R("⚠️ 未识别到需要修改的文件，请检查需求描述或先执行 /project index"))
