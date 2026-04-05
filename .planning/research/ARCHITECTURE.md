# Architecture Research — Separate-Process MCP Server (Option B)

**Domain:** FastMCP server as a standalone process integrated with Nautobot via `nautobot.setup()`
**Researched:** 2026-04-05
**Confidence:** HIGH (verified via source extraction from `nautobot-app-mcp` reference implementation)

## Context

This document is consumed by `gsd-roadmapper` to understand component responsibilities, build order, and what to implement in each phase of the v1.2.0 refactor from embedded (Option A) to separate-process (Option B).

**Existing Option A (embedded):** FastMCP ASGI app runs inside Nautobot's Django process, bridged via `mcp_view` + `asyncio.run()`. This required 8 concurrency primitives, monkey-patching dataclass fields, and an override of FastMCP's private `_list_tools_mcp` API.

**New Option B (separate-process):** FastMCP runs as a standalone process started by a Django management command. It calls `nautobot.setup()` once at worker startup to bootstrap the Django ORM. Tool handlers wrap ORM calls in `sync_to_async`. Session state lives in a plain dict keyed by FastMCP session ID.

---

## Option A vs Option B: Structural Comparison

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    OPTION A — Embedded (current)                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Nautobot Django process                                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  mcp_view() [view.py]                                                │    │
│  │    async_to_sync(_bridge_django_to_asgi)()                           │    │
│  │      get_mcp_app() [lazy singleton, 3× double-checked locking]       │    │
│  │        _ensure_lifespan_started()  ──► daemon thread: asyncio.Event()│    │
│  │          run_lifespan()              keeps FastMCP loop alive forever │    │
│  │        mcp_instance.http_app()                                        │    │
│  │          Starlette ASGI app at /mcp/                                  │    │
│  │                                                                            │
│  │  server.py: _mcp_instance, _mcp_app, _lifespan_lock, _lifespan_guard │    │
│  │            _app_lock, _lifespan_started — 6 module-level globals      │    │
│  │                                                                            │
│  │  session_tools.py: monkey-patches RequestContext._mcp_tool_state        │    │
│  │  auth.py:         monkey-patches RequestContext._cached_user            │    │
│  │  server.py:       overrides FastMCP._list_tools_mcp (private API)      │    │
│  │                                                                            │
│  │  Concurrency primitives: 1 threading.Lock + 1 asyncio.Lock           │    │
│  │                          + 1 daemon thread + 1 Event.wait()             │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────┐
│                    OPTION B — Separate Process (target)                      │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Process 1: Nautobot Django  (port 8080, unchanged)                          │
│  Process 2: FastMCP MCP Server (port 8005, separate)                         │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  start_mcp_server.py / start_mcp_dev_server.py                        │    │
│  │    nautobot.setup()  ──► bootstraps Django ORM once per worker        │    │
│  │    FastMCP("NautobotMCP", port=8005)                                  │    │
│  │    register_all_tools_with_mcp(mcp)  ──► registry.py decorators       │    │
│  │    mcp.run(transport="http")  /  mcp.http_app() via uvicorn            │    │
│  │                                                                            │
│  │  Tool handlers (device_tools.py, etc.)                                  │    │
│  │    @sync_to_async(thread_sensitive=True)                                │    │
│  │    def get_device_details_sync(device_name):                            │    │
│  │      return Device.objects.get(name=device_name)                        │    │
│  │                                                                            │
│  │  Session state: plain dict keyed by FastMCP session_id                  │    │
│  │  Progressive disclosure: scope-guard decorator                          │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Option B System Overview

