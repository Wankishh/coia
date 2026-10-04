import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from app.models.conversation import ChatMessage, ChatRole, Conversation
from app.models.execution import ExecutionLog, ExecutionStatus, TriggerType
from app.services.agent_runner import _prepend_run_memory
from app.services.chat_service import _memory_message, prepare_chat_memory
from app.services.memory import (
    extractive_summary,
    format_run_memory_block,
    window_chat_messages,
)
from app.services.repos import ExecutionRepository


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


def test_prepare_chat_memory_passes_only_windowed_tail_to_langchain():
    messages = [
        _msg(
            ChatRole.user if index % 2 == 0 else ChatRole.assistant,
            f"message-{index}",
        )
        for index in range(30)
    ]
    messages.insert(
        25,
        ChatMessage(
            role=ChatRole.assistant,
            content="scheduled run output",
            kind="run_result",
        ),
    )
    conversation = Conversation(agent_id="a1", messages=messages)

    tail, summary_update = prepare_chat_memory(
        conversation,
        SimpleNamespace(),
        window=8,
        summary_max_chars=2000,
    )

    assert len(tail) == 8
    assert [message.content for message in tail] == [
        f"message-{index}" for index in range(22, 30)
    ]
    assert all(isinstance(message, (HumanMessage, AIMessage)) for message in tail)
    assert summary_update is not None
    assert summary_update.through_count == 22
    assert "scheduled run output" not in summary_update.summary


def test_prepare_chat_memory_summarizes_only_new_overflow_and_keeps_newest():
    messages = [
        _msg(
            ChatRole.user if index % 2 == 0 else ChatRole.assistant,
            f"message-{index}-" + ("x" * 40),
        )
        for index in range(8)
    ]
    conversation = Conversation(
        agent_id="a1",
        messages=messages,
        rolling_summary="old summary that should be displaced",
        summary_through_count=4,
    )

    _, summary_update = prepare_chat_memory(
        conversation,
        SimpleNamespace(),
        window=2,
        summary_max_chars=100,
    )

    assert summary_update is not None
    assert summary_update.through_count == 6
    assert "message-5" in summary_update.summary
    assert "message-4" not in summary_update.summary
    assert "old summary" not in summary_update.summary


def test_prepare_chat_memory_returns_no_update_without_new_overflow():
    conversation = Conversation(
        agent_id="a1",
        messages=[_msg(ChatRole.user, f"message-{index}") for index in range(6)],
        rolling_summary="already summarized",
        summary_through_count=4,
    )

    _, summary_update = prepare_chat_memory(
        conversation,
        SimpleNamespace(),
        window=2,
        summary_max_chars=2000,
    )

    assert summary_update is None


def test_historical_memory_is_an_untrusted_human_message():
    memory = _memory_message("Earlier user text")

    assert isinstance(memory, HumanMessage)
    assert memory.content.startswith(
        "[Untrusted memory of earlier turns — may be incomplete]\n"
    )


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


def test_empty_prior_run_memory_leaves_prompt_unchanged():
    human = "Analyze the latest revenue."
    assert _prepend_run_memory(human, "") == human


class _FakeExecutionCursor:
    def __init__(self, documents):
        self.documents = documents
        self.sort_args = None
        self.limit_value = None

    def sort(self, key, direction):
        self.sort_args = (key, direction)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for document in self.documents[: self.limit_value]:
            yield document


class _FakeExecutionCollection:
    def __init__(self, documents):
        self.cursor = _FakeExecutionCursor(documents)
        self.query = None
        self.projection = None

    def find(self, query, projection):
        self.query = query
        self.projection = projection
        return self.cursor


def test_list_recent_finished_excludes_current_and_returns_oldest_first():
    newest = ExecutionLog(
        id="newest",
        agent_id="a1",
        trigger_type=TriggerType.manual,
        status=ExecutionStatus.failed,
    )
    oldest = ExecutionLog(
        id="oldest",
        agent_id="a1",
        trigger_type=TriggerType.cron,
        status=ExecutionStatus.completed,
    )
    collection = _FakeExecutionCollection(
        [
            newest.model_dump(mode="json"),
            oldest.model_dump(mode="json"),
        ]
    )
    repository = ExecutionRepository.__new__(ExecutionRepository)
    repository._col = collection

    rows = asyncio.run(
        repository.list_recent_finished(
            "a1",
            limit=2,
            exclude_id="current",
        )
    )

    assert [row.id for row in rows] == ["oldest", "newest"]
    assert collection.query == {
        "agent_id": "a1",
        "status": {
            "$in": ["completed", "failed", "cancelled"],
        },
        "id": {"$ne": "current"},
    }
    assert collection.cursor.sort_args == ("start_time", -1)
    assert collection.cursor.limit_value == 2
