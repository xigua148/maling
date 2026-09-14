"""首页 · 房间式（B2/A-7 改造）—— 主形象常驻 + 问候/每日动态 + 快捷入口 + 关系称谓 + 徽章占位。

v1.2 改造要点（design-v12 §3.9 暴露面红线 + A-6/A-7）：
  - **不渲染任何数值型养成元素**：无心情条/好感分数/经验条/Lv/打卡倒计时/「连续 N 天」；
    心情只经表情（MaidAvatar.set_maid_expression）与文案表达；关系成长只用文本称谓
    （companion.relation_stage_name()：初识/熟悉/亲近/信赖）。
  - 问候 + 每日动态卡：GreetingEngine 时段问候 + companion 心情/最近事件语境（模板先行，
    无 LLM；措辞正向，无数值义务感词）。
  - 主形象复用 gui/maid_avatar.py MaidAvatar（缺 PNG 时显示中性铃铛兜底，不画程序假脸；美术插画就位自动启用）；
    订阅 companion_bridge.mood_changed 随心情换表情。
  - 徽章墙展示位预留（A-12 接入，本批只放空容器/已解锁名称软展示）。
  - 保留既有会话/模式卡功能入口（不删功能），用组件替换 + 布局重组实现，降低回归。

取色一律 theme_color()，禁止裸色值。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, List

from gui import icons
from gui import elevation  # v2.1(UI-P2): 投影层次试点（主题 shadow 变量 → QGraphicsDropShadowEffect）
from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGridLayout, QFrame, Qt, QFont, Signal, QListWidget,
    QListWidgetItem, QScrollArea, QSizePolicy,
)
from gui.utils import theme_color, brand_persona_self

logger = logging.getLogger("maid_coder.gui")

# v2.1(V21-12/D-V21-06): 首页图标位统一 —— 只记「图标名 + 尺寸 + theme_color 取色」，
# 字体不可用时回落原 emoji（不空白、不崩）。
_ICON_SIZE_CARD = 20   # 状态卡 / 模式卡图标
_ICON_SIZE_QUICK = 16  # 快捷入口按钮图标


def _vector_icon(app_ctx, name: str, size: int, color: Optional[str]):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落 emoji）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


def _apply_button_icon(btn: QPushButton, app_ctx, name: str, clean_text: str,
                       fallback_text: str, size: int = _ICON_SIZE_QUICK) -> None:
    """按钮挂矢量图标（取色 text）并去掉文案 emoji；不可用回落原 emoji 文案。"""
    ic = _vector_icon(app_ctx, name, size, theme_color(app_ctx, "text", "#5D4037"))
    if ic is not None:
        btn.setIcon(ic)
        btn.setText(clean_text)
    else:
        btn.setText(fallback_text)

try:
    from gui.maid_avatar import MaidAvatar, QT_OK as _MAID_QT_OK
except Exception:  # 极端情况下形象模块不可用也允许降级（防御）
    MaidAvatar = None  # type: ignore
    _MAID_QT_OK = False

# 快捷入口定义：(key, 标题, 图标名, 回落 emoji, tooltip, handler_key)
# v2.1(V21-12): 图标名走 icons.icon（字体不可用时回落 emoji）
QUICK_ACTIONS = [
    ("chat", "开始聊天", "chat", "💬", "新开一段对话，和码铃说说话", "start_chat"),
    ("agent", "Agent", "agent", "🤖", "切换 Agent 模式：让码铃带工具干活", "agent"),
    ("tools", "工具箱", "settings", "🧰", "打开工具箱", "tools"),
    ("plan", "计划", "list", "📋", "打开计划编辑器", "plan"),
    # v1.5.0: 知识库 / 待办 GUI 入口（审计 #C1/#C2 空壳销项）
    ("kb", "知识库", "menu_book", "📚", "索引本地文档并检索（与 CLI /kb 同一份索引）", "kb"),
    ("todo", "待办", "todo", "📝", "查看/添加/勾选待办事项（与 CLI /todo 同一份存档）", "todo"),
    # v1.4(A3): 番茄钟「她陪你专注」（D-V14-04 首页快捷入口）
    ("pomodoro", "专注", "time", "🍅", "25 分钟番茄钟，她陪你专注", "pomodoro"),
    ("save", "保存会话", "save", "💾", "保存当前会话", "save"),
    ("load", "加载会话", "folder", "📂", "加载已有会话", "load"),
    ("help", "帮助", "help", "❓", "查看帮助", "help"),
    ("about", "关于", "notification", "🔔", "关于码铃", "about"),
]


class ToggleCard(QFrame):
    """模式切换卡片 —— 可点击切换开关状态。"""

    toggled = Signal(bool)  # (new_state)

    def __init__(
        self,
        title: str,
        description: str,
        icon: str,
        initial_state: bool = False,
        parent: Optional[QWidget] = None,
        icon_name: str = "",
        app_ctx=None,
    ):
        super().__init__(parent)
        self._state = initial_state
        self._title = title
        self._description = description
        self._icon = icon
        self._icon_name = icon_name
        self._app_ctx = app_ctx
        self.setObjectName("toggleCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._init_ui()
        self._update_style()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        top = QHBoxLayout()
        icon_label = QLabel(self._icon)
        icon_label.setObjectName("toggleCardIcon")
        ic = (_vector_icon(self._app_ctx, self._icon_name, _ICON_SIZE_CARD,
                           theme_color(self._app_ctx, "text", "#5D4037"))
              if self._icon_name else None)
        if ic is not None:
            icon_label.setText("")
            icon_label.setPixmap(ic.pixmap(_ICON_SIZE_CARD, _ICON_SIZE_CARD))
            icon_label.setFixedSize(_ICON_SIZE_CARD, _ICON_SIZE_CARD)
        else:
            font = QFont()
            icon_label.setFont(font)
        top.addWidget(icon_label)
        top.addStretch()
        self.state_label = QLabel("开" if self._state else "关")
        self.state_label.setObjectName("toggleCardState")
        top.addWidget(self.state_label)
        layout.addLayout(top)

        title_label = QLabel(self._title)
        title_label.setObjectName("toggleCardTitle")
        font = QFont()
        font.setBold(True)
        title_label.setFont(font)
        layout.addWidget(title_label)

        desc_label = QLabel(self._description)
        desc_label.setObjectName("toggleCardDesc")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)
        layout.addStretch()

    def _update_style(self) -> None:
        self.state_label.setText("开" if self._state else "关")
        if self._state:
            self.setObjectName("toggleCardActive")
        else:
            self.setObjectName("toggleCard")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_state(self, state: bool) -> None:
        self._state = state
        self._update_style()

    def toggle(self) -> bool:
        self._state = not self._state
        self._update_style()
        self.toggled.emit(self._state)
        return self._state

    def is_on(self) -> bool:
        return self._state

    def mousePressEvent(self, event) -> None:
        self.toggle()
        super().mousePressEvent(event)


class StatusCard(QFrame):
    """状态概览卡片 —— 展示单项非养成状态（Token/网络/项目根）。"""

    def __init__(
        self,
        title: str,
        value: str,
        icon: str,
        parent: Optional[QWidget] = None,
        icon_name: str = "",
        app_ctx=None,
    ):
        super().__init__(parent)
        self.setObjectName("statusCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._init_ui(title, value, icon, icon_name, app_ctx)

    def _init_ui(self, title: str, value: str, icon: str,
                 icon_name: str = "", app_ctx=None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        top = QHBoxLayout()
        ic = (_vector_icon(app_ctx, icon_name, _ICON_SIZE_CARD,
                           theme_color(app_ctx, "text", "#5D4037"))
              if icon_name else None)
        if ic is not None:
            icon_label = QLabel()
            icon_label.setPixmap(ic.pixmap(_ICON_SIZE_CARD, _ICON_SIZE_CARD))
            icon_label.setFixedSize(_ICON_SIZE_CARD, _ICON_SIZE_CARD)
            icon_label.setObjectName("statusCardIcon")
        else:
            icon_label = QLabel(icon)
            icon_label.setObjectName("statusCardIcon")
            icon_font = QFont()
            icon_label.setFont(icon_font)
        top.addWidget(icon_label)
        top.addStretch()
        layout.addLayout(top)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("statusCardValue")
        val_font = QFont()
        val_font.setBold(True)
        self.value_label.setFont(val_font)
        layout.addWidget(self.value_label)

        title_label = QLabel(title)
        title_label.setObjectName("statusCardTitle")
        layout.addWidget(title_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


# v1.8(V18-13/D-V18-07): 场景 chip（可点按 QLabel 子类 —— PyQt 虚方法派发
# 走类级定义，实例属性赋值 mousePressEvent 不可靠；on_clicked 由宿主注入）
class _SceneChip(QLabel):
    """当前场景状态 chip：显示 scene_chip_text 文案，点击回调宿主循环切换。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.on_clicked = None
        self.setCursor(Qt.PointingHandCursor)

    def trigger_click(self) -> None:
        """公共点击入口（测试可调用，绕开 mousePressEvent(None) 崩溃风险）。"""
        cb = getattr(self, "on_clicked", None)
        if callable(cb):
            try:
                cb()
            except Exception:
                logger.debug("静默降级：trigger_click 中忽略异常", exc_info=True)

    def mousePressEvent(self, event) -> None:
        self.trigger_click()
        if event is not None:
            super().mousePressEvent(event)


