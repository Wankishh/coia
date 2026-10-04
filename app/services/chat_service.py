"""Chat turns — sync and SSE streaming (no ExecutionLog)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.config import Settings
from app.models.conversation import (
    ChatAttachment,
    ChatMessage,
    ChatRole,
    Conversation,
)
from app.models.execution import ExecutionLog, ExecutionStatus
from app.services.activity_registry import ActivityRegistry
from app.services.html_helpers import extract_html_from_text
from app.services.llm_factory import LLMFactory, LLMFactoryError
from app.services.message_content import (
    looks_like_scratchpad,
    message_content_to_str,
    truncate_for_chat,
)
from app.services.memory import extractive_summary, window_chat_messages
from app.services.prompt_interpolate import interpolate_prompt
from app.services.repos import (
    AgentRepository,
    ConversationRepository,
    SourceRepository,
    UsageRepository,
)
from app.services.schema_context import (
    append_schema_to_system_prompt,
    build_attached_sources_schema_block,
)
from app.services.source_resolve import resolve_agent_sources
from app.tools.factory import (
    agent_has_html_report_tool,
    append_html_report_hint,
    build_tools_for_agent,
)

logger = logging.getLogger(__name__)

__all__ = ["ChatService", "ChatServiceError"]

_TITLE_MAX_LEN = 60
_RUNS_SESSION_TITLE = "Agent runs"
_RUN_RESULT_KIND = "run_result"
_HTML_CAPTION_MAX = 280
_SCRATCHPAD_PREVIEW_MAX = 280
_SCRATCHPAD_STATUS_NOTE = (
    "Run completed, but no clean final report text was produced. "
    "See the execution detail for full model output and tool traces."
)


class ChatServiceError(RuntimeError):
    """User-facing chat failure (LLM / timeout / agent missing)."""


class ChatService:
    """Run a single chat turn against an agent using conversation history."""

    def __init__(
        self,
        agent_repo: AgentRepository,
        conversation_repo: ConversationRepository,
        settings: Settings,
        source_repo: Optional[SourceRepository] = None,
        activity: Optional[ActivityRegistry] = None,
        usage_repo: Optional[UsageRepository] = None,
    ) -> None:
        self._agents = agent_repo
        self._conversations = conversation_repo
        self._settings = settings
        self._sources = source_repo
        self._activity = activity
        self._usage = usage_repo

    async def create_chat(self, agent_id: str) -> Optional[Conversation]:
        agent = await self._agents.get(agent_id)
        if agent is None:
            return None
        return await self._conversations.create(agent_id)

    async def list_chats(self, agent_id: str):
        return await self._conversations.list_for_agent(agent_id)

    async def list_all_chats(self, *, limit: int = 100):
        return await self._conversations.list_all(limit=limit)

    async def get_chat(self, chat_id: str) -> Optional[Conversation]:
        return await self._conversations.get(chat_id)

    async def rename_chat(self, chat_id: str, title: str) -> Optional[Conversation]:
        cleaned = " ".join(title.split())
        if not cleaned:
            raise ChatServiceError("Title is required")
        return await self._conversations.update_title(
            chat_id, _truncate_title(cleaned)
        )

    async def delete_chat(self, chat_id: str) -> bool:
        return await self._conversations.delete(chat_id)

    async def mark_read(self, chat_id: str) -> Optional[Conversation]:
        return await self._conversations.mark_read(chat_id)

    async def add_attachment(
        self, chat_id: str, attachment: ChatAttachment
    ) -> Optional[Conversation]:
        conversation = await self._conversations.get(chat_id)
        if conversation is None:
            return None
        return await self._conversations.add_attachment(chat_id, attachment)

    async def request_cancel(self, chat_id: str) -> bool:
        if self._activity is None:
            return False
        return await self._activity.request_chat_cancel(chat_id)

    async def handoff_report(
        self,
        chat_id: str,
        *,
        message_index: Optional[int] = None,
        handoff_agent_id: Optional[str] = None,
    ) -> Conversation:
        """
        Post a summary + HTML into a chat on the handoff agent.
        Creates a new chat when none exists titled \"Handoffs\".
        """
        source = await self._conversations.get(chat_id)
        if source is None:
            raise ChatServiceError("Chat not found")
        agent = await self._agents.get(source.agent_id)
        if agent is None:
            raise ChatServiceError("Agent not found")

        target_id = (handoff_agent_id or agent.handoff_agent_id or "").strip()
        if not target_id:
            raise ChatServiceError("No handoff agent configured")
        target = await self._agents.get(target_id)
        if target is None:
            raise ChatServiceError("Handoff agent not found")

        msg = _pick_html_message(source.messages, message_index)
        if msg is None or not msg.html:
            raise ChatServiceError("No HTML report found on this chat")

        dest = await self._conversations.get_or_create_runs_session(
            target_id,
            title="Handoffs",
        )
        summary = (msg.content or "").strip()
        if len(summary) > 1200:
            summary = summary[:1199] + "…"
        note = ChatMessage(
            role=ChatRole.system,
            content=(
                f"Handoff from agent {agent.name} ({agent.id}) "
                f"via chat {source.id}.\n\n{summary or '(no text summary)'}"
            ),
            kind="handoff",
        )
        report = ChatMessage(
            role=ChatRole.assistant,
            content=summary or "HTML report handoff",
            html=msg.html,
            kind="handoff_report",
        )
        updated = await self._conversations.append_messages(
            dest.id, [note, report]
        )
        if updated is None:
            raise ChatServiceError("Failed to append handoff messages")
        return updated

    async def post_run_result(self, log: ExecutionLog) -> Conversation:
        """
        Append a harness run result into the agent's dedicated "Agent runs" session.

        Does not invoke the LLM. Callers should treat failures as non-fatal.
        """
        conversation = await self._conversations.get_or_create_runs_session(
            log.agent_id,
            title=_RUNS_SESSION_TITLE,
        )
        msg = ChatMessage(
            role=ChatRole.assistant,
            content=_format_run_result_content(log),
            html=log.output_html,
            execution_id=log.id,
            kind=_RUN_RESULT_KIND,
        )
        updated = await self._conversations.append_messages(conversation.id, [msg])
        if updated is None:
            raise ChatServiceError("Agent runs session not found after append")
        return updated

    async def send_message(self, chat_id: str, content: str) -> Conversation:
        """
        Append user message, run agent with history + system_prompt + tools,
        append assistant reply. Synchronous await for MVP (no ExecutionLog).
        """
        text = content.strip()
        if not text:
            raise ChatServiceError("Message content is required")

        conversation = await self._prepare_user_turn(chat_id, text)
        agent = await self._require_agent(conversation.agent_id)

        try:
            (
                assistant_text,
                tool_calls,
                html,
                summary_update,
            ) = await self._run_agent_turn(
                agent,
                conversation,
            )
        except ChatServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat turn failed for %s", chat_id)
            raise ChatServiceError(str(exc) or "Chat turn failed") from exc

        updated = await self._persist_assistant(
            chat_id, assistant_text, tool_calls, html=html
        )
        if summary_update is not None:
            await self._conversations.set_rolling_summary(
                conversation.id,
                summary_update,
            )
        await self._record_usage(agent)
        return updated

    async def stream_message(
        self, chat_id: str, content: str
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream a chat turn as SSE-oriented event dicts:

        ``{"event": "token"|"delta"|"tool"|"done"|"error", "data": {...}}``

        ``done`` is lightweight (``{"chat_id": ...}`` only). Clients should
        ``GET /chats/{id}`` for the final transcript — HTML reports can be
        large and must not ride in the SSE payload.
        """
        text = content.strip()
        if not text:
            yield {
                "event": "error",
                "data": {"message": "Message content is required"},
            }
            return

        try:
            conversation = await self._prepare_user_turn(chat_id, text)
        except ChatServiceError as exc:
            yield {"event": "error", "data": {"message": str(exc)}}
            return

        agent = await self._agents.get(conversation.agent_id)
        if agent is None:
            yield {"event": "error", "data": {"message": "Agent not found"}}
            return

        history, summary_update = prepare_chat_memory(
            conversation,
            agent,
            window=self._settings.chat_history_window,
            summary_max_chars=self._settings.chat_summary_max_chars,
        )
        memory = summary_update or conversation.rolling_summary

        if self._activity is not None:
            await self._activity.begin_chat(
                chat_id,
                conversation.agent_id,
                title=conversation.title,
            )

        assistant_text = ""
        tool_calls: list[dict[str, Any]] = []
        captured_html: dict[str, Optional[str]] = {"html": None}
        cancelled = False

        def on_html(html: str) -> None:
            captured_html["html"] = html

        try:
            async for event in self._stream_agent_turn(
                agent,
                history,
                memory=memory,
                on_html=on_html,
            ):
                if self._activity and self._activity.is_chat_cancelled(chat_id):
                    cancelled = True
                    break
                kind = event.get("event")
                if kind in ("token", "delta"):
                    piece = str(event.get("data", {}).get("text") or "")
                    assistant_text += piece
                    yield event
                elif kind == "tool":
                    data = event.get("data") or {}
                    if data.get("phase") == "start":
                        tool_calls.append(
                            {
                                "name": data.get("name"),
                                "args": data.get("args"),
                                "id": data.get("id"),
                            }
                        )
                    yield event
                else:
                    yield event
        except ChatServiceError as exc:
            yield {"event": "error", "data": {"message": str(exc)}}
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat stream failed for %s", chat_id)
            yield {
                "event": "error",
                "data": {"message": str(exc) or "Chat turn failed"},
            }
            return
        finally:
            if self._activity is not None:
                await self._activity.end_chat(chat_id)

        html = captured_html["html"] or extract_html_from_text(assistant_text)

        if cancelled:
            if assistant_text.strip():
                try:
                    await self._persist_assistant(
                        chat_id,
                        assistant_text + "\n\n_(Cancelled.)_",
                        tool_calls,
                        html=html,
                    )
                except ChatServiceError as exc:
                    yield {"event": "error", "data": {"message": str(exc)}}
                    return
            yield {
                "event": "error",
                "data": {"message": "Cancelled", "chat_id": chat_id},
            }
            return

        if not assistant_text.strip():
            assistant_text = "(No text reply from agent.)"

        try:
            await self._persist_assistant(
                chat_id, assistant_text, tool_calls, html=html
            )
            if summary_update is not None:
                await self._conversations.set_rolling_summary(
                    conversation.id,
                    summary_update,
                )
            await self._record_usage(agent)
        except ChatServiceError as exc:
            yield {"event": "error", "data": {"message": str(exc)}}
            return

        yield {
            "event": "done",
            "data": {"chat_id": chat_id},
        }

    async def _prepare_user_turn(self, chat_id: str, text: str) -> Conversation:
        conversation = await self._conversations.get(chat_id)
        if conversation is None:
            raise ChatServiceError("Chat not found")

        agent = await self._agents.get(conversation.agent_id)
        if agent is None:
            raise ChatServiceError("Agent not found")

        content = text
        if conversation.attachments:
            lines = [
                "",
                "[Chat attachments — use sandbox read_file / list_files on these paths]",
            ]
            for att in conversation.attachments:
                lines.append(
                    f"- {att.name} → `_chat_attachments/{att.name}` "
                    f"({att.size} bytes)"
                )
            content = text + "\n" + "\n".join(lines)

        user_msg = ChatMessage(role=ChatRole.user, content=content)
        title_update: Optional[str] = None
        if conversation.title == "Chat" and not conversation.messages:
            title_update = _truncate_title(text)

        conversation = await self._conversations.append_messages(
            chat_id,
            [user_msg],
            title=title_update,
        )
        if conversation is None:
            raise ChatServiceError("Chat not found")
        return conversation

    async def _record_usage(self, agent) -> None:
        if self._usage is None:
            return
        try:
            await self._usage.record(
                agent_id=agent.id,
                provider=getattr(agent.provider, "value", str(agent.provider)),
                model=agent.model_name,
                kind="chat",
            )
        except Exception:  # noqa: BLE001
            logger.debug("Usage record failed", exc_info=True)

    async def _require_agent(self, agent_id: str):
        agent = await self._agents.get(agent_id)
        if agent is None:
            raise ChatServiceError("Agent not found")
        return agent

    async def _persist_assistant(
        self,
        chat_id: str,
        assistant_text: str,
        tool_calls: list[dict[str, Any]],
        *,
        html: Optional[str] = None,
    ) -> Conversation:
        assistant_msg = ChatMessage(
            role=ChatRole.assistant,
            content=assistant_text,
            tool_calls=tool_calls or None,
            html=html,
        )
        updated = await self._conversations.append_messages(chat_id, [assistant_msg])
        if updated is None:
            raise ChatServiceError("Chat not found after reply")
        return updated

    async def _resolved_sources(self, agent):
        if self._sources is not None:
            return await resolve_agent_sources(agent, self._sources)
        return list(agent.sources)

    async def _system_message(self, agent) -> SystemMessage:
        prompt = interpolate_prompt(agent.system_prompt, agent)
        try:
            sources = await self._resolved_sources(agent)
            schema_block = await build_attached_sources_schema_block(sources)
            prompt = append_schema_to_system_prompt(prompt, schema_block)
        except Exception:  # noqa: BLE001
            logger.debug("Schema context skipped", exc_info=True)
        prompt = append_html_report_hint(
            prompt,
            has_html_tool=agent_has_html_report_tool(agent),
        )
        return SystemMessage(content=prompt)

    async def _build_graph(self, agent, *, on_html=None):
        try:
            llm = LLMFactory.create(agent)
        except LLMFactoryError as exc:
            raise ChatServiceError(str(exc)) from exc

        resolved_sources = await self._resolved_sources(agent)
        tools = build_tools_for_agent(
            agent,
            self._settings,
            sources=resolved_sources,
            on_html=on_html,
        )
        return create_react_agent(llm, tools)

    async def _run_agent_turn(
        self,
        agent,
        conversation: Conversation,
    ) -> tuple[
        str,
        list[dict[str, Any]],
        Optional[str],
        Optional[str],
    ]:
        captured_html: dict[str, Optional[str]] = {"html": None}

        def on_html(html: str) -> None:
            captured_html["html"] = html

        graph = await self._build_graph(agent, on_html=on_html)
        history, summary_update = prepare_chat_memory(
            conversation,
            agent,
            window=self._settings.chat_history_window,
            summary_max_chars=self._settings.chat_summary_max_chars,
        )
        messages: list[Any] = [await self._system_message(agent)]
        memory = summary_update or conversation.rolling_summary
        if memory:
            messages.append(
                SystemMessage(
                    content=(
                        "Memory of earlier conversation turns "
                        "(may be incomplete):\n" + memory
                    )
                )
            )
        messages.extend(history)

        timeout = float(self._settings.chat_timeout_seconds)
        try:
            result = await asyncio.wait_for(
                graph.ainvoke(
                    {"messages": messages},
                    config={"recursion_limit": 40},
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ChatServiceError(
                f"Chat timed out after {int(timeout)}s"
            ) from exc

        result_messages = result.get("messages") if isinstance(result, dict) else None
        if not result_messages:
            raise ChatServiceError("Agent returned no messages")

        assistant_text = ""
        fallback_text = ""
        tool_calls: list[dict[str, Any]] = []
        for msg in result_messages:
            if isinstance(msg, AIMessage):
                text = message_content_to_str(msg.content)
                raw_calls = getattr(msg, "tool_calls", None) or []
                if text.strip():
                    fallback_text = text
                    if not raw_calls:
                        assistant_text = text
                for call in raw_calls:
                    if isinstance(call, dict):
                        tool_calls.append(
                            {
                                "name": call.get("name"),
                                "args": call.get("args"),
                                "id": call.get("id"),
                            }
                        )

        assistant_text = assistant_text or fallback_text
        if not assistant_text.strip():
            assistant_text = "(No text reply from agent.)"
        html = captured_html["html"] or extract_html_from_text(assistant_text)
        return assistant_text, tool_calls, html, summary_update

    async def _stream_agent_turn(
        self,
        agent,
        history: list[Any],
        *,
        memory: str = "",
        on_html=None,
    ) -> AsyncIterator[dict[str, Any]]:
        graph = await self._build_graph(agent, on_html=on_html)
        messages: list[Any] = [await self._system_message(agent)]
        if memory:
            messages.append(
                SystemMessage(
                    content=(
                        "Memory of earlier conversation turns "
                        "(may be incomplete):\n" + memory
                    )
                )
            )
        messages.extend(history)

        timeout = float(self._settings.chat_timeout_seconds)
        try:
            async with asyncio.timeout(timeout):
                async for event in graph.astream_events(
                    {"messages": messages},
                    version="v2",
                    config={"recursion_limit": 40},
                ):
                    kind = event.get("event")
                    if kind == "on_chat_model_stream":
                        chunk = (event.get("data") or {}).get("chunk")
                        piece = _chunk_text(chunk)
                        if piece:
                            yield {"event": "token", "data": {"text": piece}}
                    elif kind == "on_tool_start":
                        data = event.get("data") or {}
                        yield {
                            "event": "tool",
                            "data": {
                                "phase": "start",
                                "name": event.get("name") or data.get("name"),
                                "args": data.get("input"),
                                "id": event.get("run_id"),
                            },
                        }
                    elif kind == "on_tool_end":
                        data = event.get("data") or {}
                        yield {
                            "event": "tool",
                            "data": {
                                "phase": "end",
                                "name": event.get("name") or data.get("name"),
                                "id": event.get("run_id"),
                            },
                        }
        except TimeoutError as exc:
            raise ChatServiceError(
                f"Chat timed out after {int(timeout)}s"
            ) from exc


def _pick_html_message(
    messages: list[ChatMessage], message_index: Optional[int]
) -> Optional[ChatMessage]:
    if message_index is not None:
        if 0 <= message_index < len(messages):
            return messages[message_index]
        return None
    for msg in reversed(messages):
        if msg.html:
            return msg
    return None


def _chunk_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    content = getattr(chunk, "content", None)
    if content is None:
        return ""
    return message_content_to_str(content)


def _truncate_title(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= _TITLE_MAX_LEN:
        return cleaned or "Chat"
    return cleaned[: _TITLE_MAX_LEN - 1].rstrip() + "…"


def _format_run_result_content(log: ExecutionLog) -> str:
    """
    Build Agent-runs chat copy for a finished execution.

    Full ``output_text`` stays on the ExecutionLog for the Executions page;
    chat gets a short caption, clean Markdown, or a status note — never a CoT dump.
    """
    trigger = (
        log.trigger_type.value
        if hasattr(log.trigger_type, "value")
        else str(log.trigger_type)
    )
    status = (
        log.status.value if hasattr(log.status, "value") else str(log.status)
    )
    lines = [
        f"Agent run — {trigger}",
        f"Status: {status}",
        f"Execution: {log.id}",
        f"Started: {log.start_time.isoformat()}",
    ]
    if log.end_time is not None:
        lines.append(f"Ended: {log.end_time.isoformat()}")
    lines.append("")
    if log.status in (ExecutionStatus.failed, ExecutionStatus.cancelled) and log.error_message:
        lines.append(f"Error: {log.error_message}")
        lines.append("")

    body = (log.output_text or "").strip()
    has_html = bool((log.output_html or "").strip())

    if has_html:
        if body and not looks_like_scratchpad(body):
            lines.append(truncate_for_chat(body, _HTML_CAPTION_MAX))
        else:
            lines.append(
                "HTML report attached."
                + (
                    " Model scratchpad omitted from chat — see execution detail."
                    if body
                    else ""
                )
            )
        return "\n".join(lines)

    if body:
        if looks_like_scratchpad(body):
            lines.append(_SCRATCHPAD_STATUS_NOTE)
            # One-line peek only — repetitive CoT dumps stay out of chat.
            first_line = next(
                (ln.strip() for ln in body.splitlines() if ln.strip()),
                body,
            )
            preview = truncate_for_chat(first_line, _SCRATCHPAD_PREVIEW_MAX)
            if preview:
                lines.append("")
                lines.append(f"Preview: {preview}")
        else:
            lines.append(body)
    elif log.status == ExecutionStatus.completed:
        lines.append(
            "No text or HTML deliverable was produced. "
            "Open Executions for tool steps and model output."
        )
    elif log.status == ExecutionStatus.failed and not log.error_message:
        lines.append(
            "No text or HTML deliverable was produced. "
            "Open Executions for tool steps and model output."
        )
    return "\n".join(lines)


def _history_to_langchain(history: list[ChatMessage], agent: Any) -> list[Any]:
    """
    Map stored chat messages to LangChain messages.

    MVP: only user/assistant text turns. System always comes from agent.system_prompt.
    User turns get persona placeholder interpolation at send time.
    Tool-call details are stored for display but not replayed (avoids orphan tool_calls).
    Harness run_result messages are excluded so they do not pollute interactive history.
    """
    out: list[Any] = []
    for msg in history:
        if msg.role == ChatRole.user:
            out.append(
                HumanMessage(content=interpolate_prompt(msg.content, agent))
            )
        elif msg.role == ChatRole.assistant:
            if msg.kind == _RUN_RESULT_KIND:
                continue
            out.append(AIMessage(content=msg.content or ""))
    return out


def prepare_chat_memory(
    conversation: Conversation,
    agent: Any,
    *,
    window: int,
    summary_max_chars: int,
) -> tuple[list[Any], Optional[str]]:
    """Return the LangChain tail and an updated summary when history overflows."""
    usable = [
        message
        for message in conversation.messages
        if message.kind != _RUN_RESULT_KIND
    ]
    kept, overflow = window_chat_messages(usable, window)
    summary_update: Optional[str] = None
    if overflow:
        summary_messages: list[ChatMessage] = []
        if conversation.rolling_summary:
            summary_messages.append(
                ChatMessage(
                    role=ChatRole.assistant,
                    content=conversation.rolling_summary,
                )
            )
        summary_update = extractive_summary(
            summary_messages + overflow,
            max_chars=summary_max_chars,
        )
    return _history_to_langchain(kept, agent), summary_update
