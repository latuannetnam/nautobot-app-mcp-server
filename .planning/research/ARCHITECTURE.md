# Architecture Research — django-mcp-server Deep Dive

**Domain:** Embedded FastMCP server in Django (WSGI→ASGI bridge, session persistence)
**Researched:** 2026-04-03
**Confidence:** HIGH (verified via direct source extraction from GitHub)

## Source

- Repo: `https://github.com/gts360/django-mcp-server` (fork of `omarbenhamid/django-mcp-server`)
- Files read: `mcp_server/djangomcp.py`, `mcp_server/views.py`, `mcp_server/urls.py`
- All quotes are verbatim from source; diagrams are reconstructed from code behavior

---

## 1. django-mcp-server Architecture

### System Overview

```
MCPServerStreamableHttpView (DRF APIView — get/post/delete)
│
├── Django URL Router  →  path("mcp/", MCPServerStreamableHttpView.as_view(...))
│
├── MCPServerStreamableHttpView.get/post(request)
│       │
│       └── self.mcp_server.handle_django_request(request)
│               │
│               ├── Read Mcp-Session-Id header
│               ├── Load Django SessionStore (or create new)
│               ├── request.session = session
│               │
│               └── async_to_sync(_call_starlette_handler)(request, session_manager)
│                       │
│                       ├── django_request_ctx.set(django_request)  [contextvars]
│                       ├── Build ASGI scope dict
│                       ├── receive(): returns request body bytes
│                       ├── send(): collects response_start + response_body
│                       │
│                       └── async with session_manager.run():
│                               └── await session_manager.handle_request(scope, receive, send)
│                                       │
│                                       ├── FastMCP protocol handler
│                                       ├── Server.request_context.set(ctx)  ← ACTIVE HERE
│                                       │
│                                       ├── POST /mcp/ tools/call  →  tool execution
│                                       │       └── Server.request_context.get() → session → scopes
│                                       │
│                                       └── response assembled → send() called
│
└── On exit: session.save(); result.headers["Mcp-Session-Id"] = session_key
```

---

## 2. Six Questions Answered from Source

### Q1: The Bridge — How `MCPServerStreamableHttpView` Handles a Django Request

**File:** `mcp_server/views.py`

```python
@method_decorator(csrf_exempt, name='dispatch')
class MCPServerStreamableHttpView(APIView):
    mcp_server = global_mcp_server

    def get(self, request, *args, **kwargs):
        return self.mcp_server.handle_django_request(request)

    def post(self, request, *args, **kwargs):
        return self.mcp_server.handle_django_request(request)

    def delete(self, request, *args, **kwargs):
        self.mcp_server.destroy_session(request)
        return HttpResponse(status=200, content="Session destroyed")
```

**File:** `mcp_server/djangomcp.py` — `handle_django_request()`

```python
def handle_django_request(self, request):
    if not self.stateless:
        session_key = request.headers.get(MCP_SESSION_ID_HDR)
        if session_key:
            session = self.SessionStore(session_key)
            if session.exists(session_key):
                request.session = session
            else:
                return HttpResponse(status=404, content="Session not found")
        elif request.data.get('method') == 'initialize':
            request.session = self.SessionStore()   # new session for initialize
        else:
            return HttpResponse(status=400, content="Session required for stateful server")

    result = async_to_sync(_call_starlette_handler)(request, self.session_manager)

    # Persist session after async call completes
    if not self.stateless and hasattr(request, "session"):
        request.session.save()
        result.headers[MCP_SESSION_ID_HDR] = request.session.session_key
        delattr(request, "session")

    return result
```

**What it passes to the session manager:** `StreamableHTTPSessionManager(app=self._mcp_server, event_store=self._event_store, json_response=True, stateless=True)`. The session manager itself is passed as the second argument to `_call_starlette_handler`, which calls `session_manager.handle_request(scope, receive, send)` inside an `async with session_manager.run():` block.

The Django `request.session` object is **pre-loaded** before calling the async handler. Django's session middleware has already deserialized the session from cookie/database. The `Mcp-Session-Id` header is the lookup key. The `request.session` object is passed to tools via `django_request_ctx.get()` (see Q4).

---

### Q2: ASGI Scope Building

**File:** `mcp_server/djangomcp.py` — `_call_starlette_handler()`, lines 65–79

```python
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
```

