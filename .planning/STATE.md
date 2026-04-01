# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-01 (Phase 1 context gathered)
**Roadmap:** `.planning/ROADMAP.md`

---

## Current Phase

**Phase 0 — Project Setup** (not started)

---

## Phase Status

| Phase | Name | Status | Start Date | End Date | Blockers |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | Not Started | — | — | None |
| Phase 1 | MCP Server Infrastructure | Context Gathered | — | — | Phase 0 |
| Phase 2 | Authentication & Sessions | Not Started | — | — | Phase 1 |
| Phase 3 | Core Read Tools | Not Started | — | — | Phase 1 |
| Phase 4 | SKILL.md Package | Not Started | — | — | Phases 1–3 |

---

## Requirements Progress

**v1.0.0 total: 47 requirements**

| Phase | Name | Requirements | Completed | In Progress | Pending |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | 4 | 0 | 0 | 4 |
| Phase 1 | MCP Server Infrastructure | 14 | 0 | 0 | 14 |
| Phase 2 | Authentication & Sessions | 10 | 0 | 0 | 10 |
| Phase 3 | Core Read Tools | 15 | 0 | 0 | 15 |
| Phase 4 | SKILL.md Package | 3 | 0 | 0 | 3 |
| **Total** | | **47** | **0** | **0** | **47** |

---

## Blocker Log

| Blocker | Phase | Severity | Status | Resolution |
|---|---|---|---|---|
| FOUND-01 (missing deps) | Phase 0 | Critical | Pending | Add `mcp`, `fastmcp`, `asgiref` to `pyproject.toml` |
| FOUND-03 (package name) | Phase 0 | Critical | Pending | Rename all imports to `nautobot_app_mcp_server` |
| FOUND-04 (base_url) | Phase 0 | High | Pending | Set `base_url = "nautobot-app-mcp-server"` in `__init__.py` |

---

## Key Decisions Resolved

| Decision | Resolution | Source |
|---|---|---|
| Package name | `nautobot_app_mcp_server` | FOUND-03 (Phase 0) |
| `base_url` | `nautobot-app-mcp-server` | FOUND-04 (Phase 0) |
| Architecture | Option A — FastMCP ASGI app embedded via `plugin_patterns` + `WsgiToAsgi` | FOUND-05 (Phase 1) |
| ASGI bridge | `asgiref.wsgi.WsgiToAsgi` (NOT `django-starlette`) | FOUND-05 (Phase 1) |
| MCP SDK | `mcp ^1.26.0` + `fastmcp ^3.2.0` | FOUND-01 (Phase 0) |
| Pagination | Cursor-based with `base64(str(pk))` cursor | PAGE-04 (Phase 3) |
| Auth | Token from MCP request context, `.restrict(user, "view")` | AUTH-03 (Phase 2) |
| Sessions | In-memory per `Mcp-Session-Id` (NOT Redis) | SESS-02 (Phase 2) |
| SKILL.md | Separate `nautobot-mcp-skill/` pip package | SKILL-01 (Phase 4) |

---

## Open Questions

| Question | Impact | Priority |
|---|---|---|
| How to handle `search_by_name` cross-model complexity? | May need deferred implementation or simplified v1 scope | High |
| Multi-worker gunicorn session loss — acceptable for v1? | Yes, document as known limitation | Low |
| Should `nautobot-mcp-skill` be a monorepo sub-package or separate repo? | Keep in same repo for now | Low |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| 0.1.0-dev | 2026-04-01 | All 5 phases defined | Initial roadmap created |

---

*State last updated: 2026-04-01*
