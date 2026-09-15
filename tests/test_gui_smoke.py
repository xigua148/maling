"""tests/test_gui_smoke.py —— GUI 冒烟测试（需 pytest-qt）。

目的：验证核心 Widget 可实例化、不崩溃。
环境要求：pip install pytest-qt PySide6
无 pytest-qt 时全部 skip，不影响 CI 单元测试。

v1.4.8 新增。
"""
import pytest

# 条件导入：无 GUI 环境时全部跳过
try:
    from gui.qt_compat import QApplication, QWidget
    HAS_QT = True
except ImportError:
    HAS_QT = False

try:
    import pytestqt  # noqa: F401
    HAS_PYTESTQT = True
except ImportError:
    HAS_PYTESTQT = False

pytestmark = pytest.mark.skipif(
    not (HAS_QT and HAS_PYTESTQT),
    reason="需要 PySide6 + pytest-qt 才能运行 GUI 测试",
)


@pytest.fixture
def app(qapp):
    """确保 QApplication 存在（pytest-qt 的 qapp fixture 包装）。"""
    return qapp


@pytest.mark.skipif(not (HAS_QT and HAS_PYTESTQT), reason="需要 GUI 环境")
class TestWidgetInstantiation:
    """核心 Widget 冒烟测试：可实例化、不崩溃。"""

    def test_message_bubble_user(self, qtbot):
        """用户气泡可创建。"""
        from gui.widgets.message_bubble import MessageBubble
        bubble = MessageBubble("user", "测试消息")
        qtbot.addWidget(bubble)
        assert bubble.get_text() == "测试消息"
        assert bubble.role == "user"

    def test_message_bubble_assistant(self, qtbot):
        """AI 气泡可创建。"""
        from gui.widgets.message_bubble import MessageBubble
        bubble = MessageBubble("assistant", "你好~")
        qtbot.addWidget(bubble)
        assert bubble.role == "assistant"

    def test_message_bubble_update_text(self, qtbot):
        """气泡文本更新。"""
        from gui.widgets.message_bubble import MessageBubble
        bubble = MessageBubble("assistant", "初始")
        qtbot.addWidget(bubble)
        bubble.update_text("更新后")
        assert bubble.get_text() == "更新后"

    def test_message_bubble_update_text_recomputes_height(self, qtbot):
        """v2.1(UI-Fix-0915): update_text「原地 setHtml」快路径必须重算高度。

        内容 browser 是 Expanding×Fixed + setFixedHeight；快路径若不显式调
        ``_adjust_height``，高度会冻结在首个短分片的值 → 长流式回复被裁剪。
        此处断言长文本更新后的内容 browser 高度**严格大于**短文本更新后的高度。
        （纯 ASCII 长文本：确定性、不依赖 CJK 字形 / 墙钟。）
        """
        from gui.qt_compat import QApplication, QWidget, Qt
        from gui.widgets.message_bubble import MessageBubble

        bubble = MessageBubble("assistant", "short")
        qtbot.addWidget(bubble)
        bubble.setAttribute(Qt.WA_DontShowOnScreen, True)
        bubble.resize(360, 400)
        bubble.show()
        qtbot.wait(1)
        QApplication.processEvents()

        def content_browser():
            frame = bubble.findChild(QWidget, "bubbleFrame")
            assert frame is not None and frame.layout() is not None
            widget = frame.layout().itemAt(0).widget()
            assert widget is not None
            return widget

        bubble.update_text("short")
        qtbot.wait(1)
        QApplication.processEvents()
        short_browser = content_browser()
        short_h = short_browser.height()

        long_text = "This is a long streaming reply used to verify the bubble grows. " * 120
        bubble.update_text(long_text)
        qtbot.wait(1)
        QApplication.processEvents()
        long_browser = content_browser()
        # 快路径原地 setHtml，不换 widget —— 应为同一对象
        assert long_browser is short_browser
        assert long_browser.document().size().height() > 0
        assert long_browser.height() > short_h, (
            "update_text 快路径未重算高度：short=%d long=%d"
            % (short_h, long_browser.height())
        )

    def test_thinking_indicator(self, qtbot):
        """思考指示器可创建。"""
        from gui.widgets.thinking_indicator import ThinkingIndicator
        indicator = ThinkingIndicator()
        qtbot.addWidget(indicator)
        indicator.start()
        indicator.stop()

    def test_chat_helpers_import(self):
        """chat_helpers 模块可导入（不依赖 Qt 实例）。"""
        from gui.chat_helpers import build_matcher, truncate_preview
        m = build_matcher("test")
        assert m("this is a test") is True
        assert truncate_preview("hello") == "hello"

    def test_chat_bubble_utils_import(self):
        """chat_bubble_utils 模块可导入。"""
        from gui.chat_bubble_utils import HIGHLIGHT_STYLE, format_role_label
        assert "FFD700" in HIGHLIGHT_STYLE
        assert format_role_label("user") == "我"

    def test_chat_input_logic_import(self):
        """chat_input_logic 模块可导入。"""
        from gui.chat_input_logic import should_trigger_command_popup
        assert should_trigger_command_popup("/help") is True

    def test_chat_stream_state_import(self):
        """chat_stream_state 模块可导入。"""
        from gui.chat_stream_state import StreamState
        s = StreamState()
        s.start()
        s.append_chunk("test")
        assert s.buffer == "test"
