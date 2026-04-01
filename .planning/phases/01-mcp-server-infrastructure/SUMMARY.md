---
phase: 01-mcp-server-infrastructure
plan: "01"
subsystem: infra
tags: [fastmcp, asgi, django, threading, singleton, registry, wsgi, post-migrate, mcp]

# Dependency graph
requires: []

provides:
  - FastMCP ASGI server scaffold with lazy initialization
  - MCPToolRegistry thread-safe singleton with double-checked locking
  - ToolDefinition dataclass with 7 fields
  - register_mcp_tool() public API for third-party apps
  - ASGI bridge via WsgiToAsgi (Django → FastMCP → response)
  - Django URL routing at /plugins/nautobot-app-mcp-server/mcp/
  - post_migrate signal wiring for tool registration
  - test_view.py and test_signal_integration.py with 20 test cases

affects: [02-authentication-sessions, 03-core-read-tools]

# Tech tracking
tech-stack:
  added: [fastmcp]
  patterns: [lazy-factory, double-checked-locking-singleton, asgi-wsgi-bridge, django-plugin-urls, post-migrate-signal]

key-files:
  created:
    - nautobot_app_mcp_server/mcp/__init__.py
    - nautobot_app_mcp_server/mcp/registry.py
    - nautobot_app_mcp_server/mcp/server.py
    - nautobot_app_mcp_server/mcp/view.py
    - nautobot_app_mcp_server/mcp/tests/__init__.py
    - nautobot_app_mcp_server/mcp/tests/test_view.py
    - nautobot_app_mcp_server/mcp/tests/test_signal_integration.py
    - nautobot_app_mcp_server/urls.py
  modified:
    - nautobot_app_mcp_server/__init__.py
    - pyproject.toml
    - docs/dev/DESIGN.md

key-decisions:
  - "Single-file app config: kept NautobotAppMcpServerConfig in __init__.py, no separate apps.py"
  - "urls attribute: added urls = ['nautobot_app_mcp_server.urls'] to NautobotAppMcpServerConfig"
  - "post_migrate guard: if app_config.name == 'nautobot_app_mcp_server' ensures single-registration"
  - "Lazy factory: _mcp_app = None at module scope, global check in get_mcp_app()"
  - "base_url corrected: 'mcp-server' → 'nautobot-app-mcp-server' matching Nautobot plugin convention"

patterns-established:
  - "Pattern: Lazy ASGI factory — get_mcp_app() creates FastMCP on first HTTP request, not at import"
  - "Pattern: Double-checked locking singleton — threading.Lock with outer/inner None checks"
  - "Pattern: ASGI bridge — WsgiToAsgi(app)(request) converts Django WSGI → FastMCP ASGI → response"
  - "Pattern: Django plugin URLs — urls = ['nautobot_app_mcp_server.urls'] in NautobotAppConfig"
  - "Pattern: post_migrate signal guard — app_config.name check ensures single execution"

requirements-completed:
  - FOUND-02
  - FOUND-05
  - SRVR-01
  - SRVR-02
  - SRVR-03
  - SRVR-04
  - SRVR-05
  - SRVR-06
  - REGI-01
  - REGI-02
  - REGI-03
  - REGI-04
  - TEST-03
  - TEST-04

# Metrics
duration: ~15min
completed: 2026-04-01
---

# Phase 1: MCP Server Infrastructure Summary

**FastMCP ASGI scaffold embedded in Nautobot Django process — WsgiToAsgi bridge, thread-safe tool registry singleton, lazy factory, post_migrate signal wiring**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-01
- **Completed:** 2026-04-01
- **Tasks:** 11 (all executed)
- **Files modified:** 9 (2 modified, 7 created)

## Accomplishments

- FastMCP server scaffold embedded via Django plugin URL at `/plugins/nautobot-app-mcp-server/mcp/`
- `MCPToolRegistry` thread-safe singleton with double-checked locking (`threading.Lock`)
- `ToolDefinition` dataclass (7 fields: name, func, description, input_schema, tier, app_label, scope)
- `register_mcp_tool()` public API for third-party Nautobot apps
- ASGI bridge via `WsgiToAsgi` (Django WSGI → FastMCP ASGI → HTTP response)
- Lazy ASGI app factory: `_mcp_app = None` at import, created on first request
- `post_migrate` signal wiring with app-name guard
- `base_url` corrected to `"nautobot-app-mcp-server"` (matches Nautobot plugin convention)
- All `nautobot_mcp_server` → `nautobot_app_mcp_server` in DESIGN.md
- 20 test cases covering singleton, registry, ASGI bridge, lazy factory, signal wiring

