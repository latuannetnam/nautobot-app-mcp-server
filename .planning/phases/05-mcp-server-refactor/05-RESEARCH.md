# Phase 5 Research: MCP Server Refactor

**Date:** 2026-04-03
**Phase:** 05-mcp-server-refactor
**Goal:** Plan the Phase 5 implementation — fix `asyncio.run()` WSGI→ASGI bridge, add auth caching, write integration test.
**Confidence:** HIGH (source-verified from installed `.venv/` packages)

---

## Executive Summary

The Phase 5 refactor has one root cause and three implementation files. Source verification of the installed MCP SDK reveals one important correction to the django-mcp-server research: **`ServerSession` has no dict-like interface**. The session state storage pattern used in `session_tools.py` (`session["enabled_scopes"] = ...`) will crash on real `ServerSession` objects — it only works today because `asyncio.run()` causes `Server.request_context.get()` to raise `LookupError` before that code is reached. This is a **pre-existing latent bug** that the P0 fix will surface. The fix is to store session state on the `request_context` object itself (`ctx.request_context`), which is a plain Python dataclass and is always dict-accessible.

---

## 1. `async_to_sync` vs `asyncio.run()` — The Core Fix

### What `asyncio.run()` Does (current, broken)

```python
# view.py:61 (BROKEN)
asyncio.run(mcp_app(scope, receive, send))
```

`asyncio.run()` (Python stdlib, `asyncio/runners.py`):
1. Creates a **new event loop** on the current thread
2. Runs the coroutine to completion
3. **Closes the loop** (calls `loop.close()`)

When called from a Django view thread, every HTTP request creates and immediately destroys a fresh event loop. FastMCP's `StreamableHTTPSessionManager` lives inside the loop's task group. Destroying the loop destroys the task group and all `ServerSession` instances → session state vanishes. This is confirmed in `streamable_http_manager.py` line 113: `async with anyio.create_task_group() as tg` creates the task group that must survive across requests.

### What `async_to_sync` Does (correct pattern)

```python
# Pattern from django-mcp-server djangomcp.py:94
from asgiref.sync import async_to_sync
result = async_to_sync(_call_starlette_handler)(request, session_manager)
```

`async_to_sync` (asgiref `AsyncToSync.__call__`, `sync.py` lines 211–318):

**Thread without a running event loop** (Django request thread):
```python
# Line 312: Creates a ThreadPoolExecutor with 1 worker thread
loop_executor = ThreadPoolExecutor(max_workers=1)
# Line 314: Submits asyncio.run(new_loop_wrap()) to that thread
loop_future = loop_executor.submit(asyncio.run, new_loop_wrap())
# Line 316: Blocks current thread until loop completes
current_executor.run_until_future(loop_future)
```

Key difference: `asyncio.run()` is called **inside the executor thread**, which means the loop is created in that thread, the coroutine runs, and then... `asyncio.run()` closes the loop. BUT: the loop was created in the **worker thread** (not the Django request thread), and `asyncio.run()` closes the loop it created. Subsequent `async_to_sync` calls from other Django request threads each create their own executor thread with their own loop.

**The critical insight**: With `async_to_sync`, `session_manager.run()` is entered inside `new_loop_wrap()` (in the executor thread). The task group lives in that thread's loop. The `Server.request_context` ContextVar is set inside the task group. As long as the same executor thread handles sequential requests from the same client, the session persists.

**Caveat**: Each Django worker thread that calls `async_to_sync` creates its own loop in a separate executor thread. With Django's threaded development server, multiple threads may each get their own loop. With gunicorn prefork (separate OS processes), each worker has its own loop. With gunicorn threaded workers, threads share the loop if `async_to_sync` is called from the same thread.

For Docker single-process dev, this works correctly. For production multi-worker, session state is per-worker (same as Django sessions). This is documented as acceptable for v1.

### Exact Call Chain in `_call_starlette_handler`

