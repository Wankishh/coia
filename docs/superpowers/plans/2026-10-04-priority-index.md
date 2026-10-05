# Coia Agents — Priority Index (Internal-First)

**Date:** 2026-10-04  
**Audience:** Human + subagent executors  
**Product posture:** Internal use for two trusted small companies (user + wife). Secondary: show capability to a boss; personal AI-engineering training. **Not** Neo competition. **Not** optimizing for paid multi-tenant platform yet.

## Ranked order (execute top → bottom)

| Rank | Ticket | Plan | Status | Why (internal use) |
| --- | --- | --- | --- | --- |
| 1 | [001](../../tickets/001-agent-roles-roadmap.md) | [internal-roles-pack](./2026-10-04-internal-roles-pack.md) | **ACTIVE** | Templates are the fastest way to get useful agents for ops/finance/sales/content in both companies. No infra risk. Training value is high (prompt/role craft). |
| 2 | [006](../../tickets/006-production-monitoring.md) (thin slice) | [cron-reliability-ops](./2026-10-04-cron-reliability-ops.md) | **ACTIVE** | Agents must work **while you're away**. Stuck runs with no signal break trust faster than missing roles. Healthcheck + Activity/Executions clarity is the minimum “come back and see what happened” loop. |
| 3 | [007](../../tickets/007-agent-memory.md) (MVP) | [agent-memory-mvp](./2026-10-04-agent-memory-mvp.md) | **ACTIVE** | Cron is currently amnesiac; long chats will blow context. Window + summary + last-run memory makes overnight digests coherent without Neo-style memory platform. |
| 4 | [002](../../tickets/002-data-sources-integrations.md) remaining | *(no new plan — continue ticket checklist)* | **BACKLOG / as needed** | Mongo/CSV/REST already done. Next only when a real internal workflow needs them: MSSQL, Sheets, S3, cron webhook, Slack, ES, CRM. Prefer REST + files until a concrete source blocks a role. |
| 5 | [004](../../tickets/004-auth-roles.md) | [auth-roles-later](./2026-10-04-auth-roles-later.md) | **DEFER** | Trusted LAN for now. Keep design future-friendly; do not block day-one internal value. |
| — | [003](../../tickets/003-offline-installation.md) | [offline-installation](./2026-10-04-offline-installation.md) *(exists)* | **DEFER** | Air-gap / private appliance is a later distribution story. Plan already written — do not rewrite; execute only when packaging for offline hosts becomes real. |
| — | [005](../../tickets/005-external-clients.md) | [external-clients-later](./2026-10-04-external-clients-later.md) | **DEFER** | External clients / multi-tenant is after auth and after internal trust is proven. |

## Ticket 002 — remaining items (do not invent a mega-plan)

Already done: MongoDB query, CSV/Excel via DuckDB, REST GET-first.

Still open (pull from ticket when a use case appears):

3. MSSQL engine  
5. Google Sheets read  
6. S3/MinIO read  
7. Cron outbound webhook  
8. Slack notify  
9. Elasticsearch/OpenSearch  
10. CRM read (HubSpot / Salesforce)

**Internal default:** stay on SQL + files + Mongo + REST until one of the above is required by a live agent for either company.

## Explicit non-goals (this phase)

- Full Neo governance (budgets, HITL matrix, provenance product, multi-worker)
- Full ~40 role catalog
- Offline air-gap packaging (plan exists; timing deferred)
- Auth as day-one blocker
- External / paid client onboarding
- Vector RAG / LangGraph checkpointing (memory MVP stops before these)

## Recommended next session sequence

1. Execute **internal-roles-pack** (templates only).  
2. Execute **cron-reliability-ops**.  
3. Execute **agent-memory-mvp**.  
4. Revisit **002** only if a concrete data source blocks an agent.  
5. Leave **003 / 004 / 005** until packaging, untrusted network, or external clients become real goals.
