# Cron Reliability Ops (Thin Slice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect stuck agent runs, surface them clearly in Activity/Executions, and expose a richer `/health` so operators can leave cron agents overnight and see what failed when they return.

**Architecture:** Keep the single-worker APScheduler + Mongo `executions` model. Add a configurable wall-clock threshold (`run_stuck_seconds`). A periodic sweeper (APScheduler interval job on the existing `AgentScheduler`, or a lightweight loop started from `main.py` lifespan) finds `status=running` rows older than the threshold, marks them `failed` with a clear error, and best-effort cancels the in-process task via `ActivityRegistry` + `TaskRegistry`. Activity and Executions UIs show run age and a `stuck`/`failed (stuck)` signal. `/health` gains counts for running and stuck executions without becoming a Neo governance product.

**Tech Stack:** FastAPI, Motor/MongoDB, APScheduler, existing `ExecutionRepository` / admin static JS.

## Global Constraints

- Thin slice of ticket 006 only — **not** budgets, HITL, audit product, multi-worker, or Neo parity.
- Single uvicorn worker remains mandatory (`max_instances=1` cron jobs stay).
- Prefer failing stuck runs with an explicit message (`Stuck: exceeded N seconds`) over inventing a new `ExecutionStatus` enum value unless UI needs it — default: keep `failed` + distinctive `error_message` prefix `Stuck:` and optional Activity `status` display override when age > threshold but not yet swept.
- Trusted LAN / internal — no auth work in this plan.
- Default threshold should be generous enough for long LLM digests (e.g. **1800** seconds / 30 min) and overridable via env.
- Do not add Slack/email alerts in this slice (ticket 002 item 8 remains separate).

---

## File structure (create / modify)

| Path | Responsibility |
| --- | --- |
| `app/config.py` | `run_stuck_seconds`, optional `stuck_sweep_interval_seconds` |
| `app/services/repos.py` | `list_stuck_running(older_than)`, `fail_stuck_running(...)` helpers |
| `app/scheduler.py` or `app/services/stuck_runs.py` + `main.py` | Periodic sweeper + cancel hooks |
| `app/api/health.py` | Report `running_executions`, `stuck_executions`, threshold |
| `app/api/activity.py` | Include `duration_seconds`, `is_stuck` on activity items |
| `app/api/executions.py` / agents logs serialization | Expose age / stuck hint on list/detail if needed |
| `app/static/admin/app.js` | Render age + stuck badge in Activity + Executions |
| `app/static/admin/styles.css` | Minimal stuck styling (no redesign) |
| `tests/test_stuck_runs.py` | Repository + health / sweeper unit tests |
| `docs/tickets/006-production-monitoring.md` | Note thin slice done vs remaining |

**Out of scope:** multi-instance workers, Prometheus stack, auth-gated admin, outbound alerting, budget/rate limits.

---

### Task 1: Settings + repository helpers for stuck runs

**Files:**
- Modify: `app/config.py`
- Modify: `app/services/repos.py` (`ExecutionRepository`)
- Create: `tests/test_stuck_runs.py`

**Interfaces:**
- Consumes: `ExecutionLog`, `ExecutionStatus.running`, `_utcnow()`
- Produces:
  - `Settings.run_stuck_seconds: int = 1800`
  - `Settings.stuck_sweep_interval_seconds: int = 60`
  - `ExecutionRepository.list_running_older_than(cutoff: datetime) -> list[ExecutionLog]`
  - `ExecutionRepository.fail_if_running(execution_id: str, error_message: str) -> bool`

- [ ] **Step 1: Write failing tests for age query semantics**

Create `tests/test_stuck_runs.py` with pure helper tests if you extract a small pure function; otherwise test repository methods against a mongomock/fake — if the suite has no mongo fixture, extract:

```python
# tests/test_stuck_runs.py
from datetime import datetime, timedelta, timezone

from app.services.stuck_runs import is_stuck  # to be created as pure helper


def test_is_stuck_when_older_than_threshold():
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=1801)
    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is True


def test_is_stuck_false_when_within_threshold():
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=100)
    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/ivelinov/projects/ai/coia && python -m pytest tests/test_stuck_runs.py -v
```

Expected: FAIL — `stuck_runs` module missing.

- [ ] **Step 3: Implement pure helper + settings**

Create `app/services/stuck_runs.py`:

```python
"""Stuck-run detection helpers (wall-clock age vs threshold)."""

from __future__ import annotations

from datetime import datetime, timezone


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_stuck(
    *,
    start_time: datetime,
    now: datetime,
    threshold_seconds: int,
) -> bool:
    if threshold_seconds <= 0:
        return False
    age = (_as_utc(now) - _as_utc(start_time)).total_seconds()
    return age >= threshold_seconds


def stuck_error_message(threshold_seconds: int) -> str:
    return f"Stuck: exceeded {threshold_seconds} seconds without completing"
```

