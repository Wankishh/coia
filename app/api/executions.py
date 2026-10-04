"""Execution lookup and cancel endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_execution_repo
from app.models.execution import ExecutionLog, ExecutionStatus
from app.services.repos import ExecutionRepository

router = APIRouter(tags=["executions"])


class CancelResponse(BaseModel):
    ok: bool
    message: str


@router.get("/executions/{execution_id}", response_model=ExecutionLog)
async def get_execution(
    execution_id: str,
    execution_repo: ExecutionRepository = Depends(get_execution_repo),
) -> ExecutionLog:
    log = await execution_repo.get(execution_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return log


@router.post("/executions/{execution_id}/cancel", response_model=CancelResponse)
async def cancel_execution(
    execution_id: str,
    request: Request,
    execution_repo: ExecutionRepository = Depends(get_execution_repo),
) -> CancelResponse:
    log = await execution_repo.get(execution_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    if log.status != ExecutionStatus.running:
        return CancelResponse(
            ok=False,
            message=f"Execution is not running (status={log.status.value})",
        )

    activity = getattr(request.app.state, "activity", None)
    if activity is not None:
        activity.request_execution_cancel(execution_id)

    task_registry = getattr(request.app.state, "task_registry", None)
    task_cancelled = False
    if task_registry is not None:
        task_cancelled = task_registry.cancel_for_execution(execution_id)

    # Soft-mark cancelled immediately so activity feed clears; runner also
    # finalizes if it observes the flag before task cancel takes effect.
    marked = await execution_repo.cancel(execution_id, "Cancelled")
    return CancelResponse(
        ok=True,
        message=(
            "Cancel requested"
            + ("; task aborted" if task_cancelled else "")
            + ("; marked cancelled" if marked else "")
        ),
    )
