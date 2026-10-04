# 006 — Production Monitoring / Governance

**Status:** active (thin slice)
**Date:** 2026-10-04
**Priority:** active — away-monitoring slice only

## Plan

**ACTIVE (thin slice)** — stuck runs, clearer Activity/Executions, richer healthcheck — not Neo governance:
[docs/superpowers/plans/2026-10-04-cron-reliability-ops.md](../superpowers/plans/2026-10-04-cron-reliability-ops.md)

Priority context: [priority-index](../superpowers/plans/2026-10-04-priority-index.md)

## Context

Neo Agents markets control and governance: connectors, permissions, budgets, human-in-the-loop (HITL), audit, provenance. Coia is an agent harness — different product shape. This ticket tracks what we already cover for company use and what to add next, without chasing full Neo parity.

## What Coia has today

- Activity feed
- Executions view
- Agent status
- Chat unread indicators
- System health / usage
- Pause agents
- Single worker process

## Company-use playbook (now)

1. Run via Docker on LAN
2. Pause unused agents
3. Watch Activity + Executions
4. Prefer read-only data sources
5. Cap API keys / prefer Ollama locally
6. No outbound tool use until auth lands ([004](./004-auth-roles.md))

## Ranked next checklist

1. ~~Auth + roles first~~ — **deferred** for trusted LAN; see [004](./004-auth-roles.md)
2. **Now (thin slice):** stuck-run detection, Activity/Executions clarity, healthcheck counts — see plan above
3. Metrics / alerts later (fail rate, latency, LLM errors) — beyond thin slice
4. Audit trail
5. Budgets / rate limits
6. HITL for dangerous tools
7. Multi-instance workers
8. External clients later — [005-external-clients](./005-external-clients.md)

## Thin-slice delivery checklist

- [x] Detect and recover stuck runs
- [x] Show run age and stuck state in Activity and Executions
- [x] Report running/stuck counts and degraded state from `/health`
- [ ] Auth and roles
- [ ] Budgets and rate limits
- [ ] Human-in-the-loop approval
- [ ] Multi-instance workers

## Non-goal (for now)

Full feature parity with Neo Agents’ governance brochure.
