# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 码铃（MaLing）GUI（v10.4 打包整合修订版；v1.0.0 起产物名 maling / 图标 maling.ico）
#
# 本版相对旧 spec 的修订（依据见 README「.exe 打包整合说明」章节）：
# 1. datas 目标目录 'gui/themes' -> 'themes'：gui/utils.py get_resource_path() 在 frozen
#    模式下以 sys._MEIPASS 为基准，而 theme_engine.py 以 "themes/cute.qss" 相对路径查找；
#    旧目标会把 QSS 放到 _MEIPASS/gui/themes/，代码查找 _MEIPASS/themes/ 落空，
#    三主题 QSS 将全部降级为内置默认样式（theme_engine.py:116 _build_default_qss）。
# 2. hiddenimports 补第四阶段控件与语音动态导入：gui/widgets/voice_input.py:29 用
#    importlib.import_module("speech_recognition") 动态探测，PyInstaller 静态分析不可见，
#    不显式声明则打包后语音功能永远报「未安装」；pyaudio 为其 Microphone 后端。
# 3. upx=True -> False：UPX 压缩显著提高杀毒软件误报率，默认关闭（体积换安全）。
# 4. EXE 增加 icon=gui/assets/maid_coder.ico（应用图标）。
# 5. 改为 onedir 模式（推荐）：启动快、误报率低；onefile 改法见 README 打包章节。

block_cipher = None