Add to `Settings` in `app/config.py`:

```python
    # Wall-clock age after which a running ExecutionLog is treated as stuck.
    run_stuck_seconds: int = 1800
    # How often the sweeper looks for stuck runs.
    stuck_sweep_interval_seconds: int = 60
```

- [ ] **Step 4: Add repository methods**

In `ExecutionRepository` (`app/services/repos.py`):

```python
    async def list_running_older_than(self, cutoff: datetime) -> list[ExecutionLog]:
        cursor = self._col.find(
            {
                "status": ExecutionStatus.running.value,
                "start_time": {"$lte": cutoff},
            },
            {"_id": 0},
        ).sort("start_time", 1)
        return [ExecutionLog.model_validate(doc) async for doc in cursor]

    async def fail_if_running(self, execution_id: str, error_message: str) -> bool:
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
```

- [ ] **Step 5: Pass tests + commit**

```bash
python -m pytest tests/test_stuck_runs.py -v
```

Expected: PASS.

```bash
git add app/config.py app/services/stuck_runs.py app/services/repos.py tests/test_stuck_runs.py
git commit -m "$(cat <<'EOF'
feat: add stuck-run threshold settings and repository helpers

EOF
)"
```

---

### Task 2: Periodic sweeper that fails stuck runs and cancels tasks

**Files:**
- Modify: `app/services/stuck_runs.py` (async sweep function)
- Modify: `app/scheduler.py` and/or `app/main.py`
- Modify: `tests/test_stuck_runs.py`

**Interfaces:**
- Consumes: `ExecutionRepository.list_running_older_than`, `fail_if_running`, `ActivityRegistry`, `TaskRegistry`, `ChatService.post_run_result` (if available on app state — mirror cancel path)
- Produces: `async def sweep_stuck_runs(...) -> int` returning failed count; interval job registered for app lifetime

- [ ] **Step 1: Implement `sweep_stuck_runs`**

```python
async def sweep_stuck_runs(
    *,
    executions: ExecutionRepository,
    threshold_seconds: int,
    activity=None,
    task_registry=None,
    on_failed=None,  # Optional awaitable(execution_id) e.g. post_run_to_chat
) -> int:
    from datetime import datetime, timedelta, timezone

    if threshold_seconds <= 0:
        return 0
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=threshold_seconds)
    stuck = await executions.list_running_older_than(cutoff)
    failed = 0
    msg = stuck_error_message(threshold_seconds)
    for log in stuck:
        if activity is not None:
            activity.request_execution_cancel(log.id)
        if task_registry is not None:
            task_registry.cancel_for_execution(log.id)
        if await executions.fail_if_running(log.id, msg):
            failed += 1
            if on_failed is not None:
                await on_failed(log.id)
    return failed
```

Cancel APIs (current codebase): `ActivityRegistry.request_execution_cancel`, `TaskRegistry.cancel_for_execution`. Optional `on_failed` should call the same post-run chat path used after normal failures (`ChatService.post_run_result` / runner helper — wire via `app.state.chat_service` or `app.state.runner`).

- [ ] **Step 2: Register interval job**

Prefer attaching to existing `AgentScheduler` in `app/scheduler.py`:

- On `start()`, add an interval job id `stuck-run-sweeper` every `stuck_sweep_interval_seconds`.
- Job callback loads settings + repos from the same wiring path `_cron_fire` uses (app-held references).
- Ensure `reload_all` / shutdown removes or does not duplicate the sweeper job.

Alternatively, spawn `asyncio.create_task` in `main.py` lifespan with `asyncio.sleep(interval)` loop and cancel on shutdown — acceptable if scheduler wiring is awkward.

- [ ] **Step 3: Unit-test sweep with a fake repo**

Add a fake in `tests/test_stuck_runs.py` that records `fail_if_running` calls; assert message starts with `Stuck:`.

- [ ] **Step 4: Commit**

```bash
git add app/services/stuck_runs.py app/scheduler.py app/main.py tests/test_stuck_runs.py
git commit -m "$(cat <<'EOF'
feat: sweep and fail stuck agent executions

EOF
)"
```

---

### Task 3: Healthcheck + Activity API signals

**Files:**
- Modify: `app/api/health.py`
- Modify: `app/api/activity.py`
- Modify: `tests/test_stuck_runs.py` (optional API test if FastAPI TestClient is already used elsewhere)

**Interfaces:**
- Produces health JSON fields: `running_executions: int`, `stuck_executions: int`, `run_stuck_seconds: int`
- Produces `ActivityItem.duration_seconds: int`, `ActivityItem.is_stuck: bool`

- [ ] **Step 1: Extend `/health`**

