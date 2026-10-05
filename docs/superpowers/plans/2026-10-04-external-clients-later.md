# External Company Clients — Deferred Stub Plan

> **Status:** DEFER — after internal trust + auth.  
> **Ticket:** [005-external-clients](../../tickets/005-external-clients.md)  
> **Depends on:** [004 auth stub](./2026-10-04-auth-roles-later.md)  
> **Priority index:** [2026-10-04-priority-index](./2026-10-04-priority-index.md)

**Goal (when needed):** Let external company clients use the platform without treating today’s internal two-company LAN deploy as multi-tenant SaaS.

**When to pull this forward**

- Auth ([004](../../tickets/004-auth-roles.md)) exists, **and**
- There is a real external client (not just a boss demo), **and**
- Data isolation requirements are clear.

**Architecture (sketch only)**

- Tenancy boundary: per-client agent/source/conversation isolation (likely `tenant_id` on Mongo docs).
- Auth roles alone are not enough — need data scoping in repositories.
- Offline appliance ([003](./2026-10-04-offline-installation.md)) may remain single-tenant per host; external clients might be a different deploy shape.

## When we need it — checklist

- [ ] Confirm product shape: shared host multi-tenant vs one appliance per client.
- [ ] Write a full implementation plan (replace this stub).
- [ ] Add tenancy to models + repo queries.
- [ ] Admin UX for client/tenant switching (admin-only).
- [ ] Isolation tests (client A cannot read client B).

## Non-goals now

- Any product code for external clients.
- Paid platform / Neo-style partner portal work.
