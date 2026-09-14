"""模式切换相关命令。"""

from __future__ import annotations

from commands.router import CommandRouter, CommandContext
from core import C, G, R, GR


def register_mode_commands(router: CommandRouter) -> None:
    """注册所有模式切换命令。"""

    @router.command(
        "deep",
        description="切换深度思考模式",
        usage="/deep",
        category="模式切换",
    )
    def cmd_deep(ctx: CommandContext) -> None:
        state = ctx.session.toggle_deep()
        ctx.session.stats.bump_mode("deep")
        print(f"{C('🧠')} 深度思考模式已{'开启' if state else '关闭'}")
        if state:
            print(GR("  提示: 深度思考附加参数（reasoning_effort / thinking）为 DeepSeek 专属，"))
            print(GR("        使用其他厂商时将自动跳过，不影响正常对话"))

    @router.command(
        "code",
        description="切换编程模式",
        usage="/code",
        category="模式切换",
    )
    def cmd_code(ctx: CommandContext) -> None:
        state = ctx.session.toggle_coding()
        ctx.session.stats.bump_mode("coding")
        # 同时关闭闲聊模式
        if state and ctx.session.chat_mode.is_chat_mode:
            ctx.session.set_chat_mode(False)
        print(f"{C('💻')} 编程模式已{'开启' if state else '关闭'}")

    @router.command(
        "multi",
        description="切换多模型协作模式",
        usage="/multi",
        category="模式切换",
    )
    def cmd_multi(ctx: CommandContext) -> None:
        state = ctx.session.toggle_multi()
        ctx.session.stats.bump_mode("multi")
        print(f"{C('🔄')} 多模型协作模式已{'开启' if state else '关闭'}")

    @router.command(
        "stream",
        description="切换真流式输出模式",
        usage="/stream on|off",
        category="模式切换",
    )
    def cmd_stream(ctx: CommandContext) -> None:
        args = ctx.args
        if args:
            if args[0] == "on":
                ctx.session.stream_mode = True
            elif args[0] == "off":
                ctx.session.stream_mode = False
            else:
                print(R("用法: /stream on|off"))
                return
        else:
            ctx.session.stream_mode = not ctx.session.stream_mode
        print(f"{C('📡')} 流式输出已{'开启' if ctx.session.stream_mode else '关闭'}")
        print(GR("  提示: /stream on = 真流式API逐chunk输出; /speed 控制非流式模拟速度"))

    @router.command(
        "tokens",
        description="切换 Token 用量显示",
        usage="/tokens on|off",
        category="输出控制",
    )
    def cmd_tokens(ctx: CommandContext) -> None:
        args = ctx.args
        if args:
            if args[0] == "on":
                ctx.session.show_tokens = True
            elif args[0] == "off":
                ctx.session.show_tokens = False
            else:
                print(R("用法: /tokens on|off"))
                return
        else:
            ctx.session.show_tokens = not ctx.session.show_tokens
        print(f"{C('📊')} Token 显示已{'开启' if ctx.session.show_tokens else '关闭'}")

    @router.command(
        "speed",
        description="设置输出速度",
        usage="/speed fast|normal|slow",
        category="输出控制",
    )
    def cmd_speed(ctx: CommandContext) -> None:
        speed = ctx.args[0] if ctx.args else ""
        if ctx.session.set_speed(speed):
            print(G(f"✅ 输出速度已设置为: {speed}"))
        else:
            print(R("⚠️ 无效速度，可用: fast / normal / slow"))

    @router.command(
        "quiet",
        description="切换调试信息",
        usage="/quiet",
        category="输出控制",
    )
    def cmd_quiet(ctx: CommandContext) -> None:
        import logging
        ctx.cfg.output_debug = not ctx.cfg.output_debug
        # 通过 session 的 logger 调整级别（logger 在 session 初始化时创建）
        if hasattr(ctx.session, "logger") and ctx.session.logger:
            ctx.session.logger.setLevel(
                logging.DEBUG if ctx.cfg.output_debug else logging.INFO
            )
        print(G(f"✅ 调试信息已{'开启' if ctx.cfg.output_debug else '关闭'}"))

    @router.command(
        "reload",
        description="热重载配置",
        usage="/reload",
        category="其他",
    )
    def cmd_reload(ctx: CommandContext) -> None:
        from pathlib import Path
        from core import AppConfig
        ctx.cfg = AppConfig.load(yaml_path=Path("config.yaml"))
        print(G("✅ 配置已重新加载"))

    @router.command(
        "stats",
        description="会话统计",
        usage="/stats",
        category="其他",
    )
    def cmd_stats(ctx: CommandContext) -> None:
        if ctx.cfg.stats_enabled:
            print(ctx.session.stats.report())
        else:
            print(GR("统计功能已禁用。"))

    # ═══════════════════════════════════════════════════════
    # Phase 1 MVP: 聊天功能增强命令
    # ═══════════════════════════════════════════════════════

    @router.command(
        "chat",
        description="切换闲聊模式（弱化编程，强化陪伴）",
        usage="/chat | /chat off",
        category="模式切换",
    )
    def cmd_chat(ctx: CommandContext) -> None:
        args = ctx.args
        if args and args[0] == "off":
            ctx.session.set_chat_mode(False)
            print(f"{C('💬')} 闲聊模式已关闭，回到正常模式")
        else:
            state = ctx.session.toggle_chat_mode()
            label = "开启" if state else "关闭"
            print(f"{C('💬')} 闲聊模式已{label}")
            if state:
                print(GR("  提示: 闲聊模式下弱化编程辅助，强化陪伴互动"))
                print(GR("        输入 '/chat off' 或 '/code' 回到编程模式"))

    @router.command(
        "greet",
        description="触发即时情境问候",
        usage="/greet",
        category="其他",
    )
    def cmd_greet(ctx: CommandContext) -> None:
        nickname = ctx.session.memory_mgr.get_preference("nickname") or ctx.cfg.persona_address_user
        greeting = ctx.session.greeting_engine.generate_quick_greeting(
            nickname=nickname,
            intimacy_level=ctx.session.intimacy.level,
        )
        print(C(f"\n[女仆] {greeting}"))

    @router.command(
        "pref",
        description="管理用户偏好记忆",
        usage="/pref set <key> <value> | /pref get <key> | /pref list | /pref delete <key>",
        category="其他",
    )
    def cmd_pref(ctx: CommandContext) -> None:
        args = ctx.args
        if not args:
            print(R("用法: /pref set <key> <value> | /pref get <key> | /pref list | /pref delete <key>"))
            return

        subcmd = args[0].lower()
        mm = ctx.session.memory_mgr

        if subcmd == "set":
            if len(args) < 3:
                print(R("用法: /pref set <key> <value>"))
                return
            key = args[1]
            value = " ".join(args[2:])
            mm.set_preference(key, value)
            print(G(f"✅ 已记住: {key} = {value}"))
            # 更新 system prompt 使偏好立即生效
            ctx.session._update_system()

        elif subcmd == "get":
            if len(args) < 2:
                print(R("用法: /pref get <key>"))
                return
            key = args[1]
            value = mm.get_preference(key)
            if value is not None:
                print(f"  {key}: {value}")
            else:
                print(GR(f"  未找到偏好: {key}"))

        elif subcmd == "list":
            prefs = mm.list_preferences()
            if prefs:
                print("📋 主人偏好:")
                for k, v in prefs.items():
                    # v1.6: list_preferences 返回对象化结构，取 value 字段展示
                    value = v.get("value") if isinstance(v, dict) else v
                    print(f"  {k}: {value}")
            else:
                print(GR("  暂无记录的偏好。"))

        elif subcmd == "delete":
            if len(args) < 2:
                print(R("用法: /pref delete <key>"))
                return
            key = args[1]
            if mm.delete_preference(key):
                print(G(f"✅ 已删除偏好: {key}"))
                ctx.session._update_system()
            else:
                print(GR(f"  未找到偏好: {key}"))

        else:
            print(R("用法: /pref set <key> <value> | /pref get <key> | /pref list | /pref delete <key>"))

    @router.command(
        "mood",
        description="查看当前亲密度等级和情绪温度",
        usage="/mood",
        category="其他",
    )
    def cmd_mood(ctx: CommandContext) -> None:
        print(ctx.session.intimacy.report())

    @router.command(
        "memory",
        description="查看当前记忆摘要",
        usage="/memory",
        category="其他",
    )
    def cmd_memory(ctx: CommandContext) -> None:
        print(ctx.session.memory_mgr.summary())

    @router.command(
        "forget",
        description="手动遗忘某个话题",
        usage="/forget <topic_keyword>",
        category="其他",
    )
    def cmd_forget(ctx: CommandContext) -> None:
        if not ctx.args:
            print(R("用法: /forget <topic_keyword>"))
            return
        keyword = " ".join(ctx.args)
        if ctx.session.memory_mgr.forget_topic(keyword):
            print(G(f"✅ 已遗忘话题: {keyword}"))
        else:
            print(GR(f"  未找到匹配话题: {keyword}"))

    @router.command(
        "remember",
        description="手动写入记忆（/pref set 的别名）",
        usage="/remember <key> <value>",
        category="其他",
    )
    def cmd_remember(ctx: CommandContext) -> None:
        if len(ctx.args) < 2:
            print(R("用法: /remember <key> <value>"))
            return
        key = ctx.args[0]
        value = " ".join(ctx.args[1:])
        ctx.session.memory_mgr.set_preference(key, value)
        print(G(f"✅ 已记住: {key} = {value}"))
        ctx.session._update_system()
