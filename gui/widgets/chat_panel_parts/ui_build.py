# -*- coding: utf-8 -*-
"""UI 构建（主布局 / 顶栏 / 会话列表 / 消息区 / 输入区 / 快捷操作栏 / 顶栏图标化 / 信号连接）。

自 ``gui/widgets/chat_panel.py`` **纯移动**（行为不变）。
依赖宿主控件（ChatPanelWidget）的实例状态与方法。
"""
from __future__ import annotations

import logging

from datetime import datetime
from gui import icons
from gui.qt_compat import QCheckBox
from gui.qt_compat import QComboBox
from gui.qt_compat import QFont
from gui.qt_compat import QFrame
from gui.qt_compat import QGridLayout
from gui.qt_compat import QHBoxLayout
from gui.qt_compat import QIcon
from gui.qt_compat import QLabel
from gui.qt_compat import QLineEdit
from gui.qt_compat import QListWidget
from gui.qt_compat import QPushButton
from gui.qt_compat import QScrollArea
from gui.qt_compat import QSize
from gui.qt_compat import QSizePolicy
from gui.qt_compat import QTextEdit
from gui.qt_compat import QVBoxLayout
from gui.qt_compat import QWidget
from gui.qt_compat import Qt
from gui.utils import theme_color
from gui.widgets.attachment_bar import AttachmentBar
from gui.widgets.chat_panel_parts.elided_label import _ElidedLabel
from gui.widgets.message_bubble import resolve_default_speaker_name
from gui.widgets.session_tabs import SessionTabsBar
from gui.widgets.thinking_indicator import ThinkingIndicator
from gui.widgets.tool_trace import ToolTracePanel

logger = logging.getLogger("maid_coder.gui.chat_panel.ui_build")


