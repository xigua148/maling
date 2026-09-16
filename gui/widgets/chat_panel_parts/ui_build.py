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

        # v2.2.1(换肤一致性)：本方法不再内联取色 —— 全部主题化内联样式已集中到
        # `_apply_chat_theme()`（唯一取色入口），由 `_init_ui` 末尾统一调用一次。
        # 于是「构造期」与「换肤期」共用同一份样式字符串，不再存在两通道写歪的可能
        # （实锤：search_edit 常态描边在 ui_build 取 border、在 interactions 取
        #  accent_light；而 accent_light ≡ bg_light ⇒ 一切皮肤描边直接消失）。

        ss_header = QHBoxLayout()
        # v2.2.1(换肤一致性)：改为实例属性 —— 换肤时需重取 text_secondary
        self.sidebar_title_label = QLabel("会话")
        ss_header.addWidget(self.sidebar_title_label)
        ss_header.addStretch()

        # 新会话圆球：中心显示白色「＋」大号粗体，直观表达「新增会话」（避免空球歧义）。
        self.new_session_btn = QPushButton("＋")
        # v2.2.1(黑框修复 WP1)：补 id —— 24×24 定尺寸下通用 padding 8/20 会把内容区
        # 压成 -16×8，「＋」字形不绘制（空球）。padding 归零收口在 base.qss §1c。
        self.new_session_btn.setObjectName("newSessionBtn")
        self.new_session_btn.setFixedSize(24, 24)
        self.new_session_btn.setCursor(Qt.PointingHandCursor)
        self.new_session_btn.setToolTip("新建会话")
        self.new_session_btn.clicked.connect(self._on_new_session)
        ss_header.addWidget(self.new_session_btn)
        ss_layout.addLayout(ss_header)

        self.session_list = QListWidget()
        self.session_list.setObjectName("sessionList")
        self.session_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._show_session_menu)
        self.session_list.itemClicked.connect(self._on_session_selected)
        ss_layout.addWidget(self.session_list, 1)

        # 折叠按钮
        self.toggle_sidebar_btn = QPushButton("◀")
        # v2.2.1(黑框修复 WP1)：补 id —— 20×60 定尺寸下通用 padding 8/20 会把内容区
        # 压成 -20×44，「◀」字形不绘制。padding 归零收口在 base.qss §1c。
        self.toggle_sidebar_btn.setObjectName("toggleSidebarBtn")
        self.toggle_sidebar_btn.setFixedSize(20, 60)
        self.toggle_sidebar_btn.setCursor(Qt.PointingHandCursor)
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
        self.search_edit.textChanged.connect(self._on_search_filter)

        # 正则模式开关
        self.regex_check = QCheckBox("正则")
        self.regex_check.setToolTip("使用正则表达式搜索")
        self.regex_check.toggled.connect(lambda _: self._on_search_filter(self.search_edit.text()))

        # 搜索范围切换：当前会话 / 全部会话
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("当前会话", "current")
        self.scope_combo.addItem("全部会话", "all")
        self.scope_combo.setToolTip("搜索范围")
        self.scope_combo.setMinimumContentsLength(4)
        self.scope_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.scope_combo.currentIndexChanged.connect(lambda _: self._on_search_filter(self.search_edit.text()))

        title_row.addStretch()

        # 图标按钮收纳：导出 / 标签页 / 展开（窄面板下不再与文字按钮挤同一行）
        self.export_btn = QPushButton("📤")
        self.export_btn.setObjectName("exportChatBtn")
        self.export_btn.setFixedSize(32, 28)
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setToolTip("导出聊天记录（Markdown / TXT / JSON）")
        # v2.2.1(换肤一致性)：内联样式已收口到 `_apply_chat_theme()`（唯一取色入口）——
        # 原为构造期一次性内联裸色（#4A90D9 / #A8C8E8 / hover #FFFFFF），
        # 在 `_init_ui` 调用的那一刻求值一次 ⇒ 切主题不再重刷，四套皮肤下恒为同一支蓝。
        self.export_btn.clicked.connect(self._on_export_chat)
        title_row.addWidget(self.export_btn)

        # 第四阶段：标签页模式开关
        self.tab_mode_btn = QPushButton("🗂")
        self.tab_mode_btn.setObjectName("tabModeBtn")
        self.tab_mode_btn.setCheckable(True)
        self.tab_mode_btn.setFixedSize(32, 28)
        self.tab_mode_btn.setCursor(Qt.PointingHandCursor)
        self.tab_mode_btn.setToolTip("切换标签页模式（浏览器式 tab）")
        self.tab_mode_btn.toggled.connect(self._on_toggle_tab_mode)
        title_row.addWidget(self.tab_mode_btn)

        self.expand_btn = QPushButton("↗")
        self.expand_btn.setObjectName("expandChatBtn")
        self.expand_btn.setFixedSize(32, 28)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setToolTip("展开为独立聊天窗口")
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
        self._cmd_popup.itemDoubleClicked.connect(lambda _: self._accept_command())
        self._cmd_popup.hide()

        # v1.7(F10b): 群聊 @ 成员补全浮层（@ 输入态触发，复用指令浮层的轻实现）
        self._mention_popup = QListWidget(self)
        self._mention_popup.setObjectName("mentionPopup")
        self._mention_popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self._mention_popup.setFocusPolicy(Qt.NoFocus)
        self._mention_popup.setFixedWidth(220)
        self._mention_popup.setMaximumHeight(180)
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
        # v2.2.1(换肤一致性)：内联样式已收口到 `_apply_chat_theme()`（唯一取色入口）——
        # 原字色为裸 `#FFFFFF`，落 `#FF6B6B` 实底四套主题一致只有 2.775（<4.5），
        # 与 chat_window 的 #chatStopBtn 同一缺陷、同一修法（改走 text_on_accent）。
        self.stop_btn.clicked.connect(self._on_stop_generation)
        self.stop_btn.setVisible(False)
        btn_row.addWidget(self.stop_btn)

        # v1.1(agent): Agent 模式开关 —— 开启后消息走 AgentEngine 工具循环
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
        self.task_btn.toggled.connect(self._on_toggle_task_mode)
        btn_row.addWidget(self.task_btn)

        # v1.5.0: 「🌐 联网」开关 —— 开启后普通聊天命中检索意图时自动联网搜索并注入上下文
        # （引擎优先级：博查(有key) > cn.bing.com 解析 > ddgs；详见 helpers.WebSearch）。
        # 状态持久化在 GuiConfig.web_search_enabled_gui；Agent 模式不受本开关影响（其自带 web_search 工具）。
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

        # v2.2.1(换肤一致性)：全部主题化内联样式在此统一落一次（唯一取色入口）。
        # 换肤时 `_on_theme_changed` 会再调一次同一方法 —— 构造期与换肤期共用同一份
        # 样式字符串，不可能出现「构造时一套、换肤后另一套」。
        self._apply_chat_theme()

    # ==================================================================
    # v2.2.1(换肤一致性)：聊天面板内联样式的唯一取色入口
    # ==================================================================
    def _apply_chat_theme(self) -> None:
        """按当前主题重写聊天面板的全部内联样式（构造期 / 换肤期共用）。

        为什么收成一处：内联 ``setStyleSheet`` 的颜色在**调用那一刻**求值，换肤不会
        自动重来。此前这批字符串散落在 ``_init_ui``、``_setup_quick_actions`` 与
        ``ChatInteractionsMixin._apply_sidebar_theme`` 三处，只要有一处漏改或写歪，
        就会出现「构造期一套色、换肤后另一套色」。

        实锤（本轮任务 A）：``search_edit`` 常态描边在 ``ui_build`` 取 ``border``、在
        ``interactions`` 取 ``accent_light``；而四套主题里 ``accent_light ≡ bg_light``
        ⇒ 一切一次皮肤，描边就与底色同色（对比度 1.000）「凭空消失」。

        幂等：``setStyleSheet`` 是整体覆盖而非追加，且每次都由当前主题重新解析，
        重复调用不会叠加、不会写回旧值；「已勾选 / 悬停」态由 QSS 伪状态自行决定，
        不受本方法重复调用影响。

        取色口径（承 v2.2.1 配色收口，实测见 ``_fix_panel/contrast_report.txt``）：
        · 淡底（``bg_light`` / ``bg_card`` / 页底 ``bg``）上的文字 → ``text`` 或
          ``accent_text``；``accent`` / ``accent_light`` 是**填充色**，不作文字前景；
        · ``accent`` 实底上的文字 → ``text_on_accent``；
        · 常态描边 → ``border``；焦点描边 → ``focus_accent``（与常态必须可区分）。
        """
        ctx = getattr(self, "app_ctx", None)
        if ctx is None:
            return
        _txt2 = theme_color(ctx, "text_secondary", "#5D4037")
        _ac = theme_color(ctx, "accent", "#FF6B9D")
        _ac_l = theme_color(ctx, "accent_light", "#FFF0F3")
        _bg_l = theme_color(ctx, "bg_light", "#FFF0F3")
        _bg_card = theme_color(ctx, "bg_card", "#FFE4EC")
        _ac_text = theme_color(ctx, "accent_text", "#B45073")
        _on_ac = theme_color(ctx, "text_on_accent", "#FFFFFF")
        _txt = theme_color(ctx, "text", "#4A4A4A")
        _bd = theme_color(ctx, "border", "#FFD6E0")
        _div = theme_color(ctx, "divider", "#FFB6C1")
        _primary = theme_color(ctx, "primary", "#FF9EB5")
        _primary_dark = theme_color(ctx, "primary_dark", "#E0527F")
        # 任务 A：常态描边与焦点圈必须是两个不同键。
        # v2.2.1：焦点圈由 focus_accent 改取 accent_text。焦点圈属「非文本图形」
        # （WCAG 1.4.11 需 ≥3:1），而本控件自身底是 bg_light；focus_accent 落其上
        # 实测仅 2.783 / 1.931 / 5.317 / 2.814（3/4 套不达标），accent_text 落 bg_light
        # 为 4.125 / 4.397 / 5.335 / 4.280，四套全达标。与常态描边（border）仍是两键。
        _focus = theme_color(ctx, "accent_text", _ac)

        def _ssw(widget, css: str) -> None:
            """给单个控件覆盖样式；控件为 None / 异常时静默跳过，绝不阻断其余控件换肤。"""
            if widget is None:
                return
            try:
                widget.setStyleSheet(css)
            except Exception:
                logger.debug("静默降级：_apply_chat_theme 中忽略异常", exc_info=True)

        def _ss(name: str, css: str) -> None:
            _ssw(getattr(self, name, None), css)

        # --- 顶栏文字标签：去自带底色（应用级 ${bg} 会盖在页底上）---
        # 实测（真实平台 + 不 show + render 到哨兵底）：控件级只写
        # `QLabel { background: transparent; }` **不会**压掉主题里的
        # `QLabel#chatStatusLabel { color/font-size }`（两态渲染色 37px 完全一致），
        # 故无需在此重复颜色，避免造第二处取色源。
        _ss("title_label", "QLabel { background: transparent; }")
        _ss("status_label", "QLabel { background: transparent; }")

        # --- 左侧会话侧栏 ---
        # v2.2.2(缺陷2)：「会话」标题裸 QLabel 被应用级 ${bg} 刷底，而 #sessionSidebar
        #   的底是 bg_card（四套主题二者均不同值）→ 与侧栏底不同色的一条色块。
        _ss("sidebar_title_label",
            f"QLabel {{ background: transparent; font-size: 12px;"
            f" font-weight: bold; color: {_txt2}; }}")

        _ss("new_session_btn",
            f"QPushButton {{ background: {_ac_l}; color: {_txt}; border: none;"
            f" border-radius: 12px; font-size: 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {_ac}; color: {_on_ac}; }}")

        # 悬停底 bg_light 随主题翻转，原未声明 color → 继承 ::item 的 text_secondary
        # （不随主题翻转的次级灰）→ ui_night 明/暗 4.285、三套浅色 3.840~4.010 均 <4.5。
        # 显式补 bg_light 的配对文字色 text。
        _ss("session_list",
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ padding: 6px 8px; border-radius: 6px; color: {_txt2}; }}"
            f"QListWidget::item:selected {{ background: {_bg_card}; color: {_ac_text}; font-weight: 500; }}"
            f"QListWidget::item:hover {{ background: {_bg_l}; color: {_txt}; }}")

        # 折叠钮：常态 bg_light 淡底 + text（11.56~14.49）；悬停 accent 实底 + text_on_accent。
        # 原 `background: accent_light; color: accent_light` 在四风格下同值恒 1.000。
        _ss("toggle_sidebar_btn",
            f"QPushButton {{ background: {_bg_l}; color: {_txt}; border: none;"
            f" border-radius: 4px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {_ac}; color: {_on_ac}; }}")

        # --- 顶栏：搜索区 ---
        # 任务 A：常态描边与焦点圈分键 —— 切肤后描边不再与底色同色而「消失」，
        # 键盘 Tab 进来也能看见焦点圈（focus 与常态本身也不同色）。
        _ss("search_edit",
            f"QLineEdit {{ background: {_bg_l}; border: 1px solid {_bd};"
            f" border-radius: 10px; padding: 2px 8px; font-size: 11px; }}"
            f"QLineEdit:focus {{ border-color: {_focus}; }}")

        # 实测该控件底色是页底 bg（#F7F7F8/#FFF8F3/#131114/#EEF6FA），
        # 原取 accent_light ≡ bg_light ⇒ 1.05~1.22 近乎不可见；改 accent_text（4.511~7.039）。
        _ss("regex_check",
            f"QCheckBox {{ color: {_ac_text}; font-size: 11px; spacing: 4px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}")

        _ss("scope_combo",
            f"QComboBox {{ background: {_bg_l}; border: 1px solid {_div};"
            " border-radius: 10px; padding: 2px 4px; font-size: 11px; }")

        # --- 顶栏：标签页 / 展开 图标按钮 ---
        _ss("tab_mode_btn",
            "QPushButton#tabModeBtn {"
            f"  background: transparent; color: {_txt2};"
            f"  border: 1px solid {_div};"
            "  border-radius: 12px; font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#tabModeBtn:checked {"
            f"  background: {_primary}; color: {_on_ac}; border-color: {_primary_dark};"
            "}"
            # hover 原取 primary_dark 作文字前景，落 bg_light 四风格 3.144/2.538/3.853/3.841
            # 全 < 4.5 ⇒ 改 text（11.56~14.49）。
            "QPushButton#tabModeBtn:hover {"
            f"  background: {_bg_l}; color: {_txt};"
            "}")

        _ss("expand_btn",
            "QPushButton#expandChatBtn {"
            # 原取 primary（= accent 填充色）作文字前景，落页底 bg 3.051/2.057/7.014/2.966
            # （三风格 < 4.5）⇒ 改 accent_text。
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_div};"
            "  border-radius: 12px; font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#expandChatBtn:hover {"
            f"  background: {_primary}; color: {_on_ac}; border-color: {_primary};"
            "}")

        # 导出按钮（与 expandChatBtn 同排同款 32x28）：
        # 原为**构造期一次性内联裸色**（常态 #4A90D9 字 + #A8C8E8 描边、hover 实底
        # #4A90D9 + #FFFFFF 字）—— 与全站强调色体系脱节，且 `setStyleSheet` 在
        # `_init_ui` 那一刻求值一次 ⇒ 四套皮肤下恒为同一支蓝，换肤完全不跟随。
        # 现改为令牌下发：常态字色与描边取 accent_text（落页底 bg，8 档 ≥4.511 ⇒ 8/8 达标）、
        # hover 实底取 accent 填充 + text_on_accent 字色（8 档 ≥5.192 ⇒ 8/8 达标）。
        _ss("export_btn",
            "QPushButton#exportChatBtn {"
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_ac_text};"
            "  border-radius: 12px; font-size: 12px; padding: 0px;"
            "}"
            "QPushButton#exportChatBtn:hover {"
            f"  background: {_ac}; color: {_on_ac}; border-color: {_ac};"
            "}")

        # 风格切换按钮（🎨，与 export/tabMode/expand 同排同尺寸 32×28）：
        # v2.2.1(黑框修复·二轮)：本控件是全仓**唯一**没有控件级 sheet 的同排按钮 ——
        #   于是整条样式都回落到应用级通用 `QPushButton`（含 `padding: 8px 20px`）⇒
        #   内容区实测 **-8×12**，🎨 一个像素都画不出来（补 padding:0 后 111 px）。
        #   三个兄弟早已各自声明 `padding: 0px`，此处只补这一条，**不动** 底色 / 字色 /
        #   圆角 / 字号（它们本就是通用按钮观感，本次不改观感）。
        _ss("style_btn",
            "QPushButton#styleSwitchBtn {"
            "  padding: 0px;"
            "}")

        # --- 表情面板 / 快捷回复（多控件，逐个覆盖） ---
        # 表情按钮常态底 bg_light、悬停底 divider，二者均**随主题翻转**（深色下是深底）；
        # 本 sheet 原未声明 color → 常态回落 app 级 QPushButton 的 text_on_accent
        # （「亮强调实底上的深字」）→ 深底深字，深色四风格实测 1.089~1.360 近不可见。
        # 与 bg_light 配对的文字键是 text（同样随主题翻转），显式补上。
        _emoji_css = (
            # v2.2.1(黑框修复·二轮)：补 padding 归零 —— 本组按钮 setFixedSize(44, 36)，
            #   通用 padding 8/20 把内容区压成 2×18，emoji 只剩 4~11 个像素（「一排空白方块」）。
            f"QPushButton {{ background: {_bg_l}; color: {_txt}; border: 1px solid {_div};"
            " padding: 0px;"
            " border-radius: 8px; font-size: 14px; }"
            f"QPushButton:hover {{ background: {_div}; color: {_txt}; }}"
        )
        _emoji_panel = getattr(self, "emoji_panel", None)
        if _emoji_panel is not None:
            for _b in _emoji_panel.findChildren(QPushButton):
                _ssw(_b, _emoji_css)

        # 常态 / 悬停底色都是淡底（bg_light / divider）：原字色 primary 落 bg_light 仅
        # 2.783/1.931/5.317/2.814、悬停 text_on_accent 落 divider 在 ui_night 仅 1.120
        # （深字落深底）⇒ 淡底统一 text（常态 11.56~14.49 / 悬停 10.24~14.96）。
        _qr_css = (
            f"QPushButton#quickReplyBtn {{ background: {_bg_l}; color: {_txt};"
            f" border: 1px solid {_div};"
            " border-radius: 10px; font-size: 11px; padding: 2px 10px; }"
            f"QPushButton#quickReplyBtn:hover {{ background: {_div}; color: {_txt}; }}"
        )
        for _b in self.findChildren(QPushButton, "quickReplyBtn"):
            _ssw(_b, _qr_css)
            # 构造期是先上样式再算 sizeHint（padding / font-size 会影响宽度），
            # 样式搬到这里后必须补算一次，否则最小宽会按默认样式偏窄。
            try:
                _b.setMinimumWidth(_b.sizeHint().width())
            except Exception:
                logger.debug("静默降级：_apply_chat_theme 中忽略异常", exc_info=True)

        # --- 指令 / @ 补全浮层 ---
        _ss("_cmd_popup",
            f"QListWidget#commandPopup {{ background: {_bg_card};"
            f" border: 1px solid {_div};"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#commandPopup::item { padding: 6px 8px; border-radius: 6px; }"
            # 选中行底色是 bg_light 淡底，原取 primary 实测 2.783/1.931/5.317/2.814 ⇒ text。
            f"QListWidget#commandPopup::item:selected {{"
            f" background: {_bg_l}; color: {_txt}; }}")

        _ss("_mention_popup",
            f"QListWidget#mentionPopup {{ background: {_bg_card};"
            f" border: 1px solid {_div};"
            " border-radius: 8px; padding: 4px; font-size: 12px; }"
            "QListWidget#mentionPopup::item { padding: 6px 8px; border-radius: 6px; }"
            f"QListWidget#mentionPopup::item:selected {{"
            f" background: {_bg_l}; color: {_txt}; }}")

        # --- 模式开关：Agent / 任务 / 联网 ---
        # 常态字色原取 accent（填充色），落输入区卡片底（实测 bg_card）3.267/2.163/
        # 6.485/3.245 ⇒ accent_text；:checked 实底 accent 上的 #FFFFFF 只有 3.267/2.163/
        # 2.678/3.245 ⇒ text_on_accent；:hover 原先未声明 color，落 bg_light 时回落 accent
        # （2.783/1.931/5.317/2.814），且「已勾选 + 悬停」白字落 bg_light 仅 1.174/1.120/
        # 14.238/1.153 ⇒ 显式声明 text。
        _ss("agent_btn",
            "QPushButton#agentModeBtn {"
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_ac}; border-radius: 10px;"
            "  font-size: 13px; padding: 6px 16px;"
            "}"
            "QPushButton#agentModeBtn:checked {"
            f"  background: {_ac}; color: {_on_ac}; border-color: {_ac};"
            "}"
            f"QPushButton#agentModeBtn:hover {{ background: {_bg_l}; color: {_txt}; }}")

        _ss("task_btn",
            "QPushButton#taskModeBtn {"
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_ac}; border-radius: 10px;"
            "  font-size: 13px; padding: 6px 16px;"
            "}"
            "QPushButton#taskModeBtn:checked {"
            f"  background: {_ac}; color: {_on_ac}; border-color: {_ac};"
            "}"
            f"QPushButton#taskModeBtn:hover {{ background: {_bg_l}; color: {_txt}; }}")

        _ss("web_btn",
            "QPushButton#webSearchBtn {"
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_ac}; border-radius: 10px;"
            "  font-size: 13px; padding: 6px 16px;"
            "}"
            "QPushButton#webSearchBtn:checked {"
            f"  background: {_ac}; color: {_on_ac}; border-color: {_ac};"
            "}"
            f"QPushButton#webSearchBtn:hover {{ background: {_bg_l}; color: {_txt}; }}")

        # 停止生成（输入区）：原为**构造期一次性内联**裸色 —— 字色裸 `#FFFFFF` 落
        # `#FF6B6B` 实底上，四套主题一致只有 2.775（< 小字 AA 4.5），白字近不可辨；
        # 且同样换肤不重刷。修法与 `chat_window.chatStopBtn` 完全一致：字色走
        # text_on_accent（实底上的文字令牌）。
        # 实测（8 档 = 4 风格 × 明暗）：常态底 #FF6B6B 上 6.131/4.664/6.258/6.071
        # （浅）/6.131/6.131/6.258/4.978（深）⇒ 8/8 达标，最差 4.664。
        # hover 底 #FF5252 上 5.332/4.056/5.442/5.279（浅）/5.332/5.332/5.442/4.329（深）
        # ⇒ 6/8 达标，ui_cream/浅 4.056 与 ui_whale/深 4.329 未达 4.5（差 0.44 / 0.17）。
        # 底色 `#FF6B6B` / hover `#FF5252` 与 chat_window 的 #chatStopBtn 保持同值
        # （同一交互的两个入口），属既有裸值残留；hover 两档未达标见回传「需 owner 决策」
        # （选项：为 danger 实底立专用 on-color 令牌 / 取消 hover 变色，二者均越界）。
        _ss("stop_btn",
            "QPushButton#stopBtn {"
            "  background: #FF6B6B;"
            f"  color: {_on_ac};"
            "  border: none; border-radius: 10px;"
            "  font-size: 13px; padding: 6px 16px;"
            "}"
            "QPushButton#stopBtn:hover { background: #FF5252; }")

        # --- 意图 / 场景 小型下拉（同款） ---
        # 下拉列表的 selection-color 原是硬编码 #4A4A4A，而 selection-background 是
        # bg_light —— ui_night 深底深字仅 1.12 ⇒ 改 text（12.50~14.96）。
        # （列表底色 #FFFFFF / #4A4A4A 为既有硬编码，本轮只登记不改，见裁决 2。）
        for _name, _oid in (("intent_combo", "intentModeCombo"),
                            ("scene_combo", "sceneModeCombo")):
            _ss(_name,
                f"QComboBox#{_oid} {{"
                f"  background: transparent; color: {_ac_text};"
                f"  border: 1px solid {_ac}; border-radius: 10px;"
                "  font-size: 13px; padding: 6px 10px;"
                "}"
                f"QComboBox#{_oid}::drop-down {{ border: none; width: 18px; }}"
                f"QComboBox#{_oid} QAbstractItemView {{"
                "  background: #FFFFFF; color: #4A4A4A;"
                f"  selection-background-color: {_bg_l}; selection-color: {_txt};"
                "}")

        # --- 看屏 / 操作 快捷开关 ---
        # 常态字色原取 accent（填充色），落快捷栏页底（实测 bg）3.051/2.057/7.014/2.966；
        # :checked 实底 accent 上的 #FFFFFF 仅 3.267/2.163/2.678/3.245 ⇒ text_on_accent。
        _sw_css = (
            "QPushButton#watchToggleBtn, QPushButton#computerToggleBtn {"
            f"  background: transparent; color: {_ac_text};"
            f"  border: 1px solid {_ac}; border-radius: 12px;"
            "  font-size: 12px; padding: 2px 12px;"
            "}"
            "QPushButton#watchToggleBtn:checked, QPushButton#computerToggleBtn:checked {"
            f"  background: {_ac}; color: {_on_ac}; border-color: {_ac};"
            "}"
            "QPushButton#watchToggleBtn:hover, QPushButton#computerToggleBtn:hover {"
            f"  background: {_bg_l}; color: {_txt};"
            "}"
        )
        _ss("watch_btn", _sw_css)
        _ss("computer_btn", _sw_css)

        # v2.2.2(P4 根因的兜底重出图)：本方法是面板内联样式的**唯一取色入口**，
        #   构造期与换肤期都经由它 ⇒ 在此重出一次顶栏图标。实测（`_evidence_b/
        #   out_p4_real_*.txt`）：换肤路径本已由 `ChatInteractionsMixin._on_theme_changed`
        #   调过一次 `_apply_title_icons()`（`interactions.py:572`），本次追加是**幂等
        #   兜底** —— 目的是让「取色入口」这一条出口自洽（不依赖另一个 mixin 记得调），
        #   并在将来 `main.py` 顺序变动时仍有一次重出图机会。
        #   ⚠ 真正把四键从纯黑救回来的不是这一行（本方法在构造期同样早于
        #   `icons.configure`），而是上面 `_apply_title_icons()` 的**显式传色**。
        self._apply_title_icons()

    # ==================================================================
    # v2.1(I-2/D-V21-06): 顶栏按钮图标化（矢量图标 + emoji 回退 + hover 重着色）
    # ==================================================================
    def _apply_title_icons(self) -> None:
        """把顶栏四按钮的 emoji/文字图标换成 ``icons.icon``。

        · ``icons.available()`` 为假（字体缺失 / 未注册）→ 回落原 emoji 文本（不空白）；
        · 尺寸与原占位对齐（16px，按钮 32x28 不变），功能与信号零变更；
        · 取色唯一入口：**显式传色** —— ``theme_color(self.app_ctx, "text")``。
          v2.2.2(P4 根因·跨文件注册顺序)：原先传 ``color=None``，让 ``icons.icon()``
          自己去 ``icons._app_ctx`` 取色；而 ``icons._app_ctx`` 由 ``gui/main.py``
          的 ``icons.configure(app_ctx)`` 注入，**晚于** ``MainWindow`` 构造
          （实测：``main.py:1633`` 构造 → ``:1640`` configure）。构造期那一刻
          ``icons._app_ctx is None`` ⇒ ``theme_color`` 回落
          ``icons._FALLBACK_TEXT_COLOR = "#000000"``，纯黑 pixmap 被写进
          ``QPixmapCache``（键含色值，故此后不会自动失效）⇒ 默认流程（不换肤）
          四键**整个会话纯黑**，深色主题下近乎不可见。
          面板自己的 ``app_ctx`` 从构造起就可用、且 ``theme_engine`` 与
          ``icons._app_ctx.theme_engine`` 是同一个 ⇒ 显式传色**语义完全等价**，
          但不再依赖任何跨文件的初始化顺序。
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
                    # v2.2.2(P4 根因)：显式传本面板 `text` 令牌色，不依赖
                    # `icons.configure()` 是否已跑过（见 docstring 的取色说明）。
                    ic = icons.icon(
                        name, self._TITLE_ICON_SIZE,
                        theme_color(self.app_ctx, "text", "#000000"))
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
                # v2.2.2(P4 根因·同类)：同一缺陷类 —— 别处也不许再以 `color=None`
                #   出图（那会退回依赖 `icons._app_ctx`）。显式传本面板 `text` 令牌色。
                ic = icons.icon(
                    name, self._TITLE_ICON_SIZE,
                    theme_color(self.app_ctx, "text", "#000000"))
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
        # v2.2.2(P6-B)：依赖缺失时**置灰 + tooltip 写明原因** —— 此前按钮恒可点，用户
        #   要先付出一次无效点击才看到说明框。诊断走 `voice_input` 的既有入口
        #   （`voice_input_button_state()`，内部复用 `diagnose_voice_input()`，
        #   未另写一套探测），形态与「免提」按钮一致
        #   （见 `chat_panel_parts/extras.py::_init_handsfree` 的 setEnabled + 原因 tooltip）。
        #   ⚠ 只改**可用性呈现**：`_on_voice_input` 的运行时守卫保留（托盘等其它入口仍
        #   可触达），识别逻辑零改动。
        try:
            from gui.widgets import voice_input as _voice_mod
            _voice_ok, _voice_tip = _voice_mod.voice_input_button_state()
            self.voice_btn.setEnabled(_voice_ok)
            self.voice_btn.setToolTip(_voice_tip)
        except Exception:
            logger.debug("静默降级：语音入口可用性诊断失败，保持默认可点", exc_info=True)
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

