"""独立聊天窗口 —— 无边框圆角浮窗，支持拖拽移动、消息列表、输入发送、文件拖拽附件。"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QScrollArea, QFrame, Qt, QSize, QSizePolicy, QFont,
    QApplication, QGraphicsDropShadowEffect, QColor, QPoint,
    QSystemTrayIcon, QMenu, QAction, Signal, QObject,
    QMessageBox, QDialog, QDragEnterEvent, QDropEvent,
    QDragMoveEvent, QEvent,
)
from gui.utils import theme_color
# v2.1(G-2/D-V21-04/D-V21-02/I-2): 毛玻璃 / 动效 / 图标内核 —— 仅调用，内核零改动
from gui import glass, motion, icons
from gui.widgets.message_bubble import (
    MessageBubble, invalidate_default_speaker_name, resolve_default_speaker_name,
)
from gui.widgets.thinking_indicator import ThinkingIndicator
from gui.widgets.attachment_bar import AttachmentBar

# v2.1(可观测性)：静默 except 收敛用 —— 本文件此前 26 处 `except ...: pass` 无任何
#   记录，异常被完全吞掉，问题只能靠肉眼发现。改走 logger.debug 后可在日志里定位
#   （仅记录、不重抛，行为零变化）。
logger = logging.getLogger("maid_coder.gui.chat_window")

# v1.4：自绘标题栏窗口控制按钮尺寸（宽 ≥28、高 ≥24，符号才看得清）
_TITLE_BTN_WIDTH = 32
_TITLE_BTN_HEIGHT = 26
# v2.2.2(P3 尺寸收口)：标题栏的**两套**尺寸此前在 `_init_ui` 里写成裸字面量
#   （`setFixedSize(28, 28)` / `setFixedSize(_TITLE_BTN_WIDTH, _TITLE_BTN_HEIGHT)`）
#   ⇒ 归到本常量块，只此一处定义。
#   ⚠ **数值一个都没改**：两组尺寸被布局与守卫钉住
#     （`tests/test_v22_1_blackbox_fixes.py::_WP4_SIZES` 锁 `pin/attach 28×28`、
#      `min/max/close 32×26`），实测把三键并到 28×28 会让按钮组宽 3×32=96 → 3×28=84
#     （Δ−12px）、高 26 → 28（Δ+2px），即**可见位移**；而「统一数值」正是该守卫的
#     反面。故本次只收口「定义处数目」，不动观感。
#   v2.2.2(裁决2)：原先第三套 `_EMOJI_BTN_SIZE = (44, 36)` 随浮窗表情面板一并移除
#     —— 该常量的唯一消费者就是那个面板；主面板表情格子的 44×36 在
#     `chat_panel_parts/ui_build.py` 侧（`_emoji_css`）自成一体，不受影响。
_TITLE_TOOL_BTN_SIZE = (28, 28)                               # 标题栏工具键（置顶 / 合并）
_TITLE_WINDOW_BTN_SIZE = (_TITLE_BTN_WIDTH, _TITLE_BTN_HEIGHT)  # 标题栏窗口控制键
# v2.2.2(P2 缺陷·字形晚注册)：本窗全部「图标字体字形」文本位。
#   `icons.text_glyph()` 的调用点原先**只在构造期求值一次**；图标字体缺失、或注册
#   晚于建窗（`gui/main.py` 的启动顺序）时，文本就永久停在 emoji 兜底态。
#   下表是 (属性名, 图标名, 兜底文本)，由 `_refresh_icon_glyphs()` 在换肤/主题变更点重取。
_GLYPH_SLOTS = (
    ("icon_label", "chat", "💬"),
    ("pin_btn", "anchor", "📌"),
    ("attach_btn", "link", "🔗"),
    ("stop_btn", "stop", "⏹"),
    ("send_btn", "send", "➤"),
)
# 标题栏控制按钮：(Unicode 兜底符号, tooltip, 字号, remixicon 图标名或 None)
# v2.2.2(P3)：manifest 实测只有 `close` 一个语义合适的名字
#   （minimize / maximize / fullscreen / minus / subtract **均不在** manifest，
#    `expand` 虽在但语义是「展开为独立浮窗」且已归主面板 `#expandChatBtn` 使用
#    ⇒ 硬塞会让两个不同功能的按钮共用一个字形），故**只有关闭键**改走图标族，
#   最小化 / 最大化保留 Unicode（按 team-lead 口径：不许硬塞语义不对的字形）。
# v2.2.2(P3 缺陷·字号零余量)：字号列三键**统一为 17px**。此前最小化键单独用 20px，
#   而 20px 档 `QFontMetrics.height()` 实测 **26**，恰等于 `_TITLE_BTN_HEIGHT` 26 ⇒
#   **零纵向余量**（另两键 fmH 22 / 高 26，余 4px）。按钮高被
#   `tests/test_v22_1_blackbox_fixes.py` 的 `_WP4_SIZES` 钉死 32×26，唯一可动的杠杆
#   就是字号；且本仓字体族可由用户切换（v1.9 字体系统）⇒ 换到行盒更高的字体时，
#   这一键会最先被内容区裁掉。并档实测代价（真实平台 + 整窗 grab 后裁切，四主题一致）：
#     字号    min 落墨   fmH     max / close 落墨
#     20px    22         26      46~54 / 80~109
#     17px    16~18      22      23~40 / 57~86
#   ⇒ `−`(U+2212) 是细横线，落墨由 hinting 而非 em 尺寸决定，并档只短 2px，视觉代价≈0；
#   收益是三键 fmH 一并降到 22（统一 4px 余量、字重同款）。
_TITLE_BUTTONS = (
    ("−", "最小化", 17, None),
    ("□", "最大化/还原", 17, None),
    ("✕", "关闭", 17, "close"),
)


class ChatWindow(QWidget):
    """独立聊天窗口：无边框、圆角、可拖拽、与主窗聊天页可共存。"""

    attach_requested = Signal()
    """用户点击"合并"按钮时发出，通知主面板重新显示聊天区。"""

    user_message_sent = Signal(str, list)
    """R6: 窗口发送用户消息时发出 (display_text, attachments)，
    由主面板统一渲染并持久化，使两条发送路径落同一份会话数据。"""

    # v2.2.2(裁决2)：原类属性 `EMOJIS`（内置颜文字/符号表情）随浮窗表情面板一并移除
    #   —— 它唯一的消费者就是那个面板的 12 个格子。主面板表情用
    #   `ChatPanelWidget.EMOJIS`（`chat_panel.py:40`），不受影响。

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
        # v2.1(G-2): 顶层浮窗 Acrylic 应用态（仅记账，失败即回落纯色）
        self._glass_applied: bool = False
        # v2.2.2(缺陷·脆弱耦合)：_connect_signals 分通道的「一次性连接」标记 ——
        #   重复调用不得叠加连接（重复 connect 会让同一个槽被调多次）。
        self._svc_connected = False
        self._mood_connected = False
        self._session_connected = False
        self._theme_connected = False
        self._role_connected = False
        self._tts_connected = False
        # 第四阶段：拖拽支持
        self.setAcceptDrops(True)

        self._setup_window_geometry()
        self._init_ui()
        # v2.2(缺陷1)：构造期即对齐主题。此前 _apply_theme 只在 _on_theme_changed 里被调用，
        #   首帧停在 _init_ui 的浅色取值上；UI 建好后补一次，保证「首次启动 + 换肤」同源。
        self._apply_theme()
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

    # ==================================================================
    # v2.1(G-2/D-V21-04): 顶层浮窗 Acrylic（与既有 WA_TranslucentBackground 协调）
    # ==================================================================
    def _glass_popups_enabled(self) -> bool:
        """浮层 Acrylic 开关（``GuiConfig.glass_popups_enabled``，缺键默认开）。"""
        cfg = getattr(self.app_ctx, "config", None)
        return bool(getattr(cfg, "glass_popups_enabled", True))

    def _is_dark_effective(self) -> bool:
        """当前是否生效深色（供 DWM immersive dark 联动；取不到 → False）。"""
        engine = getattr(self.app_ctx, "theme_engine", None)
        if engine is None:
            return False
        fn = getattr(engine, "is_dark_effective", None)
        if callable(fn):
            try:
                return bool(fn())
            except Exception:
                return False
        return False

    def _apply_glass_popup(self) -> None:
        """对本浮窗应用 / 移除 Acrylic 材质（best-effort，绝不抛）。

        与既有 ``WA_TranslucentBackground`` 的协调（R-§9 风险点）：
          · 本窗以「**透明留白 + 不透明主容器 ``chatWindowContainer``**」表达圆角与
            投影；主容器不透明白底，DWM 材质**不会**与之叠加成「二次半透明发灰」；
          · 故**保持** ``WA_TranslucentBackground`` 不动（改为不透明会让 10px 留白
            露出窗口底色 → 直角 / 黑边，违 R-Q）；
          · 材质只从留白处透出，深浅联动经 ``dark`` 重设 immersive dark；
          · 不满足开关 / 不支持 / 任一步失败 → ``glass.remove`` 回落原观感、不黑窗。
        """
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        try:
            if not self._glass_popups_enabled() or not glass.is_supported():
                glass.remove(hwnd)
                self._glass_applied = False
                return
            ok = glass.safe_apply(hwnd, "acrylic", dark=self._is_dark_effective())
            self._glass_applied = bool(ok)
            if not ok:
                glass.remove(hwnd)
        except Exception:
            self._glass_applied = False
            try:
                glass.remove(hwnd)
            except Exception:
                logger.debug("静默降级：_apply_glass_popup 中忽略异常", exc_info=True)

    def showEvent(self, event) -> None:  # noqa: N802
        """窗口显示后应用材质（HWND 此时才有效）。"""
        super().showEvent(event)
        self._apply_glass_popup()

    def changeEvent(self, event) -> None:  # noqa: N802
        """最小化还原 / 重显后部分 Windows 版本会丢材质 → 重应用。"""
        super().changeEvent(event)
        try:
            if event.type() == QEvent.WindowStateChange and self.isVisible():
                self._apply_glass_popup()
        except Exception:
            logger.debug("静默降级：changeEvent 中忽略异常", exc_info=True)

    def _exec_modal_fade(self, dialog):
        """模态 ``exec()`` 对话框**只做淡入**，透传返回值（design D-V21-02）。

        模态阻塞语义下延迟关闭会与返回值时序纠缠 → 只淡入、不淡出、不延迟关闭；
        ``off`` 档 / 无系统动画时直接原样 ``exec()``。
        """
        try:
            motion.fade(dialog, to=1.0)
        except Exception:
            logger.debug("静默降级：_exec_modal_fade 中忽略异常", exc_info=True)
        return dialog.exec_()

    def _init_ui(self) -> None:
        """构建窗口 UI：阴影容器 + 标题栏 + 消息区 + 输入区。

        v2.2(缺陷1)：本方法内所有配色一律经 ``_tc``(=theme_color) 取主题令牌，
        不再硬编码浅色；否则深色主题下「标题栏白底 + 文字取主题浅色」= 近不可见。
        注意：此处只做初值，``_apply_theme`` 负责换肤期重刷（两处同源）。
        """
        def _tc(key: str, fallback: str) -> str:
            return theme_color(self.app_ctx, key, fallback)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        self.main_container = QWidget()
        self.main_container.setObjectName("chatWindowContainer")
        self.main_container.setStyleSheet(
            "QWidget#chatWindowContainer {"
            f"  background: {_tc('chat_bg', '#FFF8FA')};"
            f"  border: 1px solid {_tc('chat_border', '#FFE4EC')};"
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
        # v2.2(缺陷1)：底色改 bg_card、分隔线改 border —— 跟随主题而非硬编码白。
        title_bar = QWidget()
        title_bar.setObjectName("chatTitleBar")
        title_bar.setStyleSheet(
            "QWidget#chatTitleBar {"
            f"  background: {_tc('bg_card', '#FFFFFF')};"
            f"  border-bottom: 1px solid {_tc('border', '#FFE4EC')};"
            "  border-top-left-radius: 16px;"
            "  border-top-right-radius: 16px;"
            "}"
        )
        self.title_bar = title_bar
        title_bar.setFixedHeight(48)
        title_bar.setCursor(Qt.OpenHandCursor)

        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 12, 0)
        title_layout.setSpacing(8)

        icon_label = QLabel(icons.text_glyph("chat", "💬"))
        # v2.2.2(缺陷1)：裸 QLabel 会吃应用级 `QWidget{background-color:${bg}}`，
        #   在 bg_card 标题栏上画出一条异色竖带 → 补 background: transparent。
        icon_label.setStyleSheet(
            "background: transparent;"
            f"font-size: 16px; color: {_tc('accent_text', '#FF6B9D')};")
        self.icon_label = icon_label
        title_layout.addWidget(icon_label)

        # 标题用 accent_text（「浅底上的强调文字」专用令牌）：四个主题下均 ≥4.5，
        # 而 primary/accent 这类「实底用色」在浅色主题上只有 ~2.1。
        self.title_label = QLabel("与女仆的对话")
        self.title_label.setStyleSheet(
            "QLabel { background: transparent;"
            f" color: {_tc('accent_text', '#FF6B9D')};"
            " font-size: 15px; font-weight: 600; }"
        )
        title_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("在线")
        self.subtitle_label.setStyleSheet(
            "QLabel { background: transparent;"
            f" color: {_tc('text_secondary', '#BBBBBB')};"
            " font-size: 11px; margin-left: 4px; }"
        )
        title_layout.addWidget(self.subtitle_label)
        title_layout.addStretch()

        # 置顶按钮
        # v2.1(I-2): 图标位改矢量字形（文案内嵌 → QSS color/hover 仍生效，置顶态重着色不丢；
        # 缺字体自动回落原 emoji）。manifest 无 pushpin 名，取 anchor（锚定/固定）语义。
        self.pin_btn = QPushButton(icons.text_glyph("anchor", "📌"))
        _tool_btn_w, _tool_btn_h = _TITLE_TOOL_BTN_SIZE
        self.pin_btn.setFixedSize(_tool_btn_w, _tool_btn_h)
        self.pin_btn.setCursor(Qt.PointingHandCursor)
        self.pin_btn.setStyleSheet(self._idle_tool_button_qss("accent_text"))

        self.pin_btn.setToolTip("窗口置顶")
        self.pin_btn.clicked.connect(self._on_toggle_pin)
        title_layout.addWidget(self.pin_btn)

        # 合并按钮（Attach）
        self.attach_btn = QPushButton(icons.text_glyph("link", "🔗"))
        self.attach_btn.setFixedSize(_tool_btn_w, _tool_btn_h)
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setStyleSheet(self._idle_tool_button_qss("info"))
        self.attach_btn.setToolTip("合并到主窗口")
        self.attach_btn.clicked.connect(self._on_attach)
        title_layout.addWidget(self.attach_btn)

        # v1.4：本窗口是无边框自绘标题栏，窗口控制按钮必须自带可见符号。
        # 此前只用极淡的 − □ × ，在浅色标题栏上几乎看不见（像是空白按钮），
        # 这里统一给符号 + 中文 tooltip + 主题取色的 hover 态。
        # v2.2.2(P3)：符号文本不再在这里写死 —— 交给 `_refresh_icon_glyphs()`
        #   唯一写入（图标名 / Unicode 兜底 / 字号全部真值源在 `_TITLE_BUTTONS`），
        #   这样关闭键能随图标字体就绪状态重取，且不存在第二处字形来源。
        self.min_btn = QPushButton()
        self.max_btn = QPushButton()
        self.close_btn = QPushButton()
        self.min_btn.clicked.connect(self.showMinimized)
        self.max_btn.clicked.connect(self._toggle_maximize)
        self.close_btn.clicked.connect(self.hide)
        _win_btn_w, _win_btn_h = _TITLE_WINDOW_BTN_SIZE
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setFixedSize(_win_btn_w, _win_btn_h)
            btn.setCursor(Qt.PointingHandCursor)
            title_layout.addWidget(btn)
        self._refresh_icon_glyphs()
        self._apply_title_button_theme()

        main_layout.addWidget(title_bar)

        # --- 消息滚动区 ---
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet(
            f"QScrollArea {{ background: {_tc('chat_bg', '#FFF8FA')}; border: none; }}")

        self.messages_container = QWidget()
        self.messages_container.setStyleSheet(f"background: {_tc('chat_bg', '#FFF8FA')};")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(12, 12, 12, 12)
        self.messages_layout.setSpacing(4)
        self.messages_layout.addStretch()
        self.scroll_area.setWidget(self.messages_container)
        main_layout.addWidget(self.scroll_area, 1)

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

        # --- 输入区 ---
        input_container = QWidget()
        input_container.setObjectName("chatInputArea")
        input_container.setStyleSheet(
            "QWidget#chatInputArea {"
            f"  background: {_tc('bg_card', '#FFFFFF')};"
            f"  border-top: 1px solid {_tc('border', '#FFE4EC')};"
            "  border-bottom-left-radius: 16px;"
            "  border-bottom-right-radius: 16px;"
            "}"
        )
        self.input_container = input_container
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(16, 12, 16, 16)
        input_layout.setSpacing(8)

        # v2.2.2(裁决2 · 用户指令)：浮窗的 12 格表情面板**已移除**。
        #   面板原先 `setVisible(False)`，其唯一开关是浮窗的 `emoji_btn` —— 而该按钮
        #   随 P0（浮窗「表情 / 导出 / 语音」三按钮移除）一并删除 ⇒ 面板**无任何路径
        #   可达**，留着即是死代码（每次构造仍建 12 个 QPushButton + 一个 QGridLayout）。
        #   表情功能保留在聊天主面板自己的面板上：`chat_panel_parts/ui_build.py:281-293`
        #   构造、`#quickActionBtn` 开它、`interactions.py:282` 的 `_on_toggle_emoji_panel`
        #   给它开合、`ui_build.py:697-708` 的 `_emoji_css` 给 12 个格子补 `padding:0`。
        #   固化守卫：`tests/test_v22_1_blackbox_fixes.py::test_wp4_chat_window_emoji_panel_absent`。

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
                f"QPushButton#quickReplyBtn {{ background: {_tc('bg_light', '#FFF0F5')};"
                f" color: {_tc('accent_text', '#FF69B4')};"
                f" border: 1px solid {_tc('accent_light', '#FFB6C1')}; border-radius: 10px;"
                f" font-size: 11px; padding: 2px 10px; }}"
                f"QPushButton#quickReplyBtn:hover {{ background: {_tc('accent_light', '#FFB6C1')};"
                f" color: {_tc('text', '#FFFFFF')}; }}"
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
            f"  background: {_tc('bg_light', '#FFF5F7')};"
            f"  border: 1px solid {_tc('border', '#FFD6E0')};"
            "  border-radius: 20px;"
            "  padding: 10px 16px;"
            "  font-size: 14px;"
            f"  color: {_tc('text', '#4A4A4A')};"
            "  line-height: 1.5;"
            f"  selection-background-color: {_tc('accent_light', '#FFB6C1')};"
            "}"
            "QTextEdit#chatInput:focus {"
            f"  border-color: {_tc('accent_text', '#B45073')};"
            f"  background: {_tc('bg_card', '#FFFFFF')};"
            "}"
        )
        # 安装事件过滤器捕获 Enter / Shift+Enter
        self.input_edit.installEventFilter(self)
        input_row.addWidget(self.input_edit, 1)

        # 停止按钮
        self.stop_btn = QPushButton(icons.text_glyph("stop", "⏹"))
        self.stop_btn.setObjectName("chatStopBtn")
        self.stop_btn.setFixedSize(40, 40)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton#chatStopBtn {"
            "  background: #FF6B6B;"
            # v2.2(补修·悬停态取色同类): 原为裸 "color: #FFFFFF"，在 #FF6B6B 实底上
            #   四套主题一致只有 2.775（hover #FF5252 为 3.191）→ 图形字近不可辨。
            #   改走 text_on_accent（实底上的文字令牌，四套均 ≥4.5：6.131/4.664/
            #   6.3x/5.1x）。⚠ 底色 #FF6B6B 仍是裸硬编码值，属 QSS/令牌治理线，
            #   不在本次取色修复范围（见回传「残留」）。
            f"  color: {_tc('text_on_accent', '#1C1C1E')};"
            "  border: none;"
            "  border-radius: 20px;"
            # v2.2.1(黑框修复·二轮)：40×40 定尺寸，通用 padding 8/20 把内容区压成
            #   0×24 → 「⏹」一个像素都画不出来（字形 0 → 补 padding:0 后 36 px）。
            "  padding: 0px;"
            "  font-size: 14px;"
            "}"
            "QPushButton#chatStopBtn:hover { background: #FF5252; }"
        )
        self.stop_btn.clicked.connect(self._on_stop_generation)
        self.stop_btn.setVisible(False)
        input_row.addWidget(self.stop_btn, alignment=Qt.AlignBottom)

        self.send_btn = QPushButton(icons.text_glyph("send", "➤"))
        self.send_btn.setObjectName("chatSendBtn")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(
            "QPushButton#chatSendBtn {"
            f"  background: {_tc('primary', '#FF9EB5')};"
            f"  color: {_tc('text_on_accent', '#FFFFFF')};"
            "  border: none;"
            "  border-radius: 20px;"
            # v2.2.1(黑框修复·二轮)：40×40 定尺寸，通用 padding 8/20 把内容区压成
            #   0×24 → 「➤」一个像素都画不出来（字形 0 → 补 padding:0 后 44 px）。
            "  padding: 0px;"
            "  font-size: 16px;"
            "  font-weight: bold;"
            "}"
            f"QPushButton#chatSendBtn:hover {{ background: {_tc('primary_dark', '#FF8AA5')}; }}"
            f"QPushButton#chatSendBtn:pressed {{ background: {_tc('primary_dark', '#FF6B8A')}; }}"
            f"QPushButton#chatSendBtn:disabled {{ background: {_tc('disabled_bg', '#FFD6E0')}; }}"
        )
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn, alignment=Qt.AlignBottom)

        input_layout.addLayout(input_row)

        # 底部工具行：仅剩快捷键提示。
        # v2.2.2(需求·用户指令)：浮窗的「表情 / 导出 / 语音」三个扁平文字按钮**已移除**。
        #   三项功能仍在聊天主面板上（导出 = `ui_build.py` 的 `#exportChatBtn`，
        #   表情 = `#quickActionBtn`，语音 = 主面板语音入口），故本次只删浮窗
        #   这一套入口，并连带删掉 `_apply_theme` 里对这三个按钮的 `setStyleSheet` 重刷。
        bottom_row = QHBoxLayout()
        # v2.2.2(缺陷·横向被压 → 已随三按钮移除而不可达)：本行原先并排「表情 / 导出 /
        #   语音」三个扁平文字按钮 + 本提示标签，且布局上**不能**用 addStretch() 顶替
        #   下面那行 —— 裸 QLabel 的 minimumSizeHint ≡ 全文宽（QLabel 既不省略也不换行），
        #   整行最小宽 = 三按钮 sizeHint + 全文提示 > 容器可用宽 ⇒ QBoxLayout 按比例摊派
        #   亏空，会连带把三个按钮压到低于 sizeHint ⇒ 横向裁字。实测（均 `show()`，四主题
        #   一致，数字**按平台分组**，两型号字宽不同不可混用）：
        #     offscreen 平台：控件 88px、内容区 48px、advance 48px；最小窗宽 400 档被压到
        #       81px（内容区 41 < advance 48）⇒ 裁字。
        #     真实平台：控件 85px、内容区 45px、advance 45px；同档被压到 81px
        #       （内容区 41 < advance 45）⇒ 裁字。
        #   三按钮已删（用户指令），本行只剩提示标签，该挤压不再可能发生。下列两行保留，
        #   作用是让提示标签可以窄于全文宽、不把输入区顶宽：`setMinimumWidth(1)` 写 1 而
        #   非 0（Qt 把 (0,0) 当作「未设置」，会回落到 minimumSizeHint），
        #   `addWidget(..., 1)` 让它吃下全部剩余宽度（宽窗右对齐 ⇒ 视觉与原先一致，
        #   窄窗下由它先让位）。
        self._hint_label = QLabel("Enter 发送 · Shift+Enter 换行")
        self._hint_label.setAlignment(Qt.AlignRight)
        self._hint_label.setMinimumWidth(1)
        bottom_row.addWidget(self._hint_label, 1)
        self._update_hint_theme()
        input_layout.addLayout(bottom_row)

        main_layout.addWidget(input_container)

    def _connect_signals(self) -> None:
        """接线：与 ``chat_service`` 无关的通道**不受其缺失影响**。

        v2.2.2(缺陷·脆弱耦合)：此前首行 `if self.chat_service is None: return`
        会让 theme_changed / gui_session.message_added / role_bridge.role_changed /
        tts.state_changed / companion_bridge.mood_changed **一并**跳过 —— 这些订阅
        只依赖 app_ctx 上的**其它**对象。真实路径下 chat_service 恒有值（main.py
        注入），症状不可观测；但任一注入失败都会连带断掉全部通道。现改为「判空只
        保护依赖它的那一组连接」+ 每组一次性标记（重复 connect 会让同一槽被调多
        次），同型修法见 gui/pages/page_home.py::_connect_companion。
        """
        # --- 通道①：依赖 chat_service 的流式 / 工具 / 授权事件（缺失只跳过本组）---
        if self.chat_service is not None and not self._svc_connected:
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
            except Exception:
                logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)
            self._svc_connected = True
        # v1.6(P0-3): 未点击的反馈动作行追踪。与 chat_service 无关，故搬出上面那组
        #   无条件初始化 —— 此前 chat_service 缺失时该属性从未建立。
        if not hasattr(self, "_feedback_bars"):
            self._feedback_bars: list = []

        # --- 通道②：v1.2(A-11)(B5) 托盘 tooltip 随心情更新（最小实现：复用现有托盘
        #   图标，只做 tooltip 文案，无数值红线；无 bridge 则静默跳过）---
        if not self._mood_connected:
            try:
                bridge = getattr(self.app_ctx, "companion_bridge", None)
                if bridge is not None and hasattr(bridge, "mood_changed") \
                        and hasattr(bridge.mood_changed, "connect"):
                    bridge.mood_changed.connect(self._on_tray_mood_changed)
                    self._mood_connected = True
            except Exception:
                logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # --- 通道③：会话消息广播 ---
        if not self._session_connected:
            gui_session = getattr(self.app_ctx, "gui_session", None)
            if gui_session is not None:
                gui_session.message_added.connect(self._on_message_added)
                self._session_connected = True

        # --- 通道④：换肤（不依赖 chat_service）---
        if not self._theme_connected:
            theme_engine = getattr(self.app_ctx, "theme_engine", None)
            if theme_engine is not None:
                theme_engine.theme_changed.connect(self._on_theme_changed)
                self._theme_connected = True

        # --- 通道⑤：v2.1(UI-P2) 角色生效 → 气泡人名（given_name）缓存失效（浮窗独立
        #   订阅，保证浮窗单独使用时也能跟上角色切换；解析次数 = 角色切换次数，非气泡
        #   条数）---
        if not self._role_connected:
            try:
                _rb = getattr(self.app_ctx, "role_bridge", None)
                if _rb is not None and hasattr(_rb, "role_changed") \
                        and hasattr(_rb.role_changed, "connect"):
                    _rb.role_changed.connect(self._on_role_changed)
                    self._role_connected = True
            except Exception:
                logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

        # --- 通道⑥：v1.3(P1-1) TTS 朗读归属变化 -> 刷新浮窗气泡「朗读/停止」按钮态 ---
        if not self._tts_connected:
            tts = getattr(self.app_ctx, "tts", None)
            if tts is not None and hasattr(tts, "state_changed"):
                try:
                    tts.state_changed.connect(self._on_tts_state_changed)
                    self._tts_connected = True
                except Exception:
                    logger.debug("静默降级：_connect_signals 中忽略异常", exc_info=True)

    def _adjust_input_height(self) -> None:
        """v1.4.6: 输入框随内容多行增高（48~120）。"""
        try:
            doc_h = int(self.input_edit.document().size().height() + 14)
            self.input_edit.setFixedHeight(max(48, min(doc_h, 120)))
        except Exception:
            logger.debug("静默降级：_adjust_input_height 中忽略异常", exc_info=True)

    # ------------------------------------------------------------------
    # v2.2(缺陷1)：配色基因（QSS 串只在此处生成，换肤期重新生成即生效）
    # ------------------------------------------------------------------
    def _idle_tool_button_qss(self, hover_color_key: str) -> str:
        """标题栏小图标按钮（置顶/合并）常态 QSS：次要文字色 + 悬停实底。

        v2.2.1(黑框修复·二轮)：补 ``padding: 0px``。本组按钮 ``setFixedSize(28, 28)``，
        而应用级 ``QPushButton { padding: 8px 20px; }`` 光左右就吃掉 40px ⇒ 内容区
        （``SE_PushButtonContents``）实测 **-12×12**，``📌`` / ``🔗`` 结构上不可能绘制
        （字形像素 0 → 独立重扫补 ``padding:0`` 后 28 px）。与 base.qss §1e-bis 同一缺陷类。
        ⚠ 只补 padding：尺寸 / 底色 / 字色 / 圆角 / 字号一律不动 —— 违反会位移标题栏版式。
        """
        idle = theme_color(self.app_ctx, "text_secondary", "#888888")
        hover_bg = theme_color(self.app_ctx, "bg_light", "#F5F5F5")
        hover_fg = theme_color(self.app_ctx, hover_color_key, "#FF6B9D")
        return (
            "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " padding: 0px;"
            f" color: {idle}; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; color: {hover_fg}; }}"
        )

    def _pinned_tool_button_qss(self) -> str:
        """置顶生效态的按钮 QSS（强调底 + 强调文字）。

        padding 归零的理由与 :meth:`_idle_tool_button_qss` 完全一致（同一 28×28 按钮的
        另一态）—— 漏掉这一支会让「置顶生效」时字形又消失。
        """
        bg = theme_color(self.app_ctx, "bg_light", "#FFF0F3")
        fg = theme_color(self.app_ctx, "accent_text", "#FF6B9D")
        hover_bg = theme_color(self.app_ctx, "accent_light", "#FFE4EC")
        return (
            "QPushButton { border: none; border-radius: 6px; padding: 0px;"
            f" background: {bg}; color: {fg}; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; color: {fg}; }}"
        )

    def _apply_title_bar_theme(self) -> None:
        """重刷标题栏 / 输入区容器与其中的文字、按钮配色（换肤期调用）。

        v2.2(缺陷1)：``_apply_theme`` 此前只刷 main_container / 消息区 / 输入框，
        标题栏与输入区容器**没有重刷点** → 换肤后仍停在旧色（深色主题下即白底
        浅字，对比度 1.139）。
        """
        def _c(key: str, fallback: str) -> str:
            return theme_color(self.app_ctx, key, fallback)

        cursor_bg = _c("bg_card", "#FFFFFF")
        cursor_border = _c("border", "#FFE4EC")
        accent_text = _c("accent_text", "#FF6B9D")
        text_secondary = _c("text_secondary", "#BBBBBB")

        if getattr(self, "title_bar", None) is not None:
            self.title_bar.setStyleSheet(
                "QWidget#chatTitleBar {"
                f"  background: {cursor_bg};"
                f"  border-bottom: 1px solid {cursor_border};"
                "  border-top-left-radius: 16px;"
                "  border-top-right-radius: 16px;"
                "}"
            )
        if getattr(self, "icon_label", None) is not None:
            self.icon_label.setStyleSheet(
                f"background: transparent; font-size: 16px; color: {accent_text};")
        if getattr(self, "title_label", None) is not None:
            self.title_label.setStyleSheet(
                f"QLabel {{ background: transparent; color: {accent_text};"
                f" font-size: 15px; font-weight: 600; }}")
        if getattr(self, "subtitle_label", None) is not None:
            self.subtitle_label.setStyleSheet(
                f"QLabel {{ background: transparent; color: {text_secondary};"
                f" font-size: 11px; margin-left: 4px; }}")
        if getattr(self, "pin_btn", None) is not None:
            self.pin_btn.setStyleSheet(
                self._pinned_tool_button_qss() if self._is_pinned
                else self._idle_tool_button_qss("accent_text"))
        if getattr(self, "attach_btn", None) is not None:
            self.attach_btn.setStyleSheet(self._idle_tool_button_qss("info"))
        if getattr(self, "input_container", None) is not None:
            self.input_container.setStyleSheet(
                "QWidget#chatInputArea {"
                f"  background: {cursor_bg};"
                f"  border-top: 1px solid {cursor_border};"
                "  border-bottom-left-radius: 16px;"
                "  border-bottom-right-radius: 16px;"
                "}"
            )

    def _apply_title_button_theme(self) -> None:
        """给自绘标题栏的窗口控制按钮上符号 / 中文 tooltip / 主题色 hover 态。

        取色一律走 theme_color（禁裸硬编码色），随主题切换即时生效。
        v1.4.3 加强可见性：常态用正文主色（text）+ 加粗符号，确保浅/深标题栏上都
        清晰可辨；hover 改为「实底色块」加强对比（最小/最大=主色实底，
        关闭键=警示色实底）。
        v2.2(补修·悬停态取色)：实底上的字色此前误用 ``bg_card``（浅色主题=白、
        深色主题=卡片深色），既非「落实底的文字」语义键，实测四套主题里
        最小/最大化 3.267 / 2.163 / 6.485 / 3.245、关闭键 2.273 / 2.273 / 8.886 /
        2.273 —— 半数以上不达标。正解是 ``text_on_accent``（"强调实底上的文字"
        令牌，四套均已注册）：换键后最小/最大化 5.208 / 5.984 / 6.485 / 5.192、
        关闭键 7.484 / 5.693 / 8.886 / 7.411，全部 ≥4.5。
        注意**不能**改用 ``text``：ui_night 的 ``text`` 是浅色（#F2EFF5），压在
        警示实底上只剩 1.716。
        """
        # 常态：正文主色（两主题均足够对比）；加粗符号已随 _TITLE_BUTTONS 字号放大。
        idle = theme_color(self.app_ctx, "text", "#4A4A4A")
        # hover 实底：最小/最大用主色实底 + 「强调实底上的文字」色。
        hover_bg = theme_color(self.app_ctx, "primary", "#FFB6C1")
        hover_fg = theme_color(self.app_ctx, "text_on_accent", "#1C1C1E")
        # 关闭键 hover 保持警示语义色（底）+ 同一「实底文字」色。
        close_hover_bg = theme_color(self.app_ctx, "state_warn", "#E5A02E")
        close_hover_fg = theme_color(self.app_ctx, "text_on_accent", "#1C1C1E")

        for btn, (_symbol, tooltip, font_size, _icon_name) in zip(
            (self.min_btn, self.max_btn, self.close_btn), _TITLE_BUTTONS
        ):
            if btn is None:
                continue
            btn.setToolTip(tooltip)
            btn.setStyleSheet(
                # v2.2.1(黑框修复·二轮)：窗口控制键 32×26 定尺寸，通用 padding 8/20
                #   把内容区压成 -8×10（字形 0 → 补 padding:0 后 22/44/81 px）→ 补 `padding: 0px`。
                "QPushButton { background: transparent; border: none; border-radius: 6px;"
                " padding: 0px;"
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
        # v2.1(UI-Fix-0913)：补上容器/输入区主题刷新 —— `_apply_theme` 此前**定义了却从未
        #   被调用**（全文件无调用点，实为死代码），导致切换主题后 main_container /
        #   messages_container / 输入框 / 发送按钮等仍停在 _init_ui 里的硬编码粉色上
        #   （气泡能跟随是因为这里单独调了 widget.update_theme()）。
        self._apply_theme()
        self._apply_title_button_theme()
        # v2.1(G-2/D-V21-04): 深浅切换 → 重设 DWM immersive dark（否则材质色调不对）
        try:
            if self.isVisible():
                self._apply_glass_popup()
        except Exception:
            logger.debug("静默降级：_on_theme_changed 中忽略异常", exc_info=True)
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
                logger.debug("静默降级：_on_theme_changed 中忽略异常", exc_info=True)

    def _apply_theme(self) -> None:
        """应用当前主题到聊天窗口容器（构造期与换肤期同源）。"""
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
        # v2.2(缺陷1)：补标题栏 / 输入区容器的重刷点（此前无，换肤后残留旧色）。
        self._apply_title_bar_theme()
        self._update_hint_theme()
        # v2.2.2(P2/P5 缺陷)：换肤 / 主题变更点必须重取「图标字形」与「标题人名」——
        #   这两者在改前都只在构造期求值一次（字形走 `icons.text_glyph`，标题是
        #   硬编码字面量），样式表刷新不会带上它们 ⇒ 换肤后仍是旧值。
        #   顺序：`_refresh_title_text()` 必须**晚于** `_apply_title_bar_theme()`
        #   （后者重设 `title_label` 的样式表；先写名再刷样式虽也成立，但把「先样式
        #    后内容」固定下来可避免将来有人在样式里带 `setText` 时互相覆盖）。
        self._refresh_icon_glyphs()
        self._refresh_title_text()

        # v2.1(UI-Fix-0913) 输入区主题化：输入框 + 发送按钮。
        #   这两处在 _init_ui 里是硬编码粉色，切主题时若不重刷就会残留。
        #   停止按钮为「停止生成」的语义警示红，跨主题应保持一致，故刻意不主题化。
        try:
            _bg_l = theme_engine.get_color("bg_light", "#FFF5F7")
            _bd = theme_engine.get_color("border", "#FFD6E0")
            _txt = theme_engine.get_color("text", "#4A4A4A")
            _ac_l = theme_engine.get_color("accent_light", "#FFB6C1")
            # v2.2.1：焦点圈改取 accent_text。此前取 accent_light，而四套主题里
            # accent_light ≡ bg_light，且该输入框自身底也是 bg_light
            # → 焦点圈与其自身底对比 **1.000，完全不可见**。
            # accent_text 落 bg_light 为 4.125~4.280，四套全达标（非文本图形需 ≥3:1）。
            _ac_tx = theme_engine.get_color("accent_text", "#B45073")
            _bg_card = theme_engine.get_color("bg_card", "#FFFFFF")
            if getattr(self, "input_edit", None) is not None:
                self.input_edit.setStyleSheet(
                    f"QTextEdit#chatInput {{"
                    f"  background: {_bg_l};"
                    f"  border: 1px solid {_bd};"
                    f"  border-radius: 20px;"
                    f"  padding: 10px 16px;"
                    f"  font-size: 14px;"
                    f"  color: {_txt};"
                    f"  line-height: 1.5;"
                    f"  selection-background-color: {_ac_l};"
                    f"}}"
                    f"QTextEdit#chatInput:focus {{"
                    f"  border-color: {_ac_tx};"
                    f"  background: {_bg_card};"
                    f"}}"
                )
        except Exception:
            logger.debug("静默降级：_apply_theme 中忽略异常", exc_info=True)
        try:
            _primary = theme_engine.get_color("primary", "#FF9EB5")
            _primary_d = theme_engine.get_color("primary_dark", "#FF8AA5")
            _disabled = theme_engine.get_color("disabled_bg", "#FFD6E0")
            _on_accent = theme_engine.get_color("text_on_accent", "#FFFFFF")
            if getattr(self, "send_btn", None) is not None:
                self.send_btn.setStyleSheet(
                    f"QPushButton#chatSendBtn {{"
                    f"  background: {_primary};"
                    f"  color: {_on_accent};"
                    f"  border: none;"
                    f"  border-radius: 20px;"
                    # v2.2.1(黑框修复·二轮)：padding 归零（与 _init_ui 同源，换肤期重刷不漏）。
                    f"  padding: 0px;"
                    f"  font-size: 16px;"
                    f"  font-weight: bold;"
                    f"}}"
                    f"QPushButton#chatSendBtn:hover {{ background: {_primary_d}; }}"
                    f"QPushButton#chatSendBtn:pressed {{ background: {_primary_d}; }}"
                    f"QPushButton#chatSendBtn:disabled {{ background: {_disabled}; }}"
                )
        except Exception:
            logger.debug("静默降级：_apply_theme 中忽略异常", exc_info=True)
        # 快捷回复：在 _init_ui 的循环内创建（无 self 引用），故用 findChildren 取回再刷。
        # v2.2.2(裁决2)：原「表情面板 + 其 12 格」那一段随浮窗表情面板一并移除
        #   （`QWidget#emojiPanel` 与 44×36 格子都已不在本窗）。
        try:
            _e_bg_l = theme_engine.get_color("bg_light", "#FFF0F5")
            _e_txt = theme_engine.get_color("text", "#4A4A4A")
            # v2.2(缺陷1)：文字色用 accent_text（浅底强调文字令牌），
            #   原 accent/primary 在浅色主题的浅底上只有 ~2.8，仍 <3。
            _e_ac_txt = theme_engine.get_color("accent_text", "#FF69B4")
            _e_ac_l = theme_engine.get_color("accent_light", "#FFB6C1")
            for _b in self.findChildren(QPushButton, "quickReplyBtn"):
                _b.setStyleSheet(
                    f"QPushButton#quickReplyBtn {{ background: {_e_bg_l}; color: {_e_ac_txt};"
                    f" border: 1px solid {_e_ac_l}; border-radius: 10px;"
                    f" font-size: 11px; padding: 2px 10px; }}"
                    f"QPushButton#quickReplyBtn:hover {{ background: {_e_ac_l};"
                    f" color: {_e_txt}; }}")
        except Exception:
            logger.debug("静默降级：_apply_theme 中忽略异常", exc_info=True)
    def _update_hint_theme(self) -> None:
        """更新快捷键提示标签颜色。"""
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        color = "#CCCCCC"
        if theme_engine is not None:
            color = theme_engine.get_color("text_secondary", "#CCCCCC")
        # v2.2.2(缺陷2)：提示语裸 QLabel 同样被 ${bg} 刷底（它坐在 bg_card 输入区上）。
        self._hint_label.setStyleSheet(
            f"QLabel {{ background: transparent; color: {color}; font-size: 11px; }}")

    def _refresh_icon_glyphs(self) -> None:
        """重新解析本窗所有「图标字体字形」文本（换肤 / 主题变更点调用）。

        v2.2.2(P2 缺陷·字形晚注册)：`icons.text_glyph()` 的调用点原**只在构造期求值一次**，
        而 `_apply_theme` / `_on_theme_changed` 只重设样式表、**从不重取文本** ⇒ 图标字体
        缺失、或注册晚于建窗时，这 8 个位**永久停在 emoji / Unicode 兜底态**：之后注册
        字体、切多少次主题都不会恢复。实测（真实平台，四主题一致）见
        `_evidence_b/out_p2p3p5_real_*.txt`：未注册字体建窗 → 注册 + `icons.configure`
        + 换肤两轮，改前 5 个文本**一字未变**（缺陷）；改后全部恢复 remixicon 字形。

        幂等：`setText` 是整体覆盖而非追加，字形已就位的位重复写入同一字符，零副作用。
        """
        for _attr, _name, _fallback in _GLYPH_SLOTS:
            _w = getattr(self, _attr, None)
            if _w is None:
                continue
            try:
                _w.setText(icons.text_glyph(_name, _fallback))
            except Exception:
                logger.debug("静默降级：_refresh_icon_glyphs 中忽略异常", exc_info=True)
        # 标题栏窗口控制键：图标名 / Unicode 兜底 / 字号同源于 `_TITLE_BUTTONS`
        #   （唯一真值源，不在此另写一套字面量）。
        _btns = (getattr(self, "min_btn", None), getattr(self, "max_btn", None),
                 getattr(self, "close_btn", None))
        for _btn, (_sym, _tooltip, _fs, _icon_name) in zip(_btns, _TITLE_BUTTONS):
            if _btn is None:
                continue
            try:
                _btn.setText(
                    icons.text_glyph(_icon_name, _sym) if _icon_name else _sym)
            except Exception:
                logger.debug("静默降级：_refresh_icon_glyphs 中忽略异常", exc_info=True)

    def _refresh_title_text(self) -> None:
        """标题显示「与<当前角色人名>的对话」（**运行期**刷新，换肤 / 切角色各一次）。

        v2.2.2(P5 缺陷)：标题原为硬编码字面量「与女仆的对话」（本文件 `title_label`
        的 `setText` 调用点实测 **0** 处，`_on_role_changed` 只刷副标题）⇒ 切角色后
        标题恒定不变；且「女仆」是角色**类型标签**、不是人名，违反本仓 v1.9 硬规则
        「显示谁说话一律取当前角色 `given_name`」。

        人名唯一来源 = :func:`resolve_default_speaker_name`（**既有解析器**，三级兜底：
        `role.given_name` → 预设 `given_name` → 产品名「码铃」；`given_name` 为空是
        **合法状态**，**不会**退化成 `role.name` 这种人设标签）。
        解析器抛异常 / 返回空串时**保留原标题文案**（不写「与的对话」这种半截文案）。
        """
        _label = getattr(self, "title_label", None)
        if _label is None:
            return
        try:
            _name = (resolve_default_speaker_name() or "").strip()
        except Exception:
            logger.debug("静默降级：_refresh_title_text 中忽略异常", exc_info=True)
            return
        if _name:
            _label.setText(f"与{_name}的对话")

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
            self._exec_modal_fade(box)
            approved = box.clickedButton() is yes_btn
        except Exception:
            approved = False
        try:
            if self.chat_service is not None:
                self.chat_service.resolve_agent_authorization(approved)
        except Exception:
            logger.debug("静默降级：_on_agent_authorization_requested 中忽略异常", exc_info=True)

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
            logger.debug("静默降级：_on_agent_tool_event 中忽略异常", exc_info=True)

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

    # v2.2.2(裁决2)：原 `_on_emoji_clicked()`（表情插入输入框光标处）随浮窗表情面板
    #   一并移除 —— 它在浮窗内唯一调用者就是被删面板的 12 个格子。主面板同名方法
    #   `ChatPanelWidget._on_emoji_clicked`（`interactions.py:285`）不受影响。

    def _on_quick_reply(self, text: str) -> None:
        """点击快捷回复按钮，填入输入框并触发发送。"""
        self.input_edit.setPlainText(text)
        self._on_send()

    def _on_role_changed(self, role_id: str, avatar_path: str = "",
                         base_expr: str = "normal") -> None:
        """v2.1(UI-P2): 角色生效广播 → 清人名缓存（历史气泡不追溯）。

        v2.2.2(P5 缺陷)：此前**只**清缓存、标题不动 ⇒ 切角色后标题恒定。
        现在同点重取标题人名（清缓存 → 重取，两步同序，才不会读到旧缓存值）。
        """
        try:
            invalidate_default_speaker_name()
        except Exception:
            logger.debug("静默降级：_on_role_changed 中忽略异常", exc_info=True)
        # v2.2.2(P5)：运行期挂点 —— 切角色即刷新标题（不是只改构造期字面量）
        self._refresh_title_text()

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
            self.subtitle_label.setText(f"已收藏 {icons.text_glyph('auto_awesome', '✨')}")
        except Exception:
            logger.debug("静默降级：_on_favorite_requested 中忽略异常", exc_info=True)
        try:
            from gui.qt_compat import QTimer
            QTimer.singleShot(1500, self._restore_subtitle)
        except Exception:
            logger.debug("静默降级：_on_favorite_requested 中忽略异常", exc_info=True)

    def _restore_subtitle(self) -> None:
        try:
            self.subtitle_label.setText("在线")
        except Exception:
            logger.debug("静默降级：_restore_subtitle 中忽略异常", exc_info=True)

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
                logger.debug("静默降级：_on_bubble_read_aloud 中忽略异常", exc_info=True)
            return
        text = (bubble.get_text() or "").strip()
        if not text:
            return
        try:
            tts.speak(text, owner=bubble)
        except Exception:
            logger.debug("静默降级：_on_bubble_read_aloud 中忽略异常", exc_info=True)

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
            logger.debug("静默降级：_on_tts_state_changed 中忽略异常", exc_info=True)

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
            self.pin_btn.setStyleSheet(self._pinned_tool_button_qss())
            self.pin_btn.setToolTip("取消置顶")
        else:
            self.setWindowFlags(flags & ~Qt.WindowStaysOnTopHint)
            self.pin_btn.setStyleSheet(self._idle_tool_button_qss("accent_text"))
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
            logger.debug("静默降级：_refresh_tray_mood 中忽略异常", exc_info=True)

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
            logger.debug("静默降级：_on_proactive_feedback_ready 中忽略异常", exc_info=True)

    def _on_feedback_picked(self, subject: str, scene: str, kind: str) -> None:
        """三键回调：纯 memory 策略写入（绝不触碰 intimacy / 交互打点）。"""
        session = getattr(self.app_ctx, "session", None)
        memory_mgr = getattr(session, "memory_mgr", None) if session is not None else None
        if memory_mgr is not None and hasattr(memory_mgr, "record_followup_feedback"):
            try:
                memory_mgr.record_followup_feedback(subject, kind)
            except Exception:
                logger.debug("静默降级：_on_feedback_picked 中忽略异常", exc_info=True)

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
            logger.debug("静默降级：_on_proactive_ready 中忽略异常", exc_info=True)

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
