# 007 — Agent Memory

**Status:** active (MVP)
**Date:** 2026-10-04
**Priority:** active — after roles pack + cron reliability slice

## Plan

**ACTIVE (MVP)** — chat window/summary + cron last-run summary memory:
[docs/superpowers/plans/2026-10-04-agent-memory-mvp.md](../superpowers/plans/2026-10-04-agent-memory-mvp.md)

Priority context: [priority-index](../superpowers/plans/2026-10-04-priority-index.md)

## Today (demo OK)

- Full chat transcript as STM
- Cron runs are stateless
- Files / SQL as informal LTM
- No truncation, summaries, RAG, or checkpoints

## Demo risk

- Long chats blow context
- Cron amnesia unless prompts / files / DB carry state

## Must-do (MVP in plan)

- [x] Chat history window + rolling summaries
- [x] Optional episodic memory for cron/manual runs (last N run summaries)

## Later (not in MVP plan)

- [ ] Explicit memory tools or workspace conventions (save / recall)
- [ ] Optional vector RAG over files / past reports
- [ ] LangGraph checkpointing if multi-turn durability needed

## Non-goal (this phase)

Full Neo-style memory platform.
