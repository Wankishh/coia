"""Chat conversation models (Mongo `conversations` collection)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


# Assistant message kinds that count toward unread (excludes kind="handoff" notes).
_UNREAD_KINDS = frozenset({"run_result", "handoff_report"})


class ChatAttachment(BaseModel):
    """File uploaded into a chat session (workspace `_chats/{chat_id}/`)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    path: str  # workspace-relative path under _chats/{chat_id}/
    size: int = 0
    content_type: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=_utcnow)


class ChatMessage(BaseModel):
    role: ChatRole
    content: str
    timestamp: datetime = Field(default_factory=_utcnow)
    tool_calls: Optional[list[dict[str, Any]]] = None
    # Optional fields for harness run results posted into the "Agent runs" session.
    html: Optional[str] = None
    execution_id: Optional[str] = None
    kind: Optional[str] = None  # e.g. "run_result"
    usage: Optional[dict[str, Any]] = None  # optional token metadata


def message_counts_as_unread(
    message: Union[ChatMessage, dict[str, Any]],
    last_read_at: Optional[datetime],
) -> bool:
    """Return True if an assistant deliverable is unread relative to last_read_at."""
    if isinstance(message, ChatMessage):
        role = message.role.value if isinstance(message.role, ChatRole) else str(message.role)
        kind = message.kind
        ts = message.timestamp
    else:
        role = message.get("role")
        kind = message.get("kind")
        ts = message.get("timestamp")
    if role != ChatRole.assistant.value and role != ChatRole.assistant:
        return False
    if kind not in _UNREAD_KINDS and kind not in (None, ""):
        return False
    if last_read_at is None:
        return True
    if ts is None:
        return False
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if isinstance(ts, datetime) and ts.tzinfo is None and last_read_at.tzinfo is not None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts > last_read_at


def count_unread_messages(
    messages: list[Union[ChatMessage, dict[str, Any]]],
    last_read_at: Optional[datetime],
) -> int:
    """Count unread assistant replies / run results / handoff reports."""
    return sum(1 for m in messages if message_counts_as_unread(m, last_read_at))


class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    title: str = "Chat"
    messages: list[ChatMessage] = Field(default_factory=list)
    rolling_summary: str = ""
    attachments: list[ChatAttachment] = Field(default_factory=list)
    last_read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ConversationSummary(BaseModel):
    id: str
    agent_id: str
    title: str
    updated_at: datetime
    message_count: int = 0
    has_html: bool = False
    unread_count: int = 0
    unread_runs: int = 0  # compat alias of unread_count

    @model_validator(mode="after")
    def _sync_unread_alias(self) -> "ConversationSummary":
        count = self.unread_count or self.unread_runs
        if self.unread_count != count or self.unread_runs != count:
            object.__setattr__(self, "unread_count", count)
            object.__setattr__(self, "unread_runs", count)
        return self


class ConversationCreateResponse(BaseModel):
    id: str


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class SendMessageResponse(BaseModel):
    messages: list[ChatMessage]
    assistant_message: ChatMessage
