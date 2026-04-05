# Stack Research: Separate-Process FastMCP Server Architecture

**Domain:** Separate-process MCP server (Option B) — FastMCP as a standalone Python process, bootstrapped via Django management commands
**Researched:** 2026-04-05
**Confidence:** HIGH — Source-verified from `nautobot-app-mcp` reference project (two management commands, `create_app()` factory, `nautobot.setup()`)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `fastmcp` | `^3.2.0` (existing) | `FastMCP` server instance, `mcp.run(transport="sse")` | Already installed; provides the standalone runloop — no Django bridge needed |
| `uvicorn` | `>=0.35.0` (transitive via fastmcp; locked `0.42.0`) | ASGI server for dev hot-reload | FastMCP already depends on uvicorn; `start_mcp_dev_server.py` uses `uvicorn.run()` with `reload=True` and `create_app()` factory |
| `nautobot` | `>=3.0.0,<4.0.0` (existing) | `nautobot.setup()` bootstraps Django ORM once per worker | Called once at worker startup; from then on, direct ORM access works without the WSGI→ASGI bridge |
| `asgiref` | ships with Nautobot/FastMCP (existing) | `sync_to_async` wraps ORM calls in async tool handlers | Existing in embedded architecture; continues to be used for ORM calls inside `async def tool_handler()` |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `django.core.management` | (ships with Nautobot) | `BaseCommand` for `start_mcp_server.py` and `start_mcp_dev_server.py` | Always — management commands are the process entry point |
| `signal` | stdlib | `SIGUSR1` force-reload handler in dev server | Only in dev server; handles uvicorn restart signals |

---

## What Is ADDED vs REMOVED vs KEPT

### ADDED (New Dependencies / Patterns for Separate-Process)

| Addition | Rationale | Source |
|----------|-----------|--------|
| `uvicorn` (`>=0.35`) explicitly listed | Required for `start_mcp_dev_server.py`; already a transitive dep via FastMCP but should be explicit for `uvicorn.run()` API | `nautobot-app-mcp` `start_mcp_dev_server.py` L79 |
| `start_mcp_server.py` Django management command | Production entry point: `mcp.run(transport="sse")` on a configurable host/port | `nautobot-app-mcp` `start_mcp_server.py` L71 |
| `start_mcp_dev_server.py` Django management command | Dev entry point: `uvicorn.run("...:create_app", reload=True)` with auto-reload watching tool dirs | `nautobot-app-mcp` `start_mcp_dev_server.py` L79 |
| `create_app()` factory function | Standalone FastMCP app factory callable by uvicorn; calls `nautobot.setup()` + registers tools | `nautobot-app-mcp` `start_mcp_dev_server.py` L91 |
| `nautobot.setup()` call at worker startup | Bootstraps Django ORM once per worker; from then on `sync_to_async(orm_fn)()` works without WSGI | `nautobot-app-mcp` `start_mcp_dev_server.py` L95 |
| `mcp.run(transport="sse")` for production | FastMCP's built-in SSE transport; runs the server loop natively | `nautobot-app-mcp` `start_mcp_server.py` L71 |

### REMOVED (Embedded Architecture — No Longer Needed)

| Removal | Rationale |
|---------|-----------|
| `asgiref.wsgi.WsgiToAsgi` bridge | No longer bridging WSGI↔ASGI — FastMCP runs as a standalone ASGI/SSE server, not inside Django |
| `daemon thread` for lifespan management | No shared event loop with Django; FastMCP owns its own event loop in the separate process |
| `StreamableHTTPSessionManager` (Django-hosted) | The session manager lives inside FastMCP's own process; no longer needs to be instantiated by Django code |
| `async_to_sync` WSGI→ASGI bridge in `view.py` | `mcp_view()` Django view endpoint is deleted entirely; MCP has its own HTTP endpoint |
| `contextvars.ContextVar` for Django request passthrough | No need to thread Django requests into FastMCP — they are separate processes |
| 8 concurrency primitives (locks, doublets, ContextVars) | Eliminated entirely: no lazy factory with double-check locking, no `_mcp_tool_state` on `RequestContext`, no `_cached_user` monkey-patching |
| `urls.py` with `path("mcp/", mcp_view)` | No Django URL routing for MCP — separate process has its own port/endpoint |
| `mcp._list_tools_mcp` override for progressive disclosure | FastMCP 3.x native tool listing used directly; progressive disclosure via scope-checking decorator or session dict in FastMCP's own session state |