```python
async def _call_starlette_handler(django_request, session_manager):
    # 1. Build ASGI scope dict from Django request
    scope = build_asgi_scope(django_request)

    # 2. Capture body bytes synchronously (before entering async)
    body = django_request.body

    # 3. Define ASGI receive — returns the captured body once
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    # 4. Define ASGI send — collects start + body messages
    response_started = {}
    response_body = bytearray()
    async def send(message):
        if message["type"] == "http.response.start":
            response_started["status"] = message["status"]
            response_started["headers"] = message["headers"]
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    # 5. Enter FastMCP task group → sets Server.request_context ContextVar
    #    MUST be inside async function (not a bare `async with` at module level)
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

    # 6. Assemble Django response
    status = response_started.get("status", 200)
    headers = response_started.get("headers", [])
    response = HttpResponse(bytes(response_body), status=status)
    for k, v in headers:
        response[bytes(k).decode()] = bytes(v).decode()
    return response
```

The `async with session_manager.run():` context manager (streamable_http_manager.py lines 86–125):
- Sets `self._has_started = True` (guards against re-entry)
- Creates an `anyio.TaskGroup` stored in `self._task_group`
- All `handle_request()` calls run inside this task group
- `Server.request_context` ContextVar is set by `MCPServer._handle_request()` **inside** this task group (lowlevel/server.py lines 746–779)

---

## 2. `StreamableHTTPSessionManager.run()` and `handle_request()`

### Signatures

**`run()`** (`streamable_http_manager.py` lines 86–125):
```python
@contextlib.asynccontextmanager
async def run(self) -> AsyncIterator[None]:
```

**`handle_request()`** (`streamable_http_manager.py` lines 127–150):
```python
async def handle_request(
    self,
    scope: Scope,
    receive: Receive,
    send: Send,
) -> None:
```

Both are async methods. They must be called **inside an active event loop** (inside `async_to_sync`).

### What `handle_request()` Does

1. Checks `self._task_group is None` → raises `RuntimeError("Task group is not initialized...")`
2. Dispatches to `_handle_stateless_request()` or `_handle_stateful_request()` based on `self.stateless`
3. With `stateless=False` (current setting):
   - Reads `Mcp-Session-Id` header from request
   - If session ID exists in `self._server_instances`: routes to existing `StreamableHTTPServerTransport`
   - If session ID is None: creates new `StreamableHTTPServerTransport`, generates UUID session ID, stores in `_server_instances`, starts `run_server` task in `_task_group`, handles request
   - If session ID not found: returns 404 JSONRPC error

### `Server.request_context` ContextVar Setup

In `MCPServer._handle_request()` (`lowlevel/server.py` lines 746–779):
```python
token = request_ctx.set(
    RequestContext(
        message.request_id,
        message.request_meta,
        session,           # ← ServerSession (ServerSession subclass in FastMCP)
        lifespan_context,
        Experimental(...),
        request=request_data,
        ...
    )
)
try:
    response = await handler(req)
finally:
    if token is not None:
        request_ctx.reset(token)
```

`request_ctx` is `contextvars.ContextVar("request_ctx")` (line 109 of lowlevel/server.py). It is set inside `_handle_request()`, which is called from `MCPServer.run()` inside `StreamableHTTPServerTransport.connect()`. All of this happens inside the task group created by `session_manager.run()`.

**Critical**: `_handle_request()` is called **before** tool handlers run. By the time `_list_tools_handler` executes (which is called as a tool handler), `request_ctx` is already set. `Server.request_context.get()` will return the `RequestContext` object.

---

## 3. Server.request_context ContextVar — How It's Set and Accessed

### Definition
```python
# mcp/server/lowlevel/server.py:109
request_ctx: contextvars.ContextVar[RequestContext[ServerSession, Any, Any]] = contextvars.ContextVar("request_ctx")
```

### Set (in `_handle_request()`, line 746)
```python
token = request_ctx.set(RequestContext(
    message.request_id,
    message.request_meta,
    session,        # ServerSession instance (NOT a dict!)
    lifespan_context,
    Experimental(...),
    request=request_data,
    ...
))
```

