---
gsd_state_version: 1.0
milestone: v1.2.0
milestone_name: separate-process-refactor
status: defining_roadmap
last_updated: "2026-04-05"
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 28
  completed_plans: 0
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-05 (v1.2.0 roadmap created — Phases 7–13)

---

## Current Position

Phase: 7 of 7 (Setup — roadmap defining complete)
Plan: —
Status: Ready to plan
Last activity: 2026-04-05 — v1.2.0 ROADMAP.md created; 27 requirements mapped to 7 phases (7–13)

Progress: [░░░░░░░░░░] 0%

---

## Accumulated Context

**v1.0.0 completed (Phases 0–4):** Core MCP server, auth, 10 read tools, SKILL.md package.

**v1.1.0 completed (Phases 5–6):** Embedded FastMCP bridge refactor — `async_to_sync` + `session_manager.run()` replaces `asyncio.run()`; session state on `RequestContext._mcp_tool_state`; auth caching on `_cached_user`; progressive disclosure via `mcp._list_tools_mcp` override.

**v1.2.0 active (Phases 7–13):** Separate-process migration (Option A → Option B).

**Reference project (`nautobot-app-mcp`):**
- Separate process via `nautobot-server start_mcp_server`
- `FastMCP("Nautobot MCP Server", host, port).run(transport="sse")`
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
| Phase 7 | Setup | Not Started | — | — | None |
| Phase 8 | Infrastructure | Not Started | — | — | Phase 7 |
| Phase 9 | Tool Registration | Not Started | — | — | Phase 8 |
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
| 0.1.0 | 2026-04-05 | Phase 7–13 | v1.2.0 roadmap created |

---

*State last updated: 2026-04-05*