class PageHome(QWidget):
    """首页 · 房间式页面（v1.2 A-6/A-7）。"""

    session_selected = Signal(str)

    def __init__(self, app_context, title: str = "首页", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self.setObjectName("pageHome")
        self._companion_connected = False
        self._role_base_expr = "normal"  # v1.4.2: 角色基线表情
        # Bug2 修复：AI 自选表情的"保持"语义 —— 心情引擎回落事件不应把 AI 标记
        # 的表情打回基线；记住最近一次 AI 标记，回落时优先沿用。
        self._last_ai_expr: Optional[str] = None
        self._init_ui()
        self._sync_from_session()
        # v1.9(V19-16): 主题切换 → D 风格口吻文案即时刷新
        self._connect_theme_brand()
        # v1.2(B9): 启动即刷新首页模型入口当前状态
        try:
            if getattr(self, "model_entry_btn", None) is not None:
                self._refresh_model_entry()
        except Exception:
            logger.debug("静默降级：__init__ 中忽略异常", exc_info=True)

    # ==================================================================
    # 取色辅助（§3.9：一律 theme_color，禁止裸色值）
    # ==================================================================
    def _tc(self, key: str, fallback: str) -> str:
        return theme_color(self.app_ctx, key, fallback)

    # ==================================================================
    # 布局构建
    # ==================================================================
    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页面整体可滚动（房间式内容较长，避免小窗溢出）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        root.addWidget(scroll)

        container = QWidget()
        container.setStyleSheet(f"background: {self._tc('bg', '#FFF5F5')};")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(24, 20, 24, 24)
        self._layout.setSpacing(14)
        scroll.setWidget(container)

        self._build_header()
        self._build_room_card()
        self._build_weekly_review_card()
        self._build_quick_actions()
        self._build_status_section()
        self._build_mode_section()
        self._layout.addStretch()

    # -- 顶部标题行 --
    def _build_header(self) -> None:
        self.welcome_label = QLabel("欢迎回来，主人~")
        self.welcome_label.setObjectName("homeWelcome")
        wf = QFont()
        wf.setBold(True)
        self.welcome_label.setFont(wf)
        self.welcome_label.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        self._layout.addWidget(self.welcome_label)
        self.header_hint = QLabel("")
        self.header_hint.setStyleSheet(f"color: {self._tc('text_secondary', '#888888')}; font-size: 12px;")
        self._layout.addWidget(self.header_hint)

    # -- 房间形象 + 每日动态卡（A-6） --
    def _build_room_card(self) -> None:
        card = QFrame()
        card.setObjectName("roomCard")
        card.setStyleSheet(
            f"QFrame#roomCard {{ background: {self._tc('bg_card', '#FFFFFF')};"
            f" border: 1px solid {self._tc('border', '#FFE4E1')};"
            f" border-radius: {self._tc('radius_lg', '16px')}; }}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(18)

        # 左：主形象（缺真图时中性铃铛兜底，UI 永不空白）
        self.avatar = None
        try:
            if MaidAvatar is not None and _MAID_QT_OK:
                self.avatar = MaidAvatar(size=150, expression="normal")
                self.avatar.setMinimumSize(110, 110)
                self.avatar.setMaximumSize(180, 180)
        except Exception:
            self.avatar = None
        if self.avatar is None:
            # 兜底：形象不可用时显示铃铛图标（仍不空白、不崩溃）
            # v2.1(V21-12): 有矢量图标则用图标字体渲染（高 DPI 更清晰），否则回落 emoji
            self.avatar = QLabel()
            self.avatar.setObjectName("homeAvatarFallback")
            self.avatar.setAlignment(Qt.AlignCenter)
            fallback_px = 64
            ic = _vector_icon(self.app_ctx, "notification", fallback_px,
                              theme_color(self.app_ctx, "text", "#5D4037"))
            if ic is not None:
                self.avatar.setPixmap(ic.pixmap(fallback_px, fallback_px))
            else:
                self.avatar.setText("🔔")
                f = QFont()
                self.avatar.setFont(f)
        row.addWidget(self.avatar, 0, Qt.AlignVCenter)

        # 右：问候 / 动态文案列
        col = QVBoxLayout()
        col.setSpacing(6)

        self.greeting_label = QLabel("码铃已准备好为您效劳")
        self.greeting_label.setObjectName("homeGreeting")
        gf = QFont()
        gf.setBold(True)
        self.greeting_label.setFont(gf)
        self.greeting_label.setWordWrap(True)
        self.greeting_label.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        col.addWidget(self.greeting_label)

        # 每日动态（mood 语境 + 最近事件，正向无数值）
        self.moment_label = QLabel("")
        self.moment_label.setWordWrap(True)
        self.moment_label.setStyleSheet(f"color: {self._tc('text_secondary', '#757575')}; font-size: 12px;")
        col.addWidget(self.moment_label)

        # 关系称谓 chip（文本，无数值）
        self.stage_chip = QLabel("")
        self.stage_chip.setStyleSheet(
            f"color: {self._tc('primary_dark', '#FF69B4')}; background: {self._tc('bg_light', '#FFF0F3')};"
            " border-radius: 10px; padding: 2px 10px; font-size: 11px;"
        )
        col.addWidget(self.stage_chip, 0, Qt.AlignLeft)

        # v1.8(V18-13/D-V18-07): 场景 chip（当前场景状态 + 点按循环切换；
        # 手动切换当日有效次日回落 Q-D4；scene_auto 关闭时隐藏）
        self.scene_chip = _SceneChip()
        self.scene_chip.setStyleSheet(
            f"color: {self._tc('text_secondary', '#8D6E63')};"
            " border: 1px solid rgba(141, 110, 99, 0.35); border-radius: 10px;"
            " padding: 2px 10px; font-size: 11px;"
        )
        self.scene_chip.on_clicked = self._on_scene_chip_clicked
        col.addWidget(self.scene_chip, 0, Qt.AlignLeft)

        # 徽章墙占位（A-12 接入；本批软展示已解锁成就名，无数值）
        self.badge_hint = QLabel("")
        self.badge_hint.setWordWrap(True)
        self.badge_hint.setStyleSheet(f"color: {self._tc('text_secondary', '#9E9E9E')}; font-size: 11px;")
        col.addWidget(self.badge_hint)

        col.addStretch()
        row.addLayout(col, 1)
        self.room_card = card
        self._layout.addWidget(card)
        # v2.1(UI-P2): 投影层次试点 —— 首页主卡（level 1）
        # 取色走主题 shadow 变量；主题缺失/非法时 elevation 内部静默跳过。
        elevation.apply_card_shadow(card, level=1, app_ctx=self.app_ctx)

    # -- 本周回顾卡片（v1.6 P1-3 / D-V16-10） --
    def _build_weekly_review_card(self) -> None:
        """「本周回顾」卡片：仅当本周已有回顾记录才渲染（无空卡打扰）。

        R-A：档位词措辞、无计数无「第 N 周」无对比；R-C：无通知，只静候翻阅。
        """
        card = QFrame()
        card.setObjectName("weeklyCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        ic = _vector_icon(self.app_ctx, "calendar", _ICON_SIZE_CARD,
                          theme_color(self.app_ctx, "text", "#5D4037"))
        if ic is not None:
            icon_lab = QLabel()
            icon_lab.setPixmap(ic.pixmap(_ICON_SIZE_CARD, _ICON_SIZE_CARD))
            icon_lab.setFixedSize(_ICON_SIZE_CARD, _ICON_SIZE_CARD)
            title_row.addWidget(icon_lab)
            title = QLabel("本周回顾")
        else:
            title = QLabel("🌿 本周回顾")
        tf = QFont()
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        title_row.addWidget(title)
        title_row.addStretch()
        lay.addLayout(title_row)

        self.weekly_body = QLabel("")
        self.weekly_body.setWordWrap(True)
        self.weekly_body.setTextFormat(Qt.RichText)
        self.weekly_body.setStyleSheet(
            f"color: {self._tc('text_secondary', '#757575')}; font-size: 12px;")
        lay.addWidget(self.weekly_body)

        self.weekly_card = card
        card.setVisible(False)  # 无本周记录 → 整卡不出现
        self._layout.addWidget(card)

    def _weekly_mgr(self):
        """app 级 WeeklyReviewManager 单例（main 装配时挂 app_ctx.weekly）。"""
        mgr = getattr(self.app_ctx, "weekly", None)
        if mgr is not None:
            return mgr
        try:
            from weekly import WeeklyReviewManager
            mgr = WeeklyReviewManager()
            self.app_ctx.weekly = mgr
        except Exception as exc:
            logger.debug("WeeklyReviewManager 懒装配失败（卡片隐藏）: %s", exc)
            mgr = None
        return mgr

    def refresh_weekly_review(self) -> None:
        """按本周 week_start 取回顾；有则渲染、无则整卡隐藏。"""
        card = getattr(self, "weekly_card", None)
        if card is None:
            return
        mgr = self._weekly_mgr()
        review = None
        if mgr is not None:
            try:
                from weekly import week_start_of
                review = mgr.get_by_week(week_start_of(datetime.now()))
            except Exception as exc:
                logger.debug("读取本周回顾失败（卡片隐藏）: %s", exc)
                review = None
        if not review:
            card.setVisible(False)
            return
        sk = review.get("skeleton") or {}
        lines = []
        pace = str(sk.get("pace", "")).strip()
        if pace:
            lines.append(f"这是{pace}。")
        stage = str(sk.get("relation_stage", "")).strip()
        if stage:
            lines.append(f"我们正处在「{stage}」的时光里。")
        new_topics = [str(s) for s in (sk.get("new_topics") or []) if str(s).strip()]
        done_topics = [str(s) for s in (sk.get("done_topics") or []) if str(s).strip()]
        if done_topics:
            lines.append("完成的事：" + "、".join(done_topics) + "，干得漂亮~")
        if new_topics:
            lines.append("最近聊起：" + "、".join(new_topics))
        mood_note = str(sk.get("mood_note", "")).strip()
        if mood_note:
            lines.append(mood_note)
        for h in (sk.get("highlights") or []):
            text = str(h.get("text", "")).strip()
            if text:
                lines.append(f"{icons.text_glyph('auto_awesome', '✨')} 「{text}」")
        lines.append("想翻翻以前的回忆，去「记忆中心 → 往期回顾」看看吧~")
        self.weekly_body.setText("<br>".join(lines))
        card.setVisible(True)

    # -- 快捷入口区（B2：保留功能入口，重组为导航/动作按钮） --
    def _build_quick_actions(self) -> None:
        title = QLabel("快捷入口")
        title.setObjectName("homeSectionTitle")
        tf = QFont()
        tf.setBold(True)
        title.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        self._layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(10)
        for idx, (key, text, icon_name, emoji, tip, handler_key) in enumerate(QUICK_ACTIONS):
            btn = QPushButton(f"{emoji}  {text}")
            btn.setObjectName("quickBtn")
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            _apply_button_icon(btn, self.app_ctx, icon_name, text, f"{emoji}  {text}")
            handler = self._resolve_quick_handler(handler_key)
            if handler is not None:
                btn.clicked.connect(handler)
            grid.addWidget(btn, idx // 4, idx % 4)
        # 占满最后一行空白，保持按钮等宽（列数固定 4；按 4 对齐补齐尾行）
        cols = 4
        pad_to = ((grid.count() + cols - 1) // cols) * cols
        for c in range(grid.count(), pad_to):
            grid.addWidget(QWidget(), c // cols, c % cols)
        self._layout.addLayout(grid)

        # v1.2(B9): 模型配置直达入口 —— 只加不改（A-7 首页大改完成后可由 A 线统一并入）
        entry = QHBoxLayout()
        entry.setSpacing(10)
        self.model_entry_btn = QPushButton("\u2699 模型设置")
        self.model_entry_btn.setObjectName("homeModelEntry")
        self.model_entry_btn.setCursor(Qt.PointingHandCursor)
        self.model_entry_btn.setMinimumHeight(38)
        _apply_button_icon(self.model_entry_btn, self.app_ctx, "settings",
                           "模型设置", "\u2699 模型设置")
        self.model_entry_btn.clicked.connect(self._on_open_model_settings)
        entry.addWidget(self.model_entry_btn, 1)
        self.model_entry_hint = QLabel("")
        self.model_entry_hint.setObjectName("homeModelEntryDesc")
        entry.addWidget(self.model_entry_hint)
        self._layout.addLayout(entry)

    def _resolve_quick_handler(self, key: str):
        return {
            "start_chat": self._on_start_chat,
            "agent": self._on_toggle_agent_from_home,
            "tools": lambda: self._navigate("tools"),
            "plan": lambda: self._navigate("plan"),
            "kb": self._on_open_kb,        # v1.5.0
            "todo": self._on_open_todo,    # v1.5.0
            "pomodoro": self._on_pomodoro,  # v1.4(A3)
            "save": self._on_save_session,
            "load": self._on_load_session,
            "help": lambda: self._navigate("help"),
            "about": lambda: self._navigate("about"),
        }.get(key)

    def _on_open_kb(self) -> None:
        """v1.5.0: 打开知识库对话框（审计 #C1 GUI 入口销项）。"""
        try:
            from gui.widgets.kb_dialog import KnowledgeBaseDialog
            dlg = KnowledgeBaseDialog(self.app_ctx, parent=self)
            dlg.setWindowModality(Qt.NonModal)
            dlg.show()
        except Exception as exc:
            logger.warning("知识库对话框打开失败: %s", exc)

    def _on_open_todo(self) -> None:
        """v1.5.0: 打开待办对话框（审计 #C2 GUI 入口销项）。"""
        try:
            from gui.widgets.todo_dialog import TodoDialog
            dlg = TodoDialog(self.app_ctx, parent=self)
            dlg.setWindowModality(Qt.NonModal)
            dlg.show()
        except Exception as exc:
            logger.warning("待办对话框打开失败: %s", exc)

    def _on_pomodoro(self) -> None:
        """v1.4(A3): 打开/聚焦番茄钟浮窗（controller 单例懒建；失败不阻断）。"""
        try:
            from gui.pomodoro import open_pomodoro
            open_pomodoro(self.app_ctx)
        except Exception as exc:
            logger.warning("番茄钟打开失败: %s", exc)

    # -- 状态概览（Token/网络/项目根 —— 非养成数值，保留） --
    def _build_status_section(self) -> None:
        title = QLabel("工作状态")
        title.setObjectName("homeSectionTitle")
        tf = QFont()
        tf.setBold(True)
        title.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        self._layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.token_card = StatusCard("Token 用量", "--", "📊",
                                     icon_name="chart", app_ctx=self.app_ctx)
        self.network_card = StatusCard("网络状态", "检查中...", "🌐",
                                       icon_name="wifi", app_ctx=self.app_ctx)
        self.project_card = StatusCard("项目根目录", "未设置", "📁",
                                       icon_name="folder", app_ctx=self.app_ctx)
        for c in (self.token_card, self.network_card, self.project_card):
            row.addWidget(c, 1)
            # v2.1(UI-P2): 投影层次试点 —— 三张状态卡（level 1）
            elevation.apply_card_shadow(c, level=1, app_ctx=self.app_ctx)
        self._layout.addLayout(row)

    # -- 模式切换卡（保留原功能入口，不删） --
    def _build_mode_section(self) -> None:
        title = QLabel("模式切换")
        title.setObjectName("homeSectionTitle")
        tf = QFont()
        tf.setBold(True)
        title.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        self._layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards: dict = {}
        card_defs = [
            ("deep", "深度思考", "更详细的推理过程", "🧠", False, "lightbulb"),
            ("coding", "编程模式", "优先输出代码", "💻", False, "terminal"),
            ("chat", "闲聊模式", "弱化编程，自然对话", "💬", False, "chat"),
            ("multi", "多模型", "启用多模型协作", "👥", False, "people"),
            ("stream", "流式输出", "实时显示 AI 回复", "📡", True, "wifi"),
        ]
        for i, (key, c_title, desc, icon, default, icon_name) in enumerate(card_defs):
            card = ToggleCard(c_title, desc, icon, default,
                              icon_name=icon_name, app_ctx=self.app_ctx)
            card.toggled.connect(lambda state, k=key: self._apply_mode_change(k, state))
            self.cards[key] = card
            row, col = divmod(i, 3)
            grid.addWidget(card, row, col)
        self._layout.addLayout(grid)

        # 最近会话（保留；若有需要可读 session_manager 数据）
        session_title = QLabel("最近会话")
        session_title.setFont(tf)
        session_title.setStyleSheet(f"color: {self._tc('text', '#5D4037')};")
        self._layout.addWidget(session_title)
        self.session_list = QListWidget()
        self.session_list.setObjectName("recentSessionList")
        self.session_list.setMaximumHeight(150)
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.session_list.itemClicked.connect(self._on_session_clicked)
        self._layout.addWidget(self.session_list)
        self._load_recent_sessions()

    # ==================================================================
    # companion 接线（心情 -> 表情；关系称谓）
    # ==================================================================
    def _connect_companion(self) -> None:
        """订阅 companion_bridge.mood_changed：心情态变化即换表情 + 刷新动态/称谓。"""
        if self._companion_connected:
            return
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None:
            return
        try:
            if hasattr(bridge, "mood_changed") and hasattr(bridge.mood_changed, "connect"):
                bridge.mood_changed.connect(self._on_companion_mood_changed)
                self._companion_connected = True
            # v1.4.2: 订阅角色生效 → 首页大形象切角色专属资产集
            rb = getattr(self.app_ctx, "role_bridge", None)
            if rb is not None and hasattr(rb, "role_changed"):
                rb.role_changed.connect(self._on_role_changed)
        except Exception:
            logger.debug("静默降级：_connect_companion 中忽略异常", exc_info=True)

    def _on_companion_mood_changed(self, mood: str, reason: str) -> None:
        """心情变化：更新主形象表情 + 每日动态文案（不渲染任何数值）。

        v1.4.2: 表情显示策略 —— AI 自选标记直接生效；活动态临时覆盖；
        Bug2: 其余回落事件优先保持 AI 标记表情，不再打回角色基线。
        """
        try:
            from companion import ACTIVITY_STATES
            if reason == "ai-markup" and mood:
                # Bug2: 记住最近一次 AI 标记表情，后续引擎回落事件保持它
                self._last_ai_expr = mood
                self._apply_mood_to_avatar(mood)
            elif mood in ACTIVITY_STATES:
                # 活动态（thinking/focus/surprised 等）临时覆盖显示
                self._apply_mood_to_avatar(mood)
            else:
                # Bug2: 引擎回落事件 —— 有 AI 标记就保持标记表情，没有才回基线
                self._apply_mood_to_avatar(
                    self._last_ai_expr or self._role_base_expr
                )
        except Exception:
            try:
                self._apply_mood_to_avatar(mood)
            except Exception:
                logger.debug("静默降级：_on_companion_mood_changed 中忽略异常", exc_info=True)
        self._refresh_dynamic_text()

    def _apply_mood_to_avatar(self, mood: str) -> None:
        avatar = getattr(self, "avatar", None)
        if avatar is not None and hasattr(avatar, "set_maid_expression"):
            avatar.set_maid_expression(mood)

    def _on_role_changed(self, role_id: str, avatar_path: str, base_expr: str) -> None:
        """v1.4.2: 角色生效 → 首页大形象切角色专属资产集 + 基线表情。"""
        try:
            self._role_base_expr = base_expr or "normal"
            # Bug2: 切角色 = 上下文重置，清除旧角色的 AI 标记记忆，回到该角色基线
            self._last_ai_expr = None
            from gui.maid_avatar import role_assets
            assets = role_assets(role_id)
            avatar = getattr(self, "avatar", None)
            if avatar is not None and hasattr(avatar, "set_assets"):
                avatar.set_assets(assets)  # None → 回落码铃本体
                avatar.set_maid_expression(self._role_base_expr)
        except Exception:
            logger.debug("静默降级：_on_role_changed 中忽略异常", exc_info=True)

    def _get_nickname(self) -> str:
        try:
            session = getattr(self.app_ctx, "session", None)
            if session is not None:
                memory_mgr = getattr(session, "memory_mgr", None)
                if memory_mgr is not None:
                    nick = memory_mgr.get_preference("nickname")
                    if nick:
                        return str(nick)
        except Exception:
            logger.debug("静默降级：_get_nickname 中忽略异常", exc_info=True)
        return "主人"

    # -- v1.9(V19-16/D-V19-14): 界面口吻文案（D 风格自称随当前角色） --
    def _refresh_welcome_label(self, nickname: Optional[str] = None) -> None:
        """欢迎语口吻：D 风格（ui_whale）用当前角色自称，其余保持原中性文案。"""
        label = getattr(self, "welcome_label", None)
        if label is None:
            return
        if nickname is None:
            nickname = self._get_nickname()
        self_ref = brand_persona_self(self.app_ctx)
        try:
            if self_ref:
                label.setText(f"{self_ref}在这里等你回来啦，{nickname}~")
            else:
                label.setText(f"欢迎回来，{nickname}~")
        except Exception:
            logger.debug("静默降级：_refresh_welcome_label 中忽略异常", exc_info=True)

    def _set_greeting_fallback(self, nickname: str) -> None:
        """GreetingEngine 不可用时的兜底问候：D 风格自称随人设，其余不变。"""
        self_ref = brand_persona_self(self.app_ctx)
        try:
            if self_ref:
                self.greeting_label.setText(f"{nickname}，{self_ref}在这里~")
            else:
                self.greeting_label.setText(f"{nickname}，码铃在这里~")
        except Exception:
            logger.debug("静默降级：_set_greeting_fallback 中忽略异常", exc_info=True)

    def _connect_theme_brand(self) -> None:
        """v1.9(V19-16): 主题切换 → D 风格口吻文案即时刷新（只刷文本，不动布局/随机问候）。"""
        engine = getattr(self.app_ctx, "theme_engine", None)
        if engine is None or not hasattr(engine, "theme_changed"):
            return
        try:
            engine.theme_changed.connect(lambda _n: self._refresh_welcome_label())
        except Exception:
            logger.debug("静默降级：_connect_theme_brand 中忽略异常", exc_info=True)

    def _refresh_companion_panel(self) -> None:
        """刷新主形象表情 + 问候 + 每日动态 + 称谓 + 徽章占位（A-6 组装）。"""
        companion = getattr(self.app_ctx, "companion", None)
        nickname = self._get_nickname()
        # v1.9(V19-16): 欢迎语口吻 —— D 风格走当前角色自称
        self._refresh_welcome_label(nickname)

        intimacy_level = 0
        mood = None
        if companion is not None:
            try:
                intimacy_level = companion.intimacy_level()
                mood = companion.mood
            except Exception:
                logger.debug("静默降级：_refresh_companion_panel 中忽略异常", exc_info=True)

        # 问候（GreetingEngine 时段短问候；纯模板，无数值）
        try:
            from greeting import GreetingEngine
            greeting_text = GreetingEngine().generate_quick_greeting(
                nickname=nickname, intimacy_level=int(intimacy_level or 0),
            )
            self.greeting_label.setText(greeting_text)
        except Exception:
            self._set_greeting_fallback(nickname)

        # 主形象表情（mood/活动态兜底 normal）
        self._apply_mood_to_avatar(mood or "normal")

        # 每日动态文案（companion.current_mood_context：心情短句+最近事件，正向无数字）
        self._refresh_dynamic_text(companion)

        # 关系称谓 chip（A5 口径：文本称谓，无数值/进度）
        stage = "初识"
        if companion is not None:
            try:
                stage = companion.relation_stage_name()
            except Exception:
                logger.debug("静默降级：_refresh_companion_panel 中忽略异常", exc_info=True)
        try:
            self.stage_chip.setText(f"· 和主人的故事，正在「{stage}」篇章 ·")
            self.stage_chip.setVisible(bool(stage))
        except Exception:
            logger.debug("静默降级：_refresh_companion_panel 中忽略异常", exc_info=True)

        # v1.8(V18-13/D-V18-07): 场景 chip 状态刷新（每次面板刷新即重算，
        # 手动次日回落/时段切换无需定时器）
        self._refresh_scene_chip()

        # 徽章墙占位（A-12 接入点；软展示已解锁成就 id → 名称，无数值）
        self._refresh_badge_hint(companion)

    # -- v1.8(V18-13/D-V18-07): 场景 chip（状态显示 + 点按循环切换） --
    def _refresh_scene_chip(self) -> None:
        """场景 chip 刷新：scene_auto 关 → 隐藏；否则显示当前场景 + 切换提示。"""
        chip = getattr(self, "scene_chip", None)
        if chip is None:
            return
        try:
            import scene as scene_mod
            cfg = getattr(self.app_ctx, "config", None)
            if cfg is not None and not bool(getattr(cfg, "scene_auto", True)):
                chip.setVisible(False)
                return
            mo = scene_mod.resolve_manual_override(
                str(getattr(cfg, "manual_scene", "") or ""),
                str(getattr(cfg, "manual_scene_date", "") or ""))
            sc = scene_mod.current_scene(None, mo)
            text = scene_mod.scene_chip_text(sc)
            chip.setText(text)
            chip.setVisible(bool(text))
        except Exception:
            try:
                chip.setVisible(False)
            except Exception:
                logger.debug("静默降级：_refresh_scene_chip 中忽略异常", exc_info=True)

    def _on_scene_chip_clicked(self) -> None:
        """点按循环切换：当前场景 → 下一场景（work → rest → sleep → 自动）。"""
        try:
            import scene as scene_mod
            cfg = getattr(self.app_ctx, "config", None)
            if cfg is None:
                return
            mo = scene_mod.resolve_manual_override(
                str(getattr(cfg, "manual_scene", "") or ""),
                str(getattr(cfg, "manual_scene_date", "") or ""))
            cur = scene_mod.current_scene(None, mo)
            cycle = {"": scene_mod.SCENE_WORK,
                     scene_mod.SCENE_WORK: scene_mod.SCENE_REST,
                     scene_mod.SCENE_REST: scene_mod.SCENE_SLEEP,
                     scene_mod.SCENE_SLEEP: ""}   # "" = 回到自动感知
            nxt = cycle.get(cur, "")
            cfg.manual_scene = nxt
            if hasattr(cfg, "manual_scene_date"):
                from datetime import datetime as _dt
                cfg.manual_scene_date = _dt.now().strftime("%Y-%m-%d")
            if hasattr(cfg, "save"):
                cfg.save()
        except Exception:
            logger.debug("静默降级：_on_scene_chip_clicked 中忽略异常", exc_info=True)
        self._refresh_scene_chip()

    def _refresh_dynamic_text(self, companion=None) -> None:
        if companion is None:
            companion = getattr(self.app_ctx, "companion", None)
        text = ""
        if companion is not None:
            try:
                text = companion.current_mood_context()
            except Exception:
                text = ""
        if not text:
            text = "安安静静地陪在主人身边~"
        try:
            self.moment_label.setText(f"今日随记 · {text}")
        except Exception:
            logger.debug("静默降级：_refresh_dynamic_text 中忽略异常", exc_info=True)

    def _refresh_badge_hint(self, companion=None) -> None:
        """徽章墙占位：已解锁成就展示名称；未解锁给正向引导，不出现「N/总数」。"""
        if companion is None:
            companion = getattr(self.app_ctx, "companion", None)
        try:
            if companion is None:
                return
            summary = companion.summary_dict()
            achs = summary.get("achievements") or []
            if achs:
                names = {
                    "first_meeting": "初次见面", "first_task": "初次效劳", "first_heal": "暖心治愈",
                    "streak_3": "三日之约", "intimacy_2": "渐渐亲近", "theme_switch": "焕然一新",
                }
                shown = " · ".join(names.get(a, a) for a in achs)
                self.badge_hint.setText(f"徽章 · {shown}")
            else:
                self.badge_hint.setText("徽章墙 · 故事里的每一个「第一次」，都会被悄悄记下")
        except Exception:
            logger.debug("静默降级：_refresh_badge_hint 中忽略异常", exc_info=True)

    # ==================================================================
    # 原有行为（保留功能入口，不删功能）
    # ==================================================================
    def _load_recent_sessions(self) -> None:
        """加载最近会话列表（从 session 历史或本地存储读取）。"""
        self.session_list.clear()
        sessions: List[str] = []

        session = getattr(self.app_ctx, "session", None)
        if session is not None:
            try:
                hist = getattr(session, "history", [])
                if hist:
                    for i, msg in enumerate(hist[-5:]):
                        role = msg.get("role", "unknown")
                        content = msg.get("content", "")[:30]
                        sessions.append(f"{role}: {content}...")
            except Exception:
                logger.debug("静默降级：_load_recent_sessions 中忽略异常", exc_info=True)

        if not sessions:
            sessions = [
                "会话 1: 代码审查讨论...",
                "会话 2: API 接口设计...",
                "会话 3: 重构方案分析...",
                "会话 4: Bug 排查记录...",
                "会话 5: 项目初始化...",
            ]

        for s in sessions[:5]:
            item = QListWidgetItem(s)
            self.session_list.addItem(item)

    def _on_session_clicked(self, item: QListWidgetItem) -> None:
        text = item.text()
        self.session_selected.emit(text)

    def _apply_mode_change(self, key: str, state: bool) -> None:
        """将模式变更应用到 session。"""
        session = getattr(self.app_ctx, "session", None)
        if session is None:
            return
        try:
            if key == "deep":
                if session.deep_mode != state:
                    session.toggle_deep()
            elif key == "coding":
                if session.coding_mode != state:
                    session.toggle_coding()
            elif key == "chat":
                session.set_chat_mode(state)
            elif key == "multi":
                if session.multi_mode != state:
                    session.toggle_multi()
            elif key == "stream":
                if session.stream_mode != state:
                    session.toggle_stream()
        except Exception as exc:
            import logging
            logging.getLogger("maid_coder.gui").warning("模式切换失败: %s", exc)

    def _sync_from_session(self) -> None:
        """从 session 同步当前模式状态 + 刷新房间陪伴区。"""
        session = getattr(self.app_ctx, "session", None)
        if session is not None:
            mapping = {
                "deep": getattr(session, "deep_mode", False),
                "coding": getattr(session, "coding_mode", False),
                "chat": getattr(session, "chat_mode", None) and getattr(session.chat_mode, "is_chat_mode", False),
                "multi": getattr(session, "multi_mode", False),
                "stream": getattr(session, "stream_mode", True),
            }
            for key, state in mapping.items():
                if key in self.cards:
                    self.cards[key].set_state(bool(state))
        self._update_status_cards()
        self._load_recent_sessions()
        # v1.2: 房间陪伴区（形象/问候/动态/称谓/徽章占位）
        self._refresh_companion_panel()
        self._connect_companion()

    def on_enter(self) -> None:
        """页面进入时同步状态。"""
        self._sync_from_session()
        # v1.6(P1-3): 本周回顾卡片（有本周记录才渲染，无则整卡隐藏）
        try:
            self.refresh_weekly_review()
        except Exception as exc:
            logger.debug("本周回顾卡片刷新失败（忽略）: %s", exc)
        # v1.2(B9): 刷新模型设置入口的当前状态文案（厂商/脱敏 Key）
        try:
            if getattr(self, "model_entry_btn", None) is not None:
                self._refresh_model_entry()
        except Exception:
            logger.debug("静默降级：on_enter 中忽略异常", exc_info=True)

    def _update_status_cards(self) -> None:
        """更新状态概览卡片数据（技术态，非养成数值）。"""
        token_used = "--"
        session = getattr(self.app_ctx, "session", None)
        if session is not None:
            try:
                token_used = getattr(session, "token_used", "--")
                if isinstance(token_used, int):
                    token_used = f"{token_used}"
            except Exception:
                logger.debug("静默降级：_update_status_cards 中忽略异常", exc_info=True)
        self.token_card.set_value(str(token_used))

        cfg = getattr(self.app_ctx, "cfg", None)
        if cfg and getattr(cfg, "api_key", None):
            self.network_card.set_value("已连接")
        else:
            self.network_card.set_value("未配置")

        proj_dir = getattr(self.app_ctx, "project_dir", None)
        if proj_dir:
            import os
            self.project_card.set_value(os.path.basename(str(proj_dir)))
        else:
            self.project_card.set_value("未设置")

    # ==================================================================
    # 快捷入口 handlers
    # ==================================================================
    def _navigate(self, key: str) -> None:
        pm = getattr(self.app_ctx, "page_manager", None)
        if pm is not None and hasattr(pm, "navigate"):
            pm.navigate(key)
        else:
            self.header_hint.setText(f"页面管理器未就绪（目标：{key}）")

    # ---- v1.2(B9): 模型设置直达 ----
    def _refresh_model_entry(self) -> None:
        """刷新首页模型入口文案：当前厂商 + Key 末 4 位（脱敏）+ 引导。"""
        try:
            from core import api_status_summary
            summary = api_status_summary(getattr(self.app_ctx, "cfg", None))
        except Exception:
            summary = None
        if not summary:
            _apply_button_icon(self.model_entry_btn, self.app_ctx, "settings",
                               "模型设置", "\u2699 模型设置")
            self.model_entry_hint.setText("")
            return
        if summary["configured"]:
            clean = f"模型设置 · {summary['provider_short']} · {summary['masked_key']}"
            _apply_button_icon(self.model_entry_btn, self.app_ctx, "settings",
                               clean, f"\u2699 {clean}")
            hint = summary["state_text"]
        else:
            _apply_button_icon(self.model_entry_btn, self.app_ctx, "settings",
                               "模型设置 · 未配置 Key，点此去配置",
                               "\u2699 模型设置 · 未配置 Key，点此去配置")
            hint = summary.get("hint") or "选择厂商并填写 API Key"
        self.model_entry_hint.setText(hint)
        tip_lines = [
            f"当前厂商：{summary['provider_label']}",
            f"模型：{summary['model'] or '—'}",
            f"Key：{summary['masked_key']}",
            f"状态：{summary['state_text']}",
            "点击直达设置页「模型与接口」",
        ]
        self.model_entry_btn.setToolTip("\n".join(tip_lines))

    def _on_open_model_settings(self) -> None:
        """模型设置直达：优先走 MainWindow.open_model_settings()（含滚动定位），
        否则退化为仅导航到设置页。全部防御式。"""
        try:
            mw = self.window()
            if mw is not None and hasattr(mw, "open_model_settings"):
                mw.open_model_settings()
                return
        except Exception:
            logger.debug("静默降级：_on_open_model_settings 中忽略异常", exc_info=True)
        self._navigate("settings")

    def _on_start_chat(self) -> None:
        """开始聊天：开启新会话并提示（聊天主屏常驻，输入即对话）。"""
        self._on_new_chat()
        self.header_hint.setText("已为你开好新会话，去聊天页和码铃说点什么吧~")

    def _on_toggle_agent_from_home(self) -> None:
        """Agent 快捷开关：切换 ChatService Agent 模式（保底失败给出提示）。"""
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is None:
            self.header_hint.setText("聊天服务未就绪，稍后再试")
            return
        try:
            current = bool(chat_service.is_agent_mode()) if hasattr(chat_service, "is_agent_mode") else False
            new_state = not current
            if hasattr(chat_service, "set_agent_mode"):
                chat_service.set_agent_mode(new_state)
            self.header_hint.setText("Agent 模式已开启：去聊天页输入任务，码铃会带工具干活~"
                                     if new_state else "Agent 模式已关闭")
        except Exception:
            self.header_hint.setText("切换 Agent 模式失败，请到聊天页操作")

    def _on_new_chat(self) -> None:
        session = getattr(self.app_ctx, "session", None)
        if session is not None:
            try:
                session.clear()
                # v2.1(UI-Fix-0912): clear() 仅清空内存,需要显式 save() 才会有新记录文件
                try:
                    name = session.save()
                    self.header_hint.setText(f"新对话已创建: {name}")
                except Exception:
                    self.header_hint.setText("新对话已创建")
                self._load_recent_sessions()
            except Exception:
                logger.debug("静默降级：_on_new_chat 中忽略异常", exc_info=True)

    def _on_save_session(self) -> None:
        session = getattr(self.app_ctx, "session", None)
        if session is not None:
            try:
                name = session.save()
                self.header_hint.setText(f"会话已保存: {name}")
                self._load_recent_sessions()
            except Exception as exc:
                self.header_hint.setText(f"保存失败: {exc}")

    def _on_load_session(self) -> None:
        from gui.qt_compat import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "加载会话", "", "JSON (*.json)")
        if path:
            session = getattr(self.app_ctx, "session", None)
            if session is not None:
                try:
                    session.load(path)
                    self.header_hint.setText("会话已加载")
                    self._load_recent_sessions()
                except Exception as exc:
                    self.header_hint.setText(f"加载失败: {exc}")
