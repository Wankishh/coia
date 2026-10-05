"""Assemble enabled tools for an agent."""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from langchain_core.tools import BaseTool

from app.config import Settings
from app.models.agent import AgentConfig
from app.models.conversation import ChatAttachment
from app.models.source import (
    NosqlSourceConfig,
    RestSourceConfig,
    SourceConfig,
    SourceType,
    SqlSourceConfig,
)
from app.services.source_files import library_source_root
from app.tools.file_sql import create_file_sql_tool
from app.tools.generate_image import create_generate_image_tool
from app.tools.html_report import create_write_html_report_tool
from app.tools.mongo_readonly import create_mongo_tools_from_source
from app.tools.rest_get import create_http_get_tool
from app.tools.sandbox_file import create_sandbox_tools
from app.tools.sql_readonly import create_sql_tool, create_sql_tool_from_source

logger = logging.getLogger(__name__)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug[:40] or "source"


HTML_REPORT_HINT = (
    "When producing analytical summaries or scheduled run reports, call "
    "`write_html_report` with a complete styled HTML document; keep a short "
    "Markdown summary in the chat message. Skip the HTML tool for casual chat. "
    "Your final message must be the deliverable only (HTML via the tool and/or "
    "a concise executive summary) — no scratchpad and no step-by-step internal "
    "reasoning in the user-visible answer."
)

# Stronger requirement for cron / manual AgentRunner executions (not casual chat).
HTML_REPORT_HINT_RUN = (
    "For this cron/manual agent run, your FINAL step MUST call "
    "`write_html_report` with a complete, self-contained HTML document "
    "(full document with html/body or an equivalent complete report). "
    "Also leave a short Markdown executive summary in your final text message. "
    "Do not finish with only tool calls, empty output, or thinking-only content — "
    "an HTML report plus a brief summary are required deliverables. "
    "No scratchpad and no step-by-step internal reasoning in the user-visible answer."
)


def agent_has_html_report_tool(agent: AgentConfig) -> bool:
    """True when write_html_report will be included (same rules as build_tools)."""
    enabled = {t.strip() for t in (agent.enabled_tools or []) if t and t.strip()}
    return "write_html_report" in enabled or not enabled


def append_html_report_hint(
    system_prompt: str,
    *,
    has_html_tool: bool,
    for_run: bool = False,
) -> str:
    """Append an HTML report reminder when the tool is available."""
    if not has_html_tool:
        return system_prompt
    base = (system_prompt or "").rstrip()
    hint = HTML_REPORT_HINT_RUN if for_run else HTML_REPORT_HINT
    if for_run:
        # Always reinforce the run requirement (templates may mention the tool lightly).
        if HTML_REPORT_HINT_RUN.strip() in base:
            return system_prompt
        return f"{base}\n\n{hint}\n"
    if "write_html_report" in base:
        return system_prompt
    return f"{base}\n\n{hint}\n"


