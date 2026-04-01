# Phase 1: MCP Server Infrastructure - Context

**Gathered:** 2026-04-01 (assumptions mode — all decisions from research)
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the embedded FastMCP server scaffold — plugin wiring, ASGI bridge, URL routing, and the tool registry. No auth, no tools yet. Validates the core architectural decision (Option A: ASGI bridge via `asgiref.wsgi.WsgiToAsgi`).

</domain>

<decisions>
## Implementation Decisions

### Architecture
- **D-01:** Option A — FastMCP ASGI app embedded in Django via Nautobot `plugin_patterns` URL system + `asgiref.wsgi.WsgiToAsgi`. No core Nautobot files modified.
- **D-02:** NOT `django-starlette` — that package does not exist on PyPI. Use `asgiref.wsgi.WsgiToAsgi` (ships with Django).
- **D-03:** NOT Option B (separate worker) — violates core value prop, requires Redis, adds firewall complexity.

### Package Identity
- **D-04:** Package name is `nautobot_app_mcp_server` (not `nautobot_mcp_server` as in DESIGN.md). Fix DESIGN.md references before implementing.
- **D-05:** `base_url = "nautobot-app-mcp-server"` in `__init__.py`. Endpoint at `/plugins/nautobot-app-mcp-server/mcp/`.

### ASGI Bridge
- **D-06:** Bridge direction is Django WSGI → FastMCP ASGI. `WsgiToAsgi(app)` wraps the ASGI app for Django. NOT `async_to_sync`.
- **D-07:** `get_mcp_app()` lazy factory — ASGI app created on first HTTP request from the view function. NOT at module import time.

### FastMCP Server
- **D-08:** `FastMCP("NautobotMCP", stateless_http=False, json_response=True)`
- **D-09:** `streamable_http_app()` returns the Starlette ASGI app callable (`scope/receive/send`)
- **D-10:** `StreamableHTTPSessionManager` used internally by FastMCP (not called directly)

### MCP SDK Stack
- **D-11:** Dependencies: `mcp ^1.26.0` (Anthropic SDK), `fastmcp ^3.2.0` (Prefect), `asgiref ^3.11.1` (explicit dep)
- **D-12:** No `channels` or `uvicorn` needed (Option A, no separate worker)

### Tool Registry
- **D-13:** `MCPToolRegistry` — thread-safe singleton with `threading.Lock`, double-checked locking
- **D-14:** `ToolDefinition` dataclass with: name, func, description, input_schema, tier, scope
- **D-15:** `register_mcp_tool()` — public API for third-party Nautobot apps
- **D-16:** Methods: `get_core_tools()`, `get_by_scope()`, `fuzzy_search()`

### Django URL Route
- **D-17:** `nautobot_app_mcp_server/urls.py` with `path("mcp/", mcp_view)` — auto-discovered by Nautobot plugin system

### Signal Wiring
- **D-18:** `post_migrate` signal connected from `ready()` — fires when this app's migrations run, guaranteeing all third-party `ready()` hooks have already completed

### Not in Phase 1
- Auth (AUTH-01 through AUTH-03) — Phase 2
- Session state tools (SESS-01 through SESS-06) — Phase 2
- Core read tools (TOOL-01 through TOOL-10) — Phase 3
- Pagination helpers (PAGE-01 through PAGE-05) — Phase 3

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture & Stack
- `.planning/research/STACK.md` — mcp/fastmcp/asgiref versions, starlette compatibility
- `.planning/research/ARCHITECTURE.md` — 8-layer data flow, Option A/B resolution, build order, ASGI bridge code patterns
- `.planning/research/PITFALLS.md` — 18 pitfalls including PIT-03 (import-time ASGI app), PIT-04 (wrong bridge), PIT-05 (django-starlette doesn't exist)
- `.planning/codebase/ARCHITECTURE.md` — existing codebase structure and planned mcp/ module layout

### Package & Config
- `nautobot_app_mcp_server/__init__.py` — current NautobotAppConfig (note: `base_url = "mcp-server"`, needs update)
- `pyproject.toml` — add dependencies here (FOUND-01)
- `docs/dev/DESIGN.md` — source of truth for implementation patterns (note: fix `nautobot_mcp_server` → `nautobot_app_mcp_server` throughout)

### Conventions
- `.planning/codebase/CONVENTIONS.md` — Python naming, docstrings, error handling, import ordering
- `.planning/codebase/TESTING.md` — TransactionTestCase patterns, coverage config

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `nautobot_app_mcp_server/__init__.py` — NautobotAppConfig pattern to follow (26 lines, minimal)
- Nautobot's `nautobot/extras/plugins/urls.py` — verified plugin URL auto-discovery pattern (read this before writing urls.py)
- asgiref `WsgiToAsgi` — standard Django→ASGI bridge (confirmed in research)

### Established Patterns
- Package name `nautobot_app_mcp_server` is fixed (matches pyproject.toml Poetry name)
- No Django models in this app (protocol adapter, not data model)
- Poetry-only dependency management (no pip)

### Integration Points
- `nautobot_app_mcp_server/mcp/` package — all new code goes here
- `nautobot_app_mcp_server/__init__.py` — plugin entry point (add post_migrate wiring)
- `development/nautobot_config.py` — `PLUGINS = ["nautobot_app_mcp_server"]` already configured
- Nautobot plugin URL registry: `/plugins/nautobot-app-mcp-server/mcp/`

</code_context>

<deferred>
## Deferred Ideas

- Auth (Phase 2): Token extraction from MCP request context, AnonymousUser warning logging
- Session state (Phase 2): MCPSessionState dataclass, mcp_enable_tools/mcp_disable_tools/mcp_list_tools
- Core tools (Phase 3): TOOL-01 through TOOL-10
- search_by_name (Phase 3/4): Multi-model search with ranking — complexity underestimated in initial design

</deferred>

---
*Phase: 01-mcp-server-infrastructure*
*Context gathered: 2026-04-01*