| Field | Source | Notes |
|-------|--------|-------|
| `type` | Constant `"http"` | Required by ASGI spec |
| `http_version` | Constant `"1.1"` | Could be `"1.0"` for HTTP/1.0 requests |
| `method` | `django_request.method` | GET, POST, DELETE |
| `headers` | `django_request.headers.items()` | Lowercased keys, `latin-1` encoded |
| `path` | `django_request.path` | Full path including plugin prefix |
| `raw_path` | `django_request.get_full_path().encode("utf-8")` | Path + query string as bytes |
| `query_string` | `django_request.META["QUERY_STRING"].encode("latin-1")` | Raw query string bytes |
| `scheme` | `django_request.is_secure()` ternary | `"https"` or `"http"` |
| `client` | `django_request.META.get("REMOTE_ADDR")` | Tuple: (host, port=0) |
| `server` | `(django_request.get_host(), django_request.get_port())` | Derived from Host header |

**Note:** `root_path` is **not** included. The MCP path routing is handled by the session manager, not by path prefix stripping.

**Current implementation vs. django-mcp-server:**
```python
# Current (BROKEN — asyncio.run destroys session):
scope = {
    "type": "http",
    "asgi": {"version": "3.0"},
    "http_version": "1.1",
    "method": request.method,
    "query_string": request.META.get("QUERY_STRING", "").encode("utf-8"),
    "root_path": plugin_prefix,      # ← NOT in django-mcp-server
    "path": mcp_path,                # ← Stripped prefix
    "headers": [...],
    "server": ("127.0.0.1", 8080),   # ← HARDCODED (should be request.get_host())
}
# asyncio.run(mcp_app(scope, receive, send))  ← WRONG

# Should be:
# async_to_sync(_call_starlette_handler)(request, session_manager)
# Inside _call_starlette_handler, FastMCP routes via session_manager.handle_request()
```

---

### Q3: `async_to_sync` Usage

**File:** `mcp_server/djangomcp.py`, `handle_django_request()` line:

```python
result = async_to_sync(_call_starlette_handler)(request, self.session_manager)
```

**The async function it calls — `_call_starlette_handler()`:**

```python
async def _call_starlette_handler(django_request, session_manager):
    django_request_ctx.set(django_request)   # contextvars — accessible in sync tool calls
    body = json.dumps(django_request.data, cls=DjangoJSONEncoder).encode("utf-8")

    scope: Scope = { ... }   # ASGI scope built from Django request

    async def receive() -> Receive:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    response_started = {}
    response_body = bytearray()

    async def send(message: Send):
        if message["type"] == "http.response.start":
            response_started["status"] = message["status"]
            response_started["headers"] = Headers(raw=message["headers"])
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    async with session_manager.run():          # ← ENTERS FastMCP session context
        await session_manager.handle_request(scope, receive, send)

    status = response_started.get("status", 500)
    headers = response_started.get("headers", {})
    response = HttpResponse(bytes(response_body), status=status)
    for key, value in headers.items():
        response[key] = value
    return response
```

**Critical difference from current implementation:**

```
# Current (BROKEN):
asyncio.run(mcp_app(scope, receive, send))
  → Creates NEW event loop
  → Executes mcp_app() coroutine
  → CLOSES loop → destroys Server.request_context, session dict
  → Next request: fresh loop, fresh session store, session state gone

# django-mcp-server (CORRECT):
async_to_sync(_call_starlette_handler)(request, session_manager)
  → Uses existing event loop (or creates one on current thread, doesn't close it)
  → session_manager.run() enters FastMCP's Server.request_context
  → Server.request_context.get() works inside tool handlers
  → Loop stays alive → session dict persists across requests
```

`asgiref.sync.async_to_sync` creates a new event loop only if one doesn't already exist on the thread, and it **does not close the loop after**. This preserves FastMCP's in-memory session store.

---

### Q4: Session State Flow

**Django-side session → MCP request context:**

```python
# djangomcp.py — django_request_ctx is a contextvars.ContextVar
django_request_ctx = contextvars.ContextVar("django_request")

# Stored at the start of _call_starlette_handler
django_request_ctx.set(django_request)

# Accessed in tool execution path via _ToolsetMethodCaller
class _ToolsetMethodCaller:
    def __call__(self, *args, **kwargs):
        instance = self.class_(
            context=kwargs[self.context_kwarg],
            request=django_request_ctx.get(SimpleNamespace)   # ← gets Django request here
        )
        method = sync_to_async(_SyncToolCallWrapper(getattr(instance, self.method_name)))
        return method(*args, **kwargs)
```