```
Startup (one-time per worker)
│
└─ start_mcp_server.py / start_mcp_dev_server.py
       │
       ├── nautobot.setup()         [Django ORM bootstrap]
       │
       ├── FastMCP("NautobotMCP", port=8005)  [FastMCP server instance]
       │
       ├── register_all_tools_with_mcp(mcp)  [registry.py → tool decorators]
       │
       └── mcp.run(transport="http")  [production]  OR  mcp.http_app() via uvicorn  [dev]

Runtime (per MCP request)
│
└─ MCP client (Claude Code, Claude Desktop)
       │
       ├── HTTP POST /mcp/  ──► FastMCP HTTP handler
       │         │
       │         ├── Auth: extract Authorization: Token header
       │         │           → Token.objects.select_related("user").get(key=...)
       │         │           → user stored in per-session state dict
       │         │
       │         ├── Session: Mcp-Session-Id → in-memory sessions dict
       │         │           → scope state: {"enabled_scopes": set(), "enabled_searches": set()}
       │         │
       │         ├── Tool dispatch: FastMCP → tool handler (sync_to_async wrapped)
       │         │           → MCPToolRegistry.get_by_scope(scope) for progressive disclosure
       │         │           → Django ORM: Device.objects.select_related(...).restrict(user)
       │         │
       │         └── HTTP response (JSON-RPC)
       │
       └── MCP client reads response
```

---

## Component Responsibilities

| Component | Location | Responsibility | Implementation Pattern |
|-----------|----------|----------------|----------------------|
| **Management command (prod)** | `management/commands/start_mcp_server.py` | Bootstrap FastMCP worker: `nautobot.setup()` → register tools → `mcp.run(transport="http")` | Django `BaseCommand`, reads plugin settings for host/port, `mcp.run()` blocks forever |
| **Management command (dev)** | `management/commands/start_mcp_dev_server.py` | Dev worker with uvicorn auto-reload: `nautobot.setup()` → `create_app()` factory → `uvicorn.run(mcp.http_app())` | Django `BaseCommand` + `create_app()` module-level factory for uvicorn reload detection |
| **Tool registry** | `nautobot_mcp/tools/registry.py` | Register tools via `@register_tool` decorator; `discover_tools_from_directory()` for custom tools; `register_all_tools_with_mcp()` to wire all tools to FastMCP | Module-level `_tool_registry` dict; `MCPTool.objects` database persistence; `@mcp.tool()` applied during `register_all_tools_with_mcp()` |
| **Tool implementations** | `nautobot_mcp/tools/device_tools.py` | Individual tool handlers; `sync_to_async` ORM wrappers; permission enforcement | `@register_tool` decorator + `sync_to_async` wrapper pattern; `select_related`/`prefetch_related` chains; `.restrict(user, action="view")` |
| **Session state** | `MCPSessionState` (session_tools.py) | Per-session enabled_scopes + enabled_searches; keyed by FastMCP session ID in `StreamableHTTPSessionManager.sessions` dict | Plain Python dict, no monkey-patching of RequestContext; `_mcp_tool_state` dict on session, not on dataclass |
| **Auth** | `get_user_from_request()` (auth.py) | Extract Token from MCP request context; cache on session dict; return `AnonymousUser` on failure | `ctx.request_context.request.headers["Authorization"]`; `Token.objects.select_related("user").get(key=...)`; `session["cached_user"]` cache |
| **Cleanup (deleted)** | `view.py`, `server.py`, monkey-patches | WSGI→ASGI bridge, daemon lifespan thread, RequestContext monkey-patching | **Entirely removed** in Option B |

---

## How Option B Integrates with Nautobot

### 1. `nautobot.setup()` — Django ORM Bootstrap

`nautobot.setup()` is called **once** at worker startup (inside the management command, before FastMCP is initialized):

```python
# start_mcp_dev_server.py — create_app()
def create_app():
    import nautobot
    nautobot.setup()   # ← boots Django ORM, runs all app.ready() hooks

    from mcp.server.fastmcp import FastMCP
    from nautobot_mcp.tools.registry import register_all_tools_with_mcp

    mcp = FastMCP("NautobotMCP", port=8005)
    register_all_tools_with_mcp(mcp)
    return mcp.http_app()
```

