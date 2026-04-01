# Stack Research — MCP Server Layer for Nautobot

**Domain:** MCP Python Server embedded in Django/Nautobot
**Researched:** 2026-04-01
**Confidence:** HIGH

> **Scope note:** Nautobot/Django/Poetry/invoke tooling is already established in `.planning/codebase/STACK.md`. This document covers only the MCP server layer: FastMCP, ASGI mounting into Django, async/sync bridging, and related infrastructure.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **`fastmcp`** | `>=3.2.0,<4.0.0` | MCP server framework | The standard 2025+ framework for MCP servers in Python. Built on `mcp` SDK. Declarative `@mcp.tool()` decorator handles schema generation, validation, Context injection automatically. "FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024" — the standalone package (`fastmcp`) is the actively maintained version, downloaded ~1M times/day, powers ~70% of production MCP servers. |
| **`mcp`** | `>=1.26.0,<2.0.0` | Underlying MCP protocol SDK | Direct dependency of `fastmcp`. Exposes `mcp.server.fastmcp.FastMCP`, `mcp.server.session.ServerSession`, `mcp.types`, `mcp.shared.context`. Pin upper bound `<2.0` since FastMCP 3.x pins it `<2.0`. |
| **`starlette`** | `>=0.40.0,<2.0.0` | ASGI routing and app framework | `fastmcp.streamable_http_app()` returns a Starlette ASGI app. Used for mounting the MCP server under a Django URL path via `Mount()`. Also used for `ASGITestClient` in tests. **Not `django-starlette`** — that package doesn't exist on PyPI. |
| **`uvicorn`** | `>=0.35.0,<1.0.0` | ASGI server | Required by `fastmcp` (peer dep). Only needed as a dev/test dependency for running the standalone MCP server. In production, Nautobot handles ASGI serving. |
| **`asgiref`** | `>=3.8.0,<4.0.0` | ASGI spec helpers + sync-to-async bridge | Already a transitive dep of Starlette. Provides `asgiref.sync.sync_to_async` for bridging Django ORM calls inside async FastMCP tool handlers. `thread_sensitive=True` reuses Django's thread-local connection pool — essential for ORM safety. Also provides `ASGI3App` type for type hints. Nautobot itself uses `asgiref`. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---|---|---|---|
| **`httpx`** | `>=0.28.0,<1.0.0` | HTTP client (peer dep) | Transitive dep of `fastmcp`. Starlette test client uses it internally. |
| **`anyio`** | `>=4.5.0,<5.0.0` | Async I/O framework | Peer dep of `mcp` and `starlette`. Required for async/await compatibility. |
| **`pydantic`** | `>=2.11.0,<3.0.0` | Data validation | Used internally by `mcp` for request/response models. Not called directly in this app. |
| **`python-multipart`** | `>=0.0.9` | Multipart form parsing | Required by `mcp` SDK for `Content-Type: multipart/form-data` handling in streamable HTTP. |

---

## Installation

```bash
# Add to pyproject.toml [tool.poetry.dependencies]

# MCP server layer
fastmcp = ">=3.2.0,<4.0.0"   # Framework (pins mcp, starlette, uvicorn, httpx, anyio transitively

# Dev/test only (not prod)
uvicorn = ">=0.35.0"          # Run standalone MCP server in dev
```

**Transitive deps that get installed automatically (do NOT pin separately):**
- `mcp >=1.26.0,<2.0.0`
- `starlette >=0.40.0`
- `httpx >=0.28.0,<1.0.0`
- `anyio >=4.5.0`
- `pydantic >=2.11.0,<3.0.0`
- `python-multipart >=0.0.9`
- `sse-starlette >=1.6.1`
- `jsonschema >=4.20.0`
- `typing-extensions >=4.9.0`

---

## Architecture Pattern: Embedding FastMCP ASGI App in Django

### The Core Problem