class ChatUiBuildMixin:
    """UI 构建（主布局 / 顶栏 / 会话列表 / 消息区 / 输入区 / 快捷操作栏 / 顶栏图标化 / 信号连接）（供 ChatPanelWidget 多继承）。"""

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

        # v2.1(UI-Fix-0913) 主题化：会话侧栏颜色走 theme_color，避免换肤后残留默认粉色
        # ⚠ 本方法后续有 `from gui.utils import theme_color` 的局部导入 → theme_color 在本
        #   方法内被判定为**局部名**，故此处必须先局部导入再调用，否则 UnboundLocalError。
        from gui.utils import theme_color
        _txt2 = theme_color(self.app_ctx, "text_secondary", "#5D4037")
        _ac = theme_color(self.app_ctx, "accent", "#FF6B9D")
        _ac_l = theme_color(self.app_ctx, "accent_light", "#FF9EB5")
        _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        _bg_card = theme_color(self.app_ctx, "bg_card", "#FFE4EC")

        ss_header = QHBoxLayout()
        ss_title = QLabel("会话")
        ss_title.setStyleSheet(f"QLabel {{ font-size: 12px; font-weight: bold; color: {_txt2}; }}")
        ss_header.addWidget(ss_title)
        ss_header.addStretch()

        # 新会话圆球：中心显示白色「＋」大号粗体，直观表达「新增会话」（避免空球歧义）。
        self.new_session_btn = QPushButton("＋")
        self.new_session_btn.setFixedSize(24, 24)
        self.new_session_btn.setCursor(Qt.PointingHandCursor)
        self.new_session_btn.setStyleSheet(
            f"QPushButton {{ background: {_ac_l}; color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_ac}; }}"
        )
        self.new_session_btn.setToolTip("新建会话")
        self.new_session_btn.clicked.connect(self._on_new_session)
        ss_header.addWidget(self.new_session_btn)
        ss_layout.addLayout(ss_header)

        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ padding: 6px 8px; border-radius: 6px; color: {_txt2}; }}"
            f"QListWidget::item:selected {{ background: {_bg_card}; color: {_ac}; font-weight: 500; }}"
            f"QListWidget::item:hover {{ background: {_bg_l}; }}"
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
            f"QPushButton {{ background: {_bg_l}; color: {_ac_l}; border: none; border-radius: 4px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {_ac_l}; color: white; }}"
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
        font.setBold(True)
        self.title_label.setFont(font)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_row.addWidget(self.title_label, 1)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("chatSearchEdit")
        self.search_edit.setPlaceholderText("搜索消息...")
        self.search_edit.setMinimumWidth(60)
        self.search_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # v2.1(UI-Fix-0913) 主题化：颜色改走 theme_color，避免换肤后残留默认粉色
        _bg_l = theme_color(self.app_ctx, "bg_light", "#FFF5F7")
        _bd = theme_color(self.app_ctx, "border", "#FFD6E0")
        _ac_l = theme_color(self.app_ctx, "accent_light", "#FF9EB5")
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background: {_bg_l}; border: 1px solid {_bd};"
            f" border-radius: 10px; padding: 2px 8px; font-size: 11px; }}"
            f"QLineEdit:focus {{ border-color: {_ac_l}; }}"
        )
        self.search_edit.textChanged.connect(self._on_search_filter)

        # 正则模式开关
        self.regex_check = QCheckBox("正则")
        self.regex_check.setToolTip("使用正则表达式搜索")
        self.regex_check.setStyleSheet(
            f"QCheckBox {{ color: {_ac_l}; font-size: 11px; spacing: 4px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
        )
        self.regex_check.toggled.connect(lambda _: self._on_search_filter(self.search_edit.text()))

        # 搜索范围切换：当前会话 / 全部会话
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("当前会话", "current")
        self.scope_combo.addItem("全部会话", "all")
        self.scope_combo.setToolTip("搜索范围")
        self.scope_combo.setMinimumContentsLength(4)
        self.scope_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        # v2.1(UI-Fix-0914): 硬编码粉色 → 主题色（此前换主题后此处仍停在粉色系）
        self.scope_combo.setStyleSheet(
            f"QComboBox {{ background: {theme_color(self.app_ctx, 'bg_light', '#FFF5F7')};"
            f" border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFD6E0')};"
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
            # v2.1(UI-Fix-0914): 硬编码紫色 → 主题色（此前换主题后此处仍是紫色系）
            "QPushButton#tabModeBtn {"
            f"  background: transparent; color: {theme_color(self.app_ctx, 'text_secondary', '#8A6D9C')};"
            f"  border: 1px solid {theme_color(self.app_ctx, 'divider', '#D4B5DC')};"
            "  border-radius: 12px; font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#tabModeBtn:checked {"
            f"  background: {theme_color(self.app_ctx, 'primary', '#D4B5DC')};"
            f"  color: {theme_color(self.app_ctx, 'text_on_accent', '#FFFFFF')};"
            f"  border-color: {theme_color(self.app_ctx, 'primary_dark', '#B58FC2')};"
            "}"
            "QPushButton#tabModeBtn:hover {"
            f"  background: {theme_color(self.app_ctx, 'bg_light', '#E8D5EE')};"
            f"  color: {theme_color(self.app_ctx, 'primary_dark', '#6D4A85')};"
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
            f"  background: transparent; color: {theme_color(self.app_ctx, 'primary', '#FF6B9D')};"
            f"  border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
            "  border-radius: 12px; font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#expandChatBtn:hover {"
            f"  background: {theme_color(self.app_ctx, 'primary', '#FF9EB5')};"
            f"  color: {theme_color(self.app_ctx, 'text_on_accent', '#FFFFFF')};"
            f"  border-color: {theme_color(self.app_ctx, 'primary', '#FF9EB5')};"
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

        # v2.1(I-2): 顶栏四按钮图标化（字体可用 → 矢量图标；不可用 → 原 emoji 文本）
        self._apply_title_icons()

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
        # v2.1(UI)：思考文案用**当前角色名**替代固定「AI」
        #   （ThinkingIndicator.start() 每次还会再刷新一次，双保险，切角色后自动跟上）
        try:
            _think_name = resolve_default_speaker_name() or "AI"
        except Exception:
            _think_name = "AI"
        self.thinking_indicator = ThinkingIndicator(
            f"{_think_name} 正在思考", app_context=self.app_ctx, parent=self)
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
                f"QPushButton {{ background: {theme_color(self.app_ctx, 'bg_light', '#FFF0F5')};"
                f" border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
                " border-radius: 8px; font-size: 14px; }"
                f"QPushButton:hover {{ background: {theme_color(self.app_ctx, 'divider', '#FFB6C1')}; }}"
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
                f"QPushButton#quickReplyBtn {{ background: {theme_color(self.app_ctx, 'bg_light', '#FFF0F5')};"
                f" color: {theme_color(self.app_ctx, 'primary', '#FF69B4')};"
                f" border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
                " border-radius: 10px; font-size: 11px; padding: 2px 10px; }"
                f"QPushButton#quickReplyBtn:hover {{ background: {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
                f" color: {theme_color(self.app_ctx, 'text_on_accent', 'white')}; }}"
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
            f"QListWidget#commandPopup {{ background: {theme_color(self.app_ctx, 'bg_card', '#FFFFFF')};"
            f" border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#commandPopup::item { padding: 6px 8px; border-radius: 6px; }"
            f"QListWidget#commandPopup::item:selected {{"
            f" background: {theme_color(self.app_ctx, 'bg_light', '#FFE4EC')};"
            f" color: {theme_color(self.app_ctx, 'primary', '#FF6B9D')}; }}"
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
            f"QListWidget#mentionPopup {{ background: {theme_color(self.app_ctx, 'bg_card', '#FFFFFF')};"
            f" border: 1px solid {theme_color(self.app_ctx, 'divider', '#FFB6C1')};"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#mentionPopup::item { padding: 6px 8px; border-radius: 6px; }"
            f"QListWidget#mentionPopup::item:selected {{"
            f" background: {theme_color(self.app_ctx, 'bg_light', '#FFE4EC')};"
            f" color: {theme_color(self.app_ctx, 'primary', '#FF6B9D')}; }}"
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
        # v2.1(I-2/D-V21-06): 图标位改矢量字形（text_glyph 缺字体自动回落原 emoji）
        self.agent_btn = QPushButton(f"{icons.text_glyph('agent', '🤖')} Agent")
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
        btn_row.addWidget(self.agent_btn)

        # v1.4.7: 任务模式按钮 —— 开启后发送消息走 managed task（自动拆分步骤/自愈/断点恢复）
        self.task_btn = QPushButton(f"{icons.text_glyph('task', '📋')} 任务")
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
        self.web_btn = QPushButton(f"{icons.text_glyph('web', '🌐')} 联网")
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
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
            logger.debug("静默降级：_init_ui 中忽略异常", exc_info=True)
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

    # ==================================================================
    # v2.1(I-2/D-V21-06): 顶栏按钮图标化（矢量图标 + emoji 回退 + hover 重着色）
    # ==================================================================
    def _apply_title_icons(self) -> None:
        """把顶栏四按钮的 emoji/文字图标换成 ``icons.icon``。

        · ``icons.available()`` 为假（字体缺失 / 未注册）→ 回落原 emoji 文本（不空白）；
        · 尺寸与原占位对齐（16px，按钮 32x28 不变），功能与信号零变更；
        · 取色唯一入口：``color=None`` → ``theme_color(app_ctx, "text")``。
        """
        self._icon_buttons = {}
        try:
            use_vector = bool(icons.available())
        except Exception:
            use_vector = False
        for attr, name in self._TITLE_ICON_NAMES.items():
            btn = getattr(self, attr, None)
            if btn is None:
                continue
            if use_vector:
                try:
                    ic = icons.icon(name, self._TITLE_ICON_SIZE, None)
                except Exception:
                    ic = None
                if ic is not None and not ic.isNull():
                    btn.setText("")
                    btn.setIcon(ic)
                    btn.setIconSize(QSize(self._TITLE_ICON_SIZE, self._TITLE_ICON_SIZE))
                    self._icon_buttons[btn] = (name, self._TITLE_ICON_HOVER_KEY.get(attr))
                    # 仅装一次事件过滤器（换肤重着色时重复安装会重复派发事件）
                    if not getattr(btn, "_ml_icon_filter", False):
                        btn.installEventFilter(self)
                        btn._ml_icon_filter = True
                    continue
            # 回退：还原原 emoji 文本、清除可能残留的图标（不空白）
            btn.setIcon(QIcon())
            if not btn.text():
                btn.setText(self._TITLE_ICON_FALLBACK.get(attr, ""))

    def _set_title_icon(self, btn, name: str, color_key) -> None:
        """按取色键重渲染顶栏图标（hover 态重着色）；任一步失败静默保持原样。"""
        try:
            if color_key:
                color = theme_color(self.app_ctx, color_key, "#FFFFFF")
                ic = icons.icon(name, self._TITLE_ICON_SIZE, color)
            else:
                ic = icons.icon(name, self._TITLE_ICON_SIZE, None)
            if ic is not None and not ic.isNull():
                btn.setIcon(ic)
        except Exception:
            logger.debug("静默降级：_set_title_icon 中忽略异常", exc_info=True)

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

        self.attach_btn = QPushButton(f"{icons.text_glyph('attach', '📎')} 附件")
        self.attach_btn.setObjectName("quickActionBtn")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setFixedHeight(28)
        self.attach_btn.clicked.connect(self._on_attach_file)
        quick_layout.addWidget(self.attach_btn)

        self.paste_btn = QPushButton(f"{icons.text_glyph('paste', '📋')} 粘贴")
        self.paste_btn.setObjectName("quickActionBtn")
        self.paste_btn.setCursor(Qt.PointingHandCursor)
        self.paste_btn.setFixedHeight(28)
        self.paste_btn.clicked.connect(self._on_paste_clipboard)
        quick_layout.addWidget(self.paste_btn)

        self.search_btn = QPushButton(f"{icons.text_glyph('search', '🔍')} 搜索")
        self.search_btn.setObjectName("quickActionBtn")
        self.search_btn.setCursor(Qt.PointingHandCursor)
        self.search_btn.setFixedHeight(28)
        self.search_btn.clicked.connect(self._on_search_messages)
        quick_layout.addWidget(self.search_btn)

        self.emoji_btn = QPushButton(f"{icons.text_glyph('emoji', '😊')} 表情")
        self.emoji_btn.setObjectName("quickActionBtn")
        self.emoji_btn.setCursor(Qt.PointingHandCursor)
        self.emoji_btn.setFixedHeight(28)
        self.emoji_btn.clicked.connect(self._on_toggle_emoji_panel)
        quick_layout.addWidget(self.emoji_btn)

        # 第四阶段：语音输入入口
        self.voice_btn = QPushButton(f"{icons.text_glyph('voice', '🎤')} 语音")
        self.voice_btn.setObjectName("quickActionBtn")
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.setFixedHeight(28)
        self.voice_btn.setToolTip("语音输入（依赖 SpeechRecognition + 麦克风）")
        self.voice_btn.clicked.connect(self._on_voice_input)
        quick_layout.addWidget(self.voice_btn)

        # v1.2.2：拍照发图（配合多模态看图；仅拍照一张，不做监控）
        self.camera_btn = QPushButton(f"{icons.text_glyph('camera', '📷')} 拍照")
        self.camera_btn.setObjectName("quickActionBtn")
        self.camera_btn.setCursor(Qt.PointingHandCursor)
        self.camera_btn.setFixedHeight(28)
        self.camera_btn.setToolTip("调起摄像头拍一张，随消息以图片发送给 AI（需模型支持视觉）")
        self.camera_btn.clicked.connect(self._on_camera_capture)
        quick_layout.addWidget(self.camera_btn)

        # v1.3(P1-2): 区域截图直接问 —— 截图选区进附件条 + 预填引导，不自动发送；
        # 同入口供 P1-3 全局热键 Ctrl+Alt+S 与 P2-4 托盘「🖼 截图」复用。
        self.screenshot_btn = QPushButton(f"{icons.text_glyph('screenshot', '🖼')} 截图")
        self.screenshot_btn.setObjectName("quickActionBtn")
        self.screenshot_btn.setCursor(Qt.PointingHandCursor)
        self.screenshot_btn.setFixedHeight(28)
        self.screenshot_btn.setToolTip("划屏选区截图，作为图片问码铃（Ctrl+Alt+S / 托盘可触发）")
        self.screenshot_btn.clicked.connect(self.capture_screenshot)
        quick_layout.addWidget(self.screenshot_btn)

        # v1.3(P2-1): 小游戏 —— 她当荷官（纯确定性随机、零计分无数值）
        self.game_btn = QPushButton(f"{icons.text_glyph('game', '🎲')} 小游戏")
        self.game_btn.setObjectName("quickActionBtn")
        self.game_btn.setCursor(Qt.PointingHandCursor)
        self.game_btn.setFixedHeight(28)
        self.game_btn.setToolTip("抛硬币 / 抽签 / 猜拳 / 21 点，和码铃玩一小局")
        self.game_btn.clicked.connect(self._open_mini_games)
        quick_layout.addWidget(self.game_btn)

        # v1.3(P2-2): 免提对话开关 —— 与既有「🎤 语音」并存（单次语音 = 弹窗，免提 = 连续对话）
        self.handsfree_btn = QPushButton(f"{icons.text_glyph('handsfree', '🎙')} 免提")
        self.handsfree_btn.setObjectName("quickActionBtn")
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
        self.watch_btn = QPushButton(f"{icons.text_glyph('watch', '👀')} 看屏")
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
        self.computer_btn = QPushButton(f"{icons.text_glyph('computer', '🖱')} 操作")
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
            logger.debug("静默降级：_setup_quick_actions 中忽略异常", exc_info=True)

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
                logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)
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
                # v2.1(UI-Fix-0913)：走 effective_avatar()，让 avatar 字段为 null 的
                # 预设角色（如 preset_whale）也能用上包内资源，而非一律回落女仆主形象。
                try:
                    self._current_role_avatar = _default_role.effective_avatar()
                except Exception:
                    self._current_role_avatar = str(getattr(_default_role, "avatar", "") or "")
        except Exception:
            self._current_role_avatar = ""
        try:
            _rb = getattr(self.app_ctx, "role_bridge", None)
            if _rb is not None and hasattr(_rb, "role_changed"):
                _rb.role_changed.connect(self._on_role_avatar_changed)
        except Exception:
            logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

        # v1.3(P1-1): TTS 朗读归属变化 -> 刷新气泡「朗读/停止」按钮态
        tts = getattr(self.app_ctx, "tts", None)
        if tts is not None and hasattr(tts, "state_changed"):
            try:
                tts.state_changed.connect(self._on_tts_state_changed)
            except Exception:
                logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

