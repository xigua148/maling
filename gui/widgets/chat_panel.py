"""聊天面板 —— 消息气泡区、输入框、发送按钮、快捷操作栏、会话列表，支持展开为独立窗口。

第四阶段扩展：文件拖拽上传、消息编辑/重新生成、多会话标签页、语音输入。

v2.1(P0-②)：本模块原为 4000 行「单类 130+ 方法」，已按职责拆为 ``chat_panel_parts/``
下 9 个 mixin（浮层淡入淡出 / 输入补全 / 看屏 / 会话 / 消息与群聊 / 流式 /
交互与开关 / 扩展功能 / UI 构建）。本文件只保留：类声明与类属性、实例状态初始化、
以及两处粘合方法（``_scroll_to_bottom`` / ``eventFilter``）。拆分方式为**纯移动**，
行为零变化（全量回归前后一致）。
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("maid_coder.gui.chat_panel")

from gui.qt_compat import QEvent, QWidget, Qt

from gui.widgets.chat_window import ChatWindow
from gui.command_registry import CommandRegistry

# v2.1(P0-②): 拆分出的 mixin —— 纯移动，行为不变
from gui.widgets.chat_panel_parts.popup_fade import ChatPopupFadeMixin
from gui.widgets.chat_panel_parts.completion import ChatCompletionMixin
from gui.widgets.chat_panel_parts.screen_watch import ChatScreenWatchMixin
from gui.widgets.chat_panel_parts.sessions import ChatSessionsMixin
from gui.widgets.chat_panel_parts.messaging import ChatMessagingMixin
from gui.widgets.chat_panel_parts.streaming import ChatStreamingMixin
from gui.widgets.chat_panel_parts.interactions import ChatInteractionsMixin
from gui.widgets.chat_panel_parts.extras import ChatExtrasMixin
from gui.widgets.chat_panel_parts.ui_build import ChatUiBuildMixin
# v2.1(P0-②): _ElidedLabel 已抽至 chat_panel_parts/elided_label.py（此处 re-export，兼容既有引用）
from gui.widgets.chat_panel_parts.elided_label import _ElidedLabel  # noqa: F401


class ChatPanelWidget(ChatPopupFadeMixin, ChatCompletionMixin, ChatScreenWatchMixin, ChatSessionsMixin, ChatMessagingMixin, ChatStreamingMixin, ChatInteractionsMixin, ChatExtrasMixin, ChatUiBuildMixin, QWidget):
    """聊天面板：会话列表 + 消息列表 + 快捷操作栏 + 输入区 + 展开按钮。"""

    EMOJIS = ["❤", "✨", "(｡･ω･｡)", "(´▽｀)", "(*´∀`)~♥", "(๑•̀ㅂ•́)و✧",
              "(｡♥‿♥｡)", "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", "(｡◕‿◕｡)", "♪(´ε｀ )", "(≧▽≦)", "(｡･ω･｡)ﾉ♡"]

    QUICK_REPLIES = [
        "辛苦了~",
        "做得不错❤",
        "继续吧",
        "等等，我有别的事说",
    ]

    # v2.1(I-2/D-V21-06): 顶栏按钮图标位 —— 属性名 → 矢量图标名；
    # 图标字体不可用时回落到 _TITLE_ICON_FALLBACK 的原 emoji 文本（不空白）。
    _TITLE_ICON_NAMES = {
        "export_btn": "export",
        "tab_mode_btn": "layout",
        "expand_btn": "expand",
        "style_btn": "palette",
    }
    _TITLE_ICON_FALLBACK = {
        "export_btn": "📤",
        "tab_mode_btn": "🗂",
        "expand_btn": "↗",
        "style_btn": "🎨",
    }
    # hover 态图标取色键（与各按钮既有 QSS hover 前景对齐；None = 沿用正文色）；
    # 取色唯一入口 theme_color，禁裸硬编码色。
    # v2.2.1(换肤一致性)：export_btn / expand_btn 的 hover 实底是 accent（= primary），
    # 其 QSS hover 前景已是 text_on_accent；此处原取 bg_card（四套浅色下 = #FFFFFF）
    # 落 accent 实底只有 3.267 / 2.163 / 2.678 / 3.245（ui_minimal/cream/night/whale 浅色），
    # 其中 ui_cream、ui_night 两档低于 3:1（图形对象下界）⇒ 对齐为 text_on_accent
    # （8 档最差 5.192，全部达标）。
    _TITLE_ICON_HOVER_KEY = {
        "export_btn": "text_on_accent",
        "expand_btn": "text_on_accent",
        "tab_mode_btn": None,
        "style_btn": None,
    }
    _TITLE_ICON_SIZE = 16

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
        # v2.1(M-2/D-V21-02): 历史重载期标志 —— 为真时新增气泡不放入场动画
        #（切会话 / 重载历史 / 恢复会话绝不逐条重播，避免满屏闪动）
        self._loading_history: bool = False
        # v2.1(I-2): 顶栏图标按钮 hover 重着色登记表（btn -> (name, hover_key)）
        self._icon_buttons: dict = {}
        # 第四阶段：拖拽
        self.setAcceptDrops(True)
        self._init_ui()
        self._connect_signals()
        self._init_handsfree()
        self._init_screen_watch()
        self._load_active_session()


    def _scroll_to_bottom(self) -> None:
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def eventFilter(self, obj, event) -> bool:
        # v2.1(I-2): 顶栏图标按钮 hover 态重着色（QIcon 不随 QSS 伪态变色）
        if obj in self._icon_buttons:
            name, hover_key = self._icon_buttons[obj]
            if event.type() == QEvent.Enter:
                self._set_title_icon(obj, name, hover_key)
            elif event.type() == QEvent.Leave:
                self._set_title_icon(obj, name, None)
            return False
        if obj is self.input_edit and event.type() == event.Type.KeyPress:
            key_event = event
            # v1.7(F10b): @成员补全浮层打开时：方向键选择、Tab/Enter 确认、Esc 关闭
            if getattr(self, "_mention_popup", None) is not None and self._popup_open(self._mention_popup):
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
            if self._popup_open(self._cmd_popup):
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
