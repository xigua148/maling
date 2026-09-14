"""GUI 入口 —— 初始化 QApplication、AppContext、主题引擎。"""
from __future__ import annotations

import json
import logging
import sys
import os
from datetime import datetime
from pathlib import Path

# 确保项目根目录在路径中（PyInstaller 运行时兼容）
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent.parent
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))

try:
    from gui.qt_compat import QApplication, QIcon
    from gui.config import GuiConfig
    from gui.theme_engine import ThemeEngine
    from gui.app_context import AppContext
    from gui.main_window import MainWindow
    from gui.chat_service import ChatService
    from gui.adapters.gui_chat_session import GuiChatSession
    from gui.session_manager import SessionManager
    from intimacy import IntimacyTracker  # v10.14: GUI 好感度钩子
    from gui.update_checker import (  # v2.0: 启动检查更新（v1.0.0 起）
        UpdateChecker, format_update_text, pick_download_link, save_ignored_version,
        load_update_state, save_update_state, resolve_effective_channel,
        detect_install_form, asset_for_form, has_valid_sha256, extract_host,
        should_check_now,
    )
    from gui.utils import get_resource_path  # 应用图标（窗口/任务栏）
except ModuleNotFoundError as _e:
    _missing = str(_e).replace("No module named '", "").replace("'", "")
    print(f"\n缺少依赖模块：{_missing}")
    if "PySide6" in _missing or "qt_compat" in _missing:
        print("GUI 模式需要 PySide6，请先安装依赖。\n")
    else:
        print("\n")
    print("这是码铃第一次运行，需要先安装依赖。\n")
    print("请按以下步骤操作：")
    print("1. 打开终端，进入项目目录")
    print("2. 运行：python install.py")
    print("3. 安装完成后，运行：python run.py\n")
    print("或者手动安装：")
    print("   pip install -r requirements_gui.txt\n")
    sys.exit(1)

logger = logging.getLogger("maid_coder.gui")


def _setup_logging() -> logging.Logger:
    """配置日志。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger("maid_coder")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # v1.4.0-勘: exe/后台运行时控制台不可见，追加文件输出便于复现定位（幂等）
    try:
        from pathlib import Path
        from gui.utils import get_user_data_dir
        _log_file = str(Path(get_user_data_dir()) / "maid_debug.log")
        _fh = logging.FileHandler(_log_file, encoding="utf-8")
        _fh.setLevel(logging.INFO)
        _fh.setFormatter(formatter)
        root.addHandler(_fh)
        root.info("调试日志文件: %s", _log_file)
    except Exception:
        pass
    return root


def _init_cli_core(app_ctx: AppContext) -> bool:
    """初始化 CLI 核心对象，无需 API Key 也能启动界面。"""
    try:
        from core import AppConfig
        from api import APIClient
        from session import ChatSession
        from agents import MultiModelCollaborator
        from commands.router import CommandRouter
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
        from commands.fallbacks import (
            fallback_multi_mode, fallback_agent_role, fallback_single_turn,
        )

        # 确保配置文件存在
        config_path = Path("config.yaml")
        if not config_path.exists():
            # v10.15: 默认配置改为嵌套结构，与 AppConfig.save() 一致；
            # 老的 flat 字段（api_key / api_url 等）落盘后无法被 AppConfig.load() 正确识别，
            # 此处统一改为按 section 分组（api / session / output / multi_model / web_search / code / safety）。
            default_cfg = """# 码铃配置文件（嵌套结构，与 AppConfig.save() 一致）
api:
  provider: "openai"
  key: ""
  url: "https://api.deepseek.com/v1/chat/completions"
  model: "deepseek-chat"
  max_tokens: 4096
  temperature: 0.7
  retry_times: 3
  timeout_seconds: 60

persona:
  role: "女仆"
  title: "资深全栈开发工程师"
  personality: "娇羞、温顺、细腻，技术问题上专业且自信"
  address_user: "主人"
  # v1.9: 名字与人设标签分离 —— given_name 是她的名字（留空则自称「我」）
  given_name: ""
  address_self: ""

output:
  speed: "normal"
  debug: false
  show_token_usage: true
  stream_mode: true

session:
  max_history_rounds: 20
  summary_interval: 10
  clipboard_check: true
  snippets_file: "snippets.json"
  todos_file: "todos.json"
  kb_index_file: "kb_index.json"

multi_model:
  enabled: false
  roles: ["Coder", "Reviewer", "Generalist"]

web_search:
  enabled: true
  max_results: 5
  provider: "ddgs"

code:
  plugins_dir: "plugins"
  exec_timeout: 30

safety:
  require_confirm_exec: true
  network_allowlist: []

agent:
  # v1.1(agent): 启动后聊天面板「🤖 Agent」按钮是否默认开启；
  # 运行时仍可手动开关（按钮显式操作优先），enabled 只是启动默认状态偏好。
  enabled: false
  # 单次 Agent 任务的工具调用步数上限（GUI 设置页可调 3~20）
  max_steps: 8
  # v1.2(C1): run_command 单条命令超时（秒，默认 30），超时即 kill 进程树。
  # 命令白名单(python/python3/pytest/node)是 design-v12 D3 定稿常量集，不开放配置。
  command_timeout: 30
  # v1.2(C2): 步骤失败后 C2 内层自愈（heal）最大轮数（默认 3），超限即该步 failed+上报卡点
  max_retries: 3
  # v1.2(A9): 有节制主动陪伴（码铃主动开口）。运行态计数存 companion.json.proactive，
  # 本段只存偏好/阈值；免打扰时段内/超单日上限/未过冷却绝不自发开口。
  proactive:
    enabled: true
    quiet: {start: "22:30", end: "08:00"}
    daily_cap: 3
    idle_minutes: 90
    cooldown_minutes: 60
    llm_enhance: false
    # v1.3(P1-4): Idle 问候（系统全局空闲恢复时一句迎接；与 A9 共享冷却/上限）
    idle_return_enabled: true
    system_idle_minutes: 30
