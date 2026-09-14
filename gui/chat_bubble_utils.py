"""chat_bubble_utils.py —— 气泡渲染辅助函数。

v1.4.8: 从 chat_panel.py 提取的纯渲染/格式化函数，不依赖 Qt self. 属性。
供 chat_panel.py 和测试共同使用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ── 气泡样式常量 ──────────────────────────────────────────────
HIGHLIGHT_STYLE = "QWidget { border: 2px solid #FFD700; border-radius: 12px; }"
CLEAR_STYLE = ""
ERROR_STYLE = "QWidget { border: 2px solid #FF4444; border-radius: 12px; }"
FAVORITE_STYLE = "QWidget { border: 2px solid #FF69B4; border-radius: 12px; }"

# 气泡最大宽度（对齐现代 AI 聊天观感）
DEFAULT_MAX_BUBBLE_WIDTH = 880


def format_timestamp(dt: Optional[datetime] = None, fmt: str = "%H:%M") -> str:
    """格式化时间戳用于气泡显示。

    Args:
        dt: 日期时间对象，None 表示当前时间
        fmt: 显示格式
    """
    if dt is None:
        dt = datetime.now()
    return dt.strftime(fmt)


def format_role_label(role: str) -> str:
    """将角色 ID 转为显示标签。"""
    mapping = {
        "user": "我",
        "assistant": "AI",
        "system": "系统",
    }
    return mapping.get(role, role)


def is_consecutive_role(prev_role: Optional[str], current_role: str) -> bool:
    """判断是否与上一条消息同角色（用于合并间距）。"""
    return prev_role is not None and prev_role == current_role


def truncate_text(text: str, max_len: int = 60) -> str:
    """截断文本用于预览/摘要显示。"""
    one_line = text.replace("\n", " ")
    if len(one_line) > max_len:
        return one_line[:max_len] + "..."
    return one_line


def build_bubble_metadata(
    attachments: Optional[List[dict]] = None,
    model: Optional[str] = None,
    tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
) -> Dict:
    """构造气泡附带的 metadata dict。

    仅包含非空字段，避免空值污染存储。
    """
    meta: Dict = {}
    if attachments:
        meta["attachments"] = attachments
    if model:
        meta["model"] = model
    if tokens is not None and tokens > 0:
        meta["tokens"] = tokens
    if latency_ms is not None and latency_ms > 0:
        meta["latency_ms"] = latency_ms
    return meta


def collect_messages_from_layout(layout, bubble_class) -> List[Tuple[str, str, str]]:
    """从 Qt layout 中收集所有气泡的消息数据。

    Args:
        layout: QLayout 实例
        bubble_class: MessageBubble 类（用于 isinstance 检查）

    Returns:
        [(role, text, timestamp), ...]
    """
    messages = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        widget = item.widget()
        if isinstance(widget, bubble_class):
            messages.append((widget.role, widget.get_text(), widget.timestamp))
    return messages


def compute_insert_index(layout, bubble_class) -> int:
    """计算新气泡应插入的 layout 索引。

    通常在最后一个气泡之后、底部 spacer 之前。
    """
    idx = layout.count() - 2
    if idx < 0:
        idx = layout.count() - 1
    return max(0, idx)


def format_message_count(count: int) -> str:
    """格式化消息计数为可读文本。"""
    if count == 0:
        return "暂无消息"
    if count == 1:
        return "1 条消息"
    return f"{count} 条消息"


def estimate_bubble_height(text: str, chars_per_line: int = 40, line_height: int = 24) -> int:
    """估算气泡高度（用于虚拟滚动/预加载计算）。

    粗略计算：文本行数 × 行高 + 固定边距。
    """
    if not text:
        return line_height + 32  # 空气泡最小高度
    lines = len(text) // chars_per_line + text.count("\n") + 1
    return lines * line_height + 32
