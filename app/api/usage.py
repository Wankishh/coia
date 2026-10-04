"""Cost & usage meter (rough MVP)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_usage_repo
from app.models.usage import UsageSummary
from app.services.repos import UsageRepository

router = APIRouter(tags=["usage"])


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    days: int = Query(7, ge=1, le=90),
    usage_repo: UsageRepository = Depends(get_usage_repo),
) -> UsageSummary:
    return await usage_repo.summarize(days=days)
