---
gsd_state_version: 1.0
milestone: v1.2.0
milestone_name: Milestone Goal
status: executing
last_updated: "2026-04-05T12:00:00Z"
last_activity: 2026-04-05
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 6
  completed_plans: 4
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-05 (Phase 09 context gathered — ready to plan)

---

## Current Position

Phase: 09 (tool-registration-refactor) — EXECUTING
Plan: 4 of 6
Status: Ready to execute
Last activity: 2026-04-05

Progress: [▓▓▓▓▓▓▓▓▓▓] Phase 8 complete (4/4 sub-plans); Phase 9 executing (4/6 plans)

**Phase 09-01 completed** (`09-01-SUMMARY.md`):

- `schema.py`: `func_signature_to_input_schema()` auto-derives JSON Schema from Python type hints
- `@register_tool` decorator in `mcp/__init__.py`: ergonomic wrapper with auto-schema
- All 10 core tools in `core.py` converted to `@register_tool` (net: 54 insertions, 245 deletions)
- All 80 MCP tests pass

**Phase 09-02 completed** (`09-PLAN-02-SUMMARY.md`):

- `register_all_tools_with_mcp(mcp)` in `mcp/__init__.py`: iterates `MCPToolRegistry.get_all()` and calls `mcp.tool(func, name, description)` for each tool; added to `__all__`
- `mcp/commands.py` STEP 4: replaced placeholder with real wiring — import `core` (side-effect registration) then call `register_all_tools_with_mcp(mcp)`
- 79/80 MCP tests pass; 1 pre-existing failure in `test_signal_integration.py`

**Phase 09-04 completed** (`09-PLAN-04-SUMMARY.md`):

- Confirmed all 10 core read tools use `async def` + `sync_to_async(thread_sensitive=True)` pattern
- `grep -c "^async def _"` returns 10
- `grep -c "sync_to_async(query_utils._sync_"` returns 10
- No module-level Django model imports in `core.py`
- `ToolContext` imported from `fastmcp.server.context`

---

## Accumulated Context

**v1.0.0 completed (Phases 0–4):** Core MCP server, auth, 10 read tools, SKILL.md package.

**v1.1.0 completed (Phases 5–6):** Embedded FastMCP bridge refactor — `async_to_sync` + `session_manager.run()` replaces `asyncio.run()`; session state on `RequestContext._mcp_tool_state`; auth caching on `_cached_user`; progressive disclosure via `mcp._list_tools_mcp` override.

**v1.2.0 active (Phases 7–13):** Separate-process migration (Option A → Option B).

**Phase 08 decisions to carry forward:**

- FastMCP 3.x: `stateless_http` passed at `mcp.run()` / `mcp.http_app()` — NOT constructor
- Two-phase import pattern: `nautobot.setup()` before relative imports
- `create_app()` returns `(FastMCP, host, port)` tuple
- `reload_dirs` scoped to `nautobot_app_mcp_server/` package root (computed via `Path(__file__).resolve().parents[3]`)
- `connection.ensure_connection()` before `nautobot.setup()` for fast DB failure detection

**Reference project (`nautobot-app-mcp`):**

- Separate process via `nautobot-server start_mcp_server`
- `FastMCP("Nautobot MCP Server", host, port).run(transport="http")`
- `nautobot.setup()` called once at worker startup
- `@register_tool` decorator: dual registration (in-memory dict + FastMCP `.tool()` wiring)
- Tools: async wrapper → `sync_to_async(get_sync_fn())` → Django ORM
- Session state: normal `dict` keyed by `session_id`
- `tool_registry.json` for cross-process plugin discovery
- No auth (assumed trusted network)

---

## Phase Status

| Phase | Name | Status | Start Date | End Date | Blockers |
|---|---|---|---|---|---|
| Phase 7 | Setup | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 8 | Infrastructure | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 9 | Tool Registration | In Progress | 2026-04-05 | — | Phase 8 |
| Phase 10 | Session State | Not Started | — | — | Phase 9 |
| Phase 11 | Auth Refactor | Not Started | — | — | Phase 10 |
| Phase 12 | Bridge Cleanup | Not Started | — | — | Phase 11 |
| Phase 13 | UAT & Validation | Not Started | — | — | Phase 12 |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| 0.1.0 | 2026-04-01 | Phases 0–4 | v1.0 shipped |
| 0.1.0 | 2026-04-04 | Phases 5–6 | v1.1.0 shipped |
| 0.1.0 | 2026-04-05 | Phase 7 | v1.2.0 Phase 7 setup complete |
| 0.1.0 | 2026-04-05 | Phase 8 | v1.2.0 Phase 8 infrastructure complete (`9215257`) |

---

*State last updated: 2026-04-05*