**What it does:** Initializes Django settings, registers all installed apps, runs migrations if needed, and prepares the ORM. After this call, `Device.objects`, `Token.objects`, etc. are fully usable from the same process.

**Why it works as a separate process:** `nautobot.setup()` initializes Django in-process. The MCP server IS that process. No WSGI→ASGI bridge is needed because the MCP server is not embedded inside Nautobot's Django HTTP worker.

### 2. `sync_to_async` ORM Wrappers

All tool handlers use `sync_to_async` to call the Django ORM from within FastMCP's async event loop:

```python
# device_tools.py — pattern from nautobot-app-mcp reference
from asgiref.sync import sync_to_async

@register_tool
async def get_device_details(device_name: str) -> str:
    @sync_to_async
    def get_device_details_sync(device_name):
        device = Device.objects.get(name=device_name)
        # ... build response string ...
        return device_info

    return await get_device_details_sync(device_name)
```

**Key:** `thread_sensitive=True` is the default and correct choice — it runs the sync ORM code in the same thread that Django's database connection pool expects. Without it, the ORM calls may use a different thread, causing connection pool errors.

### 3. Session State as Normal Dict

Option A monkey-patched `RequestContext._mcp_tool_state` and `RequestContext._cached_user`. Option B stores session state as a plain dict on FastMCP's built-in session object:

```python
# Inside a tool handler or session management utility
async def _get_session_state(session_id: str) -> dict:
    """Get or create session state dict keyed by FastMCP session_id."""
    sessions = mcp.session_manager.sessions  # FastMCP's in-memory sessions dict
    if session_id not in sessions:
        sessions[session_id] = {"enabled_scopes": set(), "enabled_searches": set()}
    return sessions[session_id]
```

No monkey-patching. No private API overrides. Session state is a normal dict keyed by FastMCP's `Mcp-Session-Id` header value.

### 4. Auth: Token from MCP Request Context

Auth still extracts the `Authorization: Token <hex>` header from the MCP request, but now uses FastMCP's native request object:

```python
# auth.py — Option B pattern
def get_user_from_request(ctx: ToolContext):
    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")

    if not auth_header or not auth_header.startswith("Token "):
        return AnonymousUser()

    token_key = auth_header[6:]

    # Check per-session cache
    session = ctx.request_context.session
    cached = session.get("cached_user")
    if cached is not None:
        return cached

    try:
        user = Token.objects.select_related("user").get(key=token_key).user
    except Token.DoesNotExist:
        return AnonymousUser()

    session["cached_user"] = user
    return user
```

The session is FastMCP's native session dict (not Django's `SessionStore`). Caching on the session avoids repeated DB lookups per request batch.

### 5. Progressive Disclosure: Scope-Guard Decorator

Option B replaces the private-API override `mcp._list_tools_mcp` with a straightforward scope-checking decorator:

```python
# progressive_disclosure.py — Option B pattern (new file)
from functools import wraps

def scope_guard(allowed_scopes: set[str]):
    """Decorator: skip tool if session doesn't have required scope."""
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            session_state = _get_session_state_from_context(ctx)
            if session_state.get("enabled_scopes", set()) & allowed_scopes:
                return await func(ctx, *args, **kwargs)
            return {"error": "scope not enabled"}
        return wrapper
    return decorator
```

FastMCP's `list_tools` returns the full tool manifest (all registered tools). Progressive disclosure in Option B is handled at the **tool handler level** (the tool returns an error if scope not enabled) rather than at the **manifest level** (filtering what appears in `tools/list`). This is simpler and avoids the private-API override.

---

## Production vs Development Patterns

