# Stack Research: WSGI→ASGI Bridge for FastMCP in Django

**Domain:** Django WSGI App embedding a FastMCP ASGI server
**Researched:** 2026-04-03
**Confidence:** HIGH — Source-verified from django-mcp-server v0.5.6 and `mcp` SDK `streamable_http_manager.py`

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `asgiref` | (ships with Django / FastMCP) | `async_to_sync` WSGI→ASGI bridge | Single canonical tool; used by Django Channels, Starlette; keeps event loop alive across requests |
| `mcp` | `>=1.8.0` (ships via fastmcp) | `StreamableHTTPSessionManager`, `MCPServer` core | Already installed via `fastmcp`; exposes the session manager used in django-mcp-server |
| `fastmcp` | `^3.2.0` (already installed) | `FastMCP` server, `http_app()` ASGI factory | Already used; provides `http_app()` that returns a Starlette ASGI app |
| `starlette` | (ships with fastmcp) | `Headers`, `Scope` types | Already a transitive dep; used by django-mcp-server for ASGI scope typing |
| `contextvars` | stdlib | Thread-local request context in `_call_starlette_handler` | Keeps Django request accessible in async tool calls without coupling to MCP internals |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `django` | `>=3.0` (already installed) | Django `HttpRequest`, session backend | Always — Django is the host |
| `anyio` | (ships with FastMCP) | `anyio.Lock`, `anyio.create_task_group` | Only if re-implementing session manager internals |

---

## Installation

No new packages required. All needed APIs are already present:

```python
# Already installed via fastmcp / Django — just import them
from asgiref.sync import async_to_sync                              # ← THE critical fix
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager  # ← session manager
from starlette.datastructures import Headers                        # ← for header parsing in send()
from starlette.types import Scope, Receive, Send                   # ← ASGI type hints
import contextvars                                                   # ← stdlib: pass Django request into async ctx
```

---

## Why `async_to_sync` Is Correct (and `asyncio.run()` Is Broken)

### The Problem with `asyncio.run()`

Every call to `asyncio.run()`:
1. **Creates a brand-new event loop** on the current thread
2. Runs the coroutine to completion inside it
3. **Destroys the loop** when done — including all session state held by `StreamableHTTPSessionManager`

`StreamableHTTPSessionManager._server_instances` (a `dict`) lives on the session manager **instance**, but the `_task_group` (an `anyio.create_task_group()`) — and crucially, the **tasks running inside it** — are bound to the event loop that was destroyed.

**Result:** Every HTTP request starts with a blank slate. The session manager has no running tasks, no session state, and `Server.request_context.get()` raises `LookupError` on every production request.

### How `async_to_sync` Works (from `asgiref/sync.py` source)

```
async_to_sync(my_async_func)(args...)
    │
    ├─ Creates a Future (call_result) on the current thread
    ├─ Creates a CurrentThreadExecutor on the current thread
    ├─ Schedules the async work onto the main event loop (if one exists)
    │     OR creates a new loop in a single ThreadPoolExecutor (if no loop)
    ├─ Blocks the WSGI worker thread on CurrentThreadExecutor.run_until_future()
    ├─ The async work runs to completion, including all task_group tasks
    └─ Returns result — event loop is NOT destroyed
```

Key behavior (lines 281–318 of `asgiref/sync.py`):

```python
if self.main_event_loop is not None:
    # If we're in a thread that already has a running loop:
    self.main_event_loop.call_soon_threadsafe(
        self.main_event_loop.create_task, awaitable
    )
    current_executor.run_until_future(call_result)  # Block, wait, don't destroy
else:
    # Fallback: new loop in a thread
    loop_executor = ThreadPoolExecutor(max_workers=1)
    loop_future = loop_executor.submit(asyncio.run, new_loop_wrap())
    current_executor.run_until_future(loop_future)
    loop_future.result()
```

**In WSGI (no running loop):** `async_to_sync` creates a new loop in a background thread via `ThreadPoolExecutor.submit(asyncio.run, ...)`. This loop stays alive as long as the executor's future hasn't resolved. While it runs, **all async work completes**, including session task groups.

**In ASGI (already has a loop):** `async_to_sync` reuses the existing loop — safe because the loop is managed by the ASGI server, not destroyed after each call.

