"""GUI 数据模型 —— ChatMessage / ChatSession 定义。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class ChatMessage:
    """单条聊天消息。"""

    role: str                                   # "user" | "assistant" | "system"
    content: str                                # 消息正文
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "complete"                    # "pending" | "streaming" | "complete" | "error" | "cancelled"
    model: Optional[str] = None                 # 使用的模型名称
    tokens: Optional[int] = None                # 消耗 token 数
    metadata: dict = field(default_factory=dict)  # 扩展字段（引用消息ID、附件路径等）

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "model": self.model,
            "tokens": self.tokens,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatMessage":
        """从字典反序列化。"""
        ts = data.get("timestamp")
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            role=data.get("role", ""),
            content=data.get("content", ""),
            timestamp=datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.now(),
            status=data.get("status", "complete"),
            model=data.get("model"),
            tokens=data.get("tokens"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ChatSession:
    """聊天会话：包含一组消息及会话元信息。"""

    name: str = "新会话"
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    messages: List[ChatMessage] = field(default_factory=list)
    system_prompt: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def add_message(self, role: str, content: str, **kwargs) -> ChatMessage:
        """添加消息并更新会话时间。"""
        msg = ChatMessage(role=role, content=content, **kwargs)
        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def last_message(self) -> Optional[ChatMessage]:
        """获取最后一条消息。"""
        return self.messages[-1] if self.messages else None

    def clear(self) -> None:
        """清空所有消息。"""
        self.messages.clear()
        self.updated_at = datetime.now()

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "messages": [m.to_dict() for m in self.messages],
            "system_prompt": self.system_prompt,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        """从字典反序列化。"""
        msgs = [ChatMessage.from_dict(m) for m in data.get("messages", [])]
        created = data.get("created_at")
        updated = data.get("updated_at")
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "新会话"),
            created_at=datetime.fromisoformat(created) if isinstance(created, str) else datetime.now(),
            updated_at=datetime.fromisoformat(updated) if isinstance(updated, str) else datetime.now(),
            messages=msgs,
            system_prompt=data.get("system_prompt"),
            metadata=data.get("metadata", {}),
        )