"""
            config_path.write_text(default_cfg, encoding="utf-8")
            logger.info("已创建默认配置文件")

        cfg = AppConfig.load(yaml_path=config_path)
        app_ctx.cfg = cfg

        # API Key 可能为空，但不阻止启动
        api = APIClient(cfg, app_ctx.logger)
        app_ctx.api = api

        session = ChatSession(cfg, api, app_ctx.logger)
        app_ctx.session = session

        # 包装为 GuiChatSession
        gui_session = GuiChatSession(session)
        app_ctx.gui_session = gui_session

        # v10.14: 初始化 GUI 好感度追踪器（与 CLI 共用 ~/.maid_coder/intimacy.json）
        app_ctx.intimacy = IntimacyTracker()

        # 初始化协作器
        collaborator = MultiModelCollaborator(api, cfg, app_ctx.logger)
        app_ctx.collaborator = collaborator

        # 初始化命令路由
        router = CommandRouter()
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

        router.add_fallback(fallback_multi_mode)
        router.add_fallback(fallback_agent_role)
        router.add_fallback(fallback_single_turn)

        app_ctx.router = router

        # 插件注册
        if hasattr(session, "plugin_mgr") and session.plugin_mgr:
            try:
                session.plugin_mgr.register_with_router(router)
            except Exception:
                pass

        logger.info("CLI 核心初始化完成")
        return True

    except Exception as exc:
        logger.warning("CLI 核心初始化失败（GUI 将以降级模式运行）: %s", exc)
        return False


# 保持引用，防止非阻断提示框被 Python GC 回收
_active_update_prompts: list = []

# v2.0(域4): 单轮更新编排的进程内共享状态（防 GC；跨回调共享原始 version.json）。
#   "checker"  → 启动检查的 UpdateChecker 实例
#   "remote"   → 最近一次拉取到的原始 version.json（含 assets，供下载取 sha256/size）
#   "download" → 进行中的下载（version/worker/dialog/asset/path）
_update_ctx: dict = {}


def _init_companion(app_ctx: AppContext) -> bool:
    """v1.2 A1: 装配 companion 陪伴域（纯逻辑 Manager）+ Qt 心情广播桥。

    - companion.py 为纯 stdlib，任何依赖缺失（intimacy/session）都鸭子类型降级；
    - 只读 intimacy.level，绝不写 intimacy.json；情绪输入源 = session.memory_mgr.detect_emotion；
    - CompanionBridge 在无 PySide6 时由 companion 内建降级类，import 永不炸；
    - maid_avatar（形象资产）本批不做强装配，留给 UI 批次按需懒加载。
    任一环节失败只记日志，绝不阻断启动。
    """
    try:
        from companion import CompanionBridge, CompanionManager
    except Exception as exc:
        logger.warning("companion 模块导入失败（跳过陪伴域）: %s", exc)
        return False

    try:
        intimacy = getattr(app_ctx, "intimacy", None)  # 只读 .level/.score

        def _emotion_detector(text: str):
            """从 session.memory_mgr.detect_emotion 取主人情绪（无则 None）。"""
            session = getattr(app_ctx, "session", None)
            memory_mgr = getattr(session, "memory_mgr", None) if session is not None else None
            if memory_mgr is None or not hasattr(memory_mgr, "detect_emotion"):
                return None
            return memory_mgr.detect_emotion(text)

        mgr = CompanionManager(
            intimacy=intimacy,
            emotion_detector=_emotion_detector,
            logger=logger,
        )
        app_ctx.companion = mgr

        # Qt 广播桥（mood_changed 单源，供后续首页/宠物/气泡/侧栏订阅）
        try:
            app_ctx.companion_bridge = CompanionBridge(manager=mgr, parent=None)
        except Exception as exc:
            logger.warning("companion 桥接初始化失败（不影响运行）: %s", exc)
            app_ctx.companion_bridge = None

        # 每日打卡 + 心情初算（深夜 -> tired / 默认 normal）；内部按需落盘并广播
        mood, _moment = mgr.on_app_open()
        app_ctx.companion_mood = mood
        logger.info("companion 陪伴域初始化完成，当前心情: %s", mood)
        return True
    except Exception as exc:
        logger.warning("companion 初始化失败（不影响运行）: %s", exc)
        return False


def _init_proactive(app_ctx: AppContext) -> bool:
    """v1.2(A9): 装配有节制主动陪伴调度器（低频 QTimer，依赖 chat_service/companion）。

    调度器为 GUI 运行期唯一主动触发源；呈现走 ChatService.proactive_ask
    （会话落 assistant + proactive_message 广播）。任一环节失败只记日志不阻断启动。
    """
    try:
        from gui.proactive_scheduler import ProactiveScheduler
    except Exception as exc:
        logger.warning("proactive_scheduler 模块导入失败（跳过主动陪伴）: %s", exc)
        return False
    try:
        scheduler = ProactiveScheduler(app_ctx)
        app_ctx.proactive_scheduler = scheduler
        started = scheduler.start()
        logger.info("主动陪伴调度器初始化完成（定时: %s）", "已启动" if started else "非 Qt 环境跳过")
        return True
    except Exception as exc:
        logger.warning("主动陪伴调度器初始化失败（不影响运行）: %s", exc)
        return False


def _init_weekly_review(app_ctx: AppContext) -> bool:
    """v1.6(P1-3/D-V16-10): 装配每周共同回顾（启动装配完成后调 maybe_generate）。

    - manager 单例挂 app_ctx.weekly（page_home 卡片 / page_memory_book 往期
      Tab 复用同一实例，weekly.json 原子写）；
    - maybe_generate 自带周日 18:00–21:00 窗口判定 + 同周幂等 + 错过不补；
      窗口外调用恒为 None（零副作用）；
    - 无系统通知无推送（R-C）：生成只落 weekly.json，呈现全靠用户自己翻页；
    - 任一数据源缺失/异常都降级，绝不阻断启动。
    """
    try:
        from weekly import WeeklyReviewManager, week_start_of  # noqa: F401
        manager = WeeklyReviewManager()
    except Exception as exc:
        logger.warning("WeeklyReviewManager 初始化失败（周回顾降级）: %s", exc)
        return False
    app_ctx.weekly = manager
    try:
        from gui.pages.page_memories import get_highlights_manager
        review = manager.maybe_generate(
            datetime.now(),
            highlights=get_highlights_manager(app_ctx),
            memory_mgr=getattr(getattr(app_ctx, "session", None), "memory_mgr", None),
            companion=getattr(app_ctx, "companion", None),
        )
        if review is not None:
            logger.info("每周共同回顾已生成（week_start=%s）", review.get("week_start"))
        return True
    except Exception as exc:
        logger.warning("周回顾生成判定失败（不影响运行）: %s", exc)
        return False


def _init_reminders(app_ctx: AppContext) -> bool:
    """v1.7(F4/D-V17-03): 装配贴身提醒调度器（60s QTimer 扫描 todos.json 单源）。

    - 启动即 catch_up 补送（due_at<now ∧ not notified 恰一次，文案带
      "你不在时到点的"）；到点 notify_maid（Windows 通知中心，Q-C4）+
      确定性气泡（scene="reminder"）；quiet 降级顺延补看不弹通知；
    - 独立通道不占 A9 cap（番茄钟先例）；任一环节失败只记日志不阻断启动。
    """
    try:
        from reminders import ReminderScheduler
    except Exception as exc:
        logger.warning("reminders 模块导入失败（贴身提醒降级）: %s", exc)
        return False
    try:
        sched = ReminderScheduler(app_ctx)
        app_ctx.reminder_scheduler = sched
        started = sched.start()
        logger.info("贴身提醒调度器初始化完成（定时: %s）",
                    "已启动" if started else "非 Qt 环境跳过")
        return True
    except Exception as exc:
        logger.warning("贴身提醒调度器初始化失败（不影响运行）: %s", exc)
        return False


def _diary_worker(app_ctx: AppContext) -> None:
    """女仆日记后台生成线程（daemon；Q-C6 次日启动补写昨日）。

    失败静默（should_write 仍 True 自然重试），绝不落占位假日记；
    退出不等待（守护线程，丢了次日重试即可，无一致性问题）。
    """
    try:
        from diary import (build_diary_payload, build_diary_prompt,
                           extract_diary_content, should_write)
        mgr = getattr(app_ctx, "diary", None)
        if mgr is None:
            return
        memory = getattr(getattr(app_ctx, "session", None), "memory_mgr", None)
        highlights = None
        try:
            from gui.pages.page_memories import get_highlights_manager
            highlights = get_highlights_manager(app_ctx)
        except Exception:
            highlights = None
        role_name = "码铃"
        try:
            from gui.pages.page_role import RoleManager
            role = RoleManager().default_role
            if role is not None and getattr(role, "name", ""):
                role_name = role.name
        except Exception:
            role_name = "码铃"
        stage = ""
        diary_tone = False
        try:  # F5 特权表消费（信赖阶段 → 日记口吻更亲密）
            companion = getattr(app_ctx, "companion", None)
            if companion is not None and callable(
                    getattr(companion, "relation_stage_name", None)):
                stage = str(companion.relation_stage_name() or "")
            tracker = getattr(app_ctx, "intimacy", None)
            if tracker is not None and callable(
                    getattr(tracker, "stage_privileges", None)):
                diary_tone = bool(tracker.stage_privileges().get("diary_tone"))
        except Exception:
            stage, diary_tone = "", False
        payload = build_diary_payload(
            memory_mgr=memory, highlights_mgr=highlights,
            companion=getattr(app_ctx, "companion", None), role_name=role_name)
        if not should_write(mgr, payload):
            return
        api = getattr(app_ctx, "api", None)
        if api is None or not callable(getattr(api, "chat", None)):
            return
        resp = api.chat([{"role": "user", "content":
                          build_diary_prompt(payload, stage=stage,
                                            diary_tone=diary_tone)}],
                        max_tokens=500, temperature=0.8)
        content = ""
        try:
            content = extract_diary_content(
                resp["choices"][0]["message"]["content"])
        except Exception:
            content = ""
        if not content:
            return  # 绝不落占位假日记
        mood = str(payload.get("mood_word", "") or "")
        if mgr.add_entry(payload["date"], role_name, mood, content):
            logger.info("女仆日记已生成（%s）", payload["date"])
    except Exception as exc:
        logger.debug("女仆日记生成失败（次日自然重试）: %s", exc)


def _init_diary(app_ctx: AppContext) -> bool:
    """v1.7(F7/D-V17-05): 装配女仆日记（DiaryManager 单例 + 后台补写线程）。

    - 默认开、GuiConfig.diary_enabled 可关（Q-C2）；关闭时静默跳过；
    - 每日一句不存在补写并发：单 daemon 线程一次性检查（weekly 同款挂载）。
    """
    try:
        from diary import DiaryManager
        cfg = getattr(app_ctx, "config", None)
        if cfg is not None and not bool(getattr(cfg, "diary_enabled", True)):
            logger.info("女仆日记已关闭（diary_enabled=False，Q-C2）")
            return False
        app_ctx.diary = DiaryManager()
    except Exception as exc:
        logger.warning("DiaryManager 初始化失败（女仆日记降级）: %s", exc)
        return False
    try:
        import threading
        thread = threading.Thread(target=_diary_worker, args=(app_ctx,),
                                  daemon=True, name="maid-diary")
        app_ctx.diary_thread = thread
        thread.start()
        logger.info("女仆日记补写线程已启动（daemon）")
        return True
    except Exception as exc:
        logger.warning("女仆日记线程启动失败（不影响运行）: %s", exc)
        return False


def _init_tts(app_ctx: AppContext) -> None:
    """v1.3(P1-1): 装配 app 级 TTS 单例（gui/tts.py，PySide6.QtTextToSpeech/SAPI）。

    必须在 ChatPanel 构造（MainWindow）之前挂好，供面板订阅朗读按钮态；
    后端缺失/无可用语音 = degraded（available False + availability_reason），绝不崩。
    """
    try:
        from gui.tts import TTSController
        tts = TTSController(app_ctx)
        app_ctx.tts = tts
        tts.start()
        logger.info("TTS 语音控制器初始化完成（可用: %s%s）",
                    tts.available,
                    f"，原因: {tts.availability_reason}" if tts.degraded else "")
    except Exception as exc:
        logger.warning("TTS 语音控制器初始化失败（不影响运行）: %s", exc)
        app_ctx.tts = None


def _mount_v13_services(app: QApplication, app_ctx: AppContext) -> None:
    """v1.3(P1-3/P1-4): 主窗显示后一次性装配 —— 托盘/热键/Idle 监视（各 try/except 不阻断）。

    方法级分区（design-v13 §3.2）：与 P1-4 的 main 装配同文件、分方法落位；
    顺序依赖：MainWindow/ChatService/Scheduler 均已就绪。
    """
    # ---- P1-3: app 级单一托盘（D-V13-01/D-V13-10）+ quitOnLastWindowClosed 联动 ----
    try:
        from gui.tray_manager import TrayManager
        app_ctx.tray_manager = TrayManager(app_ctx)
    except Exception as exc:
        logger.warning("系统托盘初始化失败（主窗 X 保持直退）: %s", exc)
        app_ctx.tray_manager = None

    try:
        from gui.qt_compat import QSystemTrayIcon  # noqa: F401
        tray = getattr(app_ctx, "tray_manager", None)
        tray_ok = tray is not None and callable(getattr(tray, "is_available", None)) \
            and bool(tray.is_available())
        close_quits = bool(getattr(app_ctx.config, "close_quits", False))
        # D-V13-11：随 close_quits 联动；无托盘环境恢复 True 防「关窗后退不掉」
        app.setQuitOnLastWindowClosed(close_quits or not tray_ok)
        logger.info("quitOnLastWindowClosed 已按 close_quits=%s / 托盘=%s 设置", close_quits, tray_ok)
    except Exception as exc:
        logger.warning("quitOnLastWindowClosed 设置失败: %s", exc)

    # ---- P1-3: 全局热键（toggle = Ctrl+Alt+M 默认 / screenshot = Ctrl+Alt+S 默认）----
    try:
        from gui.hotkeys import HotkeyManager
        hk = HotkeyManager(app_ctx)
        app_ctx.hotkeys = hk
        gui_config = getattr(app_ctx, "config", None)

        def _toggle_main() -> None:
            mw = getattr(app_ctx, "main_window", None)
            if mw is not None and hasattr(mw, "toggle_visibility"):
                try:
                    mw.toggle_visibility()
                except Exception:
                    pass

        def _screenshot_capture() -> None:
            mw = getattr(app_ctx, "main_window", None)
            panel = getattr(mw, "chat_panel", None) if mw is not None else None
            if panel is not None and hasattr(panel, "capture_screenshot"):
                try:
                    panel.capture_screenshot()
                except Exception:
                    pass

        hk.register("toggle", getattr(gui_config, "hotkey_toggle", "Ctrl+Alt+M"), _toggle_main)
        hk.register("screenshot",
                    getattr(gui_config, "hotkey_screenshot", "Ctrl+Alt+S"), _screenshot_capture)

        def _on_hotkey_state(name: str, ok: bool) -> None:
            if ok:
                return
            mw = getattr(app_ctx, "main_window", None)
            if mw is None or getattr(mw, "status_bar", None) is None:
                return
            try:
                mw.status_bar.showMessage(
                    f"⚠️ 全局热键 {name} 注册失败（可能被占用），可在设置中更换", 8000)
            except Exception:
                pass

        try:
            hk.hotkey_registered.connect(_on_hotkey_state)
        except Exception:
            pass
        logger.info("全局热键管理器初始化完成（toggle=%s, screenshot=%s）",
                    getattr(gui_config, "hotkey_toggle", "Ctrl+Alt+M"),
                    getattr(gui_config, "hotkey_screenshot", "Ctrl+Alt+S"))
    except Exception as exc:
        logger.warning("全局热键初始化失败（不影响运行）: %s", exc)
        app_ctx.hotkeys = None

    # ---- P1-4: 系统 Idle 监视（crossing -> scheduler.on_system_idle_return 四重闸）----
    try:
        from gui.system_idle import SystemIdleMonitor
        monitor = SystemIdleMonitor(app_ctx)
        app_ctx.idle_monitor = monitor
        scheduler = getattr(app_ctx, "proactive_scheduler", None)
        if scheduler is not None and hasattr(scheduler, "on_system_idle_return"):
            monitor.returned.connect(scheduler.on_system_idle_return)
        else:
            logger.warning("proactive_scheduler 未就绪，Idle 问候不接线")
        monitor.start()
        logger.info("系统 Idle 监视已挂载（阈值 %s 分钟）", monitor.threshold_minutes)
    except Exception as exc:
        logger.warning("系统 Idle 监视挂载失败（不影响运行）: %s", exc)
        app_ctx.idle_monitor = None


def _mount_v14_services(app: QApplication, app_ctx: AppContext) -> None:
    """v1.4（V-1.4-0 预编汇交点，docs/design-v14.md §3.2）：主窗显示后 v1.4 服务挂载钩子。

    ⚠️ 汇交点契约：本钩子为 v1.4 挂载点，主体由 **B 线**实施（B 域 screen_watch/
    screen_grab/computer_use 等服务挂载 + quit 生命周期卫生补 screen_watch.stop）。
    A 线番茄钟（gui/pomodoro）为懒挂载 app 级单例，由首页/托盘入口首次打开时
    装配，不走本钩子，故 A 线不再改 main.py（见 _mount_v14_a_services 注释）。
    """
    # ---- B 线挂载（懒 import + try/except 守卫；服务未创建/未接线时仅记日志，绝不阻断启动）----
    try:
        _mount_v14_b_screen(app, app_ctx)
    except Exception as exc:
        logger.warning("v1.4 B 线服务挂载失败（不影响运行）: %s", exc)
    # ---- A 线占位（无需启动即挂 pomodoro；如需可在此接 get_pomodoro_controller + quit 卫生）----
    try:
        _mount_v14_a_services(app, app_ctx)
    except Exception as exc:
        logger.warning("v1.4 A 线服务挂载失败（不影响运行）: %s", exc)


def _quit_stop_services(app_ctx: AppContext) -> None:
    """quit 生命周期卫生（v1.6.1 完整退出序列，防退出竞态 fail-fast 崩溃）。

    顺序契约：先停产生事件的源（QTimer / worker 线程 / 音频），再动 UI 对象。
    每步 try/except 独立包裹（单步失败不阻断后续），日志留 QUIT-stop-* 轨迹。
    幂等：托盘退出（tray._on_quit）已调 chat_service.shutdown()，此处重复无害。
    """
    # 1) proactive_scheduler：QTimer.stop（aboutToQuit 在主线程 ✓；防退出后 tick 再触 UI/交付）
    try:
        sched = getattr(app_ctx, "proactive_scheduler", None)
        if sched is not None and callable(getattr(sched, "stop", None)):
            sched.stop()
            logger.info("QUIT-stop-scheduler: proactive_scheduler 已停")
    except Exception as exc:
        logger.warning("QUIT-stop-scheduler 失败（继续）: %s", exc)
    # 1b) v1.7(F4): 贴身提醒调度器 QTimer（同上，防退出后 tick 再触通知/气泡）
    try:
        rsched = getattr(app_ctx, "reminder_scheduler", None)
        if rsched is not None and callable(getattr(rsched, "stop", None)):
            rsched.stop()
            logger.info("QUIT-stop-reminders: reminder_scheduler 已停")
    except Exception as exc:
        logger.warning("QUIT-stop-reminders 失败（继续）: %s", exc)
    # 2) chat_service：停流式 worker（stop_current + QThread.wait(5000) 超时保护，不永久阻塞）
    try:
        cs = getattr(app_ctx, "chat_service", None)
        if cs is not None and callable(getattr(cs, "shutdown", None)):
            cs.shutdown()
            logger.info("QUIT-stop-chat: chat_service worker 已收尾")
    except Exception as exc:
        logger.warning("QUIT-stop-chat 失败（继续）: %s", exc)
    # 3) voice_conversation：停免提（释放麦克风、断 worker、停本归属朗读）
    try:
        vc = getattr(app_ctx, "voice_conversation", None)
        if vc is not None and callable(getattr(vc, "shutdown", None)):
            vc.shutdown()
            logger.info("QUIT-stop-voice: voice_conversation 已停")
    except Exception as exc:
        logger.warning("QUIT-stop-voice 失败（继续）: %s", exc)
    # 4) TTS 控制器兜底：停任何归属的朗读后端（免提停读只覆盖自己的 owner）
    try:
        tts = getattr(app_ctx, "tts", None)
        if tts is not None and callable(getattr(tts, "shutdown", None)):
            tts.shutdown()
            logger.info("QUIT-stop-tts: TTS 控制器已停")
    except Exception as exc:
        logger.warning("QUIT-stop-tts 失败（继续）: %s", exc)
    # 5) B 线 ScreenWatch 停采弃帧 + A 线番茄钟控制器（v1.4 既有卫生，幂等）
    svc = getattr(app_ctx, "screen_watch", None)
    if svc is not None:
        try:
            shutdown = getattr(svc, "shutdown", None)
            if callable(shutdown):
                shutdown()
            elif callable(getattr(svc, "stop", None)):
                svc.stop(discard=True)
            logger.info("QUIT-stop-screen: ScreenWatch 已停采")
        except Exception as exc:
            logger.warning("QUIT-stop-screen 失败（继续）: %s", exc)
    try:
        from gui.pomodoro import get_pomodoro_controller
        ctrl = getattr(app_ctx, "pomodoro", None) or get_pomodoro_controller(app_ctx)
        if ctrl is not None and callable(getattr(ctrl, "shutdown", None)):
            ctrl.shutdown()
    except Exception as exc:
        logger.warning("退出时番茄钟控制器停表失败: %s", exc)
    # 6) v2.0(D-V20-09/V20-13): 更新编排末步 —— 待安装且校验通过则写 plan.json 并拉起 sidecar。
    #    ⚠ 严格追加在既有 5 步之后（既有顺序与实现零变更，R-D）；本步 try/except，失败静默。
    try:
        _maybe_launch_updater(app_ctx)
    except Exception as exc:
        logger.warning("QUIT-launch-updater 失败（继续退出）: %s", exc)


def _mount_v14_b_screen(app: QApplication, app_ctx: AppContext) -> None:
    """v1.4 B 线：ScreenWatchService / ComputerUseController app 级单例挂载 + 退出卫生。

    懒 import（模块缺失/导入失败降级记日志）；chat_panel/page_settings 仍走
    get_screen_watch_service 取同一实例；aboutToQuit 时 svc.shutdown 弃帧停表。
    """
    try:
        from gui.screen_watch import get_screen_watch_service
        svc = get_screen_watch_service(app_ctx)
        if svc is not None:
            app_ctx.screen_watch = svc
            logger.info("v1.4 ScreenWatch 服务实例就绪（未开启，等用户触发）")
        else:
            logger.warning("v1.4 ScreenWatch 服务实例创建失败（看屏入口将显示不可用）")
    except Exception as exc:
        logger.warning("v1.4 ScreenWatch 服务挂载失败（不影响运行）: %s", exc)
        app_ctx.screen_watch = None
    try:
        from gui.computer_use import get_computer_use_controller
        ctrl = get_computer_use_controller(app_ctx)
        app_ctx.computer_use = ctrl if ctrl is not None else None
    except Exception as exc:
        logger.warning("v1.4 ComputerUse 控制器挂载失败（不影响运行）: %s", exc)
        app_ctx.computer_use = None
    # quit 生命周期卫生：app 退出即停采弃帧（幂等）
    try:
        app.aboutToQuit.connect(lambda: _quit_stop_services(app_ctx))
    except Exception as exc:
        logger.warning("v1.4 quit 卫生接线失败: %s", exc)


def _mount_v14_a_services(app: QApplication, app_ctx: AppContext) -> None:
    """v1.4 A 线：番茄钟为懒挂载 app 级单例（首页/托盘首次打开时装配）。

    此处不预创建控制器，避免启动即起常驻 tick；仅登记 quit 卫生，确保退出时
    若有运行中的一轮能回落 idle（_quit_stop_services 内已做 get_pomodoro_controller
    守卫式 shutdown，controller 从未创建时 getter 会懒建后立刻 shutdown，幂等无害）。
    """



# ===========================================================================
# v2.0(域4): 自动更新编排层（design-v20 §5 批 C · V20-12/13/14）
#   - 纯函数（_app_version/_compute_install_targets/_build_swap_plan/
#     _should_launch_updater/_select_download_asset）可被 pytest 直接断言；
#   - 全部编排入口 try/except 包裹：失败只记日志、静默降级（R-N）。
# ===========================================================================
def _app_version() -> str:
    """本地版本号（单一来源 version.py → core.__version__，禁止硬编码）。"""
    try:
        from version import get_version
        return str(get_version())
    except Exception:
        try:
            from core import __version__  # type: ignore
            return str(__version__)
        except Exception:
            return "0.0.0"


def _compute_install_targets(form: str, exe_path=None, project_dir=None) -> dict:
    """纯函数：按安装形态推导 `{app_exe, install_dir, install_parent}`。

    - onedir : exe 所在目录即安装目录 `<parent>/maling` → install_parent=`<parent>`；
    - onefile: exe 即替换目标，install_dir=exe 所在目录；
    - dev    : 用项目根占位（仅展示 / 测试用，绝不用于替换）。
    staging/backup 落 install_parent 下 → 同卷（D-V20-02 铁律）。
    """
    if form == "dev":
        base = Path(str(project_dir or os.getcwd())).resolve()
        return {
            "app_exe": str(base / "run.py"),
            "install_dir": str(base),
            "install_parent": str(base.parent),
        }
    exe = Path(str(exe_path or sys.executable)).resolve()
    install_dir = exe.parent
    return {
        "app_exe": str(exe),
        "install_dir": str(install_dir),
        "install_parent": str(install_dir.parent),
    }


def _build_swap_plan(*, target_version: str, from_version: str, app_pid: int,
                     app_exe: str, install_dir: str, package_path: str,
                     package_sha256: str, confirm_dir: str,
                     action: str = "swap_onedir", log_path: str = "",
                     confirm_timeout_sec: int = 45, kill_timeout_sec: int = 20) -> dict:
    """纯函数：构造 sidecar plan.json（design §4.4 逐字段）。

    ⚠ 同卷铁律：`staging_dir` / `backup_dir` 一律落 `install_parent`（**不是** %APPDATA%，
    那是 C 盘、与安装目录可能不同卷 → rename 退化为复制、破坏原子性）。
    onefile 形态 `staging_dir=None`（无目录级 staging）、`backup_dir=None`。
    """
    install_dir_p = Path(str(install_dir))
    parent = install_dir_p.parent
    onefile = str(action) == "swap_onefile"
    return {
        "schema": 1,
        "action": str(action),
        "target_version": str(target_version),
        "from_version": str(from_version),
        "app_pid": int(app_pid),
        "app_exe": str(app_exe),
        "install_dir": str(install_dir_p),
        "install_parent": str(parent),
        "package_path": str(package_path),
        "package_sha256": str(package_sha256),
        "staging_dir": (None if onefile
                        else str(parent / f".maling_new_{target_version}")),
        "backup_dir": (None if onefile
                       else str(parent / f".maling_backup_{from_version}")),
        "confirm_dir": str(confirm_dir),
        "confirm_timeout_sec": int(confirm_timeout_sec),
        "kill_timeout_sec": int(kill_timeout_sec),
        "log_path": str(log_path),
    }


def _should_launch_updater(state: dict, form: str, *,
                           package_verified: bool = False,
                           install_writable: bool = False,
                           min_updatable_block: bool = False) -> bool:
    """纯函数：退出时是否拉起 sidecar 换包（D-V20-09 守卫）。

    守卫：形态 ∈ {onedir, onefile}（dev 一律禁止替换） ∧ pending_install ∧
    pending_version 非空 ∧ 包已通过 sha256 ∧ 安装目录可写 ∧
    本地不低于远端 min_updatable（能力闸）。
    """
    if min_updatable_block:
        return False
    if form not in ("onedir", "onefile"):
        return False
    if not isinstance(state, dict):
        return False
    if not state.get("pending_install"):
        return False
    if not str(state.get("pending_version") or "").strip():
        return False
    return bool(package_verified) and bool(install_writable)


def _select_download_asset(remote, info, form: str):
    """纯函数：选定下载资产。返回 `(asset, reason)`。

    reason ∈ {"ok", "no_asset", "no_sha256"}：
    - "ok"       → 可进入下载 / 自动替换链；
    - "no_sha256"→ Q-U5：sha256 缺失/非法 → **禁止自动替换**，仅提示手动下载；
    - "no_asset" → 无可用资产（remote 无 assets 且 info 无 primary）→ 仅提示手动下载。
    remote 为原始 version.json（含 assets）；捕获失败（None）时以 info.primary 合成兜底
    （无 sha256）。form=="dev" 时 asset_for_form 按 onedir 演练。
    """
    asset = asset_for_form(remote, form) if isinstance(remote, dict) else None
    if asset is None and isinstance(info, dict):
        # 域1(v2.0) 已让 evaluate_update 载荷含 assets；优先原始 remote，回退载荷
        asset = asset_for_form(info, form)
    if asset is None:
        # 兜底：用 info.primary（downloads.github，旧式指针）合成最简 asset（无 sha256）
        primary = str((info or {}).get("primary") or "").strip()
        if not primary:
            return None, "no_asset"
        asset = {
            "url": primary,
            "mirror": str((info or {}).get("mirror") or "").strip(),
        }
    if not has_valid_sha256(asset):
        return asset, "no_sha256"
    return asset, "ok"


def _below_min_updatable(remote, local_version: str, info=None) -> bool:
    """纯函数：本地版本 < 远端 `min_updatable` → 禁止自动替换（D-V20-02 能力闸）。

    与 `min_compatible` **正交**：前者决定"提示怎么说"、本闸决定"能不能自动换"。
    `min_updatable` 缺失 / 非法 / 两边都拿不到 → False（不限制，保持现状）。
    从 `remote` 读取，取不到再回退 `info`（域1 已让载荷含 min_updatable）。
    """
    value = None
    for src in (remote, info):
        if isinstance(src, dict):
            v = src.get("min_updatable")
            if isinstance(v, str) and v.strip():
                value = v.strip()
                break
    if not value:
        return False
    try:
        from core import parse_version
        return parse_version(str(local_version)) < parse_version(value)
    except (TypeError, ValueError):
        return False


def _can_auto_update(info, reason: str, remote=None) -> bool:
    """纯函数：是否允许进入「自动下载 / 自动替换」链。

    - `kind=="reinstall"`（本地低于 min_compatible，须整包重装）→ 否；
    - 本地低于远端 `min_updatable`（能力闸）→ 否；
    - `reason != "ok"`（无资产 / 无 sha256）→ 否（Q-U5 安全优先）。
    """
    if str((info or {}).get("kind") or "update") == "reinstall":
        return False
    if _below_min_updatable(remote, _app_version(), info=info):
        return False
    return reason == "ok"


def _resolve_remote():
    """取原始 version.json：读域1 公开属性 `UpdateChecker.last_remote`。

    域1 已保证该属性在每次 fetch 成功后、emit 之前刷新（update_checker._on_fetched），
    是跨多次检查的唯一正确来源；未成功过 / 非 dict → None。此前对私有 `_worker` 的
    过渡期捕获已摘除（消除对域1 私有实现的耦合）。
    """
    try:
        checker = _update_ctx.get("checker")
        remote = getattr(checker, "last_remote", None) if checker is not None else None
        return remote if isinstance(remote, dict) else None
    except Exception:
        return None


def _release_page_url(info) -> str:
    """纯函数：载荷中可用于「查看完整更新内容」的 Release 页 URL。

    仅当 `release_url` 存在且为 https 时返回，否则返回 ""（调用方据此不出按钮）。
    design-v20 §4.1：`release_url` = Release 页入口，可选、缺失时载荷为 None。
    """
    url = str((info or {}).get("release_url") or "").strip()
    return url if url.startswith("https://") else ""


def _open_external_url(url: str) -> None:
    """用系统默认浏览器打开 URL（独立成函数，便于测试 monkeypatch、不真开浏览器）。"""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(str(url)))
    except Exception as exc:
        logger.info("打开外部链接失败（忽略）: %s", exc)


def _maybe_open_release_page(info, opener=None) -> bool:
    """纯逻辑：载荷含可用 Release 页 URL → 调 opener 打开；返回是否已处理。

    opener 可注入（默认 `_open_external_url`），供测试断言路由而不真开浏览器。
    """
    url = _release_page_url(info)
    if not url:
        return False
    (opener or _open_external_url)(url)
    return True


def _bootstrap_update_subsystem(app_ctx: AppContext) -> dict:
    """v2.0 启动早期：sidecar 自举 + 消费上轮换包结果 + onefile `.old` 清理。

    design §5 V20-12/V20-14/D-V20-06/D-V20-08：
    - form == "dev"（源码态）→ **禁用一切自动替换路径**，不复制 sidecar；
    - onedir/onefile → `ensure_self_installed`（幂等，失败不阻断）；
    - 消费 `last_result.json` → 合并进 `update_state.last_install`（R-A：只在设置页留一句）；
    - onefile → `purge_old_files(sys.executable)` 清理上一轮 `.old`。
    返回当前 update_state（供检查段复用）。全程 try/except，失败静默（R-N）。
    """
    state: dict = {}
    try:
        state = load_update_state()
    except Exception as exc:
        logger.info("读取更新状态失败（忽略）: %s", exc)

    form = "dev"
    try:
        form = detect_install_form()
    except Exception as exc:
        logger.info("更新形态探测失败（按 dev 降级、禁用替换）: %s", exc)
    app_ctx.update_install_form = form

    if form == "dev":
        logger.info("更新子系统：源码/dev 形态，禁用自动替换（仅检查与下载演练）")
        return state

    # 1) sidecar 自举（幂等：大小+sha 一致则跳过、不改 mtime）
    try:
        from gui.utils import get_resource_path, get_user_data_dir
        from maling_updater import ensure_self_installed
        src_dir = get_resource_path("updater")
        dest_dir = get_user_data_dir() / "updater"
        ensure_self_installed(str(src_dir), str(dest_dir))
    except Exception as exc:
        logger.info("sidecar 自举失败（忽略，将不自动替换）: %s", exc)

    # 2) 消费上轮换包结果（读后删，幂等）
    try:
        from gui.utils import get_user_data_dir
        from maling_updater import consume_last_result
        confirm_dir = get_user_data_dir() / "updater"
        res = consume_last_result(str(confirm_dir))
        if isinstance(res, dict):
            # ⚠ 换包已有结论（success/failed/rolled_back）→ 必须清掉待安装标记：
            #   否则新版下次退出仍满足守卫 → 重复拉起 sidecar 自我覆盖（自替换循环）。
            save_update_state({
                "last_install": res,
                "pending_install": False,
                "pending_version": "",
            })
            state = load_update_state()
            try:
                app_ctx.update_last_install = res
            except Exception:
                pass
            # R-A：不在聊天区/首页弹错，只在设置页留一句（last_install 已落盘供设置页读）
            logger.info("上轮更新结果：result=%s version=%s",
                        res.get("result"), res.get("version"))
    except Exception as exc:
        logger.info("消费上轮换包结果失败（忽略）: %s", exc)

    # 3) onefile：清理上一轮 `<exe>.old`（失败留待下次）
    if form == "onefile":
        try:
            from maling_updater import purge_old_files
            purge_old_files(sys.executable)
        except Exception as exc:
            logger.info("清理 .old 失败（忽略）: %s", exc)

    return state


def _arm_confirm_handshake(app: QApplication, app_ctx: AppContext) -> None:
    """v2.0 §4.5：UI 就绪举手（sidecar 回滚判定的**唯一主判据**）。

    在 `window.show()` 之后经 `QTimer.singleShot(0, …)` 触发——此时事件循环已跑通一次，
    最接近"用户真的能用"的时点。dev 形态跳过。
    """
    try:
        form = getattr(app_ctx, "update_install_form", None) or detect_install_form()
        if form == "dev":
            return
        from gui.utils import get_user_data_dir
        from maling_updater import write_confirmed
        from gui.qt_compat import QTimer
        confirm_dir = str(get_user_data_dir() / "updater")
        version = _app_version()
        pid = os.getpid()

        def _do() -> None:
            try:
                write_confirmed(confirm_dir, version, pid)
                logger.info("更新举手：confirmed.json 已写（version=%s pid=%s）", version, pid)
            except Exception as exc:
                logger.info("更新举手失败（忽略）: %s", exc)

        QTimer.singleShot(0, _do)
    except Exception as exc:
        logger.warning("更新举手装配失败（忽略）: %s", exc)


def _start_update_check(app_ctx: AppContext, window, state=None) -> None:
    """v2.0(D-V20-14 / L1-1)：启动检查段——24h 节奏闸 + 生效频道。

    主窗已显示后异步发起；失败/离线/超时一律静默（不弹窗，R-A）。
    频道优先级：GuiConfig.update_channel > update_state.channel > stable。
    """
    try:
        cfg = getattr(app_ctx, "config", None)
        if state is None:
            state = load_update_state()
        channel = resolve_effective_channel(
            getattr(cfg, "update_channel", "") if cfg is not None else "",
            state.get("channel"),
        )
        auto_check = bool(getattr(cfg, "auto_check", True)) if cfg is not None else True
        if not (auto_check and should_check_now(state)):
            logger.info("更新检查：节奏闸未放行（auto_check=%s）", auto_check)
            return
        try:
            save_update_state({
                "last_checked": datetime.now().isoformat(timespec="seconds"),
                "channel": channel,
            })
        except Exception:
            pass
        checker = UpdateChecker(parent=window, channel=channel)
        _update_ctx["checker"] = checker
        checker.update_available.connect(
            lambda info: _show_update_prompt(app_ctx, info, window))
        checker.check_finished.connect(
            lambda status: logger.info("更新检查完成：%s", status))
        checker.start()
        # 原始 version.json（含 assets/sha256）由域1 公开属性 `last_remote` 提供，
        # 不再连接私有 `_worker`——消除对域1 私有实现的耦合（_resolve_remote 只读公开属性）。
    except Exception as exc:
        logger.info("更新检查初始化失败（不影响启动）: %s", exc)


def _show_update_prompt(app_ctx: AppContext, info: dict, window=None) -> None:
    """v2.0 提示卡·发现新版态（非阻断，R-A）。

    - 可自动更新（`_can_auto_update`）：`立即下载` / `稍后` / `忽略此版本`；
    - sha256 缺失 / 无资产 / `kind==reinstall` / 低于 `min_updatable`：
      `复制下载链接` / `稍后` / `忽略此版本`，绝不进下载/替换链（Q-U5 / 能力闸）；
    - 两态共同：载荷含 https 的 `release_url` 时追加 `查看完整更新内容`（开 Release 页）；
    - `cfg.auto_download` 为真且可自动更新时后台静默开始下载（安装仍需确认，Q-U9）。
    """
    from gui.qt_compat import QMessageBox, QApplication
    if not isinstance(info, dict):
        return
    version = str(info.get("version") or "")
    cfg = getattr(app_ctx, "config", None)
    form = getattr(app_ctx, "update_install_form", None) or detect_install_form()
    remote = _resolve_remote()
    _asset, reason = _select_download_asset(remote, info, form)
    too_old = _below_min_updatable(remote, _app_version(), info=info)
    auto_ok = _can_auto_update(info, reason, remote=remote)

    box = QMessageBox(window)
    box.setWindowTitle("码铃更新")
    text = format_update_text(info)
    if too_old:
        text = text + "\n\n当前版本过旧，无法自动替换，建议重新下载安装。"
    elif reason != "ok":
        text = text + "\n\n发现新版（无法校验），建议手动下载安装。"
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Information)

    download_btn = None
    copy_btn = None
    if auto_ok:
        download_btn = box.addButton("立即下载", QMessageBox.ButtonRole.AcceptRole)
    else:
        copy_btn = box.addButton("复制下载链接", QMessageBox.ButtonRole.ActionRole)
    # 兑现 design-v20 §4.1：`release_url` 有值（且 https）时给「查看完整更新内容」入口，
    # 「发现新版（未下载）」与「无法自动替换」两态都会出现该按钮；缺失 / 非 https 则不出。
    release_btn = None
    if _release_page_url(info):
        release_btn = box.addButton("查看完整更新内容", QMessageBox.ButtonRole.ActionRole)
    box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
    ignore_btn = box.addButton("忽略此版本", QMessageBox.ButtonRole.ActionRole)
    box.setModal(False)  # R-A 非阻断

    def _on_button_clicked(btn):
        try:
            if download_btn is not None and btn is download_btn:
                _start_update_download(app_ctx, info, window)
            elif copy_btn is not None and btn is copy_btn:
                link = pick_download_link(info)
                if link:
                    QApplication.clipboard().setText(link)
            elif release_btn is not None and btn is release_btn:
                _maybe_open_release_page(info)
            elif btn is ignore_btn:
                save_ignored_version(version)
        except Exception as exc:
            logger.info("更新提示按钮处理失败（忽略）: %s", exc)

    box.buttonClicked.connect(_on_button_clicked)
    _active_update_prompts.append(box)
    box.show()

    # auto_download：后台静默开始（Q-U9：只影响下载，不影响安装确认）
    if auto_ok and bool(getattr(cfg, "auto_download", True)):
        _start_update_download(app_ctx, info, window)


def _start_update_download(app_ctx: AppContext, info: dict, window=None) -> None:
    """组装 DownloadWorker + 非模态进度卡并启动（L2；失败静默降级 R-N）。

    ⚠ 已知集成缺口必须显式注入：`allowed_check` 必须带 `extra_hosts`
    （含 `extract_host(cfg.mirror_url)`），否则用户自配镜像 host 会被 R-M 白名单拒绝、
    备用链整体失效（Q-U3）。
    """
    try:
        version = str(info.get("version") or "")
        if not version:
            return
        active = _update_ctx.get("download")
        if isinstance(active, dict) and active.get("version") == version:
            dlg = active.get("dialog")
            try:
                dlg.show()
                dlg.raise_()
            except Exception:
                pass
            return
        cfg = getattr(app_ctx, "config", None)
        form = getattr(app_ctx, "update_install_form", None) or detect_install_form()
        remote = _resolve_remote()
        asset, reason = _select_download_asset(remote, info, form)
        if asset is None or not _can_auto_update(info, reason, remote=remote):
            logger.info("下载未启动（资产不可用/不允许自动更新：%s）", reason)
            return

        from gui.update_downloader import (
            make_download_worker, make_allowed_check, disk_precheck, staging_dir_for,
        )
        use_mirror = bool(getattr(cfg, "use_mirror", True)) if cfg is not None else True
        mirror_url = str(getattr(cfg, "mirror_url", "") or "") if cfg is not None else ""
        extra = [h for h in [extract_host(mirror_url)] if h] if (use_mirror and mirror_url) else []

        # L2-6 磁盘空间预检：不足 → 不发第一个 GET，提示 + 打开文件夹兜底
        size = int(asset.get("size") or 0)
        staging = staging_dir_for(version)
        ok, _why = disk_precheck(str(staging), size)
        if not ok:
            _show_disk_space_hint(window, staging)
            return

        worker = make_download_worker(
            asset, version=version, use_mirror=use_mirror,
            allowed_check=make_allowed_check(extra_hosts=extra),
            parent=window,
        )
        from gui.widgets.update_progress import UpdateProgressDialog
        dlg = UpdateProgressDialog(app_ctx, parent=window)
        dlg.download_verified.connect(
            lambda path: _on_update_verified(app_ctx, version, asset, path, window))
        dlg.download_failed.connect(
            lambda reason_: _on_update_download_failed(app_ctx, reason_))
        dlg.begin(worker)  # 只连线 + show，不启线程
        _update_ctx["download"] = {
            "version": version, "worker": worker, "dialog": dlg,
            "asset": asset, "path": str(worker.dest_path),
        }
        worker.start()
    except Exception as exc:
        logger.info("启动下载失败（静默降级）: %s", exc)


def _on_update_verified(app_ctx: AppContext, version: str, asset: dict,
                        path: str, window=None) -> None:
    """校验通过 → 落 pending_install/download.verified → 提示「重启后启用」。

    worker **不写** update_state（D-V20-10 单一写者），状态写入必须由本回调用
    `save_update_state` 完成。
    """
    try:
        sha = str(asset.get("sha256") or "")
        filename = Path(str(path)).name
        is_single = str(asset.get("url") or "").lower().endswith(".exe")
        try:
            received = int(Path(str(path)).stat().st_size)
        except Exception:
            received = 0
        save_update_state({
            "pending_version": version,
            "pending_install": True,
            "download": {
                "version": version,
                "asset": "single" if is_single else "onedir",
                "filename": filename,
                "path": str(path),
                "part_path": str(path) + ".part",
                "received": received,
                "total": int(asset.get("size") or 0),
                "sha256": sha,
                "url_index": 0,
                "verified": True,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
        })
        _show_install_ready_prompt(app_ctx, version, window)
    except Exception as exc:
        logger.info("下载完成状态落盘失败（忽略）: %s", exc)


def _on_update_download_failed(app_ctx: AppContext, reason: str) -> None:
    """下载失败：R-A 无焦虑——只在设置页留一句可重试提示，不弹模态、不在聊天区报错。"""
    logger.info("更新下载未完成（设置页可重试）: %s", reason)
    try:
        app_ctx.update_last_download_error = str(reason)
    except Exception:
        pass


def _show_install_ready_prompt(app_ctx: AppContext, version: str, window=None) -> None:
    """下载完成待安装态：`立即重启安装` / `稍后（下次退出时安装）`（非阻断）。"""
    from gui.qt_compat import QMessageBox
    form = getattr(app_ctx, "update_install_form", None) or detect_install_form()
    box = QMessageBox(window)
    box.setWindowTitle("码铃更新")
    box.setIcon(QMessageBox.Icon.Information)
    box.setModal(False)
    restart_btn = box.addButton("立即重启安装", QMessageBox.ButtonRole.AcceptRole)
    if form == "dev":
        # D-V20-06：dev 形态禁用自动替换，如实标注（R-O）
        box.setText(f"v{version} 已下载并校验通过（开发模式，不自动替换）")
        try:
            restart_btn.setEnabled(False)
        except Exception:
            pass
    else:
        box.setText(f"v{version} 已下载并校验通过，重启后启用")
    box.addButton("稍后（下次退出时安装）", QMessageBox.ButtonRole.RejectRole)

    def _on_button_clicked(btn):
        if btn is restart_btn:
            _trigger_restart_install(app_ctx)

    box.buttonClicked.connect(_on_button_clicked)
    _active_update_prompts.append(box)
    box.show()


def _trigger_restart_install(app_ctx: AppContext) -> None:
    """「立即重启安装」→ 走**既有退出链**（D-V20-09：不新造退出逻辑，防退出竞态回归）。"""
    try:
        app_ctx.quitting = True
    except Exception:
        pass
    try:
        from gui.qt_compat import QApplication
        app = QApplication.instance()
        if app is not None:
            app.quit()
    except Exception as exc:
        logger.info("触发重启安装失败（忽略）: %s", exc)


def _show_disk_space_hint(window, staging) -> None:
    """磁盘空间不足：明确提示 +「打开文件夹」手动兜底（不启动下载）。"""
    try:
        from gui.qt_compat import QMessageBox
        box = QMessageBox(window)
        box.setWindowTitle("码铃更新")
        box.setText("磁盘空间不足，暂无法下载更新。可在设置页稍后重试。")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setModal(False)
        open_btn = box.addButton("打开文件夹", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)

        def _on_button_clicked(btn):
            if btn is open_btn:
                _open_folder(staging)

        box.buttonClicked.connect(_on_button_clicked)
        _active_update_prompts.append(box)
        box.show()
    except Exception as exc:
        logger.info("磁盘不足提示失败（忽略）: %s", exc)


def _open_folder(path) -> None:
    """打开目标文件夹（Windows 用 os.startfile；其它平台 xdg-open；失败静默）。"""
    try:
        target = str(path)
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
        else:
            import subprocess
            subprocess.Popen(["xdg-open", target])
    except Exception as exc:
        logger.info("打开文件夹失败: %s", exc)


def _launch_updater_process(updater_exe, plan_path, log_path) -> None:
    """detached 拉起 sidecar（team-lead 更正定稿：DETACHED_PROCESS | CREATE_NO_WINDOW）。

    主进程拉起后**立刻退出**，必须保证 sidecar 生命周期独立于父进程 →
    `DETACHED_PROCESS`（design D-V20-01 原案）。sidecar 只写日志文件、从不写 stdout，
    且标准流已显式置 DEVNULL，故 console=True 的 stdout 句柄失效担忧在本场景不存在。
    子进程不随父进程退出而终止 → 主进程退出后 sidecar 存活。
    """
    import subprocess
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW) \
        if os.name == "nt" else 0
    subprocess.Popen(
        [str(updater_exe), "--pid", str(os.getpid()),
         "--plan", str(plan_path), "--log", str(log_path)],
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(Path(str(updater_exe)).parent),
        creationflags=flags,
    )


def _maybe_launch_updater(app_ctx: AppContext) -> None:
    """退出编排末端：守卫 → 写 plan.json → 拉起 sidecar（D-V20-09 / V20-13）。

    ⚠ 只在 `_quit_stop_services` 既有 5 步**全部完成之后**调用（此时服务已停、UI 已拆、
    安装目录即将释放）。守卫不过（含 dev 形态）即静默跳过（R-N）。
    team-lead 核实：Pi 残留进程清理职责归 sidecar（`drain_install_dir_processes`），
    main.py 不新增 Pi 停机步。
    """
    state = load_update_state()
    form = getattr(app_ctx, "update_install_form", None) or detect_install_form()
    if form == "dev":
        logger.info("QUIT-launch-updater: dev 形态，跳过自动替换")
        return
    download = state.get("download") if isinstance(state.get("download"), dict) else {}
    package_path = str(download.get("path") or "")
    expected = str(download.get("sha256") or "")
    package_verified = False
    try:
        from gui.update_downloader import verify_sha256
        package_verified = bool(package_path) and os.path.isfile(package_path) \
            and verify_sha256(package_path, expected)
    except Exception as exc:
        logger.info("待安装包校验失败: %s", exc)
    targets = _compute_install_targets(form)
    install_dir = targets["install_dir"]
    install_writable = False
    try:
        from gui.update_downloader import is_install_writable
        install_writable = bool(is_install_writable(install_dir))
    except Exception as exc:
        logger.info("安装目录可写探测失败: %s", exc)
    # min_updatable 能力闸（与 min_compatible 正交）：本地过旧 → 禁止自动替换。
    min_updatable_block = _below_min_updatable(_resolve_remote(), _app_version())
    if not _should_launch_updater(state, form, package_verified=package_verified,
                                  install_writable=install_writable,
                                  min_updatable_block=min_updatable_block):
        logger.info(
            "QUIT-launch-updater: 守卫未通过（form=%s pending=%s verified=%s "
            "writable=%s min_updatable_block=%s）",
            form, state.get("pending_install"), package_verified, install_writable,
            min_updatable_block)
        return

    version = str(state.get("pending_version") or download.get("version") or "")
    try:
        from gui.utils import get_user_data_dir
        updater_dir = get_user_data_dir() / "updater"
    except Exception as exc:
        logger.info("定位 sidecar 目录失败: %s", exc)
        return
    updater_exe = updater_dir / "maling_updater.exe"
    if not updater_exe.is_file():
        logger.info("sidecar 缺失，跳过自动替换: %s", updater_exe)
        return

    from_version = _app_version()
    action = "swap_onefile" if form == "onefile" else "swap_onedir"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_dir = updater_dir / "plans"
    log_dir = updater_dir / "logs"
    plan = _build_swap_plan(
        target_version=version, from_version=from_version, app_pid=os.getpid(),
        app_exe=targets["app_exe"], install_dir=install_dir,
        package_path=package_path, package_sha256=expected,
        confirm_dir=str(updater_dir), action=action,
        log_path=str(log_dir / f"updater_{version}_{ts}.log"),
    )
    try:
        plan_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.info("创建 sidecar 目录失败: %s", exc)
    plan_path = plan_dir / f"plan_{version}_{ts}.json"
    try:
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.info("写 plan.json 失败（跳过自动替换）: %s", exc)
        return
    try:
        _launch_updater_process(updater_exe, plan_path, Path(plan["log_path"]))
        logger.info("QUIT-launch-updater: sidecar 已拉起 plan=%s action=%s",
                    plan_path, action)
    except Exception as exc:
        logger.warning("QUIT-launch-updater: 拉起 sidecar 失败: %s", exc)


def main() -> int:
    """GUI 应用入口。"""
    # 高 DPI 适配
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("MaLing")
    app.setApplicationDisplayName("码铃")
    # v1.4.0-勘: 退出留痕——谁触发退出，看日志里最后一条 QUIT-* 记录
    try:
        app.aboutToQuit.connect(
            lambda: logger.info("QUIT-aboutToQuit: 进程即将退出（上方最后一条 QUIT-* 即触发源）")
        )
    except Exception:
        pass
    # 应用图标：窗口标题栏 + Windows 任务栏 + 任务切换（malingic 内置多尺寸，
    # Qt 按 DPI 自动选用；spec datas 已含 assets 目录，PyInstaller 打包后路径一致）
    try:
        app.setWindowIcon(QIcon(str(get_resource_path("assets/maling.ico"))))
    except Exception as e:
        logger.warning("应用图标加载失败（不影响运行）: %s", e)
    # Windows 任务栏分组需稳定的 AppUserModelID（避免图标被系统默认 exe 图标覆盖）
    try:
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.setOrganizationName("maid_coder")
        QCoreApplication.setApplicationName("MaLing")
    except Exception:
        pass

    _setup_logging()
    logger.info("码铃 GUI 启动中...")

    # 加载 GUI 配置
    gui_config = GuiConfig.load()

    # v1.9 B/D-V19-05: 注册内置字体（资源圆体 / jf open 粉圆）—— 必须在 MainWindow
    # 构造（其内 load_theme 取 family）之前；缺字体文件 / 注册失败均静默回退不阻断。
    try:
        from gui import fonts
        registered = fonts.register_bundled_fonts()
        logger.info("内置字体注册完成: %s", registered)
    except Exception as exc:
        logger.warning("内置字体注册失败（回退系统字体，不影响运行）: %s", exc)

    # 构建 AppContext
    app_ctx = AppContext()
    app_ctx.config = gui_config
    app_ctx.project_dir = os.getcwd()
    # v1.3(P1-3): quit 单一编舞标志 + main_window 引用占位（D-V13-11）
    app_ctx.quitting = False
    app_ctx.main_window = None

    # 初始化 CLI 核心（零侵入，失败不阻断）
    _init_cli_core(app_ctx)

    # v1.2 A1: 装配 companion 陪伴域 + 心情广播桥（失败不阻断启动）
    _init_companion(app_ctx)

    # v10.13: 应用角色面板已保存的默认角色覆盖（未定制时不改变行为）
    try:
        from gui.pages.page_role import apply_role_override_on_startup
        if apply_role_override_on_startup(app_ctx):
            logger.info("已应用角色面板的默认角色覆盖")
    except Exception as exc:
        logger.warning("角色覆盖启动应用失败（不影响运行）: %s", exc)

    # v1.4.x(Bug8): GUI 侧开启表情指南注入（session._build_system_prompt 末尾
    # 单点追加；CLI 会话不受影响）。此前指南依赖角色面板 sync 注入，用户从未
    # 打开角色面板时模型收不到指南 → 表情标记输出率低。
    try:
        _session = getattr(app_ctx, "session", None)
        if _session is not None and hasattr(_session, "expr_guide_enabled"):
            _session.expr_guide_enabled = True
            # 立即按新开关重建 system（首次启动尚未开过角色面板也能收到指南）
            if callable(getattr(_session, "_update_system", None)):
                _session._update_system()
    except Exception as exc:
        logger.warning("表情指南注入开关启用失败（不影响运行）: %s", exc)

    # v1.4.2: 角色切换广播桥（左下角/首页大形象、聊天气泡头像按角色联动）
    try:
        from gui.role_bridge import RoleBridge
        app_ctx.role_bridge = RoleBridge()
    except Exception as exc:
        logger.warning("role_bridge 装配失败（角色形象联动降级）: %s", exc)
        app_ctx.role_bridge = None

    # 启动时按当前默认角色广播一次，让形象与角色对齐
    try:
        _rb = getattr(app_ctx, "role_bridge", None)
        if _rb is not None:
            from gui.pages.page_role import RoleManager
            _role = RoleManager().default_role
            _rb.notify_role_changed(
                _role.id if _role else "",
                (getattr(_role, "avatar", "") or "") if _role else "",
                (getattr(_role, "current_expression", "normal") or "normal") if _role else "normal",
            )
    except Exception as exc:
        logger.warning("启动角色广播失败（不影响运行）: %s", exc)

    # 初始化 ChatService
    chat_service = ChatService(app_ctx)
    app_ctx.chat_service = chat_service

    # v1.2(A9): 主动陪伴调度器（低频 QTimer，依赖 companion 与 chat_service；失败不阻断）
    _init_proactive(app_ctx)

    # v1.6(P1-3/D-V16-10): 每周共同回顾（周日窗口判定 + 错过不补；失败不阻断）
    _init_weekly_review(app_ctx)

    # v1.7(F4/D-V17-03): 贴身提醒调度器（60s 扫描 + 启动补送；失败不阻断）
    _init_reminders(app_ctx)

    # v1.7(F7/D-V17-05): 女仆日记（次日启动后台补写昨日；失败不阻断）
    _init_diary(app_ctx)

    # 初始化 SessionManager（聊天会话持久化）
    session_manager = SessionManager()
    app_ctx.session_manager = session_manager

    # v1.3(P1-1): TTS app 级单例（必须在 ChatPanel/MainWindow 构造前挂好，
    # 供 chat_panel 订阅朗读按钮态；失败降级不阻断）
    _init_tts(app_ctx)

    # 创建主窗口
    window = MainWindow(app_ctx)
    app_ctx.main_window = window  # v1.3(P1-3): 托盘/热键/Idle 装配前先挂好引用
    window.show()

    logger.info("主窗口已显示")

    # v1.3(P1-3/P1-4): 托盘 / 全局热键 / Idle 监视装配（try/except 不阻断启动）
    _mount_v13_services(app, app_ctx)

    # v1.4(V-1.4-0 预编汇交点): v1.4 服务挂载钩子（当前守卫式空实现，B 线实施）
    _mount_v14_services(app, app_ctx)

    # v2.0(V20-12/V20-14): 启动早期——sidecar 自举 + 消费上轮换包结果 + onefile .old 清理。
    # 放在 window.show() 之后：不拖慢首屏；全程 try/except，失败绝不阻断（R-N）。
    _update_state = _bootstrap_update_subsystem(app_ctx)

    # v2.0(§4.5/D-V20-04): UI 就绪举手（sidecar 回滚判定的唯一主判据），事件循环跑通一次后写。
    _arm_confirm_handshake(app, app_ctx)

    # v2.0(D-V20-14/L1-1): 启动检查段——24h 节奏闸 + 生效频道（主窗已显示后异步，绝不阻塞）。
    _start_update_check(app_ctx, window, state=_update_state)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