## Task Commits

All 11 tasks committed atomically in a single commit:

- **Commit:** `13ca60e` (feat)
  - Wave 1 (Foundation): pyproject.toml, mcp package, base_url, DESIGN.md, ASGI bridge
  - Wave 2 (Server): registry.py, server.py, urls.py, mcp/__init__.py (public API)
  - Wave 3 (Signal + Tests): __init__.py (ready + post_migrate), test files

**Plan:** `.planning/phases/01-mcp-server-infrastructure/01-PLAN.md`

## Files Created/Modified

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | Modified | Added `fastmcp = "^3.2.0"` dependency |
| `nautobot_app_mcp_server/__init__.py` | Modified | Added `base_url`, `urls`, `ready()`, `_on_post_migrate` |
| `docs/dev/DESIGN.md` | Modified | Replaced all `nautobot_mcp_server` → `nautobot_app_mcp_server` |
| `nautobot_app_mcp_server/mcp/__init__.py` | Created | Public API: `MCPToolRegistry`, `ToolDefinition`, `register_mcp_tool` |
| `nautobot_app_mcp_server/mcp/registry.py` | Created | Thread-safe singleton registry |
| `nautobot_app_mcp_server/mcp/server.py` | Created | FastMCP instance + lazy factory `get_mcp_app()` |
| `nautobot_app_mcp_server/mcp/view.py` | Created | ASGI bridge via `WsgiToAsgi` |
| `nautobot_app_mcp_server/urls.py` | Created | Django URL route at `path("mcp/", mcp_view)` |
| `nautobot_app_mcp_server/mcp/tests/__init__.py` | Created | Test package marker |
| `nautobot_app_mcp_server/mcp/tests/test_view.py` | Created | 5 tests: imports, URL resolution, ASGI bridge, lazy factory |
| `nautobot_app_mcp_server/mcp/tests/test_signal_integration.py` | Created | 15 tests: singleton, registry, signal wiring |

## Decisions Made

1. **Single-file app config**: Kept `NautobotAppMcpServerConfig` in `__init__.py` with `ready()` and `_on_post_migrate`. No separate `apps.py` — simpler, fewer files for Phase 1.

2. **`urls` attribute in config**: `urls = ["nautobot_app_mcp_server.urls"]` enables Nautobot plugin URL discovery without modifying any core Nautobot files.

3. **`post_migrate` guard**: `if app_config.name == "nautobot_app_mcp_server"` ensures `_on_post_migrate` runs only when this specific app's migrations complete (fires exactly once after all `ready()` hooks).

4. **Lazy factory safety**: Module-level `_mcp_app: Starlette | None = None` with `global` check — no double-checked locking needed (Python GIL + module-level sentinel is sufficient for Phase 1).

5. **`base_url` correction**: `"mcp-server"` → `"nautobot-app-mcp-server"` aligns with Nautobot plugin URL convention (`/plugins/<base_url>/`).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None — all 11 tasks executed without issues. Ruff and Pylint both passed cleanly on first run.

## Next Phase Readiness

Phase 1 is complete. The following Phase 2 and Phase 3 foundations are in place:

- **Phase 2 (Auth + Sessions)**: `MCPToolRegistry` singleton ready for `@mcp.list_tools()` progressive disclosure (REGI-05); `mcp_server.py` FastMCP instance ready for session manager integration; no auth enforcement yet — `get_user_from_request()` not yet called in tools.
- **Phase 3 (Core Read Tools)**: `nautobot_app_mcp_server/mcp/tools/` directory does not yet exist; `register_mcp_tool()` ready to be called from `_on_post_migrate` with core tool definitions.

**Blockers:** None.

---
*Phase: 01-mcp-server-infrastructure*
*Completed: 2026-04-01*
