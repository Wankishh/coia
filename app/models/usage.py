"""Usage / cost meter models (rough MVP)."""

from datetime import date, datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    day: str  # YYYY-MM-DD UTC
    provider: str = ""
    model: str = ""
    request_count: int = 1
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    kind: str = "chat"  # chat | run
    created_at: datetime = Field(default_factory=_utcnow)


class UsageDayRow(BaseModel):
    day: str
    agent_id: str
    provider: str = ""
    model: str = ""
    request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageSummary(BaseModel):
    days: int
    totals: dict[str, int]
    by_agent_day: list[UsageDayRow]
