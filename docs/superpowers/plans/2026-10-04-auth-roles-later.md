# Auth + Roles — Deferred Stub Plan

> **Status:** DEFER — not day-one for trusted LAN internal use.  
> **Ticket:** [004-auth-roles](../../tickets/004-auth-roles.md)  
> **Priority index:** [2026-10-04-priority-index](./2026-10-04-priority-index.md)

**Goal (when needed):** Add authentication and role-based access so the harness/admin is safe beyond a trusted LAN — without blocking current internal value.

**When to pull this forward**

- Admin is reachable beyond trusted LAN, **or**
- A non-operator colleague needs limited access, **or**
- External clients ([005](../../tickets/005-external-clients.md)) become real.

**Architecture (sketch only)**

- Future-friendly seams: keep API routers free of hard-coded “open LAN” assumptions; prefer a single auth dependency (`get_current_user`) added later.
- Start simple: local users + session/JWT **or** reverse-proxy identity headers — decide at kickoff, not now.
- Role matrix v1: `admin` (full) / `operator` (run + view) / `viewer` (read-only). Map later to agents/sources if needed.
- Do **not** require auth for offline appliance packaging ([003](../../tickets/003-offline-installation.md)) unless the network threat model changes.

**Tech Stack (likely):** FastAPI dependencies, secure cookies or bearer tokens, password hashing (or SSO later), Mongo `users` collection.

## Global Constraints (when executed)

- Trusted-LAN internal use must keep working (dev escape hatch / bootstrap admin).
- No multi-tenant external clients in the first auth ship — that is ticket 005.
- Single worker still applies; auth must not assume sticky multi-instance sessions without design.

---

## When we need it — checklist (not scheduled)

- [ ] **Decide identity:** local users vs SSO / reverse-proxy.
- [ ] **Write full writing-plans doc** with checkbox tasks (replace this stub).
- [ ] **Model:** `User`, roles, bootstrap admin via env.
- [ ] **Protect** mutating admin APIs; keep `/health` policy explicit.
- [ ] **Admin UI:** login gate; hide create/pause for viewers.
- [ ] **Tests:** unauthorized → 401/403; role matrix smoke.
- [ ] **Docs:** LAN deploy note + “auth off for local demo” flag if kept.

## Non-goals now

- Implementing product code for auth in the current priority wave.
- Blocking tickets 001 / 006-slice / 007-MVP on this work.
