"""Bounded chat window and extractive summaries for MVP agent memory."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.conversation import ChatMessage, ChatRole
from app.models.execution import ExecutionLog, ExecutionStatus
from app.services.message_content import truncate_for_chat


def window_chat_messages(
    history: list[ChatMessage],
    window: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """Split history into (kept tail, overflow prefix); non-positive keeps all."""
    if window <= 0 or len(history) <= window:
        return list(history), []
    return list(history[-window:]), list(history[:-window])


def extractive_summary(messages: Iterable[ChatMessage], max_chars: int) -> str:
    """Format older user/assistant turns as a bounded extractive summary."""
    lines: list[str] = []
    for message in messages:
        if message.role == ChatRole.user:
            prefix = "User"
        elif message.role == ChatRole.assistant:
            if message.kind == "run_result":
                continue
            prefix = "Assistant"
        else:
            continue

        text = (message.content or "").strip().replace("\n", " ")
        if text:
            lines.append(f"- {prefix}: {text[:240]}")

    summary = "Conversation summary (older turns):\n" + "\n".join(lines)
    return truncate_for_chat(summary, max_chars)


def format_run_memory_block(
    logs: list[ExecutionLog],
    each_max_chars: int,
) -> str:
    """Format prior execution outcomes, preserving caller-provided order."""
    if not logs:
        return ""

    parts = ["Prior run memory (most recent last):"]
    for log in logs:
        when = log.start_time.isoformat() if log.start_time else "?"
        status = (
            log.status.value
            if isinstance(log.status, ExecutionStatus)
            else str(log.status)
        )
        body = (log.output_text or "").strip()
        if not body and log.error_message:
            body = f"ERROR: {log.error_message}"
        if not body:
            body = "(no text output)"
        body = truncate_for_chat(body.replace("\n", " "), each_max_chars)
        parts.append(f"- [{when}] {status}: {body}")

    return "\n".join(parts)