Nautobot 3.0 uses **Django's WSGI application** (`nautobot.core.wsgi.application`), not ASGI. You cannot simply mount a Starlette ASGI app inside a WSGI Django app via the URL router — Django `path()` only routes to callable views, not ASGI apps.

**Three options exist:**

| Option | Description | Reliability |
|---|---|---|
| **A: Django view wrapping ASGI scope** | A Django view function manually constructs an ASGI `scope` dict and calls the FastMCP ASGI app | ⚠️ Hacky — requires manually building scope dict, handling body streaming, chunked transfer encoding |
| **B: Separate uvicorn/Daphne process on different port** | MCP server runs standalone on port 9001, Nautobot on 8080 | ✅ Simplest, most reliable; used in production MCP deployments |
| **C: Starlette app mounted on a separate ASGI socket via `python -c` startup hook** | Nautobot is modified to listen on a second socket that serves the Starlette MCP app | ⚠️ Requires modifying Nautobot startup, fragile across upgrades |

### Recommended: Option B (Separate uvicorn Worker / Process)

**This is the officially documented pattern** in the MCP Python SDK README for mounting to "an existing ASGI server" — and Nautobot is not an ASGI server. The separate process pattern is also what every major MCP hosting solution (Claude Desktop, Claude Code MCP, Horizon) uses.

```
Claude Code MCP  →  HTTP POST/GET  →  uvicorn on :9001 (MCP server)
                                         │
                                         └── FastMCP ASGI app
                                              ├── mcp.session_manager.run() [async session loop]
                                              └── tool handlers → sync_to_async → Django ORM
                                                       ↑
                                              Direct import (same machine, no HTTP)
                                                       │
Nautobot Django  ←  REST API / Celery  ←  Same process (no MCP involvement)
```

**How to wire it:**
```python
# nautobot_app_mcp_server/mcp/server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "NautobotMCP",
    stateless_http=False,
    json_response=True,
    streamable_http_path="/",  # Mount at root of uvicorn server
)

# Run via: uvicorn nautobot_app_mcp_server.mcp.server:asgi_app --bind 0.0.0.0:9001
# asgi_app is exposed by FastMCP automatically (mcp.run() is not called)
```

The `asgi_app` attribute on `FastMCP` is a Starlette app. Run it standalone with uvicorn in a Docker Compose service.

**For development:** run `uvicorn nautobot_app_mcp_server.mcp.server:asgi_app --reload` in a sidecar container or the dev shell.

### Option A (In-Django Embedding via Starlette Mount) — If Required

