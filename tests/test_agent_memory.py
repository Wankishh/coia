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
