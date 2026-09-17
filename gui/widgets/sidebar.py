"""侧边栏导航 —— 7 个导航项 + 底部固定入口（码铃形象/模型状态/帮助/关于），当前项高亮。

v1.2(B9): 底部「模型状态」直达按钮（provider 短名 + 状态点；tooltip 含脱敏 Key），
点击经 model_clicked 由 MainWindow 桥接跳转到设置页「模型与接口」专区并滚动定位。
v1.2(A-11)(B5): 底部新增「码铃形象入口行」—— 迷你码铃头像（复用 MaidAssets 缩略，
随心情换表情）+ 关系称谓文本 + 心情 tooltip；点击回首页。与 B9 模型状态行并存。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    Qt, Signal, QIcon, QPushButton, QHBoxLayout, QLabel, QSize,
    QEvent, QTimer, QCursor,
)
from gui.utils import theme_color
from core import api_status_summary

# v2.1(可观测性)：静默 except 收敛用 —— 本文件此前多处 `except ...: pass` 无任何
#   记录，异常被完全吞掉，问题只能靠肉眼发现。改走 logger.debug 后可在日志里定位
#   （仅记录、不重抛，行为零变化）。
import logging
logger = logging.getLogger("maid_coder.gui.sidebar")

# v2.1(V21-09/D-V21-06): 矢量图标内核（只调用不改）。导入失败静默回退 emoji（R-Q⑤）。
try:
    from gui import icons as _icons
except Exception:  # pragma: no cover - 内核剥离兜底
    _icons = None

def _nav_glyph(name: str, fallback: str) -> str:
    """文本内嵌图标字形；图标内核缺失 / 字体不可用时原样返回 emoji（R-Q⑤）。"""
    try:
        if _icons is None:
            return fallback
        return _icons.text_glyph(name, fallback)
    except Exception:
        return fallback


# 图标渲染尺寸（单一取值；高 DPI 由 icons.icon 内部 setDevicePixelRatio 适配）
_NAV_ICON_SIZE = 18

# 导航项附加数据角色（Qt.UserRole = key，沿用既有信号语义，零变更）
_ROLE_ICON_NAME = Qt.UserRole + 1   # [2] icon_name（None = 走 QIcon.fromTheme）
_ROLE_LABEL = Qt.UserRole + 2       # [1] 展示文案
_ROLE_FALLBACK = Qt.UserRole + 3    # [3] 图标不可用时的 emoji/unicode 回退

# 取色兜底值（仅当活动色板取不到时使用；正常路径一律经 theme_color，禁硬编码颜色）
_NAV_FB_TEXT = "#5D4037"
_NAV_FB_ACCENT = "#FF6B9D"
_NAV_FB_DISABLED = "#9E9E9E"

# v2.1(阶段 C-1): 侧栏导航滚动条 hover 门控（WorkBuddy 风格 —— 鼠标进入侧栏才显示）
# 属性名须与 base.qss 中 QScrollBar[sidebarHover="true"] 选择器严格一致。
_SCROLLBAR_HOVER_PROP = "sidebarHover"
_SCROLLBAR_SCROLL_HOLD_MS = 700   # 滚动停止后 handle 保持可见的时长（ms）
_SCROLLBAR_HOVER_EVENTS = (QEvent.Enter, QEvent.Leave, QEvent.HoverEnter, QEvent.HoverLeave)

# v1.2(A-11): 防御式引入 MaidAssets（缩略/圆裁）与心情 tooltip 拼装（maid_pet 纯函数）。
# 资产不可用时入口退化为「🔔 + 文本」，UI 永不空白/崩溃。
try:
    from gui.maid_avatar import MaidAssets as _SideMaidAssets
    from gui.maid_avatar import mood_to_expression as _side_mood_to_expr
    from gui.widgets.maid_pet import mood_tooltip_text as _side_mood_tooltip
    _SIDEBAR_MAID_OK = _SideMaidAssets is not None
except Exception:
    _SideMaidAssets = None
    _side_mood_to_expr = None
    _side_mood_tooltip = None
    _SIDEBAR_MAID_OK = False

# v1.2.3: 侧栏左下放大的码铃形象（MaidAvatar，QT_OK 才接）+ 表情差分联动
try:
    from gui.maid_avatar import MaidAvatar as _SideMaidAvatar
    from gui.maid_avatar import QT_OK as _MAID_BIG_OK
except Exception:
    _SideMaidAvatar = None
    _MAID_BIG_OK = False

_sidebar_assets_cache = None


def _sidebar_assets():
    """模块级共享 MaidAssets（每个侧栏只解析一次主形象资产）。"""
    global _sidebar_assets_cache
    if _sidebar_assets_cache is None and _SIDEBAR_MAID_OK:
        try:
            _sidebar_assets_cache = _SideMaidAssets()
        except Exception:
            _sidebar_assets_cache = None
    return _sidebar_assets_cache


class SidebarWidget(QWidget):
    """侧边栏导航组件。"""

    item_clicked = Signal(str)  # 参数：页面 key
    help_clicked = Signal()
    about_clicked = Signal()
    model_clicked = Signal()    # v1.2(B9): 「模型状态」直达按钮
    maid_clicked = Signal()     # v1.2(A-11): 码铃形象入口点击（回首页）

    # v2.1(V21-09/D-V21-06 + §4.5): 3 元组 → 4 元组
    # (key, label, icon_name, fallback_text)。[0]key/[1]label 语义零变更（R-D）；
    # [2] 图标名（已登记语义名；project 为 None → 走 QIcon.fromTheme("folder")）；
    # [3] = 原第三元（emoji/unicode），图标字体不可用时回退，绝不空白。
    NAV_ITEMS = [
        ("chat",        "聊天",     "chat",         "\U0001F4AC"),  # 💬
        ("home",        "首页",     "home",         "\u2302"),      # ⌂
        ("memories",    "回忆",     "auto_awesome", "\u2728"),      # ✨  v1.3(P2-3)
        ("memory_book", "记忆中心", "menu_book",    "\U0001F4D4"),  # 📔  v1.6(P0-1)
        ("project",     "项目",     None,           "\U0001F4C1"),  # 📁  沿用文件夹降级链
        ("file",        "文件",     "edit",         "\u270E"),      # ✎
        ("plan",        "计划",     "list",         "\u2630"),      # ☰
        ("tavern",      "酒馆",     "glass",        "\U0001F377"),  # 🍷  v2.2(V22-09)
        ("agent",       "角色",     "person",       "\u263A"),      # ☺
        # 用户诉求：调换「工具 / 设置」两项的**图标**（[2] icon_name）—— 工具的本义是滑杆
        # （tune），设置的本义是齿轮（settings），此前二者写反。[1] label / [0] key 零变更。
        # 随后配套：交换 [2] 后 [3] 回退 emoji 变得语义不配对（工具=滑杆却回退 ⚙、
        # 设置=齿轮却回退 ⚑），故一并订正为「工具 → 扳手 U+1F527 / 设置 → 齿轮 U+2699」。
        #   · U+1F527 沿用本仓既有「工具类」回退约定（gui/widgets/tool_trace.py:223、
        #     gui/chat_input_logic.py:72 均以 🔧 作 plugin/工具 的 text_glyph 回退），非新造；
        #   · U+2699 与设置语义同族（gui/pages/page_home.py:728 的「⚙ 模型设置」同字符）。
        ("tools",       "工具",     "tune",         "\U0001F527"),  # 🔧
        ("settings",    "设置",     "settings",     "\u2699"),      # ⚙
        # v2.2.3(内置 SillyTavern): 用户指定的入口名 —— 就是字符串「Silly Tavern」
        #   （含空格，**不**译成中文、不改写）。**纯追加**在末位：既有 11 项的
        #   key/label/顺序逐项零变更（v2.2 的「tavern 是 plan→agent 之间的纯插入」
        #   契约因此不受影响）。
        #   图标：矢量取 question_answer（对话气泡，manifest 已登记语义名），与旧
        #   「酒馆」项的 glass（酒杯）不重名；图标字体不可用时回退 🎭（扮演 —— ST 是
        #   角色扮演前端），两项的回退字符亦不重复。
        ("sillytavern", "Silly Tavern", "question_answer", "\U0001F3AD"),  # 🎭
    ]

    #: 侧栏条目的悬停说明（v2.2.3）。键与 NAV_ITEMS 的 key 对齐，未登记则无提示。
    #: **刻意独立于 NAV_ITEMS**：后者的 4 元结构自 v2.1 起冻结（[0]key / [1]label 语义
    #: 被多处测试断言），塞第 5 个元素会打破契约，故另开一张表。
    #: 这里同时承担「语义区分」职责 —— 「旧酒馆」与「Silly Tavern」都是角色扮演向入口，
    #: 用户容易混，悬停一句话说清各自定位（前者是项目自研的轻量剧情引擎，后者是原样
    #: 捆绑的第三方专业前端）。
    NAV_TOOLTIPS = {
        "tavern": "内置轻量剧情引擎：本地成书式文字冒险，角色与进度都存本机",
        "sillytavern": "SillyTavern 1.19.0（专业角色扮演前端）：独立进程，仅本机回环访问",
    }

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._maid_connected = False
        self._role_base_expr = "normal"  # v1.4.2: 角色基线表情
        # Bug2 修复：AI 自选表情的"保持"语义 —— 心情引擎回落事件（如 idle 回 normal）
        # 不应把 AI 标记的表情打回基线；记住最近一次 AI 标记，回落时优先沿用。
        self._last_ai_expr: Optional[str] = None
        self._current_role_id = ""
        self._current_role_name = "码铃"
        self._current_role_assets = None
        self._init_ui()
        # v1.2(A-11): 订阅 mood_changed（心情换表情）+ theme_changed（换肤刷新）
        self._connect_maid_companion()
        # v1.4.2: 订阅角色生效 → 左下角大形象切角色专属资产集
        self._connect_role_bridge()
        # role_changed 的启动广播可能早于 Sidebar 构造，主动读取当前默认角色补齐首帧。
        self._refresh_current_role()
        self.update_maid_chip()
        self._apply_current_role_assets_to_big_avatar()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("sidebarNavList")  # v2.1(C-1): QSS 作用域
        self.list_widget.setFrameShape(QListWidget.NoFrame)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # v2.1(C-1): 竖向滚动条恒占位（AlwaysOn）—— 空闲时 handle 透明（见 base.qss）。
        # 实测 AsNeeded 会因出现/消失使 viewport 宽 156↔168 跳变；AlwaysOn 恒 156 无跳版。
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setCursor(Qt.PointingHandCursor)
        self.list_widget.setIconSize(QSize(_NAV_ICON_SIZE, _NAV_ICON_SIZE))

        # v2.1(V21-09): 矢量图标优先，字体不可用 → [3] emoji 回退（不空白、不崩）
        for key, label, icon_name, fallback_text in self.NAV_ITEMS:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, key)
            item.setData(_ROLE_ICON_NAME, icon_name)
            item.setData(_ROLE_LABEL, label)
            item.setData(_ROLE_FALLBACK, fallback_text)
            self._apply_nav_item_icon(item, selected=False, enabled=True)
            _tip = self.NAV_TOOLTIPS.get(key)
            if _tip:
                item.setToolTip(_tip)
            self.list_widget.addItem(item)

        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget, 1)

        # v1.2(B9): 「模型状态」直达行 —— 状态点 + 直达按钮（脱敏展示）
        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        self.model_dot = QLabel("")
        self.model_dot.setObjectName("sidebarModelDot")
        self.model_dot.setFixedSize(8, 8)
        model_row.addWidget(self.model_dot, 0, Qt.AlignVCenter)
        self.model_btn = QPushButton("模型 · 未配置")
        self.model_btn.setObjectName("sidebarModelBtn")
        self.model_btn.setCursor(Qt.PointingHandCursor)
        self.model_btn.setFixedHeight(30)
        self.model_btn.setToolTip("模型配置：未配置（点击直达设置）")
        self.model_btn.clicked.connect(self._on_model_clicked)
        model_row.addWidget(self.model_btn, 1)
        layout.addLayout(model_row)

        # v1.2.3: 侧栏左下放大的码铃形象（MaidAvatar）+ 表情差分联动
        # 居中放入 model 行与 maid_chip 之间，保留原 mini chip 作"码铃 · 称谓"文本入口。
        self.maid_big_avatar = None
        if _MAID_BIG_OK and _SideMaidAvatar is not None:
            try:
                big = _SideMaidAvatar(
                    parent=self, assets=_sidebar_assets(), expression="normal", size=170,
                )
                big.setMinimumSize(120, 120)
                big_row = QHBoxLayout()
                big_row.setContentsMargins(0, 6, 0, 6)
                big_row.addStretch(1)
                big_row.addWidget(big, 0, Qt.AlignCenter)
                big_row.addStretch(1)
                layout.addLayout(big_row)
                self.maid_big_avatar = big
            except Exception:
                self.maid_big_avatar = None

        # 码铃形象入口行：当前角色专属小形象（随心情）+「角色名 · 好感度阶段」。
        # 位于模型状态行之下、帮助/关于之上；B9 行原样保留、二者共存。
        self.maid_chip = QPushButton("码铃 · 初识")
        self.maid_chip.setObjectName("sidebarMaidChip")
        self.maid_chip.setCursor(Qt.PointingHandCursor)
        self.maid_chip.setFixedHeight(34)
        self.maid_chip.setToolTip("码铃 · 初识（点击回首页）")
        self.maid_chip.clicked.connect(self._on_maid_clicked)
        layout.addWidget(self.maid_chip)
        self._apply_maid_chip_style()
        self.update_maid_chip()

        # 底部固定入口：帮助 + 关于
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(6)

        self.help_btn = QPushButton(f"{_nav_glyph('help', '\u2753')} 帮助")
        self.help_btn.setObjectName("sidebarBottomBtn")
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setFixedHeight(32)
        self.help_btn.clicked.connect(self._on_help_clicked)
        bottom_layout.addWidget(self.help_btn, 1)

        self.about_btn = QPushButton(f"{_nav_glyph('info', '\u2139')} 关于")
        self.about_btn.setObjectName("sidebarBottomBtn")
        self.about_btn.setCursor(Qt.PointingHandCursor)
        self.about_btn.setFixedHeight(32)
        self.about_btn.clicked.connect(self._on_about_clicked)
        bottom_layout.addWidget(self.about_btn, 1)

        layout.addLayout(bottom_layout)

        # 默认选中聊天主屏（NAV_ITEMS 第一项 = "chat"）
        self.list_widget.setCurrentRow(0)

        # v1.2(B9): 初始化即刷新模型状态展示
        self.update_model_status()

        # v2.1(阶段 C-1): 安装滚动条 hover 门控（须在全部子控件建好后）
        self._init_scrollbar_hover()

    # ==================================================================
    # v2.1(阶段 C-1): 侧栏滚动条 —— 默认隐藏，鼠标进入侧栏 / 滚动中才显示
    # ==================================================================
    def _init_scrollbar_hover(self) -> None:
        """安装滚动条 hover 门控（WorkBuddy 风格）。

        机制：监听侧栏自身 + 全部子控件的鼠标进出事件，按**光标是否落在侧栏
        矩形内**（QCursor 全局坐标 → 本地）判定，把结果写入滚动条动态属性
        ``sidebarHover``；base.qss 依该属性切换 handle 颜色（默认透明）。
        另订阅 ``valueChanged``：滚动中短暂保持可见（停止 ``_SCROLLBAR_SCROLL_HOLD_MS``
        后收束）。门控失效时静默降级（滚动条退化为 base.qss 的常显弱化色，不崩）。
        """
        try:
            self._scrollbar_hover = False
            self._scrollbar_scrolling = False
            self._scrollbar_idle_timer = QTimer(self)
            self._scrollbar_idle_timer.setSingleShot(True)
            self._scrollbar_idle_timer.timeout.connect(self._on_scrollbar_idle)
            sb = self.list_widget.verticalScrollBar()
            sb.setProperty(_SCROLLBAR_HOVER_PROP, False)
            sb.valueChanged.connect(self._on_scrollbar_scrolled)
            self.installEventFilter(self)
            for w in self.findChildren(QWidget):
                w.installEventFilter(self)
        except Exception:
            self._scrollbar_idle_timer = None

    def eventFilter(self, obj, event):  # noqa: N802 (Qt 命名)
        """进出事件 → 重算滚动条 hover 态（只读，不消费事件）。"""
        try:
            if event.type() in _SCROLLBAR_HOVER_EVENTS:
                self._update_scrollbar_hover()
        except Exception:
            logger.debug("静默降级：eventFilter 中忽略异常", exc_info=True)
        return super().eventFilter(obj, event)

    def _update_scrollbar_hover(self) -> None:
        """按光标是否在侧栏矩形内刷新 hover 态（幂等，仅在变化时重刷样式）。"""
        try:
            inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
            if inside != getattr(self, "_scrollbar_hover", False):
                self._scrollbar_hover = inside
                self._apply_scrollbar_visibility()
        except Exception:
            logger.debug("静默降级：_update_scrollbar_hover 中忽略异常", exc_info=True)

    def _on_scrollbar_scrolled(self, _value: int = 0) -> None:
        """滚动中保持 handle 可见；停止后延时收束（若光标已不在侧栏）。"""
        try:
            self._scrollbar_scrolling = True
            self._apply_scrollbar_visibility()
            if self._scrollbar_idle_timer is not None:
                self._scrollbar_idle_timer.start(_SCROLLBAR_SCROLL_HOLD_MS)
        except Exception:
            logger.debug("静默降级：_on_scrollbar_scrolled 中忽略异常", exc_info=True)

    def _on_scrollbar_idle(self) -> None:
        """滚动停止保持期结束 → 收束滚动态。"""
        try:
            self._scrollbar_scrolling = False
            self._apply_scrollbar_visibility()
        except Exception:
            logger.debug("静默降级：_on_scrollbar_idle 中忽略异常", exc_info=True)

    def _apply_scrollbar_visibility(self) -> None:
        """把 hover/滚动态落到滚动条动态属性并重刷样式（幂等）。"""
        try:
            sb = self.list_widget.verticalScrollBar()
            visible = bool(getattr(self, "_scrollbar_hover", False)
                           or getattr(self, "_scrollbar_scrolling", False))
            if sb.property(_SCROLLBAR_HOVER_PROP) == visible:
                return
            sb.setProperty(_SCROLLBAR_HOVER_PROP, visible)
            style = sb.style()
            style.unpolish(sb)
            style.polish(sb)
            sb.update()
        except Exception:
            logger.debug("静默降级：_apply_scrollbar_visibility 中忽略异常", exc_info=True)

    def hideEvent(self, event):  # noqa: N802 (Qt 命名)
        """侧栏隐藏 → 复位门控态（避免残留属性导致下次显示即常显）。"""
        try:
            self._scrollbar_hover = False
            self._scrollbar_scrolling = False
            if self._scrollbar_idle_timer is not None:
                self._scrollbar_idle_timer.stop()
            self._apply_scrollbar_visibility()
        except Exception:
            logger.debug("静默降级：hideEvent 中忽略异常", exc_info=True)
        super().hideEvent(event)

    def _on_row_changed(self, row: int) -> None:
        self._refresh_nav_icons()
        item = self.list_widget.item(row)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key:
            self.item_clicked.emit(key)

    # ==================================================================
    # v2.1(V21-09/D-V21-06): 导航图标渲染（矢量优先 / emoji 回退 / 四态着色）
    # ==================================================================
    def _nav_icon(self, icon_name, *, selected: bool, enabled: bool):
        """按态取色并渲染 ``QIcon``；不可用返回 ``None``（调用方回退文本）。

        取色唯一入口 ``theme_color``（禁硬编码颜色）：选中 = ``accent``、
        悬停/普通 = ``text``、禁用 = ``disabled_text``。
        """
        if _icons is None:
            return None
        try:
            if icon_name is None:
                # project 项：按 design §4.5 走 QIcon.fromTheme → emoji 降级链
                theme_icon = QIcon.fromTheme("folder")
                return theme_icon if not theme_icon.isNull() else None
            if not _icons.available():
                return None
            if enabled:
                key = "accent" if selected else "text"
                fallback = _NAV_FB_ACCENT if selected else _NAV_FB_TEXT
            else:
                key, fallback = "disabled_text", _NAV_FB_DISABLED
            color = theme_color(self.app_ctx, key, fallback)
            return _icons.icon(icon_name, _NAV_ICON_SIZE, color)
        except Exception:
            return None

    def _apply_nav_item_icon(self, item, *, selected: bool, enabled: bool) -> None:
        """把图标（或 emoji 回退文本）落到列表项上；两种情况都绝不空白。"""
        label = item.data(_ROLE_LABEL) or ""
        fallback = item.data(_ROLE_FALLBACK) or ""
        icon = self._nav_icon(item.data(_ROLE_ICON_NAME), selected=selected, enabled=enabled)
        if icon is not None and not icon.isNull():
            item.setIcon(icon)
            item.setText(label)
        else:
            item.setIcon(QIcon())
            item.setText(f"{fallback}  {label}" if fallback else label)

    def _refresh_nav_icons(self) -> None:
        """按当前选中行刷新全部导航项图标着色（选中 accent / 其余 text）。"""
        if _icons is None or not _icons.available():
            return
        try:
            current = self.list_widget.currentRow()
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item is None:
                    continue
                enabled = bool(item.flags() & Qt.ItemIsEnabled)
                self._apply_nav_item_icon(item, selected=(i == current), enabled=enabled)
        except Exception:
            logger.debug("静默降级：_refresh_nav_icons 中忽略异常", exc_info=True)

    def _on_sidebar_theme_changed(self, _theme_name: str = "") -> None:
        """换肤 / 深浅切换 → 清图标缓存并按新色重渲染导航图标（V21-09）。"""
        try:
            if _icons is not None:
                _icons.clear_cache()
        except Exception:
            logger.debug("静默降级：_on_sidebar_theme_changed 中忽略异常", exc_info=True)
        self._apply_maid_chip_style()
        self._refresh_nav_icons()

    def set_active_page(self, key: str) -> None:
        """外部导航后同步导航高亮（首页入口/宠物/独立窗等一切 navigate 入口）。

        PageManager.page_changed 连接本方法；blockSignals 防止 setCurrentRow
        触发 _on_row_changed -> item_clicked 递归。key 不在主导航列表
        （如 help/about 底按钮页、back 清空）时取消高亮。
        """
        try:
            target = -1
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                if it is not None and it.data(Qt.UserRole) == key:
                    target = i
                    break
            was_blocked = self.list_widget.signalsBlocked()
            self.list_widget.blockSignals(True)
            try:
                self.list_widget.setCurrentRow(target)
            finally:
                if not was_blocked:
                    self.list_widget.blockSignals(False)
            # 程序化高亮不走 currentRowChanged（已 blockSignals）→ 手动刷新图标着色
            self._refresh_nav_icons()
        except Exception:
            # 高亮同步失败不影响导航本身，静默容错
            pass

    def _on_help_clicked(self) -> None:
        self.help_clicked.emit()

    def _on_about_clicked(self) -> None:
        self.about_clicked.emit()

    def _on_model_clicked(self) -> None:
        self.model_clicked.emit()

    # ==================================================================
    # v1.2(A-11)(B5): 码铃形象入口（心情换表情 + tooltip 文案 + 回首页）
    # ==================================================================
    def _connect_maid_companion(self) -> None:
        """订阅 mood_changed（换表情/文案）与 theme_changed（换肤刷样式）。"""
        if self._maid_connected:
            return
        try:
            bridge = getattr(self.app_ctx, "companion_bridge", None)
            if bridge is not None and hasattr(bridge, "mood_changed") \
                    and hasattr(bridge.mood_changed, "connect"):
                bridge.mood_changed.connect(self._on_maid_mood_changed)
        except Exception:
            logger.debug("静默降级：_connect_maid_companion 中忽略异常", exc_info=True)
        try:
            engine = getattr(self.app_ctx, "theme_engine", None)
            if engine is not None and hasattr(engine, "theme_changed") \
                    and hasattr(engine.theme_changed, "connect"):
                engine.theme_changed.connect(self._on_sidebar_theme_changed)
        except Exception:
            logger.debug("静默降级：_connect_maid_companion 中忽略异常", exc_info=True)
        self._maid_connected = True

    def _on_maid_mood_changed(self, mood: str, reason: str) -> None:
        self.update_maid_chip()
        # v1.4.2: 表情显示策略 —— AI 自选标记直接生效；活动态临时覆盖；
        # Bug2: 其余回落事件优先保持 AI 标记表情，不再一闪而过被打回基线。
        if self.maid_big_avatar is not None:
            try:
                if reason == "ai-markup" and mood:
                    # Bug2: 记住最近一次 AI 标记表情，后续引擎回落事件保持它
                    self._last_ai_expr = mood
                    self.maid_big_avatar.set_maid_expression(mood)
                    return
                from companion import ACTIVITY_STATES
                if mood in ACTIVITY_STATES:
                    # 活动态（thinking/focus/surprised）临时覆盖显示
                    self.maid_big_avatar.set_maid_expression(mood)
                else:
                    # Bug2: 引擎回落事件 —— 有 AI 标记就保持标记表情，没有才回基线
                    self.maid_big_avatar.set_maid_expression(
                        self._last_ai_expr or self._role_base_expr
                    )
            except Exception:
                logger.debug("静默降级：_on_maid_mood_changed 中忽略异常", exc_info=True)

    def _connect_role_bridge(self) -> None:
        """v1.4.2: 订阅角色生效广播（大形象切角色专属资产集 + 基线表情）。"""
        try:
            rb = getattr(self.app_ctx, "role_bridge", None)
            if rb is not None and hasattr(rb, "role_changed"):
                rb.role_changed.connect(self._on_role_changed)
        except Exception:
            logger.debug("静默降级：_connect_role_bridge 中忽略异常", exc_info=True)

    def _refresh_current_role(self, role_id: str = "") -> None:
        """读取当前角色的展示名与专属资产；资源缺失时保留默认形象回退链。"""
        try:
            from gui.pages.page_role import RoleManager
            manager = RoleManager()
            role = manager.get_role(role_id) if role_id else manager.default_role
            if role is not None:
                self._current_role_id = str(getattr(role, "id", "") or role_id)
                # 显示姓名而非人设标签；与聊天气泡复用同一三级兜底规则。
                from gui.widgets.message_bubble import resolve_speaker_name
                self._current_role_name = resolve_speaker_name(role) or "码铃"
            elif role_id:
                self._current_role_id = role_id
            from gui.maid_avatar import role_assets
            self._current_role_assets = role_assets(self._current_role_id)
        except Exception:
            logger.debug("读取当前角色信息失败", exc_info=True)

    def _apply_current_role_assets_to_big_avatar(self) -> None:
        """将当前角色专属资产应用到大形象；None 由控件回退默认码铃资产。"""
        if self.maid_big_avatar is None:
            return
        try:
            if hasattr(self.maid_big_avatar, "set_assets"):
                self.maid_big_avatar.set_assets(self._current_role_assets)
            self.maid_big_avatar.set_maid_expression(self._role_base_expr)
        except Exception:
            logger.debug("刷新侧栏大形象失败", exc_info=True)

    def _on_role_changed(self, role_id: str, avatar_path: str, base_expr: str) -> None:
        try:
            self._role_base_expr = base_expr or "normal"
            # 切角色 = 上下文重置，清除旧角色的 AI 标记记忆，回到该角色基线。
            self._last_ai_expr = None
            try:
                from gui.widgets.message_bubble import invalidate_default_speaker_name
                invalidate_default_speaker_name()
            except Exception:
                pass
            self._refresh_current_role(role_id)
            self.update_maid_chip()
            self._apply_current_role_assets_to_big_avatar()
        except Exception:
            logger.debug("静默降级：_on_role_changed 中忽略异常", exc_info=True)

    def _on_maid_clicked(self) -> None:
        self.maid_clicked.emit()
        # 兜底：外部未接管时直接回首页（MainWindow 侧已连接则二者幂等）
        page_manager = getattr(self.app_ctx, "page_manager", None)
        if page_manager is not None and hasattr(page_manager, "navigate"):
            try:
                page_manager.navigate("home")
            except Exception:
                logger.debug("静默降级：_on_maid_clicked 中忽略异常", exc_info=True)

    def _current_maid_state(self) -> str:
        """当前应展示态：bridge 活动态优先，否则 companion.mood，再回落 normal。"""
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        try:
            if bridge is not None and hasattr(bridge, "current_display"):
                return bridge.current_display() or "normal"
        except Exception:
            logger.debug("静默降级：_current_maid_state 中忽略异常", exc_info=True)
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None:
            try:
                return companion.mood or "normal"
            except Exception:
                logger.debug("静默降级：_current_maid_state 中忽略异常", exc_info=True)
        return "normal"

    def update_maid_chip(self) -> None:
        """刷新小形象：当前角色名、IntimacyTracker 阶段与角色专属表情资产。"""
        state = self._current_maid_state()
        companion = getattr(self.app_ctx, "companion", None)
        stage = "初识"
        tracker = getattr(self.app_ctx, "intimacy", None)
        try:
            level_name = getattr(tracker, "level_name", None)
            if callable(level_name):
                stage = str(level_name() or stage)
        except Exception:
            logger.debug("读取好感度阶段失败", exc_info=True)
        role_name = str(getattr(self, "_current_role_name", "") or "码铃")
        btn_text = f"{role_name} · {stage}"
        expr = _side_mood_to_expr(state) if _side_mood_to_expr is not None else "normal"

        icon = QIcon()
        if _SIDEBAR_MAID_OK:
            try:
                # 当前角色的专属资产优先；角色没有资源或该表情缺图时才回退默认形象。
                for assets in (getattr(self, "_current_role_assets", None), _sidebar_assets()):
                    if assets is None:
                        continue
                    pix = assets.rounded(expr, 28)
                    if pix is not None:
                        icon = QIcon(pix)
                        break
                if not icon.isNull():
                    self.maid_chip.setIcon(icon)
                    self.maid_chip.setIconSize(QSize(24, 24))
                    btn_text = " " + btn_text
            except Exception:
                logger.debug("静默降级：update_maid_chip 中忽略异常", exc_info=True)
        if icon.isNull():
            # 资产缺失：退化为铃铛字符头像（不空白、不崩）
            self.maid_chip.setIcon(QIcon())
            btn_text = f"🔔 {btn_text}"
        self.maid_chip.setText(btn_text)

        # tooltip：心情句 + IntimacyTracker 阶段 + 最近事件 + 操作提示（全部自然语言）
        tooltip = ""
        if _side_mood_tooltip is not None:
            try:
                tooltip = _side_mood_tooltip(companion, state)
            except Exception:
                tooltip = ""
        if not tooltip:
            tooltip = f"{role_name}在这里陪着主人"
        self.maid_chip.setToolTip(f"{tooltip}\n关系：{stage}\n点击回首页")

    def _apply_maid_chip_style(self) -> None:
        """主题色样式（theme_color，禁裸色）。

        v2.2.2 缺陷修复：基态底色原取 ``bg_card``，而**四套主题的侧栏根底本身也是
        ``bg_card``**（各肤感层 `SidebarWidget { background-color: ${bg_card}; }`）
        ⇒ 二者同色 Δ=0，等于压根没画底色。改取 ``bg_light``：4 浅 + 4 深共 8 组实测
        与侧栏底 ``bg_card`` 均有可见差（8/8 不再 Δ=0，Δ 通道 14~31：
        浅色档 21 / 17 / 30 / 31，深色档 15 / 14 / 30 / 18 ⇒ 浅色 ≥ 17、深色 ≥ 14；见
        `_probe/maid_chip_probe.py`）。

        悬停态原用 ``bg_light``，与本轮基态撞色，故改取 ``surface_muted`` ——
        与侧栏同排的 ``#sidebarModelBtn:hover`` 用的是同一令牌，观感一致；
        字色仍为 ``text``（8 组实测 字/底 ≥ 11.5、字/悬停底 ≥ 11.9 ——
        「≥ 10.9」是早一轮的读数，未随重测更新）。

        本函数是**运行期动态取色重刷**的写法：``_on_sidebar_theme_changed`` 在
        ThemeEngine.theme_changed 上调用它（见 `_connect_maid_companion`），
        故换肤后会重取色，本轮改动随之生效。
        """
        border = theme_color(self.app_ctx, "divider", "#F0DAE0")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        muted = theme_color(self.app_ctx, "surface_muted", "#FFF7FA")
        self.maid_chip.setStyleSheet(
            f"QPushButton#sidebarMaidChip {{"
            f"  background: {bg_light}; border: 1px solid {border};"
            f"  border-radius: 12px; padding: 2px 8px;"
            f"  text-align: left; color: {text}; font-size: 12px;"
            f"}}"
            # hover 底色 surface_muted 同为淡底，字色保持 text
            # （原注：字落 bg_light 实底时用 accent 仅 2.783/1.931/5.317/2.814，
            #  三套浅色 <4.5 → 故一律用 text；本轮沿用该结论）。
            f"QPushButton#sidebarMaidChip:hover {{"
            f"  background: {muted}; border-color: {accent}; color: {text};"
            f"}}"
        )

    def update_model_status(self) -> None:
        """刷新「模型状态」按钮：provider 短名 + 脱敏状态 + 状态点颜色（B9）。

        缺 Key/未配置 → 状态点黄色引导；配置就绪 → 绿色。
        """
        try:
            summary = api_status_summary(getattr(self.app_ctx, "cfg", None))
        except Exception:
            summary = None
        if not summary:
            self.model_btn.setText("模型 · 未配置")
            self.model_btn.setToolTip("模型配置：未配置（点击直达设置）")
            return

        if summary["configured"]:
            label = f"模型 · {summary['provider_short']}"
        else:
            label = "模型 · 未配置"
        self.model_btn.setText(label)
        lines = [
            f"当前厂商：{summary['provider_label']}",
            f"模型：{summary['model'] or '—'}",
            f"Key：{summary['masked_key']}",
            f"状态：{summary['state_text']}",
        ]
        if summary.get("hint"):
            lines.append(summary["hint"])
        lines.append("点击直达「模型与接口」配置")
        self.model_btn.setToolTip("\n".join(lines))

        # 状态点颜色（theme_color 取色，禁裸值）
        color_key = "state_ok" if summary["ok"] else "state_warn"
        dot_color = theme_color(self.app_ctx, color_key, "#E0A02E" if not summary["ok"] else "#3FBF7F")
        self.model_dot.setStyleSheet(
            f"QLabel#sidebarModelDot {{ background-color: {dot_color}; border-radius: 4px; }}"
        )

    def set_current_page(self, key: str) -> None:
        """从外部设置当前选中项（不触发信号风暴）。"""
        self.list_widget.currentRowChanged.disconnect(self._on_row_changed)
        try:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item and item.data(Qt.UserRole) == key:
                    self.list_widget.setCurrentRow(i)
                    break
            self._refresh_nav_icons()
        finally:
            self.list_widget.currentRowChanged.connect(self._on_row_changed)