def build_tools_for_agent(
    agent: AgentConfig,
    settings: Settings,
    *,
    sources: Optional[list[SourceConfig]] = None,
    on_html: Optional[Callable[[str], None]] = None,
    on_image: Optional[Callable[[ChatAttachment], None]] = None,
    chat_id: Optional[str] = None,
) -> list[BaseTool]:
    """
    Build tools for an agent.

    ``sources`` should be the resolved library (or legacy embedded) sources.
    When omitted, falls back to ``agent.sources`` (legacy only).

    ``generate_image`` is included for all agents (default toolset). OpenAI,
    OpenRouter, and Google have image backends; Anthropic/Ollama return a clear
    error. Pass ``chat_id`` + ``on_image`` so generated PNGs become chat
    attachments for UI preview.
    """
    resolved = list(sources) if sources is not None else list(agent.sources)

    workspace = settings.workspace_path / agent.id
    workspace.mkdir(parents=True, exist_ok=True)

    library_mounts: dict = {}
    files_titles: dict[str, str] = {}
    for source in resolved:
        if source.type == SourceType.files:
            lib_root = library_source_root(settings.workspace_path, source.id)
            library_mounts[f"sources/{source.id}"] = lib_root
            files_titles[source.id] = source.title

    enabled = {t.strip() for t in agent.enabled_tools if t and t.strip()}
    tools: list[BaseTool] = []

    want_sandbox = bool(
        enabled
        & {"sandbox_file", "read_file", "write_file", "list_files"}
    ) or not enabled
    # If enabled_tools is empty, default to all tools for MVP convenience
    want_sql = bool(enabled & {"sql", "run_sql_query"}) or not enabled
    want_mongo = bool(
        enabled & {"mongo", "mongo_find", "mongo_aggregate", "mongo_list_collections"}
    ) or not enabled
    want_file_sql = bool(enabled & {"file_sql", "run_file_sql"}) or not enabled
    want_rest = bool(enabled & {"rest", "http_get"}) or not enabled
    want_html = "write_html_report" in enabled or not enabled
    want_image = "generate_image" in enabled or not enabled

    if want_sandbox:
        tools.extend(
            create_sandbox_tools(workspace, library_mounts=library_mounts)
        )

    if want_sql:
        sql_sources = [s for s in resolved if s.type == SourceType.sql]
        if sql_sources:
            for index, source in enumerate(sql_sources):
                try:
                    sql_cfg = SqlSourceConfig.model_validate(source.config)
                    tool_name = (
                        "run_sql_query"
                        if index == 0
                        else f"run_sql_query_{_slug(source.title)}"
                    )
                    tools.append(
                        create_sql_tool_from_source(
                            sql_cfg,
                            title=source.title,
                            description=source.description or "",
                            name=tool_name,
                            fallback_url=(
                                settings.demo_database_url if index == 0 else None
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Skipping SQL source %s for agent %s: %s",
                        source.id,
                        agent.id,
                        exc,
                    )
            # If every source failed to build, fall back to demo DB
            if not any(t.name.startswith("run_sql_query") for t in tools):
                tools.append(create_sql_tool(settings.demo_database_url))
        else:
            tools.append(
                create_sql_tool(
                    settings.demo_database_url,
                    description=(
                        "Execute a read-only SQL query against the demo sales database. "
                        "Allowed: SELECT, WITH, SHOW, EXPLAIN. "
                        "Tables: sales_transactions (denormalized fact), customers, products, "
                        "employees, orders, order_items. "
                        "sales_transactions columns: transaction_date, region, product, channel, "
                        "quantity, unit_price, revenue, customer_segment, salesperson."
                    ),
                )
            )

    if want_mongo:
        mongo_sources = [s for s in resolved if s.type == SourceType.nosql]
        for index, source in enumerate(mongo_sources):
            try:
                nosql_cfg = NosqlSourceConfig.model_validate(source.config)
                if nosql_cfg.engine != "mongodb":
                    continue
                name_prefix = "mongo" if index == 0 else f"mongo_{_slug(source.title)}"
                tools.extend(
                    create_mongo_tools_from_source(
                        nosql_cfg,
                        title=source.title,
                        description=source.description or "",
                        name_prefix=name_prefix,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping Mongo source %s for agent %s: %s",
                    source.id,
                    agent.id,
                    exc,
                )

    if want_file_sql and library_mounts:
        try:
            file_tool = create_file_sql_tool(
                library_mounts,
                source_titles=files_titles,
            )
            if file_tool is not None:
                tools.append(file_tool)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Skipping file SQL tool for agent %s: %s", agent.id, exc
            )

    if want_rest:
        rest_sources = [s for s in resolved if s.type == SourceType.rest]
        for index, source in enumerate(rest_sources):
            try:
                rest_cfg = RestSourceConfig.model_validate(source.config)
                tool_name = (
                    "http_get" if index == 0 else f"http_get_{_slug(source.title)}"
                )
                tools.append(
                    create_http_get_tool(
                        rest_cfg,
                        title=source.title,
                        description=source.description or "",
                        name=tool_name,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping REST source %s for agent %s: %s",
                    source.id,
                    agent.id,
                    exc,
                )

    if want_html:
        tools.append(create_write_html_report_tool(workspace, on_html=on_html))

    if want_image:
        tools.append(
            create_generate_image_tool(
                workspace,
                provider=agent.provider,
                api_key=agent.api_key or "",
                base_url=agent.base_url,
                image_model=agent.image_model,
                workspace_root=settings.workspace_path,
                chat_id=chat_id,
                on_image=on_image,
            )
        )

    return tools
