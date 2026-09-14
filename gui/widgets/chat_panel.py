"""聊天面板 —— 消息气泡区、输入框、发送按钮、快捷操作栏、会话列表，支持展开为独立窗口。

第四阶段扩展：文件拖拽上传、消息编辑/重新生成、多会话标签页、语音输入。
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger("maid_coder.gui.chat_panel")

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QScrollArea, QFrame, Qt, QSizePolicy, QFont,
    QFileDialog, QClipboard, QApplication, QMessageBox,
    QGridLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QInputDialog, QCheckBox, QComboBox, QDialog,
)
from gui.widgets.message_bubble import MessageBubble
from gui.widgets.chat_window import ChatWindow
from gui.widgets.thinking_indicator import ThinkingIndicator
from gui.widgets.tool_trace import ToolTracePanel
from gui.widgets.attachment_bar import AttachmentBar
from gui.widgets.session_tabs import SessionTabsBar
from gui.widgets import voice_input as voice_input_mod
from gui.models import ChatMessage, ChatSession
from gui.command_registry import CommandRegistry
from gui.chat_exporter import ChatExporter
from datetime import datetime

# v1.4.8: 引入提取的纯函数模块，降低 chat_panel 耦合
from gui.chat_helpers import (
    build_matcher as _pure_build_matcher,
    highlight_style as _highlight_style,
    clear_highlight_style as _clear_highlight_style,
    truncate_preview,
    format_search_result,
    filter_messages_by_role,
    format_export_preview,
    parse_command_input,
    estimate_reading_time,
    detect_code_language,
    detect_export_format,
    normalize_session_name,
)
from gui.chat_bubble_utils import (
    HIGHLIGHT_STYLE,
    DEFAULT_MAX_BUBBLE_WIDTH,
    format_role_label,
    is_consecutive_role,
    build_bubble_metadata,
    format_message_count,
    estimate_bubble_height,
    collect_messages_from_layout,
)
# v1.4.8: 输入/流式/Agent 纯逻辑模块
from gui.chat_input_logic import (
    should_trigger_command_popup,
    format_tool_label,
    format_agent_event_status,
    is_agent_final_event,
)
from gui.chat_stream_state import StreamState, format_usage_summary
# v1.7(F10a/D-V17-06): 群聊显示会话层（@解析 / 会话判定 / 建群）
from gui.chat_service import (
    parse_mention_partial as _parse_mention_partial,
    mention_candidates as _mention_candidates,
    apply_mention_completion as _apply_mention_completion,
    GROUP_DEFAULT_NO_AT_POLICY,
)
from gui.session_manager import is_group_session as _is_group_session


class _ElidedLabel(QLabel):
    """窄宽度下自动显示省略号（…）的 QLabel，替代直接截断/挤压重叠。

    对外接口与 QLabel 完全一致（setText 等调用点无需改动）。
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self._full_text = text
        self.setMinimumWidth(4)

    def setText(self, text: str) -> None:
        self._full_text = text
        QLabel.setText(self, text)
        self._apply_elide()

    def text(self) -> str:
        # 对外始终返回完整原文（省略号只用于显示，不污染读取方）
        return self._full_text

    def _apply_elide(self) -> None:
        width = self.contentsRect().width()
        if width <= 0:
            return
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, width
        )
        QLabel.setText(self, elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()


class ChatPanelWidget(QWidget):
    """聊天面板：会话列表 + 消息列表 + 快捷操作栏 + 输入区 + 展开按钮。"""

    EMOJIS = ["❤", "✨", "(｡･ω･｡)", "(´▽｀)", "(*´∀`)~♥", "(๑•̀ㅂ•́)و✧",
              "(｡♥‿♥｡)", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "(｡◕‿◕｡)", "♪(´ε｀ )", "(≧▽≦)", "(｡･ω･｡)ﾉ♡"]

    QUICK_REPLIES = [
        "辛苦了~",
        "做得不错❤",
        "继续吧",
        "等等，我有别的事说",
    ]

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.chat_service = getattr(app_context, "chat_service", None)
        self.session_manager = getattr(app_context, "session_manager", None)
        self._command_registry = CommandRegistry()
        self._chat_window: Optional[ChatWindow] = None
        self._last_role: Optional[str] = None
        self._current_session_id: Optional[str] = None
        # v1.7(F10a): 群聊发言者追踪（气泡名字/头像渲染与流式归属）
        self._last_speaker_id: Optional[str] = None
        self._highlighted_bubble = None
        # 第四阶段：标签页模式状态
        self._tab_mode: bool = False
        self._open_tab_ids: List[str] = []
        # v1.1(B2): Agent 工具轨迹状态 —— 是否正在收集本轮的轨迹事件
        self._agent_trace_active: bool = False
        # v1.3(P1-2): 截图选区模态是否进行中（防热键/按钮重入）
        self._screenshot_active: bool = False
        # v1.4(B1b): 看屏 —— 状态栏/按屏待发标志/本屏帧 token 待记
        self._watch_svc = None
        self._watch_svc_ready: bool = False
        self._screen_pending_token: bool = False
        # v1.3(P2-2): 免提 —— 语音消息发送后等待 AI 回复流结束（用于回到听/朗读）
        self._hf_pending_reply: bool = False
        # 第四阶段：拖拽
        self.setAcceptDrops(True)
        self._init_ui()
        self._connect_signals()
        self._init_handsfree()
        self._init_screen_watch()
        self._load_active_session()

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 左侧会话列表（可折叠）---
        self.session_sidebar = QWidget()
        self.session_sidebar.setObjectName("sessionSidebar")
        self.session_sidebar.setFixedWidth(160)
        ss_layout = QVBoxLayout(self.session_sidebar)
        ss_layout.setContentsMargins(8, 8, 8, 8)
        ss_layout.setSpacing(6)

        ss_header = QHBoxLayout()
        ss_title = QLabel("会话")
        ss_title.setStyleSheet("QLabel { font-size: 12px; font-weight: bold; color: #5D4037; }")
        ss_header.addWidget(ss_title)
        ss_header.addStretch()

        # 新会话圆球：中心显示白色「＋」大号粗体，直观表达「新增会话」（避免空球歧义）。
        self.new_session_btn = QPushButton("＋")
        self.new_session_btn.setFixedSize(24, 24)
        self.new_session_btn.setCursor(Qt.PointingHandCursor)
        self.new_session_btn.setStyleSheet(
            "QPushButton { background: #FF9EB5; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: bold; }"
            "QPushButton:hover { background: #FF6B9D; }"
        )
        self.new_session_btn.setToolTip("新建会话")
        self.new_session_btn.clicked.connect(self._on_new_session)
        ss_header.addWidget(self.new_session_btn)
        ss_layout.addLayout(ss_header)

        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; color: #5D4037; }"
            "QListWidget::item:selected { background: #FFE4EC; color: #FF6B9D; font-weight: 500; }"
            "QListWidget::item:hover { background: #FFF0F3; }"
        )
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._show_session_menu)
        self.session_list.itemClicked.connect(self._on_session_selected)
        ss_layout.addWidget(self.session_list, 1)

        # 折叠按钮
        self.toggle_sidebar_btn = QPushButton("◀")
        self.toggle_sidebar_btn.setFixedSize(20, 60)
        self.toggle_sidebar_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_sidebar_btn.setStyleSheet(
            "QPushButton { background: #FFF0F3; color: #FF9EB5; border: none; border-radius: 4px; font-size: 10px; }"
            "QPushButton:hover { background: #FFB6C1; color: white; }"
        )
        self.toggle_sidebar_btn.clicked.connect(self._on_toggle_sidebar)

        main_layout.addWidget(self.session_sidebar)
        main_layout.addWidget(self.toggle_sidebar_btn)

        # --- 聊天区（v1.2 起聊天面板为中间主屏，非右侧窄栏）---
        chat_area = QWidget()
        layout = QVBoxLayout(chat_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题栏 —— v10.5 布局修复：拆两行收纳
        # 第一行：会话标题（省略号）+ 状态 + 三个图标按钮（导出/标签页/展开）
        # 第二行：搜索框（随面板伸缩）+ 正则开关 + 范围下拉
        header_wrap = QVBoxLayout()
        header_wrap.setContentsMargins(12, 8, 12, 4)
        header_wrap.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.title_label = _ElidedLabel("聊天")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_row.addWidget(self.title_label, 1)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("chatSearchEdit")
        self.search_edit.setPlaceholderText("搜索消息...")
        self.search_edit.setMinimumWidth(60)
        self.search_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.search_edit.setStyleSheet(
            "QLineEdit { background: #FFF5F7; border: 1px solid #FFD6E0;"
            " border-radius: 10px; padding: 2px 8px; font-size: 11px; }"
            "QLineEdit:focus { border-color: #FF9EB5; }"
        )
        self.search_edit.textChanged.connect(self._on_search_filter)

        # 正则模式开关
        self.regex_check = QCheckBox("正则")
        self.regex_check.setToolTip("使用正则表达式搜索")
        self.regex_check.setStyleSheet(
            "QCheckBox { color: #FF9EB5; font-size: 11px; spacing: 4px; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
        )
        self.regex_check.toggled.connect(lambda _: self._on_search_filter(self.search_edit.text()))

        # 搜索范围切换：当前会话 / 全部会话
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("当前会话", "current")
        self.scope_combo.addItem("全部会话", "all")
        self.scope_combo.setToolTip("搜索范围")
        self.scope_combo.setMinimumContentsLength(4)
        self.scope_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.scope_combo.setStyleSheet(
            "QComboBox { background: #FFF5F7; border: 1px solid #FFD6E0;"
            " border-radius: 10px; padding: 2px 4px; font-size: 11px; }"
        )
        self.scope_combo.currentIndexChanged.connect(lambda _: self._on_search_filter(self.search_edit.text()))

        title_row.addStretch()

        # 图标按钮收纳：导出 / 标签页 / 展开（窄面板下不再与文字按钮挤同一行）
        self.export_btn = QPushButton("📤")
        self.export_btn.setObjectName("exportChatBtn")
        self.export_btn.setFixedSize(32, 28)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setToolTip("导出聊天记录（Markdown / TXT / JSON）")
        self.export_btn.setStyleSheet(
            "QPushButton#exportChatBtn {"
            "  background: transparent; color: #4A90D9;"
            "  border: 1px solid #A8C8E8; border-radius: 12px;"
            "  font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#exportChatBtn:hover {"
            "  background: #4A90D9; color: #FFFFFF; border-color: #4A90D9;"
            "}"
        )
        self.export_btn.clicked.connect(self._on_export_chat)
        title_row.addWidget(self.export_btn)

        # 第四阶段：标签页模式开关
        self.tab_mode_btn = QPushButton("🗂")
        self.tab_mode_btn.setObjectName("tabModeBtn")
        self.tab_mode_btn.setCheckable(True)
        self.tab_mode_btn.setFixedSize(32, 28)
        self.tab_mode_btn.setCursor(Qt.PointingHandCursor)
        self.tab_mode_btn.setToolTip("切换标签页模式（浏览器式 tab）")
        self.tab_mode_btn.setStyleSheet(
            "QPushButton#tabModeBtn {"
            "  background: transparent; color: #8A6D9C;"
            "  border: 1px solid #D4B5DC; border-radius: 12px;"
            "  font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#tabModeBtn:checked {"
            "  background: #D4B5DC; color: #FFFFFF; border-color: #B58FC2;"
            "}"
            "QPushButton#tabModeBtn:hover {"
            "  background: #E8D5EE; color: #6D4A85;"
            "}"
        )
        self.tab_mode_btn.toggled.connect(self._on_toggle_tab_mode)
        title_row.addWidget(self.tab_mode_btn)

        self.expand_btn = QPushButton("↗")
        self.expand_btn.setObjectName("expandChatBtn")
        self.expand_btn.setFixedSize(32, 28)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setToolTip("展开为独立聊天窗口")
        self.expand_btn.setStyleSheet(
            "QPushButton#expandChatBtn {"
            "  background: transparent; color: #FF6B9D;"
            "  border: 1px solid #FFB6C1; border-radius: 12px;"
            "  font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#expandChatBtn:hover {"
            "  background: #FF9EB5; color: #FFFFFF; border-color: #FF9EB5;"
            "}"
        )
        self.expand_btn.clicked.connect(self._on_expand_chat)
        title_row.addWidget(self.expand_btn)

        # v1.9 A(D-V19-13②)：界面风格快捷入口（顶栏按钮 → 四风格小菜单，选中即切）
        self.style_btn = QPushButton("🎨")
        self.style_btn.setObjectName("styleSwitchBtn")
        self.style_btn.setFixedSize(32, 28)
        self.style_btn.setCursor(Qt.PointingHandCursor)
        self.style_btn.setToolTip("切换界面风格")
        self.style_btn.clicked.connect(self._on_style_menu)
        title_row.addWidget(self.style_btn)

        self.status_label = _ElidedLabel("")
        self.status_label.setObjectName("chatStatusLabel")
        self.status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        title_row.addWidget(self.status_label)
        header_wrap.addLayout(title_row)

        # 第二行：搜索区
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.regex_check)
        search_row.addWidget(self.scope_combo)
        header_wrap.addLayout(search_row)
        layout.addLayout(header_wrap)

        # 第四阶段：标签页栏（默认隐藏，开启标签页模式时显示）
        self.session_tabs = SessionTabsBar(self.app_ctx)
        self.session_tabs.setVisible(False)
        self.session_tabs.tab_switched.connect(self._on_tab_switched)
        self.session_tabs.tab_new_requested.connect(self._on_tab_new)
        self.session_tabs.tab_close_requested.connect(self._on_tab_close)
        layout.addWidget(self.session_tabs)

        # v1.3(P2-2): 免提状态条 —— 聊天面板顶部常驻醒目（开关在快捷操作栏「🎙 免提」）
        try:
            from gui.widgets.handsfree_bar import HandsfreeBar
            self.handsfree_bar = HandsfreeBar(self.app_ctx)
            self.handsfree_bar.setVisible(False)  # 无 STT 后端时整条隐藏（见 _init_handsfree）
        except Exception as exc:
            logger.warning("免提状态条不可用: %s", exc)
            self.handsfree_bar = None
        if self.handsfree_bar is not None:
            layout.addWidget(self.handsfree_bar)

        # v1.4(B1b): 看屏状态条 chip —— 常驻在看屏开启期间（默认隐藏，开关驱动显隐）
        self.screen_watch_bar = None
        try:
            from gui.widgets.screen_watch_bar import ScreenWatchBar
            self.screen_watch_bar = ScreenWatchBar(self.app_ctx)
        except Exception as exc:
            logger.warning("看屏状态条不可用: %s", exc)
            self.screen_watch_bar = None
        if self.screen_watch_bar is not None:
            self.screen_watch_bar.setVisible(False)
            layout.addWidget(self.screen_watch_bar)

        # 消息滚动区
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.messages_container = QWidget()
        self.messages_container.setObjectName("chatMessagesContainer")
        self.messages_layout = QVBoxLayout(self.messages_container)
        # 大气化：消息流水平与上下留白充足、气泡之间呼吸感更舒服
        self.messages_layout.setContentsMargins(24, 20, 24, 20)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch()
        self.scroll_area.setWidget(self.messages_container)
        layout.addWidget(self.scroll_area, 1)

        # 思考指示器
        self.thinking_indicator = ThinkingIndicator("AI 正在思考", app_context=self.app_ctx, parent=self)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, self.thinking_indicator)

        # v1.1(B2): Agent 工具轨迹折叠卡片 —— 常驻在输入区上方、消息滚动区之下；
        # 默认隐藏，收到 agent 事件时自动显示，新一次发送前 reset（不打断气泡流式渲染）
        self.tool_trace_panel = ToolTracePanel(app_context=self.app_ctx, parent=self)
        layout.addWidget(self.tool_trace_panel)

        # 快捷操作栏
        self._setup_quick_actions(layout)

        # 输入区
        input_container = QWidget()
        input_container.setObjectName("chatInputContainer")
        input_layout = QVBoxLayout(input_container)
        # 大气化：输入区四周留白加大，与消息区协调
        input_layout.setContentsMargins(20, 12, 20, 16)
        input_layout.setSpacing(10)

        # 表情选择面板（默认隐藏）
        self.emoji_panel = QWidget()
        self.emoji_panel.setObjectName("emojiPanel")
        self.emoji_panel.setVisible(False)
        emoji_layout = QGridLayout(self.emoji_panel)
        emoji_layout.setContentsMargins(8, 8, 8, 8)
        emoji_layout.setSpacing(6)
        for idx, emoji in enumerate(self.EMOJIS):
            btn = QPushButton(emoji)
            btn.setFixedSize(44, 36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { background: #FFF0F5; border: 1px solid #FFB6C1;"
                " border-radius: 8px; font-size: 14px; }"
                "QPushButton:hover { background: #FFB6C1; }"
            )
            btn.clicked.connect(lambda checked, e=emoji: self._on_emoji_clicked(e))
            emoji_layout.addWidget(btn, idx // 4, idx % 4)
        input_layout.addWidget(self.emoji_panel)

        # 快捷回复栏 —— v10.5 布局修复：收纳进横向滚动区并锁定最小宽，
        # 标签文字完整显示，放不下时横向滚动，不再截断成单字
        quick_reply_scroll = QScrollArea()
        quick_reply_scroll.setObjectName("quickReplyScroll")
        quick_reply_scroll.setWidgetResizable(True)
        quick_reply_scroll.setFixedHeight(44)
        quick_reply_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        quick_reply_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        quick_reply_scroll.setFrameShape(QFrame.NoFrame)

        quick_reply_container = QWidget()
        quick_reply_layout = QHBoxLayout(quick_reply_container)
        quick_reply_layout.setContentsMargins(0, 0, 4, 0)
        quick_reply_layout.setSpacing(6)
        for reply_text in self.QUICK_REPLIES:
            btn = QPushButton(reply_text)
            btn.setObjectName("quickReplyBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton#quickReplyBtn { background: #FFF0F5; color: #FF69B4;"
                " border: 1px solid #FFB6C1; border-radius: 10px;"
                " font-size: 11px; padding: 2px 10px; }"
                "QPushButton#quickReplyBtn:hover { background: #FFB6C1; color: white; }"
            )
            btn.setMinimumWidth(btn.sizeHint().width())
            btn.clicked.connect(lambda checked, t=reply_text: self._on_quick_reply(t))
            quick_reply_layout.addWidget(btn)
        quick_reply_layout.addStretch()
        quick_reply_scroll.setWidget(quick_reply_container)
        input_layout.addWidget(quick_reply_scroll)

        # 第四阶段：附件芯片栏（拖拽 / 添加后自动出现，初始隐藏）
        self.attachment_bar = AttachmentBar(self.app_ctx)
        input_layout.addWidget(self.attachment_bar)

        self.input_edit = QTextEdit()
        self.input_edit.setObjectName("chatInput")
        self.input_edit.setPlaceholderText("和女仆说点什么吧... （或拖拽文件）")
        # 大气化：输入框更高，可写更多内容；与发送按钮协调
        # （动态上限约 6 行，见 _adjust_input_height；此处 200 为初值兜底）
        self.input_edit.setMinimumHeight(48)
        self.input_edit.setMaximumHeight(200)
        self.input_edit.setAcceptRichText(False)
        # 让文件拖拽事件透传到 ChatPanelWidget 自身（panel setAcceptDrops(True)）
        self.input_edit.setAcceptDrops(False)
        self.input_edit.installEventFilter(self)
        self.input_edit.textChanged.connect(self._on_input_text_changed)
        input_layout.addWidget(self.input_edit)
        # v1.4.6: 输入框随内容多行增高（48~200 区间，超出内部滚动）
        self.input_edit.textChanged.connect(self._adjust_input_height)

        # 指令补全浮层（默认隐藏）
        self._cmd_popup = QListWidget(self)
        self._cmd_popup.setObjectName("commandPopup")
        self._cmd_popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self._cmd_popup.setFocusPolicy(Qt.NoFocus)
        self._cmd_popup.setFixedWidth(280)
        self._cmd_popup.setMaximumHeight(220)
        self._cmd_popup.setStyleSheet(
            "QListWidget#commandPopup { background: #FFFFFF; border: 1px solid #FFB6C1;"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#commandPopup::item { padding: 6px 8px; border-radius: 6px; }"
            "QListWidget#commandPopup::item:selected { background: #FFE4EC; color: #FF6B9D; }"
        )
        self._cmd_popup.itemDoubleClicked.connect(lambda _: self._accept_command())
        self._cmd_popup.hide()

        # v1.7(F10b): 群聊 @ 成员补全浮层（@ 输入态触发，复用指令浮层的轻实现）
        self._mention_popup = QListWidget(self)
        self._mention_popup.setObjectName("mentionPopup")
        self._mention_popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self._mention_popup.setFocusPolicy(Qt.NoFocus)
        self._mention_popup.setFixedWidth(220)
        self._mention_popup.setMaximumHeight(180)
        self._mention_popup.setStyleSheet(
            "QListWidget#mentionPopup { background: #FFFFFF; border: 1px solid #FFB6C1;"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#mentionPopup::item { padding: 6px 8px; border-radius: 6px; }"
            "QListWidget#mentionPopup::item:selected { background: #FFE4EC; color: #FF6B9D; }"
        )
        self._mention_popup.itemClicked.connect(
            lambda item: self._accept_mention(item.data(Qt.UserRole))
        )
        self._mention_popup.hide()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.stop_btn = QPushButton("停止生成")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        # 大气化：按钮高度与发送/Agent 按钮统一
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setStyleSheet(
            "QPushButton#stopBtn {"
            "  background: #FF6B6B; color: #FFFFFF;"
            "  border: none; border-radius: 10px;"
            "  font-size: 13px; padding: 6px 16px;"
            "}"
            "QPushButton#stopBtn:hover { background: #FF5252; }"
        )
        self.stop_btn.clicked.connect(self._on_stop_generation)
        self.stop_btn.setVisible(False)
        btn_row.addWidget(self.stop_btn)

        # v1.1(agent): Agent 模式开关 —— 开启后消息走 AgentEngine 工具循环
        try:
            from gui.utils import theme_color
            _agent_on = theme_color(self.app_ctx, "accent", "#FF6B9D")
            _agent_bg = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        except Exception:
            _agent_on, _agent_bg = "#FF6B9D", "#FFF0F3"
        self.agent_btn = QPushButton("🤖 Agent")
        self.agent_btn.setObjectName("agentModeBtn")
        self.agent_btn.setCheckable(True)
        self.agent_btn.setCursor(Qt.PointingHandCursor)
        # 大气化：按钮高度 40 与发送按钮统一
        self.agent_btn.setFixedHeight(40)
        self.agent_btn.setToolTip(
            "Agent 模式：让女仆自主调用工具完成任务\n"
            "（读文件 / 列目录 / Git / 写文件 / 运行沙箱代码 / 联网搜索）\n"
            "修改类操作会先征求你的授权。关闭后回到普通聊天。"
        )
        self.agent_btn.setStyleSheet(
            f"QPushButton#agentModeBtn {{"
            f"  background: transparent; color: {_agent_on};"
            f"  border: 1px solid {_agent_on}; border-radius: 10px;"
            f"  font-size: 13px; padding: 6px 16px;"
            f"}}"
            f"QPushButton#agentModeBtn:checked {{"
            f"  background: {_agent_on}; color: #FFFFFF; border-color: {_agent_on};"
            f"}}"
            f"QPushButton#agentModeBtn:hover {{ background: {_agent_bg}; }}"
        )
        self.agent_btn.toggled.connect(self._on_toggle_agent_mode)
        # v1.1(B1/B3): 启动默认状态读自 AppConfig.agent_enabled（设置页可持久化；
        # 运行时用户仍可手动切换，按钮显式操作优先）
        try:
            _cfg = getattr(self.app_ctx, "cfg", None)
            if _cfg is not None and getattr(_cfg, "agent_enabled", False):
                self.agent_btn.setChecked(True)
        except Exception:
            pass
        btn_row.addWidget(self.agent_btn)

        # v1.4.7: 任务模式按钮 —— 开启后发送消息走 managed task（自动拆分步骤/自愈/断点恢复）
        self.task_btn = QPushButton("📋 任务")
        self.task_btn.setObjectName("taskModeBtn")
        self.task_btn.setCheckable(True)
        self.task_btn.setCursor(Qt.PointingHandCursor)
        self.task_btn.setFixedHeight(40)
        self.task_btn.setToolTip(
            "任务模式：女仆自动将大任务拆分为多步逐步执行\n"
            "支持断点恢复、失败自愈（自动重试修复）。\n"
            "适合多步骤复杂任务（如「写一个脚本并测试」）。\n"
            "需要同时开启 Agent 模式。"
        )
        _task_color = theme_color(self.app_ctx, "accent", "#FF6B9D") if hasattr(self, 'app_ctx') else "#FF6B9D"
        self.task_btn.setStyleSheet(
            f"QPushButton#taskModeBtn {{"
            f"  background: transparent; color: {_task_color};"
            f"  border: 1px solid {_task_color}; border-radius: 10px;"
            f"  font-size: 13px; padding: 6px 16px;"
            f"}}"
            f"QPushButton#taskModeBtn:checked {{"
            f"  background: {_task_color}; color: #FFFFFF; border-color: {_task_color};"
            f"}}"
            f"QPushButton#taskModeBtn:hover {{ background: {theme_color(self.app_ctx, 'bg_light', '#FFF0F3') if hasattr(self, 'app_ctx') else '#FFF0F3'}; }}"
        )
        self.task_btn.toggled.connect(self._on_toggle_task_mode)
        btn_row.addWidget(self.task_btn)

        # v1.5.0: 「🌐 联网」开关 —— 开启后普通聊天命中检索意图时自动联网搜索并注入上下文
        # （引擎优先级：博查(有key) > cn.bing.com 解析 > ddgs；详见 helpers.WebSearch）。
        # 状态持久化在 GuiConfig.web_search_enabled_gui；Agent 模式不受本开关影响（其自带 web_search 工具）。
        try:
            _web_on = theme_color(self.app_ctx, "accent", "#FF6B9D")
            _web_bg = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        except Exception:
            _web_on, _web_bg = "#FF6B9D", "#FFF0F3"
        self.web_btn = QPushButton("🌐 联网")
        self.web_btn.setObjectName("webSearchBtn")
        self.web_btn.setCheckable(True)
        self.web_btn.setCursor(Qt.PointingHandCursor)
        self.web_btn.setFixedHeight(40)
        self.web_btn.setToolTip(
            "联网搜索：开启后，普通聊天遇到「最新版本 / 文档 / 报错」等\n"
            "需要最新信息的问题时会自动联网检索并注入回答上下文。\n"
            "默认引擎 cn.bing.com（免费零配置）；配置博查 API Key 后优先使用博查。"
        )
        self.web_btn.setStyleSheet(
            f"QPushButton#webSearchBtn {{"
            f"  background: transparent; color: {_web_on};"
            f"  border: 1px solid {_web_on}; border-radius: 10px;"
            f"  font-size: 13px; padding: 6px 16px;"
            f"}}"
            f"QPushButton#webSearchBtn:checked {{"
            f"  background: {_web_on}; color: #FFFFFF; border-color: {_web_on};"
            f"}}"
            f"QPushButton#webSearchBtn:hover {{ background: {_web_bg}; }}"
        )
        self.web_btn.toggled.connect(self._on_toggle_web_search)
        # 启动默认状态读自 GuiConfig.web_search_enabled_gui（持久化）
        try:
            _gui_cfg = getattr(self.app_ctx, "config", None)
            if _gui_cfg is not None and getattr(_gui_cfg, "web_search_enabled_gui", False):
                self.web_btn.setChecked(True)
        except Exception:
            pass
        btn_row.addWidget(self.web_btn)

        # v1.6(P0-2): 意图选态小型下拉（默认"自动"；手动选态覆盖自动识别）。
        # 只附加不接管 —— 选态仅影响请求副本里的语气提示，消息流绝不改道；
        # 状态持久化 GuiConfig.chat_intent_mode。
        self.intent_combo = QComboBox()
        self.intent_combo.setObjectName("intentModeCombo")
        self.intent_combo.setCursor(Qt.PointingHandCursor)
        self.intent_combo.setFixedHeight(40)
        for label, value in (
            ("🎯 自动", "auto"), ("💭 只想说说", "confide"), ("💬 陪我聊聊", "chat"),
            ("🔍 帮我分析", "analyze"), ("💡 给我建议", "advise"), ("⚡ 帮我行动", "act"),
        ):
            self.intent_combo.addItem(label, value)
        self.intent_combo.setToolTip(
            "消息意图：默认自动识别（零 token 纯规则）。\n"
            "想固定语气时手动选一种 —— 只会影响码铃的回应方式，\n"
            "不会改变消息的正常收发。"
        )
        try:
            self.intent_combo.setStyleSheet(
                f"QComboBox#intentModeCombo {{"
                f"  background: transparent; color: {_web_on};"
                f"  border: 1px solid {_web_on}; border-radius: 10px;"
                f"  font-size: 13px; padding: 6px 10px;"
                f"}}"
                f"QComboBox#intentModeCombo::drop-down {{ border: none; width: 18px; }}"
                f"QComboBox#intentModeCombo QAbstractItemView {{"
                f"  background: #FFFFFF; color: #4A4A4A; selection-background-color: {_web_bg};"
                f"  selection-color: #4A4A4A;"
                f"}}"
            )
        except Exception:
            pass
        self.intent_combo.currentIndexChanged.connect(self._on_intent_mode_changed)
        # 启动默认态读自 GuiConfig.chat_intent_mode（持久化）
        try:
            _saved = str(getattr(getattr(self.app_ctx, "config", None),
                                 "chat_intent_mode", "auto") or "auto")
            _i = self.intent_combo.findData(_saved)
            if _i >= 0:
                self.intent_combo.blockSignals(True)
                self.intent_combo.setCurrentIndex(_i)
                self.intent_combo.blockSignals(False)
        except Exception:
            pass
        btn_row.addWidget(self.intent_combo)

        # v1.8(V18-13/D-V18-07): 场景手动切换小型下拉（与意图选态同款风格）。
        # 手动切换当日有效、次日回落自动感知（Q-D4）；持久化 GuiConfig
        # manual_scene + manual_scene_date。当前场景状态 = 下拉选中项即状态显示。
        self.scene_combo = QComboBox()
        self.scene_combo.setObjectName("sceneModeCombo")
        self.scene_combo.setCursor(Qt.PointingHandCursor)
        self.scene_combo.setFixedHeight(40)
        for label, value in (
            ("✨ 场景·自动", ""), ("💼 工作", "work"),
            ("☕ 休息", "rest"), ("🌙 睡前", "sleep"),
        ):
            self.scene_combo.addItem(label, value)
        self.scene_combo.setToolTip(
            "陪伴场景：默认按时段自动感知（工作日 9-12/14-18 点为工作模式，\n"
            "22:30-次日 6:30 为睡前模式）。手动选定后当日有效、次日自动回落；\n"
            "只影响码铃的语气底色与主动消息频率，不会改变消息的正常收发。"
        )
        try:
            self.scene_combo.setStyleSheet(
                f"QComboBox#sceneModeCombo {{"
                f"  background: transparent; color: {_web_on};"
                f"  border: 1px solid {_web_on}; border-radius: 10px;"
                f"  font-size: 13px; padding: 6px 10px;"
                f"}}"
                f"QComboBox#sceneModeCombo::drop-down {{ border: none; width: 18px; }}"
                f"QComboBox#sceneModeCombo QAbstractItemView {{"
                f"  background: #FFFFFF; color: #4A4A4A; selection-background-color: {_web_bg};"
                f"  selection-color: #4A4A4A;"
                f"}}"
            )
        except Exception:
            pass
        self.scene_combo.currentIndexChanged.connect(self._on_scene_mode_changed)
        # 启动默认态：manual_scene 当日有效才回显，否则回落"自动"
        try:
            _scfg = getattr(self.app_ctx, "config", None)
            _saved_scene = str(getattr(_scfg, "manual_scene", "") or "")
            _saved_date = str(getattr(_scfg, "manual_scene_date", "") or "")
            if _saved_date != datetime.now().strftime("%Y-%m-%d"):
                _saved_scene = ""
            _si = self.scene_combo.findData(_saved_scene)
            if _si >= 0:
                self.scene_combo.blockSignals(True)
                self.scene_combo.setCurrentIndex(_si)
                self.scene_combo.blockSignals(False)
        except Exception:
            pass
        btn_row.addWidget(self.scene_combo)

        btn_row.addStretch()

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        # 大气化：发送按钮加高加大
        self.send_btn.setFixedHeight(40)
        self.send_btn.clicked.connect(self._on_send)
        btn_row.addWidget(self.send_btn)
        input_layout.addLayout(btn_row)

        layout.addWidget(input_container)
        main_layout.addWidget(chat_area, 1)

    def _setup_quick_actions(self, parent_layout: QVBoxLayout) -> None:
        # v10.5 布局修复：快捷操作栏收纳进横向滚动区——
        # 面板再窄也不会挤压重叠，放不下时出现横向滚动条
        scroll = QScrollArea()
        scroll.setObjectName("quickActionsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(48)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        quick_container = QWidget()
        quick_container.setObjectName("quickActionsContainer")
        quick_layout = QHBoxLayout(quick_container)
        quick_layout.setContentsMargins(12, 4, 12, 4)
        quick_layout.setSpacing(8)

        self.attach_btn = QPushButton("\U0001F4CE 附件")
        self.attach_btn.setObjectName("quickActionBtn")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setFixedHeight(28)
        self.attach_btn.clicked.connect(self._on_attach_file)
        quick_layout.addWidget(self.attach_btn)

        self.paste_btn = QPushButton("\U0001F4CB 粘贴")
        self.paste_btn.setObjectName("quickActionBtn")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.setFixedHeight(28)
        self.paste_btn.clicked.connect(self._on_paste_clipboard)
        quick_layout.addWidget(self.paste_btn)

        self.search_btn = QPushButton("\U0001F50D 搜索")
        self.search_btn.setObjectName("quickActionBtn")
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setFixedHeight(28)
        self.search_btn.clicked.connect(self._on_search_messages)
        quick_layout.addWidget(self.search_btn)

        self.emoji_btn = QPushButton("😊 表情")
        self.emoji_btn.setObjectName("quickActionBtn")
        self.emoji_btn.setCursor(Qt.PointingHandCursor)
        self.emoji_btn.setFixedHeight(28)
        self.emoji_btn.clicked.connect(self._on_toggle_emoji_panel)
        quick_layout.addWidget(self.emoji_btn)

        # 第四阶段：语音输入入口
        self.voice_btn = QPushButton("🎤 语音")
        self.voice_btn.setObjectName("voiceInputBtn")
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.setFixedHeight(28)
        self.voice_btn.setToolTip("语音输入（依赖 SpeechRecognition + 麦克风）")
        self.voice_btn.clicked.connect(self._on_voice_input)
        quick_layout.addWidget(self.voice_btn)

        # v1.2.2：拍照发图（配合多模态看图；仅拍照一张，不做监控）
        self.camera_btn = QPushButton("📷 拍照")
        self.camera_btn.setObjectName("quickActionBtn")
        self.camera_btn.setCursor(Qt.PointingHandCursor)
        self.camera_btn.setFixedHeight(28)
        self.camera_btn.setToolTip("调起摄像头拍一张，随消息以图片发送给 AI（需模型支持视觉）")
        self.camera_btn.clicked.connect(self._on_camera_capture)
        quick_layout.addWidget(self.camera_btn)

        # v1.3(P1-2): 区域截图直接问 —— 截图选区进附件条 + 预填引导，不自动发送；
        # 同入口供 P1-3 全局热键 Ctrl+Alt+S 与 P2-4 托盘「🖼 截图」复用。
        self.screenshot_btn = QPushButton("🖼 截图")
        self.screenshot_btn.setObjectName("quickActionBtn")
        self.screenshot_btn.setCursor(Qt.PointingHandCursor)
        self.screenshot_btn.setFixedHeight(28)
        self.screenshot_btn.setToolTip("划屏选区截图，作为图片问码铃（Ctrl+Alt+S / 托盘可触发）")
        self.screenshot_btn.clicked.connect(self.capture_screenshot)
        quick_layout.addWidget(self.screenshot_btn)

        # v1.3(P2-1): 小游戏 —— 她当荷官（纯确定性随机、零计分无数值）
        self.game_btn = QPushButton("🎲 小游戏")
        self.game_btn.setObjectName("quickActionBtn")
        self.game_btn.setCursor(Qt.PointingHandCursor)
        self.game_btn.setFixedHeight(28)
        self.game_btn.setToolTip("抛硬币 / 抽签 / 猜拳 / 21 点，和码铃玩一小局")
        self.game_btn.clicked.connect(self._open_mini_games)
        quick_layout.addWidget(self.game_btn)

        # v1.3(P2-2): 免提对话开关 —— 与既有「🎤 语音」并存（单次语音 = 弹窗，免提 = 连续对话）
        self.handsfree_btn = QPushButton("🎙 免提")
        self.handsfree_btn.setObjectName("handsfreeToggleBtn")
        self.handsfree_btn.setCursor(Qt.PointingHandCursor)
        self.handsfree_btn.setFixedHeight(28)
        self.handsfree_btn.setCheckable(True)
        self.handsfree_btn.setToolTip(
            "免提对话：开启后直接说话即可连续发消息，码铃会把回答念给你听\n"
            "说「暂停 / 结束对话 / 不说了」或开始敲键盘/动鼠标都会自动停下"
        )
        self.handsfree_btn.toggled.connect(self._on_handsfree_toggled)
        quick_layout.addWidget(self.handsfree_btn)

        # v1.4(B1b): 持续看屏开关（默认关；开启有成本确认弹窗 + 状态 chip）
        self.watch_btn = QPushButton("👀 看屏")
        self.watch_btn.setObjectName("watchToggleBtn")
        self.watch_btn.setCursor(Qt.PointingHandCursor)
        self.watch_btn.setCheckable(True)
        self.watch_btn.setFixedHeight(28)
        self.watch_btn.setToolTip(
            "持续看屏：开启后码铃周期看一下你的屏幕，能回答「这个报错为什么」、"
            "在检测到报错/异常时主动提醒；会额外消耗 token，可随时关闭（不落盘、不做行为统计）"
        )
        self.watch_btn.toggled.connect(self._on_watch_toggled)
        quick_layout.addWidget(self.watch_btn)

        # v1.4(B2): GUI 单步操作开关（开启后下一条消息被路由到「操作」，逐次授权执行）
        self.computer_btn = QPushButton("🖱 操作")
        self.computer_btn.setObjectName("computerToggleBtn")
        self.computer_btn.setCursor(Qt.PointingHandCursor)
        self.computer_btn.setCheckable(True)
        self.computer_btn.setFixedHeight(28)
        self.computer_btn.setToolTip(
            "单步操作：点亮后，下一条发给码铃的消息会被当成操作指令（如「点那个确定」「把这里填成 xxx」）；"
            "码铃先看清屏幕 → 弹窗给你看目标与预览 → 你「允许这一次 / 拒绝」才执行，绝不擅自乱点"
        )
        quick_layout.addWidget(self.computer_btn)

        # 给两个 checkable 快捷钮上主题色（开启 = 实底强调色，一眼可辨）
        try:
            from gui.utils import theme_color
            _accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
            _accent_l = theme_color(self.app_ctx, "accent_light", "#FFB6C1")
            _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
            _txt = theme_color(self.app_ctx, "text", "#4A4A4A")
            _sw_ss = (
                f"QPushButton#watchToggleBtn, QPushButton#computerToggleBtn {{"
                f"  background: transparent; color: {_accent};"
                f"  border: 1px solid {_accent}; border-radius: 12px;"
                f"  font-size: 12px; padding: 2px 12px;"
                f"}}"
                f"QPushButton#watchToggleBtn:checked, QPushButton#computerToggleBtn:checked {{"
                f"  background: {_accent}; color: #FFFFFF; border-color: {_accent};"
                f"}}"
                f"QPushButton#watchToggleBtn:hover, QPushButton#computerToggleBtn:hover {{"
                f"  background: {_bg_l}; color: {_txt};"
                f"}}"
            )
            self.watch_btn.setStyleSheet(_sw_ss)
            self.computer_btn.setStyleSheet(_sw_ss)
        except Exception:
            pass

        quick_layout.addStretch()
        scroll.setWidget(quick_container)
        parent_layout.addWidget(scroll)

    # ==================================================================
    # 信号连接
    # ==================================================================
    def _connect_signals(self) -> None:
        self._feedback_bars: list = []  # v1.6(P0-3): 未点击的反馈动作行追踪
        # v1.6(P0-4): 失败动作行 / 状态链追踪
        self._failure_row = None          # 错误气泡下的「🔄 重试 / ✏️ 改后重发」动作行
        self._failure_user_bubble = None  # 失败前最后一条 user 气泡（改后重发用）
        self._last_user_bubble = None     # 最近一条 user 气泡引用
        self._status_first_chunk = False  # 状态链：本轮是否已进入流式
        if self.chat_service is not None:
            self.chat_service.message_stream_started.connect(self._on_stream_started)
            self.chat_service.message_chunk_received.connect(self._on_chunk)
            self.chat_service.message_stream_finished.connect(self._on_stream_finished)
            self.chat_service.message_cancelled.connect(self._on_stream_cancelled)
            self.chat_service.thinking_indicator.connect(self._on_thinking)
            # v10.15: 真实错误冒泡显示（替代旧版「女仆 fallback」掩盖）
            self.chat_service.message_failed.connect(self._on_message_failed)
            # v1.1(agent): 工具轨迹事件
            self.chat_service.agent_tool_event.connect(self._on_agent_tool_event)
            # v1.5.0: 联网检索提示（流式气泡前的小字）
            self.chat_service.web_search_notice.connect(self._on_web_search_notice)
            # v1.6(P0-3): 反馈三键内容源 —— 主动气泡渲染后（proactive_message 已被
            # gui_session.message_added 链处理）挂动作行（不入会话存档）
            try:
                self.chat_service.proactive_feedback_ready.connect(self._on_proactive_feedback_ready)
            except Exception:
                pass
            # v1.1(agent): 修改类工具授权弹窗
            self.chat_service.agent_authorization_requested.connect(self._on_agent_authorization_requested)

        gui_session = getattr(self.app_ctx, "gui_session", None)
        if gui_session is not None:
            gui_session.message_added.connect(self._on_message_added)

        # Bug4: AI 气泡头像跟随当前角色 —— 初始取默认角色头像，订阅角色生效广播刷新
        self._current_role_avatar = ""
        try:
            from gui.pages.page_role import RoleManager
            _default_role = RoleManager().default_role
            if _default_role is not None:
                self._current_role_avatar = str(getattr(_default_role, "avatar", "") or "")
        except Exception:
            self._current_role_avatar = ""
        try:
            _rb = getattr(self.app_ctx, "role_bridge", None)
            if _rb is not None and hasattr(_rb, "role_changed"):
                _rb.role_changed.connect(self._on_role_avatar_changed)
        except Exception:
            pass

        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

        # v1.3(P1-1): TTS 朗读归属变化 -> 刷新气泡「朗读/停止」按钮态
        tts = getattr(self.app_ctx, "tts", None)
        if tts is not None and hasattr(tts, "state_changed"):
            try:
                tts.state_changed.connect(self._on_tts_state_changed)
            except Exception:
                pass

    # ==================================================================
    # 会话管理
    # ==================================================================
    def _publish_activity(self, state: Optional[str]) -> None:
        """v1.2(A-9/A-10): 活动态广播到 companion_bridge（thinking/focus/surprised/None）。

        设计（design-v12 D2 §3.2 广播约定）：聊天面板作为活动态呈现触发源，经
        bridge.note_activity 广播同一条 mood_changed —— 角落宠物 / 气泡头像 /
        首页形象 / 侧栏同步更新；无 bridge 或方法缺失时静默空转（不崩）。
        """
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None:
            return
        note = getattr(bridge, "note_activity", None)
        if not callable(note):
            return
        try:
            note(state)
        except Exception:
            pass

    def _load_active_session(self) -> None:
        """加载活跃会话并显示其消息。"""
        if self.session_manager is None:
            return
        session = self.session_manager.ensure_active()
        self._current_session_id = session.id
        self._refresh_session_list()
        self._load_session_messages(session)
        # v1.5.1(切角色人设残留): 启动加载也让 LLM 历史对齐显示会话
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        self._apply_group_placeholder(session)

    def _refresh_session_list(self) -> None:
        """刷新会话列表显示。"""
        if self.session_manager is None:
            return
        self.session_list.clear()
        for session in self.session_manager.all_sessions():
            # v1.7(F10a): 群聊会话带 👥 群标签（旧单聊会话零影响）
            prefix = "👥 " if _is_group_session(session) else ""
            item = QListWidgetItem(f"{prefix}{session.name} ({session.message_count})")
            item.setData(Qt.UserRole, session.id)
            self.session_list.addItem(item)
            if session.id == self._current_session_id:
                self.session_list.setCurrentItem(item)
        if self._tab_mode:
            self._sync_tabs()

    def _load_session_messages(self, session: ChatSession) -> None:
        """将会话消息加载到消息列表。"""
        # v1.1(B2): 切换会话时清掉旧会话残留的工具轨迹
        try:
            self.tool_trace_panel.reset()
            self._agent_trace_active = False
        except Exception:
            pass
        # v1.6(P0-4): 切换会话时清掉旧会话残留的失败动作行引用
        self._clear_failure_actions()
        # 清空现有消息气泡（保留 stretch 和 thinking_indicator）
        for i in range(self.messages_layout.count() - 2, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None and not isinstance(widget, ThinkingIndicator):
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()

        self._last_role = None
        self._last_speaker_id = None
        for msg in session.messages:
            if msg.role in ("user", "assistant"):
                atts = (msg.metadata or {}).get("attachments") if msg.metadata else None
                # v1.7(F10a): 群聊 assistant 消息带发言者（气泡名字+头像渲染）
                speaker_id = (msg.metadata or {}).get("speaker_id") if msg.metadata else None
                self._add_message_bubble(msg.role, msg.content, attachments=atts,
                                         speaker_id=speaker_id)
        self._scroll_to_bottom()

    def _on_session_selected(self, item: QListWidgetItem) -> None:
        """切换会话。"""
        session_id = item.data(Qt.UserRole)
        self._switch_to_session(session_id)

    def _switch_to_session(self, session_id: str) -> None:
        """切换活跃会话（同时供会话列表点击和标签页切换调用）。"""
        if not session_id or session_id == self._current_session_id:
            return
        if self.session_manager is None:
            return
        self.session_manager.set_active(session_id)
        session = self.session_manager.get_session(session_id)
        if session is not None:
            self._current_session_id = session_id
            self.title_label.setText(session.name)
            self._load_session_messages(session)
            # v1.5.1(切角色人设残留): LLM 历史跟随显示会话（旧会话的对话不再泄漏）
            self._sync_llm_context(session)
            self._apply_group_placeholder(session)
            if self._tab_mode and session_id not in self._open_tab_ids:
                self._open_tab_ids.append(session_id)
                self._sync_tabs()

    def _on_new_session(self) -> None:
        """新建会话（通过侧栏 + 按钮触发，默认名「新会话」，不弹对话框）。"""
        if self.session_manager is None:
            return
        name = "新会话"
        session = self.session_manager.create_session(name)
        self._current_session_id = session.id
        self._refresh_session_list()
        self._clear_messages()
        # v1.5.1(切角色人设残留): 新会话 = 干净的 LLM 历史（空 entries → 仅当前
        # 角色 system）。此前 LLM 历史跨显示会话持续累积，旧角色对话泄漏进新会话。
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        if self._tab_mode and session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
            self._sync_tabs()

    def _sync_llm_context(self, session) -> None:
        """v1.5.1(切角色人设残留): 让 LLM 会话历史跟随活跃显示会话。

        根因：显示会话（session_manager）与 LLM 会话（app_ctx.session）是两套
        历史 —— LLM history 自启动起持续累积、跨显示会话/角色切换从不清空，
        旧角色（如鲸鱼娘）的对话持续带偏模型，且"新会话"也携带旧上下文。
        本方法以显示会话的 user/assistant 消息重建 LLM 历史（首条 = 当前角色
        system，人设来源唯一）。重建走 session.replace_history（直赋值，
        不触发 GuiChatSession.message_added，气泡不会被重放）。

        v1.7(F10a/D-V17-06): 群聊会话隔离分支 —— 群聊消息**绝不写入** LLM
        对齐历史（R-J④⑤ / 共享知识 26），仅清空 LLM 历史防跨会话泄漏；
        单聊路径零改动。
        """
        if session is None:
            return
        llm_session = getattr(self.app_ctx, "session", None)
        if llm_session is None or not callable(getattr(llm_session, "replace_history", None)):
            return
        if _is_group_session(session):
            try:
                llm_session.replace_history([])
            except Exception as exc:
                logger.debug("群聊会话 LLM 历史清空失败（不影响会话切换）: %s", exc)
            return
        entries: List[dict] = []
        for msg in session.messages:
            if msg.role not in ("user", "assistant"):
                continue
            content = msg.content or ""
            # 附件按发送时的摘要规则回填（与 _collect_ui_history_before 一致）
            atts = (msg.metadata or {}).get("attachments") if msg.metadata else None
            if msg.role == "user" and atts:
                att_lines = "\n".join(
                    f"[附件] {a.get('name', '')} ({a.get('size', 0)} bytes)"
                    for a in atts
                )
                content = (content + "\n" if content else "") + att_lines
            entries.append({"role": msg.role, "content": content})
        try:
            llm_session.replace_history(entries)
        except Exception as exc:
            logger.debug("LLM 历史对齐失败（不影响会话切换）: %s", exc)

    def _show_session_menu(self, pos) -> None:
        """会话右键菜单（空白处 = 新建群聊入口）。"""
        item = self.session_list.itemAt(pos)
        if item is None:
            # v1.7(F10a): 空白处右键 → 最小建群入口（选 2-3 个已建角色）
            menu = QMenu(self)
            new_group_action = menu.addAction("👥 新建群聊")
            action = menu.exec_(self.session_list.mapToGlobal(pos))
            if action == new_group_action:
                self._on_new_group_session()
            return
        session_id = item.data(Qt.UserRole)
        session = self.session_manager.get_session(session_id) if self.session_manager else None
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        # v1.7(F10b): 群聊会话专属「群聊设置」（成员查看/改名/解散）
        group_settings_action = menu.addAction("👥 群聊设置") \
            if session is not None and _is_group_session(session) else None
        clear_action = menu.addAction("清空消息")
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.session_list.mapToGlobal(pos))

        if action == rename_action:
            self._rename_session(session_id)
        elif group_settings_action is not None and action == group_settings_action:
            self._on_group_settings(session_id)
        elif action == clear_action:
            self._clear_session(session_id)
        elif action == delete_action:
            self._delete_session(session_id)

    def _on_group_settings(self, session_id: str) -> None:
        """v1.7(F10b): 群聊设置（最小集）—— 查看成员 / 改名 / 解散确认。

        R-J③：成员只读展示（人员增减留 v1.7.x，避免运行中改群composition
        与历史改写语义冲突）；解散 = 删除会话（复用既有删除链，含文件清理）。
        """
        if self.session_manager is None:
            return
        session = self.session_manager.get_session(session_id)
        if session is None or not _is_group_session(session):
            return
        roles = self._group_member_roles(session)
        member_names = [getattr(roles.get(rid), "name", "（已删除角色）")
                        for rid in (session.metadata or {}).get("members", [])]
        box = QMessageBox(self)
        box.setWindowTitle("群聊设置")
        box.setText(f"群聊：{session.name}\n成员（{len(member_names)}/3）：\n  · "
                    + "\n  · ".join(member_names))
        rename_btn = box.addButton("✏️ 改名", QMessageBox.ActionRole)
        disband_btn = box.addButton("💥 解散群聊", QMessageBox.DestructiveRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is rename_btn:
            self._rename_session(session_id)
        elif clicked is disband_btn:
            confirm = QMessageBox.question(
                self, "解散群聊",
                f"确定要解散「{session.name}」吗？\n群聊记录将一并删除，此操作不可恢复。",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm == QMessageBox.Yes:
                self._delete_session(session_id)

    def _on_new_group_session(self) -> None:
        """v1.7(F10a): 新建群聊 —— 选 2-3 个已建角色的最小选择框（R-J③ 成员 ≤3）。"""
        if self.session_manager is None:
            return
        try:
            from gui.pages.page_role import RoleManager
            roles = list(RoleManager().all_roles())
        except Exception as exc:
            logger.warning("角色列表读取失败: %s", exc)
            roles = []
        if len(roles) < 2:
            QMessageBox.information(self, "新建群聊", "至少需要 2 个已创建的角色才能建群哦~")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("新建群聊（选择 2-3 个成员）")
        dialog.setMinimumWidth(280)
        lay = QVBoxLayout(dialog)
        lay.addWidget(QLabel("选择群聊成员（最多 3 个）："))
        checks: List[QCheckBox] = []
        for role in roles:
            cb = QCheckBox(role.name or role.id)
            cb.setParent(dialog)
            lay.addWidget(cb)
            checks.append(cb)
        hint = QLabel("")
        hint.setStyleSheet("QLabel { color: #FF6B9D; font-size: 11px; }")
        lay.addWidget(hint)

        def _validate() -> None:
            n = sum(1 for c in checks if c.isChecked())
            ok_btn.setEnabled(2 <= n <= 3)
            hint.setText("" if n <= 3 else "最多选择 3 个成员")
            if n < 2:
                hint.setText("至少选择 2 个成员")

        ok_btn = QPushButton("创建群聊")
        ok_btn.setEnabled(False)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dialog.reject)
        for cb in checks:
            cb.toggled.connect(_validate)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        lay.addLayout(btns)

        if dialog.exec_() != QDialog.Accepted:
            return
        member_ids = [r.id for r, c in zip(roles, checks) if c.isChecked()][:3]
        if len(member_ids) < 2:
            return
        # v1.7(F10b): 无@策略全局默认读 GuiConfig（会话级 metadata 可覆盖）
        gui_cfg = getattr(self.app_ctx, "config", None)
        policy = str(getattr(gui_cfg, "group_no_at_policy", GROUP_DEFAULT_NO_AT_POLICY)
                     or GROUP_DEFAULT_NO_AT_POLICY)
        session = self.session_manager.create_group_session(
            "群聊", member_ids, no_at_policy=policy
        )
        self._current_session_id = session.id
        self._refresh_session_list()
        self._load_session_messages(session)
        # v1.7(F10a): 群聊隔离 —— LLM 对齐历史保持干净（不写群聊消息）
        self._sync_llm_context(session)
        self.title_label.setText(session.name)
        self._apply_group_placeholder(session)
        if self._tab_mode and session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
            self._sync_tabs()

    def _rename_session(self, session_id: str) -> None:
        session = self.session_manager.get_session(session_id) if self.session_manager else None
        if session is None:
            return
        name, ok = QInputDialog.getText(self, "重命名会话", "新名称:", text=session.name)
        if ok and name.strip():
            self.session_manager.rename_session(session_id, name.strip())
            self._refresh_session_list()
            if session_id == self._current_session_id:
                self.title_label.setText(name.strip())
            if self._tab_mode:
                self._sync_tabs()

    def _clear_session(self, session_id: str) -> None:
        if self.session_manager is None:
            return
        reply = QMessageBox.question(
            self, "清空消息", "确定要清空该会话的所有消息吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.session_manager.clear_session(session_id)
            if session_id == self._current_session_id:
                self._clear_messages()
            self._refresh_session_list()

    def _delete_session(self, session_id: str) -> None:
        if self.session_manager is None:
            return
        reply = QMessageBox.question(
            self, "删除会话", "确定要删除该会话吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # 先从标签页打开列表中移除（删除是删除，关闭 tab 是另一回事）
            if session_id in self._open_tab_ids:
                self._open_tab_ids.remove(session_id)
            self.session_manager.delete_session(session_id)
            if session_id == self._current_session_id:
                self._clear_messages()
                active = self.session_manager.active_session
                if active is not None:
                    self._current_session_id = active.id
                    self.title_label.setText(active.name)
                    self._load_session_messages(active)
                    if self._tab_mode and active.id not in self._open_tab_ids:
                        self._open_tab_ids.append(active.id)
                else:
                    self._current_session_id = None
                    self.title_label.setText("聊天")
            self._refresh_session_list()
            if self._tab_mode:
                self._sync_tabs()

    def _clear_messages(self) -> None:
        """清空消息列表。"""
        # v1.1(B2): 清空消息时同步清掉工具轨迹
        try:
            self.tool_trace_panel.reset()
            self._agent_trace_active = False
        except Exception:
            pass
        # v1.6(P0-4): 清空消息时同步清掉失败动作行引用（widget 将被 deleteLater）
        self._clear_failure_actions()
        for i in range(self.messages_layout.count() - 2, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is not None:
                widget = item.widget()
                if widget is not None and not isinstance(widget, ThinkingIndicator):
                    self.messages_layout.removeWidget(widget)
                    widget.deleteLater()
        self._last_role = None
        self._last_speaker_id = None

    def _on_toggle_sidebar(self) -> None:
        """折叠/展开会话列表。"""
        visible = self.session_sidebar.isVisible()
        self.session_sidebar.setVisible(not visible)
        self.toggle_sidebar_btn.setText("◀" if not visible else "▶")

    # ==================================================================
    # 消息处理
    # ==================================================================
    def _on_send(self) -> None:
        """发送消息（支持纯文本、附件、或两者都有）。"""
        text = self.input_edit.toPlainText().strip()
        attachments = self.attachment_bar.attachments()
        if not text and not attachments:
            return
        # v1.7(F10a/D-V17-06): 群聊会话 → 群聊发言调度（独立路径，不进单聊链）
        if _is_group_session(self._current_group_session()):
            self.input_edit.clear()
            self._on_group_send(text, attachments)
            return
        # v1.4(B2): 「🖱 操作」点亮时，下一条纯文本消息路由给单步操作（单次即熄）
        computer_btn = getattr(self, "computer_btn", None)
        if computer_btn is not None and computer_btn.isChecked() and text and not attachments:
            self._route_computer_request(text)
            return
        self.input_edit.clear()
        bubble_text = text if text else "📎 附件"

        # v1.6(P0-3): 用户开新话头 → 移除未点击的反馈动作行（防堆积）
        self._clear_feedback_bars()
        # v1.6(P0-4): 用户开新话头 → 移除上一条失败动作行（用户已选择继续前进）
        self._clear_failure_actions()

        # v1.4(B1b): 看屏期间 —— 按屏提问 / 被动命中 → 把最近帧作为内存附件随消息发送
        screen_att = None
        if self.chat_service is not None and not attachments and getattr(self, "_watch_svc", None) is not None:
            try:
                want_ask = False
                bar = getattr(self, "screen_watch_bar", None)
                if bar is not None and bar.ask_pending():
                    want_ask = True
                elif self._watch_svc.is_running() and self._screen_intent_hit(text):
                    want_ask = True
                if want_ask:
                    screen_att = self._attach_screen_frame()
                    bar.set_ask_pending(False) if bar is not None else None
                    if screen_att:
                        self.status_label.setText("已附上当前屏幕（内存帧，不落盘）")
            except Exception:
                screen_att = None

        extra_attachments = list(attachments)
        if screen_att:
            extra_attachments.append(screen_att)
            self._screen_pending_token = True  # 流结束补记 token
        self._add_message_bubble("user", bubble_text, attachments=extra_attachments)
        self.attachment_bar.clear()
        self._save_current_session()
        # v10.15: 用共享 helper 拼装附件 payload（文本 ≤50KB 直入 prompt，二进制做诚实标注）
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(text, attachments)

        # v1.1(B2): 新一次用户消息：清空上一轮工具轨迹；若处于 Agent 模式则预备收集
        self._reset_agent_trace()

        if self.chat_service is not None:
            # v1.4.7: 任务模式时 task_type="managed_task"，否则由 chat_service 内部根据 agent_mode 决定
            task_type = "managed_task" if self._is_task_mode() else "chat"
            # R1: UI 直插气泡为唯一 user 渲染入口——抑制服务层 message_added 回声
            self.chat_service.send_message(send_text, task_type=task_type, suppress_echo=True, attachments=extra_attachments)
            # v1.6(P0-4/T4): 发送状态链第一拍 ——「发送中…」
            self._status_first_chunk = False
            self.status_label.setText("发送中…")
        else:
            self._add_message_bubble("assistant", "哎呀，女仆的聊天服务还没准备好呢... 请主人稍等~")

    def _reset_agent_trace(self) -> None:
        """清空上一轮工具轨迹；若处于 Agent 模式则标记为本轮预备收集。

        面板本身保持隐藏，直到第一个 agent 事件到达才 show（避免空白卡片）。
        """
        try:
            panel = getattr(self, "tool_trace_panel", None)
            if panel is not None:
                panel.reset()
            agent_mode = False
            if self.chat_service is not None:
                agent_mode = bool(self.chat_service.is_agent_mode())
            self._agent_trace_active = agent_mode
        except Exception:
            self._agent_trace_active = False

    # ==================================================================
    # v1.7(F10a/F10b/D-V17-06): 群聊发言调度与渲染（显示会话层）
    # ==================================================================
    def _current_group_session(self):
        """v1.7(F10a): 当前活跃显示会话（群聊判定用；单聊返回该会话但由调用方判定）。"""
        if self.session_manager is None or not self._current_session_id:
            return None
        return self.session_manager.get_session(self._current_session_id)

    def _group_role_by_id(self, role_id: Optional[str]):
        """v1.7(F10a): RoleManager 只读解析角色（头像/名字渲染；仅群聊路径调用）。"""
        if not role_id:
            return None
        try:
            from gui.pages.page_role import RoleManager
            return RoleManager().get_role(role_id)
        except Exception:
            return None

    def _group_member_roles(self, session) -> dict:
        """v1.7(F10a): 群成员 id→Role 只读映射。"""
        if session is None:
            return {}
        try:
            from gui.pages.page_role import RoleManager
            ids = set((session.metadata or {}).get("members") or [])
            return {r.id: r for r in RoleManager().all_roles() if r.id in ids}
        except Exception:
            return {}

    def _apply_group_placeholder(self, session) -> None:
        """v1.7(F10a): 群聊/单聊输入框占位提示切换（零逻辑影响）。"""
        try:
            # v1.7(F10b): 切换会话时收起 @补全浮层（防旧会话成员名单残留）
            self._hide_mention_popup()
            if session is not None and _is_group_session(session):
                self.input_edit.setPlaceholderText("在群里 @角色名 说话...")
            else:
                self.input_edit.setPlaceholderText("和女仆说点什么吧... （或拖拽文件）")
        except Exception:
            pass

    def _on_group_send(self, text: str, attachments: list) -> None:
        """v1.7(F10 自由发言): 群聊发送路径 —— user 气泡入显示会话 → 一轮调度。

        - @点名（显式覆盖，最高优先级）：被 @ 角色必回；
        - 未 @：轻量 LLM 调度决定本轮接话者（1-2 人串行接话），
          silent 策略则全员沉默等待 @（消息照常入会话，零回复）；
        - 完全不触碰 app_ctx.session（LLM 对齐历史）与 v1.5.1 对齐链。
        """
        session = self._current_group_session()
        if session is None or self.chat_service is None:
            return
        self._hide_mention_popup()
        self._clear_feedback_bars()
        self._clear_failure_actions()
        bubble_text = text if text else "📎 附件"
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(text, attachments)
        self._add_message_bubble("user", bubble_text, attachments=list(attachments) or None)
        self._save_current_session()
        self._reset_agent_trace()
        self._status_first_chunk = False
        member_roles = self._group_member_roles(session)
        try:
            mode = self.chat_service.send_group_turn(send_text, session, member_roles)
        except Exception as exc:
            logger.exception("群聊一轮调度失败: %s", exc)
            mode = "silent"
        if mode == "silent":
            # silent 策略：消息已入会话，零回复（诚实呈现「等你点名」）
            self.status_label.setText("已发送。本群为沉默模式，@角色名 才会回复~")
        else:
            self.status_label.setText("")

    def _on_message_added(self, role: str, content: str) -> None:
        # v1.7(F10b): proactive 边界收口 —— 群聊会话激活时，单聊链的主动消息
        #（proactive_ask 等写 LLM 会话触发 message_added 的路径）不入群聊面板/
        # 不落群聊显示会话（防被当成无 speaker 的「成员」发言污染历史改写）。
        # LLM 历史中的该条由下次切回单聊的 replace_history 重建自然收敛。
        current = self._current_group_session()
        if current is not None and _is_group_session(current) \
                and role == "assistant" \
                and getattr(self, "_current_ai_bubble", None) is None:
            return
        # R1: 发送方已抑制回声（面板/独立窗口直插气泡）时跳过，避免双气泡
        if role == "user":
            service = self.chat_service
            if service is not None and getattr(service, "echo_suppressed", False):
                return
        # R1: 流式期间 assistant 回声跳过——流式气泡已是展示载体；
        # 仅非流式（mock / 非流式 API）回放路径经此处渲染
        if role == "assistant" and getattr(self, "_current_ai_bubble", None) is not None:
            return
        if role in ("user", "assistant"):
            self._add_message_bubble(role, content)
            self._save_current_session()

    def _on_role_avatar_changed(self, role_id: str, avatar_path: str, base_expr: str) -> None:
        """Bug4: 角色生效广播 → 缓存头像路径，新 AI 气泡用角色头像（历史气泡不追溯）。"""
        self._current_role_avatar = str(avatar_path or "")

    def _add_message_bubble(
        self, role: str, content: str, attachments: Optional[List[dict]] = None,
        error_style: bool = False, speaker_id: Optional[str] = None,
    ) -> None:
        is_consecutive = self._last_role == role
        # v1.7(F10a): 群聊中不同发言者的连续 assistant 气泡不算连续（保留名字/头像）
        if role == "assistant" and speaker_id is not None:
            is_consecutive = is_consecutive and self._last_speaker_id == speaker_id
        # v1.7(F10a): 群聊发言者 → 头像/名字从 RoleManager 只读解析
        speaker_role = self._group_role_by_id(speaker_id) \
            if (speaker_id and role == "assistant") else None
        avatar_path = self._current_role_avatar
        if speaker_role is not None:
            avatar_path = str(getattr(speaker_role, "avatar", "") or "") or avatar_path
        bubble = MessageBubble(
            role, content,
            is_consecutive=is_consecutive,
            # 大气化：气泡最大宽度从 280 提到 720，对齐 WorkBuddy/豆包现代 AI 聊天观感
            max_bubble_width=DEFAULT_MAX_BUBBLE_WIDTH,
            app_context=self.app_ctx,
            attachments=attachments,
            error_style=error_style,  # v10.15: 错误气泡红框
            # Bug4: AI 气泡传入当前角色头像（无则回落女仆表情头像）
            # v1.7(F10a): 群聊气泡优先用发言角色头像
            avatar_path=avatar_path if role == "assistant" else None,
        )
        if speaker_role is not None:
            try:
                bubble.speaker_id = speaker_id  # _save_current_session 持久化用
                name_label = bubble.findChild(QLabel, "nameLabel")
                if name_label is not None:
                    name_label.setText(speaker_role.name or "成员")
            except Exception:
                pass
        bubble.delete_requested.connect(lambda: self._remove_bubble(bubble))
        bubble.edit_requested.connect(lambda b=bubble: self._on_edit_requested(b))
        bubble.regenerate_requested.connect(lambda b=bubble: self._on_regenerate_requested(b))
        # v1.3(P1-1): 朗读按钮 -> 本面板接 TTS（只朗读 AI 文本）
        bubble.read_aloud_requested.connect(lambda b=bubble: self._on_bubble_read_aloud(b))
        # v1.3(P2-3): 右键收藏高光回忆（AI 与用户气泡均可）
        bubble.favorite_requested.connect(
            lambda role, text, meta, b=bubble: self._on_favorite_requested(b, role, text, meta)
        )
        idx = self.messages_layout.count() - 2
        if idx < 0:
            idx = self.messages_layout.count() - 1
        self.messages_layout.insertWidget(idx, bubble)
        self._last_role = role
        self._last_speaker_id = speaker_id if role == "assistant" else None
        # v1.6(P0-4/T2): 记录最近一条 user 气泡（失败动作行「改后重发」锚点用）
        if role == "user":
            self._last_user_bubble = bubble
        self._scroll_to_bottom()
        return bubble

    def add_message(
        self, role: str, content: str, attachments: Optional[List[dict]] = None
    ) -> None:
        """外部调用：添加消息。"""
        self._add_message_bubble(role, content, attachments=attachments)
        self._save_current_session()

    def _remove_bubble(self, bubble: MessageBubble) -> None:
        self.messages_layout.removeWidget(bubble)
        bubble.deleteLater()
        self._save_current_session()

    def _save_current_session(self) -> None:
        """将当前消息保存到活跃会话。

        R11: 增量同步——按序对位更新，命中前缀的消息对象原位改 content/metadata，
        保留 id/timestamp/model/tokens 等既有字段；仅新增消息才生成新 ChatMessage。
        """
        if self.session_manager is None or self._current_session_id is None:
            return
        session = self.session_manager.get_session(self._current_session_id)
        if session is None:
            return
        # 先快照当前气泡（R10 同理：避免边遍历边删引发的不一致）
        bubbles: List[MessageBubble] = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                bubbles.append(widget)
        # 会话中多出的尾部消息（截断/删除）直接裁掉
        if len(session.messages) > len(bubbles):
            del session.messages[len(bubbles):]
        # 逐条对位同步
        for i, widget in enumerate(bubbles):
            atts = widget.get_attachments()
            metadata = {"attachments": atts} if atts else {}
            text = widget.get_text()
            # v1.7(F10a): 群聊发言者归属持久化（气泡 attr → 存量消息 metadata 均可来源）
            speaker_id = getattr(widget, "speaker_id", None)
            if not speaker_id and i < len(session.messages):
                speaker_id = (session.messages[i].metadata or {}).get("speaker_id")
            if speaker_id and widget.role == "assistant":
                metadata["speaker_id"] = speaker_id
            if i < len(session.messages):
                msg = session.messages[i]
                if msg.role == widget.role:
                    if msg.content != text or msg.metadata != metadata:
                        msg.content = text
                        msg.metadata = metadata
                else:
                    # 角色错位（编辑后重排）：整条替换
                    session.messages[i] = ChatMessage(
                        role=widget.role, content=text, metadata=metadata
                    )
            else:
                session.messages.append(
                    ChatMessage(role=widget.role, content=text, metadata=metadata)
                )
        session.updated_at = datetime.now()
        self.session_manager.save_active()
        self._refresh_session_list()

    # ==================================================================
    # 流式输出
    # ==================================================================
    def _on_stream_started(self) -> None:
        self._stream_buffer = ""
        self._current_ai_bubble: Optional[MessageBubble] = None
        self.stop_btn.setVisible(True)
        self.send_btn.setEnabled(False)
        # v1.6(P0-4/T4): 状态链第二拍 —— 模型已响应（思考拍在 _on_thinking）
        try:
            self.status_label.setText("模型响应中…")
        except Exception:
            pass
        # v1.2(A-9/A-10): 开始回复 -> 活动态 thinking（宠物/气泡头像等广播）
        self._publish_activity("thinking")

    def _on_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        # v1.6(P0-4/T4): 状态链第三拍 —— 首个增量到达 →「正在回复…」
        if not getattr(self, "_status_first_chunk", False):
            self._status_first_chunk = True
            try:
                self.status_label.setText("正在回复…")
            except Exception:
                pass
        if self._current_ai_bubble is None:
            is_consecutive = self._last_role == "assistant"
            # v1.7(F10a): 群聊流式气泡带发言者头像+名字（发言者由 service 调度提供）
            speaker_id = None
            if _is_group_session(self._current_group_session()):
                speaker_id = getattr(self.chat_service, "current_group_speaker", None)
                if speaker_id and is_consecutive:
                    is_consecutive = self._last_speaker_id == speaker_id
            speaker_role = self._group_role_by_id(speaker_id) if speaker_id else None
            avatar_path = self._current_role_avatar
            if speaker_role is not None:
                avatar_path = str(getattr(speaker_role, "avatar", "") or "") or avatar_path
            self._current_ai_bubble = MessageBubble(
                "assistant", self._stream_buffer,
                is_consecutive=is_consecutive,
                max_bubble_width=DEFAULT_MAX_BUBBLE_WIDTH,
                app_context=self.app_ctx,
                # Bug4: 流式 AI 气泡同样用当前角色头像
                # v1.7(F10a): 群聊流式气泡用发言角色头像
                avatar_path=avatar_path,
            )
            if speaker_role is not None:
                try:
                    self._current_ai_bubble.speaker_id = speaker_id
                    name_label = self._current_ai_bubble.findChild(QLabel, "nameLabel")
                    if name_label is not None:
                        name_label.setText(speaker_role.name or "成员")
                except Exception:
                    pass
            # v1.3(P1-1): 流式气泡同样接朗读（只朗读 AI 文本）
            self._current_ai_bubble.read_aloud_requested.connect(
                lambda b=self._current_ai_bubble: self._on_bubble_read_aloud(b)
            )
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, self._current_ai_bubble)
            self._last_role = "assistant"
            self._last_speaker_id = speaker_id
        else:
            self._current_ai_bubble.update_text(self._stream_buffer)
        self._scroll_to_bottom()

    def _on_stream_finished(self, full_text: str, usage: dict) -> None:
        # v1.4(B1b): 本轮回传了屏幕帧 → 把用量补记进看屏 chip（成本可见）
        self._settle_screen_round_tokens(usage)
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 状态链收尾 —— 清状态；成功 → 清残留失败动作行
        self._status_first_chunk = False
        self._clear_failure_actions()
        # v1.2.3(无焦虑红线): 聊天面板不再展示逐条/累计 token（数值焦虑）；
        # 累计用量仍由 session.add_usage 记账，只在首页 Token 卡呈现。
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 回复完成 -> 回落心情态（活动态结束）
        self._publish_activity(None)
        # v1.1(B2): Agent 流结束（含中途取消）→ 轨迹收起为可折叠摘要
        try:
            if self._agent_trace_active:
                trace = getattr(self, "tool_trace_panel", None)
                if trace is not None:
                    if trace.has_events():
                        hint = "已取消" if (usage or {}).get("cancelled") else "执行结束"
                        trace.finish(hint)
                    else:
                        # 没有跑出任何轨迹（如演示模式/立即失败）：不留空卡片
                        trace.reset()
                self._agent_trace_active = False
        except Exception:
            self._agent_trace_active = False
        # v1.3(P2-2): 语音消息的回复流结束 -> 免提读回复/回到 listening
        self._hf_resume_after_reply(full_text or "")
        self._save_current_session()
        # v1.7(F10): 串行接话由 service 队列驱动（_on_group_stream_finished 推进），
        # 面板只负责渲染/落盘，无需再触发下一位

    def _on_stream_cancelled(self) -> None:
        self._settle_screen_round_tokens({})
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 取消 → 状态清除（取消不算失败，失败动作行一并收走）
        self._status_first_chunk = False
        self._clear_failure_actions()
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 中止 -> 回落心情态
        self._publish_activity(None)
        self._add_message_bubble("assistant", "生成已停止~")
        # v1.3(P2-2): 免提语音的回复被取消 -> 放行回 listening
        self._hf_resume_after_reply("")
        self._save_current_session()

    def _on_thinking(self, active: bool) -> None:
        if active:
            self.thinking_indicator.start()
        else:
            self.thinking_indicator.stop()
        # v1.6(P0-4/T4): 状态链第二拍 ——「正在思考…」（自然不机械；
        # 已进入流式时 thinking(False) 不回写，保持「正在回复…」到完成清空）
        # v1.9(C/D-V19-03): 去「女仆」自称残留，改中性表述。
        if active:
            self.status_label.setText("正在思考…")
        elif not getattr(self, "_status_first_chunk", False):
            self.status_label.setText("")

    def _on_message_failed(self, error: str) -> None:
        """v10.15: API 错误冒泡 —— 真实展示错误，不再以女仆语气掩盖。

        v1.6(P0-4/T2/D-V16-07): 失败保留链 UI 入口 —— 数据层 user 消息早已保留
        （_launch_worker 先写 session 后调 API，失败不回滚），此处补动作行：
        错误气泡（红边）之下挂「🔄 重试 / ✏️ 改后重发」。
        """
        self._settle_screen_round_tokens({})
        self._current_ai_bubble = None
        self._stream_buffer = ""
        # v1.6(P0-4/T4): 失败 → 状态清除（动作行承接后续）
        self._status_first_chunk = False
        self.status_label.setText("")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        # v1.2(A-9/A-10): 失败同样结束活动态
        self._publish_activity(None)
        # v1.1(B2): Agent 中途出错 → 轨迹收起为「执行中断」摘要
        try:
            if self._agent_trace_active:
                trace = getattr(self, "tool_trace_panel", None)
                if trace is not None:
                    if trace.has_events():
                        trace.finish("执行中断")
                    else:
                        trace.reset()
                self._agent_trace_active = False
        except Exception:
            self._agent_trace_active = False
        # 错误以 assistant 气泡呈现（红色加重），明确告诉用户是失败而非助手回复
        err_bubble = self._add_message_bubble("assistant", error, error_style=True)
        # v1.7(F10a): 群聊失败 → 不挂重试动作行（重试走单聊链，
        # 会写 session.history，群聊禁入，R-J 隔离）；发言者由 service 复位
        if _is_group_session(self._current_group_session()):
            self.status_label.setText("群聊回复失败，请在输入框重新发送~")
        else:
            # v1.6(P0-4/T2): 错误气泡之下挂失败动作行（🔄 重试 / ✏️ 改后重发）
            self._show_failure_actions(err_bubble)
        # v1.3(P2-2): 语音消息发送失败 -> 放行回 listening（避免卡在 sending）
        self._hf_resume_after_reply("")
        self._save_current_session()

    # ==================================================================
    # v1.6(P0-4/T2/D-V16-07): 失败保留动作行（🔄 重试 / ✏️ 改后重发）
    # 数据层 user 消息在失败时不回滚（_launch_worker 先写后调 API）——
    # 重试走 ChatService.retry_last_failure（skip_history_write 幂等，
    # 切勿改走 send_message 会重复入库）；改后重发走既有编辑截断链。
    # ==================================================================
    def _show_failure_actions(self, anchor_bubble=None) -> None:
        """错误气泡之后插入动作行；引用对 (user_bubble, row) 保留失败现场。"""
        try:
            from gui.qt_compat import QWidget as _QWidget
            row = _QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(8, 0, 8, 6)
            lay.setSpacing(8)
            try:
                from gui.utils import theme_color
                _accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
                _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
            except Exception:
                _accent, _bg_l = "#FF6B9D", "#FFF0F3"
            _btn_ss = (
                "QPushButton {"
                f"  background: transparent; color: {_accent};"
                f"  border: 1px solid {_accent}; border-radius: 12px;"
                "  font-size: 12px; padding: 3px 12px;"
                "}"
                "QPushButton:hover {"
                f"  background: {_bg_l};"
                "}"
            )
            retry_btn = QPushButton("🔄 重试")
            retry_btn.setCursor(Qt.PointingHandCursor)
            retry_btn.setFixedHeight(26)
            retry_btn.setStyleSheet(_btn_ss)
            retry_btn.clicked.connect(self._on_retry_failed)
            edit_btn = QPushButton("✏️ 改后重发")
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.setFixedHeight(26)
            edit_btn.setStyleSheet(_btn_ss)
            edit_btn.clicked.connect(self._on_edit_resend_failed)
            lay.addWidget(retry_btn)
            lay.addWidget(edit_btn)
            lay.addStretch()
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, row)
            self._failure_row = row
            # 失败现场引用对：最近一条 user 气泡（改后重发的截断锚点）
            ub = getattr(self, "_last_user_bubble", None)
            self._failure_user_bubble = ub
            self._scroll_to_bottom()
        except Exception:
            self._failure_row = None
            self._failure_user_bubble = None

    def _clear_failure_actions(self) -> None:
        """移除失败动作行（重试成功 / 用户开新话头 / 取消 / 会话切换时）。"""
        row = getattr(self, "_failure_row", None)
        if row is not None:
            try:
                self.messages_layout.removeWidget(row)
                row.deleteLater()
            except RuntimeError:
                pass
            except Exception:
                pass
        self._failure_row = None
        self._failure_user_bubble = None

    def _on_retry_failed(self) -> None:
        """🔄 重试：chat_service.retry_last_failure()（skip_history_write 幂等）。"""
        if self.chat_service is None:
            return
        self._clear_failure_actions()
        # v1.6(P0-4/T4): 状态链「重试中…」
        self._status_first_chunk = False
        self.status_label.setText("重试中…")
        try:
            if not self.chat_service.retry_last_failure():
                self.status_label.setText("没有可重试的消息~")
        except Exception:
            self.status_label.setText("")

    def _on_edit_resend_failed(self) -> None:
        """✏️ 改后重发：对失败前的 user 气泡执行既有编辑截断链
        （R9 确认框 + 截断该条及之后 + 回填输入框），用户改完自行正常发送
        —— 截断后 session 已无该条，正常发送不重复入库（幂等）。
        """
        bubble = getattr(self, "_failure_user_bubble", None)
        if bubble is None:
            return
        self._clear_failure_actions()
        try:
            self._on_edit_requested(bubble)
        except Exception:
            pass

    # ==================================================================
    # 其他交互
    # ==================================================================
    def _on_expand_chat(self) -> None:
        if self._chat_window is None:
            self._chat_window = ChatWindow(self.app_ctx, self)
            self._chat_window.attach_requested.connect(self._on_chat_attached)
            # R6: 独立窗口发送的消息由面板统一渲染并持久化（含附件 metadata），
            # 使面板 / 窗口两条发送路径落同一份会话数据
            self._chat_window.user_message_sent.connect(self._on_window_user_message)
        self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()

    # ------------------------------------------------------------------
    # v1.9 A(D-V19-13②)：界面风格快捷入口（顶栏 🎨 → 四风格小菜单）
    # ------------------------------------------------------------------
    def _on_style_menu(self) -> None:
        try:
            from gui.theme_engine import ThemeEngine
        except Exception:
            return
        cur = ThemeEngine.normalize_theme_id(
            getattr(getattr(self.app_ctx, "config", None), "theme_name", "") or "")
        menu = QMenu(self)
        actions = []
        for tid in ThemeEngine.THEME_IDS:
            act = menu.addAction(ThemeEngine.THEME_DEFINITIONS[tid]["name"])
            act.setCheckable(True)
            act.setChecked(tid == cur)
            actions.append((act, tid))
        chosen = menu.exec_(self.style_btn.mapToGlobal(self.style_btn.rect().bottomLeft()))
        for act, tid in actions:
            if chosen is act:
                self._apply_style_choice(tid)
                break

    def _apply_style_choice(self, theme_id: str) -> None:
        """顶栏切换风格：与设置页同一条收口（归一 + C 深色夜间进出 + 即时生效 + 持久化）。"""
        try:
            from gui.theme_engine import ThemeEngine, apply_night_lock
        except Exception:
            return
        theme_id = ThemeEngine.normalize_theme_id(theme_id)
        engine = getattr(self.app_ctx, "theme_engine", None)
        config = getattr(self.app_ctx, "config", None)
        apply_night_lock(engine, config, theme_id)
        if engine is not None:
            try:
                engine.load_theme(theme_id)
            except Exception:
                pass
        if config is not None:
            config.theme_name = theme_id
            try:
                config.save()
            except Exception:
                pass

    def _on_chat_attached(self) -> None:
        """独立窗口请求合并回主面板。"""
        self._chat_window = None
    def _on_window_user_message(self, display_text: str, attachments: list) -> None:
        """R6: 独立窗口发送路径的持久化入口——面板侧渲染并保存同一份会话数据。"""
        self._add_message_bubble("user", display_text, attachments=attachments or None)
        self._save_current_session()

    def _on_attach_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择附件", "",
            "所有文件 (*);;文本文件 (*.txt);;代码文件 (*.py *.js *.ts *.java *.cpp *.c *.h *.go *.rs *.md)"
        )
        if not path:
            return
        # R5: 与拖拽同一条校验链（存在性 / 10MB 上限 / 重复），不再以纯文本插入输入框
        ok, info = self.attachment_bar.add_file_path(path)
        if ok is True:
            self.status_label.setText(f"已添加附件: {info}")
            return
        name = os.path.basename(path)
        if info == "too_large":
            QMessageBox.warning(self, "附件过大", f"{name} 超过 10MB 上限，未添加。")
        elif info == "missing":
            QMessageBox.warning(self, "附件不存在", f"{name} 不存在或不可访问，未添加。")
        elif info == "duplicate":
            QMessageBox.information(self, "附件已存在", f"{name} 已在附件列表中。")

    def _on_paste_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text()
        if text:
            current = self.input_edit.toPlainText()
            prefix = "\n" if current else ""
            self.input_edit.setPlainText(f"{current}{prefix}{text}")
        else:
            QMessageBox.information(self, "粘贴", "剪贴板中没有文本内容")

    def _on_search_filter(self, text: str) -> None:
        query = text.strip()
        scope = self.scope_combo.currentData() if hasattr(self, "scope_combo") else "current"

        # --- 全部会话范围：跨会话搜索，结果弹窗展示 ---
        if scope == "all" and query:
            self._search_all_sessions(query)
            return

        # --- 当前会话范围 ---
        matcher = self._build_matcher(query)
        if matcher is None:
            # 正则语法错误或空查询：恢复全部可见
            for i in range(self.messages_layout.count() - 1):
                item = self.messages_layout.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                if isinstance(widget, MessageBubble):
                    widget.setVisible(True)
            return

        first_hit = None
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                hit = matcher(widget.get_text())
                widget.setVisible(hit)
                if hit and first_hit is None:
                    first_hit = widget
        # 命中第一条：高亮并滚动定位
        if first_hit is not None:
            self._highlight_bubble(first_hit)
            self.scroll_area.ensureWidgetVisible(first_hit)
        else:
            self._highlight_bubble(None)

    def _build_matcher(self, query: str):
        """根据查询构造匹配函数；正则语法错误时返回 None。"""
        use_regex = hasattr(self, "regex_check") and self.regex_check.isChecked()
        matcher = _pure_build_matcher(query, use_regex=use_regex)
        if query and matcher is None:
            self.status_label.setText("正则语法错误")
        elif query and matcher is not None:
            self.status_label.setText("")
        return matcher

    def _highlight_bubble(self, bubble) -> None:
        """高亮命中的消息气泡（金色边框），清除上一个。"""
        if self._highlighted_bubble is not None:
            try:
                self._highlighted_bubble.setStyleSheet(_clear_highlight_style())
            except RuntimeError:
                pass
            self._highlighted_bubble = None
        if bubble is not None:
            bubble.setStyleSheet(_highlight_style())
            self._highlighted_bubble = bubble

    def _search_all_sessions(self, query: str) -> None:
        """跨全部会话搜索，结果以对话框展示。"""
        if self.session_manager is None:
            return
        use_regex = hasattr(self, "regex_check") and self.regex_check.isChecked()
        matcher = _pure_build_matcher(query, use_regex=use_regex)
        if matcher is None and query:
            self.status_label.setText("正则语法错误")
            return

        results = []
        for session in self.session_manager.all_sessions():
            for msg in session.messages:
                if msg.role in ("user", "assistant") and matcher(msg.content):
                    results.append(format_search_result(session.name, msg.role, msg.content))

        dialog = QDialog(self)
        dialog.setWindowTitle(f"搜索结果（{len(results)} 条）")
        dialog.resize(520, 360)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(12, 12, 12, 12)
        result_list = QListWidget(dialog)
        for line in results:
            result_list.addItem(line)
        if not results:
            result_list.addItem("（无匹配结果）")
        dlg_layout.addWidget(result_list)
        close_btn = QPushButton("关闭", dialog)
        close_btn.clicked.connect(dialog.accept)
        dlg_layout.addWidget(close_btn)
        dialog.exec_()

    # ==================================================================
    # 聊天记录导出
    # ==================================================================
    def _collect_messages(self) -> list:
        """从当前消息气泡收集 (role, content, timestamp) 列表。"""
        return collect_messages_from_layout(self.messages_layout, MessageBubble)

    def _on_export_chat(self) -> None:
        """导出当前会话聊天记录（Markdown / TXT / JSON）。"""
        messages = self._collect_messages()
        if not messages:
            QMessageBox.information(self, "导出", "当前没有消息可导出")
            return

        session_name = "聊天记录"
        if self.session_manager is not None and self._current_session_id:
            session = self.session_manager.get_session(self._current_session_id)
            if session is not None:
                session_name = session.name

        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出聊天记录", "chat_export.md",
            "Markdown (*.md);;文本文件 (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        fmt = detect_export_format(selected_filter)

        if ChatExporter.export(messages, fmt, path, session_name):
            QMessageBox.information(self, "导出成功", f"聊天记录已导出到:\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", "导出聊天记录失败，请检查文件路径")

    def _on_search_messages(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def _on_toggle_emoji_panel(self) -> None:
        self.emoji_panel.setVisible(not self.emoji_panel.isVisible())

    def _on_emoji_clicked(self, emoji: str) -> None:
        cursor = self.input_edit.textCursor()
        cursor.insertText(emoji)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    def _on_quick_reply(self, text: str) -> None:
        self.input_edit.setPlainText(text)
        self._on_send()

    def _on_stop_generation(self) -> None:
        if self.chat_service is not None:
            self.chat_service.stop_generation()

    # ----- v1.1(agent): Agent 模式开关与工具轨迹提示 -----
    def _on_toggle_agent_mode(self, checked: bool) -> None:
        if self.chat_service is not None:
            self.chat_service.set_agent_mode(checked)
        self.input_edit.setPlaceholderText(
            "Agent 模式：女仆会自主调用工具完成任务（读文件/Git/写文件/跑代码/联网搜索）..."
            if checked else "和女仆说点什么吧... （或拖拽文件）"
        )
        hint = "已开启 Agent 模式，女仆现在可以自主调用工具啦~" if checked else "已关闭 Agent 模式，回到普通聊天。"
        try:
            self.status_label.setText(hint)
        except Exception:
            pass
        # 会话级授权状态重置：每次开关都清空（重新授权）
        tools = getattr(self.app_ctx, "agent_tools", None)
        if tools is not None and hasattr(tools, "reset_session_authorization"):
            tools.reset_session_authorization()

    # ----- v1.4.7: 任务模式开关 -----
    def _on_toggle_task_mode(self, checked: bool) -> None:
        """任务模式切换：开启后发送消息走 managed task（自动拆分步骤/自愈/断点恢复）。

        任务模式依赖 Agent 模式：如果 Agent 未开启则自动开启。
        """
        if checked:
            # 任务模式需要 Agent 模式
            agent_btn = getattr(self, "agent_btn", None)
            if agent_btn is not None and not agent_btn.isChecked():
                agent_btn.setChecked(True)
            if self.chat_service is not None:
                self.chat_service.set_agent_mode(True)
            self.input_edit.setPlaceholderText(
                "任务模式：描述一个复杂任务，女仆会自动拆分步骤逐步执行（支持自愈/断点恢复）..."
            )
            self.status_label.setText("已开启任务模式，发送消息将自动拆分步骤执行~")
        else:
            self.input_edit.setPlaceholderText(
                "Agent 模式：女仆会自主调用工具完成任务（读文件/Git/写文件/跑代码/联网搜索）..."
                if (self.chat_service and self.chat_service.is_agent_mode()) else
                "和女仆说点什么吧... （或拖拽文件）"
            )
            self.status_label.setText("已关闭任务模式，回到普通 Agent 聊天。")

    def _is_task_mode(self) -> bool:
        """当前是否处于任务模式。"""
        btn = getattr(self, "task_btn", None)
        return btn is not None and btn.isChecked()

    # ----- v1.5.0: 「🌐 联网」开关与检索提示 -----
    def _on_toggle_web_search(self, checked: bool) -> None:
        """联网开关切换：状态持久化到 GuiConfig.web_search_enabled_gui。

        检索时机由 ChatService 决定（命中 should_auto_search 才搜），
        Agent 模式不受本开关影响（其自带 web_search 工具）。
        """
        try:
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "web_search_enabled_gui"):
                gui_cfg.web_search_enabled_gui = bool(checked)
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            pass
        try:
            self.status_label.setText(
                "已开启联网搜索：遇到需要最新信息的问题会自动检索~" if checked
                else "已关闭联网搜索。"
            )
        except Exception:
            pass

    # ----- v1.6(P0-2): 意图选态下拉 -----
    def _on_intent_mode_changed(self, index: int) -> None:
        """意图选态切换：持久化到 GuiConfig.chat_intent_mode。

        手动选态覆盖自动识别（"auto" 恢复纯规则识别）；选态只决定附加的
        语气提示（ChatService 请求副本注入），消息流绝不改道。
        """
        combo = getattr(self, "intent_combo", None)
        if combo is None:
            return
        try:
            mode = str(combo.currentData() or "auto")
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "chat_intent_mode"):
                gui_cfg.chat_intent_mode = mode
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            pass
        try:
            tips = {
                "auto": "已回到自动识别：码铃按消息内容自动调整回应方式~",
                "confide": "已切换「只想说说」：码铃会先倾听陪伴，不急着给方案。",
                "chat": "已切换「陪我聊聊」：纯闲聊模式。",
                "analyze": "已切换「帮我分析」：码铃会给出有条理的分析。",
                "advise": "已切换「给我建议」：码铃会直接给明确建议。",
                "act": "已切换「帮我行动」：码铃会给可执行的步骤与方案。",
            }
            if self.status_label is not None:
                self.status_label.setText(tips.get(mode, ""))
        except Exception:
            pass

    # ----- v1.8(V18-13/D-V18-07): 场景手动切换下拉 -----
    def _on_scene_mode_changed(self, index: int) -> None:
        """场景切换：持久化 GuiConfig.manual_scene + manual_scene_date（当日）。

        "" = 回到自动感知（清除手动覆盖）；选定场景当日有效、次日回落（Q-D4）。
        场景只影响语气底色（request_injections + 幂等边界消息）与工作时段
        主动降档（Q-D6），消息流绝不改道。
        """
        combo = getattr(self, "scene_combo", None)
        if combo is None:
            return
        try:
            value = str(combo.currentData() or "")
            gui_cfg = getattr(self.app_ctx, "config", None)
            if gui_cfg is not None and hasattr(gui_cfg, "manual_scene"):
                gui_cfg.manual_scene = value
                if hasattr(gui_cfg, "manual_scene_date"):
                    gui_cfg.manual_scene_date = datetime.now().strftime("%Y-%m-%d")
                if hasattr(gui_cfg, "save"):
                    gui_cfg.save()
        except Exception:
            pass
        try:
            tips = {
                "": "已回到自动感知：码铃按时段切换场景语气（次日也无需手动调）。",
                "work": "已进入工作模式：回应会简洁高效，主动消息也会降到最低。",
                "rest": "已进入休息模式：轻松随意地聊，码铃陪主人放松~",
                "sleep": "已进入睡前模式：语气放轻放缓，安静陪伴。",
            }
            value = str(getattr(combo, "currentData", lambda: "")() or "")
            if self.status_label is not None:
                self.status_label.setText(tips.get(value, ""))
        except Exception:
            pass

    # ==================================================================
    # v1.6(P0-3/D-V16-05): 反馈三键动作行（不入会话存档；R-A：不进 intimacy）
    # ==================================================================
    def _on_proactive_feedback_ready(self, subject: str, scene: str) -> None:
        """主动消息内容源就绪：在消息流末尾挂反馈三键动作行。"""
        if not subject:
            return  # 纯模板问候 → 不渲染三键
        try:
            from gui.widgets.proactive_feedback import ProactiveFeedbackBar
            bar = ProactiveFeedbackBar(subject, scene, self._on_feedback_picked)
            bar.set_app_ctx(self.app_ctx)
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, bar)
            self._feedback_bars.append(bar)
            self._scroll_to_bottom()
        except Exception:
            pass

    def _on_feedback_picked(self, subject: str, scene: str, kind: str) -> None:
        """三键回调：纯 memory 策略写入（绝不触碰 intimacy / 交互打点）。"""
        session = getattr(self.app_ctx, "session", None)
        memory_mgr = getattr(session, "memory_mgr", None) if session is not None else None
        if memory_mgr is not None and hasattr(memory_mgr, "record_followup_feedback"):
            try:
                memory_mgr.record_followup_feedback(subject, kind)
            except Exception:
                pass
        # 「想聊聊」：小字引导主人直接开口（复用既有小字插入通道；只引导不记分）
        if kind == "chat" and self.chat_service is not None:
            try:
                self.chat_service.web_search_notice.emit("💬 那我们接着聊~ 主人直接说就好")
            except Exception:
                pass

    def _clear_feedback_bars(self) -> None:
        """新一条用户消息发出时移除未点击的反馈动作行（防堆积）。"""
        try:
            for bar in list(getattr(self, "_feedback_bars", [])):
                self.messages_layout.removeWidget(bar)
                bar.deleteLater()
            self._feedback_bars = []
        except Exception:
            self._feedback_bars = []

    def _on_web_search_notice(self, notice: str) -> None:
        """联网检索提示：在流式气泡前插入一条小字提示（不入会话存档）。"""
        if not notice:
            return
        try:
            from gui.utils import theme_color
            color = theme_color(self.app_ctx, "text_secondary", "#999999")
        except Exception:
            color = "#999999"
        try:
            label = QLabel(str(notice))
            label.setObjectName("webSearchNotice")
            label.setStyleSheet(
                f"color: {color}; font-size: 11px; padding: 2px 8px; background: transparent;"
            )
            label.setWordWrap(True)
            # 与气泡一致的插入位（末尾 stretch 之前），QLabel 不会被 _save_current_session 快照
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, label)
            self._scroll_to_bottom()
        except Exception:
            pass

    def _on_agent_authorization_requested(self, action_desc: str, tool_name: str) -> None:
        """Agent 修改类工具授权弹窗（主线程）。

        用户点「是」→ 本次会话后续同类操作自动放行（会话级一次授权）；
        点「否」/ 关窗 → 拒绝本次。
        """
        try:
            tool_label = format_tool_label(tool_name)
            box = QMessageBox(self)
            box.setWindowTitle("码铃 · Agent 授权请求")
            box.setIcon(QMessageBox.Question)
            box.setText(f"女仆想执行一个修改类操作：\n\n【{tool_label}】\n{action_desc[:200]}")
            box.setInformativeText("允许本次及本次会话内后续操作吗？\n（白名单目录内的操作不受此限制，会自动放行）")
            yes_btn = box.addButton("允许（本次会话）", QMessageBox.AcceptRole)
            box.addButton("拒绝本次", QMessageBox.RejectRole)
            box.exec_()
            approved = box.clickedButton() is yes_btn
        except Exception:
            approved = False
        try:
            if self.chat_service is not None:
                self.chat_service.resolve_agent_authorization(approved)
        except Exception:
            pass

    def _on_agent_tool_event(self, event_type: str, data_json: str) -> None:
        """Agent 工具轨迹：把 llm_start / tool_call / tool_done 等事件渲染进折叠卡片，
        同时保留状态栏文字提示（原有行为不回退）。
        """
        import json as _json
        try:
            data = _json.loads(data_json or "{}")
        except Exception:
            data = {}
        try:
            # v1.1(B2): 事件 → 工具轨迹卡片（防御式：卡片异常绝不外抛）
            trace = getattr(self, "tool_trace_panel", None)
            if trace is not None:
                try:
                    if not self._agent_trace_active:
                        trace.reset()
                        self._agent_trace_active = True
                    trace.add_event(event_type, data)
                    if event_type in ("final", "max_steps"):
                        trace.finish()
                        self._agent_trace_active = False
                except Exception:
                    self._agent_trace_active = False
        except Exception:
            pass
        # v1.2(A-9/A-10): Agent 干活中 -> 活动态 focus；结束/收尾 -> 回落
        if event_type in ("final", "max_steps"):
            self._publish_activity(None)
        elif self._agent_trace_active:
            self._publish_activity("focus")
        try:
            status_text = format_agent_event_status(event_type, data)
            if status_text is not None:
                self.status_label.setText(status_text)
        except Exception:
            pass

    def _on_theme_changed(self, theme_name: str) -> None:
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                widget.update_theme()
            elif isinstance(widget, ThinkingIndicator):
                widget.update_theme()
        # 第四阶段：附件栏 / 标签页栏主题色同步
        self.attachment_bar.refresh_theme()
        self.session_tabs.apply_theme()
        # v1.1(B2): 工具轨迹卡片主题刷新（防御式）
        try:
            self.tool_trace_panel.update_theme()
        except Exception:
            pass

    # ==================================================================
    # 第四阶段 · 扩展功能：拖拽 / 编辑 / 重新生成 / 标签页 / 语音
    # ==================================================================
    # ----- 拖拽上传 -----
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        added = 0
        skipped_big: List[str] = []
        skipped_missing: List[str] = []
        skipped_dup: List[str] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            ok, info = self.attachment_bar.add_file_path(path)
            if ok is True:
                added += 1
            elif info == "too_large":
                skipped_big.append(os.path.basename(path))
            elif info == "missing":
                skipped_missing.append(os.path.basename(path))
            elif info == "duplicate":
                skipped_dup.append(os.path.basename(path))
        event.acceptProposedAction()
        # 汇总提示
        if skipped_big:
            QMessageBox.warning(
                self,
                "附件过大",
                f"以下文件超过 10MB 上限，未添加：\n  " + "\n  ".join(skipped_big),
            )
        elif skipped_missing or skipped_dup:
            lines = []
            if skipped_missing:
                lines.append("不存在的文件：\n  " + "\n  ".join(skipped_missing))
            if skipped_dup:
                lines.append("已存在的附件：\n  " + "\n  ".join(skipped_dup))
            QMessageBox.information(self, "部分附件未添加", "\n\n".join(lines))

    # ----- 消息编辑 / 重新生成 -----
    def _on_edit_requested(self, bubble: MessageBubble) -> None:
        """编辑用户消息：截断该消息及其后内容，回填到输入框，保存会话。"""
        if bubble.role != "user":
            return
        # v1.7(F10a): 群聊消息不支持编辑（截断链走 LLM 历史重建，禁入群聊，R-J 隔离）
        if _is_group_session(self._current_group_session()):
            QMessageBox.information(self, "群聊", "群聊消息暂不支持编辑（MVP）~")
            return
        # R9: 编辑会截断该消息及其后全部内容，先弹确认，避免误触即永久丢失
        reply = QMessageBox.question(
            self, "编辑消息",
            "编辑将移除该消息及其后的所有消息（含 AI 回复），\n"
            "原文与附件会回填到输入框。确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # R10: 截断前先取局部变量，deleteLater 之后不再访问 bubble 的内容接口
        text = bubble.get_text()
        atts = bubble.get_attachments()
        if self._truncate_messages_from(bubble):
            # 回填
            self.input_edit.setPlainText(text)
            # 附件也回填
            if atts:
                self.attachment_bar.add_from_dicts(atts)
            self._save_current_session()
            self.input_edit.setFocus()
            self.status_label.setText("已回填到输入框，修改后点击「发送」")

    def _on_regenerate_requested(self, bubble: MessageBubble) -> None:
        """重新生成 AI 回复：截断该回复及其后内容，复跑 ChatService.regenerate()。

        R2: 截断基准与重发文本由 UI 提供——从剩余气泡取最后一条 user 文本传入，
        并把 ui_history（剩余消息）一并交给服务层，使 app_ctx.session.history
        与 UI 截断后的状态对齐，消除两套历史分叉。
        """
        if bubble.role != "assistant":
            return
        # v1.7(F10a): 群聊消息不支持重新生成（重建 LLM 历史禁入群聊，R-J 隔离）
        if _is_group_session(self._current_group_session()):
            QMessageBox.information(self, "群聊", "群聊消息暂不支持重新生成（MVP）~")
            return
        idx = self.messages_layout.indexOf(bubble)
        if idx < 0:
            return
        # R10: 截断前先收集剩余消息（局部变量快照）
        remaining = self._collect_ui_history_before(idx)
        last_user_text = None
        for entry in reversed(remaining):
            if entry.get("role") == "user":
                last_user_text = entry.get("content", "")
                break
        if last_user_text is None:
            QMessageBox.information(
                self, "重新生成", "该回复之前没有用户消息，无法重新生成。"
            )
            return
        if self._truncate_messages_from(bubble):
            self._save_current_session()
            if self.chat_service is not None:
                self.chat_service.regenerate(
                    user_text=last_user_text, ui_history=remaining
                )
            self.status_label.setText("正在重新生成...")

    def _collect_ui_history_before(self, idx: int) -> List[dict]:
        """收集布局中 [0, idx) 的消息，格式与发送时给 AI 的 content 一致（附件带摘要）。"""
        entries: List[dict] = []
        for i in range(idx):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if not isinstance(widget, MessageBubble):
                continue
            content = widget.get_text()
            if widget.role == "user":
                atts = widget.get_attachments()
                if atts:
                    att_lines = "\n".join(
                        f"[附件] {a.get('name', '')} ({a.get('size', 0)} bytes)"
                        for a in atts
                    )
                    content = (content + "\n" if content else "") + att_lines
            entries.append({"role": widget.role, "content": content})
        return entries

    def _truncate_messages_from(self, bubble: MessageBubble) -> bool:
        """从指定气泡（含）开始截断消息列表，返回是否截断成功。"""
        if bubble is None:
            return False
        idx = self.messages_layout.indexOf(bubble)
        if idx < 0:
            return False
        # 收集要移除的 widget 索引（先取列表避免迭代过程中 index 变化）
        to_remove: List[int] = []
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, MessageBubble) and i >= idx:
                to_remove.append(i)
        for i in to_remove:
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            self.messages_layout.removeWidget(widget)
            widget.deleteLater()
        # 重新计算 _last_role（指向剩余最后一条气泡的角色）
        self._last_role = None
        self._last_speaker_id = None
        for i in range(self.messages_layout.count() - 1, -1, -1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                self._last_role = widget.role
                self._last_speaker_id = getattr(widget, "speaker_id", None)
                break
        return True

    # ----- 标签页模式 -----
    def _on_toggle_tab_mode(self, checked: bool) -> None:
        self._tab_mode = checked
        self.session_tabs.setVisible(checked)
        if checked:
            # 首次开启：把当前会话加入开放列表
            if self._current_session_id and self._current_session_id not in self._open_tab_ids:
                self._open_tab_ids.append(self._current_session_id)
            self._sync_tabs()
        else:
            # 关闭时保留 open_tab_ids（再次开启可恢复），仅隐藏栏
            pass

    def _sync_tabs(self) -> None:
        """根据当前会话数据刷新标签页栏。"""
        if not self._tab_mode:
            return
        if self.session_manager is None:
            return
        # 清理已删除的会话
        valid_ids = {s.id for s in self.session_manager.all_sessions()}
        self._open_tab_ids = [sid for sid in self._open_tab_ids if sid in valid_ids]
        if self._current_session_id and self._current_session_id not in self._open_tab_ids:
            self._open_tab_ids.append(self._current_session_id)
        id_to_name = {s.id: s.name for s in self.session_manager.all_sessions()}
        # v1.7(F10b) 遗留收口：群聊会话 Tab 带 👥 角标（与左侧列表展示一致）
        group_ids = {s.id for s in self.session_manager.all_sessions()
                     if _is_group_session(s)}
        self.session_tabs.rebuild(self._open_tab_ids, id_to_name,
                                  self._current_session_id, group_ids)

    def _on_tab_switched(self, session_id: str) -> None:
        self._switch_to_session(session_id)

    def _on_tab_new(self) -> None:
        # 标签页 "+" 直接创建默认名「新会话」并打开为 tab
        if self.session_manager is None:
            return
        session = self.session_manager.create_session("新会话")
        if session.id not in self._open_tab_ids:
            self._open_tab_ids.append(session.id)
        self._current_session_id = session.id
        self.title_label.setText(session.name)
        self._clear_messages()
        self._refresh_session_list()

    def _on_tab_close(self, session_id: str) -> None:
        """关闭标签 = 结束会话（不删除，仍在左侧列表中）。"""
        if session_id not in self._open_tab_ids:
            return
        # R13: 记住被关 tab 的位置——切换优先其相邻项（先左后右），而非列表末项
        closed_idx = self._open_tab_ids.index(session_id)
        self._open_tab_ids.remove(session_id)
        if session_id == self._current_session_id:
            # 切换到相邻 open tab，或最近一个未打开的会话，或新建空会话
            target: Optional[str] = None
            if self._open_tab_ids:
                pick = closed_idx - 1 if closed_idx > 0 else 0
                target = self._open_tab_ids[min(pick, len(self._open_tab_ids) - 1)]
            elif self.session_manager is not None:
                recent = self.session_manager.all_sessions()
                if recent:
                    target = next((s.id for s in recent if s.id != session_id), None)
            if target:
                self._switch_to_session(target)
                if target not in self._open_tab_ids:
                    self._open_tab_ids.append(target)
            else:
                # 没有任何会话可用：创建新空会话
                if self.session_manager is not None:
                    new_session = self.session_manager.create_session("新会话")
                    self._current_session_id = new_session.id
                    self.title_label.setText(new_session.name)
                    self._clear_messages()
                    self._open_tab_ids.append(new_session.id)
                else:
                    self._current_session_id = None
                    self.title_label.setText("聊天")
        self._sync_tabs()

    # ----- 语音输入 -----
    def _on_voice_input(self) -> None:
        backend_ok, device_ok, desc = voice_input_mod.diagnose_voice_input()
        if not backend_ok or not device_ok:
            QMessageBox.information(
                self, "语音输入", voice_input_mod.build_unavailable_message()
            )
            return
        dlg = voice_input_mod.VoiceInputDialog(self.app_ctx, self)
        if dlg.exec_() == QDialog.Accepted and dlg.transcript:
            current = self.input_edit.toPlainText().strip()
            sep = "\n" if current else ""
            self.input_edit.setPlainText(current + sep + dlg.transcript)
            self.input_edit.setFocus()
            self.status_label.setText("已插入语音识别结果")

    # ------------------------------------------------------------------
    # v1.3(P2-2): 免提对话（voice_conversation 控制器 + handsfree_bar 状态条）
    # ------------------------------------------------------------------
    def _handsfree_ctrl(self):
        """返回 app 级免提控制器单例（无则懒创建；导入失败返回 None）。"""
        app_ctx = self.app_ctx
        ctrl = getattr(app_ctx, "voice_conversation", None) if app_ctx is not None else None
        if ctrl is not None:
            return ctrl
        try:
            from gui.voice_conversation import VoiceConversationController
            ctrl = VoiceConversationController(app_ctx)
            if app_ctx is not None:
                try:
                    setattr(app_ctx, "voice_conversation", ctrl)
                except Exception:
                    pass
            return ctrl
        except Exception as exc:
            logger.warning("免提控制器不可用: %s", exc)
            return None

    def _init_handsfree(self) -> None:
        """接线免提：控制器信号 -> 状态条/按钮；按钮仅在 STT 后端存在时可用。"""
        bar = getattr(self, "handsfree_bar", None)
        btn = getattr(self, "handsfree_btn", None)
        ctrl = self._handsfree_ctrl()
        backend_ok = bool(voice_input_mod.stt_backend_available())
        self._hf_backend_ok = backend_ok
        if bar is not None:
            bar.setVisible(backend_ok)
        if btn is not None:
            btn.setEnabled(backend_ok)
            if not backend_ok:
                btn.setToolTip(
                    "免提暂不可用：未检测到 SpeechRecognition / PyAudio\n"
                    "（与「🎤 语音」同依赖，安装并连接麦克风后可用）"
                )
        if ctrl is None:
            return
        try:
            ctrl.state_changed.connect(self._on_hf_state_changed)
            ctrl.notice.connect(self._on_hf_notice)
            ctrl.speech_ready.connect(self._on_hf_speech_ready)
            if bar is not None:
                bar.stop_requested.connect(self._on_hf_stop_clicked)
        except Exception as exc:
            logger.warning("免提信号接线失败: %s", exc)

    def _on_handsfree_toggled(self, checked: bool) -> None:
        """快捷操作栏「🎙 免提」开关。"""
        if checked:
            ctrl = self._handsfree_ctrl()
            if ctrl is None:
                self._set_hf_btn_checked(False)
                return
            ok = False
            try:
                ok = ctrl.start()
            except Exception as exc:
                logger.warning("免提 start 异常: %s", exc)
            if not ok:
                self._set_hf_btn_checked(False)
        else:
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.stop()
                except Exception:
                    pass

    def _set_hf_btn_checked(self, checked: bool) -> None:
        btn = getattr(self, "handsfree_btn", None)
        if btn is None:
            return
        btn.blockSignals(True)
        try:
            btn.setChecked(checked)
        finally:
            btn.blockSignals(False)

    def _on_hf_stop_clicked(self) -> None:
        self._set_hf_btn_checked(False)
        ctrl = self._handsfree_ctrl()
        if ctrl is not None:
            try:
                ctrl.stop()
            except Exception:
                pass

    def _on_hf_state_changed(self, state: str) -> None:
        bar = getattr(self, "handsfree_bar", None)
        if bar is not None:
            bar.set_state(state)
        self._set_hf_btn_checked(state != "idle")

    def _on_hf_notice(self, text: str) -> None:
        bar = getattr(self, "handsfree_bar", None)
        if bar is not None:
            bar.set_notice(text)
        else:
            self.status_label.setText(text)

    def _on_hf_speech_ready(self, text: str) -> None:
        """免提识别结果：复用 UI 直插气泡 + ChatService 发送路径（不直连）。

        speech_ready 只发文本信号，由本面板走与打字发送同源的渲染/发送链，
        保证单气泡渲染入口、不产生第二套发送逻辑。
        """
        content = (text or "").strip()
        if not content:
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.notify_reply_done("")
                except Exception:
                    pass
            return
        # UI 直插用户气泡（唯一 user 渲染入口之一，suppress_echo 防双泡）
        self._add_message_bubble("user", content)
        self._save_current_session()
        self._hf_pending_reply = True
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(content, [])
        self._reset_agent_trace()
        if self.chat_service is not None:
            self.chat_service.send_message(send_text, suppress_echo=True, attachments=[])
        else:
            # 无服务（异常态）：不要卡在 sending，放行回 listening
            self._hf_pending_reply = False
            ctrl = self._handsfree_ctrl()
            if ctrl is not None:
                try:
                    ctrl.notify_reply_done("")
                except Exception:
                    pass

    def _hf_resume_after_reply(self, reply_text: str) -> None:
        """语音消息的 AI 回复结束 -> 通知控制器朗读/回听。"""
        if not getattr(self, "_hf_pending_reply", False):
            return
        self._hf_pending_reply = False
        ctrl = self._handsfree_ctrl()
        if ctrl is not None:
            try:
                ctrl.notify_reply_done(reply_text or "")
            except Exception:
                pass

    # ----- v1.2.2 拍照发图（配合看图）-----
    def _on_camera_capture(self) -> None:
        try:
            from gui.widgets.camera_capture import capture_photo
        except Exception:
            QMessageBox.information(self, "拍照", "拍照功能暂不可用，可改用「📎 附件」选择图片。")
            return
        path = capture_photo(self)
        if not path:
            return  # 用户取消或不可用（内部已提示）
        ok, reason = self.attachment_bar.add_file_path(path)
        if ok:
            self.status_label.setText("已加入照片（发送时以图片发送给模型）")
        elif reason == "duplicate":
            self.status_label.setText("照片已在附件列表中")
        elif reason == "too_large":
            QMessageBox.warning(self, "图片过大", "照片超过 10MB，未添加。")
        else:
            QMessageBox.warning(self, "添加失败", "照片文件无效，未添加。")

    # ----- v1.3(P2-1): 小游戏入口（她当荷官，无数值零计分）-----
    def _open_mini_games(self) -> None:
        """打开小游戏对话框（会话隔离、不落聊天记录）。"""
        try:
            from gui.widgets.mini_games import MiniGamesDialog
        except Exception as exc:
            logger.warning("小游戏模块导入失败: %s", exc)
            QMessageBox.information(self, "小游戏", "小游戏暂不可用（模块加载失败），请稍后再试~")
            return
        dlg = MiniGamesDialog(self.app_ctx, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()

    # ----- v1.3(P2-3): 收藏高光回忆（右键 -> HighlightsManager.add）-----
    def _on_favorite_requested(self, bubble, role: str, text: str, meta: object) -> None:
        """收藏一条气泡文本为高光回忆（本地落盘，绝不上云）。"""
        try:
            from gui.pages.page_memories import add_highlight
        except Exception as exc:
            logger.warning("回忆模块导入失败: %s", exc)
            return
        session_id = self._current_session_id or ""
        new_id = add_highlight(self.app_ctx, role, text, session_id=session_id)
        if new_id:
            self.status_label.setText("✨ 已收藏为高光回忆（「回忆」页可随时查看）")
        else:
            self.status_label.setText("收藏失败：高光回忆暂不可用")

    # ----- v1.3(P1-1): 朗读本条（TTS）-----
    def _on_bubble_read_aloud(self, bubble: Optional[MessageBubble]) -> None:
        """气泡「🔊 朗读本条 / ⏹ 停止」点击。

        - 只朗读 AI 气泡文本（用户气泡无朗读按钮）；
        - 正在朗读本气泡 -> 停止；否则全局单例开口（后开口打断前开口）。
        """
        if bubble is None:
            return
        tts = getattr(self.app_ctx, "tts", None)
        if not self._tts_usable(tts):
            return
        if bubble.is_reading() or tts.active_owner is bubble:
            try:
                tts.stop()
            except Exception:
                pass
            return
        text = (bubble.get_text() or "").strip()
        if not text:
            return
        try:
            ok = tts.speak(text, owner=bubble)
        except Exception:
            ok = False
        if not ok:
            self.status_label.setText("语音朗读暂不可用")
        # speak 已同步发 state_changed(owner)，按钮态刷新无需在此手动 set

    def _tts_usable(self, tts) -> bool:
        """TTS 可用性守卫：总开关 + 后端/语音可用；不可用给一句可读提示（不崩）。"""
        config = getattr(self.app_ctx, "config", None)
        if tts is None:
            self._show_tts_unavailable(None)
            return False
        if config is None or not bool(getattr(config, "tts_enabled", True)):
            self._show_tts_unavailable(tts)
            return False
        if not tts.available:
            self._show_tts_unavailable(tts)
            return False
        return True

    def _show_tts_unavailable(self, tts) -> None:
        reason = ""
        if tts is not None:
            try:
                reason = tts.availability_reason or ""
            except Exception:
                reason = ""
        if reason:
            msg = (f"{reason}。\n可在 Windows 语音设置中安装/启用语音包，"
                   f"或在「设置 → 语音」中检查开关。")
        else:
            msg = "语音朗读已关闭或暂不可用。\n可在「设置 → 语音」中开启。"
        QMessageBox.information(self, "语音朗读", msg)

    def _on_tts_state_changed(self, owner) -> None:
        """TTS 朗读归属变化 -> 刷新本面板所有气泡的「朗读中/待朗读」按钮态。"""
        try:
            for i in range(self.messages_layout.count()):
                item = self.messages_layout.itemAt(i)
                if item is None:
                    continue
                w = item.widget()
                if isinstance(w, MessageBubble):
                    w.set_read_aloud(w is owner)
        except Exception:
            pass

    # ==================================================================
    # v1.4(B1b/B2): 看屏 + GUI 单步操作（ScreenWatchService / ComputerUseController）
    # ==================================================================
    def _init_screen_watch(self) -> None:
        """看屏接线：取 app 级服务、订阅事件、连 chip 按钮；cfg 曾开启 → 直接恢复。

        单例语义：与 V-1.4-0 main._mount_v14_b_screen 共用 get_screen_watch_service，
        不会重复创建；此处只读 config 默认值（getattr 容错）。
        """
        try:
            from gui.screen_watch import get_screen_watch_service
            svc = get_screen_watch_service(self.app_ctx)
        except Exception as exc:
            logger.warning("看屏服务初始化失败: %s", exc)
            svc = None
        self._watch_svc = svc
        self._watch_svc_ready = svc is not None
        if svc is None:
            btn = getattr(self, "watch_btn", None)
            if btn is not None:
                btn.setEnabled(False)
                btn.setToolTip("看屏组件初始化失败，暂不可用")
            return
        try:
            svc.watch_state_changed.connect(self._on_watch_state_changed)
            svc.frame_captured.connect(self._on_watch_frame_captured)
            svc.screen_changed.connect(self._on_watch_screen_changed)
            svc.stats_changed.connect(self._on_watch_stats_changed)
            svc.auto_paused.connect(self._on_watch_auto_paused)
            svc.paused_changed.connect(self._on_watch_paused_changed)
            svc.high_value_notice.connect(self._on_watch_high_value_notice)
            svc.notice.connect(self._on_watch_notice)
        except Exception as exc:
            logger.warning("看屏信号订阅失败: %s", exc)
        bar = getattr(self, "screen_watch_bar", None)
        if bar is not None:
            try:
                bar.peek_requested.connect(self._on_watch_peek)
                bar.stop_requested.connect(self._on_watch_close)
                bar.resume_requested.connect(self._on_watch_resume)
                bar.ask_screen_toggled.connect(self._on_watch_ask_toggled)
            except Exception as exc:
                logger.warning("看屏 chip 接线失败: %s", exc)
        # 启动默认态：用户此前显式开启并持久化 → 恢复运行（已确认过成本，不再重复弹窗）
        try:
            from gui.screen_watch import read_sw
            enabled = bool(read_sw(getattr(self.app_ctx, "config", None), "enabled", False))
            if enabled:
                svc.start()
        except Exception as exc:
            logger.warning("看屏默认态恢复失败: %s", exc)
        self._sync_watch_ui()

    def _watch_svc(self):
        return self._watch_svc

    # ----- 看屏 UI 状态同步 -----
    def _sync_watch_ui(self) -> None:
        """按钮 checked 态 + chip 显隐/状态与 ScreenWatchService 对齐。"""
        svc = self._watch_svc
        btn = getattr(self, "watch_btn", None)
        if btn is not None:
            if svc is None:
                btn.setEnabled(False)
            else:
                on = svc.is_running() or svc.is_paused()
                if btn.isChecked() != on:
                    btn.blockSignals(True)
                    try:
                        btn.setChecked(on)
                    finally:
                        btn.blockSignals(False)
        bar = getattr(self, "screen_watch_bar", None)
        if bar is None:
            return
        if svc is None:
            bar.setVisible(False)
            return
        if svc.is_running():
            bar.setVisible(True)
            bar.set_state("running")
            bar.set_stats(svc.frame_count(), svc.token_total())
        elif svc.is_paused():
            bar.setVisible(True)
            bar.set_state("paused")
            bar.set_stats(svc.frame_count(), svc.token_total())
        else:
            bar.setVisible(False)

    def _on_watch_state_changed(self, running: bool) -> None:
        self._sync_watch_ui()

    def _on_watch_paused_changed(self, paused: bool) -> None:
        self._sync_watch_ui()

    def _on_watch_stats_changed(self) -> None:
        svc = self._watch_svc
        bar = getattr(self, "screen_watch_bar", None)
        if svc is None or bar is None or not bar.isVisible():
            return
        bar.set_stats(svc.frame_count(), svc.token_total())

    def _on_watch_frame_captured(self, _uri: str, _meta_json: str) -> None:
        pass  # 最近帧由服务内部维护；此处保留扩展位

    def _on_watch_screen_changed(self, _ratio: float) -> None:
        pass  # 显著变化事件（分类/提示由服务处理；UI 不逐帧刷）

    def _on_watch_notice(self, text: str) -> None:
        bar = getattr(self, "screen_watch_bar", None)
        if bar is not None:
            bar.set_notice(text)

    def _on_watch_auto_paused(self, limit: int) -> None:
        self._sync_watch_ui()
        try:
            if self.chat_service is not None:
                self.chat_service.screen_bubble(
                    f"👀 看屏已自动暂停：本会话已分析到 {limit} 帧（成本护栏）。"
                    "想继续看就点 chip 里的「▶ 续开」，或在设置里调高单会话帧上限。",
                    "screen_pause",
                )
        except Exception:
            pass

    def _on_watch_high_value_notice(self, text: str) -> None:
        """高价值主动提示：仅对话气泡（chat_service.screen_bubble），不 toast（R-C）。"""
        if not (text or "").strip():
            return
        try:
            if self.chat_service is not None:
                self.chat_service.screen_bubble(
                    "👀 " + text.strip(), "screen_notice")
        except Exception as exc:
            logger.warning("高价值提示投递失败: %s", exc)

    # ----- 看屏按钮 / chip 事件 -----
    def _on_watch_toggled(self, checked: bool) -> None:
        svc = self._watch_svc
        if svc is None:
            self._set_watch_checked(False)
            return
        if checked:
            if not self._confirm_watch_start():
                self._set_watch_checked(False)
                return
            try:
                from gui.screen_watch import write_sw
                write_sw(getattr(self.app_ctx, "config", None), "enabled", True)
            except Exception:
                pass
            svc.start()
        else:
            svc.stop()
            try:
                from gui.screen_watch import write_sw
                write_sw(getattr(self.app_ctx, "config", None), "enabled", False)
            except Exception:
                pass
        self._sync_watch_ui()

    def _set_watch_checked(self, checked: bool) -> None:
        btn = getattr(self, "watch_btn", None)
        if btn is not None:
            btn.blockSignals(True)
            try:
                btn.setChecked(checked)
            finally:
                btn.blockSignals(False)

    def _confirm_watch_start(self) -> bool:
        """开启看屏的成本确认弹窗（含单会话帧上限自动暂停说明 + 视觉模型提示）。"""
        box = QMessageBox(self)
        box.setWindowTitle("开启持续看屏")
        box.setIcon(QMessageBox.Question)
        box.setText("开启后，码铃会周期性看一下你的屏幕：回答「这个报错为什么」、按当前屏提问，并在检测到报错/异常时主动提醒。")
        lines = [
            "· 会额外消耗 token 与额度（chip 里会显示已分析帧数与约消耗）",
            "· 单会话帧上限（默认 200 帧）到达会自动暂停，可随时续开",
            "· 帧只在内存里当轮即弃：不落盘、不进历史、不做行为统计",
            "· 随时可一键关闭，关闭即停采并丢弃内存帧",
        ]
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            lines.append("\n⚠️ " + hint)
        box.setInformativeText("\n".join(lines))
        ok_btn = box.addButton("继续开启", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec_()
        return box.clickedButton() is ok_btn

    def _on_watch_close(self) -> None:
        """chip ✕ 关闭：停采弃帧 + 持久化关 + 按钮回弹。"""
        svc = self._watch_svc
        if svc is not None:
            svc.stop()
        try:
            from gui.screen_watch import write_sw
            write_sw(getattr(self.app_ctx, "config", None), "enabled", False)
        except Exception:
            pass
        self._set_watch_checked(False)
        self._sync_watch_ui()

    def _on_watch_resume(self) -> None:
        """chip ▶ 续开：重置会话计数（start 内部处理）并重启。"""
        svc = self._watch_svc
        if svc is None:
            return
        svc.start()
        self._sync_watch_ui()

    def _on_watch_ask_toggled(self, pending: bool) -> None:
        if pending:
            self.status_label.setText("🔍 已点亮按屏提问：下一条消息将带上当前屏幕")
        else:
            self.status_label.setText("")

    def _on_watch_peek(self) -> None:
        """chip「📷 看一帧」：即时采集 → 送视觉 → 结果以对话气泡呈现（非 toast）。"""
        svc = self._watch_svc
        if svc is None or not svc.is_running():
            return
        if self.chat_service is None:
            return
        if self.chat_service.is_busy():
            try:
                self.chat_service.screen_bubble("码铃还在说上一条呢，等它说完再「看一帧」~", "screen_peek")
            except Exception:
                pass
            return
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self.app_ctx)
        except Exception:
            hint = None
        if hint:
            try:
                self.chat_service.screen_bubble(hint, "screen_peek")
            except Exception:
                pass
            return
        att = self._attach_screen_frame()
        if not att:
            self.status_label.setText("取帧失败，稍后再试")
            return
        self._screen_pending_token = True
        text = "📷 看一眼当前屏幕：用一两句话告诉我有什么值得注意或需要帮忙的地方吧~"
        self._add_message_bubble("user", text, attachments=[att])
        self._save_current_session()
        prompt = "这是当前屏幕的一张截图。请用一两句中文简要说说：有什么值得注意的地方、异常或需要帮忙的地方吗？"
        self.chat_service.send_message(prompt, suppress_echo=True, attachments=[att])

    def _attach_screen_frame(self) -> Optional[dict]:
        """取一张新鲜内存帧作为附件条目（uri 通道，不落盘）；送前计一帧分析。"""
        svc = self._watch_svc
        if svc is None or not svc.is_running():
            return None
        try:
            uri = svc.capture_now() or svc.latest_frame_data_uri()
        except Exception:
            uri = None
        if not uri:
            return None
        try:
            svc.note_analysis(0)
        except Exception:
            pass
        return {"name": "当前屏幕", "ext": ".jpg", "size": len(uri), "uri": uri}

    def _screen_intent_hit(self, text: str) -> bool:
        """被动解释启发式：文本含指向当前屏的意图词才附最近帧（非命中不附，防烧 token）。"""
        if not text:
            return False
        keywords = ("屏幕", "报错", "错误", "崩溃", "弹窗", "界面", "页面", "窗口",
                    "怎么点", "点一下", "看一下", "看下", "哪里", "这个", "那个")
        return any(k in text for k in keywords)

    def _settle_screen_round_tokens(self, usage: dict) -> None:
        """本轮回传了屏幕帧 → 流结束把 usage.total_tokens 补记进看屏 chip。"""
        if not getattr(self, "_screen_pending_token", False):
            return
        self._screen_pending_token = False
        svc = self._watch_svc
        if svc is None:
            return
        try:
            tokens = int((usage or {}).get("total_tokens") or 0)
        except (TypeError, ValueError):
            tokens = 0
        if tokens > 0:
            try:
                svc.note_tokens(tokens)
            except Exception:
                pass

    # ----- v1.4(B2): 单步操作路由 -----
    def _route_computer_request(self, text: str) -> None:
        """「🖱 操作」点亮后的下一条消息：渲染用户气泡 + 路由给 ComputerUseController。"""
        self.input_edit.clear()
        self._add_message_bubble("user", "🖱 " + text)
        self.attachment_bar.clear()
        self._save_current_session()
        # 单步语义：路由即熄（每次只处理一条）
        btn = getattr(self, "computer_btn", None)
        if btn is not None and btn.isChecked():
            btn.blockSignals(True)
            try:
                btn.setChecked(False)
            finally:
                btn.blockSignals(False)
        try:
            from gui.computer_use import get_computer_use_controller
            ctrl = get_computer_use_controller(self.app_ctx)
        except Exception as exc:
            logger.warning("单步操作控制器不可用: %s", exc)
            ctrl = None
        if ctrl is None:
            if self.chat_service is not None:
                try:
                    self.chat_service.screen_bubble("单步操作组件暂不可用，请稍后再试。", "screen_action")
                except Exception:
                    pass
            return
        self.status_label.setText("码铃正在看屏幕…")
        ctrl.handle_request(text, parent_widget=self)

    # ----- v1.3(P1-2): 区域截图直接问（聊天工具按钮 / 热键 / 托盘共用入口）-----
    def capture_screenshot(self) -> None:
        """划屏选区截图 -> 附件条 + 输入框预填引导，**不自动发送**。

        供「🖼 截图」按钮、P1-3 热键 Ctrl+Alt+S、P2-4 托盘动作复用；
        隐私：仅在用户显式操作下截图；选完由用户确认/改字后走既有发送链路。
        """
        if self._screenshot_active:
            return
        self._screenshot_active = True
        try:
            # 主窗可能处于隐藏（热键触发），先呼出并切到聊天页，保证选区后可见可发
            mw = getattr(self.app_ctx, "main_window", None) or self.window()
            if mw is not None:
                try:
                    if not mw.isVisible():
                        mw.showNormal()
                        mw.raise_()
                        mw.activateWindow()
                except Exception:
                    pass
                try:
                    pm = getattr(self.app_ctx, "page_manager", None)
                    if pm is not None and hasattr(pm, "navigate"):
                        pm.navigate("chat")
                except Exception:
                    pass
            try:
                from gui.widgets.screen_capture import capture_region
            except Exception:
                QMessageBox.information(
                    self, "截图", "截图功能暂不可用，可改用「📎 附件」选择一张已有图片。"
                )
                return
            path = capture_region(self)
            if not path:
                return  # 用户取消/不可用（内部已提示）
            ok, reason = self.attachment_bar.add_file_path(path)
            if not ok:
                if reason == "duplicate":
                    self.status_label.setText("截图已在附件列表中")
                elif reason == "too_large":
                    QMessageBox.warning(self, "图片过大", "截图超过 10MB，未添加。")
                else:
                    QMessageBox.warning(self, "添加失败", "截图文件无效，未添加。")
                return
            # 不自动发送：进附件条 + 预填引导文字，用户确认/改字后自行发送
            self.input_edit.setPlainText("帮我看看这张截图…")
            self.input_edit.setFocus()
            self.status_label.setText("截图已加入附件，可修改文字后发送（不会自动发送）")
        finally:
            self._screenshot_active = False

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def eventFilter(self, obj, event) -> bool:
        if obj is self.input_edit and event.type() == event.Type.KeyPress:
            key_event = event
            # v1.7(F10b): @成员补全浮层打开时：方向键选择、Tab/Enter 确认、Esc 关闭
            if getattr(self, "_mention_popup", None) is not None and self._mention_popup.isVisible():
                if key_event.key() == Qt.Key_Up:
                    row = max(0, self._mention_popup.currentRow() - 1)
                    self._mention_popup.setCurrentRow(row)
                    return True
                if key_event.key() == Qt.Key_Down:
                    row = min(self._mention_popup.count() - 1, self._mention_popup.currentRow() + 1)
                    self._mention_popup.setCurrentRow(row)
                    return True
                if key_event.key() == Qt.Key_Tab or key_event.key() == Qt.Key_Return \
                        or key_event.key() == Qt.Key_Enter:
                    self._accept_mention()
                    return True
                if key_event.key() == Qt.Key_Escape:
                    self._hide_mention_popup()
                    return True
                return False
            # 指令补全浮层打开时：方向键选择、Tab/Enter 确认、Esc 关闭
            if self._cmd_popup.isVisible():
                if key_event.key() == Qt.Key_Up:
                    row = max(0, self._cmd_popup.currentRow() - 1)
                    self._cmd_popup.setCurrentRow(row)
                    return True
                if key_event.key() == Qt.Key_Down:
                    row = min(self._cmd_popup.count() - 1, self._cmd_popup.currentRow() + 1)
                    self._cmd_popup.setCurrentRow(row)
                    return True
                if key_event.key() == Qt.Key_Tab:
                    self._accept_command()
                    return True
                if key_event.key() == Qt.Key_Escape:
                    self._hide_command_popup()
                    return True
                if key_event.key() == Qt.Key_Return or key_event.key() == Qt.Key_Enter:
                    if key_event.modifiers() == Qt.ShiftModifier:
                        return False
                    self._accept_command()
                    return True
                return False
            if key_event.key() == Qt.Key_Return or key_event.key() == Qt.Key_Enter:
                if key_event.modifiers() == Qt.ShiftModifier:
                    return False
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 指令补全
    # ==================================================================
    def _adjust_input_height(self) -> None:
        """v1.4.6: 输入框随内容多行增高（Bug6: 上限约 6 行，超出内部滚动）。"""
        try:
            edit = self.input_edit
            # 约 6 行上限：行高取字体行距，加少量内边距余量（随主题字号自适应）
            line_h = edit.fontMetrics().lineSpacing()
            max_h = max(48, line_h * 6 + 16)
            doc_h = int(edit.document().size().height() + 14)
            edit.setFixedHeight(max(48, min(doc_h, max_h)))
            edit.setMaximumHeight(max_h)
        except Exception:
            pass

    def _on_input_text_changed(self) -> None:
        """输入变化时：/ 前缀触发指令补全列表；@ 输入态触发群成员补全（F10b）。"""
        text = self.input_edit.toPlainText()
        if should_trigger_command_popup(text):
            first_line = text.split("\n", 1)[0].strip()
            matches = self._command_registry.search(first_line)
            if matches:
                self._show_command_popup(matches)
            else:
                self._hide_command_popup()
        else:
            self._hide_command_popup()
        # v1.7(F10b): 群聊 @补全（仅群聊会话激活时评估，单聊零开销）
        self._update_mention_popup()

    def _show_command_popup(self, matches) -> None:
        self._cmd_popup.clear()
        for cmd in matches:
            item = QListWidgetItem(f"{cmd['name']}  —  {cmd['description']}")
            item.setData(Qt.UserRole, cmd)
            self._cmd_popup.addItem(item)
        if self._cmd_popup.count() > 0:
            self._cmd_popup.setCurrentRow(0)
            # 定位到输入框上方
            pos = self.input_edit.mapToGlobal(self.input_edit.rect().topLeft())
            self._cmd_popup.move(pos.x(), pos.y() - self._cmd_popup.sizeHint().height() - 4)
            self._cmd_popup.show()
        else:
            self._cmd_popup.hide()

    def _hide_command_popup(self) -> None:
        self._cmd_popup.hide()

    def _accept_command(self) -> None:
        """确认选中的指令：填入模板前缀（如 '/explain '）。"""
        item = self._cmd_popup.currentItem()
        self._hide_command_popup()
        if item is None:
            return
        cmd = item.data(Qt.UserRole)
        if not cmd:
            return
        # 替换首行指令词为完整模板前缀，保留其余输入
        text = self.input_edit.toPlainText()
        lines = text.split("\n")
        lines[0] = cmd["template"]
        self.input_edit.setPlainText("\n".join(lines))
        cursor = self.input_edit.textCursor()
        cursor.movePosition(cursor.End)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    # ==================================================================
    # v1.7(F10b): 群聊 @成员补全（@ 输入态 → 成员名浮层 → 补全插入）
    # ==================================================================
    def _update_mention_popup(self) -> None:
        """按光标前的 @片段刷新成员补全浮层（仅群聊会话；单聊零影响）。"""
        popup = getattr(self, "_mention_popup", None)
        if popup is None:
            return
        session = self._current_group_session()
        if session is None or not _is_group_session(session):
            popup.hide()
            return
        cursor = self.input_edit.textCursor()
        before = self.input_edit.toPlainText()[:cursor.position()]
        partial = _parse_mention_partial(before)
        if partial is None:
            popup.hide()
            return
        roles = self._group_member_roles(session)
        names = _mention_candidates([r.name for r in roles.values()], partial)
        if not names:
            popup.hide()
            return
        popup.clear()
        for name in names:
            item = QListWidgetItem(f"@{name}")
            item.setData(Qt.UserRole, name)
            popup.addItem(item)
        popup.setCurrentRow(0)
        popup.setFixedWidth(max(160, popup.sizeHintForColumn(0) + 24))
        rect = self.input_edit.cursorRect(cursor)
        pos = self.input_edit.mapToGlobal(rect.bottomLeft())
        popup.move(pos.x(), pos.y() + 4)
        popup.show()

    def _hide_mention_popup(self) -> None:
        popup = getattr(self, "_mention_popup", None)
        if popup is not None:
            popup.hide()

    def _accept_mention(self, name: Optional[str] = None) -> None:
        """确认补全：光标前 @片段 → @完整名字 + 空格（保留其余输入）。"""
        popup = getattr(self, "_mention_popup", None)
        if popup is not None:
            popup.hide()
        if not name:
            item = popup.currentItem() if popup is not None else None
            name = item.data(Qt.UserRole) if item is not None else None
        if not name:
            return
        cursor = self.input_edit.textCursor()
        before = self.input_edit.toPlainText()[:cursor.position()]
        after = self.input_edit.toPlainText()[cursor.position():]
        new_before = _apply_mention_completion(before, name)
        self.input_edit.blockSignals(True)
        try:
            self.input_edit.setPlainText(new_before + after)
        finally:
            self.input_edit.blockSignals(False)
        new_cursor = self.input_edit.textCursor()
        new_cursor.movePosition(new_cursor.End)
        self.input_edit.setTextCursor(new_cursor)
        self.input_edit.setFocus()
