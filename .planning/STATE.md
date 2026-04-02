---
gsd_state_version: 1.0
milestone: v1.0.0
milestone_name: milestone
status: unknown
last_updated: "2026-04-02T06:49:29.290Z"
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 5
  completed_plans: 4
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-02 (Phase 3 Plans 01+02+03 executed — pagination + 10 core tools + search_by_name + tests complete)
**Roadmap:** `.planning/ROADMAP.md`

---

## Current Phase

**Phase 3 — Core Read Tools** (All 3 plans complete — Plans 01+02+03 executed)

---

## Phase Status

| Phase | Name | Status | Start Date | End Date | Blockers |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | Not Started | — | — | None |
| Phase 1 | MCP Server Infrastructure | **Executed** | 2026-04-01 | 2026-04-01 | Phase 0 |
| Phase 2 | Authentication & Sessions | **Executed** | 2026-04-01 | 2026-04-01 | Phase 1 |
| Phase 3 | Core Read Tools | **In Progress** | 2026-04-02 | — | Phase 1 |
| Phase 4 | SKILL.md Package | Not Started | — | — | Phases 1–3 |

---

## Requirements Progress

**v1.0.0 total: 47 requirements**

| Phase | Name | Requirements | Completed | In Progress | Pending |
|---|---|---|---|---|---|
| Phase 0 | Project Setup | 4 | 0 | 0 | 4 |
| Phase 1 | MCP Server Infrastructure | 14 | **14** | 0 | 0 |
| Phase 2 | Authentication & Sessions | 10 | **10** | 0 | 0 |
| Phase 3 | Core Read Tools | 15 | **15** | 0 | 0 |
| Phase 4 | SKILL.md Package | 3 | 0 | 0 | 3 |
| **Total** | | **47** | **39** | **0** | **8** |

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
| Session storage | FastMCP session dict (`session["enabled_scopes"]`, `session["enabled_searches"]`) | D-19 (Phase 2) |
| Progressive disclosure | `@mcp.list_tools()` override with `ToolContext` | D-20 (Phase 2) |
| Scope hierarchy | `startswith(f"{scope}.")` prefix matching | D-21 (Phase 2) |
| Auth log levels | No token → `logger.warning`, Invalid → `logger.debug` | D-22 (Phase 2) |
| MCPSessionState | Thin dataclass wrapper over FastMCP session dict | D-26 (Phase 2) |
| Core tools always | `registry.get_core_tools()` always included in list_tools_handler | D-27 (Phase 2) |

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

## Phase 2 — Decisions Made During Execution

| Decision | Choice | Rationale |
|---|---|---|
| `_setup_mcp_app()` separation | Extracted from `get_mcp_app()` as separate helper | Allows `mcp` instance to be accessible for decorator registration |
| Session tools registration | Both `@mcp.tool()` decorator AND `register_mcp_tool(tier="core")` | FastMCP needs decorator; MCPToolRegistry needs explicit `register_mcp_tool()` call |
| MCPSessionState as dataclass | Stored in FastMCP session dict via `from_session`/`apply_to_session` | Clean separation; round-trip serializable to FastMCP session |
| `get_user_from_request` in `__init__.py` | Exported from `mcp/__init__.py` alongside `register_mcp_tool` | Third-party apps call it to get Nautobot user in their tool handlers |

---

## Phase 3 — Decisions Made During Execution

| Decision | Choice | Rationale |
|---|---|---|
| `sync_to_async` + query_utils split | Async handlers in `core.py` import `query_utils` for `_sync_*` helpers | Avoids circular imports; ORM stays in sync code |
| `_looks_like_uuid()` regex | `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` | Works for both UUID and non-UUID identifiers |
| `search_by_name` implementation | Sequential per-model queries + in-memory merge | Union would lose model type without discriminator column |
| `interface_get` ip_addresses | Flat `{pk, address}` dicts | Deep serialization deferred to `interface_get` itself |
| `__init__.py` triggers `core` import | `from nautobot_app_mcp_server.mcp.tools import core` | Ensures all `register_mcp_tool()` calls fire on package load |
| `paginate_queryset_async` in `__all__` | Added despite plan omission | Public API needed for tests and future tools |

### Phase 3 Plan 03 — Decisions Made During Execution

| Decision | Choice | Rationale |
|---|---|---|
| AND filter with `functools.reduce` | `functools.reduce(op.and_, [Q(...) for t in terms])` | `op.and_()` requires exactly 2 positional args; `reduce` handles any list length |
| search_by_name cursor | Manual pagination over combined list; cursor = `base64(f"{model}.{pk}")` | No DB cursor across models; manual offset over sorted list |
| Test serializer patching | Patch `serialize_device_with_interfaces` and `serialize_interface` | `model_to_dict()` fails with chained MagicMock attributes (MagicMock != str) |
| `restrict()` action assertion | `kwargs.get("action")` not positional args | Django ORM passes `action` as keyword arg, not positional |

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
| 0.1.0-dev | 2026-04-01 | Phase 2 executed | All 6 tasks complete; 7 commits (c8469cb→750878f) |
| 0.1.0-dev | 2026-04-02 | Phase 3 Plans 01+02 executed | Pagination + 10 core read tools; commits (e861e2b→033728b) |
| 0.1.0-dev | 2026-04-02 | Phase 3 Plan 03 executed | search_by_name + test_core_tools.py (31 tests); commits (84f9c03→9948527) |
| 0.1.0-dev | 2026-04-02 | Phase 3 Plan 01 executed | Pagination layer (PAGE-01→05); commits (5b3dca1, 0341f98) |

---

*State last updated: 2026-04-02*