| Aspect | Production (`start_mcp_server.py`) | Development (`start_mcp_dev_server.py`) |
|--------|-----------------------------------|----------------------------------------|
| Transport | `mcp.run(transport="http")` — FastMCP's built-in HTTP server | `mcp.http_app()` + `uvicorn.run()` — uvicorn with auto-reload |
| Process management | `systemctl start nautobot-mcp` or Docker `command:` | `poetry run invoke start-mcp-dev` |
| Auto-reload | No — production static binary | Yes — uvicorn `--reload` with `reload_dirs` including custom tools |
| Host/port config | From `settings.PLUGINS_CONFIG["nautobot_mcp"]["MCP_HOST/PORT"]` | Default `127.0.0.1:8005` |
| Custom tools | Via `MCP_CUSTOM_TOOLS_DIR` setting | Via `NAUTOBOT_MCP_CUSTOM_TOOLS_DIR` env var set inside command |
| Logs | `nautobot_mcp.utilities.logger` → structured JSON | `print()` to terminal (stdout captured by uvicorn) |

---

## Build Order

Dependencies dictate the following implementation order:

```
1.  start_mcp_server.py + start_mcp_dev_server.py
    └─ Imports: nothing else from this app (just Django BaseCommand + FastMCP + registry)
    └─ Must come FIRST: all downstream components depend on nautobot.setup() running first

2.  registry.py (nautobot_mcp/tools/registry.py)
    └─ Imports: nothing from auth or session (standalone)
    └─ Must come SECOND: tools need the registry to exist before they can register
    └─ Tool implementations (device_tools.py etc.) depend on this for @register_tool

3.  Tool implementations (device_tools.py, interface_tools.py, etc.)
    └─ Depend on: registry.py (for @register_tool decorator)
    └─ Depend on: nautobot.setup() having run (for Device, Interface, IPAddress models)
    └─ Auth and session: accessed via FastMCP ToolContext, not imported directly

4.  session.py (new file — session state management)
    └─ Depend on: FastMCP session dict access pattern
    └─ Produces: MCPSessionState, _get_session_state(), scope-guard decorator

5.  auth.py (update — simplify from monkey-patch to session dict)
    └─ Depend on: session.py (for session dict access)
    └─ Produces: get_user_from_request() reading from FastMCP session dict

6.  Cleanup (deletion phase — after all above are implemented and tested)
    └─ Delete: mcp/view.py, mcp/server.py (bridge layer)
    └─ Delete: monkey-patches in session_tools.py, auth.py
    └─ Delete: mcp._list_tools_mcp override in server.py
    └─ Delete: mcp/session_tools.py (replaced by session.py + FastMCP native)
    └─ Delete: mcp/__init__.py register_mcp_tool re-exports (no longer needed)
```

---

## Migration Path: What Changes vs What Gets Deleted

### Files Modified (Option B reads)

| File | Action | Changes |
|------|--------|---------|
| `management/commands/start_mcp_server.py` | **New** | Production management command with `nautobot.setup()` + `mcp.run(transport="http")` |
| `management/commands/start_mcp_dev_server.py` | **New** | Dev management command with `create_app()` factory + uvicorn auto-reload |
| `nautobot_mcp/tools/registry.py` | **New** | Tool registration, `discover_tools_from_directory()`, `register_all_tools_with_mcp()` |
| `nautobot_mcp/tools/device_tools.py` | **New** | `get_device_details` with `sync_to_async` ORM wrapper (reference implementation) |
| `nautobot_mcp/session.py` | **New** | `MCPSessionState`, `_get_session_state()`, progressive disclosure helpers |
| `nautobot_mcp/auth.py` | **New / updated** | `get_user_from_request()` reading from FastMCP session dict cache |
| `nautobot_mcp/__init__.py` | **Modified** | Remove embedded FastMCP wiring; keep plugin metadata only |

### Files Deleted (Option A only)

