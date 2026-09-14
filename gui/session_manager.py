"""SessionManager —— 聊天会话的本地持久化管理。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from gui.models import ChatSession

logger = logging.getLogger("maid_coder.gui")

DEFAULT_SESSIONS_DIR = Path.home() / ".maid_coder" / "sessions"
ACTIVE_SESSION_FILE = "active_session.json"

# v1.7(F10a/D-V17-06): 群聊会话模型常量（R-J③ 成员 ≤3）
GROUP_SESSION_TYPE = "group"
GROUP_MAX_MEMBERS = 3


def is_group_session(session) -> bool:
    """v1.7(F10a): 判断显示会话是否为群聊会话（旧会话无 type = 单聊，零影响）。"""
    meta = getattr(session, "metadata", None) or {}
    return meta.get("type") == GROUP_SESSION_TYPE


class SessionManager:
    """管理聊天会话的创建、加载、保存、删除。"""

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, ChatSession] = {}
        self._active_session_id: Optional[str] = None
        self._load_all()

    # ------------------------------------------------------------------
    # 基础 CRUD
    # ------------------------------------------------------------------
    def create_session(self, name: str = "新会话") -> ChatSession:
        """创建新会话并保存。"""
        session = ChatSession(name=name)
        self._sessions[session.id] = session
        self._active_session_id = session.id
        self.save_session(session)
        logger.info("创建新会话: %s (%s)", name, session.id)
        return session

    def create_group_session(self, name: str, member_ids: List[str],
                             no_at_policy: str = "rotate") -> ChatSession:
        """v1.7(F10a/D-V17-06): 创建群聊会话（metadata 扩展，旧会话零影响）。

        - members ≤3（R-J③，超出截断；<2 拒绝）；
        - turn_order 初始与 members 相同（发言后该角色移到队尾）；
        - no_at_policy: rotate（默认轮转第一位）| silent（全员沉默等待 @，Q-C1）；
        - v1.8 收尾：旧的 chatter 主动插话记账字段已退役（F10 自由发言调度取代）；
          旧会话残留的 metadata.chatter 仅作为历史数据保留，不再读取。
        """
        members = [m for m in (member_ids or []) if m][:GROUP_MAX_MEMBERS]
        if len(members) < 2:
            raise ValueError("群聊至少需要 2 名成员")
        session = ChatSession(name=name or "群聊")
        session.metadata = {
            "type": GROUP_SESSION_TYPE,
            "members": members,
            "turn_order": list(members),
            "no_at_policy": no_at_policy if no_at_policy in ("rotate", "silent") else "rotate",
        }
        self._sessions[session.id] = session
        self._active_session_id = session.id
        self.save_session(session)
        logger.info("创建群聊会话: %s (%s) 成员=%s", name, session.id, members)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除会话及本地文件。"""
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        file_path = self._session_file_path(session_id)
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError as exc:
            logger.warning("删除会话文件失败: %s", exc)
        if self._active_session_id == session_id:
            self._active_session_id = next(iter(self._sessions), None)
            self._save_active()
        logger.info("删除会话: %s", session_id)
        return True

    def rename_session(self, session_id: str, new_name: str) -> bool:
        """重命名会话。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.name = new_name
        session.updated_at = __import__("datetime").datetime.now()
        self.save_session(session)
        return True

    def clear_session(self, session_id: str) -> bool:
        """清空会话消息。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.clear()
        self.save_session(session)
        return True

    def all_sessions(self) -> List[ChatSession]:
        """返回所有会话列表（按更新时间倒序）。"""
        return sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)

    # ------------------------------------------------------------------
    # 活跃会话
    # ------------------------------------------------------------------
    @property
    def active_session(self) -> Optional[ChatSession]:
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    def set_active(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._active_session_id = session_id
        self._save_active()
        return True

    def ensure_active(self) -> ChatSession:
        """确保存在活跃会话，没有则自动创建。"""
        session = self.active_session
        if session is not None:
            return session
        if self._sessions:
            first_id = next(iter(self._sessions))
            self.set_active(first_id)
            return self._sessions[first_id]
        return self.create_session("默认会话")

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save_session(self, session: ChatSession) -> None:
        """将会话保存到本地 JSON。"""
        file_path = self._session_file_path(session.id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("保存会话失败: %s", exc)

    def save_active(self) -> None:
        """保存当前活跃会话。"""
        session = self.active_session
        if session is not None:
            self.save_session(session)
            self._save_active()

    def _session_file_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.json"

    def _load_all(self) -> None:
        """加载目录下所有会话文件。"""
        if not self.sessions_dir.exists():
            return
        for file_path in self.sessions_dir.glob("*.json"):
            if file_path.name == ACTIVE_SESSION_FILE:
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                session = ChatSession.from_dict(data)
                self._sessions[session.id] = session
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("加载会话文件失败 %s: %s", file_path.name, exc)

        # 恢复活跃会话
        active_file = self.sessions_dir / ACTIVE_SESSION_FILE
        if active_file.exists():
            try:
                with open(active_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                active_id = data.get("active_session_id")
                if active_id in self._sessions:
                    self._active_session_id = active_id
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("加载活跃会话记录失败: %s", exc)

        # 首次启动且没有任何会话时自动创建默认会话
        if not self._sessions:
            self.create_session("默认会话")

    def _save_active(self) -> None:
        active_file = self.sessions_dir / ACTIVE_SESSION_FILE
        try:
            with open(active_file, "w", encoding="utf-8") as f:
                json.dump({"active_session_id": self._active_session_id}, f)
        except OSError as exc:
            logger.warning("保存活跃会话记录失败: %s", exc)
