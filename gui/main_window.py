"""MainWindow —— QMainWindow 三栏布局（侧边栏 | 内容区 | 聊天面板）。"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from gui.qt_compat import (
    QMainWindow, QWidget, QStackedWidget, QSplitter,
    QVBoxLayout, QStatusBar, QLabel, Qt,
    QPushButton,  # v1.2.1: 顶部 Key 引导横幅
)
from core import __version__ as CORE_VERSION
from gui.theme_engine import ThemeEngine
from gui.page_manager import PageManager
from gui.widgets.sidebar import SidebarWidget
from gui.widgets.chat_panel import ChatPanelWidget
from gui.pages.page_home import PageHome
from gui.pages.page_project import PageProject
from gui.pages.page_editor import PageEditor
from gui.pages.page_settings import PageSettings
from gui.pages.page_help import PageHelp
from gui.pages.page_about import PageAbout
from gui.pages.page_role import PageRole
from gui.pages.page_toolbox import PageToolbox
from gui.pages.page_plan import PagePlan
from gui.pages.page_memories import PageMemories  # v1.3(P2-3): 高光回忆册
from gui.pages.page_memory_book import PageMemoryBook  # v1.6(P0-1): 透明记忆中心
from gui.pages.onboarding import OnboardingDialog

logger = logging.getLogger("maid_coder.gui")


class MainWindow(QMainWindow):
    """应用主窗口：三栏布局 + 页面栈 + 聊天面板常驻。"""

    def __init__(self, app_context):
        super().__init__()
        self.app_ctx = app_context

        # 1. 初始化主题引擎（必须在任何 widget 创建之前）
        self.theme_engine = ThemeEngine(self)
        self.app_ctx.theme_engine = self.theme_engine
        # v1.3(P2-7): 外观模式（light/dark/system）先于主题应用，随后 load_theme
        # 以活动色板渲染；默认 light，不改旧用户观感。
        # v1.9 A(D-V19-10/11)：先归一旧主题值；C 深色夜间（dark_locked）强制深色。
        _theme_name = self.theme_engine.normalize_theme_id(
            getattr(self.app_ctx.config, "theme_name", self.theme_engine.DEFAULT_THEME_ID) or "")
        _mode = getattr(self.app_ctx.config, "theme_mode", "light") or "light"
        if self.theme_engine.is_dark_locked(_theme_name):
            _mode = "dark"
        try:
            self.theme_engine.set_theme_mode(_mode)
        except Exception:
            pass
        # v1.4.3「主题强调色色盘」：启动时把持久化的自定义强调色注入引擎，
        # 随后 load_theme 即以派生色板渲染（空串=用主题默认，无副作用）。
        try:
            self.theme_engine.set_custom_accent(
                getattr(self.app_ctx.config, "custom_accent", "") or ""
            )
        except Exception:
            pass
        self.theme_engine.load_theme(_theme_name)

        # 2. 设置窗口基础属性
        # v1.2.3: 主窗标题不含版本号（正常使用不显示；版本在设置/关于页可见）
        self.setWindowTitle("码铃")
        self.setMinimumSize(1200, 800)

        # 恢复窗口几何
        geo = getattr(self.app_ctx.config, "window_geometry", None)
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                self.resize(1600, 900)
        else:
            self.resize(1600, 900)

        # 透明度
        opacity = getattr(self.app_ctx.config, "window_opacity", 1.0)
        self.setWindowOpacity(opacity)

        # 3. 构建中心布局
        self._setup_central_layout()

        # 4. 构建页面栈
        self._setup_pages()

        # 5. 构建状态栏
        self._setup_status_bar()

        # 6. 连接信号
        self._connect_signals()

        # 7. 首次启动引导
        self._check_first_run()

    def _setup_central_layout(self) -> None:
        """中心区域：左侧功能导航栏 + 中间主屏（页面栈）。

        布局目标（v1.2 UI 大气化）：聊天面板是**中间主屏**（占全部可用宽度，
        气泡宽、留白足），而不是右侧一条窄栏；功能页（首页/项目/文件/计划/
        角色/工具/设置/帮助/关于）仍从左侧导航进入，在同一主屏内切换显示，
        点导航「聊天」随时回到聊天主屏。
        """
        self.central_splitter = QSplitter(Qt.Horizontal)

        # 左栏：功能导航（固定宽度）
        self.sidebar = SidebarWidget(self.app_ctx)
        self.sidebar.setFixedWidth(180)
        self.central_splitter.addWidget(self.sidebar)

        # 中间主屏：页面栈（聊天主屏在 _setup_pages 注册为 "chat" 页）
        self.page_stack = QStackedWidget()
        self.central_splitter.addWidget(self.page_stack)

        self.central_splitter.setStretchFactor(0, 0)  # 侧栏不拉伸
        self.central_splitter.setStretchFactor(1, 1)  # 主屏占满剩余宽度
        self.central_splitter.setCollapsible(0, False)  # 禁止把侧边栏拖到 0 宽
        self.central_splitter.setSizes([180, max(1, self.width() - 180)])

        # v1.2.1: 顶部「配置模型」引导横幅 —— 小白首次打开未配 Key 时醒目提示，
        # 点击直达设置「模型与接口」；配置完成后自动隐藏（refresh_api_status 维护）。
        self.key_banner = QPushButton("⚠️ 尚未配置模型 Key —— 点这里打开「模型与接口」设置（只需一次）")
        self.key_banner.setObjectName("apiKeyBanner")
        self.key_banner.setCursor(Qt.PointingHandCursor)
        self.key_banner.setFixedHeight(36)
        # 语义警示色（不随主题漂移，warning 语义固定橙）
        self.key_banner.setStyleSheet(
            "QPushButton#apiKeyBanner {"
            "  background: #FFE0B2; color: #E65100; border: none;"
            "  border-bottom: 1px solid #FFB74D;"
            "  font-size: 13px; font-weight: 600;"
            "}"
            "QPushButton#apiKeyBanner:hover { background: #FFCC80; }"
        )
        self.key_banner.setVisible(False)
        self.key_banner.clicked.connect(self.open_model_settings)

        _central_outer = QWidget()
        _outer_layout = QVBoxLayout(_central_outer)
        _outer_layout.setContentsMargins(0, 0, 0, 0)
        _outer_layout.setSpacing(0)
        _outer_layout.addWidget(self.key_banner)
        _outer_layout.addWidget(self.central_splitter, 1)
        self.setCentralWidget(_central_outer)

        # 聊天面板：作为主屏页注册进页面栈（见 _setup_pages），不再单独占右栏
        self.chat_panel = ChatPanelWidget(self.app_ctx)

        # 根据配置控制侧栏可见性（聊天是主屏，不再受 chat_panel_visible 隐藏）
        config = self.app_ctx.config
        if config and not getattr(config, "sidebar_visible", True):
            self.sidebar.hide()

        # v1.2(A-9): 窗口角落微型常驻宠物 —— 内容区(page_stack)右上角 overlay。
        # 纯增量挂载：parent=central_splitter(同级顶层，避免被页面栈盖住) +
        # track_widget=page_stack(决定宽度/锚点)；MaidPet 内部自订阅 mood_changed、
        # 自监听内容区 resize 定位、窄窗自动缩 24px 或隐藏。
        # companion/资产缺失自动走占位；失败不阻断主窗。
        # v1.2.3: 默认不挂载（默认 pet_enabled=False），用户可在设置页「角落宠物」开关开启。
        # 保留 MaidPet 类与变量构造（代码兼容）。
        self.maid_pet = None
        try:
            from gui.widgets.maid_pet import MaidPet
            if MaidPet is not None:
                pet_enabled = getattr(config, "pet_enabled", False) if config else False
                if pet_enabled:
                    self.maid_pet = MaidPet(
                        self.app_ctx,
                        parent=self.central_splitter,
                        track_widget=self.page_stack,
                    )
                    self.maid_pet.relayout()
        except Exception as exc:
            logger.warning("角落宠物 MaidPet 挂载失败（不影响运行）: %s", exc)
            self.maid_pet = None

    def set_pet_enabled(self, enabled: bool) -> None:
        """设置页切换：开=挂载/显示 MaidPet；关=隐藏（保留实例，再次开可直接 show）。"""
        if enabled:
            if self.maid_pet is None:
                try:
                    from gui.widgets.maid_pet import MaidPet
                    if MaidPet is not None:
                        self.maid_pet = MaidPet(
                            self.app_ctx,
                            parent=self.central_splitter,
                            track_widget=self.page_stack,
                        )
                        self.maid_pet.relayout()
                except Exception as exc:
                    logger.warning("MaidPet 挂载失败: %s", exc)
                    self.maid_pet = None
            else:
                self.maid_pet.show()
                try:
                    self.maid_pet.relayout()
                except Exception:
                    pass
        else:
            if self.maid_pet is not None:
                self.maid_pet.hide()

    def _setup_pages(self) -> None:
        """注册主页面到页面栈。聊天面板 = 主屏页（index 0，默认显示）。"""
        self.pages: Dict[str, QWidget] = {}

        # 主屏：聊天面板注册为 "chat" 页（首个入栈 = index 0）
        self.pages["chat"] = self.chat_panel
        self.page_stack.addWidget(self.chat_panel)

        page_classes = [
            ("home", PageHome, "首页仪表盘"),
            ("project", PageProject, "项目视图"),
            ("file", PageEditor, "编辑"),
            ("memories", PageMemories, "高光回忆"),  # v1.3(P2-3)
            ("memory_book", PageMemoryBook, "记忆中心"),  # v1.6(P0-1)
            ("settings", PageSettings, "设置"),
            ("help", PageHelp, "帮助"),
            ("about", PageAbout, "关于"),
            ("agent", PageRole, "角色面板"),
            ("tools", PageToolbox, "工具箱"),
            ("plan", PagePlan, "计划编辑器"),
        ]

        for key, cls, title in page_classes:
            page = cls(self.app_ctx, title)
            self.pages[key] = page
            self.page_stack.addWidget(page)

        # 默认显示聊天主屏
        self.page_stack.setCurrentWidget(self.chat_panel)

        # 初始化 PageManager
        self.page_manager = PageManager(self.page_stack, self.pages)
        self.app_ctx.page_manager = self.page_manager

    def _build_placeholder_page(self, title: str) -> QWidget:
        """构建占位页面。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)

        label = QLabel(f"{title}")
        font = page.font()
        font.setPointSize(18)
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)

        desc = QLabel("该功能将在后续 Sprint 中实现~")
        layout.addWidget(desc)
        layout.addStretch()
        return page

    def _setup_status_bar(self) -> None:
        """构建状态栏。v10.15: API 状态通过 refresh_api_status() 统一刷新。"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_theme = QLabel("主题: 现代极简")
        self.status_bar.addWidget(self.status_theme)

        self.status_mode = QLabel("模式: 标准")
        self.status_bar.addWidget(self.status_mode)

        self.status_api = QLabel("API: 未配置")
        self.status_bar.addWidget(self.status_api)

        # v10.15: 初始化时调用 refresh_api_status()，由它判断已配置/未配置
        self.refresh_api_status()

    def refresh_api_status(self) -> None:
        """v10.15: 统一刷新底部 API 状态栏。

        真值源：app_ctx.cfg.api_key（同时兜底看 ollama 本地）。每次入口变更
        （启动初始化、设置页保存、引导页完成）都调一次，保证状态栏与实际一致。
        """
        if not hasattr(self, "status_api") or self.status_api is None:
            return
        cfg = getattr(self.app_ctx, "cfg", None)
        if cfg is None:
            self.status_api.setText("API: 未配置")
            return
        provider = getattr(cfg, "api_provider", "openai") or "openai"
        api_key = (getattr(cfg, "api_key", "") or "").strip()
        # ollama 本地视为已配置；其余厂商看 key
        if api_key or provider == "ollama":
            self.status_api.setText(f"API: 已配置 ({provider})")
        else:
            self.status_api.setText("API: 未配置")
        # v1.2.1: 顶部 Key 引导横幅同步（未配置时显示，配置后隐藏）
        try:
            banner = getattr(self, "key_banner", None)
            if banner is not None:
                configured = bool(api_key) or provider == "ollama"
                if banner.isVisible() != (not configured):
                    banner.setVisible(not configured)
        except Exception:
            pass
        # v1.2(B9): 侧栏「模型状态」按钮同步刷新（provider/脱敏 Key/状态点）
        if hasattr(self, "sidebar"):
            try:
                self.sidebar.update_model_status()
            except Exception:
                pass

    def _connect_signals(self) -> None:
        """连接跨组件信号。"""
        # 侧边栏导航 → 页面切换
        self.sidebar.item_clicked.connect(self._on_navigate)
        # v1.2.x 修复：任何入口的导航（首页快捷按钮/宠物回首页/onboarding/back）
        # 都同步侧栏高亮，避免「页面已切、高亮停旧处」错位
        try:
            self.page_manager.page_changed.connect(self.sidebar.set_active_page)
        except Exception:
            pass

        # 侧边栏底部按钮
        self.sidebar.help_clicked.connect(self._on_help_clicked)
        self.sidebar.about_clicked.connect(self._on_about_clicked)

        # v1.2(B9): 侧栏「模型状态」直达 → open_model_settings
        try:
            self.sidebar.model_clicked.connect(self.open_model_settings)
        except Exception:
            pass

        # v1.2(A-11): 侧栏「码铃形象入口」点击 → 回首页（兜底导航在 sidebar 内部也有）
        try:
            self.sidebar.maid_clicked.connect(self._on_sidebar_maid_clicked)
        except Exception:
            pass

        # 主题变更 → 状态栏更新
        self.theme_engine.theme_changed.connect(self._on_theme_changed)

        # 模式变更 → 状态栏更新
        gui_session = getattr(self.app_ctx, "gui_session", None)
        if gui_session is not None:
            gui_session.mode_changed.connect(self._on_mode_changed)

        # 项目页面 → 文件打开
        project_page = self.pages.get("project")
        if isinstance(project_page, PageProject):
            project_page.file_opened.connect(self._on_project_file_opened)

        # v10.14: 好感度等级变化 → 状态栏可见提示
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None:
            chat_service.intimacy_changed.connect(self._on_intimacy_changed)

    def _check_first_run(self) -> None:
        """检查是否为首次启动，若是则显示引导页面。"""
        config = getattr(self.app_ctx, "config", None)
        if config is not None and getattr(config, "first_run", True):
            # 创建并显示 onboarding 页面（替换首页内容）
            self._show_onboarding()

    def _show_onboarding(self) -> None:
        """显示首次启动引导。"""
        self.onboarding = OnboardingDialog(self.app_ctx, self)
        self.onboarding.finished.connect(self._on_onboarding_finished)
        # 将 onboarding 插入页面栈并切换
        self.page_stack.addWidget(self.onboarding)
        self.page_stack.setCurrentWidget(self.onboarding)

    def _on_onboarding_finished(self) -> None:
        """引导完成后切回首页。v10.15: 引导完成后立即同步 API 状态栏。"""
        if hasattr(self, "onboarding"):
            self.page_stack.removeWidget(self.onboarding)
            self.onboarding.deleteLater()
            del self.onboarding
        # v10.15: 引导页可能保存了新 key，刷新一次状态栏
        try:
            self.refresh_api_status()
        except Exception:
            pass
        # 引导完成 → 进入聊天主屏
        self.page_manager.navigate("chat")

    def _on_navigate(self, key: str) -> None:
        """侧边栏导航处理。"""
        if self.page_manager is not None:
            self.page_manager.navigate(key)

    def open_model_settings(self) -> None:
        """v1.2(B9): 模型配置直达桥 —— 首页/侧栏共用。

        跳到设置页，触发 on_enter（刷新 ModelConfigPanel），再滚动定位
        到「模型与接口」分区（scroll_to_model）。所有步骤 getattr/异常防御。
        """
        if self.page_manager is None:
            return
        try:
            self.page_manager.navigate("settings")
        except Exception:
            return
        settings_page = self.pages.get("settings") if hasattr(self, "pages") else None
        if settings_page is not None and hasattr(settings_page, "scroll_to_model"):
            try:
                settings_page.scroll_to_model()
            except Exception:
                pass

    def _on_help_clicked(self) -> None:
        """侧边栏帮助按钮点击。"""
        if self.page_manager is not None:
            self.page_manager.navigate("help")

    def _on_about_clicked(self) -> None:
        """侧边栏关于按钮点击。"""
        if self.page_manager is not None:
            self.page_manager.navigate("about")

    def _on_sidebar_maid_clicked(self) -> None:
        """v1.2(A-11): 侧栏码铃形象入口点击 → 回首页（幂等，可与内部兜底并存）。"""
        if self.page_manager is not None:
            try:
                self.page_manager.navigate("home")
            except Exception:
                pass

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更处理（v1.9 A：四风格标签 + 旧值归一兜底）。"""
        theme_labels = {
            "ui_minimal": "现代极简", "ui_cream": "温暖奶油",
            "ui_night": "深色夜间", "ui_whale": "鲸鱼娘深海",
            # 旧值兜底（读时映射前若直接收到旧 id 也不显示乱码）
            "cute": "温暖奶油", "maid": "温暖奶油", "minimal": "现代极简",
        }
        label = theme_labels.get(theme_name, theme_name)
        self.status_theme.setText(f"主题: {label}")

    def _on_mode_changed(self, mode_name: str, state: bool) -> None:
        """模式变更处理。"""
        modes = {
            "deep": "深度思考",
            "coding": "编程模式",
        }
        label = modes.get(mode_name, mode_name)
        self.status_mode.setText(f"模式: {label} {'开' if state else '关'}")

    def _on_intimacy_changed(self, message: str) -> None:
        """v10.14: 好感度等级 / 感谢回应 → 状态栏 5 秒气泡提示。"""
        try:
            self.status_bar.showMessage(f"💕 {message}", 5000)
        except Exception:
            pass

    def _on_project_file_opened(self, file_path: str) -> None:
        """项目页面双击文件 → 切换到文件编辑器页面。"""
        self.app_ctx.current_file_path = file_path
        if self.page_manager is not None:
            self.page_manager.navigate("file")

    def save_window_state(self) -> None:
        """持久化窗口几何/侧栏可见性（closeEvent 与托盘退出共用的单一保存点）。"""
        config = self.app_ctx.config
        if config is None:
            return
        config.window_geometry = bytes(self.saveGeometry().toHex()).decode()
        # v1.4.5 修复: 不再把侧栏瞬时可见状态写入配置——收起主窗时子控件
        # isVisible()=False 会被持久化，导致重启后侧栏"永久消失"。
        # 侧栏显隐唯一权威 = 设置页「显示侧边栏」开关（page_settings）。
        try:
            config.save()
        except Exception as exc:
            logger.warning("保存窗口状态失败: %s", exc)

    def toggle_visibility(self) -> None:
        """v1.3(P1-3): 全局热键 Ctrl+Alt+M / 托盘「显示/隐藏主窗」动作桥。"""
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    # ------------------------------------------------------------------
    # v1.3(P2-4): 托盘完整动作桥（TrayManager 菜单动作经这些方法落到主窗/聊天面板）
    # ------------------------------------------------------------------
    def _show_and_navigate(self, page_key: str) -> None:
        """托盘动作统一前置：主窗可见置前 + 导航到指定页（各步防御）。"""
        try:
            if not self.isVisible():
                self.showNormal()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass
        pm = getattr(self.app_ctx, "page_manager", None)
        if pm is not None and hasattr(pm, "navigate"):
            try:
                pm.navigate(page_key)
            except Exception:
                pass

    def navigate_settings(self) -> None:
        """⚙️ 设置：呼主窗 + 导航设置页。"""
        self._show_and_navigate("settings")

    def open_float_chat(self) -> None:
        """💬 聊天浮窗：呼出/聚焦独立聊天浮窗（复用 chat_panel._on_expand_chat）。"""
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "_on_expand_chat"):
            try:
                panel._on_expand_chat()
                return
            except Exception:
                pass
        # 浮窗不可用兜底：回聊天主屏
        self._show_and_navigate("chat")

    def trigger_camera(self) -> None:
        """📷 拍照：呼主窗并触发聊天面板拍照发图路径。"""
        self._show_and_navigate("chat")
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "_on_camera_capture"):
            try:
                panel._on_camera_capture()
            except Exception:
                pass

    def trigger_voice(self) -> None:
        """🎤 语音输入：呼主窗并触发聊天面板单次语音输入路径。"""
        self._show_and_navigate("chat")
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "_on_voice_input"):
            try:
                panel._on_voice_input()
            except Exception:
                pass

    def trigger_screenshot(self) -> None:
        """🖼 截图提问：调 chat_panel.capture_screenshot（内部自带呼出+导航，P1-2 既有链）。"""
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "capture_screenshot"):
            try:
                panel.capture_screenshot()
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        """窗口关闭处理。

        v1.3(P1-3 / design-v13 D-V13-01 / D-V13-11): 默认行为从「关窗即退」改为
        「X = 隐藏到托盘」——close_quits=False 且托盘可用时保存几何并隐藏，应用继续
        驻留（热键/托盘可随时呼出）；真退出唯一入口 = 托盘「❌ 退出」（置
        app_ctx.quitting=True）或设置开启「关闭窗口直接退出」。托盘不可用环境
        自动回落既有真退出行为（不产生隐形进程）。
        """
        try:
            self.save_window_state()
        except Exception as exc:
            logger.warning("关闭事件保存状态失败: %s", exc)

        app_ctx = self.app_ctx
        quitting = bool(getattr(app_ctx, "quitting", False))
        config = getattr(app_ctx, "config", None)
        close_quits = bool(getattr(config, "close_quits", False)) if config is not None else False
        tray_ok = False
        tray = getattr(app_ctx, "tray_manager", None)
        if tray is not None and hasattr(tray, "is_available"):
            try:
                tray_ok = bool(tray.is_available())
            except Exception:
                tray_ok = False

        if not quitting and not close_quits and tray_ok:
            # X = 最小化到托盘（保存几何照旧），绝不真退出
            logger.info("QUIT-no: closeEvent → 隐藏到托盘（非退出）")
            event.ignore()
            self.hide()
            # v1.4.0-勘: 提示用户「只是收进托盘，不是退出」——避免误以为已关闭
            try:
                _tray = getattr(app_ctx, "tray_manager", None)
                if _tray is not None and hasattr(_tray, "notify_maid"):
                    _tray.notify_maid(
                        "码铃还在哦",
                        "窗口已最小化到托盘啦——右键托盘图标可呼出或退出。",
                    )
            except Exception:
                pass
            return

        # quitting=True（托盘退出路径已完成 shutdown）或 无托盘 / close_quits=True
        # -> 原退出逻辑（保存 + shutdown + accept）
        logger.info("QUIT-yes: closeEvent accept（quitting=%s close_quits=%s tray_ok=%s）",
                    quitting, close_quits, tray_ok)
        if not quitting:
            chat_service = getattr(app_ctx, "chat_service", None)
            if chat_service is not None:
                try:
                    chat_service.shutdown()
                except Exception as exc:
                    logger.warning("关闭事件 shutdown 失败: %s", exc)
        event.accept()
