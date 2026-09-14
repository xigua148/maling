from __future__ import annotations

import sys
# Windows 双击运行时自动切换到 GUI 模式
if sys.platform == "win32" and not sys.stdin.isatty():
    import subprocess
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gui_script = os.path.join(script_dir, "gui", "main.py")
    if os.path.exists(gui_script):
        subprocess.Popen([sys.executable, gui_script], creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        import tkinter.messagebox as msgbox
        msgbox.showerror("码铃", "GUI 入口文件缺失，请检查项目完整性。\n\n建议重新运行：python install.py")
    sys.exit(0)

try:
    import io
    import os
    import traceback
    from pathlib import Path

    from core import (
        AppConfig, _setup_logging, G, R, Y, C, B, GR, M, W,
        _HAS_DOTENV, _HAS_PYPERCLIP, AGENT_ROLES, print_typed,
    )
    from api import APIClient
    from session import ChatSession
    from persona import PersonaConfig, PromptManager
    from agents import MultiModelCollaborator
    from utils import (
        _check_dependencies, _ensure_config, _setup_api_key,
        _first_run_banner, _setup_readline, _load_offline_cache,
        _check_recovery, parse_command, show_help,
        _validate_file_path, _show_diff, _audit_log, _save_recovery,
    )
    from helpers import GitHelper
    from editors import FileEditor
    from managers import SessionManager, sanitize_session_name
    from security import is_command_safe

    # CommandRouter 导入
    from commands.router import CommandRouter, CommandContext
    from commands.mode_cmds import register_mode_commands
    from commands.file_cmds import register_file_commands
    from commands.session_cmds import register_session_commands
    from commands.snippet_cmds import register_snippet_commands
    from commands.run_cmds import register_run_commands
    from commands.git_cmds import register_git_commands
    from commands.kb_cmds import register_kb_commands
    from commands.agent_cmds import register_agent_commands
    from commands.search_cmds import register_search_commands
    from commands.todo_cmds import register_todo_commands
    from commands.dev_cmds import register_dev_commands
    from commands.export_cmds import register_export_commands
    from commands.lint_cmds import register_lint_commands
    from commands.bookmark_cmds import register_bookmark_commands
    from commands.review_cmds import register_review_commands
    from commands.deps_cmds import register_deps_commands
    from commands.complete_cmds import register_complete_commands
    from commands.changelog_cmds import register_changelog_commands
    from commands.benchmark_cmds import register_benchmark_commands
    from commands.api_cmds import register_api_commands
    from commands.cicd_cmds import register_cicd_commands
    from commands.i18n_cmds import register_i18n_commands
    from commands.viz_cmds import register_viz_commands
    from commands.project_cmds import register_project_commands
    from commands.plan_cmds import register_plan_commands
    from commands.fallbacks import fallback_multi_mode, fallback_agent_role, fallback_single_turn
except ModuleNotFoundError as _e:
    _missing = str(_e).replace("No module named '", "").replace("'", "")
    print(f"\n缺少依赖模块：{_missing}\n")
    print("这是码铃第一次运行，需要先安装依赖。\n")
    print("请按以下步骤操作：")
    print("1. 打开终端，进入项目目录")
    print("2. 运行：python install.py")
    print("3. 安装完成后，运行：python run.py\n")
    print("或者手动安装：")
    print("   pip install -r requirements_gui.txt\n")
    sys.exit(1)


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    # 步骤 1: 依赖检测
    _check_dependencies()

    # 步骤 2: 确保配置文件存在
    _ensure_config()

    # 步骤 3: 加载配置
    cfg = AppConfig.load(yaml_path=Path("config.yaml"))
    logger = _setup_logging(cfg.output_debug)

    # 步骤 4: API Key 交互式配置
    is_first_run = False
    if not cfg.api_key:
        key = _setup_api_key()
        os.environ["DEEPSEEK_API_KEY"] = key
        cfg.api_key = key
        is_first_run = True

    # 重新加载配置（.env 写入后）
    if _HAS_DOTENV:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        cfg = AppConfig.load(yaml_path=Path("config.yaml"))

    api = APIClient(cfg, logger)
    session = ChatSession(cfg, api, logger)

    # P0-1/2: 命令自动补全与历史（初始用默认列表，Router 初始化后更新）
    completion_available = _setup_readline()

    # P0-4: 崩溃恢复检测
    _load_offline_cache()
    _check_recovery(session)

    # 启动时自动恢复
    auto_loaded = False
    if os.path.exists("default.json"):
        print(Y("检测到上回会话记录（default.json），正在自动恢复..."))
        if session.load("default"):
            print(G("✅ 会话已恢复"))
            auto_loaded = True
        else:
            print(R("⚠️ 会话恢复失败，开始新会话"))

    # 启动时列出可用会话
    sessions = SessionManager.list_sessions()
    if sessions and not auto_loaded:
        print(B(f"可用会话: {', '.join(sessions)}"))

    # 剪贴板检测
    if cfg.clipboard_check and _HAS_PYPERCLIP:
        try:
            import pyperclip
            clip = pyperclip.paste()
            if clip and len(clip) > 20 and "```" in clip:
                print(Y("📋 检测到剪贴板有代码内容"))
                resp = input("是否直接分析剪贴板内容？(Y/n): ").strip().lower()
                if resp in ("", "y", "yes"):
                    session.add_message("user", f"请分析以下代码:\n```\n{clip[:5000]}\n```")
        except Exception:
            pass

    # 欢迎信息（新引导横幅 + 情境问候）
    _first_run_banner(is_first_run, cfg)

    # Phase 1 MVP: 情境问候
    nickname = session.memory_mgr.get_preference("nickname") or cfg.persona_address_user
    topic_followup = session.memory_mgr.build_topic_followup(min_hours=1, max_hours=72)
    greeting = session.greeting_engine.generate_greeting(
        nickname=nickname,
        intimacy_level=session.intimacy.level,
        memory_topic=topic_followup,
    )
    print(C(f"\n[女仆] {greeting}\n"))

    # 快速状态栏
    print(f"命令: /help | /deep | /code | /multi | /stream | /speed | /save | /load | /agent | /session")
    mode_labels = []
    mode_labels.append(f"思考: {'开' if session.deep_mode else '关'}")
    mode_labels.append(f"编程: {'开' if session.coding_mode else '关'}")
    mode_labels.append(f"闲聊: {'开' if session.chat_mode.is_chat_mode else '关'}")
    mode_labels.append(f"多模型: {'开' if session.multi_mode else '关'}")
    mode_labels.append(f"流式: {'开' if session.stream_mode else '关'}")
    mode_labels.append(f"速度: {session.speed}")
    print(f"{' | '.join(mode_labels)}")
    # 亲密度显示
    if session.intimacy.level >= 1:
        print(f"亲密度: {session.intimacy.level_name()}(Lv.{session.intimacy.level}) | 分数: {session.intimacy.score}")
    if GitHelper.is_git_repo():
        print(f"Git 仓库: 是")
    print(B("=" * 50))

    collaborator = MultiModelCollaborator(api, cfg, logger)

    # ═══════════════════════════════════════
    # 初始化 CommandRouter
    # ═══════════════════════════════════════
    router = CommandRouter()

    # 各子系统自注册命令
    register_mode_commands(router)
    register_file_commands(router)
    register_session_commands(router)
    register_snippet_commands(router)
    register_run_commands(router)
    register_git_commands(router)
    register_kb_commands(router)
    register_agent_commands(router)
    register_search_commands(router)
    register_todo_commands(router)
    register_dev_commands(router)
    register_export_commands(router)
    register_lint_commands(router)
    register_bookmark_commands(router)
    register_review_commands(router)
    register_deps_commands(router)
    register_complete_commands(router)
    register_changelog_commands(router)
    register_benchmark_commands(router)
    register_api_commands(router)
    register_cicd_commands(router)
    register_i18n_commands(router)
    register_viz_commands(router)
    register_project_commands(router)
    register_plan_commands(router)

    # 插件注册（兼容现有机制）
    session.plugin_mgr.register_with_router(router)

    # 注册 fallback 链（顺序重要: multi → agent → single）
    router.add_fallback(fallback_multi_mode)
    router.add_fallback(fallback_agent_role)
    router.add_fallback(fallback_single_turn)

    # 注册 help 命令（最后注册，确保所有命令已入库）
    @router.command(
        "help",
        description="显示命令帮助",
        usage="/help",
        category="其他",
    )
    def cmd_help(ctx: CommandContext) -> None:
        print(router.build_help(ctx.session))

    # 注册 quit 命令
    @router.command(
        "quit",
        description="退出程序",
        usage="quit / exit / q",
        category="其他",
        aliases=["exit", "q"],
    )
    def cmd_quit(ctx: CommandContext) -> bool:
        return False  # False = 退出 REPL

    # 更新 Tab 补全命令列表
    if completion_available:
        _setup_readline(router.get_command_list())

    # ═══════════════════════════════════════
    # REPL 主循环
    # ═══════════════════════════════════════
    while True:
        try:
            user_input = input(W("\n[我] ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        cmd, args = parse_command(user_input)

        # 特殊处理：paste 命令读取剪贴板后替换 user_input，保持与原始逻辑等价
        if cmd == "paste":
            if _HAS_PYPERCLIP:
                try:
                    import pyperclip
                    clip = pyperclip.paste()
                    if clip:
                        print(C(f"📋 剪贴板内容已读取 ({len(clip)} 字符)"))
                        user_input = clip
                        cmd, args = parse_command(user_input)
                    else:
                        print("剪贴板为空。")
                        continue
                except Exception as e:
                    print(R(f"读取剪贴板失败: {e}"))
                    continue
            else:
                print(Y("未安装 pyperclip，请执行: pip install pyperclip"))
                continue

        # 构造执行上下文
        ctx = CommandContext(
            session=session,
            cmd=cmd,
            args=args,
            raw_input=user_input,
            cfg=cfg,
            api=api,
            collaborator=collaborator,
        )

        # 单点分发 —— 替换整个 elif 链
        should_continue = router.dispatch(ctx)
        if not should_continue:
            break

    # 退出
    if cfg.auto_save:
        filename = session.save()
        print(G(f"✅ 会话已自动保存: {filename}"))

    print(C("\n女仆已退下，期待再次侍奉主人~ 💕"))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(R(f"\n程序崩溃: {e}"))
        traceback.print_exc()
        input("按回车键退出...")