### KEPT (Existing Code That Transfers to Separate-Process)

| Kept Item | What Changes |
|-----------|--------------|
| `MCPToolRegistry` singleton (`registry.py`) | Still in-memory singleton, but now inside FastMCP's process (no Django RequestContext) |
| `register_mcp_tool()` API (`mcp/tools/__init__.py`) | Works identically — called via `post_migrate` signal or at `create_app()` startup |
| `ToolDefinition` dataclass (`registry.py`) | Unchanged |
| `sync_to_async(fn, thread_sensitive=True)` ORM wrappers | Still needed inside `async def tool_handler()` — wraps Django ORM calls in FastMCP's async context |
| `PaginatedResult`, cursor encoding (`pagination.py`) | Unchanged — FastMCP async tools call the same pagination helpers |
| Auth: `get_user_from_request()`, `.restrict()`, `AnonymousUser` fallback | Still needed; auth context comes from FastMCP request headers (no Django `request` involved) |
| `MCPSessionState`, session tools (`session_tools.py`) | Session dict is now a plain `dict` keyed by FastMCP session ID — no monkey-patching on `RequestContext` |
| 10 core read tools (`mcp/tools/core.py`) | Unchanged signatures; `sync_to_async` wrappers still needed |
| `mcp/tools/query_utils.py` | Unchanged — query building helpers used by tools |
| All 78 tests | Rewrite `test_view.py` to test the management command entry point instead of the Django endpoint; others largely unchanged |

---

## uvicorn — Dev Server Hot-Reload

### Why uvicorn Is Needed

`nautobot-app-mcp` uses `uvicorn.run()` in `start_mcp_dev_server.py` specifically for **hot-reload**:

```python
uvicorn.run(
    "nautobot_mcp.management.commands.start_mcp_dev_server:create_app",
    host=host,
    port=port,
    reload=True,
    reload_dirs=reload_dirs,
    reload_delay=0.25,
    timeout_keep_alive=0,
    timeout_graceful_shutdown=1,
)
```

- `reload=True` — uvicorn watches source files and restarts the worker on changes
- `reload_dirs=[tools_dir, custom_tools_dir]` — watches tool directories specifically
- `create_app()` factory — called by uvicorn on each reload; calls `nautobot.setup()` fresh each time
- `timeout_keep_alive=0` — prevents hanging connections during reloads

### Production vs Development

| Environment | Transport | Server | Notes |
|-------------|-----------|--------|-------|
| **Production** | `mcp.run(transport="sse")` | FastMCP native loop | systemd-managed; no uvicorn |
| **Development** | `uvicorn.run(reload=True)` | uvicorn ASGI server | Auto-reload on file changes; `create_app()` factory |

### Version

uvicorn is **already a transitive dependency** of `fastmcp ^3.2.0` (`fastmcp` requires `uvicorn >= 0.35`). The current lock shows `uvicorn 0.42.0`. No new direct dependency needed — just use it from the existing transitive.

---

## Integration: How the Two Processes Communicate

```
┌─────────────────────────────────────┐
│  Nautobot Django App (port 8080)    │  ← Existing: REST API, admin UI
│  - Nautobot ORM                     │
│  - Token auth via Token model       │
│  - post_migrate signal              │
└─────────────────────────────────────┘
            ▲
            │ Nautobot ORM (direct, no network)
            │ nautobot.setup() bootstraps once per worker
            │
┌─────────────────────────────────────┐
│  FastMCP Separate Process (port N)  │  ← NEW: MCP protocol endpoint
│  - FastMCP SSE/streamable-http      │
│  - MCPToolRegistry (in-memory)      │
│  - sync_to_async ORM wrappers       │
│  - Plain dict session state         │
│  - start_mcp_server (prod: mcp.run) │
│  - start_mcp_dev_server (dev: uvicorn)│
└─────────────────────────────────────┘
            ▲
            │ MCP protocol (HTTP/SSE)
            │ Authorization: Token <key>
            │
┌─────────────────────────────────────┐
│  AI Agent (Claude Code, MCP client) │
└─────────────────────────────────────┘
```