### Why You Cannot Call `async_to_sync` from Inside a Running Loop

```python
# This raises RuntimeError in asgiref/sync.py line 233:
# "You cannot use AsyncToSync in the same thread as an async event loop"
async def my_view(request):
    await async_to_sync(some_async_fn)()  # WRONG — we're already inside the loop
```

Django WSGI workers have **no running event loop** (they're synchronous threads). `async_to_sync` is exactly the right tool.

### Why You Cannot Use `asyncio.run()` Inside `async_to_sync`

`asyncio.run()` is used **once**, inside the ThreadPoolExecutor's single background thread (line 314 of `asgiref/sync.py`):
```python
loop_future = loop_executor.submit(asyncio.run, new_loop_wrap())
```
After that, the executor blocks on the future. The loop is not destroyed until `loop_future.result()` returns.

---

## How to Build the ASGI Scope (django-mcp-server Pattern)

**Source:** `mcp_server/djangomcp.py`, `_call_starlette_handler()` function

```python
from __future__ import annotations

import json
import contextvars

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest
from starlette.datastructures import Headers
from starlette.types import Scope, Receive, Send

django_request_ctx: contextvars.ContextVar[HttpRequest] = contextvars.ContextVar(
    "django_request"
)

async def _call_starlette_handler(
    django_request: HttpRequest,
    session_manager: StreamableHTTPSessionManager,
) -> HttpResponse:
    """Bridge a Django request into the FastMCP session manager."""
    django_request_ctx.set(django_request)
    body = json.dumps(django_request.data, cls=DjangoJSONEncoder).encode("utf-8")

    scope: Scope = {
        "type": "http",
        "http_version": "1.1",
        "method": django_request.method,
        "headers": [
                       (key.lower().encode("latin-1"), value.encode("latin-1"))
                       for key, value in django_request.headers.items()
                       if key.lower() != "content-length"
                   ] + [("Content-Length", str(len(body)).encode("latin-1"))],
        "path": django_request.path,
        "raw_path": django_request.get_full_path().encode("utf-8"),
        "query_string": django_request.META["QUERY_STRING"].encode("latin-1"),
        "scheme": "https" if django_request.is_secure() else "http",
        "client": (django_request.META.get("REMOTE_ADDR"), 0),
        "server": (django_request.get_host(), django_request.get_port()),
    }

    async def receive() -> Receive:
        return {"type": "http.request", "body": body, "more_body": False}

    response_started: dict = {}
    response_body = bytearray()

    async def send(message: Send) -> None:
        if message["type"] == "http.response.start":
            response_started["status"] = message["status"]
            response_started["headers"] = Headers(raw=message["headers"])
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    # MUST use session_manager.run() context manager
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

    status = response_started.get("status", 500)
    headers = response_started.get("headers", {})

    response = HttpResponse(bytes(response_body), status=status)
    for key, value in headers.items():
        response[key] = value
    return response
```

### Key Differences from Current `view.py`

| Field | Current (BROKEN) | django-mcp-server (CORRECT) |
|-------|-----------------|-----------------------------|
| `"server"` | `("127.0.0.1", 8080)` hardcoded | `(request.get_host(), request.get_port())` |
| `"scheme"` | Missing | `"https" if request.is_secure() else "http"` |
| `"raw_path"` | Missing | `request.get_full_path().encode("utf-8")` |
| `"client"` | Missing | `(request.META.get("REMOTE_ADDR"), 0)` |
| `"Content-Length"` | Missing | Explicitly added (divides POST body) |
| `receive()` | Returns `{"body": b"", ...}` (empty body) | Uses actual request body |
| `session_manager.run()` | NOT called — just `asyncio.run(mcp_app(...))` | **MUST call `async with session_manager.run():`** |
| HTTP bridge | `asyncio.run(mcp_app(...))` | `async_to_sync(_call_starlette_handler)(request, session_manager)` |
| `csrf_exempt` | Missing | DRF view handles it via decorator |
| DRF request body | `request.body` raw bytes | `json.dumps(request.data, cls=DjangoJSONEncoder)` |

---

## `StreamableHTTPSessionManager` with `stateless=True`

**Source:** `mcp/server/streamable_http_manager.py`, `StreamableHTTPSessionManager` class

### Constructor

```python
class StreamableHTTPSessionManager:
    def __init__(
        self,
        app: MCPServer[Any, Any],
        event_store: EventStore | None = None,
        json_response: bool = False,
        stateless: bool = False,       # ← key parameter
        security_settings: TransportSecuritySettings | None = None,
        retry_interval: int | None = None,
    ):
        self.app = app
        self.event_store = event_store
        self.json_response = json_response
        self.stateless = stateless
        # Session tracking dict — only populated when stateless=False
        self._server_instances: dict[str, StreamableHTTPServerTransport] = {}
        self._session_creation_lock = anyio.Lock()
        self._task_group = None
        self._run_lock = anyio.Lock()
        self._has_started = False
```

### `run()` Context Manager (Critical — Must Be Used)

```python
@contextlib.asynccontextmanager
async def run(self) -> AsyncIterator[None]:
    """Creates task group for session operations. MUST be called before handle_request()."""
    async with self._run_lock:
        if self._has_started:
            raise RuntimeError(
                "StreamableHTTPSessionManager .run() can only be called "
                "once per instance. Create a new instance if you need to run again."
            )
        self._has_started = True

    async with anyio.create_task_group() as tg:
        self._task_group = tg
        yield
        tg.cancel_scope.cancel()
```

**`handle_request()` requires `run()` to be active:**

```python
async def handle_request(self, scope, receive, send) -> None:
    if self._task_group is None:
        raise RuntimeError("Task group is not initialized. Make sure to use run().")
    if self.stateless:
        await self._handle_stateless_request(scope, receive, send)
    else:
        await self._handle_stateful_request(scope, receive, send)
```

**Why `run()` is required:** In both stateless and stateful modes, `handle_request()` calls `await tg.start(run_server)` which **spawns the MCP server task** inside the task group. Without `run()`, there's no task group, and `handle_request()` raises `RuntimeError`.

### `stateless=True` vs `stateless=False`

| Behavior | `stateless=True` | `stateless=False` (current / correct) |
|----------|-------------------|----------------------------------------|
| Session ID header | Ignored (`mcp_session_id=None`) | Reads `Mcp-Session-Id`, creates new UUID if missing |
| Session transport store | `_server_instances` NOT used | Sessions persist across requests in `_server_instances[session_id]` |
| Event store | `event_store=None` | Uses `self.event_store` (may be None) |
| HTTP methods allowed | `["POST", "DELETE"]` only (GET = SSE streaming, no session to stream to) | `["GET", "POST", "DELETE"]` |
| Server task lifecycle | Created + terminated per request | Persists across requests in `_server_instances` |
| FastMCP `stateless=` arg | `stateless=True` passed to `app.run()` | `stateless=False` passed to `app.run()` |

### For `nautobot-app-mcp-server`: Keep `stateless_http=False`

The project needs session state for progressive disclosure. `stateless=True` would make session dicts ephemeral per-request — **undoing the very fix** being applied.

**CORRECT config (keep as-is in `server.py`):**
```python
_mcp_app = mcp_instance.http_app(
    path="/mcp",
    transport="streamable-http",
    stateless_http=False,  # ← Keep — need session state for progressive disclosure
    json_response=True,
)
```

---

## Auth Layer: Caching Patterns

### Current Auth (No Caching) — `mcp/auth.py`

```python
def get_user_from_request(ctx: ToolContext):
    ...
    token = Token.objects.select_related("user").get(key=real_token_key)
    return token.user
```

Each tool call → DB query. For batch MCP requests (multiple tool calls), this multiplies.

### Recommended Fix: MCP Session Cache

Cache on the MCP `request_context.session` dict — naturally scoped to the MCP session lifetime and survives `async_to_sync` (the same session dict is used across all tool calls in a session):

```python
def get_user_from_request(ctx: ToolContext):
    """Get cached user or look up token, caching on MCP session dict."""
    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")
    if not auth_header or not auth_header.startswith("Token "):
        return AnonymousUser()

    token_key = auth_header[6:]
    if not token_key.startswith(TOKEN_PREFIX):
        return AnonymousUser()
    real_token_key = token_key[len(TOKEN_PREFIX):]

    # Check MCP session cache first
    session = ctx.request_context.session
    if "cached_user" in session:
        return session["cached_user"]

    # DB lookup
    try:
        from nautobot.users.models import Token
        token = Token.objects.select_related("user").get(key=real_token_key)
        user = token.user
    except Exception:  # noqa: BLE001
        return AnonymousUser()

    # Store in MCP session cache
    session["cached_user"] = user
    return user
```

This is superior to thread-local or `lru_cache` because it naturally scopes to the MCP session (not the HTTP request — which may be short-lived in WSGI workers).

---

## Exact Import Changes for `view.py`

### Add These Imports

```python
from __future__ import annotations

import json                                    # ← ADD (for body serialization)
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync         # ← ADD (replaces asyncio)
from django.core.serializers.json import DjangoJSONEncoder  # ← ADD
from starlette.datastructures import Headers   # ← ADD (for ASGI send())
from starlette.types import Scope, Receive, Send  # ← ADD (ASGI type hints)
import contextvars                             # ← ADD (request context passthrough)
```

### Remove These Imports

```python
# REMOVE — asyncio.run() is the broken pattern that destroys sessions
import asyncio  # REMOVE from view.py
```

---

## Integration Points

### 1. `view.py` — Replace the Bridge Entirely

The entire `mcp_view()` function needs to be rewritten:
1. Build ASGI scope from Django request (mirror django-mcp-server)
2. Wrap `_call_starlette_handler` with `async_to_sync`
3. Return Django `HttpResponse`

The `session_manager.run()` context manager must be entered **inside** `_call_starlette_handler` (which is itself async), not outside.

### 2. `server.py` — Create `StreamableHTTPSessionManager` as a Module-Level Singleton

django-mcp-server creates `global_mcp_server = DjangoMCP(...)` at module level. For nautobot-app-mcp-server:

```python
# server.py — expose session manager alongside the ASGI app
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

_mcp_app: Starlette | None = None
_mcp_session_manager: StreamableHTTPSessionManager | None = None

def get_session_manager() -> StreamableHTTPSessionManager:
    """Lazily build the session manager + FastMCP app on first request."""
    global _mcp_session_manager, _mcp_app
    if _mcp_session_manager is None:
        mcp_instance = _setup_mcp_app()
        _mcp_session_manager = StreamableHTTPSessionManager(
            app=mcp_instance._mcp_server,
            event_store=None,
            json_response=True,
            stateless=False,  # Need state for progressive disclosure
        )
        _mcp_app = mcp_instance.http_app(
            path="/mcp",
            transport="streamable-http",
            stateless_http=False,
            json_response=True,
        )
    return _mcp_session_manager
```

Both `_mcp_session_manager` and `_mcp_app` are created atomically on first request.

### 3. `contextvars` for Django Request Pass-Through

django-mcp-server stores the Django request in a `contextvars.ContextVar` inside `_call_starlette_handler`:

```python
django_request_ctx: contextvars.ContextVar[HttpRequest] = contextvars.ContextVar(
    "django_request"
)

async def _call_starlette_handler(django_request, session_manager):
    django_request_ctx.set(django_request)  # ← available to async tool code
```

This allows async tool wrappers to reconstruct a Django-like request without depending on MCP internals. Currently, nautobot-app-mcp-server uses `ctx.request_context.request` (the MCP request object) — this is **still correct** and should be kept. The `contextvars` approach is only needed if you need the actual Django `HttpRequest` inside tool handlers.

### 4. `auth.py` — Add MCP Session Cache

Add session-level caching to `get_user_from_request()` to avoid per-tool-call DB lookups. Cache on `ctx.request_context.session["cached_user"]`.

---

## What NOT to Add

| Pattern | Why Avoid | Use Instead |
|---------|-----------|-------------|
| `asyncio.run()` in view | Destroys session state every request | `async_to_sync()` |
| `stateless=True` | Kills session state; reverts the fix | Keep `stateless=False` |
| `lru_cache` on `get_user_from_request` | No invalidation; thread-unsafe in WSGI thread pools | MCP session cache |
| DRF `APIView` | Over-engineered; Nautobot doesn't use DRF auth | Plain Django view + custom auth |
| `django_mcp_server` package | Opinionated tool registration (metaclass); not needed | Keep `MCPToolRegistry` singleton |
| `FastMCP.http_app()` called per-request | Factory method; should be called once | Module-level singleton (`_mcp_app`, `_mcp_session_manager`) |
| `run()` called twice on same `StreamableHTTPSessionManager` instance | Raises `RuntimeError: .run() can only be called once per instance` | One session manager instance, reused across requests |

### The `run()` Per-Request Trap — Explained

django-mcp-server calls `run()` inside `_call_starlette_handler`, which is itself wrapped in `async_to_sync`. Since `async_to_sync` runs in a **background thread with a persistent loop** (the ThreadPoolExecutor's loop stays alive until `loop_future.result()` returns), each HTTP request gets its own `run()` context entered and exited cleanly. The `run()` context manager exits after `handle_request()` completes, but the **same session manager instance** is reused on the next request — with a new `run()` call, which works because the ThreadPoolExecutor creates a fresh loop per `asyncio.run()` call inside `async_to_sync`.

---

## Version Compatibility

| Package | Version in Project | Compatible With | Notes |
|---------|-------------------|-----------------|-------|
| `fastmcp` | `^3.2.0` | `mcp>=1.8.0,<2.0.0` | Pins upper bound on `mcp` at `<2.0` |
| `mcp` (transitive) | from fastmcp | `StreamableHTTPSessionManager` API stable | Source-verified in `.venv/.../mcp/server/streamable_http_manager.py` |
| `asgiref` | ships with Django / fastmcp | `async_to_sync` stable since asgiref 1.x | Source-verified in `.venv/.../asgiref/sync.py` |
| `starlette` | ships with fastmcp | `Headers`, `Scope`, `Receive`, `Send` stable | Source-verified in django-mcp-server usage |
| Django | `>=3.0,<4.0` | `DjangoJSONEncoder`, `HttpRequest`, session backends | Already installed via Nautobot dep |

---

## Sources

- `mcp/server/streamable_http_manager.py` (mcp SDK, installed via fastmcp) — `StreamableHTTPSessionManager.__init__`, `run()`, `handle_request()`, `_handle_stateless_request()`, `_handle_stateful_request()` — **source-verified**
- `asgiref/sync.py` (installed via Django) — `AsyncToSync.__call__` (lines 211–325), `main_wrap` pattern, ThreadPoolExecutor + asyncio.run usage — **source-verified**
- `mcp_server/djangomcp.py` (django-mcp-server v0.5.6, github.com/gts360/django-mcp-server) — `_call_starlette_handler`, `DjangoMCP.handle_django_request`, `session_manager` property, `async_to_sync` usage — **source-verified via WebFetch**
- `mcp_server/views.py` (django-mcp-server v0.5.6) — `MCPServerStreamableHttpView`, `csrf_exempt`, DRF APIView pattern — **source-verified via WebFetch**
- `pyproject.toml` — existing dependency versions: `fastmcp = "^3.2.0"`, `python = ">=3.10,<3.15"`
- `docs/dev/mcp-implementation-analysis.md` — architecture analysis, P0/P1 issue triage (source-verified)
- `nautobot_app_mcp_server/mcp/server.py` — current broken `get_mcp_app()` implementation (source-verified)
- `nautobot_app_mcp_server/mcp/view.py` — current broken `asyncio.run()` bridge (source-verified)

---

## GSD Execution Notes

For the v1.1.0 refactor, the **exact changes needed** in `view.py`:

1. **Add imports:** `async_to_sync`, `Headers`, `Scope/Receive/Send`, `DjangoJSONEncoder`, `json`, `contextvars`
2. **Remove** `import asyncio`
3. **Define** `django_request_ctx` as a module-level `contextvars.ContextVar`
4. **Define** `_call_starlette_handler` async function (mirror django-mcp-server's)
5. **In `mcp_view`:** Replace `asyncio.run(mcp_app(...))` with `async_to_sync(_call_starlette_handler)(request, session_manager)`
6. **Expose** `get_session_manager()` from `server.py` and call it in `view.py`
7. **In `server.py`:** Create `StreamableHTTPSessionManager` alongside the app factory, store as module-level singleton

The `session_manager.run()` is called **inside** `_call_starlette_handler` (which is wrapped by `async_to_sync`). The `run()` context is entered and exited per request — this is the correct pattern from django-mcp-server.

In `auth.py`: add session-level caching using `ctx.request_context.session["cached_user"]` to avoid per-tool-call DB lookups.
