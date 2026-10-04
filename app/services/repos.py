"""MongoDB repositories for agents, data sources, and executions."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.models.agent import AgentConfig, AgentCreate, AgentUpdate
from app.models.conversation import (
    ChatAttachment,
    ChatMessage,
    Conversation,
    ConversationSummary,
)
from app.models.execution import (
    ExecutionLog,
    ExecutionStatus,
    ToolCallRecord,
)
from app.models.source import (
    DataSource,
    DataSourceCreate,
    DataSourceUpdate,
    SourceConfig,
    merge_source_secrets,
    merge_sources_list,
)
from app.models.usage import UsageDayRow, UsageEvent, UsageSummary

_PATHLIKE_ID = re.compile(r"[/\\]|\.\.")


class AgentAlreadyRunningError(Exception):
    """Raised when insert hits the partial unique index for status=running."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"Agent {agent_id} already has a running execution")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceRepository:
    """Global Data Sources library (`data_sources` collection)."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["data_sources"]

    async def ensure_indexes(self) -> None:
        await self._col.create_index("id", unique=True)
        await self._col.create_index("title")

    async def create(self, payload: DataSourceCreate) -> DataSource:
        data = payload.model_dump(exclude_none=True)
        # Harden: always server-generate UUIDs; reject client path-like ids.
        requested = data.pop("id", None)
        if requested is not None:
            req = str(requested).strip()
            if _PATHLIKE_ID.search(req) or len(req) > 64 or not req:
                raise ValueError("Invalid source id — path-like or empty ids are not allowed")
            # Still ignore client ids for new sources (UUID only).
        source_id = str(uuid4())
        source = DataSource(id=source_id, **data)
        await self._col.insert_one(source.model_dump(mode="json"))
        return source

    async def get(self, source_id: str) -> Optional[DataSource]:
        doc = await self._col.find_one({"id": source_id}, {"_id": 0})
        return DataSource.model_validate(doc) if doc else None

    async def list_all(self) -> list[DataSource]:
        cursor = self._col.find({}, {"_id": 0}).sort("created_at", 1)
        return [DataSource.model_validate(doc) async for doc in cursor]

    async def get_many(self, source_ids: list[str]) -> list[DataSource]:
        """Return sources in the same order as `source_ids` (skip missing)."""
        if not source_ids:
            return []
        by_id: dict[str, DataSource] = {}
        async for doc in self._col.find({"id": {"$in": source_ids}}, {"_id": 0}):
            src = DataSource.model_validate(doc)
            by_id[src.id] = src
        return [by_id[sid] for sid in source_ids if sid in by_id]

    async def update(
        self, source_id: str, payload: DataSourceUpdate
    ) -> Optional[DataSource]:
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
        if not updates:
            return await self.get(source_id)

        existing = await self.get(source_id)
        if existing is None:
            return None

        next_type = updates.get("type", existing.type)
        next_config = updates.get("config", existing.config)
        if "config" in updates or "type" in updates:
            incoming = SourceConfig(
                id=existing.id,
                title=updates.get("title", existing.title),
                description=updates.get("description", existing.description),
                type=next_type,
                config=next_config or {},
            )
            existing_cfg = existing.as_source_config()
            merged = merge_source_secrets(existing_cfg, incoming)
            updates["type"] = merged.type
            updates["config"] = merged.config
            if "title" in updates:
                updates["title"] = merged.title
            if "description" in updates:
                updates["description"] = merged.description

        updates["updated_at"] = _utcnow()
        result = await self._col.find_one_and_update(
            {"id": source_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return DataSource.model_validate(result) if result else None

    async def delete(self, source_id: str) -> bool:
        result = await self._col.delete_one({"id": source_id})
        return result.deleted_count > 0


class AgentRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["agents"]

    async def create(self, payload: AgentCreate) -> AgentConfig:
        data = payload.model_dump()
        # Prefer source_ids; keep embedded sources only when source_ids empty (legacy).
        if data.get("source_ids"):
            data["sources"] = []
        agent = AgentConfig(**data)
        await self._col.insert_one(agent.model_dump(mode="json"))
        return agent

    async def get(self, agent_id: str) -> Optional[AgentConfig]:
        doc = await self._col.find_one({"id": agent_id})
        return AgentConfig.model_validate(doc) if doc else None

    async def list_all(self) -> list[AgentConfig]:
        cursor = self._col.find({}, {"_id": 0}).sort("created_at", 1)
        return [AgentConfig.model_validate(doc) async for doc in cursor]

    async def update(self, agent_id: str, payload: AgentUpdate) -> Optional[AgentConfig]:
        updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
        if not updates:
            return await self.get(agent_id)

        if "source_ids" in updates:
            # New UI path: attach by id; clear embedded blobs to avoid dual truth.
            updates["sources"] = []
        elif "sources" in updates:
            existing = await self.get(agent_id)
            if existing is None:
                return None
            incoming = [SourceConfig.model_validate(s) for s in updates["sources"]]
            merged = merge_sources_list(existing.sources, incoming)
            updates["sources"] = [s.model_dump(mode="json") for s in merged]

        updates["updated_at"] = _utcnow()
        result = await self._col.find_one_and_update(
            {"id": agent_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return AgentConfig.model_validate(result) if result else None

    async def delete(self, agent_id: str) -> bool:
        result = await self._col.delete_one({"id": agent_id})
        return result.deleted_count > 0

    async def set_avatar(
        self,
        agent_id: str,
        *,
        avatar_path: Optional[str] = None,
        avatar_preset: Optional[str] = None,
        clear_path: bool = False,
        clear_preset: bool = False,
    ) -> Optional[AgentConfig]:
        """Update avatar fields without going through AgentUpdate validation."""
        updates: dict[str, Any] = {"updated_at": _utcnow()}
        if clear_path:
            updates["avatar_path"] = None
        elif avatar_path is not None:
            updates["avatar_path"] = avatar_path
        if clear_preset:
            updates["avatar_preset"] = None
        elif avatar_preset is not None:
            updates["avatar_preset"] = avatar_preset
        result = await self._col.find_one_and_update(
            {"id": agent_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return AgentConfig.model_validate(result) if result else None

    async def list_with_cron(self) -> list[AgentConfig]:
        """Agents with a cron schedule that are not paused (missing paused = active)."""
        cursor = self._col.find(
            {
                "cron_schedule": {"$nin": [None, ""]},
                "paused": {"$ne": True},
            },
            {"_id": 0},
        )
        return [AgentConfig.model_validate(doc) async for doc in cursor]


class ConversationRepository:
    """Chat conversations (`conversations` collection). Separate from ExecutionLog."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["conversations"]

    async def ensure_indexes(self) -> None:
        await self._col.create_index("id", unique=True)
        await self._col.create_index([("agent_id", 1), ("updated_at", -1)])
        await self._col.create_index([("agent_id", 1), ("title", 1)])
        await self._col.create_index([("updated_at", -1)])

    async def create(self, agent_id: str, *, title: str = "Chat") -> Conversation:
        conversation = Conversation(agent_id=agent_id, title=title)
        await self._col.insert_one(conversation.model_dump(mode="json"))
        return conversation

    async def get_or_create_runs_session(
        self,
        agent_id: str,
        *,
        title: str = "Agent runs",
    ) -> Conversation:
        """Find the per-agent runs session by title, or create it."""
        doc = await self._col.find_one(
            {"agent_id": agent_id, "title": title},
            {"_id": 0},
        )
        if doc:
            return Conversation.model_validate(doc)
        return await self.create(agent_id, title=title)

    async def get(self, chat_id: str) -> Optional[Conversation]:
        doc = await self._col.find_one({"id": chat_id}, {"_id": 0})
        return Conversation.model_validate(doc) if doc else None

    async def list_for_agent(self, agent_id: str) -> list[ConversationSummary]:
        return await self._list_summaries({"agent_id": agent_id})

    async def list_all(self, *, limit: int = 100) -> list[ConversationSummary]:
        return await self._list_summaries({}, limit=limit)

    async def _list_summaries(
        self,
        match: dict[str, Any],
        *,
        limit: Optional[int] = None,
    ) -> list[ConversationSummary]:
        pipeline: list[dict[str, Any]] = [{"$match": match}] if match else []
        pipeline.extend(
            [
                {"$sort": {"updated_at": -1}},
                {
                    "$project": {
                        "_id": 0,
                        "id": 1,
                        "agent_id": 1,
                        "title": 1,
                        "updated_at": 1,
                        "message_count": {
                            "$size": {"$ifNull": ["$messages", []]}
                        },
                        "has_html": {
                            "$gt": [
                                {
                                    "$size": {
                                        "$filter": {
                                            "input": {"$ifNull": ["$messages", []]},
                                            "as": "m",
                                            "cond": {
                                                "$and": [
                                                    {"$ne": ["$$m.html", None]},
                                                    {"$ne": ["$$m.html", ""]},
                                                ]
                                            },
                                        }
                                    }
                                },
                                0,
                            ]
                        },
                        # Count assistant deliverables newer than last_read_at.
                        # Includes run_result / handoff_report and normal replies
                        # (kind null/absent); excludes user/system/kind=handoff.
                        "unread_count": {
                            "$size": {
                                "$filter": {
                                    "input": {"$ifNull": ["$messages", []]},
                                    "as": "m",
                                    "cond": {
                                        "$and": [
                                            {"$eq": ["$$m.role", "assistant"]},
                                            {
                                                "$or": [
                                                    {
                                                        "$in": [
                                                            "$$m.kind",
                                                            [
                                                                "run_result",
                                                                "handoff_report",
                                                            ],
                                                        ]
                                                    },
                                                    {
                                                        "$eq": [
                                                            {
                                                                "$ifNull": [
                                                                    "$$m.kind",
                                                                    None,
                                                                ]
                                                            },
                                                            None,
                                                        ]
                                                    },
                                                ]
                                            },
                                            {
                                                "$or": [
                                                    {
                                                        "$eq": [
                                                            {
                                                                "$ifNull": [
                                                                    "$last_read_at",
                                                                    None,
                                                                ]
                                                            },
                                                            None,
                                                        ]
                                                    },
                                                    {
                                                        "$gt": [
                                                            "$$m.timestamp",
                                                            "$last_read_at",
                                                        ]
                                                    },
                                                ]
                                            },
                                        ]
                                    },
                                }
                            }
                        },
                    }
                },
                {"$addFields": {"unread_runs": "$unread_count"}},
            ]
        )
        if limit is not None:
            pipeline.append({"$limit": limit})
        cursor = self._col.aggregate(pipeline)
        return [ConversationSummary.model_validate(doc) async for doc in cursor]

    async def mark_read(self, chat_id: str) -> Optional[Conversation]:
        result = await self._col.find_one_and_update(
            {"id": chat_id},
            {"$set": {"last_read_at": _utcnow()}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return Conversation.model_validate(result) if result else None

    async def add_attachment(
        self, chat_id: str, attachment: ChatAttachment
    ) -> Optional[Conversation]:
        result = await self._col.find_one_and_update(
            {"id": chat_id},
            {
                "$push": {"attachments": attachment.model_dump(mode="json")},
                "$set": {"updated_at": _utcnow()},
            },
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return Conversation.model_validate(result) if result else None

    async def update_title(self, chat_id: str, title: str) -> Optional[Conversation]:
        result = await self._col.find_one_and_update(
            {"id": chat_id},
            {"$set": {"title": title, "updated_at": _utcnow()}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return Conversation.model_validate(result) if result else None

    async def set_rolling_summary(
        self,
        chat_id: str,
        summary: str,
        through_count: int,
    ) -> None:
        await self._col.update_one(
            {"id": chat_id},
            {
                "$set": {
                    "rolling_summary": summary,
                    "summary_through_count": through_count,
                    "updated_at": _utcnow(),
                }
            },
        )

    async def delete(self, chat_id: str) -> bool:
        result = await self._col.delete_one({"id": chat_id})
        return result.deleted_count > 0

    async def append_messages(
        self,
        chat_id: str,
        messages: list[ChatMessage],
        *,
        title: Optional[str] = None,
    ) -> Optional[Conversation]:
        if not messages and title is None:
            return await self.get(chat_id)

        update: dict[str, Any] = {"updated_at": _utcnow()}
        ops: dict[str, Any] = {"$set": update}
        if messages:
            ops["$push"] = {
                "messages": {
                    "$each": [m.model_dump(mode="json") for m in messages],
                }
            }
        if title is not None:
            update["title"] = title

        result = await self._col.find_one_and_update(
            {"id": chat_id},
            ops,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        return Conversation.model_validate(result) if result else None


class ExecutionRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["executions"]

    async def ensure_indexes(self) -> None:
        await self._col.create_index("id", unique=True)
        await self._col.create_index([("agent_id", 1), ("start_time", -1)])
        await self._col.create_index([("agent_id", 1), ("status", 1)])
        # At most one running execution per agent (claim-by-insert).
        await self._col.create_index(
            [("agent_id", 1)],
            unique=True,
            partialFilterExpression={"status": ExecutionStatus.running.value},
            name="uniq_agent_id_running",
        )

    async def create(self, log: ExecutionLog) -> ExecutionLog:
        """Insert execution; raises AgentAlreadyRunningError on concurrent claim."""
        try:
            await self._col.insert_one(log.model_dump(mode="json"))
        except DuplicateKeyError as exc:
            # Prefer the partial unique running index; id collisions are extremely unlikely.
            raise AgentAlreadyRunningError(log.agent_id) from exc
        return log

    async def get(self, execution_id: str) -> Optional[ExecutionLog]:
        doc = await self._col.find_one({"id": execution_id}, {"_id": 0})
        return ExecutionLog.model_validate(doc) if doc else None

    async def list_for_agent(self, agent_id: str, limit: int = 50) -> list[ExecutionLog]:
        cursor = (
            self._col.find({"agent_id": agent_id}, {"_id": 0})
            .sort("start_time", -1)
            .limit(limit)
        )
        return [ExecutionLog.model_validate(doc) async for doc in cursor]

    async def list_recent_finished(
        self,
        agent_id: str,
        *,
        limit: int = 3,
        exclude_id: Optional[str] = None,
    ) -> list[ExecutionLog]:
        query: dict[str, Any] = {
            "agent_id": agent_id,
            "status": {
                "$in": [
                    ExecutionStatus.completed.value,
                    ExecutionStatus.failed.value,
                    ExecutionStatus.cancelled.value,
                ]
            },
        }
        if exclude_id:
            query["id"] = {"$ne": exclude_id}
        cursor = (
            self._col.find(query, {"_id": 0})
            .sort("start_time", -1)
            .limit(limit)
        )
        rows = [ExecutionLog.model_validate(doc) async for doc in cursor]
        rows.reverse()
        return rows

    async def has_running(self, agent_id: str) -> bool:
        doc = await self._col.find_one(
            {"agent_id": agent_id, "status": ExecutionStatus.running.value},
            {"_id": 1},
        )
        return doc is not None

    async def list_running(self, *, limit: int = 100) -> list[ExecutionLog]:
        cursor = (
            self._col.find({"status": ExecutionStatus.running.value}, {"_id": 0})
            .sort("start_time", -1)
            .limit(limit)
        )
        return [ExecutionLog.model_validate(doc) async for doc in cursor]

    async def list_running_older_than(self, cutoff: datetime) -> list[ExecutionLog]:
        cursor = self._col.find(
            {
                "status": ExecutionStatus.running.value,
                "start_time": {"$lte": cutoff},
            },
            {"_id": 0},
        ).sort("start_time", 1)
        return [ExecutionLog.model_validate(doc) async for doc in cursor]

    async def get_latest_failed(self, agent_id: str) -> Optional[ExecutionLog]:
        doc = await self._col.find_one(
            {"agent_id": agent_id, "status": ExecutionStatus.failed.value},
            {"_id": 0},
            sort=[("end_time", -1), ("start_time", -1)],
        )
        return ExecutionLog.model_validate(doc) if doc else None

    async def fail_all_running(
        self,
        error_message: str = "Interrupted by restart",
    ) -> int:
        """Mark every running execution as failed. Returns modified count."""
        result = await self._col.update_many(
            {"status": ExecutionStatus.running.value},
            {
                "$set": {
                    "status": ExecutionStatus.failed.value,
                    "error_message": error_message,
                    "end_time": _utcnow(),
                }
            },
        )
        return int(result.modified_count)

    async def fail_if_running(
        self,
        execution_id: str,
        error_message: str,
    ) -> bool:
        result = await self._col.update_one(
            {"id": execution_id, "status": ExecutionStatus.running.value},
            {
                "$set": {
                    "status": ExecutionStatus.failed.value,
                    "error_message": error_message,
                    "end_time": _utcnow(),
                }
            },
        )
        return int(result.modified_count) == 1

    async def append_step(self, execution_id: str, step: ToolCallRecord) -> None:
        await self._col.update_one(
            {"id": execution_id},
            {"$push": {"tool_calls": step.model_dump(mode="json")}},
        )

    async def append_output_text(self, execution_id: str, text: str) -> None:
        await self._col.update_one(
            {"id": execution_id},
            {"$set": {"output_text": text}},
        )

    async def complete(
        self,
        execution_id: str,
        *,
        output_text: str,
        output_html: Optional[str] = None,
        error_message: Optional[str] = None,
        status: ExecutionStatus = ExecutionStatus.completed,
    ) -> bool:
        """Finalize a running execution. Returns False if it was already terminal."""
        update: dict[str, Any] = {
            "status": status.value,
            "output_text": output_text,
            "end_time": _utcnow(),
        }
        if output_html is not None:
            update["output_html"] = output_html
        if error_message is not None:
            update["error_message"] = error_message
        result = await self._col.update_one(
            {"id": execution_id, "status": ExecutionStatus.running.value},
            {"$set": update},
        )
        return int(result.modified_count) > 0

    async def fail(self, execution_id: str, error_message: str) -> None:
        """Mark failed without clearing any partial output_text already stored."""
        await self._col.update_one(
            {"id": execution_id, "status": ExecutionStatus.running.value},
            {
                "$set": {
                    "status": ExecutionStatus.failed.value,
                    "error_message": error_message,
                    "end_time": _utcnow(),
                }
            },
        )

    async def cancel(
        self,
        execution_id: str,
        error_message: str = "Cancelled",
    ) -> bool:
        """Mark a running execution as cancelled. Returns True if a doc was updated."""
        result = await self._col.update_one(
            {"id": execution_id, "status": ExecutionStatus.running.value},
            {
                "$set": {
                    "status": ExecutionStatus.cancelled.value,
                    "error_message": error_message,
                    "end_time": _utcnow(),
                }
            },
        )
        return int(result.modified_count) > 0


class UsageRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["usage_events"]

    async def ensure_indexes(self) -> None:
        await self._col.create_index("id", unique=True)
        await self._col.create_index([("day", -1), ("agent_id", 1)])

    async def record(
        self,
        *,
        agent_id: str,
        provider: str = "",
        model: str = "",
        kind: str = "chat",
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> UsageEvent:
        day = _utcnow().strftime("%Y-%m-%d")
        event = UsageEvent(
            agent_id=agent_id,
            day=day,
            provider=provider or "",
            model=model or "",
            kind=kind,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        await self._col.insert_one(event.model_dump(mode="json"))
        return event

    async def summarize(self, *, days: int = 7) -> UsageSummary:
        days = max(1, min(int(days), 90))
        start = (_utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        pipeline = [
            {"$match": {"day": {"$gte": start}}},
            {
                "$group": {
                    "_id": {
                        "day": "$day",
                        "agent_id": "$agent_id",
                        "provider": "$provider",
                        "model": "$model",
                    },
                    "request_count": {"$sum": "$request_count"},
                    "input_tokens": {
                        "$sum": {"$ifNull": ["$input_tokens", 0]}
                    },
                    "output_tokens": {
                        "$sum": {"$ifNull": ["$output_tokens", 0]}
                    },
                }
            },
            {"$sort": {"_id.day": -1, "_id.agent_id": 1}},
        ]
        rows: list[UsageDayRow] = []
        totals = {
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        async for doc in self._col.aggregate(pipeline):
            key = doc["_id"]
            row = UsageDayRow(
                day=key["day"],
                agent_id=key["agent_id"],
                provider=key.get("provider") or "",
                model=key.get("model") or "",
                request_count=int(doc.get("request_count") or 0),
                input_tokens=int(doc.get("input_tokens") or 0),
                output_tokens=int(doc.get("output_tokens") or 0),
            )
            rows.append(row)
            totals["request_count"] += row.request_count
            totals["input_tokens"] += row.input_tokens
            totals["output_tokens"] += row.output_tokens
        return UsageSummary(days=days, totals=totals, by_agent_day=rows)
