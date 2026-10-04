"""Unit checks for chat unread message aggregation rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.conversation import (
    ChatMessage,
    ChatRole,
    ConversationSummary,
    count_unread_messages,
    message_counts_as_unread,
)


def _ts(minutes: int = 0) -> datetime:
    return datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_counts_assistant_replies_and_run_kinds() -> None:
    messages = [
        ChatMessage(role=ChatRole.user, content="hi", timestamp=_ts(0)),
        ChatMessage(role=ChatRole.assistant, content="hello", timestamp=_ts(1)),
        ChatMessage(
            role=ChatRole.assistant,
            content="run",
            kind="run_result",
            timestamp=_ts(2),
        ),
        ChatMessage(
            role=ChatRole.assistant,
            content="handoff report",
            kind="handoff_report",
            timestamp=_ts(3),
        ),
        ChatMessage(
            role=ChatRole.system,
            content="note",
            kind="handoff",
            timestamp=_ts(4),
        ),
        ChatMessage(
            role=ChatRole.assistant,
            content="handoff note should not count",
            kind="handoff",
            timestamp=_ts(5),
        ),
    ]
    assert count_unread_messages(messages, last_read_at=None) == 3


def test_respects_last_read_at() -> None:
    messages = [
        ChatMessage(role=ChatRole.assistant, content="old", timestamp=_ts(1)),
        ChatMessage(
            role=ChatRole.assistant,
            content="new run",
            kind="run_result",
            timestamp=_ts(5),
        ),
    ]
    assert count_unread_messages(messages, last_read_at=_ts(3)) == 1
    assert count_unread_messages(messages, last_read_at=_ts(6)) == 0


def test_dict_messages_and_absent_kind() -> None:
    messages = [
        {"role": "assistant", "content": "plain", "timestamp": _ts(1)},
        {"role": "user", "content": "me", "timestamp": _ts(2)},
    ]
    assert message_counts_as_unread(messages[0], None) is True
    assert message_counts_as_unread(messages[1], None) is False
    assert count_unread_messages(messages, None) == 1


def test_summary_aliases_unread_runs() -> None:
    summary = ConversationSummary(
        id="c1",
        agent_id="a1",
        title="Chat",
        updated_at=_ts(0),
        unread_count=2,
    )
    assert summary.unread_count == 2
    assert summary.unread_runs == 2

    legacy = ConversationSummary(
        id="c2",
        agent_id="a1",
        title="Agent runs",
        updated_at=_ts(0),
        unread_runs=4,
    )
    assert legacy.unread_count == 4
    assert legacy.unread_runs == 4
