"""chat_helpers.py —— 聊天面板辅助工具函数。

v1.4.8: 从 chat_panel.py 提取的纯工具函数，不依赖 Qt self. 属性。
降低 chat_panel.py 耦合度，便于单独测试。
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple


def build_matcher(query: str, use_regex: bool = False) -> Optional[Callable[[str], bool]]:
    """根据查询构造匹配函数。

    Args:
        query: 搜索关键词或正则表达式
        use_regex: 是否使用正则模式

    Returns:
        匹配函数 (text -> bool)，正则语法错误或空查询时返回 None。
    """
    if not query:
        return None
    if use_regex:
        try:
            pattern = re.compile(query)
        except re.error:
            return None
        return lambda text: pattern.search(text) is not None
    lowered = query.lower()
    return lambda text: lowered in text.lower()


def highlight_style() -> str:
    """返回高亮气泡的 QSS 样式（金色边框）。"""
    return "QWidget { border: 2px solid #FFD700; border-radius: 12px; }"


def clear_highlight_style() -> str:
    """返回清除高亮的空样式。"""
    return ""


def truncate_preview(text: str, max_len: int = 60) -> str:
    """截断文本用于预览显示。"""
    preview = text.replace("\n", " ")
    if len(preview) > max_len:
        return preview[:max_len] + "..."
    return preview


def format_search_result(session_name: str, role: str, content: str) -> str:
    """格式化单条搜索结果为显示文本。"""
    preview = truncate_preview(content)
    return f"[{session_name}] {role}: {preview}"


def filter_messages_by_role(
    messages: List[Tuple[str, str, str]],
    roles: Optional[List[str]] = None,
) -> List[Tuple[str, str, str]]:
    """按角色过滤消息列表。

    Args:
        messages: (role, content, timestamp) 列表
        roles: 要保留的角色列表，None 表示全部
    """
    if roles is None:
        return list(messages)
    return [m for m in messages if m[0] in roles]


def format_export_preview(messages: List[Tuple[str, str, str]], max_msgs: int = 5) -> str:
    """生成导出预览文本。"""
    preview_lines = []
    for role, content, _ in messages[:max_msgs]:
        label = "我" if role == "user" else "AI"
        preview_lines.append(f"{label}: {truncate_preview(content, 40)}")
    if len(messages) > max_msgs:
        preview_lines.append(f"... (还有 {len(messages) - max_msgs} 条消息)")
    return "\n".join(preview_lines)


def parse_command_input(text: str) -> Tuple[Optional[str], str]:
    """解析用户输入，提取斜杠命令。

    Returns:
        (command_name, remaining_args) 或 (None, original_text)
    """
    text = text.strip()
    if not text.startswith("/"):
        return None, text
    parts = text.split(maxsplit=1)
    cmd = parts[0][1:]  # 去掉 /
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args


def estimate_reading_time(text: str, wpm: int = 200) -> int:
    """估算阅读时间（秒）。"""
    words = len(text.split())
    return max(1, int(words / wpm * 60))


def detect_code_language(code_block: str) -> str:
    """从代码块标记检测语言。"""
    if code_block.startswith("```"):
        first_line = code_block.split("\n", 1)[0]
        lang = first_line[3:].strip()
        if lang:
            return lang
    return "text"


def detect_export_format(selected_filter: str) -> str:
    """根据 QFileDialog 的 selected_filter 判断导出格式。

    Returns:
        'markdown' | 'txt' | 'json'
    """
    if selected_filter.startswith("Markdown"):
        return "markdown"
    if selected_filter.startswith("文本"):
        return "txt"
    return "json"


def normalize_session_name(name: Optional[str], default: str = "聊天记录") -> str:
    """规范化会话名称，空值回落到默认。"""
    if name and name.strip():
        return name.strip()
    return default
