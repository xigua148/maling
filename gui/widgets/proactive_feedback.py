"""gui/widgets/proactive_feedback.py —— v1.6 P0-3 反馈三键动作行（D-V16-05）。

主动气泡后的一行轻量反馈入口：「💗 说到心坎」「🙈 先不提这个」「💬 想聊聊」。
- **独立动作行 widget**：不触碰 MessageBubble 内部、不入会话存档（R-D）；
- **hover 展开式**（Q-B3）：默认收起为一个小 ✨ 图标，鼠标进入浮现三键；
  构造参数 persistent=True 可切常驻（Q-B3 备选形态，降级预案）；
- 点击后整行收敛为「已反馈 ✓」并禁用（防重复提交）；
- 只发 feedback_picked(str)（"heart"/"mute"/"chat"），策略写回由面板回调
  memory_mgr.record_followup_feedback 完成——本组件零业务耦合。
"""
from __future__ import annotations

from typing import Callable, Optional

from gui.qt_compat import QWidget, QHBoxLayout, QLabel, QPushButton, QSize, Qt
from gui.utils import theme_color
from gui import icons

logger = __import__("logging").getLogger("maid_coder.gui")

# feedback 值 → 按钮文案
_FEEDBACK_BTNS = [
    ("heart", "💗 说到心坎"),
    ("mute", "🙈 先不提这个"),
    ("chat", "💬 想聊聊"),
]


class ProactiveFeedbackBar(QWidget):
    """主动消息反馈三键动作行（hover 展开式，Q-B3）。"""

    def __init__(self, subject: str, scene: str,
                 on_picked: Optional[Callable[[str, str, str], None]] = None,
                 parent: Optional[QWidget] = None,
                 persistent: bool = False):
        """subject/scene 仅用于回调透传（面板据此写回 memory 策略）。

        on_picked(subject, scene, kind) —— 点击任一键后回调；None 时只发信号。
        persistent=False（默认，Q-B3）：hover 展开；True：常驻三键。
        """
        super().__init__(parent)
        self.subject = subject or ""
        self.scene = scene or ""
        self._on_picked = on_picked
        self._answered = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 2)
        lay.setSpacing(6)

        # 收起态：小 ✨ 入口（persistent 模式不创建）
        self._spark = None
        if not persistent:
            self._spark = QPushButton()
            self._spark.setObjectName("feedbackSpark")
            self._spark.setCursor(Qt.PointingHandCursor)
            self._spark.setFixedSize(24, 20)
            self._spark.setToolTip("刚才这句话感觉怎么样？")
            # v2.1(D-V21-06): 纯图标按钮 —— 图标字体可用给矢量图标，
            # 不可用回落原 emoji 文本（不空白、不崩）。
            spark_icon = None
            try:
                if icons.available():
                    spark_icon = icons.icon("auto_awesome", 14, None)
            except Exception:
                spark_icon = None
            if spark_icon is not None and not spark_icon.isNull():
                self._spark.setIcon(spark_icon)
                self._spark.setIconSize(QSize(14, 14))
            else:
                self._spark.setText("✨")
            self._spark.clicked.connect(self.expand)
            lay.addWidget(self._spark)

        # 展开态：三键 + 引导小字（persistent 模式直接可见）
        self._row = QWidget(self)
        row_lay = QHBoxLayout(self._row)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)
        self._buttons = []
        for kind, label in _FEEDBACK_BTNS:
            btn = QPushButton(label)
            btn.setObjectName("feedbackBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=kind: self._pick(k))
            row_lay.addWidget(btn)
            self._buttons.append(btn)
        self._hint = QLabel("刚才这句感觉如何？")
        self._hint.setObjectName("feedbackHint")
        row_lay.insertWidget(0, self._hint)
        lay.addWidget(self._row, 1)
        if not persistent:
            self._row.setVisible(False)  # 初始收起

        self._apply_style()

    # -- 展开控制 --
    def expand(self) -> None:
        """展开三键（hover/点击 ✨ 触发；persistent 模式空操作）。"""
        if self._spark is not None:
            self._spark.setVisible(False)
        self._row.setVisible(True)

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        try:
            if not self._answered and self._spark is not None:
                self.expand()
        except Exception:
            pass
        super().enterEvent(event)

    # -- 反馈提交 --
    def _pick(self, kind: str) -> None:
        if self._answered:
            return
        self._answered = True
        # 收敛为已反馈态（防重复提交）
        try:
            self._row.setVisible(True)
            if self._spark is not None:
                self._spark.setVisible(False)
            label = dict(_FEEDBACK_BTNS).get(kind, "")
            self._hint.setText("已反馈，谢谢你 ♥")
            self._hint.show()
            for btn in self._buttons:
                btn.setEnabled(False)
                btn.setVisible(False)
            _ = label  # 文案收敛为统一致谢（简洁）
        except Exception:
            pass
        try:
            if self._on_picked is not None:
                self._on_picked(self.subject, self.scene, kind)
        except Exception as exc:
            logger.warning("feedback 回调失败: %s", exc)

    # -- 主题 --
    def _apply_style(self) -> None:
        accent = theme_color(self.app_ctx_color(), "accent", "#FF6B9D")
        secondary = theme_color(self.app_ctx_color(), "text_secondary", "#8A8A8A")
        border = theme_color(self.app_ctx_color(), "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QPushButton#feedbackBtn {{ background: transparent; color: {accent};"
            f" border: 1px solid {border}; border-radius: 8px; font-size: 11px;"
            f" padding: 2px 8px; }}"
            f"QPushButton#feedbackBtn:hover {{ background: {border}; }}"
            f"QPushButton#feedbackSpark {{ background: transparent; color: {secondary};"
            f" border: none; font-size: 12px; }}"
            f"QLabel#feedbackHint {{ color: {secondary}; font-size: 11px;"
            f" background: transparent; }}"
        )

    def app_ctx_color(self):
        """取 app_ctx（挂载方 set_app_ctx 注入；缺省用自身 parent 链）。"""
        ctx = getattr(self, "_app_ctx", None)
        if ctx is not None:
            return ctx
        return self.parent()

    def set_app_ctx(self, app_ctx) -> None:
        """挂载方注入 app_ctx（theme_color 取色用），注入后刷新配色。"""
        self._app_ctx = app_ctx
        self._apply_style()
