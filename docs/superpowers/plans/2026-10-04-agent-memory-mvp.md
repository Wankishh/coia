# Agent Memory MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop interactive chats from blowing the context window and stop cron/manual runs from being fully amnesiac — enough memory that overnight agents stay coherent for two internal companies.

**Architecture:** Keep Mongo `conversations` / `executions` as the source of truth. For **chat**, window recent user/assistant turns and inject a compact rolling summary (stored on the `Conversation` document) when older turns fall out of the window. For **cron/manual runs**, inject the last N completed execution summaries into the system or human preamble inside `AgentRunner.execute` (read-only from prior `ExecutionLog` rows — no vector DB). No RAG, no LangGraph checkpointer, no Neo memory platform.

**Tech Stack:** FastAPI, Motor/MongoDB, LangChain messages (`SystemMessage` / `HumanMessage` / `AIMessage`), existing `ChatService` + `AgentRunner`.

## Global Constraints

- MVP of ticket 007 only: (1) chat window + rolling summary, (2) cron last-N run summaries.
- Explicit memory tools / workspace conventions, vector RAG, and LangGraph checkpointing are **out of scope**.
- Do not replay `kind=="run_result"` into interactive chat history (existing rule stays).
- Summaries must be bounded (character caps) so “memory” cannot become a second unbounded transcript.
- Prefer deterministic extractive summaries from prior `output_text` / assistant content when possible; optional one-shot LLM summarize only if extractive quality is clearly insufficient — default path: **extractive** to avoid extra cost/latency on every turn.
- Internal + training value; not enterprise memory product.

---

## File structure (create / modify)

| Path | Responsibility |
| --- | --- |
| `app/config.py` | Window size + summary caps + last-N run count |
| `app/models/conversation.py` | Optional `rolling_summary: str` (+ `summary_through_index` or message count marker) |
| `app/services/memory.py` (new) | Pure helpers: window messages, build extractive summary, format run memory block |
| `app/services/chat_service.py` | Use windowed history + summary system note before agent turn |
| `app/services/agent_runner.py` | Inject last-N run summaries into run messages |
| `app/services/repos.py` | Persist rolling summary; list recent completed executions |
| `tests/test_agent_memory.py` | Window/summary/run-memory unit tests |
| `docs/tickets/007-agent-memory.md` | Mark MVP items; leave RAG/checkpoint unchecked |

**Out of scope:** vector indexes, memory tools (`save_memory` / `recall`), multi-agent shared memory, Neo parity.

---

### Task 1: Settings + pure memory helpers + tests

**Files:**
- Modify: `app/config.py`
- Create: `app/services/memory.py`
- Create: `tests/test_agent_memory.py`

**Interfaces:**
- Consumes: `ChatMessage`, `ChatRole`, execution summary fields (`status`, `output_text`, `error_message`, `start_time`)
- Produces:
  - `Settings.chat_history_window: int = 24`  # user+assistant messages kept verbatim
  - `Settings.chat_summary_max_chars: int = 2000`
  - `Settings.run_memory_last_n: int = 3`
  - `Settings.run_memory_each_max_chars: int = 600`
  - `window_chat_messages(history, window) -> tuple[list[ChatMessage], list[ChatMessage]]`  # (kept, overflow)
  - `extractive_summary(messages, max_chars) -> str`
  - `format_run_memory_block(logs, each_max_chars) -> str`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agent_memory.py
from datetime import datetime, timezone

from app.models.conversation import ChatMessage, ChatRole
from app.models.execution import ExecutionLog, ExecutionStatus, TriggerType
from app.services.memory import (
    extractive_summary,
    format_run_memory_block,
    window_chat_messages,
)


def _msg(role: ChatRole, content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


def test_window_keeps_last_n_non_run_result_style_messages():
    history = [_msg(ChatRole.user, f"u{i}") for i in range(10)]
    kept, overflow = window_chat_messages(history, window=4)
    assert [m.content for m in kept] == ["u6", "u7", "u8", "u9"]
    assert len(overflow) == 6


def test_extractive_summary_is_bounded():
    msgs = [_msg(ChatRole.user, "A" * 500), _msg(ChatRole.assistant, "B" * 500)]
    summary = extractive_summary(msgs, max_chars=200)
    assert len(summary) <= 200
    assert "user:" in summary.lower() or "User:" in summary


def test_format_run_memory_block_includes_last_outputs():
    logs = [
        ExecutionLog(
            agent_id="a1",
            trigger_type=TriggerType.cron,
            status=ExecutionStatus.completed,
            output_text="Revenue up 3% in APAC.",
            start_time=datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc),
        ),
        ExecutionLog(
            agent_id="a1",
            trigger_type=TriggerType.cron,
            status=ExecutionStatus.failed,
            error_message="LLM timeout",
            start_time=datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc),
        ),
    ]
    block = format_run_memory_block(logs, each_max_chars=600)
    assert "Revenue up 3%" in block
    assert "LLM timeout" in block
    assert "Prior run memory" in block