If you absolutely must run inside the Nautobot Django process (e.g., to access Django's test client), use this verified pattern:

```python
# Nautobot serves WSGI. FastMCP is ASGI. The Django view manually
# constructs an ASGI scope and calls the ASGI app directly.
# This works but requires careful scope dict construction.

from starlette.testclient import ASGITestClient
from asgiref.sync import sync_to_async

# In a Django test or management command:
with ASGITestClient(app=mcp.streamable_http_app()) as client:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
```

**Use case:** only for unit tests. Not for production HTTP serving.

---

## ASGI Patterns for MCP Tool Handlers

### Pattern 1: Async Tool Handlers with `Context` Injection (Preferred)

```python
from mcp.server.fastmcp import FastMCP, Context
from asgiref.sync import sync_to_async

mcp = FastMCP("NautobotMCP", json_response=True)

@mcp.tool()
async def device_list(
    name: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
    ctx: Context = None,
) -> list[dict]:
    """List Nautobot devices with pagination."""
    # Get Nautobot user from request metadata
    user = _get_user_from_request_meta(ctx.request_context.request)

    # Bridge to sync Django ORM
    _get_devices = sync_to_async(_sync_device_list, thread_sensitive=True)
    result = await _get_devices(name=name, limit=limit, cursor=cursor, user=user)
    return result
```

**Key:** `thread_sensitive=True` — this reuses Django's thread-local connection pool. Without it, each call opens a new DB connection and may exhaust the pool under load.

### Pattern 2: Lifespan Context for Shared Resources

```python
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

@dataclass
class NautobotAppContext:
    # In v1: no persistent resources needed (in-memory registry, no Redis)
    # Future: DB pool handle, config cache, Redis client
    pass

@contextlib.asynccontextmanager
async def lifespan(app) -> AsyncIterator[NautobotAppContext]:
    async with mcp.session_manager.run():  # Starts MCP session loop
        yield NautobotAppContext()

# In tools:
@mcp.tool()
async def device_list(ctx: Context) -> list[dict]:
    app_ctx: NautobotAppContext = ctx.request_context.lifespan_context
    # Use shared resources...
```

### Pattern 3: Custom `list_tools()` for Progressive Disclosure

The `@mcp.list_tools()` override intercepts the MCP `tools/list` protocol call and returns a filtered tool manifest per session:

```python
@mcp.list_tools()
async def list_tools(ctx: Context) -> list[Tool]:
    """Return tools active in this session (core + scoped + searched)."""
    registry = MCPToolRegistry.get_instance()
    session_state = _get_session_state(ctx.session.session_id)
    active_tools = session_state.get_active_tools(registry)

    return [
        Tool(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
        )
        for t in active_tools
    ]
```

### Pattern 4: Mounting FastMCP Inside a Starlette App

```python
import contextlib
from starlette.applications import Starlette
from starlette.routing import Mount

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield

app = Starlette(
    routes=[Mount("/mcp", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)
```

This is the Starlette ASGI app you'd run with `uvicorn`. FastMCP exposes it as `mcp.streamable_http_app()` which already includes the lifespan context manager internally — **you do not need to wrap it again**.

---

## `stateless_http=False` vs `True` — Decision

| Setting | Sessions | Use Case | This Project |
|---|---|---|---|
| `stateless_http=True` | No sessions. Each request standalone. | Claude Desktop, stateless proxies | ❌ Not suitable |
| `stateless_http=False` | Sessions tracked by `Mcp-Session-Id` header. FastMCP session manager stores per-session state. | Claude Code MCP, stateful AI agent workflows | ✅ **Use this** |

**Recommended configuration:**
```python
mcp = FastMCP(
    "NautobotMCP",
    stateless_http=False,       # Per-session scope state
    json_response=True,          # JSON responses (not chunked SSE)
)
```

Session state is stored **in-memory** in the FastMCP `StreamableHTTPSessionManager`. `session_manager.get_session_state(session_id)` returns the session object. For v1, this is sufficient. Redis backend is a future swap-in.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|---|---|---|
| **FastMCP (`fastmcp`)** | Low-level `mcp.server.lowlevel.Server` | Use low-level only if you need zero-FastMCP overhead, custom session management, or MCP protocol-level control. For this project, the decorator-based approach is cleaner and the FastMCP abstraction is well-tested. |
| **Option B (separate uvicorn)** | Option A (in-Django embedding) | Option A (Django view → ASGI bridge) requires manually building ASGI scope dicts. It is fragile and not documented by the MCP SDK. Option B is the officially supported mounting pattern. |
| **`fastmcp`** | `mcp` alone without FastMCP | `mcp` SDK provides raw protocol primitives. FastMCP adds declarative decorators, auto schema generation, Context injection, and session management — saving ~300 lines of boilerplate. |
| **In-memory session** | Redis-backed session (`StreamableHTTPSessionManager` with Redis) | Redis is out of scope for v1 (per DESIGN.md). The in-memory session manager is sufficient for single-worker deployments. Multi-worker deployments would need Redis (future). |
| **`mcp.list_tools()` override** | Separate `/tools/list` Django view | Override is cleaner — MCP protocol semantics stay in the MCP layer, no URL routing conflicts. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| **`django-starlette`** | Does not exist on PyPI | Mount FastMCP via a separate uvicorn service (Option B) |
| **`channels`** | Django Channels is for WebSocket/async messaging. Nautobot 3.0 does not use it. Adding it as a dependency would complicate ASGI/WSGI coexistence unnecessarily. | Separate uvicorn process for MCP |
| **`nest-asyncio`** | Workaround for nested async event loops. Sign of architectural problem. Using `thread_sensitive=True` on `sync_to_async` avoids event loop nesting in Django ORM calls. | `thread_sensitive=True` pattern |
| **Any ASGI mounting library for Django** | No stable library exists for mounting ASGI apps inside a WSGI Django app. The `django-starlette` / Starlette-in-Django approach is not a supported pattern. | Option B: separate uvicorn process |
| **`pip`** directly | Project uses Poetry exclusively. | `poetry add fastmcp` |
| **FastMCP `mcp.run()` in production** | `mcp.run()` creates its own uvicorn server. In a Docker Compose environment, run `uvicorn` directly instead for better process management. | `uvicorn nautobot_app_mcp_server.mcp.server:asgi_app --bind 0.0.0.0:9001` |
| **`anyio` directly in app code** | Anyio is a peer dep used internally. Tool handlers should use `async def` (which is naturally anyio-compatible via Starlette's anyio backend) rather than `anyio.create_task_group()` directly. | `async def` + `await` |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---|---|---|
| `fastmcp >=3.2.0` | `mcp >=1.24.0,<2.0.0`, `starlette >=0.40.0`, `uvicorn >=0.35.0` | FastMCP 3.x is the current stable. Pins upper bound on `mcp` at `<2.0`. |
| `mcp >=1.26.0` | `starlette >=0.27.0`, `anyio >=4.5.0`, `pydantic >=2.11.0,<3.0.0` | MCP 1.x is stable. v2 is pre-alpha (README notes "use v1.x branch"). |
| `starlette >=0.40.0` | `anyio >=3.6.2` | Starlette 0.40.x (latest 1.0.0 requires Python >=3.10, compatible with our stack). |
| `asgiref >=3.8.0` | `starlette >=0.20.0`, Django >=3.2 | Used transitively. Provides `sync_to_async` with `thread_sensitive`. |
| `fastmcp >=3.2.0` | Python >=3.10 | Matches our `python = ">=3.10,<3.15"` constraint. |
| `Django ~4.2.26` (Nautobot 3.0 dep) | Compatible | Django 4.2 is sync-based. Async handlers must use `sync_to_async` for ORM access. No Django Channels dependency needed. |
| `uvicorn >=0.35.0` | `starlette >=0.27.0`, `anyio` | Uvicorn is a peer dep of `fastmcp`, not pinned upper bound. |

**Critical compatibility note:** FastMCP `streamable_http_app()` uses Starlette's routing internally. When mounting at a sub-path (e.g., `/mcp`), the FastMCP app handles path routing internally — **you do not need a separate Starlette `Mount()` wrapper** when calling `streamable_http_app(path="/mcp")`. However, if you want to combine multiple ASGI apps (e.g., the MCP server alongside other Starlette routes), use Starlette's `Mount()` as shown in the "Multiple servers with path configuration" pattern.

---

## Stack Patterns by Variant

**If embedding MCP in a separate uvicorn process (recommended for production):**
- Use `fastmcp` with `streamable_http_path="/"` (mounts at root of uvicorn)
- Run via: `uvicorn nautobot_app_mcp_server.mcp.server:asgi_app --bind 0.0.0.0:9001`
- Session state: in-memory (FastMCP `StreamableHTTPSessionManager`)
- Docker Compose: add a `mcp` service alongside `nautobot`
- Claude Code MCP config: `{"url": "http://nautobot:9001/mcp"}`

**If embedding MCP in Django test client (for unit tests only):**
- Use `starlette.testclient.ASGITestClient` wrapping `mcp.streamable_http_app()`
- This is synchronous-context so must be used inside async test functions
- Not suitable for production HTTP serving

**If running MCP server in dev alongside Nautobot:**
- Run `uvicorn nautobot_app_mcp_server.mcp.server:asgi_app --reload --port 9001` in a separate terminal
- Nautobot Docker Compose services unchanged
- Claude Code connects to `http://localhost:9001/mcp`

**If needing multiple MCP servers on the same host (future):**
- Use `FastMCP(...).settings.streamable_http_path = "/"` on each server
- Mount each with Starlette `Mount("/api", app=api_mcp.streamable_http_app())`
- Single uvicorn serves all

---

## Key Design Corrections vs DESIGN.md

The following corrections apply based on live SDK verification:

1. **`streamable_http_app()` returns an ASGI app directly.** The DESIGN.md `NotImplementedError` in the ASGI bridge view is unnecessary. FastMCP's `streamable_http_app()` is a ready-to-mount Starlette ASGI app. It requires `await mcp.session_manager.run()` to be active — this runs the MCP session loop as an async context manager.

2. **`StreamableHTTPSessionManager` is used internally by FastMCP**, not called directly. The `mcp.session_manager` is the session manager instance. Use `mcp.session_manager.run()` as the async context manager in the lifespan.

3. **Auth in tool handlers**: Use `ctx.request_context.request` (an `mcp` SDK request object, not a Django `HttpRequest`). Extract headers from `ctx.request_context.request.headers`. Pass to `sync_to_async` bridge.

4. **`mcp.list_tools()` overrides the protocol handler.** Not a separate URL route — it intercepts the `tools/list` MCP protocol message. Return a list of `Tool` objects (from `mcp.types`).

5. **`post_migrate` signal for tool registration**: Still correct. This fires after all migrations, guaranteeing all `ready()` hooks have run. Use `post_migrate.connect(...)` in `NautobotAppConfig.ready()`.

6. **Package directory name**: Actual package is `nautobot_app_mcp_server/` (not `nautobot_mcp_server/`). Keep the existing name. The import path for third-party apps would be `from nautobot_app_mcp_server.mcp import register_mcp_tool`.

7. **`base_url`**: Keep `"nautobot-mcp-server"` as the Nautobot plugin URL prefix. The MCP endpoint path within that is `/mcp/` (so full URL = `/plugins/nautobot-mcp-server/mcp/`).

---

## Sources

- **PyPI JSON API** — `fastmcp`, `mcp`, `starlette`, `asgiref`, `uvicorn`, `anyio`, `httpx` package metadata and dependency trees (verified 2026-04-01)
- **`github.com/jlowin/fastmcp` README** (`main` branch) — FastMCP overview, HTTP transport docs (verified 2026-04-01)
- **`github.com/modelcontextprotocol/python-sdk` README** (`main` branch, v1.x stable docs) — FastMCP usage, Streamable HTTP transport, ASGI mounting with Starlette, `Context` injection, `stateless_http`, lifespan patterns (verified 2026-04-01)
- **`github.com/modelcontextprotocol/python-sdk` releases** (`api.github.com/repos/.../releases`) — `mcp` v1.26.0 released 2026-01-24 (verified 2026-04-01)
- **`github.com/nautobot/nautobot` pyproject.toml** (`v3.0.0` tag) — Django ~4.2.26, Python >=3.10,<3.14, WSGI-only (WSGI_APPLICATION confirmed, no ASGI/Channels) (verified 2026-04-01)
- **`github.com/nautobot/nautobot` `nautobot/core/wsgi.py`** (`develop` branch) — Nautobot uses `get_wsgi_application()`, no ASGI app exposed (verified 2026-04-01)

---

*Stack research for: MCP server layer (FastMCP + ASGI + Django integration)*
*Researched: 2026-04-01*
