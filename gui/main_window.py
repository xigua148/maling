"""MainWindow —— QMainWindow 三栏布局（侧边栏 | 内容区 | 聊天面板）。"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from gui.qt_compat import (
    QMainWindow, QWidget, QStackedWidget, QSplitter,
    QVBoxLayout, QHBoxLayout, QStatusBar, QLabel, Qt,
    QPushButton,  # v1.2.1: 顶部 Key 引导横幅
    QPixmap,  # v2.1.1: 状态栏图标清空/降级
    QEvent, QGraphicsOpacityEffect,  # v2.1(V21-08): 窗口状态重应用 / 切页淡入收尾
    QApplication,  # v2.2.1(黑框修复 WP3): 应用级焦点事件过滤器
    QSlider,  # v2.2.1(黑框修复 WP3): 滑杆手柄焦点描边同样要分流
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
from gui.pages.page_tavern import PageTavern  # v2.2(V22-09): 酒馆（AI 陪伴叙事）
from gui.pages.onboarding import OnboardingDialog

logger = logging.getLogger("maid_coder.gui")

#: v2.2.1(黑框修复 WP3)：标在 QPushButton 上的动态属性 —— 只有「键盘导航进来的焦点」
#: 才置 True，base.qss 用它门控 `outline`。
#: 背景：base.qss 原为 `QPushButton:focus { outline: 1px solid ${text}; }`，四套主题的
#: ${text} 都是近黑色（#1C1C1E / #3D2E2A / #12303F）→ **鼠标点击任意按钮**都会在内容区
#: 边缘描出一圈近黑矩形（用户报「选定的黑框」「退出弹窗两个选项的黑框」）。Qt QSS 没有
#: `:focus-visible`，故用本属性把「键盘焦点」与「鼠标焦点」分开：鼠标路径零描边（回到
#: 「按压提示足够」），键盘路径保留一圈细的 ${accent_text} 指示（可达性不丢，任务 #280）。
#: 属性值变化后**必须** unpolish/polish 才会重新求值（Qt 只在 polish 时匹配属性选择器）。
_KBD_NAV_PROP = "keyboardNav"
#: 判定「键盘/助记键进来的焦点」的 reason 白名单（其余一律视为指针/程序性焦点）。
_KBD_NAV_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)


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

        # 8. 页面根 / 侧栏底色属性
        # 必须放在第 7 步**之后**：``_check_first_run()`` 会把 ``OnboardingDialog``
        # addWidget 到页面栈（晚入栈页根），早于它执行就会漏掉该页根。
        self._ensure_page_backgrounds()

        # 9. v2.2.1(黑框修复 WP3)：应用级焦点事件过滤器 —— 按 QFocusEvent.reason()
        # 给 QPushButton / QSlider 打 keyboardNav 动态属性，供 base.qss 门控焦点描边。
        # 装在这里（而非 gui/main.py）以免触碰更新编排段；只处理 FocusIn、永不吞事件。
        try:
            _app = QApplication.instance()
            if _app is not None:
                _app.installEventFilter(self)
        except Exception:
            logger.debug("静默降级：安装焦点事件过滤器失败", exc_info=True)

    # ------------------------------------------------------------------
    # v2.2.1(黑框修复 WP3)：焦点描边的「键盘/鼠标」分流
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt 命名)
        """应用级过滤器：给拿到焦点的 ``QPushButton`` / ``QSlider`` 标 ``keyboardNav``。

        只认 ``QEvent.FocusIn``；其余事件原样交回基类（**永不吞事件**）。
        分流依据 ``QFocusEvent.reason()``：
          · ``TabFocusReason`` / ``BacktabFocusReason`` / ``ShortcutFocusReason``
            → ``keyboardNav = True`` → base.qss 画出细的 ``${text_on_accent}`` 焦点圈；
          · 其余（``MouseFocusReason`` / ``ActiveWindowFocusReason`` /
            ``PopupFocusReason`` / ``OtherFocusReason`` …）→ ``False`` → 零描边。
        只在属性值**真的变化**时才 unpolish/polish（避免无谓重绘）。

        纳入 ``QSlider`` 的依据（真机实测）：它默认 ``focusPolicy() == 11``
        （``ClickFocus|TabFocus``）→ **鼠标点一下滑杆就给焦点**，于是
        ``QSlider::handle:horizontal:focus`` 的近黑描边在指针路径上也会出现
        （聚焦帧差 85~87px）→ 与按钮同属用户否掉的那一类，故一并分流。
        ``QTabBar`` **不纳入**：默认 ``focusPolicy() == 1``（``TabFocus``），鼠标点击
        不给焦点，其近黑下划线只出现在键盘路径 = 该保留的可达性提示。
        """
        try:
            if event is not None and event.type() == QEvent.FocusIn:
                if isinstance(obj, (QPushButton, QSlider)):
                    try:
                        reason = event.reason()
                    except Exception:
                        reason = None
                    kbd = reason in _KBD_NAV_REASONS
                    cur = obj.property(_KBD_NAV_PROP)
                    # ``cur is None``（从未写过）也要落到 False —— 否则属性一直不存在，
                    # QSS 选择器虽然同样不命中，但「可读性 / 可断言性」都差一档。
                    if cur is None or bool(cur) != kbd:
                        obj.setProperty(_KBD_NAV_PROP, kbd)
                        style = obj.style()
                        if style is not None:
                            style.unpolish(obj)
                            style.polish(obj)
        except Exception:
            logger.debug("静默降级：eventFilter 中忽略异常", exc_info=True)
        return super().eventFilter(obj, event)

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
            ("tavern", PageTavern, "酒馆"),  # v2.2(V22-09)
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

    def _ensure_page_backgrounds(self) -> None:
        """给「页面根 / 侧栏」打开 ``WA_StyledBackground``，让主题 QSS 底色真正被绘制。

        缺陷（毛玻璃下整块透黑）：``SidebarWidget`` 与全部页面类都是**直接继承
        ``QWidget`` 的 Python 子类**，metaobject 与 ``QWidget`` 不同 → Qt 的样式表
        引擎**不会**给它自动置 ``Qt::WA_StyledBackground``。实测（app 级 QSS +
        ``show()`` + ``ensurePolished()`` 后取样）：

          · ``QWidget()``                    → True
          · ``QFrame``                       → True
          · Python 的 ``QFrame`` 子类         → True
          · **Python 的 ``QWidget`` 子类**    → **False**

        「不被自动置位」只适用于**直接继承 ``QWidget`` 的 Python 子类**这一档
        （``QFrame`` 子类不受此影响）；且 ``QWidget()`` / ``QSplitter`` 在**构造
        时刻**实测同样为 False，需 ``show()`` / polish 之后才被引擎置为 True ——
        故本修复在 ``__init__`` 末尾（``_check_first_run()`` 之后）**显式补位**，
        不依赖 polish 时机。

        该属性缺失时 ``QWidget::paintEvent`` 不画 ``PE_Widget``，故主题 QSS 里的
        ``QWidget { background-color: ${bg} }`` / ``SidebarWidget
        { background-color: ${bg_card} }`` **完全不生效**，控件区域保持「未绘制」。

        为什么只在毛玻璃下暴露：玻璃关时未绘制区透出 MainWindow 自绘的 ``${bg}``
        （看起来正常）；玻璃开时 base.qss §1 把 ``glassCentralOuter`` /
        ``glassCentralSplitter`` / ``glassPageStack`` 置 ``background: transparent``
        （D-V21-04），链路再无底色可透 → 真机呈全透明（截图转 RGB 即成纯黑）。
        实测读数：侧栏矩形黑占比约 79.5%~79.8%（玻璃开，两次独立采样）→ 0.0%
        （本修复后）。修复前黑区不止侧栏，全窗扫描共 8 处未绘制：help 44.5% /
        about 26.7% / memories 17.2% / memory_book 15.9% / project 13.8% /
        tavern 1.9% / chat 1.6%（20px 全高缝）/ 侧栏 79.5%，本修复后全部归零。

        **注意：这不是「零视觉变化」的改动。** 玻璃**关闭**时侧栏底色同样会改变
        （``${bg}`` → ``${bg_card}``，如 ``#F7F7F8`` → ``#FFFFFF``；四风格实测
        两色对比度 ≤1.094、ΔL* ≤4.04），依据是 ``SidebarWidget`` 那条底色规则本身
        **无条件、没有 ``[glass="on"]`` 门控** —— 改前显示 ``${bg}`` 属「属性缺失
        导致整条规则失效」的偶然结果；同一规则里的 1px ``border-right`` 也随之恢复
        绘制（此前同样被跳过）。页面根则与该区域原有底色同值（``${bg}``），实测
        13 页 × 4 风格改前/改后零像素差异。读数留档见 ``_probe/glass_off_matrix.txt``。

        与 base.qss §1 注释「页面根、侧栏…仍需各自的主题底色保持可读」的设计意图
        一致，也符合 G-1 验收②「不支持时保持纯色 ${bg}，不黑窗」。仅补属性，不动
        任何 QSS / 配色 / 布局。

        **候选集口径（治类不治例）**：取「侧栏 ∪ ``self.pages`` ∪ ``page_stack``
        的**全部直接子级**」。只听 ``self.pages`` 会漏掉**晚入栈的页根** ——
        ``OnboardingDialog`` 由 ``_check_first_run()`` 在 ``_setup_pages()`` 之后才
        ``page_stack.addWidget()``（见 ``_show_onboarding``），它不在 ``self.pages``
        里，玻璃开时实测未绘制 6.87%。并入页面栈直接子级后，同类时序漏网自动闭合。
        本方法**幂等**，可安全重入。
        """
        roots = [self.sidebar, *self.pages.values()]
        stack = getattr(self, "page_stack", None)
        if stack is not None:
            try:
                roots.extend(stack.widget(i) for i in range(stack.count()))
            except Exception:
                logger.debug("静默降级：枚举页面栈子级失败", exc_info=True)

        seen = set()
        for widget in roots:
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            try:
                widget.setAttribute(Qt.WA_StyledBackground, True)
            except Exception:
                logger.debug("静默降级：页面底色属性设置失败", exc_info=True)

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

    def _make_status_item(self, key: str, text: str) -> QLabel:
        """构造一个状态项：``[图标 QLabel] + [文案 QLabel]`` 装进 ``QHBoxLayout`` 容器。

        **为什么不共用一个 QLabel**：Qt 的 ``QLabel`` 单次只能显示 pixmap 或 text
        之一 —— ``setText()`` 会清掉已设的 pixmap，``setPixmap()`` 会清掉已有的
        text。若把图标设到文案 label 上（旧实现），文案立即被清空；API 状态路径又
        反向调 ``setText()`` 把图标清掉，于是三项互相覆盖（v2.1.1 修复的既有缺陷）。
        拆成两个 QLabel 从结构上杜绝这类互斥。

        返回**文案 QLabel**，由调用方挂到 ``self.status_theme`` / ``status_mode`` /
        ``status_api`` —— 保持 ``.text()`` 语义与既有 ``setText()`` 调用点零变更。

        内边距：主题 QSS 有 ``QStatusBar QLabel { padding: 0 12px; }`` 后代规则，
        会**同时命中**图标与文案两个子 label（旧实现只有一个 label，故无此问题），
        使图标与文案之间出现 24px 空洞、图标「浮空」。此处仅重排内边距、不改字号/
        颜色：项左内边距 12px 收口到容器，图标 label 居中无内边距，文案保留右侧
        12px —— 最终节奏与旧「单标签 12px 内边距」一致（图标 14px + 4px 间距 + 文案）。
        """
        suffix = key[len("status_"):] if key.startswith("status_") else key
        container = QWidget(self.status_bar)
        container.setObjectName(f"statusItem_{suffix}")
        row = QHBoxLayout(container)
        row.setContentsMargins(12, 0, 0, 0)  # 项左内边距（与旧单标签 12px 左内边距一致）
        row.setSpacing(4)

        icon_label = QLabel(container)
        icon_label.setObjectName(f"statusIcon_{suffix}")
        icon_label.setVisible(False)  # 图标未就绪前隐藏，避免留空白占位
        # 去掉 QSS 给子 label 的左右内边距，图标紧贴容器左内边距、右侧只留 4px 间距
        icon_label.setStyleSheet(f"QLabel#statusIcon_{suffix} {{ padding: 0; }}")

        text_label = QLabel(text, container)
        text_label.setObjectName(f"statusText_{suffix}")
        # 文案保留右侧 12px 项内边距；左侧去掉（由容器左内边距 + 4px 间距接管）
        text_label.setStyleSheet(f"QLabel#statusText_{suffix} {{ padding: 0 12px 0 0; }}")

        row.addWidget(icon_label)
        row.addWidget(text_label)
        self.status_bar.addWidget(container)
        self._status_icon_labels[key] = icon_label
        return text_label

    def _setup_status_bar(self) -> None:
        """构建状态栏。v10.15: API 状态通过 refresh_api_status() 统一刷新。

        v2.1(V21-08/I-3): 三个状态项图标化（矢量优先；字体不可用回落纯文本）。
        v2.1.1: 图标与文案拆成两个 QLabel（见 :meth:`_make_status_item`）——
        ``QLabel`` 单次只能显示 pixmap 或 text，共用一个 label 会互相覆盖。
        ``self.status_theme`` / ``status_mode`` / ``status_api`` **仍指向文案
        label**，故所有 ``.text()`` / ``setText()`` 调用点语义不变。
        """
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # v2.1(V21-08): 状态项图标名（不可用时不设图标，文案原样保留）
        self._status_icon_specs = (
            ("status_theme", "palette"),
            ("status_mode", "mode"),
            ("status_api", "api"),
        )
        # key → 图标 QLabel（与 _status_icon_specs 的 attr 对齐）
        self._status_icon_labels: Dict[str, QLabel] = {}

        self.status_theme = self._make_status_item("status_theme", "主题: 现代极简")
        self.status_mode = self._make_status_item("status_mode", "模式: 标准")
        self.status_api = self._make_status_item("status_api", "API: 未配置")

        self._refresh_status_icons()

        # v10.15: 初始化时调用 refresh_api_status()，由它判断已配置/未配置
        self.refresh_api_status()

    def _refresh_status_icons(self) -> None:
        """V21-08/I-3: 状态项图标化（换肤后按新色重渲染）。

        图标一律落在**独立的图标 QLabel**（``self._status_icon_labels``）上，
        **绝不**设到文案 label —— 否则会清掉文案（``QLabel`` pixmap/text 互斥，
        见 :meth:`_make_status_item`）。

        ``icons`` 为 None / ``available()`` 为假 / 渲染失败 / 渲染为空时：清空并
        **隐藏**该图标 label（隐藏而非留空白，避免状态栏出现莫名空隙），文案原样
        保留，绝不空白 / 崩。
        """
        labels = getattr(self, "_status_icon_labels", None) or {}
        for attr, name in getattr(self, "_status_icon_specs", ()):
            icon_label = labels.get(attr)
            if icon_label is None:
                continue

            rendered = None
            if icons is not None:
                try:
                    if icons.available():
                        color = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
                        rendered = icons.icon(name, 14, color)
                except Exception:
                    logger.debug("静默降级：状态栏图标渲染失败", exc_info=True)
                    rendered = None

            try:
                if rendered is not None and not rendered.isNull():
                    icon_label.setPixmap(rendered.pixmap(14, 14))
                    icon_label.setVisible(True)
                else:
                    icon_label.setPixmap(QPixmap())
                    icon_label.setVisible(False)
            except Exception:
                logger.debug("静默降级：状态栏图标应用失败", exc_info=True)

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

        # v2.1(修复 #279 续): 首页「最近会话」点击 → 切到该会话。此前
        # `PageHome.session_selected` 全仓零消费者（点了没反应）；范式与上面
        # `project_page.file_opened` 一致（页面发信号 → 主窗消费）。
        home_page = self.pages.get("home")
        if isinstance(home_page, PageHome):
            home_page.session_selected.connect(self._on_home_session_selected)

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
            # v2.2.1(黑框修复 WP2)：若此刻正有页面停在 opacity < 1（淡入进行中），
            # 玻璃一开它就立刻透出纯黑 → 开玻璃的同时把全部页面的淡入残留收干净。
            self._drop_page_fades()
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

            # v2.2.1(黑框修复 WP2)：毛玻璃开 → **不做透明度淡入**。
            # 根因（屏幕级实测）：glass="on" 时 base.qss §1 把 #glassCentralOuter /
            # #glassCentralSplitter / #glassPageStack 置 `background: transparent`，
            # 于是「opacity < 1 的整页」= 整片区域**无人绘制**，屏幕上是纯黑
            # （切页起帧实测纯黑 82.22%、均值 RGB(44,43,43)；glass="off" 同一动作
            # 仅 0.03% —— 该缺陷只在毛玻璃档出现）。motion 内核（gui/motion.py，冻结
            # 内核）在无 effect 时固定从 `start = 0.0` 起淡，签名/默认值不得改动，
            # 故修在**调用点**：该档直接把新页复位为完全不透明，切换交给已经完成的
            # setCurrentWidget（瞬时、无过渡）—— 视觉上是「无淡入直切」，不再是黑屏。
            # glass="off" 保留原有淡入（那里实测无害，v2.1 动效特性不动）。
            if self.property("glass") == "on":
                self._drop_page_fades()
                return

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

    def _drop_page_fades(self) -> None:
        """把**全部**页面的淡入残留收干净：停动画 + 移除 opacity effect（复位完全不透明）。

        v2.2.1(黑框修复 WP2)：只服务于「毛玻璃开」这一档 —— 该档页面栈链路
        （§1 三容器）是 transparent，任何 opacity < 1 的页面都会把**未绘制**区透成
        屏幕纯黑。触发面有两处：① 切页入口（同页重切 / 立即退出撞上未完成的淡入）；
        ② 淡入跑到一半时把毛玻璃打开（``_apply_glass_state`` 的 on 分支）。

        候选集取「``_page_fade_anims`` 的键 ∪ ``self.pages`` ∪ ``page_stack`` 全部
        直接子级」—— 只听动画表会漏掉「动画已 pop、effect 仍在页上」的残留
        （切页入口正是先 pop 再判定），只听 ``self.pages`` 会漏掉晚入栈页
        （``OnboardingDialog``）。本方法幂等，可安全重入。
        """
        targets = set()
        try:
            targets.update(getattr(self, "_page_fade_anims", {}).keys())
        except Exception:
            logger.debug("静默降级：_drop_page_fades 枚举动画表失败", exc_info=True)
        pages = getattr(self, "pages", None)
        if isinstance(pages, dict):
            targets.update(pages.values())
        stack = getattr(self, "page_stack", None)
        if stack is not None:
            try:
                targets.update(stack.widget(i) for i in range(stack.count()))
            except Exception:
                logger.debug("静默降级：_drop_page_fades 枚举页面栈失败", exc_info=True)
        for page in targets:
            if page is None:
                continue
            running = self._page_fade_anims.pop(page, None)
            if running is not None:
                try:
                    running.stop()
                except Exception:
                    logger.debug("静默降级：_drop_page_fades 停动画失败", exc_info=True)
            try:
                effect = page.graphicsEffect()
                if isinstance(effect, QGraphicsOpacityEffect):
                    page.setGraphicsEffect(None)
            except Exception:
                logger.debug("静默降级：_drop_page_fades 移除 effect 失败", exc_info=True)

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

    def _on_home_session_selected(self, session_id: str) -> None:
        """v2.1(修复 #279 续): 首页「最近会话」点击 → 复用既有切换路径切到该会话。

        - 复用 ``ChatPanelWidget._switch_to_session``（会话列表点击 / 标签页切换的
          同一入口），不另造切换逻辑；切换后回聊天主屏。
        - 目标会话不存在 / 会话管理器缺失 / 面板未就绪 → **不崩**，用状态栏给出
          克制提示并 ``logger.debug`` 收口（沿用 ``_on_intimacy_changed`` 的提示方式）。
        """
        panel = getattr(self, "chat_panel", None)
        switch = getattr(panel, "_switch_to_session", None) if panel is not None else None
        if not callable(switch):
            self._notify_home_switch_failed("聊天面板未就绪，暂不能切换会话")
            return
        # 存在性校验（用面板自带的 session_manager，即切换的权威数据源）
        session_manager = getattr(panel, "session_manager", None)
        getter = getattr(session_manager, "get_session", None)
        exists = True
        if callable(getter):
            try:
                exists = getter(session_id) is not None
            except Exception:
                logger.debug("静默降级：会话存在性检查失败 id=%s", session_id, exc_info=True)
                exists = True
        if not exists:
            self._notify_home_switch_failed("那条会话已经找不到了~")
            logger.debug("首页切换会话：目标不存在 id=%s", session_id)
            return
        try:
            switch(session_id)
        except Exception:
            logger.debug("首页切换会话失败 id=%s", session_id, exc_info=True)
            self._notify_home_switch_failed("切换会话时出了点小问题，请到聊天页重试")
            return
        try:
            if self.page_manager is not None:
                self.page_manager.navigate("chat")
        except Exception:
            logger.debug("静默降级：切换会话后导航失败", exc_info=True)

    def _notify_home_switch_failed(self, message: str) -> None:
        """首页切换会话失败/不可用的克制提示（状态栏，短时；失败静默）。"""
        try:
            self.status_bar.showMessage(message, 4000)
        except Exception:
            logger.debug("静默降级：状态栏提示失败", exc_info=True)

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