| File | Reason for Deletion |
|------|---------------------|
| `mcp/view.py` | WSGI→ASGI bridge not needed in separate process; FastMCP has its own HTTP handler |
| `mcp/server.py` | `_setup_mcp_app()`, `get_mcp_app()`, daemon lifespan thread, `_ensure_lifespan_started()` — not needed |
| `mcp/session_tools.py` | `MCPSessionState.from_session()` + `_get_tool_state()` monkey-patch patterns replaced by session.py |
| `mcp/auth.py` | `get_user_from_request()` with `ctx.request_context._cached_user` monkey-patch replaced by auth.py |
| `mcp/registry.py` | `MCPToolRegistry` singleton pattern replaced by `nautobot_mcp/tools/registry.py` |
| `mcp/__init__.py` | `register_mcp_tool()` public API — replaced by `nautobot_mcp/tools/registry.py` |
| `mcp/urls.py` | URL routing to `mcp_view` — no longer needed; MCP runs on separate port |
| `mcp/tests/test_view.py` | Tests for the ASGI bridge — not applicable to separate process |
| `mcp/tests/test_session_persistence.py` | Tests relying on `mcp_view` + session manager — re-implement as integration tests against management command |

### Files Preserved (shared between Option A and Option B)

| File | Reason for Preservation |
|------|-------------------------|
| `mcp/tools/core.py` | Core read tools (device_list, interface_list, etc.) — port to Option B pattern (`sync_to_async` + `session` dict) |
| `mcp/tools/pagination.py` | `paginate_queryset()` — no FastMCP dependencies; purely ORM |
| `mcp/tools/query_utils.py` | Query-building helpers — no FastMCP dependencies |
| `mcp/tests/test_core_tools.py` | Port to Option B auth/session mocking patterns |
| `mcp/tests/test_auth.py` | Port to Option B session dict patterns |

---

## Anti-Patterns

### Anti-Pattern: Calling `nautobot.setup()` Per Request

**What people do:** Put `nautobot.setup()` inside the request handler (tool execution path).

**Why it's wrong:** `nautobot.setup()` initializes Django settings, runs app discovery, and sets up the ORM connection pool. Doing this on every request is expensive (hundreds of milliseconds) and causes connection pool churn.

**Do this instead:** Call `nautobot.setup()` exactly once at worker startup, inside the management command's `handle()` or the `create_app()` factory. After that, the ORM is ready for all subsequent requests.

### Anti-Pattern: Using `asyncio.run()` in a Tool Handler

**What people do:** Calling `asyncio.run(some_async_fn())` inside an async tool handler to run async ORM wrappers.

**Why it's wrong:** `asyncio.run()` creates and destroys a new event loop on every call. This breaks FastMCP's internal context (event loop state, session dict). In Option B (separate process), FastMCP owns the one true event loop — calling `asyncio.run()` from within it creates a nested loop that orphan tasks.

**Do this instead:** Use `sync_to_async` for sync ORM calls (the standard pattern). If you need to run async code from a sync context, use `anyio.run()` which also respects the existing loop. Never use `asyncio.run()` inside FastMCP.

### Anti-Pattern: Storing State on `ServerSession`

**What people do (Option A):** `session["enabled_scopes"] = {...}` where `session` is FastMCP's `ServerSession`.

**Why it's wrong (Option A):** FastMCP's `ServerSession` is NOT dict-like — it has no `__setitem__`. Writes to it are silently lost. Option A worked around this by storing on `RequestContext._mcp_tool_state` (monkey-patching a dataclass field).

**Do this instead (Option B):** FastMCP's `StreamableHTTPSessionManager` manages real Python dict sessions in `self.sessions`. Access it via `ctx.request_context.session` which IS a dict in Option B. No monkey-patching needed.

### Anti-Pattern: Private-API Override of `mcp._list_tools_mcp`

**What people do (Option A):** `mcp._list_tools_mcp = progressive_list_tools_mcp` to filter tools in the manifest.

**Why it's wrong:** `_list_tools_mcp` is a private FastMCP method (underscore prefix). It may change or be removed in any FastMCP version. The override pattern relies on FastMCP internals that are not part of the public API.

