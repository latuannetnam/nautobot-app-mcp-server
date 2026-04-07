---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Planning Pending
status: planning
last_updated: "2026-04-07T09:53:00Z"
last_activity: 2026-04-07 -- v1.2.0 shipped; planning next milestone
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 7
  completed_plans: 5
  percent: 71
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-07 (v1.2.0 milestone shipped)

---

## Current Position

Milestone: v2.0 — Planning Pending
Last activity: 2026-04-07 — v1.2.0 shipped; planning next milestone
Progress: [▓▓▓▓▓▓▓▓▓▓] All milestones complete: v1.0, v1.1.0, v1.2.0

---

## Milestone Summary

**v1.2.0 (Separate Process Refactor) — SHIPPED 2026-04-07**

- Migrated MCP server from embedded Django process (Option A) to standalone FastMCP process (Option B)
- `start_mcp_server.py` + `start_mcp_dev_server.py` management commands as canonical entry points
- MCP server runs on port 8005; `invoke start` launches it automatically via `docker-compose.mcp.yml`
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
| 0 | Project Setup | Complete | 2026-04-01 |
| 1 | MCP Server Infrastructure | Complete | 2026-04-01 |
| 2 | Auth & Sessions | Complete | 2026-04-01 |
| 3 | Core Read Tools | Complete | 2026-04-02 |
| 4 | SKILL.md Package | Complete | 2026-04-02 |
| 5 | MCP Server Refactor | Complete | 2026-04-04 |
| 6 | UAT & Smoke Tests | Complete | 2026-04-04 |
| 7 | Setup | Complete | 2026-04-05 |
| 8 | Infrastructure | Complete | 2026-04-05 |
| 9 | Tool Registration | Complete | 2026-04-05 |
| 10 | Session State | Complete | 2026-04-05 |
| 11 | Auth Refactor | Complete | 2026-04-06 |
| 12 | Bridge Cleanup | Complete | 2026-04-06 |
| 13 | UAT & Validation | Complete | 2026-04-07 |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| v1.0 | 2026-04-02 | Phases 0–4 | MVP shipped |
| v1.1.0 | 2026-04-04 | Phases 5–6 | Embedded FastMCP refactor |
| v1.2.0 | 2026-04-07 | Phases 7–13 | Separate process refactor |

---

## Next Steps

- `/gsd-new-milestone` — plan v2.0 (write tools, Redis sessions, horizontal scaling)

---

*State last updated: 2026-04-07*