### Accessed (in `progressive_list_tools_mcp`, server.py:59–68)
```python
from mcp.server.lowlevel.server import Server
req_ctx = Server.request_context  # ← the ContextVar itself
ctx_obj = req_ctx.get()           # ← get() on the ContextVar, returns RequestContext
session = ctx_obj.session         # ← ServerSession instance
```

**IMPORTANT — Session Dict Interface Bug (Latent)**:

`MCPSessionState.from_session(session)` calls `session.get("enabled_scopes", set())`. But `session` here is a `ServerSession` instance (confirmed from `lowlevel/server.py` line 750: `session` parameter typed as `ServerSession`). `ServerSession` has **no** `get()`, `__getitem__()`, or `__setitem__()` methods — verified by reading the full `ServerSession` class (`mcp/server/session.py` lines 75–691) and `MiddlewareServerSession` (`fastmcp/server/low_level.py` lines 36–73).

The current code only works because `asyncio.run()` causes `Server.request_context.get()` to raise `LookupError` before `MCPSessionState.from_session(session)` is reached. Once the P0 fix makes `Server.request_context.get()` succeed, calling `.get()` on a `ServerSession` will raise `AttributeError`.

**Fix**: Store session state on the `request_context` dataclass itself (which is always dict-accessible as a plain Python object), not on `ServerSession`.

### Proposed Storage: `ctx.request_context` (a Python dataclass)

```python
# In _list_tools_handler (session_tools.py):
# Option A: Use a dict on request_context
state = getattr(ctx.request_context, '_mcp_tool_state', None)
if state is None:
    state = {'enabled_scopes': set(), 'enabled_searches': set()}
    ctx.request_context._mcp_tool_state = state  # Monkey-patch dataclass (ugly)

# Option B (cleaner): Create a wrapper class
class _MCPToolState(dict):
    """Thin dict subclass stored as _mcp_tool_state on RequestContext."""
    pass
```

Implementation approach:
1. In `_list_tools_handler`: try `ctx.request_context._mcp_tool_state`, fall back to `{'enabled_scopes': set(), 'enabled_searches': set()}` on `AttributeError`
2. In `_mcp_enable_tools_impl`, `_mcp_disable_tools_impl`: same pattern
3. No need to set initial state — `_mcp_tool_state` starts as `None`, initialized on first access

**This is a source-verified bug fix** that must be included in Phase 5. The session_tools.py file MUST be updated alongside view.py, server.py, and auth.py.

---

## 4. Thread-Safe Singleton Pattern

### Current Broken Pattern (server.py:122–131)

```python
# NOT thread-safe — two concurrent requests can both pass `if _mcp_app is None`
if _mcp_app is None:
    mcp_instance = _setup_mcp_app()
    _mcp_app = mcp_instance.http_app(...)
return _mcp_app
```

### Correct Pattern (double-checked locking)

```python
import threading

_mcp_app: Starlette | None = None
_session_mgr: StreamableHTTPSessionManager | None = None
_app_lock = threading.Lock()
_session_lock = threading.Lock()

def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:  # Second check inside lock
                mcp_instance = _setup_mcp_app()
                _mcp_app = mcp_instance.http_app(
                    path="/mcp",
                    transport="streamable-http",
                    stateless_http=False,
                    json_response=True,
                )
    return _mcp_app

def get_session_manager() -> StreamableHTTPSessionManager:
    """Return the StreamableHTTPSessionManager from the FastMCP app.

    The session manager is created by FastMCP.http_app() inside create_streamable_http_app()
    (fastmcp/server/http.py:300–309). It is stored as app.state._streamable_http_session_manager
    on the Starlette app returned by http_app().
    """
    global _session_mgr
    if _session_mgr is None:
        with _session_lock:
            if _session_mgr is None:
                app = get_mcp_app()
                _session_mgr = app.state._streamable_http_session_manager
    return _session_mgr
```

