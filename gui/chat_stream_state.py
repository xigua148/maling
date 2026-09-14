"""chat_stream_state.py —— 流式输出状态管理（无 Qt 依赖）。

v1.4.8: 从 chat_panel.py 提取的流式状态跟踪类。
chat_panel 持有实例，纯管数据；UI 渲染仍由 panel 负责。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StreamState:
    """流式输出的纯数据状态。

    用法：
        state = StreamState()
        state.start()
        state.append_chunk("hello ")
        state.append_chunk("world")
        assert state.buffer == "hello world"
        state.finish()
    """

    buffer: str = ""
    is_streaming: bool = False
    bubble_created: bool = False
    activity: Optional[str] = None
    agent_trace_active: bool = False
    _usage: dict = field(default_factory=dict)

    def start(self) -> None:
        """开始新一轮流式输出。"""
        self.buffer = ""
        self.is_streaming = True
        self.bubble_created = False
        self.activity = "thinking"
        self._usage = {}

    def append_chunk(self, chunk: str) -> str:
        """追加文本块，返回当前完整 buffer。"""
        self.buffer += chunk
        return self.buffer

    def mark_bubble_created(self) -> None:
        """标记流式气泡已创建。"""
        self.bubble_created = True
        self.activity = None

    def finish(self, usage: Optional[dict] = None) -> dict:
        """流式结束，返回最终 usage 并重置状态。"""
        self._usage = dict(usage or {})
        self.is_streaming = False
        self.bubble_created = False
        self.activity = None
        return self._usage

    def cancel(self) -> None:
        """流式取消。"""
        self.is_streaming = False
        self.bubble_created = False
        self.activity = None

    def fail(self) -> None:
        """流式失败。"""
        self.is_streaming = False
        self.bubble_created = False
        self.activity = None

    @property
    def needs_new_bubble(self) -> bool:
        """是否需要创建新气泡（流式中但气泡尚未创建）。"""
        return self.is_streaming and not self.bubble_created

    def start_agent_trace(self) -> None:
        """开启 Agent 轨迹跟踪。"""
        self.agent_trace_active = True

    def end_agent_trace(self) -> None:
        """结束 Agent 轨迹跟踪。"""
        self.agent_trace_active = False

    @property
    def is_agent_tracing(self) -> bool:
        return self.agent_trace_active


def compute_stream_insert_index(layout_count: int) -> int:
    """计算流式气泡应插入的 layout 索引。

    与 chat_bubble_utils.compute_insert_index 逻辑一致，
    但语义上专用于流式场景。
    """
    idx = layout_count - 2
    if idx < 0:
        idx = layout_count - 1
    return max(0, idx)


def format_usage_summary(usage: dict) -> str:
    """格式化 usage dict 为简短摘要（日志/调试用）。"""
    if not usage:
        return "无用量数据"
    parts = []
    if "prompt_tokens" in usage:
        parts.append(f"输入 {usage['prompt_tokens']}")
    if "completion_tokens" in usage:
        parts.append(f"输出 {usage['completion_tokens']}")
    if "total_tokens" in usage:
        parts.append(f"合计 {usage['total_tokens']}")
    if usage.get("cancelled"):
        parts.append("已取消")
    return " | ".join(parts) if parts else "无用量数据"
