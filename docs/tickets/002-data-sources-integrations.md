# 002 — Data Sources / Integrations Backlog

**Status:** in progress  
**Date:** 2026-10-04

## Plan

**BACKLOG / as needed** — no dedicated new execution plan. Continue this checklist when a live internal agent needs a source.  
See priority notes: [priority-index](../superpowers/plans/2026-10-04-priority-index.md) (rank 4).

## Current state

| Capability | Notes |
| --- | --- |
| SQL | Postgres, MySQL, SQLite (+ SSH) |
| Files | Uploads + DuckDB `run_file_sql` for CSV/TSV/XLSX |
| MongoDB | Config + read-only query tools (+ SSH) |
| REST | GET-first `http_get` with path allowlist / SSRF guards |
| HTML reports | Supported |
| Image gen | Supported |

## Ranked next steps

- [x] 1. MongoDB query tool — **S**
- [x] 2. CSV/Excel queryable — **S–M**
- [ ] 3. MSSQL engine — **S–M**
- [x] 4. Generic REST API source (GET-first) — **M**
- [ ] 5. Google Sheets read — **M**
- [ ] 6. S3/MinIO read — **M**
- [ ] 7. Cron outbound webhook — **S–M**
- [ ] 8. Slack notify — **M**
- [ ] 9. Elasticsearch/OpenSearch — **M**
- [ ] 10. CRM read (HubSpot / Salesforce) — **L**

## Defer

- Write-to-DB
- Email send
- Broad SaaS catalog before REST + OAuth foundations
- Roles that need send/CRM until tools exist → see [001-agent-roles-roadmap](./001-agent-roles-roadmap.md)