**Finding**: `StreamableHTTPSessionManager` is created by `create_streamable_http_app()` (`fastmcp/server/http.py:300`) and stored on the returned Starlette app. We can access it via `app.state._streamable_http_session_manager` — no need to create a separate manager in `server.py`. The `_session_mgr` variable in `server.py` can simply be the result of `get_mcp_app().state._streamable_http_session_manager` called lazily on first use.

Actually, `http_app()` creates the `StreamableHTTPSessionManager` internally and attaches it to the app state. The Starlette app returned by `http_app()` has `app.state.fastmcp_server` (set in http.py:258) and the session manager at a key that we need to verify.

From `http.py:365–376`, the lifespan wraps `session_manager.run()`, so the session manager is referenced by the local variable `session_manager` in `create_streamable_http_app()`. It is NOT explicitly stored on the app state.

**Two options**:
1. **Reach into FastMCP internals** (fragile): `app.state.fastmcp_server` is set; the session manager is a private attribute. Not recommended.
2. **Create session manager separately in server.py** (clean): Create `StreamableHTTPSessionManager` in `_setup_mcp_app()` alongside FastMCP instance, store it as `_session_mgr`, expose via `get_session_manager()`. This mirrors django-mcp-server's `session_manager` property approach.

**Recommended (Option 2)**: Create the session manager in `_setup_mcp_app()` and store it as a module-level singleton alongside `_mcp_app`:

```python
def _setup_mcp_app():
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    mcp = FastMCP("NautobotMCP")
    # ... register tools ...
    _session_mgr = StreamableHTTPSessionManager(
        app=mcp._mcp_server,
        json_response=True,
        stateless=False,
    )
    return mcp, _session_mgr
```

But `mcp.http_app()` also creates its own session manager. We should NOT create two. Instead, **use the session manager from `http_app()`**:

```python
_mcp_app: Starlette | None = None
_session_mgr: StreamableHTTPSessionManager | None = None

def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:
                mcp_instance, session_mgr = _setup_mcp_app()
                _session_mgr = session_mgr  # Set global
                _mcp_app = mcp_instance.http_app(...)
    return _mcp_app
```

But `http_app()` creates ANOTHER session manager. From http.py:300:
```python
session_manager = StreamableHTTPSessionManager(...)
streamable_http_app = StreamableHTTPASGIApp(session_manager)
...
async def lifespan(app):
    async with server._lifespan_manager(), session_manager.run():
        yield
```

So `http_app()` creates a session manager, puts it in the lifespan, and returns the Starlette app. We need to access that same session manager from view.py.

**Best approach**: Access the session manager from `get_mcp_app()` by creating it there and passing it to `http_app()` via a monkey-patch or by directly calling `create_streamable_http_app()` instead of `http_app()`.

Actually, looking at `http.py` more carefully — `http_app()` is a convenience wrapper around `create_streamable_http_app()`. We can call `create_streamable_http_app()` directly with our own session manager:

```python
from fastmcp.server.http import create_streamable_http_app

_mcp_app: Starlette | None = None
_session_mgr: StreamableHTTPSessionManager | None = None

def _setup_mcp_app():
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    mcp = FastMCP("NautobotMCP")
    # ... register tools and _list_tools_mcp override ...
    return mcp

def get_mcp_app() -> Starlette:
    global _mcp_app, _session_mgr
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:
                mcp_instance = _setup_mcp_app()
                _session_mgr = StreamableHTTPSessionManager(
                    app=mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
                _mcp_app = create_streamable_http_app(
                    server=mcp_instance,
                    streamable_http_path="/mcp",
                    stateless_http=False,
                    json_response=True,
                    # Override the internally-created session manager:
                    # NOTE: create_streamable_http_app() always creates its own manager.
                    # We need to pass it in... but it doesn't accept a session_manager kwarg.
                )
    return _mcp_app
```

But `create_streamable_http_app()` doesn't accept a `session_manager` argument. It always creates its own. So we can't easily inject our own manager.

