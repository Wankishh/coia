"""In-memory registry for in-flight chats and execution cancel flags."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ActiveChat:
    chat_id: str
    agent_id: str
    started_at: datetime = field(default_factory=_utcnow)
    title: Optional[str] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class ActivityRegistry:
    """
    Process-local activity for chat streams + best-effort cancel signals.

    Running executions are sourced from Mongo; this registry only tracks
    interactive chat turns and optional cancel flags for executions.
    """

    def __init__(self) -> None:
        self._chats: dict[str, ActiveChat] = {}
        self._exec_cancel: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def begin_chat(
        self,
        chat_id: str,
        agent_id: str,
        *,
        title: Optional[str] = None,
    ) -> ActiveChat:
        async with self._lock:
            entry = ActiveChat(chat_id=chat_id, agent_id=agent_id, title=title)
            self._chats[chat_id] = entry
            return entry

    async def end_chat(self, chat_id: str) -> None:
        async with self._lock:
            self._chats.pop(chat_id, None)

    async def request_chat_cancel(self, chat_id: str) -> bool:
        async with self._lock:
            entry = self._chats.get(chat_id)
            if entry is None:
                return False
            entry.cancel_event.set()
            return True

    def is_chat_cancelled(self, chat_id: str) -> bool:
        entry = self._chats.get(chat_id)
        return bool(entry and entry.cancel_event.is_set())

    async def list_chats(self) -> list[ActiveChat]:
        async with self._lock:
            return list(self._chats.values())

    def ensure_exec_cancel(self, execution_id: str) -> asyncio.Event:
        event = self._exec_cancel.get(execution_id)
        if event is None:
            event = asyncio.Event()
            self._exec_cancel[execution_id] = event
        return event

    def request_execution_cancel(self, execution_id: str) -> None:
        self.ensure_exec_cancel(execution_id).set()

    def is_execution_cancelled(self, execution_id: str) -> bool:
        event = self._exec_cancel.get(execution_id)
        return bool(event and event.is_set())

    def clear_execution_cancel(self, execution_id: str) -> None:
        self._exec_cancel.pop(execution_id, None)

    def chat_items(self) -> list[dict[str, Any]]:
        """Snapshot for /activity (sync; chat dict is tiny)."""
        items: list[dict[str, Any]] = []
        for entry in list(self._chats.values()):
            items.append(
                {
                    "id": f"chat:{entry.chat_id}",
                    "kind": "chat",
                    "agent_id": entry.agent_id,
                    "status": "cancelled" if entry.cancel_event.is_set() else "running",
                    "started_at": entry.started_at,
                    "title": entry.title,
                    "chat_id": entry.chat_id,
                }
            )
        return items