```

- [ ] **Step 2: Run tests — expect fail**

```bash
cd /Users/ivelinov/projects/ai/coia && python -m pytest tests/test_agent_memory.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement helpers**

```python
# app/services/memory.py
"""Bounded chat window + extractive summaries for MVP agent memory."""

from __future__ import annotations

from typing import Iterable

from app.models.conversation import ChatMessage, ChatRole
from app.models.execution import ExecutionLog, ExecutionStatus
from app.services.message_content import truncate_for_chat  # if signature fits; else local slice


def window_chat_messages(
    history: list[ChatMessage],
    window: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """Split history into (kept_tail, overflow_prefix). window<=0 keeps all."""
    if window <= 0 or len(history) <= window:
        return list(history), []
    overflow = history[:-window]
    kept = history[-window:]
    return kept, overflow


def extractive_summary(messages: Iterable[ChatMessage], max_chars: int) -> str:
    lines: list[str] = []
    for msg in messages:
        if msg.role == ChatRole.user:
            prefix = "User"
        elif msg.role == ChatRole.assistant:
            if msg.kind == "run_result":
                continue
            prefix = "Assistant"
        else:
            continue
        text = (msg.content or "").strip().replace("\n", " ")
        if not text:
            continue
        lines.append(f"- {prefix}: {text[:240]}")
    blob = "Conversation summary (older turns):\n" + "\n".join(lines)
    if len(blob) <= max_chars:
        return blob
    return blob[: max_chars - 1].rstrip() + "…"


def format_run_memory_block(
    logs: list[ExecutionLog],
    each_max_chars: int,
) -> str:
    if not logs:
        return ""
    parts = ["Prior run memory (most recent last):"]
    # Caller should pass oldest→newest for readability
    for log in logs:
        when = log.start_time.isoformat() if log.start_time else "?"
        status = log.status.value if isinstance(log.status, ExecutionStatus) else str(log.status)
        body = (log.output_text or "").strip()
        if not body and log.error_message:
            body = f"ERROR: {log.error_message}"
        if not body:
            body = "(no text output)"
        body = body.replace("\n", " ")
        if len(body) > each_max_chars:
            body = body[: each_max_chars - 1].rstrip() + "…"
        parts.append(f"- [{when}] {status}: {body}")
    return "\n".join(parts)
```

Add settings fields to `app/config.py` as listed in Interfaces.

- [ ] **Step 4: Pass tests + commit**

```bash
python -m pytest tests/test_agent_memory.py -v
```

```bash
git add app/config.py app/services/memory.py tests/test_agent_memory.py
git commit -m "$(cat <<'EOF'
feat: add bounded chat window and run-memory helpers

EOF
)"
```

---

### Task 2: Persist rolling summary on conversations + wire ChatService

**Files:**
- Modify: `app/models/conversation.py`
- Modify: `app/services/repos.py` (`ConversationRepository`)
- Modify: `app/services/chat_service.py` (`_history_to_langchain` call sites / `_run_agent_turn` / stream path)
- Modify: `tests/test_agent_memory.py`

**Interfaces:**
- Consumes: `Conversation.messages`, settings window/summary caps
- Produces: `Conversation.rolling_summary: str = ""` persisted when overflow grows; LLM sees `[System summary note] + windowed turns`

- [ ] **Step 1: Extend Conversation model**

On `Conversation` in `app/models/conversation.py`:

```python
    rolling_summary: str = ""
```

Mongo documents without the field must still validate (default `""`).

- [ ] **Step 2: Repository update helper**

```python
    async def set_rolling_summary(self, chat_id: str, summary: str) -> None:
        await self._col.update_one(
            {"id": chat_id},
            {"$set": {"rolling_summary": summary, "updated_at": _utcnow()}},
        )
```

(Confirm `updated_at` field exists on `Conversation`; if not, only set `rolling_summary`.)

- [ ] **Step 3: Add helper + wire ChatService**

Add this function near `_history_to_langchain` in `app/services/chat_service.py` (or in `memory.py` if you prefer easier imports):

```python
from app.services.memory import extractive_summary, window_chat_messages

def prepare_chat_memory(
    conversation: Conversation,
    agent: Any,
    *,
    window: int,
    summary_max_chars: int,
) -> tuple[list[Any], str | None]:
    """Return (langchain tail messages, summary_to_persist_or_None)."""
    usable = [
        m
        for m in conversation.messages
        if not (getattr(m, "kind", None) == "run_result")
    ]
    kept, overflow = window_chat_messages(usable, window)
    summary_update: str | None = None
    if overflow:
        prior = []
        if conversation.rolling_summary:
            prior = [
                ChatMessage(
                    role=ChatRole.assistant,
                    content=conversation.rolling_summary,
                )
            ]
        summary_update = extractive_summary(
            prior + overflow,
            max_chars=summary_max_chars,
        )
    return _history_to_langchain(kept, agent), summary_update
```