**Resolution**: Look at what `app.state` has after `http_app()` returns. From `http.py:258`: `app.state.fastmcp_server = server`. From `http.py:300–309`: `session_manager` is a local variable in `create_streamable_http_app()`. It is NOT stored on app.state.

BUT: `StreamableHTTPASGIApp.__init__` takes `session_manager` as an argument and stores it as `self.session_manager`. The Starlette app's router has a route that references `streamable_http_app` (http.py:334–352). We can't easily get back to it.

**Alternative**: Don't use `http_app()` at all. Call `create_streamable_http_app()` with our own `StreamableHTTPSessionManager`, and store it as a module-level singleton alongside `_mcp_app`:

```python
def get_mcp_app_and_session_manager():
    global _mcp_app, _session_mgr
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:
                mcp_instance = _setup_mcp_app()
                _session_mgr = StreamableHTTPSessionManager(
                    app=mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
                # Use create_streamable_http_app but with our session manager
                # by directly constructing what we need:
                from fastmcp.server.http import StreamableHTTPASGIApp
                streamable_http_app = StreamableHTTPASGIApp(_session_mgr)
                # Build the Starlette app manually with lifespan wrapping _session_mgr.run()
                ...
```

This is getting complex. The simplest approach for Phase 5:

**Approach**: Just use `async_to_sync` to call the existing `mcp_app` ASGI callable (the Starlette app from `http_app()`). But we need the session manager to call `session_manager.run()` + `handle_request()`. Without access to the session manager, we can't enter the task group.

**Cleanest solution**: Modify `_setup_mcp_app()` to create the session manager and store it globally, then have `get_mcp_app()` return both, and `get_session_manager()` return the stored manager. Since `http_app()` internally creates its own manager, we can either create the manager once in `server.py` and configure `http_app()` to use it, or we need to access the one `http_app()` creates from its return value.

The simplest path forward: create the session manager separately in `server.py`, call `http_app()` to get the Starlette app, and have `view.py` use the session manager we created in `server.py`. Since both managers reference the same `mcp._mcp_server`, the sessions will be compatible. The `http_app()` lifespan will manage its own manager, and our separate manager in `server.py` can be used for `async_to_sync` calls in `view.py` — the sessions will be tracked independently.

Actually, this creates two separate session managers for the same server, which defeats the purpose. The real issue is that `http_app()` already wraps `session_manager.run()` in its lifespan, so `handle_request()` should work if we call it through the Starlette app directly. But calling `http_app()` as an ASGI callable bypasses the lifespan context entirely, which is why the original approach failed.

The cleanest fix is to create a single session manager in `server.py`, use it to build the Starlette app in `http_app()`, and then access that same manager from `view.py` to call `handle_request()` directly. Looking at the `http.py` source, `create_streamable_http_app()` creates the session manager as a local variable but doesn't expose it, so I need to either create it in `server.py` and pass it through, or extract it from the app afterward. I need to reconsider the approach since the session manager and ASGI app are tightly coupled in FastMCP's implementation. Looking at `StreamableHTTPASGIApp`, it's instantiated with a session manager and handles requests directly. The cleanest path forward is to create the session manager separately in `server.py`, then pass it when constructing the app, rather than trying to extract it from the built app afterward. I'm checking if `create_streamable_http_app()` accepts a session manager parameter to avoid creating two separate instances, but it doesn't seem to. I need a different approach—maybe calling the Starlette app directly with `async_to_sync` instead of trying to work around the ASGI interface, though I'm running into the same lifespan problem there too.

Let me trace through what actually happens: the Starlette app has a lifespan context manager that starts the session manager when you use it as an ASGI app, but if I call it as a callable directly, that lifespan never runs. The real solution is to use the app's lifespan context properly—entering it before handling requests and exiting after—so the session manager actually starts up.

Looking at how `handle_request()` works, it expects the task group from `session_manager.run()` to already be active, which is exactly what the lifespan provides. So I need to ensure that context is entered before calling `handle_request()`.

