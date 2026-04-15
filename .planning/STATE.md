---
gsd_state_version: 1.0
milestone: v1.2.0
milestone_name: Archived
status: executing
last_updated: "2026-04-15T12:34:42.619Z"
last_activity: 2026-04-15 -- Phase 14 execution started
progress:
  total_phases: 1
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-15 (v2.0 roadmap created)

---

## Current Position

Phase: 14 (graphql-tool-scaffold) — EXECUTING
Plan: 1 of 1
Status: Executing Phase 14
Last activity: 2026-04-15 -- Phase 14 execution started

---

## Milestone Summary

**v2.0 (GraphQL MCP Tool) — PLANNED**

- `graphql_query` MCP tool wrapping `nautobot.core.graphql.execute_query()` with `sync_to_async(thread_sensitive=True)`
- `graphql_introspect` companion tool returning GraphQL schema SDL
- Auth propagated to GraphQL execution context via `get_user_from_request()`
- Query depth limit (≤8) and complexity limit (≤1000) to prevent DoS
- Structured error handling — no HTTP 500s for GraphQL errors
- 15 unit tests across 4 phases; UAT smoke test P-09 + full suite T-37+
- SKILL.md updated with `graphql_query` and `graphql_introspect` documentation

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
- FastMCP/MCP SDK `outputSchema` conflict fixed via `output_schema=None` in source

**v1.1.0 (MCP Server Refactor) — SHIPPED 2026-04-04**

- Embedded FastMCP bridge: `async_to_sync` + `session_manager.run()`
- Session state on `RequestContext._mcp_tool_state`
- Auth caching on `_cached_user`
- Progressive disclosure via `mcp._list_tools_mcp` override

**v1.0 MVP — SHIPPED 2026-04-02**

- Core MCP server with 10 read tools, auth, pagination, SKILL.md package

---

## Phase Status

| Phase | Name | Status | Completed |
|---|---|---|---|
| 14 | GraphQL Tool Scaffold | Planned | — |
| 15 | Introspection & Permissions | Planned | — |
| 16 | Security Hardening | Planned | — |
| 17 | UAT & Documentation | Planned | — |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| v1.0 | 2026-04-02 | Phases 0–4 | MVP shipped |
| v1.1.0 | 2026-04-04 | Phases 5–6 | Embedded FastMCP refactor |
| v1.2.0 | 2026-04-07 | Phases 7–13 | Separate process refactor |
| v2.0 | 2026-04-15 | Phases 14–17 | GraphQL MCP Tool (planned) |

---

## Next Steps

- Begin Phase 14 — GraphQL tool scaffold
- Implement `graphql_query` MCP tool in `mcp/tools/graphql_tool.py`
- Write unit tests covering auth propagation, valid query, invalid query, variables injection

---

*State last updated: 2026-04-15*
