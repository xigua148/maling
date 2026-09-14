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
)
from gui.utils import theme_color
from core import api_status_summary

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

    NAV_ITEMS = [
        ("chat", "聊天", "\U0001F4AC"),   # 聊天主屏（默认首页位，v1.2 UI 大气化）
        ("home", "首页", "\u2302"),
        ("memories", "回忆", "\u2728"),   # v1.3(P2-3): 高光回忆册
        ("memory_book", "记忆中心", "\U0001F4D4"),  # v1.6(P0-1): 透明记忆中心
        ("project", "项目", None),   # 占位，在 _init_ui 中初始化
        ("file", "文件", "\u270E"),
        ("plan", "计划", "\u2630"),
        ("agent", "角色", "\u263A"),
        ("tools", "工具", "\u2699"),
        ("settings", "设置", "\u2691"),
    ]

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._maid_connected = False
        self._role_base_expr = "normal"  # v1.4.2: 角色基线表情
        # Bug2 修复：AI 自选表情的"保持"语义 —— 心情引擎回落事件（如 idle 回 normal）
        # 不应把 AI 标记的表情打回基线；记住最近一次 AI 标记，回落时优先沿用。
        self._last_ai_expr: Optional[str] = None
        self._init_ui()
        # v1.2(A-11): 订阅 mood_changed（心情换表情）+ theme_changed（换肤刷新）
        self._connect_maid_companion()
        # v1.4.2: 订阅角色生效 → 左下角大形象切角色专属资产集
        self._connect_role_bridge()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        self.list_widget = QListWidget()
        self.list_widget.setFrameShape(QListWidget.NoFrame)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setFocusPolicy(Qt.NoFocus)
        self.list_widget.setCursor(Qt.PointingHandCursor)

        # 延迟初始化 folder 图标（避免模块导入时未初始化 QApplication 导致崩溃）
        folder_icon = QIcon.fromTheme("folder")
        if folder_icon.isNull():
            folder_icon = "\U0001F4C1"

        for key, label, icon in self.NAV_ITEMS:
            if icon is None:
                icon = folder_icon
            if isinstance(icon, str):
                item = QListWidgetItem(f"{icon}  {label}")
            else:
                item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, key)
            self.list_widget.addItem(item)

        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget)
        layout.addStretch()

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

        # v1.2(A-11)(B5): 码铃形象入口行 —— 迷你码铃头像(随心情) + 关系称谓文本。
        # 位于模型状态行之下、帮助/关于之上；u1 的 B9 行原样保留、二者共存。
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

        self.help_btn = QPushButton("\u2753 帮助")
        self.help_btn.setObjectName("sidebarBottomBtn")
        self.help_btn.setCursor(Qt.PointingHandCursor)
        self.help_btn.setFixedHeight(32)
        self.help_btn.clicked.connect(self._on_help_clicked)
        bottom_layout.addWidget(self.help_btn, 1)

        self.about_btn = QPushButton("\u2139 关于")
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

    def _on_row_changed(self, row: int) -> None:
        item = self.list_widget.item(row)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if key:
            self.item_clicked.emit(key)

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
            pass
        try:
            engine = getattr(self.app_ctx, "theme_engine", None)
            if engine is not None and hasattr(engine, "theme_changed") \
                    and hasattr(engine.theme_changed, "connect"):
                engine.theme_changed.connect(lambda _n: self._apply_maid_chip_style())
        except Exception:
            pass
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
                pass

    def _connect_role_bridge(self) -> None:
        """v1.4.2: 订阅角色生效广播（大形象切角色专属资产集 + 基线表情）。"""
        try:
            rb = getattr(self.app_ctx, "role_bridge", None)
            if rb is not None and hasattr(rb, "role_changed"):
                rb.role_changed.connect(self._on_role_changed)
        except Exception:
            pass

    def _on_role_changed(self, role_id: str, avatar_path: str, base_expr: str) -> None:
        try:
            self._role_base_expr = base_expr or "normal"
            # Bug2: 切角色 = 上下文重置，清除旧角色的 AI 标记记忆，回到该角色基线
            self._last_ai_expr = None
            if self.maid_big_avatar is None:
                return
            from gui.maid_avatar import role_assets
            assets = role_assets(role_id)  # None → set_assets 回落码铃本体
            if hasattr(self.maid_big_avatar, "set_assets"):
                self.maid_big_avatar.set_assets(assets)
            self.maid_big_avatar.set_maid_expression(self._role_base_expr)
        except Exception:
            pass

    def _on_maid_clicked(self) -> None:
        self.maid_clicked.emit()
        # 兜底：外部未接管时直接回首页（MainWindow 侧已连接则二者幂等）
        page_manager = getattr(self.app_ctx, "page_manager", None)
        if page_manager is not None and hasattr(page_manager, "navigate"):
            try:
                page_manager.navigate("home")
            except Exception:
                pass

    def _current_maid_state(self) -> str:
        """当前应展示态：bridge 活动态优先，否则 companion.mood，再回落 normal。"""
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        try:
            if bridge is not None and hasattr(bridge, "current_display"):
                return bridge.current_display() or "normal"
        except Exception:
            pass
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None:
            try:
                return companion.mood or "normal"
            except Exception:
                pass
        return "normal"

    def update_maid_chip(self) -> None:
        """刷新迷你码铃：表情头像 + 关系称谓文本 + 心情 tooltip（无数值红线）。"""
        state = self._current_maid_state()
        companion = getattr(self.app_ctx, "companion", None)
        stage = ""
        if companion is not None:
            try:
                stage = companion.relation_stage_name()
            except Exception:
                stage = ""
        btn_text = f"码铃 · {stage}" if stage else "码铃"
        expr = _side_mood_to_expr(state) if _side_mood_to_expr is not None else "normal"

        icon = QIcon()
        if _SIDEBAR_MAID_OK:
            try:
                assets = _sidebar_assets()
                if assets is not None:
                    pix = assets.rounded(expr, 28)
                    if pix is not None:
                        icon = QIcon(pix)
                        self.maid_chip.setIcon(icon)
                        self.maid_chip.setIconSize(QSize(24, 24))
                        if not btn_text.startswith(" "):
                            btn_text = " " + btn_text
            except Exception:
                pass
        if icon.isNull():
            # 资产缺失：退化为铃铛字符头像（不空白、不崩）
            self.maid_chip.setIcon(QIcon())
            btn_text = f"🔔 {btn_text}"
        self.maid_chip.setText(btn_text)

        # tooltip：心情句 + 关系称谓 + 最近事件 + 操作提示（全部自然语言）
        tooltip = ""
        if _side_mood_tooltip is not None:
            try:
                tooltip = _side_mood_tooltip(companion, state)
            except Exception:
                tooltip = ""
        if not tooltip:
            tooltip = "码铃在这里陪着主人"
        self.maid_chip.setToolTip(f"{tooltip}\n点击回首页")

    def _apply_maid_chip_style(self) -> None:
        """主题色样式（theme_color，禁裸色）。"""
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        border = theme_color(self.app_ctx, "divider", "#F0DAE0")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        bg_light = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        self.maid_chip.setStyleSheet(
            f"QPushButton#sidebarMaidChip {{"
            f"  background: {bg}; border: 1px solid {border};"
            f"  border-radius: 12px; padding: 2px 8px;"
            f"  text-align: left; color: {text}; font-size: 12px;"
            f"}}"
            f"QPushButton#sidebarMaidChip:hover {{"
            f"  background: {bg_light}; border-color: {accent}; color: {accent};"
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
        finally:
            self.list_widget.currentRowChanged.connect(self._on_row_changed)