**Key integration decisions:**
- FastMCP separate process uses **direct Django ORM** via `nautobot.setup()` — no REST API, no network hop
- Auth token still comes from Nautobot's `users.models.Token` table — FastMCP process imports it directly
- No inter-process communication layer needed — both processes share the same database
- Management commands register tools at startup (via `post_migrate` signal or direct call in `create_app()`)

---

## Installation

### `pyproject.toml` Changes

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.15"

# Keep existing
nautobot = ">=3.0.0,<4.0.0"
fastmcp = "^3.2.0"
python-dotenv = "*"
requests = "*"

# ADD: uvicorn explicitly (already transitive via fastmcp, but needed for
# uvicorn.run() API in start_mcp_dev_server.py)
uvicorn = { version = ">=0.35.0", extras = ["standard"] }

# REMOVE: asgiref is no longer needed for the WSGI→ASGI bridge
# (ships with Nautobot as a transitive dep; no direct use needed)
```

> **Note on `uvicorn[standard]`:** The `standard` extra includes the `uvicorn` CLI and standard ASGI server components. Since `fastmcp` already requires `uvicorn >= 0.35`, adding it explicitly with `extras = ["standard"]` pins a minimum version and ensures the full uvicorn API (`run()`, `Config`) is available. Without `standard`, only `uvicorn.importer` would be available.

### Dev Dependencies — No Change

All existing dev dependencies (`invoke`, `ruff`, `pylint`, `coverage`, etc.) remain. No new dev-only deps needed.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|------------|-------------|------------------------|
| `uvicorn` for dev server | `hypercorn` | Hypercorn has better Windows support and is used by some FastMCP deployments, but uvicorn is FastMCP's default and is already a transitive dep — no reason to add another server |
| `nautobot.setup()` + `sync_to_async` ORM | REST API calls between processes | REST adds network overhead and requires API token scoping; direct ORM is zero-latency and uses the same auth token model |
| `mcp.run(transport="sse")` production | `streamable-http` transport | `streamable-http` is more complex and requires the `StreamableHTTPSessionManager` pattern (the same complexity the refactor is trying to escape); SSE is FastMCP's recommended production transport |
| Django management commands as entry point | `__main__.py` standalone script | Management commands integrate with Nautobot's plugin system (`nautobot setup()`), Docker entry points, and systemd service files naturally — no reason to bypass them |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `asgiref.wsgi.WsgiToAsgi` | This is the embedded architecture that causes the 8-concurrency-primitives complexity; separate-process eliminates it entirely | No WSGI→ASGI bridge needed |
| `StreamableHTTPSessionManager` in Django | Session manager belongs inside FastMCP's process, not Django's | FastMCP's native session management |
| `daemon thread` for event loop persistence | Elimininated — FastMCP owns its event loop in the separate process | No daemon thread needed |
| `contextvars.ContextVar` for Django request passthrough | Separate process = no Django request to pass through | Direct ORM access after `nautobot.setup()` |
| `mcp._list_tools_mcp` override | This was a workaround for FastMCP inside Django; standalone FastMCP handles this natively | FastMCP's built-in `@mcp.list_tools()` decorator |
| `async_to_sync` for WSGI bridging | Only `sync_to_async` is needed for ORM calls inside async tool handlers | `sync_to_async(fn, thread_sensitive=True)` |

---

## Stack Patterns by Variant

**If production deployment:**
- Use `start_mcp_server.py` management command with `mcp.run(transport="sse")`
- Manage via systemd service (not uvicorn)
- `nautobot.setup()` called once at worker startup

**If development with hot-reload:**
- Use `start_mcp_dev_server.py` management command with `uvicorn.run(reload=True)`
- `create_app()` factory called by uvicorn on each reload
- `nautobot.setup()` called fresh on each reload

---

## Version Compatibility

| Package | Version | Compatible With | Notes |
|---------|---------|-----------------|-------|
| `fastmcp` | `^3.2.0` (existing) | `mcp >=1.24.0,<2.0` | Already installed; `mcp.run(transport="sse")` stable |
| `uvicorn` | `>=0.35.0` (existing transitive; locked `0.42.0`) | FastMCP requires `>=0.35`; full API (`run()`, `Config`) via `uvicorn[standard]` | No change to Nautobot compatibility |
| `nautobot` | `>=3.0.0,<4.0.0` (existing) | `nautobot.setup()` available since Nautobot 1.x; stable | `nautobot.setup()` initializes ORM without WSGI |
| `asgiref` | ships with Nautobot/FastMCP | `sync_to_async` unchanged | Still used for ORM wrappers inside async tool handlers |
| `mcp` (transitive via fastmcp) | `>=1.24.0,<2.0` | `StreamableHTTPSessionManager` not needed in separate-process | FastMCP native session management replaces it |
| Python | `>=3.10,<3.15` (existing) | `nautobot.setup()` requires 3.10+ | Unchanged |

---

## Sources

- `nautobot-app-mcp` (`nautobot_mcp/management/commands/start_mcp_server.py`) — production management command with `mcp.run(transport="sse")` — **source-verified**
- `nautobot-app-mcp` (`nautobot_mcp/management/commands/start_mcp_dev_server.py`) — dev management command with `uvicorn.run(reload=True)` and `create_app()` factory — **source-verified**
- `nautobot-app-mcp/pyproject.toml` — reference stack (`mcp ^1.6.0`, no explicit uvicorn, `python ^3.8`) — **source-verified**
- `nautobot-app-mcp-server/pyproject.toml` — current dependencies (`fastmcp ^3.2.0`, `nautobot >=3.0.0,<4.0.0`) — **source-verified**
- `nautobot-app-mcp-server/.planning/STATE.md` — current embedded architecture (8 concurrency primitives, daemon thread, monkey-patched RequestContext) — **source-verified**
- `nautobot-app-mcp-server/.planning/PROJECT.md` — v1.2.0 milestone: separate-process goal, `start_mcp_server.py`, `start_mcp_dev_server.py`, `nautobot.setup()` — **source-verified**

---

## Phase 1 Stack Additions Checklist

For `/gsd:roadmapper` consumption — Phase 1 needs:

```toml
# pyproject.toml additions
[tool.poetry.dependencies]
uvicorn = { version = ">=0.35.0", extras = ["standard"] }
# No removal of fastmcp or nautobot
# asgiref remains as transitive dep but is no longer directly imported in mcp/ code
```

```
Files ADDED:
  nautobot_app_mcp_server/management/__init__.py
  nautobot_app_mcp_server/management/commands/__init__.py
  nautobot_app_mcp_server/management/commands/start_mcp_server.py
  nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py