**MCP session state → FastMCP protocol:**

`StreamableHTTPSessionManager` stores FastMCP sessions in its own `self.sessions` dict (in-memory). The `Mcp-Session-Id` header (passed by the MCP client, NOT by django-mcp-server) is the FastMCP session key. The Django session is separate — it stores application-level data, not MCP protocol session data.

django-mcp-server uses `stateless=True` on the session manager, meaning FastMCP does NOT manage its own session store. Instead, the Django `SessionStore` (cookie/database-backed) is the session store. On each request:
1. `Mcp-Session-Id` header → load Django `SessionStore`
2. `request.session` is the Django session
3. FastMCP tool handlers access session data via `Server.request_context.get().session`

**For nautobot-app-mcp-server:** Using `stateless_http=False` with `async_to_sync` means FastMCP's own in-memory `sessions` dict is the session store. State persists because the event loop is not destroyed. The `Mcp-Session-Id` header is managed by FastMCP's `StreamableHTTPSessionManager`.

---

### Q5: How `Server.request_context.get()` Works Correctly

**The key:** `async with session_manager.run():` + FastMCP's internal `Server.request_context.set(ctx)`.

Inside `StreamableHTTPSessionManager.handle_request()`, FastMCP calls:
```python
async with self.run():
    await self._mcp_server.run(...)   # protocol handler
```

The `self.run()` context manager sets `Server.request_context.set(ctx)` where `ctx` is a `RequestContext` containing the current `ServerSession`. This is what makes `Server.request_context.get()` return a valid object instead of raising `LookupError`.

**How current implementation fails:**

```python
# Current: asyncio.run() destroys the context immediately after mcp_app() returns
asyncio.run(mcp_app(scope, receive, send))
# → mcp_app() calls session_manager.handle_request(scope, receive, send)
# → Inside handle_request(), Server.request_context.set(ctx) is called
# → But as soon as mcp_app() returns, asyncio.run() closes the loop
# → Server.request_context ContextVar is cleared
# → On next request: new loop → LookupError raised

# What happens inside progressive_list_tools_mcp:
async def progressive_list_tools_mcp(request=None):
    try:
        req_ctx = Server.request_context.get()  # LookupError — every time!
        ...
    except LookupError:
        pass  # falls through to empty session_dict
```

**Fix:** Use `async with session_manager.run():` + `async_to_sync`. The loop stays alive, `Server.request_context` ContextVar persists:

```python
async def _call_starlette_handler(django_request, session_manager):
    ...
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)
    # Server.request_context.set(ctx) is active during the entire handle_request()
    # → Server.request_context.get() works inside tool handlers
```

With this pattern, `progressive_list_tools_mcp` can successfully call `Server.request_context.get()` and get the real session (not a `LookupError`).

---

### Q6: Thread Safety — Singleton Initialization

**django-mcp-server approach:** Module-level plain singleton, not lazy.

```python
# djangomcp.py
global_mcp_server = DjangoMCP(**getattr(settings, 'DJANGO_MCP_GLOBAL_SERVER_CONFIG', {}))
```

```python
# views.py
class MCPServerStreamableHttpView(APIView):
    mcp_server = global_mcp_server   # class attribute, references same object
```

**Why this works for thread safety:** Django's WSGI workers either:
- **Prefork mode (gunicorn workers):** Each worker is a separate OS process. No shared memory issues.
- **Threaded mode:** The `global_mcp_server` is created once at module import (before workers fork), so all threads share the same object. No race condition because Python GIL makes the assignment atomic, and the object is immutable after creation.

**nautobot-app-mcp-server's issue:** Lazy initialization (`get_mcp_app()` called on first request) with no lock. Two concurrent first requests (before `_mcp_app` is set) could both see `_mcp_app is None` and create duplicate instances. Only one survives (last write wins), but the wasted instance leaks.

**Fix:** Add `threading.Lock` double-checked locking:
```python
import threading

_lock = threading.Lock()

def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _lock:
            if _mcp_app is None:   # double-check
                mcp_instance = _setup_mcp_app()
                _mcp_app = mcp_instance.http_app(...)
    return _mcp_app
```

---

