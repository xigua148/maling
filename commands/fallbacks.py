"""AI 直通模式 fallback handlers。"""

from __future__ import annotations

from typing import Optional

from commands.router import CommandContext
from core import C, print_typed
from utils import _save_recovery


def fallback_multi_mode(ctx: CommandContext) -> Optional[bool]:
    """多模型协作模式：拦截所有输入，不走单模型。"""
    if not ctx.session.multi_mode:
        return None  # 不处理，继续下一个 fallback

    final_answer, usage = ctx.collaborator.run(
        ctx.user_input, ctx.session.deep_mode, ctx.session.speed
    )
    print_typed(final_answer, ctx.session.speed, prefix=C("\n[女仆] "))
    ctx.session.add_message("user", ctx.user_input)
    ctx.session.add_message("assistant", final_answer)
    ctx.session._post_process(final_answer)
    ctx.session._last_usage = usage
    ctx.session._print_usage(usage)
    if usage:
        ctx.session.stats.add_tokens(usage.get("total_tokens", 0), mode="multi")
    _save_recovery(ctx.session)
    return True


def fallback_agent_role(ctx: CommandContext) -> Optional[bool]:
    """Agent 角色模式：已切换角色时拦截。"""
    if not ctx.session.agent_sys.current_role:
        return None

    role = ctx.session.agent_sys.current_role
    result, usage = ctx.session.agent_sys.run_agent(role, ctx.user_input, ctx.session.history)
    print_typed(result, ctx.session.speed, prefix=C(f"\n[{ctx.session.agent_sys.get_role_name(role)}] "))
    ctx.session.add_message("user", ctx.user_input)
    ctx.session.add_message("assistant", result)
    ctx.session._post_process(result)
    ctx.session._last_usage = usage
    ctx.session._print_usage(usage)
    if usage:
        ctx.session.stats.add_tokens(usage.get("total_tokens", 0), mode="agent")
    _save_recovery(ctx.session)
    return True


def fallback_single_turn(ctx: CommandContext) -> bool:
    """默认单模型模式：所有未匹配的输入都走这里。"""
    ctx.session.single_turn(ctx.user_input)
    _save_recovery(ctx.session)
    return True