**Do this instead (Option B):** Progressive disclosure at the **tool execution level** (scope-guard decorator returns an error if scope not enabled) rather than at the **manifest level**. This is simpler, uses only public APIs, and gives the AI agent clear error messages.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Nautobot ORM** | `nautobot.setup()` at startup, then direct `from nautobot.dcim.models import Device` | Only one `nautobot.setup()` call per worker lifetime |
| **Nautobot settings** | `from django.conf import settings` — reads `PLUGINS_CONFIG["nautobot_mcp"]` | Used for host, port, custom tools dir, core tools toggle |
| **Nautobot token auth** | `from nautobot.users.models import Token` — `Token.objects.select_related("user").get(key=token_key)` | Token keys are 40-char hex, no prefix |
| **FastMCP HTTP transport** | `mcp.run(transport="http")` (prod) or `mcp.http_app()` + uvicorn (dev) | Separate port from Nautobot (default 8005) |
| **Claude Code / Claude Desktop** | MCP client connects to `http://host:8005/mcp/` with `Authorization: Token <key>` | Standard MCP Streamable HTTP |

### Internal Boundaries

| Boundary | Communication | Option B Pattern |
|----------|---------------|------------------|
| Management command → Tool registry | Function call: `register_all_tools_with_mcp(mcp)` | Management command imports registry, calls registration function |
| Registry → Tool implementations | Decorator import side-effect: `@register_tool` on each tool function | Tools are imported by `discover_tools()` in registry, decorators register to `_tool_registry` dict |
| FastMCP → Tool handler | `mcp.tool()(func)` registers; FastMCP calls `func(ctx, **kwargs)` | FastMCP owns the event loop; tool handlers use `sync_to_async` for ORM |
| Tool handler → Auth | `get_user_from_request(ctx)` called at top of each tool | Reads `ctx.request_context.request.headers["Authorization"]`, caches on `ctx.request_context.session["cached_user"]` |
| Tool handler → Session | `_get_session_state(ctx)` | Reads from `ctx.request_context.session` dict (FastMCP's native session, not Django's) |
| Tool handler → ORM | `sync_to_async(fn, thread_sensitive=True)` | Runs sync ORM calls in Django's expected thread; returns awaitable to FastMCP |

---

## Sources

- `nautobot-app-mcp/nautobot_mcp/management/commands/start_mcp_server.py` — production management command pattern
- `nautobot-app-mcp/nautobot_mcp/management/commands/start_mcp_dev_server.py` — development command + `create_app()` factory
- `nautobot-app-mcp/nautobot_mcp/tools/registry.py` — `@register_tool` decorator, `register_all_tools_with_mcp()`, `discover_tools_from_directory()`
- `nautobot-app-mcp/nautobot_mcp/tools/device_tools.py` — `sync_to_async` ORM wrapper pattern, `asgiref.sync.sync_to_async`
- `nautobot_app_mcp_server/mcp/server.py` — current Option A implementation (to be deleted)
- `nautobot_app_mcp_server/mcp/view.py` — current Option A ASGI bridge (to be deleted)
- `nautobot_app_mcp_server/mcp/session_tools.py` — current Option A session state (to be replaced by `session.py`)
- `nautobot_app_mcp_server/mcp/auth.py` — current Option A auth with monkey-patch (to be simplified)
- `nautobot_app_mcp_server/mcp/registry.py` — current Option A `MCPToolRegistry` singleton (to be replaced by `nautobot_mcp/tools/registry.py`)
- `nautobot_app_mcp_server/.planning/PROJECT.md` — v1.2.0 milestone context
- `nautobot_app_mcp_server/.planning/ROADMAP.md` — Phase 5/6 requirements traceability

---
*Architecture research for: Option B separate-process MCP server refactor*
*Researched: 2026-04-05*
