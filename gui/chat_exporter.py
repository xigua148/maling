"""聊天记录导出 —— Markdown / TXT / JSON 三种格式。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("maid_coder.gui")

ROLE_LABELS = {"user": "用户", "assistant": "助手"}


class ChatExporter:
    """把一组 (role, content, timestamp) 消息导出为不同格式。"""

    @staticmethod
    def export(messages: List, fmt: str, file_path: str, session_name: str = "聊天记录") -> bool:
        """导出消息列表到文件。messages 为 [(role, content, timestamp), ...]。"""
        try:
            path = Path(file_path)
            if fmt == "markdown":
                path.write_text(ChatExporter._to_markdown(messages, session_name), encoding="utf-8")
            elif fmt == "txt":
                path.write_text(ChatExporter._to_txt(messages, session_name), encoding="utf-8")
            elif fmt == "json":
                path.write_text(ChatExporter._to_json(messages, session_name), encoding="utf-8")
            else:
                return False
            return True
        except OSError as exc:
            logger.warning("导出聊天记录失败: %s", exc)
            return False

    @staticmethod
    def _to_markdown(messages: List, session_name: str) -> str:
        lines = [f"# {session_name}", "", f"> 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for role, content, _ts in messages:
            label = ROLE_LABELS.get(role, role)
            lines.append(f"## {label}")
            lines.append("")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _to_txt(messages: List, session_name: str) -> str:
        lines = [f"===== {session_name} =====",
                 f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        for role, content, ts in messages:
            label = ROLE_LABELS.get(role, role)
            time_str = ""
            if ts:
                try:
                    time_str = datetime.fromisoformat(str(ts)).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    time_str = str(ts)
            lines.append(f"[{time_str}] {label}:")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _to_json(messages: List, session_name: str) -> str:
        data = {
            "name": session_name,
            "exported_at": datetime.now().isoformat(),
            "messages": [
                {"role": role, "content": content, "timestamp": str(ts) if ts else None}
                for role, content, ts in messages
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
