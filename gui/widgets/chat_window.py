"""独立聊天窗口 —— 无边框圆角浮窗，支持拖拽移动、消息列表、输入发送、文件拖拽附件。"""
from __future__ import annotations

import os
from typing import List, Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QScrollArea, QFrame, Qt, QSizePolicy, QFont,
    QApplication, QGraphicsDropShadowEffect, QColor, QPoint,
    QGridLayout, QSystemTrayIcon, QMenu, QAction, Signal, QObject,
    QFileDialog, QMessageBox, QDialog, QDragEnterEvent, QDropEvent,
    QDragMoveEvent,
)
from gui.utils import theme_color
from gui.widgets.message_bubble import MessageBubble
from gui.widgets.thinking_indicator import ThinkingIndicator
from gui.widgets.attachment_bar import AttachmentBar
from gui.widgets import voice_input as voice_input_mod
from gui.chat_exporter import ChatExporter

# v1.4：自绘标题栏窗口控制按钮尺寸（宽 ≥28、高 ≥24，符号才看得清）
_TITLE_BTN_WIDTH = 32
_TITLE_BTN_HEIGHT = 26
# 标题栏控制按钮：符号 / 中文 tooltip / 字号
_TITLE_BUTTONS = (
    # (符号, tooltip, 字号)
    ("−", "最小化", 20),
    ("□", "最大化/还原", 17),
    ("✕", "关闭", 17),
)


