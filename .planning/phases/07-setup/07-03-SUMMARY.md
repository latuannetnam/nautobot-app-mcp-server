---
phase: 07
plan: 03
subsystem: docs
tags:
  - documentation
  - upgrade
  - deployment
requires:
  - P0-03
provides: []
affects: []
tech-stack:
  added: []
  patterns:
    - Material for MkDocs admonition syntax (!!! warning)
    - Deployment documentation for systemd worker process requirement
key-files:
  created: []
  modified:
    - docs/admin/upgrade.md
key-decisions:
  - context: Why --workers 1 is required
    decision: MCP server uses in-memory session state for progressive tool discovery; multi-worker setups cause session loss
    rationale: Sessions stored on individual worker processes are not shared; requests routed to different workers lose session context
  - context: Where to document the requirement
    decision: docs/admin/upgrade.md — appropriate for operators upgrading or deploying the app
    rationale: upgrade.md is the standard Nautobot app location for deployment requirements
  - context: Future horizontal scaling
    decision: Defer Redis session backend to v2.0
    rationale: Simplicity first; in-memory sessions sufficient for single-worker deployments
requirements-completed:
  - P0-03
duration: "< 1 min"
completed: "2026-04-05"
---

# Phase 07 Plan 03: Document `--workers 1` Requirement in upgrade.md — Summary

**Task:** Add `--workers 1` warning section to `docs/admin/upgrade.md`

**Commit:** `5067544`

**Start:** 2026-04-05 | **End:** 2026-04-05

---

## What Was Done

Appended a new top-level `## Worker Process Requirement` section to `docs/admin/upgrade.md` immediately after the existing `## Upgrade Guide` block, using a Material for MkDocs `!!! warning` admonition.

**Section structure:**
- `!!! warning "Single Worker Required"` — top-level admonition flagging `--workers 1`
- `### Rationale` — explains in-memory session state; sessions lost when `N > 1`
- `### Production Deployment` — systemd `ExecStart` example with `--workers 1`
- `### Development` — notes that `uvicorn.run(reload=True)` always uses single worker
- `### Future: Horizontal Scaling` — v2.0 deferred: Redis session backend required for `--workers N > 1`

---

## Verification (all passed)

| Criterion | Result |
|-----------|--------|
| `grep "workers" docs/admin/upgrade.md` matches `--workers 1` | PASS |
| `grep "in-memory" docs/admin/upgrade.md` matches `in-memory` | PASS |
| `grep "progressive tool discovery" docs/admin/upgrade.md` matches feature name | PASS |
| `grep "v2.0" docs/admin/upgrade.md` matches deferred Redis promise | PASS |
| Admonition uses `!!! warning` syntax | PASS (Material for MkDocs) |
| `grep "Single Worker Required" docs/admin/upgrade.md` matches admonition title | PASS |

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Files Modified

| File | Change |
|------|--------|
| `docs/admin/upgrade.md` | +31 lines: new Worker Process Requirement section |

---

## Decisions

1. **Why `--workers 1` is required:** MCP server stores session state in-memory for progressive tool discovery; multi-worker setups route requests to different processes, losing session context.

2. **Where to document:** `docs/admin/upgrade.md` — standard Nautobot app location for deployment requirements and upgrade procedures.

3. **Future horizontal scaling:** Redis session backend deferred to v2.0 — simplicity first; in-memory sessions sufficient for single-worker deployments.

---

## Phase Status

Phase 7 (Setup) — all 3 plans complete.

- [x] 07-01: uvicorn explicit dependency in pyproject.toml
- [x] 07-02: docker-compose passes NAUTOBOT_DB_* env vars to MCP server service
- [x] 07-03: --workers 1 documented in docs/admin/upgrade.md

**Phase exit gate satisfied:** all three P0 requirements (P0-01, P0-02, P0-03) complete.

---

## Next

Ready for Phase 08: Infrastructure — Management Commands (`start_mcp_server.py` + `start_mcp_dev_server.py`).
