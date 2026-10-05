"""LangGraph-based agent execution with near-real-time log streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.config import Settings
from app.models.execution import ExecutionLog, ExecutionStatus, ToolCallRecord, TriggerType
from app.services.activity_registry import ActivityRegistry
from app.services.chat_service import ChatService
from app.services.html_helpers import extract_html_from_text, persist_html_report
from app.services.message_content import (
    EMPTY_RUN_DELIVERABLE_ERROR,
    content_block_type_labels,
    has_usable_run_deliverable,
    message_content_to_str,
)
from app.services.memory import format_run_memory_block
from app.services.schema_context import (
    append_schema_to_system_prompt,
    build_attached_sources_schema_block,
)
from app.services.llm_factory import LLMFactory, LLMFactoryError
from app.services.prompt_interpolate import interpolate_prompt
from app.services.repos import (
    AgentAlreadyRunningError,
    AgentRepository,
    ExecutionRepository,
    SourceRepository,
    UsageRepository,
)
from app.services.source_resolve import resolve_agent_sources
from app.tools.factory import (
    agent_has_html_report_tool,
    append_html_report_hint,
    build_tools_for_agent,
)

logger = logging.getLogger(__name__)

__all__ = ["AgentRunner", "AgentAlreadyRunningError"]


def _prepend_run_memory(human: str, memory_block: str) -> str:
    if not memory_block:
        return human
    return memory_block + "\n\n---\nCurrent task:\n" + human


class AgentRunner:
    """Runs an agent in the background and streams steps into ExecutionLog."""

    def __init__(
        self,
        agent_repo: AgentRepository,
        execution_repo: ExecutionRepository,
        settings: Settings,
        source_repo: Optional[SourceRepository] = None,
        chat_service: Optional[ChatService] = None,
        activity: Optional[ActivityRegistry] = None,
        usage_repo: Optional[UsageRepository] = None,
    ) -> None:
        self._agents = agent_repo
        self._executions = execution_repo
        self._settings = settings
        self._sources = source_repo
        self._chat = chat_service
        self._activity = activity
        self._usage = usage_repo

    async def start_run(
        self,
        agent_id: str,
        *,
        trigger_type: TriggerType,
        prompt: Optional[str] = None,
    ) -> Optional[ExecutionLog]:
        """
        Claim a run by inserting a status=running ExecutionLog.

        Raises AgentAlreadyRunningError if the partial unique index rejects the insert.
        Returns None if the agent does not exist.
        Caller schedules work via TaskRegistry.create_task.
        """
        agent = await self._agents.get(agent_id)
        if agent is None:
            return None

        effective_prompt = prompt or agent.default_prompt or (
            "Analyze the available data and produce a clear summary with an HTML report."
        )
        log = ExecutionLog(
            agent_id=agent_id,
            trigger_type=trigger_type,
            status=ExecutionStatus.running,
            prompt=effective_prompt,
        )
        await self._executions.create(log)
        return log

    async def execute(self, execution_id: str) -> None:
        """Run the agent graph for an existing execution log."""
        log = await self._executions.get(execution_id)
        if log is None:
            logger.error("Execution %s not found", execution_id)
            return

        agent = await self._agents.get(log.agent_id)
        if agent is None:
            await self._executions.fail(execution_id, "Agent not found")
            await self._post_run_to_chat(execution_id)
            return

        captured_html: dict[str, Optional[str]] = {"html": None}

        def on_html(html: str) -> None:
            captured_html["html"] = html

        try:
            await self._executions.append_step(
                execution_id,
                ToolCallRecord(
                    step_type="llm_start",
                    message=f"Starting agent '{agent.name}' with provider={agent.provider.value} model={agent.model_name}",
                ),
            )

            llm = LLMFactory.create(agent)
            resolved_sources = (
                await resolve_agent_sources(agent, self._sources)
                if self._sources is not None
                else list(agent.sources)
            )
            tools = build_tools_for_agent(
                agent,
                self._settings,
                sources=resolved_sources,
                on_html=on_html,
            )
            graph = create_react_agent(llm, tools)

            system_text = interpolate_prompt(agent.system_prompt, agent)
            try:
                schema_block = await build_attached_sources_schema_block(
                    resolved_sources,
                    workspace_root=self._settings.workspace_path,
                )
                system_text = append_schema_to_system_prompt(
                    system_text, schema_block
                )
            except Exception:  # noqa: BLE001
                logger.debug("Run schema context skipped", exc_info=True)
            html_tool_expected = agent_has_html_report_tool(agent)
            system_text = append_html_report_hint(
                system_text,
                has_html_tool=html_tool_expected,
                for_run=True,
            )

            prior = await self._executions.list_recent_finished(
                agent.id,
                limit=self._settings.run_memory_last_n,
                exclude_id=execution_id,
            )
            memory_block = format_run_memory_block(
                prior,
                each_max_chars=self._settings.run_memory_each_max_chars,
            )
            human = _prepend_run_memory(
                interpolate_prompt(log.prompt or "", agent),
                memory_block,
            )
            messages: list[Any] = [
                SystemMessage(content=system_text),
                HumanMessage(content=human),
            ]

            if self._activity is not None:
                self._activity.ensure_exec_cancel(execution_id)

            # Prefer last AI text with no tool_calls (true final answer).
            # Keep last text-bearing AI message as fallback for ops / debugging.
            final_text = ""
            fallback_text = ""
            empty_extraction_labels: list[str] = []
            cancelled = False
            async for event in graph.astream(
                {"messages": messages},
                stream_mode="updates",
                config={"recursion_limit": 40},
            ):
                if self._activity and self._activity.is_execution_cancelled(execution_id):
                    cancelled = True
                    break
                await self._process_event(execution_id, event, captured_html)
                for node_output in event.values():
                    if not isinstance(node_output, dict):
                        continue
                    for msg in node_output.get("messages", []):
                        if not isinstance(msg, AIMessage):
                            continue
                        text = message_content_to_str(msg.content)
                        if not text.strip():
                            labels = content_block_type_labels(msg.content)
                            empty_extraction_labels = labels
                            logger.debug(
                                "Execution %s AI message with no extractable text; "
                                "content block types: %s",
                                execution_id,
                                labels,
                            )
                            continue
                        fallback_text = text
                        # Live execution view: latest model text (incl. tool turns).
                        await self._executions.append_output_text(
                            execution_id, text
                        )
                        if not (getattr(msg, "tool_calls", None) or []):
                            final_text = text

            final_text = final_text or fallback_text

            if cancelled:
                await self._cancel(execution_id, final_text)
                return

            output_html = captured_html["html"] or extract_html_from_text(final_text)
            if output_html:
                workspace = self._settings.workspace_path / agent.id
                persist_html_report(workspace, output_html)
                await self._executions.append_step(
                    execution_id,
                    ToolCallRecord(
                        step_type="html_persisted",
                        message="HTML report saved to workspace and execution log",
                    ),
                )

            if not has_usable_run_deliverable(
                final_text,
                output_html,
                html_tool_expected=html_tool_expected,
            ):
                if empty_extraction_labels and not final_text.strip():
                    await self._executions.append_step(
                        execution_id,
                        ToolCallRecord(
                            step_type="final_answer",
                            message=(
                                "No extractable final text; content block types: "
                                + ", ".join(empty_extraction_labels)
                            ),
                            output=None,
                        ),
                    )
                error = (
                    EMPTY_RUN_DELIVERABLE_ERROR
                    if html_tool_expected
                    else "Run finished without a final summary"
                )
                await self._fail(execution_id, error)
                return

            await self._executions.append_step(
                execution_id,
                ToolCallRecord(
                    step_type="final_answer",
                    message="Agent completed successfully",
                    output=final_text[:2000] if final_text else None,
                ),
            )
            finalized = await self._executions.complete(
                execution_id,
                output_text=final_text,
                output_html=output_html,
                status=ExecutionStatus.completed,
            )
            if finalized:
                await self._post_run_to_chat(execution_id)
                if self._usage is not None:
                    try:
                        await self._usage.record(
                            agent_id=agent.id,
                            provider=getattr(
                                agent.provider, "value", str(agent.provider)
                            ),
                            model=agent.model_name,
                            kind="run",
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug("Usage record failed", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Execution %s task cancelled", execution_id)
            await self._cancel(execution_id, "")
            raise
        except LLMFactoryError as exc:
            logger.warning("LLM factory error for execution %s: %s", execution_id, exc)
            await self._fail(execution_id, str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent execution %s failed", execution_id)
            await self._fail(execution_id, str(exc))
        finally:
            if self._activity is not None:
                self._activity.clear_execution_cancel(execution_id)

    async def _cancel(self, execution_id: str, partial_text: str) -> None:
        log = await self._executions.get(execution_id)
        if log is None or log.status != ExecutionStatus.running:
            return
        await self._executions.append_step(
            execution_id,
            ToolCallRecord(step_type="error", message="Cancelled"),
        )
        if partial_text:
            await self._executions.append_output_text(execution_id, partial_text)
        await self._executions.cancel(execution_id, "Cancelled")
        await self._post_run_to_chat(execution_id)

    async def _fail(self, execution_id: str, error_message: str) -> None:
        await self._executions.append_step(
            execution_id,
            ToolCallRecord(
                step_type="error",
                message=error_message,
            ),
        )
        await self._executions.fail(execution_id, error_message)
        await self._post_run_to_chat(execution_id)

    async def _post_run_to_chat(self, execution_id: str) -> None:
        """Append finalized run output into the agent's Agent runs chat session."""
        if self._chat is None:
            return
        try:
            log = await self._executions.get(execution_id)
            if log is None:
                return
            await self._chat.post_run_result(log)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to post execution %s to Agent runs chat",
                execution_id,
                exc_info=True,
            )

    async def _process_event(
        self,
        execution_id: str,
        event: dict[str, Any],
        captured_html: dict[str, Optional[str]],
    ) -> None:
        for node_name, node_output in event.items():
            if not isinstance(node_output, dict):
                continue
            messages = node_output.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                    for call in msg.tool_calls:
                        await self._executions.append_step(
                            execution_id,
                            ToolCallRecord(
                                step_type="tool_invocation",
                                tool_name=call.get("name"),
                                input=call.get("args"),
                                message=f"Invoking tool via node '{node_name}'",
                            ),
                        )
                elif isinstance(msg, ToolMessage):
                    content = message_content_to_str(msg.content)
                    await self._executions.append_step(
                        execution_id,
                        ToolCallRecord(
                            step_type="tool_output",
                            tool_name=getattr(msg, "name", None),
                            output=content[:4000],
                            message=f"Tool result via node '{node_name}'",
                        ),
                    )
                    # Prefer HTML captured by write_html_report callback;
                    # also detect if the tool itself returned HTML content.
                    if getattr(msg, "name", None) == "write_html_report":
                        # Content already captured via on_html callback when possible.
                        pass
