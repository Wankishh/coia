"""Execution log models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TriggerType(str, Enum):
    manual = "manual"
    cron = "cron"


class ExecutionStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolCallRecord(BaseModel):
    step_type: str
    tool_name: Optional[str] = None
    input: Optional[Any] = None
    output: Optional[Any] = None
    message: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class ExecutionLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    trigger_type: TriggerType
    status: ExecutionStatus = ExecutionStatus.running
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    output_text: str = ""
    output_html: Optional[str] = None
    start_time: datetime = Field(default_factory=_utcnow)
    end_time: Optional[datetime] = None
    error_message: Optional[str] = None
    prompt: Optional[str] = None
