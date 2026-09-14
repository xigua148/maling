"""对话书签命令 — 复用 SnippetManager JSON 持久化模式。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR
from managers import sanitize_session_name


class BookmarkManager:
    """对话书签管理器 — 复用 SnippetManager JSON 持久化模式。
    记录历史索引位置，支持跳转、列出、删除。
    """

    def __init__(self, filepath: str = "bookmarks.json"):
        self.filepath = filepath
        self._data: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add(self, name: str, session_id: str, history_index: int, context: str = "") -> str:
        """添加书签。"""
        safe_name = sanitize_session_name(name)
        self._data[safe_name] = {
            "session_id": session_id,
            "history_index": history_index,
            "context": context[:200],  # 限制上下文长度
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        return G(f"✅ 已添加书签: {safe_name}")

    def list(self) -> str:
        """列出所有书签。"""
        if not self._data:
            return "🔖 暂无书签。"
        lines = ["🔖 书签列表:"]
        for name, info in self._data.items():
            session_id = info.get("session_id", "?")
            idx = info.get("history_index", 0)
            created = info.get("created_at", "?")[:16]
            context = info.get("context", "")
            preview = f" — {context[:40]}..." if context else ""
            lines.append(f"  • {name} (会话: {session_id}, 索引: {idx}){preview}")
            lines.append(f"    创建于: {created}")
        return "\n".join(lines)

    def get(self, name: str) -> Optional[dict]:
        """获取书签详情。"""
        safe_name = sanitize_session_name(name)
        return self._data.get(safe_name)

    def delete(self, name: str) -> str:
        """删除书签。"""
        safe_name = sanitize_session_name(name)
        if safe_name in self._data:
            del self._data[safe_name]
            self._save()
            return G(f"✅ 已删除书签: {safe_name}")
        return f"书签不存在: {name}"


def register_bookmark_commands(router: CommandRouter) -> None:
    """注册对话书签命令。"""

    @router.command(
        "bookmark",
        description="对话书签管理（add/list/goto/delete）",
        usage="/bookmark add <name>|list|goto <name>|delete <name>",
        category="会话管理",
    )
    def cmd_bookmark(ctx: CommandContext) -> None:
        mgr = BookmarkManager()
        sub = ctx.args[0] if ctx.args else ""

        if sub == "add" and len(ctx.args) >= 2:
            name = ctx.args[1]
            # 提取当前位置上下文（最近一条 assistant 消息的前 60 字符）
            context = ""
            for m in reversed(ctx.session.history):
                if m.get("role") == "assistant" and m.get("content"):
                    context = m["content"][:60].replace("\n", " ")
                    break
            history_index = len(ctx.session.history)
            print(mgr.add(name, ctx.session.session_id, history_index, context))

        elif sub == "list":
            print(mgr.list())

        elif sub == "goto" and len(ctx.args) >= 2:
            name = ctx.args[1]
            info = mgr.get(name)
            if not info:
                print(R(f"❌ 书签不存在: {name}"))
                return
            target_idx = info.get("history_index", 0)
            if target_idx > len(ctx.session.history):
                print(Y(f"⚠️ 书签索引 {target_idx} 超出当前历史长度 {len(ctx.session.history)}，将跳转到末尾。"))
                target_idx = len(ctx.session.history)
            # 截断历史到书签位置
            ctx.session.history = ctx.session.history[:target_idx]
            ctx.session.turn_count = max(0, ctx.session.turn_count - (len(ctx.session.history) - target_idx))
            print(G(f"✅ 已跳转到书签 '{name}' (历史索引: {target_idx})"))
            if info.get("context"):
                print(GR(f"   上下文: {info['context'][:80]}..."))

        elif sub == "delete" and len(ctx.args) >= 2:
            print(mgr.delete(ctx.args[1]))

        else:
            print("用法: /bookmark add <name>|list|goto <name>|delete <name>")