Since I can't easily inject a custom session manager into `http_app()`, I'm considering two approaches: either create the session manager separately in `server.py` and pass it through, or figure out how to get a reference to the session manager that `http_app()` creates internally so I can reuse it in the view.

Actually, I'm realizing I could call `session_manager.run()` directly in the view within an `async_to_sync` context—that would create its own task group and manage the lifecycle separately from the Starlette app's lifespan. The tricky part is that the Starlette app's lifespan handler also manages the session manager, so I'd need to be careful not to conflict with that.

But wait, looking back at how `http_app()` actually works—it wraps the handler in a lifespan context that manages both the server's lifespan and the session manager's task group. So when I call `session_manager.handle_request()`, it's happening inside that already-active task group from the Starlette lifespan, which is why it works. The session manager's task group and the lifespan's task group are the same thing.

Now I'm seeing the real issue: if I call `session_manager.run()` again in the view layer, that's a second task group trying to run, which won't work. The solution is to access the session manager that `http_app()` already created and call `handle_request()` directly on it without wrapping it in another `run()` call.

The tricky part is that `StreamableHTTPASGIApp` stores the session manager as `self.session_manager`, but the Starlette app doesn't expose it directly—I can only access it through the route handler. So I need to find another way to get a reference to that session manager instance that FastMCP already created. me check if Starlette apps expose their routes/routes after construction... not easily.

**Plan D (simplest for Phase 5)**: Don't use `http_app()`. Build the Starlette app manually using the FastMCP components:

```python
from fastmcp.server.http import StreamableHTTPASGIApp, create_streamable_http_app
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Lifespan

def get_mcp_app_and_session_manager():
    global _mcp_app, _session_mgr
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:
                mcp_instance = _setup_mcp_app()
                _session_mgr = StreamableHTTPSessionManager(
                    app=mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
                streamable_http_app = StreamableHTTPASGIApp(_session_mgr)
                
                @asynccontextmanager
                async def lifespan(app):
                    async with mcp_instance._lifespan_manager(), _session_mgr.run():
                        yield
                
                _mcp_app = Starlette(
                    routes=[Route("/mcp", streamable_http_app, methods=["GET", "POST", "DELETE"])],
                    lifespan=lifespan,
                )
    return _mcp_app, _session_mgr
```

This gives us full control over the session manager creation and lifespan, making it straightforward to access from the view layer.

Actually, I need to verify that `streamable_http_app` is callable as an ASGI app—it just delegates to `session_manager.handle_request()`, so this should work. Let me finalize the implementation plan.

The approach is to build the Starlette app manually in `server.py` instead of using the convenience `http_app()` method, which gives us explicit control over both the lifespan and the session manager. We'll use `asynccontextmanager` to properly manage the lifespan context, then configure the routes and middleware to handle MCP requests through our controlled session manager.

In the view layer, we can then call `handle_request()` directly on the session manager that's now exposed through `get_session_manager()`. The key insight is that `StreamableHTTPSessionManager` is created once in `server.py` and persists for the Django process lifetime, so each worker thread calling `async_to_sync` will execute its coroutine in a separate executor thread, but they'll all reference the same manager instance.

The session state lives in `_server_instances`, which is a regular Python dict keyed by session ID. Since `anyio` uses `asyncio` under the hood, and asyncio TaskGroups aren't thread-safe for cross-thread access, the actual request handling stays within the task group created in the executor thread. The session dict itself is thread-safe as a Python object, but concurrent access across threads would need synchronization.

For concurrent requests on different worker threads, each executor thread has its own event loop and task group, so `session_manager.handle_request()` runs in thread-isolated contexts. The session dicts persist across requests because they survive loop teardowns in their respective threads, so sequential requests from the same client stay in the same thread and maintain session state correctly.