## 3. Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| **Django view (entry)** | `mcp_server/views.py` | Route GET/POST/DELETE; `@csrf_exempt`; DRF APIView |
| **DjangoMCP (orchestrator)** | `mcp_server/djangomcp.py` | Session store init; `handle_django_request()`; DRF tool registration |
| **`_call_starlette_handler`** | `mcp_server/djangomcp.py` | ASGI scope build; `async with session_manager.run()`; receive/send; `contextvars` for Django request |
| **`StreamableHTTPSessionManager`** | `mcp.server.streamable_http_manager` (FastMCP) | Session lifecycle; `Server.request_context` context manager; protocol routing |
| **`DjangoMCP.session_manager`** | Property in `DjangoMCP` | `StreamableHTTPSessionManager(app=self._mcp_server, stateless=True)` |
| **`django_request_ctx`** | `contextvars.ContextVar` | Thread-safe carrier of Django request object into async/sync tool calls |
| **`MCPToolset`** | `mcp_server/djangomcp.py` | Metaclass registry; auto-publishes public methods as MCP tools |
| **`global_mcp_server`** | Module-level singleton | Module-level DjangoMCP instance, no lazy init, no lock needed |

---

## 4. Data Flow: django-mcp-server vs. nautobot-app-mcp-server

```
# django-mcp-server (CORRECT)

Django request
    ↓
MCPServerStreamableHttpView.get/post(request)
    ↓
DjangoMCP.handle_django_request(request)
    ├── Read Mcp-Session-Id header → Django SessionStore
    ├── request.session = session
    ↓
async_to_sync(_call_starlette_handler)(request, session_manager)
    ├── django_request_ctx.set(request)         [contextvars]
    ├── Build ASGI scope dict
    ├── async def receive(): return {body}
    ├── async def send(message): collect messages
    ↓
async with session_manager.run():               [ENTER Server.request_context]
    await session_manager.handle_request(scope, receive, send)
        ├── FastMCP protocol
        ├── Server.request_context.set(ctx)     [ACTIVE HERE]
        │
        ├── tools/list → _list_tools_mcp → Server.request_context.get() ✓
        │                    └── MCPToolRegistry.get_all() → filtered by session
        │
        └── tools/call → tool handler
              ├── Server.request_context.get().session ✓
              └── sync_to_async(tool_fn)()
    ↓
session.save()
result.headers["Mcp-Session-Id"] = session.session_key
    ↓
Django HttpResponse


# nautobot-app-mcp-server (BROKEN — asyncio.run)

Django request
    ↓
mcp_view(request)
    ↓
get_mcp_app()  →  mcp_instance.http_app(...)
    ↓
asyncio.run(mcp_app(scope, receive, send))     [WRONG: destroys loop]
    ├── mcp_app() calls session_manager.handle_request()
    │     └── Server.request_context.set(ctx)
    ├── Server.request_context.get() → ✓ works INSIDE handle_request
    │     └── progressive_list_tools_mcp → session → scopes ✓
    │
    └── asyncio.run() closes loop → Server.request_context cleared
    ↓
Next request: asyncio.run() creates NEW loop
    └── Server.request_context.get() → LookupError ❌
        └── session_dict = {} → empty scopes → all tools shown
```

---

## 5. Key Code Patterns to Borrow

### Pattern 1: `async_to_sync` Bridge (FIX for `asyncio.run()`)

```python
from asgiref.sync import async_to_sync

async def _call_starlette_handler(django_request, session_manager):
    """Bridge: Django request → ASGI → session_manager → Django response."""
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": django_request.method,
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in django_request.headers.items()
            if key.lower() != "content-length"
        ],
        "path": django_request.path,
        "raw_path": django_request.get_full_path().encode("utf-8"),
        "query_string": django_request.META["QUERY_STRING"].encode("latin-1"),
        "scheme": "https" if django_request.is_secure() else "http",
        "client": (django_request.META.get("REMOTE_ADDR"), 0),
        "server": (django_request.get_host(), django_request.get_port()),
    }

    body = django_request.body  # raw bytes — use directly

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    response_started = {}
    response_body = bytearray()

    async def send(message):
        if message["type"] == "http.response.start":
            response_started["status"] = message["status"]
            response_started["headers"] = message["headers"]
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

    return response_body, response_started.get("status", 200), response_started.get("headers", [])


def handle_django_request(request):
    session_manager = get_session_manager()   # from server.py
    body, status, headers = async_to_sync(_call_starlette_handler)(request, session_manager)
    response = HttpResponse(bytes(body), status=status)
    for k, v in headers:
        response[bytes(k).decode()] = bytes(v).decode()
    return response
```

### Pattern 2: `session_manager.run()` Context Manager (makes `Server.request_context` work)

