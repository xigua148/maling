"""user_messages.py —— 用户友好消息转换。

将工具返回的 JSON 错误、API 异常等转为自然语言提示，
避免用户看到原始 JSON 或技术细节。

v1.4.8 新增。
"""
from __future__ import annotations

import json
from typing import Optional


def format_tool_error(tool_name: str, result_json: str) -> str:
    """将工具执行的 JSON 错误转为可读文本。

    模型会将此文本作为 tool message 回读，因此保持简洁、信息完整。
    """
    try:
        parsed = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return f"工具 {tool_name} 执行失败，返回内容无法解析。"

    status = parsed.get("status", "error")
    message = parsed.get("message", "")
    reason = parsed.get("reason", "")

    if status == "denied":
        return f"🚫 操作被拒绝：{reason or message or '用户未授权'}。请尊重用户意愿，改用其他方案。"

    if status == "error":
        # 常见错误模式匹配 → 给出更友好的提示
        if "不存在" in message:
            return f"❌ 找不到目标：{message}。请检查路径是否正确。"
        if "无权限" in message or "Permission" in message:
            return f"❌ 权限不足：{message}。请尝试其他路径或请求用户授权。"
        if "超时" in message or "timeout" in message.lower():
            return f"⏰ 操作超时：{message}。请稍后重试或简化操作。"
        if "需要" in message and ("库" in message or "pip" in message):
            return f"📦 缺少依赖：{message}"
        return f"⚠️ 工具 {tool_name} 执行出错：{message}"

    # 其他 status 原样返回
    return message or f"工具 {tool_name} 返回未知状态: {status}"


def format_api_error(error: Exception, context: str = "") -> str:
    """将 API 异常转为用户友好的提示。"""
    err_str = str(error)

    # 常见网络错误
    if "Connection" in err_str or "connect" in err_str.lower():
        return (
            "🌐 网络连接失败，请检查：\n"
            "1. 网络是否正常\n"
            "2. API URL 是否正确\n"
            "3. 是否需要代理/VPN"
        )

    if "timeout" in err_str.lower() or "Timeout" in err_str:
        return "⏰ 请求超时，服务器响应太慢。请稍后重试或检查 API 服务状态。"

    if "401" in err_str or "Unauthorized" in err_str:
        return "🔑 API Key 无效或已过期，请在设置中重新填写。"

    if "403" in err_str or "Forbidden" in err_str:
        return "🚫 访问被拒绝，可能 API Key 权限不足或账户已欠费。"

    if "404" in err_str or "Not Found" in err_str:
        return "❌ API 地址找不到，请检查 URL 和模型名是否正确。"

    if "429" in err_str or "rate" in err_str.lower():
        return "⚠️ 请求太频繁，已触发限流。请等待几秒后重试。"

    if "500" in err_str or "502" in err_str or "503" in err_str:
        return "🔧 服务器内部错误，请稍后重试。如持续出现请联系 API 提供商。"

    # 通用错误
    prefix = f"{context}：\n" if context else ""
    return f"{prefix}⚠️ 请求失败：{err_str}\n请检查 API Key / 网络 / 厂商 URL"


def format_agent_summary(status: str, goal: str, steps: list, summary: dict) -> str:
    """将 Agent 任务执行结果汇总为用户友好的文本。"""
    if status == "done":
        text = f"✅ 任务完成！\n\n🎯 目标：{goal}\n📊 共 {len(steps)} 个步骤，全部通过。"
        blocker = summary.get("current_blocker")
        if blocker:
            text += f"\n\n💡 备注：{blocker}"
        return text

    if status == "paused":
        text = f"⏸️ 任务已暂停\n\n🎯 目标：{goal}\n📊 已完成 {len(steps)} 个步骤。"
        blocker = summary.get("current_blocker")
        if blocker:
            text += f"\n\n🚧 卡点：{blocker}"
        text += "\n\n你可以继续执行或调整目标。"
        return text

    # failed
    text = f"⚠️ 任务未完成\n\n🎯 目标：{goal}\n📊 尝试了 {len(steps)} 个步骤。"
    blocker = summary.get("current_blocker")
    if blocker:
        text += f"\n\n🚧 失败原因：{blocker}"
    failed_steps = [s for s in steps if isinstance(s, dict) and s.get("status") == "failed"]
    if failed_steps:
        text += f"\n\n失败步骤：{len(failed_steps)} 个"
    text += "\n\n💡 建议：简化任务目标或拆分为多个小任务。"
    return text


def truncate_for_display(text: str, max_len: int = 500) -> str:
    """截断过长文本用于显示，保留头尾。"""
    if len(text) <= max_len:
        return text
    head_len = max_len * 2 // 3
    tail_len = max_len // 3
    head = text[:head_len]
    tail = text[-tail_len:]
    return f"{head}\n\n... (已省略 {len(text) - max_len} 字符) ...\n\n{tail}"
