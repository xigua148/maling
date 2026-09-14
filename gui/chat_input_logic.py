"""chat_input_logic.py —— 输入处理纯逻辑（无 Qt 依赖）。

v1.4.8: 从 chat_panel.py 提取的输入相关纯函数。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def should_trigger_command_popup(text: str) -> bool:
    """判断输入文本是否应触发指令补全弹窗。

    条件：首行以 / 开头且尚未输入参数（无空格）。
    """
    first_line = text.split("\n", 1)[0].strip()
    return first_line.startswith("/") and " " not in first_line


def compute_input_height(
    doc_height: float,
    line_spacing: int,
    min_height: int = 48,
    max_lines: int = 6,
    padding: int = 16,
) -> int:
    """计算输入框应设高度。

    Args:
        doc_height: 文档内容高度（px）
        line_spacing: 字体行距（px）
        min_height: 最小高度
        max_lines: 最大行数
        padding: 内边距余量

    Returns:
        应设置的固定高度（px）
    """
    max_h = max(min_height, line_spacing * max_lines + padding)
    doc_h = int(doc_height + 14)
    return max(min_height, min(doc_h, max_h))


def format_tool_label(tool_name: str) -> str:
    """将工具内部名映射为授权弹窗的显示标签。"""
    mapping: Dict[str, str] = {
        "write_file": "写入 / 覆写文件",
        "git_commit": "Git 提交",
        "run_python": "沙箱执行 Python",
        "file_delete": "删除文件",
        "file_move": "移动文件",
        "file_append": "追加写入文件",
        "clipboard_write": "写入剪贴板",
    }
    return mapping.get(tool_name, tool_name)


def format_agent_event_status(event_type: str, data: dict) -> Optional[str]:
    """将 Agent 轨迹事件格式化为状态栏文字。

    Returns:
        状态栏文字，非已知事件返回 None。
    """
    if event_type == "llm_start":
        step = data.get("step", 1)
        return f"🤖 Agent 第 {step} 步：正在思考…"
    if event_type == "tool_call":
        name = data.get("name", "")
        args = data.get("arguments", {})
        summary = str(args)[:60]
        return f"🔧 调用工具 {name}({summary})…"
    if event_type == "tool_done":
        name = data.get("name", "")
        ok = data.get("ok", False)
        mark = "✅" if ok else "❌"
        return f"{mark} 工具 {name} 执行完成"
    if event_type == "tool_denied":
        name = data.get("name", "")
        return f"⛔ 工具 {name} 已被你拒绝授权"
    if event_type == "max_steps":
        return "⚠️ 达到最大步骤上限，提前收尾"
    return None


def is_agent_final_event(event_type: str) -> bool:
    """判断事件是否为 Agent 收尾事件。"""
    return event_type in ("final", "max_steps")


def filter_commands_by_prefix(
    commands: List[Dict[str, str]],
    prefix: str,
) -> List[Dict[str, str]]:
    """按前缀过滤指令列表（用于补全搜索）。

    Args:
        commands: [{"name": "/xxx", "description": "...", "template": "/xxx "}, ...]
        prefix: 用户输入的 / 前缀

    Returns:
        匹配的指令列表
    """
    prefix_lower = prefix.lower()
    return [
        cmd for cmd in commands
        if cmd.get("name", "").lower().startswith(prefix_lower)
    ]