a = Analysis(
    ['gui/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # QSS 主题三套：cute.qss / minimal.qss / maid.qss（theme_engine.py:19/45/71 引用）
        ('gui/themes', 'themes'),
        # v1.2 B1: maid 形象资产目录（manifest + 8 表情 PNG）。目录只含 manifest 也要打，
        # 防止打包后资源漏带；加载路径 get_resource_path("assets/maid/…") 与之对齐。
        ('gui/assets/maid', 'assets/maid'),
        # v1.2 A-9: maid_pet 微型宠物占位资产目录（manifest + README；PNG 到位自动进包）。
        # 目录只含 manifest 也要打，防打包后 PetAssets 资源目录落空；加载路径
        # get_resource_path("assets/maid_pet/…") 与之对齐。
        ('gui/assets/maid_pet', 'assets/maid_pet'),
        # v1.4.2: 角色专属形象资产（每角色一套表情差分，随包内置）
        ('gui/assets/roles', 'assets/roles'),
        # v1.2.x 修复：应用图标必须进包，否则 frozen 模式 get_resource_path
        # ("assets/maling.ico") 落空 -> setWindowIcon 静默失败 -> 任务栏/托盘
        # 显示默认图标（gui/main.py:368 app.setWindowIcon）
        ('gui/assets/maling.ico', 'assets'),
        # 首次运行的配置模板：gui/main.py:97 以相对路径 Path("config.yaml") 读写，
        # 实际生效的是 exe 同目录下自动生成的副本（见 README「路径行为」小节）
        ('config.yaml', '.'),
        # v1.4.8: 版本号单源
        ('version.json', '.'),
        # v1.6(P0-2): 意图词表数据文件（gui/intent.py 加载；缺文件时内置词表兜底可跑）
        ('gui/assets/intent_words.json', 'assets'),
        # v1.7(F3/D-V17-02): 每日一句语录库（缺文件时内置小池兜底可跑）
        ('gui/assets/quotations.json', 'assets'),
        # ---- v2.0(V20-17) 修复 v1.9 遗留缺口 ⚠-10：onefile 原缺本项与 'gui.fonts' ----
        # 目标目录必须为 'assets/fonts'（不是 'fonts'），与 gui/utils.py get_resource_path
        # 的源码态基准 gui/ 对齐（frozen 态基准 sys._MEIPASS）；否则单文件版
        # get_resource_path("assets/fonts/…") 落空 → 静默回退雅黑、内置字体白做。
        ('gui/assets/fonts', 'assets/fonts'),
        # ---- v2.1(图标字形体系)：图标字体 TTF + manifest + 许可副本。必须与 onedir.spec
        #    对齐（目标目录 'assets/icons'，与 gui/icons.py 的 ICON_DIR_REL="assets/icons"
        #    一致）；否则 frozen 态 get_resource_path("assets/icons/…") 落空 → 图标内核
        #    available() 为假 → 静默回退 emoji，本轮新增的图标字形体系在单文件版失效。
        ('gui/assets/icons', 'assets/icons'),
        # ---- v2.0(V20-17): 内嵌自动更新 sidecar（design D-V20-08）----
        # onefile 下 datas 进自解压 _MEIPASS → 运行时 _MEIPASS/updater/maling_updater.exe；
        # 与 gui/main.py:977 get_resource_path("updater") + ensure_self_installed 布局对齐。
        ('dist_updater/maling_updater.exe', 'updater'),
    ],
    hiddenimports=[
        # ---- 语音输入（动态导入，必须显式声明）----
        'speech_recognition',
        'pyaudio',
        # ---- 第四阶段控件（chat_panel.py 顶层导入，静态可见，列出防遗漏）----
        'gui.widgets.attachment_bar',
        'gui.widgets.session_tabs',
        'gui.widgets.voice_input',
        'gui.widgets.thinking_indicator',
        # ---- CLI 命令注册（gui/main.py _init_cli_core 内 import，静态可见，保险列出）----
        'commands.mode_cmds',
        'commands.file_cmds',
        'commands.session_cmds',
        'commands.snippet_cmds',
        'commands.run_cmds',
        'commands.git_cmds',
        'commands.kb_cmds',
        'commands.agent_cmds',
        'commands.search_cmds',
        'commands.todo_cmds',
        'commands.dev_cmds',
        'commands.export_cmds',
        'commands.lint_cmds',
        'commands.bookmark_cmds',
        'commands.review_cmds',
        'commands.deps_cmds',
        'commands.complete_cmds',
        'commands.changelog_cmds',
        'commands.benchmark_cmds',
        'commands.api_cmds',
        'commands.cicd_cmds',
        'commands.i18n_cmds',
        'commands.viz_cmds',
        'commands.project_cmds',
        'commands.plan_cmds',
        'commands.fallbacks',
        'core',
        'core.project_ctx',
        'core.plan_engine',
        'gui.config',
        'gui.theme_engine',
        'gui.app_context',
        'gui.main_window',
        'gui.page_manager',
        'gui.chat_service',
        'gui.adapters.gui_chat_session',
        'gui.widgets.sidebar',
        'gui.widgets.chat_panel',
        'gui.widgets.message_bubble',
        'gui.pages.page_home',
        'gui.pages.page_settings',
        # ---- v1.2.x 保险：页面/组件（main_window 顶部静态 import 本可追溯，显式列出防回归）----
        'gui.pages.page_project',
        'gui.pages.page_editor',
        'gui.pages.page_help',
        'gui.pages.page_about',
        'gui.pages.page_role',
        'gui.pages.page_toolbox',
        'gui.pages.page_plan',
        'gui.pages.onboarding',
        'gui.widgets.model_config_panel',
        'api',
        'session',
        'agents',
        # ---- v1.1.0 Agent 模块（chat_service._run_agent 内动态 import，保险列出）----
        'agent_tools',
        'agent_engine',
        'gui.widgets.tool_trace',
        # ---- v1.4.8 工程化加固：纯逻辑提取模块 + 用户友好消息 + 版本管理 ----
        'gui.chat_helpers',
        'gui.chat_bubble_utils',
        'gui.chat_input_logic',
        'gui.chat_stream_state',
        'user_messages',
        'version',
        # ---- v1.2 C 线：run_command 执行器 + 任务执行域（agent_engine/tool_trace 动态 import）----
        'command_runner',
        'agent_task',
        # ---- v1.2 A1/B1 companion 陪伴域 + 形象资产管线（根级 companion 由 main.py 动态 import）----
        'companion',
        'gui.maid_avatar',
        # ---- v1.2 A-9: 角落微型宠物 MaidPet（main_window 动态挂载）----
        'gui.widgets.maid_pet',
        # ---- v1.5.0: 知识库 / 待办 GUI 入口对话框（page_home 快捷入口）----
        'gui.widgets.kb_dialog',
        'gui.widgets.todo_dialog',
        # ---- v1.2 A9: 主动陪伴调度器（gui/main.py _init_proactive 内动态 import，保险列出）----
        'gui.proactive_scheduler',
        # ---- v1.2.2: 拍照发图（camera_capture 内动态 import QtMultimedia，显式列出防漏）----
        'gui.widgets.camera_capture',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        # ---- v1.3 P1 批（V-0 基线接线）：TTS/热键/托盘/Idle/截图 + QtTextToSpeech ----
        'gui.tts',
        'gui.hotkeys',
        'gui.tray_manager',
        'gui.system_idle',
        'gui.widgets.screen_capture',
        'PySide6.QtTextToSpeech',
        # ---- v1.3 P2 批预留（V-0 一并收录防漏；本版不写实现，缺模块仅为打包告警）----
        'gui.widgets.mini_games',
        'gui.voice_conversation',
        'gui.widgets.handsfree_bar',
        'gui.pages.page_memories',
        'highlights',
        'autostart',
        # ---- v1.4（V-1.4-0 预编汇交点，docs/design-v14.md §3.2）----
        # A 域：开源玩具盒 —— 游戏容器/2048/扫雷/番茄钟（A 线实现）
        'gui.pomodoro',
        'gui.widgets.pomodoro_dialog',
        'gui.widgets.games',
        'gui.widgets.games.game_2048',
        'gui.widgets.games.game_minesweeper',
        # B 域：持续看屏 + 单步操作（B 线实现；此刻未创建，PyInstaller 的
        # "Hidden import not found" 属预期告警，B 线落地后自动消除）
        'gui.screen_grab',
        'gui.screen_watch',
        'gui.vision_support',
        'gui.computer_use',
        'gui.input_sim',
        'gui.widgets.screen_watch_bar',
        'gui.widgets.authorize_action_dialog',
        'PySide6',
        'pygments',
        'yaml',
        'requests',
        'pyperclip',
        # ---- v1.5.0: Agent 工具 list_processes/system_info 依赖（C 扩展，必须显式声明）----
        'psutil',
        # ---- v1.6 增量：意图五态（gui/intent.py 纯规则模块）+ 第一批页面/组件 ----
        'gui.intent',
        'gui.pages.page_memory_book',
        'gui.widgets.proactive_feedback',
        # ---- v1.6(P1-3): 每周共同回顾（根级 weekly.py，纯 stdlib）----
        'weekly',
        # ---- v1.7(F3): 每日一句语录库（根级 quotations.py，纯 stdlib）----
        'quotations',
        # ---- v1.7(F4/F7): 贴身提醒 + 女仆日记（根级，纯 stdlib）----
        'reminders',
        'diary',
        # ---- v1.8(D-V18-04/07/08): 根级新模块 + 新控件（design-v18 §7 必核项：
        # 根级新模块是 PyInstaller 隐式收集漏网高发区）----
        'timeline',
        'scene',
        'gui.widgets.emotion_arc',
        'gui.widgets.card_import_preview',
        # ---- v2.0(V20-17) 修复 v1.9 遗留缺口 ⚠-10：字体系统 ----
        # theme_engine 顶部静态 import，onedir.spec 已有；onefile 原缺 → 单文件版白丢内置字体。
        'gui.fonts',
        # ---- v2.0(V20-17): 自动更新下载器（gui/main.py 动态 import，须显式声明）----
        'gui.update_downloader',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 精简体积：以下为 CLI 惰性依赖（utils.py:1020 OCR / viz_cmds networkx /
        # deps_cmds numpy / api_cmds httpx），GUI 主线聊天、主题、会话、语音、
        # 导出不使用。需要 CLI 这些命令的请从 excludes 中删除对应项并在
        # 打包机 pip install 对应库。
        'tkinter',
        '_tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ===== onefile 变体：所有依赖内嵌进单个 exe（发人只传一个文件）=====
# 取舍：启动时自解压到临时目录（首启慢数秒）、杀软误报概率略高于 onedir；
# 好处：别人拿到单个 MaLing_single.exe 双击即用，不需要整目录。
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MaLing_single',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # 窗口模式
    icon='gui/assets/maling.ico',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
