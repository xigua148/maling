"""MainWindow —— QMainWindow 三栏布局（侧边栏 | 内容区 | 聊天面板）。"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from gui.qt_compat import (
    QMainWindow, QWidget, QStackedWidget, QSplitter,
    QVBoxLayout, QStatusBar, QLabel, Qt,
    QPushButton,  # v1.2.1: 顶部 Key 引导横幅
    QEvent, QGraphicsOpacityEffect,  # v2.1(V21-08): 窗口状态重应用 / 切页淡入收尾
)
from gui.utils import theme_color  # v2.1(V21-08): 取色唯一入口
from core import __version__ as CORE_VERSION

# v2.1(V21-08): 三内核只调用不改；缺失时静默降级（R-Q⑤：模块可整体剥离）
try:
    from gui import glass
except Exception:  # pragma: no cover - 内核剥离兜底
    glass = None
try:
    from gui import motion
except Exception:  # pragma: no cover
    motion = None
try:
    from gui import icons
except Exception:  # pragma: no cover
    icons = None
# v2.1(质感试点): 通用过渡层（**当前仅按钮按压反馈**）；缺失时静默降级（R-Q⑤）
# 注意：切页淡入由本文件 _on_page_switched 直接走 motion.fade，不经 transitions。
try:
    from gui import transitions
except Exception:  # pragma: no cover
    transitions = None

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


def _icon_glyph(name: str, fallback: str) -> str:
    """文本内嵌图标字形；图标内核缺失 / 字体不可用时原样返回 emoji（R-Q⑤）。"""
    if icons is None:
        return fallback
    try:
        return icons.text_glyph(name, fallback)
    except Exception:
        return fallback


class MainWindow(QMainWindow):
    """应用主窗口：三栏布局 + 页面栈 + 聊天面板常驻。"""

    def __init__(self, app_context):
        super().__init__()
        self.app_ctx = app_context
        # v2.1(V21-08/M-1): 每页在跑的淡入动画（防同页快速重切时旧动画收尾误删新 effect）
        self._page_fade_anims: Dict[QWidget, object] = {}

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
            logger.debug("静默降级：__init__ 中忽略异常", exc_info=True)
        # v1.4.3「主题强调色色盘」：启动时把持久化的自定义强调色注入引擎，
        # 随后 load_theme 即以派生色板渲染（空串=用主题默认，无副作用）。
        try:
            self.theme_engine.set_custom_accent(
                getattr(self.app_ctx.config, "custom_accent", "") or ""
            )
        except Exception:
            logger.debug("静默降级：__init__ 中忽略异常", exc_info=True)
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
        # v2.1(V21-18): 毛玻璃只穿透中间结构容器；用 objectName 让 QSS 精确命中，
        # 不影响侧栏/页面/卡片等内容控件的正常不透明背景。
        self.central_splitter.setObjectName("glassCentralSplitter")

        # 左栏：功能导航（固定宽度）
        self.sidebar = SidebarWidget(self.app_ctx)
        self.sidebar.setFixedWidth(180)
        self.central_splitter.addWidget(self.sidebar)

        # 中间主屏：页面栈（聊天主屏在 _setup_pages 注册为 "chat" 页）
        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("glassPageStack")
        self.central_splitter.addWidget(self.page_stack)

        self.central_splitter.setStretchFactor(0, 0)  # 侧栏不拉伸
        self.central_splitter.setStretchFactor(1, 1)  # 主屏占满剩余宽度
        self.central_splitter.setCollapsible(0, False)  # 禁止把侧边栏拖到 0 宽
        self.central_splitter.setSizes([180, max(1, self.width() - 180)])

        # v1.2.1: 顶部「配置模型」引导横幅 —— 小白首次打开未配 Key 时醒目提示，
        # 点击直达设置「模型与接口」；配置完成后自动隐藏（refresh_api_status 维护）。
        self.key_banner = QPushButton(f"{_icon_glyph('warning', '⚠️')} 尚未配置模型 Key —— 点这里打开「模型与接口」设置（只需一次）")
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

        self.central_outer = QWidget()
        self.central_outer.setObjectName("glassCentralOuter")
        _outer_layout = QVBoxLayout(self.central_outer)
        _outer_layout.setContentsMargins(0, 0, 0, 0)
        _outer_layout.setSpacing(0)
        _outer_layout.addWidget(self.key_banner)
        _outer_layout.addWidget(self.central_splitter, 1)
        self.setCentralWidget(self.central_outer)

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
                    logger.debug("静默降级：set_pet_enabled 中忽略异常", exc_info=True)
        else:
            if self.maid_pet is not None:
                # v2.1(UI-Fix-0912): 单纯 hide() 在某些布局下不彻底(桌宠的 parent 是
                # central_splitter,会被 splitter 布局重排触发重显)。加 lower() 加强制刷新。
                self.maid_pet.hide()
                self.maid_pet.lower()

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
        label.setObjectName("placeholderTitle")
        font = page.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)

        desc = QLabel("该功能将在后续 Sprint 中实现~")
        layout.addWidget(desc)
        layout.addStretch()
        return page

    def _setup_status_bar(self) -> None:
        """构建状态栏。v10.15: API 状态通过 refresh_api_status() 统一刷新。

        v2.1(V21-08/I-3): 三个 QLabel 图标化（矢量优先；字体不可用回落纯文本）。
        """
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_theme = QLabel("主题: 现代极简")
        self.status_bar.addWidget(self.status_theme)

        self.status_mode = QLabel("模式: 标准")
        self.status_bar.addWidget(self.status_mode)

        self.status_api = QLabel("API: 未配置")
        self.status_bar.addWidget(self.status_api)

        # v2.1(V21-08): 三标签矢量图标（不可用时不加图标，文本原样保留）
        self._status_icon_specs = (
            ("status_theme", "palette"),
            ("status_mode", "mode"),
            ("status_api", "api"),
        )
        self._refresh_status_icons()

        # v10.15: 初始化时调用 refresh_api_status()，由它判断已配置/未配置
        self.refresh_api_status()

    def _refresh_status_icons(self) -> None:
        """V21-08/I-3: 状态栏三图标化（换肤后按新色重渲染）。

        ``icons.available()`` 为假时不设图标（回落纯文本，绝不空白/崩）。
        """
        if icons is None:
            return
        try:
            if not icons.available():
                return
            color = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        except Exception:
            return
        for attr, name in getattr(self, "_status_icon_specs", ()):
            label = getattr(self, attr, None)
            if label is None:
                continue
            try:
                rendered = icons.icon(name, 14, color)
                if rendered is not None and not rendered.isNull():
                    label.setPixmap(rendered.pixmap(14, 14))
            except Exception:
                continue

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
            logger.debug("静默降级：refresh_api_status 中忽略异常", exc_info=True)
        # v1.2(B9): 侧栏「模型状态」按钮同步刷新（provider/脱敏 Key/状态点）
        if hasattr(self, "sidebar"):
            try:
                self.sidebar.update_model_status()
            except Exception:
                logger.debug("静默降级：refresh_api_status 中忽略异常", exc_info=True)

    def _connect_signals(self) -> None:
        """连接跨组件信号。"""
        # 侧边栏导航 → 页面切换
        self.sidebar.item_clicked.connect(self._on_navigate)
        # v1.2.x 修复：任何入口的导航（首页快捷按钮/宠物回首页/onboarding/back）
        # 都同步侧栏高亮，避免「页面已切、高亮停旧处」错位
        try:
            self.page_manager.page_changed.connect(self.sidebar.set_active_page)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # 侧边栏底部按钮
        self.sidebar.help_clicked.connect(self._on_help_clicked)
        self.sidebar.about_clicked.connect(self._on_about_clicked)

        # v1.2(B9): 侧栏「模型状态」直达 → open_model_settings
        try:
            self.sidebar.model_clicked.connect(self.open_model_settings)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # v1.2(A-11): 侧栏「码铃形象入口」点击 → 回首页（兜底导航在 sidebar 内部也有）
        try:
            self.sidebar.maid_clicked.connect(self._on_sidebar_maid_clicked)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # 主题变更 → 状态栏更新
        self.theme_engine.theme_changed.connect(self._on_theme_changed)
        # v2.1(V21-08/D-V21-04): 追加订户——深浅变化须重设 DWM 材质/图标着色
        # （既有 _on_theme_changed 签名与语义零变更，仅新增订阅者）
        try:
            self.theme_engine.theme_changed.connect(self._on_theme_changed_glass)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # v2.1(V21-08/M-1): 切页过渡（页面栈换页处挂 motion.fade）
        try:
            self.page_manager.page_changed.connect(self._on_page_switched)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # v2.1(P1 铺开): 按压反馈由「仅侧栏」扩到**整个主窗** —— 覆盖各页静态按钮
        # 与工具栏 QToolButton（页面/状态栏已在 _setup_pages / _setup_status_bar 建好）；
        # 对话框按需创建且数量多，改用一个应用级过滤器在「显示时」自动铺开。
        # 只改 opacity，不动 geometry/size/font；off 档或已挂非 opacity effect 的控件
        # 自动跳过；永不吞事件，原有点击逻辑零影响。
        try:
            if transitions is not None:
                transitions.install_press_feedback_recursive(self)
                transitions.install_press_feedback_for_dialogs()
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

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
            logger.debug("静默降级：_on_onboarding_finished 中忽略异常", exc_info=True)
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
                logger.debug("静默降级：open_model_settings 中忽略异常", exc_info=True)

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
                logger.debug("静默降级：_on_sidebar_maid_clicked 中忽略异常", exc_info=True)

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
        # v2.1(V21-08/I-3): 换肤后状态栏图标按新色重渲染（字体不可用则跳过）
        self._refresh_status_icons()

    def _on_theme_changed_glass(self, _theme_name: str) -> None:
        """v2.1(V21-08/D-V21-04): 深浅切换后重应用毛玻璃材质（幂等，绝不抛）。

        材质深浅由 ``DWMWA_USE_IMMERSIVE_DARK_MODE`` 决定，必须在换肤后重设，
        否则切深色后材质仍是浅色调。
        """
        try:
            self._apply_glass_state()
        except Exception:
            logger.debug("静默降级：_on_theme_changed_glass 中忽略异常", exc_info=True)

    # ------------------------------------------------------------------
    # v2.1(V21-08 / D-V21-04 / D-V21-05)：毛玻璃单一收口
    # ------------------------------------------------------------------
    def _repolish(self) -> None:
        """重刷玻璃条件规则实际影响到的结构控件（安全、范围受控）。

        ``glass`` 是主窗的动态属性，但 QSS 条件规则命中的是它的中间容器
        （central outer / splitter / page stack）。只 polish 主窗时，这些后代控件
        在部分 Qt 平台不会重算祖先属性选择器，导致 Mica 虽已设好却仍被主题背景盖住。
        这里仅刷新 4 个固定结构控件；调用时机只有玻璃开关或换肤，避免递归遍历
        页面子树带来的性能成本。
        """
        try:
            style = self.style()
            if style is None:
                return
            widgets = (
                self,
                getattr(self, "central_outer", None),
                getattr(self, "central_splitter", None),
                getattr(self, "page_stack", None),
            )
            for widget in widgets:
                if widget is None:
                    continue
                style.unpolish(widget)
                style.polish(widget)
                widget.update()
        except Exception:
            logger.debug("静默降级：_repolish 中忽略异常", exc_info=True)

    def _lock_window_opacity(self) -> None:
        """玻璃生效 → 窗口不透明度锁 100%（Q-V8：不与材质叠加成双半透明）。"""
        try:
            if abs(float(self.windowOpacity()) - 1.0) > 1e-6:
                self.setWindowOpacity(1.0)
        except Exception:
            logger.debug("静默降级：_lock_window_opacity 中忽略异常", exc_info=True)

    def _restore_window_opacity(self, config) -> None:
        """玻璃关 / 不支持 → 恢复用户透明度设置（R-Q③：与改动前一致）。"""
        try:
            target = float(getattr(config, "window_opacity", 1.0))
        except Exception:
            target = 1.0
        try:
            if abs(float(self.windowOpacity()) - target) > 1e-6:
                self.setWindowOpacity(target)
        except Exception:
            logger.debug("静默降级：_restore_window_opacity 中忽略异常", exc_info=True)

    def _glass_applicable(self, config) -> bool:
        """判据：``glass_enabled`` 且环境支持且能力 ``kind`` 为主窗适用。"""
        if not bool(getattr(config, "glass_enabled", True)):
            return False
        if glass is None:
            return False
        try:
            if not bool(glass.is_supported()):
                return False
            kind = getattr(glass.detect_capability(), "kind", "none") or "none"
            return kind in ("mica", "acrylic")
        except Exception:
            return False

    def _apply_glass_state(self) -> None:
        """毛玻璃单一收口（幂等）：DWM 材质 + 根属性 + 透明度互斥。

        判据：``cfg.glass_enabled`` 且 ``glass.is_supported()`` 且 kind 适用。
          · 不满足 → ``glass.remove()`` + **移除** ``glass`` 动态属性 + 恢复透明度
            （R-Q③：关掉后与改动前观感一致）；
          · 满足 → 先锁 ``setWindowOpacity(1.0)``（避免 WS_EX_LAYERED 与 DWM 材质冲突），
            再 ``glass.safe_apply(winId, "mica", dark=is_dark_effective)``；成功后置动态属性
            ``glass="on"`` 并重刷实际受影响的结构控件。
        ``winId()`` 在 show 前可能无效 → ``safe_apply`` 返回 False 时不设属性、不崩，
        由 ``showEvent`` 重试。全部 try/except，绝不抛。
        """
        config = getattr(self.app_ctx, "config", None)
        applicable = self._glass_applicable(config)

        # 取窗口句柄（无效 = 0；safe_apply/remove 内部同样校验）
        try:
            hwnd = int(self.winId())
        except Exception:
            hwnd = 0

        if not applicable:
            if glass is not None:
                try:
                    glass.remove(hwnd)
                except Exception:
                    logger.debug("静默降级：_apply_glass_state 中忽略异常", exc_info=True)
            if self.property("glass") is not None:
                self.setProperty("glass", None)  # 移除动态属性 → 恢复主题背景
                self._repolish()
            self._restore_window_opacity(config)
            return

        try:
            dark = bool(self.theme_engine.is_dark_effective())
        except Exception:
            dark = False

        # DWM Mica 与低于 1.0 的 Qt 窗口透明度（WS_EX_LAYERED）不可叠加：必须在
        # safe_apply *之前* 锁到 1.0，否则 Windows 可能接受 API 调用却不显示材质。
        self._lock_window_opacity()

        applied = False
        if glass is not None:
            try:
                applied = bool(glass.safe_apply(hwnd, "mica", dark=dark))
            except Exception:
                applied = False

        if applied:
            if self.property("glass") != "on":
                self.setProperty("glass", "on")
                self._repolish()
        else:
            # winId 尚未有效 / DWM 应用失败 → 纯色降级（fail-safe，不黑窗）
            if self.property("glass") is not None:
                self.setProperty("glass", None)
                self._repolish()
            self._restore_window_opacity(config)

    def showEvent(self, event) -> None:
        """窗口显示后 HWND 才有效 → 应用毛玻璃（失败静默降级）。"""
        super().showEvent(event)
        try:
            self._apply_glass_state()
        except Exception:
            logger.debug("静默降级：showEvent 中忽略异常", exc_info=True)

    def changeEvent(self, event) -> None:
        """最小化还原 / 重显后部分 Windows 版本会丢材质 → 窗口状态变化时重应用。"""
        try:
            super().changeEvent(event)
        except Exception:
            logger.debug("静默降级：changeEvent 中忽略异常", exc_info=True)
        try:
            if event is not None and event.type() == QEvent.WindowStateChange:
                self._apply_glass_state()
        except Exception:
            logger.debug("静默降级：changeEvent 中忽略异常", exc_info=True)

    # ------------------------------------------------------------------
    # v2.1(V21-08 / M-1)：切页过渡（淡入新页，动画结束移除 effect）
    # ------------------------------------------------------------------
    def _on_page_switched(self, key: str) -> None:
        """页面切换后对新页淡入（不滑动整页，避免布局震荡；切页返回不阻塞）。"""
        try:
            page = None
            pages = getattr(self, "pages", None)
            if isinstance(pages, dict):
                page = pages.get(key)
            if page is None:
                page = self.page_stack.currentWidget()
            if page is None:
                return
            if motion is None:
                self._finish_page_fade(page)
                return
            # 同页快速重切：先停掉上一段未完成的淡入（stop 不发 finished，不会误触发收尾）
            running = self._page_fade_anims.pop(page, None)
            if running is not None:
                try:
                    running.stop()
                except Exception:
                    logger.debug("静默降级：_on_page_switched 中忽略异常", exc_info=True)
            # 切页淡入**唯一落点**：直接走 motion.fade，不经 gui.transitions
            # （transitions 本轮只提供按钮按压反馈，勿在此重复接入）。
            anim = motion.fade(
                page, to=1.0,
                on_finished=lambda p=page: self._finish_page_fade(p),
            )
            if anim is None:
                # off 档 / 系统减少动画 → 直接终态（不创建 effect/动画）
                self._finish_page_fade(page)
            else:
                self._page_fade_anims[page] = anim
        except Exception:
            logger.debug("静默降级：_on_page_switched 中忽略异常", exc_info=True)

    def _finish_page_fade(self, page) -> None:
        """淡入收尾：移除 ``QGraphicsOpacityEffect``（防长期重绘开销，R-P）。"""
        self._page_fade_anims.pop(page, None)
        try:
            effect = page.graphicsEffect()
            if isinstance(effect, QGraphicsOpacityEffect):
                page.setGraphicsEffect(None)
        except Exception:
            logger.debug("静默降级：_finish_page_fade 中忽略异常", exc_info=True)

    def _on_mode_changed(self, mode_name: str, state: bool) -> None:
        """模式变更处理。"""
        modes = {
            "deep": "深度思考",
            "coding": "编程模式",
        }
        label = modes.get(mode_name, mode_name)
        self.status_mode.setText(f"模式: {label} {'开' if state else '关'}")

    def _on_intimacy_changed(self, message: str) -> None:
        """好感度升级：显示提示，并刷新首页关系称谓。"""
        try:
            self.status_bar.showMessage(f"💕 {message}", 5000)
        except Exception:
            logger.debug("静默降级：_on_intimacy_changed 中忽略异常", exc_info=True)
        try:
            home_page = self.pages.get("home") if isinstance(self.pages, dict) else None
            refresh = getattr(home_page, "_refresh_companion_panel", None)
            if callable(refresh):
                refresh()
        except Exception:
            logger.debug("刷新首页关系称谓失败", exc_info=True)
        try:
            refresh_chip = getattr(getattr(self, "sidebar", None), "update_maid_chip", None)
            if callable(refresh_chip):
                refresh_chip()
        except Exception:
            logger.debug("刷新侧栏角色与关系称谓失败", exc_info=True)

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
            logger.debug("静默降级：_show_and_navigate 中忽略异常", exc_info=True)
        pm = getattr(self.app_ctx, "page_manager", None)
        if pm is not None and hasattr(pm, "navigate"):
            try:
                pm.navigate(page_key)
            except Exception:
                logger.debug("静默降级：_show_and_navigate 中忽略异常", exc_info=True)

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
                logger.debug("静默降级：open_float_chat 中忽略异常", exc_info=True)
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
                logger.debug("静默降级：trigger_camera 中忽略异常", exc_info=True)

    def trigger_voice(self) -> None:
        """🎤 语音输入：呼主窗并触发聊天面板单次语音输入路径。"""
        self._show_and_navigate("chat")
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "_on_voice_input"):
            try:
                panel._on_voice_input()
            except Exception:
                logger.debug("静默降级：trigger_voice 中忽略异常", exc_info=True)

    def trigger_screenshot(self) -> None:
        """🖼 截图提问：调 chat_panel.capture_screenshot（内部自带呼出+导航，P1-2 既有链）。"""
        panel = getattr(self, "chat_panel", None)
        if panel is not None and hasattr(panel, "capture_screenshot"):
            try:
                panel.capture_screenshot()
            except Exception:
                logger.debug("静默降级：trigger_screenshot 中忽略异常", exc_info=True)

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
                logger.debug("静默降级：closeEvent 中忽略异常", exc_info=True)
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