In `_run_agent_turn` (and the streaming path) after `system_text` is ready:

```python
tail, summary_update = prepare_chat_memory(
    conversation,
    agent,
    window=self._settings.chat_history_window,
    summary_max_chars=self._settings.chat_summary_max_chars,
)
messages: list[Any] = [SystemMessage(content=system_text)]
mem = summary_update or conversation.rolling_summary
if mem:
    messages.append(
        SystemMessage(
            content=(
                "Memory of earlier conversation turns (may be incomplete):\n"
                + mem
            )
        )
    )
messages.extend(tail)
```

After a successful turn, if `summary_update` is not `None`:

```python
await self._conversations.set_rolling_summary(conversation.id, summary_update)
```

Apply the same pattern to the streaming turn path so both stay consistent.

- [ ] **Step 4: Test window integration at helper level**

Add a test that simulates a 30-message conversation and asserts only `chat_history_window` messages are passed to `_history_to_langchain` equivalent (can test `_history_messages_for_llm` if extracted to `memory.py` or chat_service module level for testability).

- [ ] **Step 5: Commit**

```bash
git add app/models/conversation.py app/services/repos.py app/services/chat_service.py tests/test_agent_memory.py
git commit -m "$(cat <<'EOF'
feat: window chat history with rolling extractive summary

EOF
)"
```

---

### Task 3: Cron / manual run last-N summary memory

**Files:**
- Modify: `app/services/repos.py` (`ExecutionRepository`)
- Modify: `app/services/agent_runner.py`
- Modify: `tests/test_agent_memory.py`
- Modify: `docs/tickets/007-agent-memory.md`

**Interfaces:**
- Consumes: `ExecutionRepository.list_for_agent(agent_id, limit=...)` filtered to completed/failed (exclude `running` / current id)
- Produces: human or system preamble block from `format_run_memory_block`

- [ ] **Step 1: Add repo helper**

```python
    async def list_recent_finished(
        self,
        agent_id: str,
        *,
        limit: int = 3,
        exclude_id: str | None = None,
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
        rows.reverse()  # oldest → newest for the memory block
        return rows
```

- [ ] **Step 2: Inject into `AgentRunner.execute`**

After building `system_text` and before `messages = [...]`:

```python
from app.services.memory import format_run_memory_block

prior = await self._executions.list_recent_finished(
    agent.id,
    limit=self._settings.run_memory_last_n,
    exclude_id=execution_id,
)
memory_block = format_run_memory_block(
    prior,
    each_max_chars=self._settings.run_memory_each_max_chars,
)
human = interpolate_prompt(log.prompt or "", agent)
if memory_block:
    human = memory_block + "\n\n---\nCurrent task:\n" + human

messages: list[Any] = [
    SystemMessage(content=system_text),
    HumanMessage(content=human),
]
```

- [ ] **Step 3: Test format + exclude current id behavior with a fake repo or pure block test** (already partly in Task 1). Add assertion that empty prior ⇒ prompt unchanged.

- [ ] **Step 4: Manual smoke (if stack up)**

1. Create an agent with a short cron or use Run now twice.  
2. Second run’s execution detail / model context should mention prior output (visible in first human message if logged, or infer from continuity in output).  
3. Long chat: send > `chat_history_window` turns; confirm request still succeeds and `rolling_summary` populates on the conversation document.

- [ ] **Step 5: Update ticket 007**

Check off: chat window + rolling summaries; optional episodic memory for cron last N. Leave memory tools, RAG, checkpointing open.

- [ ] **Step 6: Commit**

```bash
git add app/services/repos.py app/services/agent_runner.py tests/test_agent_memory.py docs/tickets/007-agent-memory.md
git commit -m "$(cat <<'EOF'
feat: inject last-N run summaries into cron and manual runs

EOF
)"
```

---

## Acceptance criteria

1. Interactive chats only send ~last `chat_history_window` turns plus a bounded summary of older turns.  
2. Cron/manual runs see up to `run_memory_last_n` prior finished run digests in the prompt.  
3. No vector DB, no new memory tools, no LangGraph checkpointer.  
4. Existing run_result exclusion from chat LLM history remains.

## Spec coverage (self-check)

| Ticket 007 MVP | Task |
| --- | --- |
| Chat history window + rolling summaries | 1–2 |
| Episodic memory for cron (last N) | 3 |
| Not RAG / checkpoint / Neo memory | Global constraints |
