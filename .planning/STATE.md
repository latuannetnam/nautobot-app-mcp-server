---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: GraphQL-Only Mode
status: active
last_updated: "2026-05-04"
last_activity: 2026-05-04
progress:
  total_phases: 1
  completed_phases: 1
  total_plans: 5
  completed_plans: 5
  percent: 100
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-05-04 (milestone v2.1 GraphQL-Only Mode started)

---

## Current Position

Phase: 18 Complete (GraphQL-Only Mode)
Plan: All 5 plans complete
Status: Phase verified and marked complete
Last activity: 2026-05-04 — Phase 18 complete (v2.1)

---

## Milestone Summary

**v2.0 (GraphQL MCP Tool) — SHIPPED 2026-04-16**

- `graphql_query` MCP tool: arbitrary GraphQL queries via `nautobot.core.graphql.execute_query()`
- `graphql_introspect` MCP tool: returns Nautobot schema as SDL string
- `graphql_validation.py`: `MaxDepthRule` (depth ≤8) and `QueryComplexityRule` (complexity ≤1000)
- Structured error handling: all GraphQL errors return HTTP 200 with `{"data": null, "errors": [...]}`
- UAT: 44/44 passed (T-06 cursor pagination fixed post-ship)
- SKILL.md updated | 103 unit tests pass | No new poetry dependencies
- Phase 17 code review: 10 findings (Critical ×1, High ×1, Medium ×2, Low ×6) all fixed before close

**v1.2.0 (Separate Process Refactor) — SHIPPED 2026-04-07**

- Migrated MCP server from embedded Django process (Option A) to standalone FastMCP process (Option B)
- `start_mcp_server.py` + `start_mcp_dev_server.py` management commands as canonical entry points
- MCP server runs on port 8005; `invoke start` launches it automatically via Docker Compose
- `tool_registry.json` for cross-process plugin discovery (replaces `post_migrate`)
- All 10 core tools async + `sync_to_async(thread_sensitive=True)`
- Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` (no monkey-patching)
- Auth: token from FastMCP headers, cached via `ctx.set_state("mcp:cached_user")`
- Embedded architecture deleted: `view.py`, `server.py`, `urls.py` removed
- UAT: 37/37 passed | Unit tests: 91/91 passed (89 pass, 2 skipped)

**v1.1.0 (MCP Server Refactor) — SHIPPED 2026-04-04**

- Embedded FastMCP bridge: `async_to_sync` + `session_manager.run()`
- Session state on `RequestContext._mcp_tool_state`
- Auth caching on `_cached_user`

**v1.0 MVP — SHIPPED 2026-04-02**

- Core MCP server with 10 read tools, auth, pagination, SKILL.md package

---

## Phase Status

| Phase | Name | Status | Completed |
|---|---|---|---|
| 14 | GraphQL Tool Scaffold | Complete | 2026-04-15 |
| 15 | Introspection & Permissions | Complete | 2026-04-15 |
| 16 | Security Hardening | Complete | 2026-04-16 |
| 17 | UAT & Documentation | Complete | 2026-04-16 |
| 18 | GraphQL-Only Mode | Complete | 2026-05-04 |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| v1.0 | 2026-04-02 | Phases 0–4 | MVP shipped |
| v1.1.0 | 2026-04-04 | Phases 5–6 | Embedded FastMCP refactor |
| v1.2.0 | 2026-04-07 | Phases 7–13 | Separate process refactor |
| v2.0 | 2026-04-16 | Phases 14–17 | GraphQL MCP Tool |

---

## Next Steps

- Milestone v2.1 is complete. Run `/gsd-new-milestone` to define v3.0 scope.
- Candidate features: Write tools, Redis session backend, tool-level field permissions

---

*State last updated: 2026-04-17*
