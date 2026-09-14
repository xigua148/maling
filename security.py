from __future__ import annotations

import difflib
import re
from typing import List, Tuple
from math import log2

from core import DANGEROUS_COMMANDS, SAFE_COMMAND_WHITELIST, SENSITIVE_PATTERNS


# ---------------------------------------------------------------------------
def build_tools_definition() -> List[dict]:
    """构建工具调用定义（供 function calling / tool use 使用）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": "call_harness",
                "description": "执行实际操作：生成文档、运行程序、文件操作等",
                "parameters": {
                    "type": "object",
                    "properties": {"task": {"type": "string", "description": "具体任务描述"}},
                    "required": ["task"],
                },
            },
        }
    ]

# ---------------------------------------------------------------------------
def _text_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------------------
# 命令安全检查
# ---------------------------------------------------------------------------
def is_command_safe(cmd: str, mode: str = "blacklist") -> Tuple[bool, str]:
    """检查命令/任务描述是否安全。返回 (是否安全, 原因)。

    mode 取值：
    - "blacklist"：命中 DANGEROUS_COMMANDS 任一模式即拒绝；
    - "whitelist"：仅放行以 SAFE_COMMAND_WHITELIST 中任一前缀开头的命令；
    - "off"：完全放行（仅在用户显式选择时使用）。

    注意：此函数对自然语言描述的拦截是「尽力」——AI 生成的任务描述可能
    以自然语言包裹危险意图，这里只做最显眼的字符串匹配；真正的执行安全
    仍取决于 harness 程序本身。
    """
    if not cmd or not cmd.strip():
        return True, ""
    text = cmd.strip()
    mode = (mode or "blacklist").lower()

    if mode == "off":
        return True, ""

    if mode == "whitelist":
        lowered = text.lower()
        head = lowered.split(None, 1)[0] if lowered else ""
        # 允许的前缀：whitelist 列表 + 绝对路径命令
        allowed = any(
            head == p.lower() or head.endswith("/" + p.lower())
            for p in SAFE_COMMAND_WHITELIST
        )
        if not allowed:
            return False, f"白名单模式：'{head or text}' 不在允许列表中"
        # 即使通过白名单，仍要拒绝白名单中夹带黑名单特征的命令
        for pattern in DANGEROUS_COMMANDS:
            if re.search(pattern, text):
                return False, f"白名单模式：命令包含黑名单特征 '{pattern}'"
        return True, ""

    # blacklist（默认）
    for pattern in DANGEROUS_COMMANDS:
        if re.search(pattern, text):
            return False, f"黑名单模式：命令命中危险模式 '{pattern}'"
    return True, ""


# ---------------------------------------------------------------------------
# 工具调用定义
# 敏感信息检测
# ---------------------------------------------------------------------------
def _is_teaching_context(text: str, start: int, end: int) -> bool:
    """检查匹配位置是否处于教学/示例上下文。"""
    window = text[max(0, start - 30):min(len(text), end + 30)]
    teaching_markers = ["示例", "example", "格式", "format", "比如", "例如", "像这样", "如下", "template", "样例"]
    return any(m in window.lower() for m in teaching_markers)


def _entropy(s: str) -> float:
    """计算字符串香农熵，低熵（如重复字符）可能是示例值。"""
    if not s:
        return 0.0
    from math import log2
    prob = [s.count(c) / len(s) for c in set(s)]
    return -sum(p * log2(p) for p in prob)


def scan_sensitive_info(text: str) -> List[Tuple[str, str]]:
    """扫描文本中的敏感信息，返回 (类型, 匹配内容) 列表。"""
    found = []
    for pattern, label in SENSITIVE_PATTERNS:
        for match in re.finditer(pattern, text):
            # 取完整匹配或捕获组
            content = match.group(0)
            # 排除教学上下文
            if _is_teaching_context(text, match.start(), match.end()):
                continue
            # 对疑似 secret 做熵值校验（示例值通常熵较低或模式明显）
            secret_part = match.group(2) if match.lastindex and match.lastindex >= 2 else content
            if len(secret_part) >= 20 and _entropy(secret_part) < 2.5:
                continue
            # 截断显示
            display = content[:50] + "..." if len(content) > 50 else content
            found.append((label, display))
    return found


# ---------------------------------------------------------------------------
# 插件系统
# ---------------------------------------------------------------------------