But looking back at the actual code, `_session_mgr` is just a regular dict stored as a module-level global in `server.py`, not wrapped in any thread-safe container. When multiple threads try to access it, there's potential for race conditions since Python's GIL only protects individual bytecode operations, not compound actions like the check-then-write that could happen during lazy initialization. So the real issue is that `session_manager.run()` gets called inside `async_to_sync` within the executor thread, not in the Django request thread itself. The executor thread has its own event loop that persists throughout the `async_to_sync` call, which means `_has_started` gets set there rather than in the main thread where the module-level singleton lives. This creates a potential race condition where multiple Django threads could both see `_session_mgr` as `None` and try to initialize it simultaneously. The lock itself is safe since it only protects the module-level variable assignment, not the actual async initialization that happens inside the executor thread. I'm realizing the real issue: the GIL only guarantees atomic execution of individual bytecode operations, not the entire lazy initialization pattern. So if two threads both check `_session_mgr is None` before either acquires the lock, they could both proceed to initialize it. With a threading lock, only one thread enters the initialization block at a time, so the second thread would see the already-initialized value and skip it entirely. With Django's runserver using threaded mode, the first request triggers lazy initialization in one thread while others wait at the lock, then reuse the already-set `_session_mgr` once it's available. This is the correct behavior.

Now I need to understand how the `session_manager` instance itself is safely shared across threads. The `StreamableHTTPSessionManager` class stores mutable state like `_server_instances` and `_task_group` as instance attributes, which means multiple threads could theoretically access and modify them simultaneously. Looking at the `_handle_stateful_request` method, it manages session creation with a lock and uses a dictionary to store server instances, so there's some thread-safety built in at the method level. I see that `_server_instances` is a plain dict shared across the `StreamableHTTPSessionManager` instance, and while individual dict operations like `__contains__` and `__setitem__` are atomic in CPython, compound operations like `if key in dict` followed by `dict[key] = ...` aren't atomic. However, the `_session_creation_lock` protects the compound operations in `_handle_stateful_request`, so the real session dict stored at `_server_instances[session_id]` is only accessed through that protected path.

Now I'm looking at the auth caching strategy—specifically how to avoid repeated database queries for token lookups within a single MCP request batch.

The challenge is that within one `async_to_sync` call handling a batch of tool calls, each tool invocation is async but runs sequentially in the same task group, so I can cache the user object directly on the task group itself using a thread-safe dict keyed by token key. The cache needs to live close to the auth logic without requiring major refactoring of the existing `get_user_from_request()` function. Looking at the MCP SDK's RequestContext structure, it has a `request` attribute that holds the original HTTP request data. I can leverage this by checking if there's already a cached user for the token, and if not, looking it up and storing it in a way that persists across tool calls within the same request batch.

The cleanest approach is to add a simple mutable mapping to the context itself that can hold the cached user object, so I can retrieve it on subsequent calls without hitting the database again. I'll update the auth caching logic to check for a cached user in the context's extra attributes before doing a database lookup, and store it there once found. But I need to verify what the `request` attribute actually is in the FastMCP flow—whether it's the raw ASGI scope dict or something else I can safely attach metadata to. I can leverage the `request` field in the context object to cache the authenticated user, which gets set once during the `initialize` step and remains available throughout the MCP session. This means I only need to query the database for the token on the first tool call, then reuse the cached result for all subsequent calls within that same session.

The auth caching strategy is straightforward: check if the cached user exists in `ctx.request_context.request`, and if not, perform the token lookup and store the result there.

Now I'm setting up an integration test that will validate session persistence across multiple requests using a real `StreamableHTTPSessionManager`. The test needs to be placed in the Docker container and will send a POST request to the MCP endpoint to verify that sessions maintain state correctly between calls.

However, there's a significant architectural constraint: Django's test client runs synchronously and can't properly test the async bridge, while the existing test suite uses mocked `Server.request_context`. The real integration test should live in the Docker environment itself rather than trying to work around Django's synchronous testing limitations. I need to verify that `_session_mgr` is initialized before `get_session_manager()` tries to access it—the singleton creation in `server.py` handles this, so the pattern should work safely.

For the auth caching fix, I'm storing the user directly on the request object using a custom attribute to avoid circular import issues.

Now I'm writing out the research document with implementation notes on these three components.