Files REMOVED (or gutted):
  nautobot_app_mcp_server/mcp/view.py       # WSGI→ASGI bridge deleted
  nautobot_app_mcp_server/mcp/server.py     # Daemon thread + lazy factory deleted
  nautobot_app_mcp_server/urls.py           # Django URL route for MCP deleted

Files MODIFIED:
  nautobot_app_mcp_server/mcp/session_tools.py  # RequestContext monkey-patching → plain dict
  nautobot_app_mcp_server/mcp/auth.py          # _cached_user on RequestContext → plain dict
  nautobot_app_mcp_server/__init__.py          # plugin config: remove embedded bridge wiring

Files KEPT (unchanged, transferred to separate process):
  nautobot_app_mcp_server/mcp/registry.py
  nautobot_app_mcp_server/mcp/tools/__init__.py
  nautobot_app_mcp_server/mcp/tools/core.py
  nautobot_app_mcp_server/mcp/tools/pagination.py
  nautobot_app_mcp_server/mcp/tools/query_utils.py
  nautobot_app_mcp_server/mcp/auth.py (signature unchanged)
  nautobot_app_mcp_server/mcp/session_tools.py (signature unchanged)
```

---

*Stack research for: separate-process FastMCP server architecture (v1.2.0 refactor)*
*Researched: 2026-04-05*