```python
# Inside _call_starlette_handler (async function):
async with session_manager.run():
    await session_manager.handle_request(scope, receive, send)
# session_manager.run() sets Server.request_context for the duration of handle_request()
# All tool handlers called within handle_request() can use Server.request_context.get()
```

### Pattern 3: Thread-Safe Lazy Singleton

```python
import threading

_mcp_app: Starlette | None = None
_lock = threading.Lock()

def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _lock:
            if _mcp_app is None:   # double-checked locking
                mcp_instance = _setup_mcp_app()
                _mcp_app = mcp_instance.http_app(...)
    return _mcp_app
```

### Pattern 4: Deriving Server Address from Request

```python
"server": (django_request.get_host(), django_request.get_port()),
"scheme": "https" if django_request.is_secure() else "http",
"client": (django_request.META.get("REMOTE_ADDR"), 0),
```

---

## 6. Integration Points

### External vs. Internal in django-mcp-server

| Boundary | Communication | django-mcp-server pattern |
|----------|---------------|---------------------------|
| `MCPServerStreamableHttpView` → `DjangoMCP` | Method call: `handle_django_request(request)` | View calls orchestrator |
| `DjangoMCP` → `_call_starlette_handler` | `async_to_sync()` | Bridges WSGI → ASGI |
| `_call_starlette_handler` → `StreamableHTTPSessionManager` | `session_manager.run()` + `handle_request()` | Enters FastMCP protocol context |
| `StreamableHTTPSessionManager` → `FastMCP` | FastMCP internal | `Server.request_context.set()` called here |
| Tool handler → Django request | `django_request_ctx.get()` | `contextvars` carries Django request to async tools |

### What Changes in nautobot-app-mcp-server

| File | Change | Why |
|------|--------|-----|
| `mcp/view.py` | Replace `asyncio.run()` with `async_to_sync(_call_starlette_handler)(request, session_manager)` | Fixes session persistence |
| `mcp/view.py` | Build ASGI scope using `request.get_host()` / `request.get_port()` | Correct server address |
| `mcp/view.py` | Use `async with session_manager.run():` wrapper | Makes `Server.request_context.get()` work |
| `mcp/server.py` | Add `threading.Lock` double-checked locking in `get_mcp_app()` | Fixes singleton race condition |
| `mcp/server.py` | Expose `get_session_manager()` for view.py | Session manager from server.py to view.py |

---

## 7. Anti-Patterns Confirmed by Source

### Anti-Pattern: `asyncio.run()` in a WSGI Django view

**Why it breaks:** `asyncio.run()` creates a new loop, runs the coroutine, then **closes the loop**. This destroys:
1. FastMCP's `Server.request_context` ContextVar (set during `handle_request`)
2. FastMCP's in-memory `sessions` dict (same-process, same-loop sessions)
3. Any `contextvars.ContextVar` set inside the async code

**Confirmed by:** `django-mcp-server` explicitly uses `async_to_sync` and `async with session_manager.run()` — never `asyncio.run()` inside a Django request handler.

### Anti-Pattern: Accessing `Server.request_context` without `session_manager.run()`

**Confirmed by:** FastMCP's `Server.request_context` is a `ContextVar` (not a global). It is only set when inside `session_manager.run()`. Calling `Server.request_context.get()` outside that context manager raises `LookupError`. The current `progressive_list_tools_mcp` hits this on every request.

---

## 8. Sources

- `mcp_server/djangomcp.py` — `DjangoMCP.handle_django_request()`, `_call_starlette_handler()`, `StreamableHTTPSessionManager` usage (source: `gh api repos/gts360/django-mcp-server/contents/mcp_server/djangomcp.py | jq -r '.content' | base64 -d`)
- `mcp_server/views.py` — `MCPServerStreamableHttpView` (source: `gh api repos/gts360/django-mcp-server/contents/mcp_server/views.py | jq -r '.content' | base64 -d`)
- `mcp_server/urls.py` — URL routing with DRF authentication classes (source: `gh api repos/gts360/django-mcp-server/contents/mcp_server/urls.py | jq -r '.content' | base64 -d`)
- `docs/dev/mcp-implementation-analysis.md` — existing analysis of session state issues
- `nautobot_app_mcp_server/mcp/server.py` — current broken implementation
- `nautobot_app_mcp_server/mcp/view.py` — current broken asyncio.run() bridge

---
*Architecture research for: django-mcp-server → nautobot-app-mcp-server refactor*
*Researched: 2026-04-03*
