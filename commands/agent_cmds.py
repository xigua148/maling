"""Agent 系统相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import C, G
from core import AGENT_ROLES
from utils import _save_recovery


def register_agent_commands(router: CommandRouter) -> None:
    """注册 Agent 系统命令。"""

    @router.command(
        "agent",
        description="切换角色 (product/arch/dev/review/auto/reset)",
        usage="/agent <role>|auto|reset",
        category="Agent 系统",
    )
    def cmd_agent(ctx: CommandContext) -> None:
        if not ctx.args:
            print("用法: /agent <role>|auto|reset")
            return
        role = ctx.args[0]
        if role == "auto":
            detected = ctx.session.agent_sys.auto_detect_role(ctx.user_input)
            print(C(f"🤖 自动判断角色: {ctx.session.agent_sys.get_role_name(detected)}"))
            ctx.session.agent_sys.current_role = detected
        elif role == "reset":
            ctx.session.agent_sys.current_role = None
            print(G("✅ 已切回默认女仆模式"))
        elif role in AGENT_ROLES:
            ctx.session.agent_sys.current_role = role
            print(G(f"✅ 已切换为 {ctx.session.agent_sys.get_role_name(role)} 模式"))
        else:
            print(f"未知角色。可用: {', '.join(AGENT_ROLES.keys())}, reset")

    @router.command(
        "agents",
        description="查看可用角色",
        usage="/agents",
        category="Agent 系统",
    )
    def cmd_agents(ctx: CommandContext) -> None:
        print("🎭 可用角色:")
        for key, info in AGENT_ROLES.items():
            marker = G(" *") if ctx.session.agent_sys.current_role == key else ""
            print(f"  {key}: {info['name']} — {info['desc']}{marker}")
        marker = G(" *") if ctx.session.agent_sys.current_role is None else ""
        print(f"  reset: 切回默认女仆模式{marker}")

    @router.command(
        "workflow",
        description="自动串联多Agent工作流",
        usage="/workflow <任务描述>",
        category="Agent 系统",
    )
    def cmd_workflow(ctx: CommandContext) -> None:
        if ctx.args:
            task_desc = " ".join(ctx.args)
            result, usage = ctx.session.agent_sys.run_workflow(task_desc, ctx.session.history)
            from core import print_typed
            print_typed(result, ctx.session.speed, prefix=C("\n[女仆] "))
            ctx.session.add_message("user", f"/workflow {task_desc}")
            ctx.session.add_message("assistant", result)
            ctx.session._post_process(result)
            ctx.session._last_usage = usage
            ctx.session._print_usage(usage)
            if usage:
                ctx.session.stats.add_tokens(usage.get("total_tokens", 0), mode="workflow")
            _save_recovery(ctx.session)
        else:
            print("用法: /workflow <任务描述>")
