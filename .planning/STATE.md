# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-01 (Phase 1 executed — all 11 tasks complete)
**Roadmap:** `.planning/ROADMAP.md`

---

## Current Phase

**Phase 1 — MCP Server Infrastructure** (Executed)

---

## Phase Status

| Phase | Name | Status | Start Date | End Date | Blockers |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | Not Started | — | — | None |
| Phase 1 | MCP Server Infrastructure | **Executed** | 2026-04-01 | 2026-04-01 | Phase 0 |
| Phase 2 | Authentication & Sessions | Not Started | — | — | Phase 1 |
| Phase 3 | Core Read Tools | Not Started | — | — | Phase 1 |
| Phase 4 | SKILL.md Package | Not Started | — | — | Phases 1–3 |

---

## Requirements Progress

**v1.0.0 total: 47 requirements**

| Phase | Name | Requirements | Completed | In Progress | Pending |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | 4 | 0 | 0 | 4 |
| Phase 1 | MCP Server Infrastructure | 14 | **14** | 0 | 0 |
| Phase 2 | Authentication & Sessions | 10 | 0 | 0 | 10 |
| Phase 3 | Core Read Tools | 15 | 0 | 0 | 15 |
| Phase 4 | SKILL.md Package | 3 | 0 | 0 | 3 |
| **Total** | | **47** | **14** | **0** | **33** |

---

## Blocker Log

| Blocker | Phase | Severity | Status | Resolution |
|---|---|---|---|---|
| FOUND-01 (missing deps) | Phase 0 | Critical | **Resolved** | `fastmcp = "^3.2.0"` added to `pyproject.toml` |
| FOUND-03 (package name) | Phase 0 | Critical | **Resolved** | All imports use `nautobot_app_mcp_server`; DESIGN.md updated |
| FOUND-04 (base_url) | Phase 0 | High | **Resolved** | `base_url = "nautobot-app-mcp-server"` in `__init__.py` |

---

## Key Decisions Resolved

| Decision | Resolution | Source |
|---|---|---|
| Package name | `nautobot_app_mcp_server` | FOUND-03 (Phase 0) |
| `base_url` | `nautobot-app-mcp-server` | FOUND-04 (Phase 0) |
| Architecture | Option A — FastMCP ASGI app embedded via `plugin_patterns` + `WsgiToAsgi` | FOUND-05 (Phase 1) |
| ASGI bridge | `asgiref.wsgi.WsgiToAsgi` (NOT `async_to_sync`) | FOUND-05 (Phase 1) |
| MCP SDK | `fastmcp = "^3.2.0"` (pinned in pyproject.toml) | FOUND-01 (Phase 0) |
| Pagination | Cursor-based with `base64(str(pk))` cursor | PAGE-04 (Phase 3) |
| Auth | Token from MCP request context, `.restrict(user, "view")` | AUTH-03 (Phase 2) |
| Sessions | In-memory per `Mcp-Session-Id` (NOT Redis) | SESS-02 (Phase 2) |
| SKILL.md | Separate `nautobot-mcp-skill/` pip package | SKILL-01 (Phase 4) |
| App config | Single-file (`__init__.py` only, no `apps.py`) | Phase 1 execution |

---

## Phase 1 — Decisions Made During Execution

| Decision | Choice | Rationale |
|---|---|---|
| `__init__.py` vs `apps.py` | Single-file in `__init__.py` | Simpler; no separate `apps.py` needed for Phase 1 |
| `urls` attribute | `urls = ["nautobot_app_mcp_server.urls"]` in `NautobotAppMcpServerConfig` | Nautobot discovers plugin URLs via `PLUGINS` setting |
| `post_migrate` signal guard | `if app_config.name == "nautobot_app_mcp_server"` | Ensures registration runs only once for this app |
| Registry methods | `get_all`, `get_core_tools`, `get_by_scope`, `fuzzy_search` (no `get_by_tier` separate) | `get_core_tools()` covers core; `get_by_scope("core")` is equivalent |
| Lazy factory safety | Module-level `_mcp_app: Starlette | None = None` with global check | Double-checked locking not needed (Python GIL + module-level None) |

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
| 0.1.0-dev | 2026-04-01 | Phase 1 planned | Initial roadmap created |
| 0.1.0-dev | 2026-04-01 | Phase 1 executed | All 11 tasks complete; commit 13ca60e |

---

*State last updated: 2026-04-01*