```python
@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings  # or get_settings()
    mongo_ok = False
    try:
        await request.app.state.mongo.admin.command("ping")
        mongo_ok = True
    except Exception:  # noqa: BLE001
        mongo_ok = False

    running = 0
    stuck = 0
    try:
        execution_repo = request.app.state.execution_repo  # confirm attribute name on app.state
        logs = await execution_repo.list_running(limit=100)
        running = len(logs)
        now = datetime.now(timezone.utc)
        stuck = sum(
            1
            for log in logs
            if is_stuck(
                start_time=log.start_time,
                now=now,
                threshold_seconds=settings.run_stuck_seconds,
            )
        )
    except Exception:  # noqa: BLE001
        pass

    status = "ok" if mongo_ok else "degraded"
    if stuck:
        status = "degraded"

    return {
        "status": status,
        "service": "coia-agent-harness",
        "mongo": "up" if mongo_ok else "down",
        "scheduler": (
            "running" if request.app.state.scheduler.scheduler.running else "stopped"
        ),
        "running_executions": running,
        "stuck_executions": stuck,
        "run_stuck_seconds": settings.run_stuck_seconds,
    }
```

Confirm `app.state` attribute names in `main.py` before wiring (may need `Depends(get_execution_repo)` pattern instead).

- [ ] **Step 2: Extend ActivityItem**

```python
class ActivityItem(BaseModel):
    id: str
    kind: Literal["run", "chat"]
    agent_id: str
    agent_name: Optional[str] = None
    status: str = "running"
    started_at: datetime
    title: Optional[str] = None
    execution_id: Optional[str] = None
    chat_id: Optional[str] = None
    duration_seconds: int = 0
    is_stuck: bool = False
```

When building run items, compute `duration_seconds` from `start_time` and set `is_stuck` via `is_stuck(...)`. If stuck, set `status` to `"stuck"` for display (Mongo status may still be `running` until sweeper fires).

- [ ] **Step 3: Manual curl check**

```bash
curl -s http://localhost:8000/health | python -m json.tool
curl -s http://localhost:8000/activity | python -m json.tool
```

Expected: new fields present; with no runs, `running_executions=0`, `stuck_executions=0`.

- [ ] **Step 4: Commit**

```bash
git add app/api/health.py app/api/activity.py tests/test_stuck_runs.py
git commit -m "$(cat <<'EOF'
feat: expose stuck-run signals on health and activity APIs

EOF
)"
```

---

### Task 4: Admin Activity + Executions clarity

**Files:**
- Modify: `app/static/admin/app.js` (`renderActivity`, `renderExecutions`, `renderExecutionDetail`)
- Modify: `app/static/admin/styles.css` (minimal)
- Modify: `docs/tickets/006-production-monitoring.md`

**Interfaces:**
- Consumes: `is_stuck`, `duration_seconds`, `error_message` starting with `Stuck:`
- Produces: visible age (`12m`, `45m`) and a stuck badge/row highlight

- [ ] **Step 1: Format duration helper in `app.js`**

```javascript
function formatDurationSeconds(total) {
  const s = Math.max(0, Math.floor(Number(total) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
```

- [ ] **Step 2: Activity rows**

In `renderActivity()`, show duration next to status. If `item.is_stuck` or `item.status === "stuck"`, add class `activity-stuck` and label `stuck`.

- [ ] **Step 3: Executions list/detail**

For running rows, show elapsed time from `start_time`. If `error_message` starts with `Stuck:`, show a clear failed-stuck label (not a generic failure).

- [ ] **Step 4: Minimal CSS**

```css
.activity-stuck,
.execution-stuck {
  color: var(--danger, #b42318);
  font-weight: 600;
}
```

(Use an existing danger token if present; do not invent a purple theme.)

- [ ] **Step 5: Update ticket 006**

Mark checklist items covered by this thin slice (stuck runs / clearer Activity+Executions / health). Leave auth, budgets, HITL, multi-instance unchecked.

- [ ] **Step 6: Commit**

```bash
git add app/static/admin/app.js app/static/admin/styles.css docs/tickets/006-production-monitoring.md
git commit -m "$(cat <<'EOF'
feat: show stuck-run age in Activity and Executions

EOF
)"
```

---

## Acceptance criteria

1. A run left `running` longer than `RUN_STUCK_SECONDS` is failed with `Stuck: ...` and no longer blocks the agent’s unique running index forever.  
2. `GET /health` reports running/stuck counts; stuck ⇒ `degraded`.  
3. Activity shows duration + stuck; Executions show stuck failures clearly.  
4. No Neo governance features shipped.

## Spec coverage (self-check)

| Ticket 006 thin ask | Task |
| --- | --- |
| Stuck-run detection | 1–2 |
| Clearer Activity/Executions for away monitoring | 3–4 |
| Healthcheck | 3 |
| Not full Neo governance | Global constraints |
