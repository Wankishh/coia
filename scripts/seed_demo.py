#!/usr/bin/env python3
"""Register the default Financial Analyst demo agent via the harness API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

# Allow `python scripts/seed_demo.py` to import the app package.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.services.demo_source import (  # noqa: E402
    DEMO_SOURCE_ID,
    DEMO_SOURCE_TITLE,
    build_demo_source_payload,
)

DEFAULT_SYSTEM_PROMPT = """You are {{name}}, a financial analyst agent for Coia Agents.

Your job is to analyze sales data from the demo database and produce clear,
actionable insights for business stakeholders.

Guidelines:
- Use the run_sql_query tool for read-only analysis of the demo database.
- Primary fact table: sales_transactions (denormalized). Related tables for joins:
  customers, products, employees, orders, order_items.
- Prefer write_html_report when producing a visual summary (tables, key metrics, charts via simple HTML/CSS).
- You may use read_file / write_file / list_files within your sandbox workspace for notes.
- Be concise, data-driven, and cite the query results you used.
- Never attempt write/DDL SQL — only SELECT/WITH/SHOW/EXPLAIN are allowed.
"""

DEFAULT_PROMPT = (
    "Analyze demo sales data: summarize revenue by region and product from "
    "sales_transactions, optionally cross-check with orders/order_items/customers, "
    "highlight top performers, and write an HTML report with key metrics and tables."
)

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def resolve_api_key(provider: str, cli_key: Optional[str]) -> str:
    """Prefer --api-key; otherwise copy provider env into the agent payload once."""
    if cli_key and cli_key.strip():
        return cli_key.strip()

    env_name = PROVIDER_ENV_KEYS.get(provider, "OPENAI_API_KEY")
    from_env = (os.getenv("SEED_AGENT_API_KEY") or os.getenv(env_name) or "").strip()
    if from_env:
        return from_env

    raise SystemExit(
        "API key required for seed. Pass --api-key, or set SEED_AGENT_API_KEY / "
        f"{env_name} in the environment (copied into the agent once; not used at runtime)."
    )


def build_source_payload() -> dict[str, Any]:
    demo_db = os.getenv(
        "DEMO_DATABASE_URL",
        "postgresql+psycopg2://demo:demo@localhost:5432/demo",
    )
    return build_demo_source_payload(demo_db)


def build_agent_payload(api_key: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "name": os.getenv("SEED_AGENT_NAME", "Financial Analyst"),
        "role": os.getenv("SEED_AGENT_ROLE", "financial_analyst"),
        "system_prompt": os.getenv("SEED_AGENT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        "provider": os.getenv("SEED_AGENT_PROVIDER", "openai"),
        "model_name": os.getenv("SEED_AGENT_MODEL", "gpt-4o-mini"),
        "api_key": api_key,
        "enabled_tools": [],
        "cron_schedule": os.getenv("SEED_CRON_SCHEDULE") or None,
        "default_prompt": os.getenv("SEED_AGENT_DEFAULT_PROMPT", DEFAULT_PROMPT),
        "source_ids": source_ids,
    }


def ensure_demo_source(client: httpx.Client, base: str) -> str:
    """Create or reuse the library SQL source pointing at the demo DB."""
    sources = client.get(f"{base}/sources")
    sources.raise_for_status()
    for src in sources.json():
        if src.get("id") == DEMO_SOURCE_ID or (
            src.get("title") == DEMO_SOURCE_TITLE and src.get("type") == "sql"
        ):
            print(f"Data source already exists: id={src['id']}")
            return src["id"]

    payload = build_source_payload()
    safe = {
        **payload,
        "config": {
            **payload["config"],
            "connection_string": "***",
        },
    }
    print(f"Creating library data source at {base}/sources ...")
    print(json.dumps(safe, indent=2))
    created = client.post(f"{base}/sources", json=payload)
    created.raise_for_status()
    source = created.json()
    print(f"Created data source: id={source['id']}")
    return source["id"]


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Seed Coia Agents demo agent")
    parser.add_argument(
        "--base-url",
        default=os.getenv("HARNESS_BASE_URL", "http://localhost:8000"),
        help="Harness API base URL",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LLM API key to store on the agent (else SEED_AGENT_API_KEY / provider env)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Also trigger a manual run after creating the agent",
    )
    args = parser.parse_args()

    provider = os.getenv("SEED_AGENT_PROVIDER", "openai")
    api_key = resolve_api_key(provider, args.api_key)
    base = args.base_url.rstrip("/")

    try:
        with httpx.Client(timeout=30.0) as client:
            health = client.get(f"{base}/health")
            health.raise_for_status()
            print("Health:", health.json())

            source_id = ensure_demo_source(client, base)
            payload = build_agent_payload(api_key, [source_id])

            safe_preview = {
                k: ("***" if k == "api_key" else v)
                for k, v in payload.items()
                if k != "system_prompt"
            }
            print(f"Seeding demo agent at {base}/agents ...")
            print(json.dumps(safe_preview, indent=2))

            # Avoid duplicate Financial Analyst if already present
            existing = client.get(f"{base}/agents")
            existing.raise_for_status()
            agents = existing.json()
            for agent in agents:
                if agent.get("name") == payload["name"]:
                    print(f"Agent already exists: id={agent['id']}")
                    # Ensure attachment if older seed lacked source_ids
                    if source_id not in (agent.get("source_ids") or []):
                        patched = client.patch(
                            f"{base}/agents/{agent['id']}",
                            json={"source_ids": [source_id]},
                        )
                        patched.raise_for_status()
                        print(f"Attached library source {source_id} to existing agent")
                    agent_id = agent["id"]
                    break
            else:
                created = client.post(f"{base}/agents", json=payload)
                created.raise_for_status()
                agent = created.json()
                agent_id = agent["id"]
                print(f"Created agent: id={agent_id}")
                print(f"API key set: {agent.get('api_key_set')}")
                if agent.get("api_key_preview"):
                    print(f"API key preview: {agent.get('api_key_preview')}")
                print(f"Attached sources: {agent.get('source_ids')}")

            if args.run:
                run = client.post(f"{base}/agents/{agent_id}/run", json={})
                if run.status_code == 409:
                    print("Agent already running; not starting another run.")
                else:
                    run.raise_for_status()
                    print("Run accepted:", run.json())
                    print(f"Poll: GET {base}/executions/{run.json()['execution_id']}")
                    print(f"Logs: GET {base}/agents/{agent_id}/logs")
            else:
                print(f"Done. Run with: POST {base}/agents/{agent_id}/run")
                print(f"Logs: GET {base}/agents/{agent_id}/logs")
    except httpx.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        if getattr(exc, "response", None) is not None:
            print(exc.response.text, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
