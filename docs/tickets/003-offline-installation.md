# 003 — Offline / On-Prem Installation

**Status:** backlog  
**Date:** 2026-10-04  
**Priority:** DEFER (air-gap later; plan already exists)

## Plan

**DEFER** — do not execute in the internal-first wave. Existing plan (do not rewrite):  
[docs/superpowers/plans/2026-10-04-offline-installation.md](../superpowers/plans/2026-10-04-offline-installation.md)

Priority context: [priority-index](../superpowers/plans/2026-10-04-priority-index.md)

## Summary

Ship Coia Agents as a private Docker appliance for air-gapped / on-prem hosts: `docker load` + image-only Compose, vendored admin assets, Ollama external. Customers do not receive the git repo.

## Scope (Phase A)

- Package `mongo:7`, `postgres:16-alpine`, `coia-agent-harness` via `docker save`
- Customer Compose uses `image:` only
- Vendor admin CDN (fonts, EasyMDE, marked, DOMPurify)
- Document Ollama install/import separately (`OLLAMA_BASE_URL`)
- Air-gap smoke checklist
- No auth in this ticket

## Deferred

- Auth + roles → [004-auth-roles](./004-auth-roles.md)
- External company clients → [005-external-clients](./005-external-clients.md)
