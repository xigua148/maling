"""Agent 工具轨迹折叠面板（v1.1-B2）—— 把 Agent 执行过程的工具事件渲染成紧凑可折叠卡片。

事件类型（与 agent_engine / chat_service 约定一致）：
- llm_start   {step}
- tool_call   {step, name, arguments}
- tool_done   {name, ok, summary}
- tool_denied {name}
- final       {content, step}
- max_steps   {max_steps}

对外接口：
- add_event(event_type, data_dict)  追加一条轨迹并自动展开显示
- finish(status_hint="")            结束本次执行：收起明细（点标题可展开回看）
- reset()                           清空并隐藏
- update_theme()                    主题切换后刷新取色

设计约束：
- 纯展示组件，不持有业务状态；
- 颜色一律通过 theme_color(app_ctx, key, fallback) 取色（不允许裸硬编码）；
- 字体沿用应用默认（不额外加载字体）；
- 所有 UI 操作保守、可降级——异常时静默，绝不向上抛导致聊天面板崩溃。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, Qt,
    QSizePolicy, Signal, QScrollArea,
)
from gui.utils import theme_color


class _ClickableHeader(QFrame):
    """可点击的标题条：整行点击切换折叠/展开。"""

    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ToolTracePanel(QWidget):
    """Agent 工具轨迹折叠卡片。

    运行中实时追加明细并保持展开；finish() 后收起为一行摘要，
    点击标题可展开回看本次全部轨迹；下一次发送前 reset() 清空。
    """

    def __init__(self, app_context=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self._summary = {
            "steps": 0, "tools": 0, "ok": 0, "fail": 0, "denied": 0,
            "final": False, "max_steps": False,
        }
        self._row_labels = []
        self._finished = False
        self._expanded = True
        self._init_ui()
        self.hide()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _init_ui(self) -> None:
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 2)
        outer.setSpacing(0)

        self._card = QFrame()
        self._card.setObjectName("toolTraceCard")
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(10, 6, 10, 6)
        card_layout.setSpacing(4)

        self._header = _ClickableHeader()
        self._header.setCursor(Qt.PointingHandCursor)
        head_layout = QHBoxLayout(self._header)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(6)
        self._title_label = QLabel("🤖 Agent 执行过程")
        self._meta_label = QLabel("")
        self._meta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._arrow_label = QLabel("▾")
        head_layout.addWidget(self._title_label)
        head_layout.addStretch(1)
        head_layout.addWidget(self._meta_label)
        head_layout.addWidget(self._arrow_label)
        card_layout.addWidget(self._header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setFixedHeight(150)
        self._body_host = QWidget()
        self._body_layout = QVBoxLayout(self._body_host)
        self._body_layout.setContentsMargins(2, 2, 2, 2)
        self._body_layout.setSpacing(2)
        # 底部 stretch 保证新行从顶部排布
        self._body_layout.addStretch(1)
        self._scroll.setWidget(self._body_host)
        card_layout.addWidget(self._scroll)

        outer.addWidget(self._card)

        self._header.clicked.connect(self._on_header_clicked)
        self._apply_styles()

    def _color(self, key: str, fallback: str) -> str:
        """统一取色入口（fallback 色仅当主题缺失该键时使用）。"""
        return theme_color(self.app_ctx, key, fallback)

    def _apply_styles(self) -> None:
        bg_card = self._color("bg_card", "#FFFFFF")
        border = self._color("border", "#FFE4E1")
        radius = self._color("radius_md", "10px")
        title_color = self._color("primary_dark", "#FF6B9D")
        text_color = self._color("text", "#4A4A4A")
        meta_color = self._color("text_secondary", "#8A8A8A")
        self._card.setStyleSheet(
            "QFrame#toolTraceCard {"
            f" background: {bg_card}; border: 1px solid {border}; border-radius: {radius};"
            "}"
        )
        self._title_label.setStyleSheet(
            f"QLabel {{ color: {title_color}; font-size: 12px; font-weight: bold; }}"
        )
        self._meta_label.setStyleSheet(
            f"QLabel {{ color: {meta_color}; font-size: 11px; }}"
        )
        self._arrow_label.setStyleSheet(
            f"QLabel {{ color: {meta_color}; font-size: 12px; }}"
        )
        for label in self._row_labels:
            label.setStyleSheet(
                f"QLabel {{ color: {text_color}; font-size: 12px; }}"
            )

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def add_event(self, event_type: str, data: dict) -> Optional[str]:
        """追加一条轨迹；自动显示并展开面板。返回格式化后的行文本（无则不返回）。"""
        if not isinstance(data, dict):
            data = {}
        try:
            line = self._format_line(event_type, data)
        except Exception:
            line = ""
        self.show()
        self._set_expanded(True)  # 运行中保持展开，实时可见
        if line:
            self._append_row(line)
        self._meta_label.setText(self._summary_text())
        return line

    def finish(self, status_hint: str = "") -> None:
        """结束本次 Agent 执行：追加结束行（如缺）并收起明细。"""
        if not self._finished:
            has_terminal = self._summary.get("final") or self._summary.get("max_steps")
            if not has_terminal:
                hint = (status_hint or "执行结束").strip()
                if hint:
                    self._append_row(f"— {hint} —")
            self._finished = True
        self._set_expanded(False)
        self._meta_label.setText(self._summary_text())
        self.show()

    def has_events(self) -> bool:
        """是否已产生任何轨迹行（供调用方区分「跑过工具」与「空跑」）。"""
        return len(self._row_labels) > 0

    def reset(self) -> None:
        """清空并隐藏面板（新一次用户消息发送前调用）。"""
        while self._body_layout.count() > 1:
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._row_labels = []
        self._summary = {
            "steps": 0, "tools": 0, "ok": 0, "fail": 0, "denied": 0,
            "final": False, "max_steps": False,
        }
        self._finished = False
        self._set_expanded(True)
        self._meta_label.setText("")
        self.hide()

    def update_theme(self) -> None:
        """主题切换后刷新全部取色。"""
        self._apply_styles()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _format_line(self, event_type: str, data: dict) -> str:
        if event_type == "llm_start":
            step = int(data.get("step") or (self._summary["steps"] + 1))
            self._summary["steps"] = max(self._summary["steps"], step)
            return f"🤔 第 {step} 步 · 思考中…"
        if event_type == "tool_call":
            name = str(data.get("name") or "?")
            step = data.get("step", "")
            self._summary["tools"] += 1
            brief = self._brief(data.get("arguments"), 80)
            step_part = f"第 {step} 步 " if step else ""
            arg_part = f" · 参数: {brief}" if brief else ""
            # v1.2(C1): run_command 是进程级真实执行（非沙箱），轨迹上诚实标注，
            # 与 run_python（AST 沙箱）区分，避免用户误以为有代码隔离。
            tag = ""
            if name == "run_command":
                tag = " · 独立进程运行 · 非沙箱 · 受白名单约束"
            return f"🔧 {step_part}调用 {name}{tag}{arg_part}"
        if event_type == "tool_done":
            name = str(data.get("name") or "?")
            ok = bool(data.get("ok", False))
            if ok:
                self._summary["ok"] += 1
            else:
                self._summary["fail"] += 1
            summary = data.get("summary")
            extra = ""
            if summary is not None and str(summary).strip():
                extra = f" · {self._brief(summary, 80)}"
            return f"{'✅' if ok else '❌'} {name} {'完成' if ok else '失败'}{extra}"
        if event_type == "tool_denied":
            name = str(data.get("name") or "?")
            self._summary["denied"] += 1
            return f"⛔ {name} 已被拒绝授权"
        if event_type == "final":
            self._summary["final"] = True
            return "🏁 已生成最终回答"
        if event_type == "max_steps":
            self._summary["max_steps"] = True
            limit = data.get("max_steps", "")
            return f"⚠️ 达到步数上限（{limit} 轮）仍未收敛，已提前收尾"
        # v1.2(C3): managed 任务步骤事件（「女仆的工作进度」最小版）
        if event_type == "task_plan":
            n = data.get("steps", 0)
            goal = self._brief(data.get("goal"), 60)
            return f"🗂 任务规划完成 · 共 {n} 步：{goal}"
        if event_type == "step_start":
            idx = data.get("idx", "")
            total = data.get("total", "")
            goal = self._brief(data.get("goal"), 60)
            return f"🚧 第 {idx}/{total} 步进行中：{goal}"
        if event_type == "step_pass":
            idx = data.get("idx", "")
            note = self._brief(data.get("note"), 80)
            return f"✅ 第 {idx} 步通过{(' · ' + note) if note else ''}"
        if event_type == "step_fail":
            idx = data.get("idx", "")
            err = self._brief(data.get("error_summary"), 100)
            return f"❌ 第 {idx} 步失败：{err}"
        if event_type == "heal_try":
            idx = data.get("idx", "")
            attempt = data.get("attempt", "?")
            mx = data.get("max_retries", "?")
            return f"🩹 第 {idx} 步自愈中（第 {attempt}/{mx} 次）"
        if event_type == "stop_heal":
            idx = data.get("idx", "")
            reason = data.get("reason", "")
            return f"⏹ 第 {idx} 步自愈已停止{('：' + reason) if reason else ''}"
        if event_type == "task_paused":
            idx = data.get("idx", "")
            reason = data.get("reason", "")
            return f"⏸ 任务已暂停（断点 # {idx}）{('：' + reason) if reason else ''}"
        if event_type == "task_done":
            ok = bool(data.get("ok"))
            summary = data.get("summary") or {}
            if ok:
                self._summary["final"] = True
                return "🏁 任务全部完成，来向主人汇报啦"
            blocker = self._brief(summary.get("current_blocker"), 80)
            self._summary["final"] = True
            return f"⚠️ 任务未完成（有步骤失败），卡点: {blocker or '未知'}"
        # 未知事件类型：原样保留，便于后续扩展不丢信息
        return f"· {event_type}: {self._brief(data, 60)}"

    def _append_row(self, text: str) -> None:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        text_color = self._color("text", "#4A4A4A")
        label.setStyleSheet(f"QLabel {{ color: {text_color}; font-size: 12px; }}")
        self._row_labels.append(label)
        self._body_layout.insertWidget(self._body_layout.count() - 1, label)
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @staticmethod
    def _brief(value, limit: int = 80) -> str:
        """把参数/摘要压成单行短文本（尽量保留可读性）。"""
        if value is None:
            return ""
        if isinstance(value, str):
            text = value
        elif isinstance(value, (dict, list)):
            try:
                import json as _json
                text = _json.dumps(value, ensure_ascii=False)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        text = " ".join(text.split())
        if len(text) > limit:
            text = text[:limit] + "…"
        return text

    def _summary_text(self) -> str:
        parts = []
        if self._summary["steps"]:
            parts.append(f"{self._summary['steps']} 步")
        if self._summary["tools"]:
            parts.append(f"{self._summary['tools']} 次工具")
        parts.append(
            f"✅{self._summary['ok']} ❌{self._summary['fail']} ⛔{self._summary['denied']}"
        )
        return " · ".join(parts)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._scroll.setVisible(self._expanded)
        self._arrow_label.setText("▾" if self._expanded else "▸")

    def _on_header_clicked(self) -> None:
        """点标题切换折叠/展开；展开时滚到底部看最新。"""
        self._set_expanded(not self._expanded)
        if self._expanded:
            scrollbar = self._scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
