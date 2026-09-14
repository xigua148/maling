"""tests/test_v21_chat.py —— v2.1 域6「聊天 / 浮层」自测（V21-10 + V21-11）。

覆盖（全部 offscreen，零真机依赖）：
① 历史重载路径不放动画（``_loading_history`` + 断言未请求 ``motion.fade`` / 无在跑动画）；
② 新消息 / 流式落地会请求入场动画（monkeypatch ``motion.fade`` 断言被调）；
③ ``off`` 档下气泡直接落终态、无半透明残影（opacity 终值正确）；
④ 顶栏按钮在 ``icons.available()==False`` 时回退非空文本；可用时换成矢量图标；
⑤ ``chat_window`` 在不受支持环境（``glass.is_supported→False``）不崩、不设材质；
⑥ 发送链路回归（消息计数不因动画档位变化）；
⑦ 非模态浮层淡入 / 淡出（含 ``off`` 档直显直隐）；模态 ``exec()`` 对话框不做淡出
   （本域不新增其淡出逻辑，仅声明口径 —— 见 ``_fade_*_popup`` 注释）。

隔离：FakeCtx / FakeEngine，绝不读写真实 ~/.maid_coder；页面动效档位测试后复位。
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from gui.qt_compat import QApplication, QEvent, QIcon, QPixmap, Qt, QGraphicsOpacityEffect
import gui.motion as motion
import gui.icons as icons
import gui.glass as glass


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Signal:
    def connect(self, *a, **k):
        return None


class _Cfg:
    """最小 GuiConfig 替身（浮层 Acrylic 开关缺省开）。"""

    glass_popups_enabled = True


class _Engine:
    """最小 ThemeEngine 替身：取色回落 + 深浅有效位 + 主题名 + 信号占位。"""

    def __init__(self, dark: bool = False):
        self._dark = dark
        self.theme_changed = _Signal()

    def get_color(self, key, fallback=""):
        return fallback

    def current_theme_name(self):
        return "ui_minimal"

    def is_dark_effective(self):
        return self._dark


class _Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content
        self.metadata = None


class _Session:
    def __init__(self, msgs=None):
        self.id = "s1"
        self.name = "会话"
        self.messages = list(msgs or [])


class _Ctx:
    """面板 / 浮窗共用最小 app_ctx。"""

    def __init__(self, chat_service=None, dark: bool = False, history=None):
        self.config = _Cfg()
        self.theme_engine = _Engine(dark=dark)
        self.chat_service = chat_service
        self.session_manager = None
        self.companion_bridge = None
        self.companion = None
        self.tts = None
        self.gui_session = None
        self.session = type("S", (), {"history": list(history or [])})()
        self.glass = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _motion_isolate():
    """每例前后复位动效档位 + 清空在跑动画，保证模块级单例不串味。"""
    old = motion.level()
    motion.stop_all(final=False)
    yield
    motion.stop_all(final=True)
    motion.configure(old)


@pytest.fixture
def panel(qapp):
    """标准档下的最小聊天面板（chat_service=None）。"""
    motion.configure("standard")
    from gui.widgets.chat_panel import ChatPanelWidget
    p = ChatPanelWidget(_Ctx())
    qapp.processEvents()
    return p


def _count_bubbles(panel) -> int:
    from gui.widgets.message_bubble import MessageBubble
    n = 0
    for i in range(panel.messages_layout.count()):
        item = panel.messages_layout.itemAt(i)
        if item is not None and isinstance(item.widget(), MessageBubble):
            n += 1
    return n


def _settle(qapp, rounds: int = 40) -> None:
    for _ in range(rounds):
        qapp.processEvents()
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# ① 历史重载不重播（M-2 核心验收点）
# ---------------------------------------------------------------------------
class TestHistoryNoReplay:
    def test_history_reload_requests_no_animation(self, panel, qapp, monkeypatch):
        calls = []
        real_fade = motion.fade

        def spy(*a, **k):
            calls.append(a)
            return real_fade(*a, **k)

        monkeypatch.setattr(motion, "fade", spy)
        session = _Session([_Msg("user", "a"), _Msg("assistant", "b"), _Msg("user", "c")])
        panel._load_session_messages(session)

        assert calls == [], "历史重载绝不请求入场动画"
        assert motion.running_count() == 0
        assert panel._loading_history is False, "标志须在 finally 复位"
        assert _count_bubbles(panel) == 3, "气泡仍须全部渲染（只是不放动画）"

    def test_loading_history_default_off_after_exception(self, panel, monkeypatch):
        # 重载中途异常 → finally 复位，不残留标志（后续新消息仍会入场）
        real = panel._add_message_bubble

        def boom(*a, **k):
            raise RuntimeError("mock 渲染失败")

        monkeypatch.setattr(panel, "_add_message_bubble", boom)
        with pytest.raises(RuntimeError):
            panel._load_session_messages(_Session([_Msg("user", "x")]))
        monkeypatch.setattr(panel, "_add_message_bubble", real)
        assert panel._loading_history is False

    def test_explicit_animate_false_is_silent(self, panel, qapp, monkeypatch):
        calls = []
        real_fade = motion.fade
        monkeypatch.setattr(
            motion, "fade",
            lambda *a, **k: (calls.append(a), real_fade(*a, **k))[1],
        )
        panel._add_message_bubble("assistant", "恢复会话消息", animate=False)
        assert calls == []
        assert motion.running_count() == 0


# ---------------------------------------------------------------------------
# ② 新消息入场
# ---------------------------------------------------------------------------
class TestBubbleEntrance:
    def test_new_message_requests_animation(self, panel, monkeypatch):
        calls = []
        real_fade = motion.fade

        def spy(widget, **k):
            calls.append(widget)
            return real_fade(widget, **k)

        monkeypatch.setattr(motion, "fade", spy)
        bubble = panel._add_message_bubble("user", "你好")
        assert calls, "新消息应请求入场动画"
        assert calls[0] is bubble

    def test_stream_bubble_requests_animation(self, panel, monkeypatch):
        calls = []
        real_fade = motion.fade

        def spy(widget, **k):
            calls.append(widget)
            return real_fade(widget, **k)

        monkeypatch.setattr(motion, "fade", spy)
        panel._on_stream_started()
        panel._on_chunk("流式首包")
        assert calls, "流式气泡落地同样应请求入场动画"

    def test_entrance_never_breaks_send_on_fade_error(self, panel, monkeypatch):
        # 动画抛错也必须被吞掉，绝不影响气泡落地（R-D）
        def boom(*a, **k):
            raise RuntimeError("mock fade 失败")

        monkeypatch.setattr(motion, "fade", boom)
        bubble = panel._add_message_bubble("user", "动画失败也要落地")
        assert bubble is not None
        assert _count_bubbles(panel) == 1

    def test_entrance_reuses_existing_effect(self, panel, qapp):
        bubble = panel._add_message_bubble("user", "复用 effect")
        eff = QGraphicsOpacityEffect(bubble)
        bubble.setGraphicsEffect(eff)
        # 已存在 effect → fade 复用（不叠加），不崩
        panel._apply_bubble_entrance(bubble, True)
        assert isinstance(bubble.graphicsEffect(), QGraphicsOpacityEffect)


# ---------------------------------------------------------------------------
# ③ off 档直落终态（无残影）
# ---------------------------------------------------------------------------
class TestOffLevelTerminal:
    def test_off_level_new_bubble_has_no_residual_effect(self, panel):
        motion.configure("off")
        bubble = panel._add_message_bubble("user", "off-档消息")
        assert bubble.graphicsEffect() is None, "off 档不创建 opacity effect（无残影）"

    def test_off_level_finalizes_existing_partial_opacity(self, panel):
        motion.configure("off")
        bubble = panel._add_message_bubble("assistant", "x", error_style=False)
        eff = QGraphicsOpacityEffect(bubble)
        eff.setOpacity(0.0)  # 人为造「半透明残影」
        bubble.setGraphicsEffect(eff)
        panel._apply_bubble_entrance(bubble, True)
        assert bubble.graphicsEffect().opacity() == 1.0, "off 档须直接设终态 1.0"


# ---------------------------------------------------------------------------
# ④ 顶栏图标化 + emoji 回退
# ---------------------------------------------------------------------------
_TITLE_ATTRS = ("export_btn", "tab_mode_btn", "expand_btn", "style_btn")


class TestTitleIcons:
    def test_fallback_text_when_icons_unavailable(self, qapp, monkeypatch):
        monkeypatch.setattr(icons, "available", lambda: False)
        from gui.widgets.chat_panel import ChatPanelWidget
        p = ChatPanelWidget(_Ctx())
        qapp.processEvents()
        for attr in _TITLE_ATTRS:
            btn = getattr(p, attr)
            assert btn.text().strip(), f"{attr} 图标不可用时应回退非空文本"
            assert btn.icon().isNull(), f"{attr} 不应残留图标"

    def test_vector_icon_when_available(self, qapp, monkeypatch):
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        monkeypatch.setattr(icons, "available", lambda: True)
        monkeypatch.setattr(icons, "icon", lambda name, size=16, color=None: QIcon(pm))
        from gui.widgets.chat_panel import ChatPanelWidget
        p = ChatPanelWidget(_Ctx())
        qapp.processEvents()
        assert len(p._icon_buttons) == 4
        for attr in _TITLE_ATTRS:
            btn = getattr(p, attr)
            assert btn.text() == "", f"{attr} 图标化后应清空 emoji 文本"
            assert not btn.icon().isNull()
            assert btn.iconSize().width() == p._TITLE_ICON_SIZE
            assert btn.width() == 32 and btn.height() == 28, "尺寸与原占位对齐"

    def test_hover_recolor_does_not_crash(self, qapp, monkeypatch):
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        seen = []
        monkeypatch.setattr(icons, "available", lambda: True)
        monkeypatch.setattr(icons, "icon", lambda name, size=16, color=None: (seen.append(color), QIcon(pm))[1])
        from gui.widgets.chat_panel import ChatPanelWidget
        p = ChatPanelWidget(_Ctx())
        qapp.processEvents()
        for btn in list(p._icon_buttons):
            p.eventFilter(btn, QEvent(QEvent.Enter))
            p.eventFilter(btn, QEvent(QEvent.Leave))
        assert len(seen) >= 8, "hover 进出应各自重渲染一次"


# ---------------------------------------------------------------------------
# ⑤ 浮窗 Acrylic（不设材质 / 失败回落）
# ---------------------------------------------------------------------------
class TestChatWindowGlass:
    def _make_window(self, dark=False):
        from gui.widgets.chat_window import ChatWindow
        return ChatWindow(_Ctx(dark=dark, history=[{"role": "user", "content": "hi"}]))

    def test_unsupported_env_sets_no_material(self, qapp, monkeypatch):
        applied = []
        monkeypatch.setattr(glass, "is_supported", lambda: False)
        monkeypatch.setattr(glass, "safe_apply",
                            lambda hwnd, kind, *, dark: (applied.append((hwnd, kind, dark)), True)[1])
        monkeypatch.setattr(glass, "remove", lambda hwnd: True)
        w = self._make_window()
        w.show()
        qapp.processEvents()
        assert applied == [], "不支持环境不得执行 DWM 材质调用"
        assert w._glass_applied is False
        w.close()
        w.deleteLater()

    def test_supported_but_failing_falls_back(self, qapp, monkeypatch):
        removed = []
        monkeypatch.setattr(glass, "is_supported", lambda: True)
        monkeypatch.setattr(glass, "safe_apply", lambda hwnd, kind, *, dark: False)
        monkeypatch.setattr(glass, "remove", lambda hwnd: (removed.append(hwnd), True)[1])
        w = self._make_window()
        w.show()
        qapp.processEvents()
        assert w._glass_applied is False
        assert removed, "材质应用失败须 remove 回落原观感"
        w.close()
        w.deleteLater()

    def test_disabled_flag_only_removes(self, qapp, monkeypatch):
        applied = []
        removed = []
        monkeypatch.setattr(glass, "is_supported", lambda: True)
        monkeypatch.setattr(glass, "safe_apply",
                            lambda hwnd, kind, *, dark: (applied.append(kind), True)[1])
        monkeypatch.setattr(glass, "remove", lambda hwnd: (removed.append(hwnd), True)[1])
        from gui.widgets.chat_window import ChatWindow
        ctx = _Ctx(history=[])
        ctx.config = type("C", (), {"glass_popups_enabled": False})()
        w = ChatWindow(ctx)
        w.show()
        qapp.processEvents()
        assert applied == [], "开关关闭时不得应用材质"
        assert removed, "开关关闭须 remove"
        w.close()
        w.deleteLater()

    def test_theme_change_reapplies_with_dark(self, qapp, monkeypatch):
        seen = []
        monkeypatch.setattr(glass, "is_supported", lambda: True)
        monkeypatch.setattr(glass, "safe_apply",
                            lambda hwnd, kind, *, dark: (seen.append(dark), True)[1])
        monkeypatch.setattr(glass, "remove", lambda hwnd: True)
        w = self._make_window(dark=True)
        w.show()
        qapp.processEvents()
        assert seen == [True], "应随深浅联动传入 dark=True"
        w._on_theme_changed("ui_night")
        assert seen == [True, True], "换肤后须重设 immersive dark"
        w.close()
        w.deleteLater()

    def test_window_keeps_translucent_attribute(self):
        # 协调口径：不改为不透明（否则圆角/留白露底色）；材质与不透明主容器并存
        w = self._make_window()
        assert w.testAttribute(Qt.WA_TranslucentBackground)
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------------
# ⑥ 发送链路回归
# ---------------------------------------------------------------------------
class TestSendChainRegression:
    @pytest.mark.parametrize("level", ["standard", "off"])
    def test_message_count_stable_across_levels(self, qapp, level):
        from gui.widgets.chat_panel import ChatPanelWidget
        svc = MagicMock()
        motion.configure(level)
        p = ChatPanelWidget(_Ctx(chat_service=svc))
        qapp.processEvents()
        p.input_edit.setPlainText("回归测试消息")
        p._on_send()
        qapp.processEvents()
        assert _count_bubbles(p) == 1, "用户气泡计数不因动画档位变化"
        assert svc.send_message.call_count == 1, "发送链路恰好调用一次"


# ---------------------------------------------------------------------------
# ⑦ 非模态浮层淡入 / 淡出（M-4）
# ---------------------------------------------------------------------------
class TestPopupFade:
    def test_fade_in_out_and_delayed_hide(self, panel, qapp):
        popup = panel._cmd_popup
        assert panel._popup_open(popup) is False
        panel._fade_show_popup(popup)
        assert popup.isVisible() is True
        assert panel._popup_open(popup) is True
        panel._fade_hide_popup(popup)
        # 淡出进行中：逻辑上已关闭（事件过滤器不再命中），但窗口尚未真正隐藏
        assert panel._popup_open(popup) is False
        _settle(qapp)
        assert popup.isVisible() is False, "淡出结束后应真正隐藏"

    def test_off_level_direct_show_hide(self, panel, monkeypatch):
        monkeypatch.setattr(motion, "system_animations_enabled", lambda: True)
        motion.configure("off")
        popup = panel._mention_popup
        panel._fade_show_popup(popup)
        assert popup.isVisible() is True
        assert panel._popup_opacity(popup) == 1.0, "off 档直显即终态（全不透明）"
        panel._fade_hide_popup(popup)
        assert popup.isVisible() is False, "off 档直隐"
        assert panel._popup_opacity(popup) == 1.0

    def test_reshow_during_fade_out_cancels_hide(self, panel, qapp):
        popup = panel._cmd_popup
        panel._fade_show_popup(popup)
        assert popup.isVisible() is True
        panel._fade_hide_popup(popup)      # 开始淡出
        panel._fade_show_popup(popup)      # 淡出未结束又要求显示
        _settle(qapp)
        assert popup.isVisible() is True, "重新显示应取消挂起的延迟隐藏"

    def test_hide_when_already_hidden_is_noop(self, panel):
        popup = panel._cmd_popup
        panel._fade_hide_popup(popup)   # 未显示 → 不崩、不建动画
        assert popup.isVisible() is False


# ---------------------------------------------------------------------------
# ⑧ 模态 exec() 对话框只淡入（不做淡出 / 不延迟关闭）
# ---------------------------------------------------------------------------
class TestModalFadeInOnly:
    def test_modal_fade_in_passes_through_return_value(self, panel, monkeypatch):
        from gui.qt_compat import QDialog
        calls = []
        real_fade = motion.fade

        def spy(widget, **k):
            calls.append(k)
            return real_fade(widget, **k)

        monkeypatch.setattr(motion, "fade", spy)
        dlg = QDialog(panel)
        monkeypatch.setattr(dlg, "exec_", lambda: 42, raising=False)
        assert panel._exec_modal_fade(dlg) == 42, "必须透传 exec() 返回值"
        assert calls, "模态对话框应请求淡入"
        assert calls[0].get("to", 1.0) == 1.0
        assert "on_finished" not in calls[0], "模态只淡入，不得挂延迟关闭回调（无淡出）"

    def test_modal_fade_in_off_level_still_execs(self, panel, monkeypatch):
        from gui.qt_compat import QDialog
        motion.configure("off")
        dlg = QDialog(panel)
        monkeypatch.setattr(dlg, "exec_", lambda: 7, raising=False)
        assert panel._exec_modal_fade(dlg) == 7, "off 档应直接原样 exec()"

    def test_window_modal_fade_in_passthrough(self, qapp, monkeypatch):
        from gui.qt_compat import QDialog
        w = TestChatWindowGlass()._make_window()
        dlg = QDialog(w)
        monkeypatch.setattr(dlg, "exec_", lambda: 3, raising=False)
        calls = []
        real_fade = motion.fade
        monkeypatch.setattr(motion, "fade", lambda widget, **k: (calls.append(k), real_fade(widget, **k))[1])
        assert w._exec_modal_fade(dlg) == 3
        assert calls and "on_finished" not in calls[0]
        w.close()
        w.deleteLater()