class ChatWindow(QWidget):
    """独立聊天窗口：无边框、圆角、可拖拽、与主窗聊天页可共存。"""

    attach_requested = Signal()
    """用户点击"合并"按钮时发出，通知主面板重新显示聊天区。"""

    user_message_sent = Signal(str, list)
    """R6: 窗口发送用户消息时发出 (display_text, attachments)，
    由主面板统一渲染并持久化，使两条发送路径落同一份会话数据。"""

    # 内置颜文字/符号表情
    EMOJIS = ["❤", "✨", "(｡･ω･｡)", "(´▽｀)", "(*´∀`)~♥", "(๑•̀ㅂ•́)و✧",
              "(｡♥‿♥｡)", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "(｡◕‿◕｡)", "♪(´ε｀ )", "(≧▽≦)", "(｡･ω･｡)ﾉ♡"]

    # 快捷回复（主人视角：用户点击后发给女仆的常用语）
    QUICK_REPLIES = [
        "辛苦了~",
        "做得不错❤",
        "继续吧",
        "等等，我有别的事说",
    ]

    def __init__(self, app_context, parent: Optional[QWidget] = None):
        # Qt.Window 窗口类型标志不可省略：有 parent 时若缺省为 Qt.Widget，
        # 本控件会退化为面板内嵌子控件（isWindow()==False），setGeometry 的
        # 屏幕坐标与 show()/activateWindow() 均无法呈现为顶层窗口。
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.app_ctx = app_context
        self.chat_service = getattr(app_context, "chat_service", None)
        self._last_role: Optional[str] = None
        self._drag_pos = QPoint()
        self._is_dragging = False
        self._stream_buffer = ""
        self._current_ai_bubble: Optional[MessageBubble] = None
        self._is_pinned = False
        self._tray_icon: Optional[QSystemTrayIcon] = None
        # 第四阶段：拖拽支持
        self.setAcceptDrops(True)

        self._setup_window_geometry()
        self._init_ui()
        self._setup_tray()
        self._connect_signals()
        self._load_history()

    def _setup_window_geometry(self) -> None:
        """设置窗口默认位置和大小（屏幕右侧居中）。"""
        screen = QApplication.primaryScreen().availableGeometry()
        width = min(520, int(screen.width() * 0.4))
        height = min(720, int(screen.height() * 0.85))
        x = screen.right() - width - 20
        y = (screen.height() - height) // 2
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(400, 500)

    def _init_ui(self) -> None:
        """构建窗口 UI：阴影容器 + 标题栏 + 消息区 + 输入区。"""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        self.main_container = QWidget()
        self.main_container.setObjectName("chatWindowContainer")
        self.main_container.setStyleSheet(
            "QWidget#chatWindowContainer {"
            "  background: #FFF8FA;"
            "  border: 1px solid #FFE4EC;"
            "  border-radius: 16px;"
            "}"
        )

        shadow = QGraphicsDropShadowEffect(self.main_container)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(0, 4)
        self.main_container.setGraphicsEffect(shadow)

        outer_layout.addWidget(self.main_container)

        main_layout = QVBoxLayout(self.main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 标题栏 ---
        title_bar = QWidget()
        title_bar.setObjectName("chatTitleBar")
        title_bar.setStyleSheet(
            "QWidget#chatTitleBar {"
            "  background: #FFFFFF;"
            "  border-bottom: 1px solid #FFE4EC;"
            "  border-top-left-radius: 16px;"
            "  border-top-right-radius: 16px;"
            "}"
        )
        title_bar.setFixedHeight(48)
        title_bar.setCursor(Qt.OpenHandCursor)

        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 12, 0)
        title_layout.setSpacing(8)

        icon_label = QLabel("💬")
        icon_label.setStyleSheet("font-size: 16px;")
        title_layout.addWidget(icon_label)

        self.title_label = QLabel("与女仆的对话")
        self.title_label.setStyleSheet(
            "QLabel { color: #FF6B9D; font-size: 15px; font-weight: 600; }"
        )
        title_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("在线")
        self.subtitle_label.setStyleSheet(
            "QLabel { color: #BBBBBB; font-size: 11px; margin-left: 4px; }"
        )
        title_layout.addWidget(self.subtitle_label)
        title_layout.addStretch()

        # 置顶按钮
        self.pin_btn = QPushButton("📌")
        self.pin_btn.setFixedSize(28, 28)
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " color: #888888; font-size: 12px; }"
            "QPushButton:hover { background: #F5F5F5; color: #FF6B9D; }"
        )
        self.pin_btn.setToolTip("窗口置顶")
        self.pin_btn.clicked.connect(self._on_toggle_pin)
        title_layout.addWidget(self.pin_btn)

        # 合并按钮（Attach）
        self.attach_btn = QPushButton("🔗")
        self.attach_btn.setFixedSize(28, 28)
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " color: #888888; font-size: 12px; }"
            "QPushButton:hover { background: #F5F5F5; color: #4A90D9; }"
        )
        self.attach_btn.setToolTip("合并到主窗口")
        self.attach_btn.clicked.connect(self._on_attach)
        title_layout.addWidget(self.attach_btn)

        # v1.4：本窗口是无边框自绘标题栏，窗口控制按钮必须自带可见符号。
        # 此前只用极淡的 − □ × ，在浅色标题栏上几乎看不见（像是空白按钮），
        # 这里统一给符号 + 中文 tooltip + 主题取色的 hover 态。
        self.min_btn = QPushButton(_TITLE_BUTTONS[0][0])
        self.max_btn = QPushButton(_TITLE_BUTTONS[1][0])
        self.close_btn = QPushButton(_TITLE_BUTTONS[2][0])
        self.min_btn.clicked.connect(self.showMinimized)
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(self.hide)
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setFixedSize(_TITLE_BTN_WIDTH, _TITLE_BTN_HEIGHT)
            btn.setCursor(Qt.PointingHandCursor)
            title_layout.addWidget(btn)
        self._apply_title_button_theme()

        main_layout.addWidget(title_bar)

        # --- 消息滚动区 ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: #FFF8FA; border: none; }")

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background: #FFF8FA;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(12, 12, 12, 12)
        self.messages_layout.setSpacing(4)
        self.messages_layout.addStretch()
        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, 1)

        # 思考指示器
        self.thinking_indicator = ThinkingIndicator("AI 正在思考", app_context=self.app_ctx, parent=self)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, self.thinking_indicator)

        # --- 输入区 ---
        input_container = QWidget()
        input_container.setObjectName("chatInputArea")
        input_container.setStyleSheet(
            "QWidget#chatInputArea {"
            "  background: #FFFFFF;"
            "  border-top: 1px solid #FFE4EC;"
            "  border-bottom-left-radius: 16px;"
            "  border-bottom-right-radius: 16px;"
            "}"
        )
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(16, 12, 16, 16)
        input_layout.setSpacing(8)

        # 表情选择面板（默认隐藏）
        self.emoji_panel = QWidget()
        self.emoji_panel.setObjectName("emojiPanel")
        self.emoji_panel.setVisible(False)
        self.emoji_panel.setStyleSheet("QWidget#emojiPanel { background: #FFFFFF; border-radius: 12px; }")
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

        # 快捷回复栏
        quick_reply_container = QWidget()
        quick_reply_layout = QHBoxLayout(quick_reply_container)
        quick_reply_layout.setContentsMargins(0, 0, 0, 0)
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
            btn.clicked.connect(lambda checked, t=reply_text: self._on_quick_reply(t))
            quick_reply_layout.addWidget(btn)
        quick_reply_layout.addStretch()
        input_layout.addWidget(quick_reply_container)

        # 输入框 + 发送/停止按钮行
        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        # 第四阶段：附件芯片栏（位于输入框上方）
        self.attachment_bar = AttachmentBar(self.app_ctx)
        input_layout.addWidget(self.attachment_bar)

        self.input_edit = QTextEdit()
        self.input_edit.setObjectName("chatInput")
        self.input_edit.setPlaceholderText("和女仆说点什么吧... （或拖拽文件）")
        self.input_edit.setMaximumHeight(120)
        # v1.4.6: 输入框随内容多行增高（与主窗一致）
        self.input_edit.textChanged.connect(self._adjust_input_height)
        self.input_edit.setAcceptRichText(False)
        self.input_edit.setAcceptDrops(False)  # 透传拖拽事件到 ChatWindow 自身
        self.input_edit.setStyleSheet(
            "QTextEdit#chatInput {"
            "  background: #FFF5F7;"
            "  border: 1px solid #FFD6E0;"
            "  border-radius: 20px;"
            "  padding: 10px 16px;"
            "  font-size: 14px;"
            "  color: #4A4A4A;"
            "  line-height: 1.5;"
            "  selection-background-color: #FFB6C1;"
            "}"
            "QTextEdit#chatInput:focus {"
            "  border-color: #FF9EB5;"
            "  background: #FFFFFF;"
            "}"
        )
        # 安装事件过滤器捕获 Enter / Shift+Enter
        self.input_edit.installEventFilter(self)
        input_row.addWidget(self.input_edit, 1)

        # 停止按钮
        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setObjectName("chatStopBtn")
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton#chatStopBtn {"
            "  background: #FF6B6B;"
            "  color: #FFFFFF;"
            "  border: none;"
            "  border-radius: 20px;"
            "  font-size: 14px;"
            "}"
            "QPushButton#chatStopBtn:hover { background: #FF5252; }"
        )
        self.stop_btn.clicked.connect(self._on_stop_generation)
        self.stop_btn.setVisible(False)
        input_row.addWidget(self.stop_btn, alignment=Qt.AlignBottom)

        self.send_btn = QPushButton("➤")
        self.send_btn.setObjectName("chatSendBtn")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(
            "QPushButton#chatSendBtn {"
            "  background: #FF9EB5;"
            "  color: #FFFFFF;"
            "  border: none;"
            "  border-radius: 20px;"
            "  font-size: 16px;"
            "  font-weight: bold;"
            "}"
            "QPushButton#chatSendBtn:hover { background: #FF8AA5; }"
            "QPushButton#chatSendBtn:pressed { background: #FF6B8A; }"
            "QPushButton#chatSendBtn:disabled { background: #FFD6E0; }"
        )
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn, alignment=Qt.AlignBottom)

        input_layout.addLayout(input_row)

        # 底部工具行：表情按钮 + 导出按钮 + 快捷键提示
        bottom_row = QHBoxLayout()
        self.emoji_btn = QPushButton("😊 表情")
        self.emoji_btn.setFixedHeight(24)
        self.emoji_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #FF9EB5; font-size: 12px; }"
            "QPushButton:hover { color: #FF69B4; }"
        )
        self.emoji_btn.setCursor(Qt.PointingHandCursor)
        self.emoji_btn.clicked.connect(self._on_toggle_emoji_panel)
        bottom_row.addWidget(self.emoji_btn)

        self.export_btn = QPushButton("📤 导出")
        self.export_btn.setFixedHeight(24)
        self.export_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #4A90D9; font-size: 12px; }"
            "QPushButton:hover { color: #2D6FB5; }"
        )
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setToolTip("导出聊天记录（Markdown / TXT / JSON）")
        self.export_btn.clicked.connect(self._on_export_chat)
        bottom_row.addWidget(self.export_btn)

        # 第四阶段：语音输入入口
        self.voice_btn = QPushButton("🎤 语音")
        self.voice_btn.setFixedHeight(24)
        self.voice_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #FF6B9D; font-size: 12px; }"
            "QPushButton:hover { color: #FF1493; }"
        )
        self.voice_btn.setCursor(Qt.PointingHandCursor)
        self.voice_btn.setToolTip("语音输入（依赖 SpeechRecognition + 麦克风）")
        self.voice_btn.clicked.connect(self._on_voice_input)
        bottom_row.addWidget(self.voice_btn)

        bottom_row.addStretch()
        self._hint_label = QLabel("Enter 发送 · Shift+Enter 换行")
        self._hint_label.setAlignment(Qt.AlignRight)
        bottom_row.addWidget(self._hint_label)
        self._update_hint_theme()
        input_layout.addLayout(bottom_row)

        main_layout.addWidget(input_container)

    def _connect_signals(self) -> None:
        if self.chat_service is None:
            return
        self.chat_service.message_stream_started.connect(self._on_stream_started)
        self.chat_service.message_chunk_received.connect(self._on_chunk)
        self.chat_service.message_stream_finished.connect(self._on_stream_finished)
        self.chat_service.message_cancelled.connect(self._on_stream_cancelled)
        self.chat_service.thinking_indicator.connect(self._on_thinking)
        # v10.15: 错误冒泡显示（独立窗口也要有红框错误气泡）
        self.chat_service.message_failed.connect(self._on_message_failed)
        # v1.1(agent): 授权弹窗 + 工具轨迹
        self.chat_service.agent_authorization_requested.connect(self._on_agent_authorization_requested)
        self.chat_service.agent_tool_event.connect(self._on_agent_tool_event)
        # v1.2(A9): 主动陪伴 -> 托盘静默气泡（气泡渲染经 gui_session.message_added 已发生）
        self.chat_service.proactive_message.connect(self._on_proactive_ready)
        # v1.6(P0-3): 反馈三键内容源 —— 浮窗消息流末尾挂动作行（不入会话存档）
        try:
            self.chat_service.proactive_feedback_ready.connect(self._on_proactive_feedback_ready)
            self._feedback_bars: list = []
        except Exception:
            self._feedback_bars = []

        # v1.2(A-11)(B5): 托盘 tooltip 随心情更新（最小实现：复用现有托盘图标，
        # 只做 tooltip 文案，无数值红线；无 bridge 则静默跳过）
        try:
            bridge = getattr(self.app_ctx, "companion_bridge", None)
            if bridge is not None and hasattr(bridge, "mood_changed") \
                    and hasattr(bridge.mood_changed, "connect"):
                bridge.mood_changed.connect(self._on_tray_mood_changed)
        except Exception:
            pass

        gui_session = getattr(self.app_ctx, "gui_session", None)
        if gui_session is not None:
            gui_session.message_added.connect(self._on_message_added)

        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

        # v1.3(P1-1): TTS 朗读归属变化 -> 刷新浮窗气泡「朗读/停止」按钮态
        tts = getattr(self.app_ctx, "tts", None)
        if tts is not None and hasattr(tts, "state_changed"):
            try:
                tts.state_changed.connect(self._on_tts_state_changed)
            except Exception:
                pass

    def _adjust_input_height(self) -> None:
        """v1.4.6: 输入框随内容多行增高（48~120）。"""
        try:
            doc_h = int(self.input_edit.document().size().height() + 14)
            self.input_edit.setFixedHeight(max(48, min(doc_h, 120)))
        except Exception:
            pass

    def _apply_title_button_theme(self) -> None:
        """给自绘标题栏的窗口控制按钮上符号 / 中文 tooltip / 主题色 hover 态。

        取色一律走 theme_color（禁裸硬编码色），随主题切换即时生效。
        v1.4.3 加强可见性：常态用正文主色（text）+ 加粗符号，确保浅/深标题栏上都
        清晰可辨；hover 改为「实底色块」加强对比（最小/最大=主色粉底白字，
        关闭键保持警示色 hover）。
        """
        # 常态：正文主色（两主题均足够对比）；加粗符号已随 _TITLE_BUTTONS 字号放大。
        idle = theme_color(self.app_ctx, "text", "#4A4A4A")
        # hover 实底：最小/最大用主色粉底 + 卡片色（白）字，强对比。
        hover_bg = theme_color(self.app_ctx, "primary", "#FFB6C1")
        hover_fg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        # 关闭键 hover 保持警示语义色（底）+ 白字。
        close_hover_bg = theme_color(self.app_ctx, "state_warn", "#E5A02E")
        close_hover_fg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")

        for btn, (_symbol, tooltip, font_size) in zip(
            (self.min_btn, self.max_btn, self.close_btn), _TITLE_BUTTONS
        ):
            if btn is None:
                continue
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 6px;"
                " color: %s; font-size: %dpx; font-weight: bold; }"
                "QPushButton:hover { background: %s; color: %s; }"
                % (
                    idle,
                    font_size,
                    close_hover_bg if btn is self.close_btn else hover_bg,
                    close_hover_fg if btn is self.close_btn else hover_fg,
                )
            )

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题变更时刷新所有消息气泡颜色 + 附件栏。"""
        self._apply_title_button_theme()
        for i in range(self.messages_layout.count() - 1):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                widget.update_theme()
        if hasattr(self, "attachment_bar") and self.attachment_bar is not None:
            try:
                self.attachment_bar.refresh_theme()
            except Exception:
                pass

    def _apply_theme(self) -> None:
        """应用当前主题到聊天窗口容器。"""
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is None:
            return
        bg = theme_engine.get_color("chat_bg", "#FFF8FA")
        border = theme_engine.get_color("chat_border", "#FFE4EC")
        self.main_container.setStyleSheet(
            f"QWidget#chatWindowContainer {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 16px;"
            f"}}"
        )
        self.messages_container.setStyleSheet(f"background: {bg};")
        self._update_hint_theme()

    def _update_hint_theme(self) -> None:
        """更新快捷键提示标签颜色。"""
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        color = "#CCCCCC"
        if theme_engine is not None:
            color = theme_engine.get_color("text_secondary", "#CCCCCC")
        self._hint_label.setStyleSheet(f"QLabel {{ color: {color}; font-size: 11px; }}")

    def _load_history(self) -> None:
        """加载已有会话历史到窗口。"""
        session = getattr(self.app_ctx, "session", None)
        if session is None:
            return
        history = getattr(session, "history", [])
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant"):
                self.add_message(role, content)

    def _on_send(self) -> None:
        text = self.input_edit.toPlainText().strip()
        attachments = self.attachment_bar.attachments() if hasattr(self, "attachment_bar") else []
        if not text and not attachments:
            return
        self.input_edit.clear()
        bubble_text = text if text else "📎 附件"
        # v1.6(P0-3): 用户开新话头 → 移除未点击的反馈动作行（防堆积）
        self._clear_feedback_bars()
        self.add_message("user", bubble_text, attachments=attachments)
        if hasattr(self, "attachment_bar") and self.attachment_bar is not None:
            self.attachment_bar.clear()
        # v10.15: 用共享 helper 拼装附件 payload（文本 ≤50KB 直入 prompt，二进制做诚实标注）
        from gui.utils import build_attachment_payload
        send_text = build_attachment_payload(text, attachments)
        # R6: 通知主面板渲染并持久化本条消息（含附件 metadata），收敛保存入口
        self.user_message_sent.emit(bubble_text, list(attachments))
        if self.chat_service is not None:
            # R1: 窗口直插气泡为唯一 user 渲染入口——抑制服务层 message_added 回声
            self.chat_service.send_message(send_text, suppress_echo=True, attachments=self.attachment_bar.attachments() if hasattr(self, 'attachment_bar') else [])
        else:
            self.add_message("assistant", "哎呀，女仆的聊天服务还没准备好呢... 请主人稍等~ 💕")

    def _on_stop_generation(self) -> None:
        """用户点击停止生成。"""
        if self.chat_service is not None:
            self.chat_service.stop_generation()

    # ----- v1.1(agent): 授权弹窗与工具轨迹（独立窗口版） -----
    def _on_agent_authorization_requested(self, action_desc: str, tool_name: str) -> None:
        try:
            from gui.qt_compat import QMessageBox
            tool_label = {
                "write_file": "写入 / 覆写文件",
                "git_commit": "Git 提交",
                "run_python": "沙箱执行 Python",
            }.get(tool_name, tool_name)
            box = QMessageBox(self)
            box.setWindowTitle("码铃 · Agent 授权请求")
            box.setIcon(QMessageBox.Question)
            box.setText(f"女仆想执行一个修改类操作：\n\n【{tool_label}】\n{action_desc[:200]}")
            box.setInformativeText("允许本次及本次会话内后续操作吗？（白名单目录内会自动放行）")
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
        """Agent 工具轨迹状态提示（独立窗口）。

        独立窗口（QWidget 无 statusBar）退化为日志；气泡级渲染由主面板承担。
        """
        import json as _json
        try:
            data = _json.loads(data_json or "{}")
        except Exception:
            data = {}
        try:
            text = None
            if event_type == "tool_call":
                text = f"Agent 调用工具 {data.get('name', '')}"
            elif event_type == "tool_denied":
                text = f"工具 {data.get('name', '')} 已被拒绝"
            if text:
                status_bar = getattr(self, "_status_bar", None) or getattr(self, "status_label", None)
                if status_bar is not None:
                    set_text = getattr(status_bar, "showMessage", None) or getattr(status_bar, "setText", None)
                    if set_text is not None:
                        set_text(text)
        except Exception:
            pass

    # ==================================================================
    # 聊天记录导出
    # ==================================================================
    def _collect_messages(self) -> list:
        """从当前消息气泡收集 (role, content, timestamp) 列表。"""
        messages = []
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, MessageBubble):
                messages.append((widget.role, widget.get_text(), widget.timestamp))
        return messages

    def _on_export_chat(self) -> None:
        """导出当前窗口聊天记录（Markdown / TXT / JSON）。"""
        messages = self._collect_messages()
        if not messages:
            QMessageBox.information(self, "导出", "当前没有消息可导出")
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出聊天记录", "chat_export.md",
            "Markdown (*.md);;文本文件 (*.txt);;JSON (*.json)",
        )
        if not path:
            return
        if selected_filter.startswith("Markdown"):
            fmt = "markdown"
        elif selected_filter.startswith("文本"):
            fmt = "txt"
        else:
            fmt = "json"

        if ChatExporter.export(messages, fmt, path, "与女仆的对话"):
            QMessageBox.information(self, "导出成功", f"聊天记录已导出到:\n{path}")
        else:
            QMessageBox.warning(self, "导出失败", "导出聊天记录失败，请检查文件路径")

    def _on_toggle_emoji_panel(self) -> None:
        """切换表情选择面板的显示/隐藏。"""
        self.emoji_panel.setVisible(not self.emoji_panel.isVisible())

    def _on_emoji_clicked(self, emoji: str) -> None:
        """点击表情按钮，插入到输入框光标位置。"""
        cursor = self.input_edit.textCursor()
        cursor.insertText(emoji)
        self.input_edit.setTextCursor(cursor)
        self.input_edit.setFocus()

    def _on_quick_reply(self, text: str) -> None:
        """点击快捷回复按钮，填入输入框并触发发送。"""
        self.input_edit.setPlainText(text)
        self._on_send()

    def _on_message_added(self, role: str, content: str) -> None:
        # R1: 发送方已抑制回声（面板/窗口直插气泡）时跳过，避免双气泡
        if role == "user":
            service = self.chat_service
            if service is not None and getattr(service, "echo_suppressed", False):
                return
        # R1: 流式期间 assistant 回声跳过——流式气泡已是展示载体
        if role == "assistant" and self._current_ai_bubble is not None:
            return
        if role in ("user", "assistant"):
            self.add_message(role, content)

    def add_message(self, role: str, content: str, attachments: Optional[List[dict]] = None,
                error_style: bool = False) -> None:
        is_consecutive = self._last_role == role
        bubble = MessageBubble(
            role, content,
            is_consecutive=is_consecutive,
            max_bubble_width=360,
            app_context=self.app_ctx,
            attachments=attachments,
            error_style=error_style,  # v10.15
        )
        bubble.delete_requested.connect(lambda: self._remove_bubble(bubble))
        # v1.3(P1-1): 朗读按钮 -> 浮窗接 TTS（只朗读 AI 文本）
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
        self._scroll_to_bottom()

    def _remove_bubble(self, bubble: MessageBubble) -> None:
        """从消息列表中移除指定气泡。"""
        self.messages_layout.removeWidget(bubble)
        bubble.deleteLater()

    def _on_stream_started(self) -> None:
        self._stream_buffer = ""
        self._current_ai_bubble = None
        self.stop_btn.setVisible(True)
        self.send_btn.setEnabled(False)

    def _on_chunk(self, chunk: str) -> None:
        self._stream_buffer += chunk
        if self._current_ai_bubble is None:
            is_consecutive = self._last_role == "assistant"
            self._current_ai_bubble = MessageBubble(
                "assistant", self._stream_buffer,
                is_consecutive=is_consecutive,
                max_bubble_width=360,
                app_context=self.app_ctx,
            )
            self._current_ai_bubble.read_aloud_requested.connect(
                lambda b=self._current_ai_bubble: self._on_bubble_read_aloud(b)
            )
            # v1.3(P2-3): 流式气泡同样支持收藏高光
            self._current_ai_bubble.favorite_requested.connect(
                lambda role, text, meta, b=self._current_ai_bubble:
                self._on_favorite_requested(b, role, text, meta)
            )
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, self._current_ai_bubble)
            self._last_role = "assistant"
        else:
            self._current_ai_bubble.update_text(self._stream_buffer)
        self._scroll_to_bottom()

    def _on_stream_finished(self, full_text: str, usage: dict) -> None:
        self._current_ai_bubble = None
        self._stream_buffer = ""
        self.subtitle_label.setText("在线")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)

    def _on_stream_cancelled(self) -> None:
        """用户主动停止生成。"""
        self._current_ai_bubble = None
        self._stream_buffer = ""
        self.subtitle_label.setText("在线")
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self.add_message("assistant", "生成已停止~")

    def _on_thinking(self, active: bool) -> None:
        if active:
            self.thinking_indicator.start()
        else:
            self.thinking_indicator.stop()
        self.subtitle_label.setText("思考中..." if active else "在线")

    def _on_message_failed(self, error: str) -> None:
        """v10.15: API 错误冒泡 —— 独立窗口同样要红框显示。"""
        self._current_ai_bubble = None
        self._stream_buffer = ""
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self.subtitle_label.setText("在线")
        self.add_message("assistant", error, error_style=True)

    # ----- v1.3(P2-3): 收藏高光回忆（浮窗版，本地落盘）-----
    def _on_favorite_requested(self, bubble, role: str, text: str, meta: object) -> None:
        try:
            from gui.pages.page_memories import add_highlight
        except Exception:
            return
        add_highlight(self.app_ctx, role, text, session_id="")
        try:
            self.subtitle_label.setText("已收藏 ✨")
        except Exception:
            pass
        try:
            from gui.qt_compat import QTimer
            QTimer.singleShot(1500, self._restore_subtitle)
        except Exception:
            pass

    def _restore_subtitle(self) -> None:
        try:
            self.subtitle_label.setText("在线")
        except Exception:
            pass

    # ----- v1.3(P1-1): 朗读本条（TTS，浮窗版）-----
    def _on_bubble_read_aloud(self, bubble: Optional[MessageBubble]) -> None:
        if bubble is None:
            return
        tts = getattr(self.app_ctx, "tts", None)
        if tts is None or not tts.available:
            return  # 降级静默（主面板有完整提示；浮窗不弹重复对话框）
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
            tts.speak(text, owner=bubble)
        except Exception:
            pass

    def _on_tts_state_changed(self, owner) -> None:
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

    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _on_toggle_pin(self) -> None:
        """切换窗口置顶状态。"""
        self._is_pinned = not self._is_pinned
        flags = self.windowFlags()
        if self._is_pinned:
            self.setWindowFlags(flags | Qt.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet(
                "QPushButton { background: #FFF0F3; border: none; border-radius: 6px;"
                " color: #FF6B9D; font-size: 12px; }"
                "QPushButton:hover { background: #FFE4EC; color: #FF6B9D; }"
            )
            self.pin_btn.setToolTip("取消置顶")
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; border-radius: 6px;"
                " color: #888888; font-size: 12px; }"
                "QPushButton:hover { background: #F5F5F5; color: #FF6B9D; }"
            )
            self.pin_btn.setToolTip("窗口置顶")
        self.show()

    def _on_attach(self) -> None:
        """用户点击合并按钮：发出信号并隐藏独立窗口。"""
        self.attach_requested.emit()
        self.hide()

    def _setup_tray(self) -> None:
        """初始化系统托盘图标（如果平台支持）。

        v1.3(P1-3/D-V13-10): app 级单一托盘已由 TrayManager 拥有——本方法顶部
        一行退避，不建第二个图标；既有托盘处理器（_refresh_tray_mood /
        _on_proactive_ready / _on_tray_quit）经 `self._tray_icon is None` 守卫
        自动退避为空操作，零删除零改写。
        """
        from gui.tray_manager import app_tray_exists
        if app_tray_exists(self.app_ctx):
            self._tray_icon = None
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setToolTip("码铃聊天窗口")
        # 使用应用图标或默认图标
        tray_menu = QMenu(self)
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_normal)
        tray_menu.addAction(show_action)
        pin_action = QAction("窗口置顶", self)
        pin_action.setCheckable(True)
        pin_action.toggled.connect(self._on_toggle_pin)
        tray_menu.addAction(pin_action)
        tray_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._on_tray_quit)
        tray_menu.addAction(quit_action)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        # v1.2(A9): 点托盘静默气泡 -> 打开浮窗看完整会话
        self._tray_icon.messageClicked.connect(self.show_normal)
        self._tray_icon.show()
        # v1.2(A-11)(B5): 初始即带心情 tooltip（随后随 mood_changed 更新）
        self._refresh_tray_mood()

    def _on_tray_mood_changed(self, mood: str, reason: str) -> None:
        """v1.2(A-11)(B5): mood/活动态广播 -> 刷新托盘心情 tooltip。"""
        self._refresh_tray_mood()

    def _refresh_tray_mood(self) -> None:
        """托盘 tooltip = 当前心情语境一句 + 打开提示（无数值红线）。

        最小实现（R10）：复用现有托盘图标，仅更新 tooltip 文案；
        心情/活动态文案经 maid_pet.mood_tooltip_text（纯函数，无数值）。
        """
        if self._tray_icon is None:
            return
        try:
            from gui.widgets.maid_pet import mood_tooltip_text
        except Exception:
            return
        companion = getattr(self.app_ctx, "companion", None)
        state = None
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        try:
            if bridge is not None and hasattr(bridge, "current_display"):
                state = bridge.current_display() or None
        except Exception:
            state = None
        try:
            text = mood_tooltip_text(companion, state)
            self._tray_icon.setToolTip(f"{text}\n点开浮窗找码铃聊聊")
        except Exception:
            pass

    # ----- v1.6(P0-3/D-V16-05): 反馈三键动作行（浮窗侧，不入会话存档） -----
    def _on_proactive_feedback_ready(self, subject: str, scene: str) -> None:
        """主动消息内容源就绪：在浮窗消息流末尾挂反馈三键动作行。"""
        if not subject:
            return
        try:
            from gui.widgets.proactive_feedback import ProactiveFeedbackBar
            bar = ProactiveFeedbackBar(subject, scene, self._on_feedback_picked)
            bar.set_app_ctx(self.app_ctx)
            idx = self.messages_layout.count() - 2
            if idx < 0:
                idx = self.messages_layout.count() - 1
            self.messages_layout.insertWidget(idx, bar)
            self._feedback_bars.append(bar)
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

    def _clear_feedback_bars(self) -> None:
        """新一条用户消息发出时移除未点击的反馈动作行（防堆积）。"""
        try:
            for bar in list(getattr(self, "_feedback_bars", [])):
                self.messages_layout.removeWidget(bar)
                bar.deleteLater()
            self._feedback_bars = []
        except Exception:
            self._feedback_bars = []

    def _on_proactive_ready(self, text: str, scene: str) -> None:
        """v1.2(A9): 主动陪伴消息 -> 托盘静默气泡（不抢焦点；点开看浮窗）。

        气泡正文渲染已由 gui_session.message_added 链落到本窗口会话区。
        """
        if self._tray_icon is None or not self._tray_icon.isVisible():
            return
        head = (text or "").strip().split("\n")[0][:60]
        if not head:
            return
        try:
            self._tray_icon.showMessage(
                "码铃 · 悄悄话",
                head,
                QSystemTrayIcon.Information,
                6000,
            )
        except Exception:
            pass

    def show_normal(self) -> None:
        """从托盘恢复显示窗口。"""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason) -> None:
        """双击托盘图标显示窗口。"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    def _on_tray_quit(self) -> None:
        """从托盘菜单退出：彻底关闭窗口。"""
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self.close()

    def closeEvent(self, event) -> None:
        """拦截关闭事件，最小化到托盘而非直接退出。"""
        if self._tray_icon is not None and self._tray_icon.isVisible():
            self.hide()
            self._tray_icon.showMessage(
                "码铃",
                "聊天窗口已最小化到系统托盘",
                QSystemTrayIcon.Information,
                2000,
            )
            event.ignore()
        else:
            event.accept()

    # --- 拖拽移动支持 ---
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if event.pos().y() <= 48 + 10:
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                self._is_dragging = True
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
            else:
                super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """拦截输入框按键：Enter 发送，Shift+Enter 换行。"""
        if obj is self.input_edit and event.type() == event.Type.KeyPress:
            key_event = event
            if key_event.key() == Qt.Key_Return or key_event.key() == Qt.Key_Enter:
                if key_event.modifiers() == Qt.ShiftModifier:
                    return False
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    # ==================================================================
    # 第四阶段：拖拽上传 + 语音输入
    # ==================================================================
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """拖入时判断是否含可接受的文件 URL。"""
        md = event.mimeData() if hasattr(event, "mimeData") else event.mimeData
        if md is not None and md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """拖动时持续接受，否则 ignore（避免子控件闪烁）。"""
        md = event.mimeData() if hasattr(event, "mimeData") else event.mimeData
        if md is not None and md.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """放下文件：把每个文件塞进附件栏，超限/缺失/重复的逐条提示。"""
        md = event.mimeData() if hasattr(event, "mimeData") else event.mimeData
        if md is None or not md.hasUrls():
            event.ignore()
            return
        added, too_large, missing, duplicate = 0, 0, 0, 0
        for url in md.urls():
            if not url.isLocalFile():
                continue
            local = url.toLocalFile()
            ok, info = self.attachment_bar.add_file_path(local)
            if ok:
                added += 1
            elif info == "too_large":
                too_large += 1
            elif info == "missing":
                missing += 1
            elif info == "duplicate":
                duplicate += 1
        if added or too_large or missing or duplicate:
            lines = []
            if added:
                lines.append(f"已添加 {added} 个附件")
            if too_large:
                lines.append(f"超 10MB 的文件 {too_large} 个被拒绝")
            if missing:
                lines.append(f"文件不存在 {missing} 个")
            if duplicate:
                lines.append(f"重复 {duplicate} 个已跳过")
            QMessageBox.information(self, "拖拽上传", "\n".join(lines))
        event.acceptProposedAction() if added else event.ignore()

    def _on_voice_input(self) -> None:
        """点击语音按钮：探测后端，缺失弹说明，对话框就绪后启动录音。"""
        backend_ok, device_ok, desc = voice_input_mod.diagnose_voice_input()
        if not backend_ok or not device_ok:
            QMessageBox.warning(
                self,
                "语音输入不可用",
                voice_input_mod.build_unavailable_message(),
            )
            return
        dlg = voice_input_mod.VoiceInputDialog(self.app_ctx, self)
        if dlg.exec() == voice_input_mod.VoiceInputDialog.Accepted:
            text = dlg.transcript
            if text:
                self.input_edit.setPlainText(text)
                self.input_edit.setFocus()
