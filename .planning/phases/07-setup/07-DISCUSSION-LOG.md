# Phase 7: Setup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-05
**Phase:** 07-setup
**Mode:** assumptions (codebase-first, no user questioning needed)

---

## Analysis

Phase 7 is pure prerequisite wiring with 3 mechanical tasks. All success criteria are explicit and unambiguous:
- P0-01: `uvicorn >= 0.35.0` added to `pyproject.toml`
- P0-02: All four `NAUTOBOT_DB_*` env vars passed to MCP server service
- P0-03: `--workers 1` warning added to `docs/admin/upgrade.md`

## Key Decision: docker-compose File Placement

| Option | Pros | Cons |
|--------|------|------|
| `docker-compose.base.yml` | Applies to all variants (postgres, mysql, redis) | Slightly more complex base definition |
| `docker-compose.dev.yml` | Dev-only, simpler | Doesn't apply to other compose variants |

**Recommendation:** `docker-compose.base.yml` — all variants need DB vars for the MCP server to connect.

## Assumptions Confirmed

- Phase 7 is the first phase of v1.2.0 — no prior context needed from v1.1.0 that affects these decisions
- No existing MCP server service in docker-compose — this is a new service
- `docs/admin/upgrade.md` exists and is the correct location for v1.2.0 upgrade notes

## Gray Areas: None

All 3 requirements have explicit success criteria with no ambiguity.

## Scope Creep: None

No out-of-scope ideas surfaced during analysis.

---

*Audit trail — Phase 07-setup*
