# 004 — Auth with Roles

**Status:** backlog  
**Date:** 2026-10-04  
**Priority:** DEFER (Phase B / when LAN trust is not enough)

## Plan

**DEFER** — stub only until needed:  
[docs/superpowers/plans/2026-10-04-auth-roles-later.md](../superpowers/plans/2026-10-04-auth-roles-later.md)

Priority context: [priority-index](../superpowers/plans/2026-10-04-priority-index.md)

## Summary

Add authentication and role-based access to the harness / admin console. Not part of day-one internal trusted-LAN use; keep design future-friendly.

## Notes

- Depends on product decisions (identity provider, local users vs SSO, role matrix).
- Must not block internal roles / cron reliability / memory MVP work.
- Offline appliance ([003](./003-offline-installation.md)) also deferred; auth is independent and later.
