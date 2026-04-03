# Pitfalls Research — Django WSGI → FastMCP ASGI Bridge

**Domain:** Django→FastMCP bridge implementation (WSGI to ASGI)
**Researched:** 2026-04-03
**Confidence:** HIGH
**Driven by:** django-mcp-server source analysis + mcp-server SDK source reading + current codebase bugs

---

## Critical Pitfalls

### Pitfall 1: `asyncio.run()` Destroys FastMCP Session State on Every Request

**What goes wrong:**
Every HTTP request calls `asyncio.run(mcp_app(scope, receive, send))`. `asyncio.run()` creates a **new event loop**, executes the coroutine, then **closes and destroys the loop** when the coroutine returns. FastMCP's `StreamableHTTPSessionManager._server_instances` dict (which holds session transports keyed by `Mcp-Session-Id`) lives inside that loop's task group. Once the loop is closed, the session store is gone.

Effect: `stateless_http=False` is set but sessions never survive between requests. The `Mcp-Session-Id` header from the MCP client is ignored because FastMCP's session manager has no existing loop to look it up in.

**Why it happens:**
`asyncio.run()` is designed for top-level entry points (CLI scripts, `main()`). It intentionally tears down the event loop after each call. When used inside a Django view (which itself runs inside Django's request thread), each request gets a fresh loop that is immediately discarded.

The correct pattern (from django-mcp-server) is `asgiref.sync.async_to_sync`:

```python
# WRONG — current implementation (view.py line 61)
asyncio.run(mcp_app(scope, receive, send))

# CORRECT — django-mcp-server pattern
from asgiref.sync import async_to_sync
result = async_to_sync(_call_starlette_handler)(request, self.session_manager)
```

`async_to_sync` reuses or creates a loop on the **current thread without destroying it**, keeping the session manager alive across multiple requests on the same thread.

**How to avoid:**
Replace `asyncio.run()` with `async_to_sync` wrapping the ASGI call. However, FastMCP's `http_app()` is a Starlette app that uses `session_manager.run()` (an async context manager that must be entered once at startup). The correct architecture is:

```python
# Pattern from django-mcp-server djangomcp.py
async def _call_starlette_handler(django_request, session_manager):
    scope = build_asgi_scope(django_request)
    async def receive(): ...
    async def send(message): ...
    async with session_manager.run():          # ← enters task group ONCE
        await session_manager.handle_request(scope, receive, send)
    return django_response

# In view / handle_django_request:
result = async_to_sync(_call_starlette_handler)(request, self.session_manager)
```

The key insight: `session_manager.run()` must be entered **once** when the Django process starts, not per-request. In django-mcp-server this is done by calling `session_manager.run()` inside the Starlette app's lifespan context manager (which outlives individual requests).

**Warning signs:**
- `Mcp-Session-Id` header sent by client is never recognized on subsequent requests
- `mcp_enable_tools()` appears to work (returns success) but `mcp_list_tools()` shows nothing changed
- FastMCP logs show "Creating new transport" on every single request
- `StreamableHTTPSessionManager._server_instances` is always empty after each request

**P0 — Addressed in:** v1.1.0 refactor (`view.py` asyncio.run → async_to_sync)

---

### Pitfall 2: `Server.request_context.get()` Raises `LookupError` on Every Request

**What goes wrong:**
The `_list_tools_mcp` override in `server.py` tries to access FastMCP's internal `Server.request_context` context variable:

```python
from mcp.server.lowlevel.server import Server
req_ctx = Server.request_context.get()  # ← LookupError
```

This raises `LookupError` on **every production request** (not just in tests), because `Server.request_context` is `mcp.server.lowlevel.server.request_ctx` — a `contextvars.ContextVar` that is only set by `MCPServer._handle_request()` when processing an MCP protocol message inside the task group created by `session_manager.run()`.

When using `asyncio.run()`, no persistent task group exists, so `_handle_request()` is never called in a context where `request_ctx` is set. The `LookupError` is silently caught and `session_dict` falls back to `{}`, causing `MCPSessionState.from_session({})` to produce empty state.

**Why it happens:**
`Server.request_context` is a **context variable**, not a global. It is set in `_handle_request()` (line 746 of mcp/server/lowlevel/server.py):

```python
token = request_ctx.set(RequestContext(...))
try:
    response = await handler(req)
finally:
    if token is not None:
        request_ctx.reset(token)
```

This only happens when the server's message loop is running. With `asyncio.run()` creating a new loop per request, the message loop doesn't survive long enough to set the context variable before the `_list_tools_mcp` call happens.

**How to avoid:**
Fix #1 (replacing `asyncio.run()`) is a prerequisite. Once the session manager's task group persists across requests, `Server.request_context` is set during message processing.

For code that runs *outside* the message loop (tests, management commands), access `Server.request_context` via a try/except and fall back gracefully:

```python
try:
    ctx = Server.request_context.get()
    session = ctx.session
except LookupError:
    # Outside live request — use full tool list or mock session
    session = {}
```

The existing code already does this, but the fallback was returning empty state even in production because `asyncio.run()` meant the context was never set even during live requests.

**Warning signs:**
- `LookupError` silently caught in `_list_tools_mcp` override
- `filtered_names_set` always empty → `_list_tools_mcp` returns empty tool list or all tools
- `MCPSessionState.from_session({})` fires in production (detectable via logging)
- Unit tests pass because they mock the session dict, but integration tests fail

**P0 — Addressed in:** v1.1.0 refactor (fixes asyncio.run() prerequisite, then `Server.request_context` works)

---

### Pitfall 3: FastMCP's `StreamableHTTPSessionManager.run()` Must Be Entered Once at Startup

**What goes wrong:**
Calling `session_manager.run()` **inside** the per-request async call (as opposed to at app startup) causes a `RuntimeError`:

```
RuntimeError: StreamableHTTPSessionManager .run() can only be called once per instance.
Create a new instance if you need to run again.
```

This happens because `StreamableHTTPSessionManager.run()` uses `_has_started` to guard against re-entry (line 104–111 of mcp/server/streamable_http_manager.py):

```python
async with self._run_lock:
    if self._has_started:
        raise RuntimeError(".run() can only be called once per instance")
    self._has_started = True
```

If you enter the context manager and then try to call `handle_request()` again from outside it (or enter it twice), the error fires.

**Why it happens:**
django-mcp-server avoids this by:
1. Creating a new `StreamableHTTPSessionManager` instance **per FastMCP server instance** (module-level singleton)
2. Calling `session_manager.run()` inside the Starlette app's **lifespan** context manager (which is entered once at server startup, exits at shutdown)

django-mcp-server creates the `session_manager` as a `@property` on `DjangoMCP`, but the Starlette app's lifespan wraps `session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app):
    async with server._lifespan_manager(), session_manager.run():
        yield
```

**How to avoid:**
Use one of these two approaches:

**Option A (django-mcp-server pattern):** Keep `StreamableHTTPSessionManager` alive via Starlette lifespan. The FastMCP `http_app()` already creates a `StreamableHTTPASGIApp` wrapping a session manager, but the session manager's `run()` is entered inside Starlette's lifespan. In this pattern, the Django view doesn't call `session_manager.run()` at all — it just calls `session_manager.handle_request()` inside an existing lifespan context.

**Option B (if bridging manually):** Call `session_manager.run()` once at process startup (e.g., in Django's `AppConfig.ready()`) and keep the manager instance as a module-level singleton:

```python
# At module level — manager created once at import/lazy-init
_session_manager: StreamableHTTPSessionManager | None = None

def get_session_manager() -> StreamableHTTPSessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = StreamableHTTPSessionManager(
            app=get_mcp_server()._mcp_server,
            json_response=True,
            stateless=False,
        )
    return _session_manager
```

Then in the view, use `async_to_sync` to call `handle_request` inside an existing task group:

```python
async def _handle(scope, receive, send):
    async with get_session_manager().run():  # ← this must survive across requests
        await get_session_manager().handle_request(scope, receive, send)

# This STILL has the problem of re-entering .run() on every call.
# The correct approach is to keep .run() always active.
```

The **correct** approach for manual bridging: create the session manager with a **persistent task group** using `anyio.create_task_group()` started once, and route requests into it.

**Warning signs:**
- `RuntimeError: StreamableHTTPSessionManager .run() can only be called once per instance`
- `RuntimeError: Task group is not initialized. Make sure to use run().`

**P0 — Addressed in:** v1.1.0 refactor (adopt django-mcp-server pattern: lifespan-managed session manager)

---

### Pitfall 4: FastMCP Lifespan Must Be Wired to the ASGI App's Lifespan

**What goes wrong:**
When FastMCP's `http_app()` is used as a pure ASGI callable (without its lifespan), `StreamableHTTPSessionManager.run()` is never entered, so the task group is never created. Calling `handle_request()` then raises:

```
RuntimeError: Task group is not initialized. Make sure to use run().
```

FastMCP's `StreamableHTTPASGIApp.__call__` (http.py line 38–61) catches this and raises a helpful error:

```
FastMCP's StreamableHTTPSessionManager task group was not initialized.
This commonly occurs when the FastMCP application's lifespan is not passed
to the parent ASGI application (e.g., FastAPI or Starlette).
Please ensure you are setting `lifespan=mcp_app.lifespan` in your parent
app's constructor.
```

**Why it happens:**
`create_streamable_http_app()` in FastMCP's http.py (line 365–368) creates a lifespan that wraps both `server._lifespan_manager()` AND `session_manager.run()`:

```python
@asynccontextmanager
async def lifespan(app):
    async with server._lifespan_manager(), session_manager.run():
        yield
```

If you import and call the ASGI app directly without Starlette routing this lifespan context, the lifespan never fires.

**How to avoid:**
Never call `mcp.http_app()` ASGI app directly without Starlette's lifespan context. Always mount it as a Starlette app with its lifespan properly wired, OR use the pattern where `handle_request` is called inside an active `session_manager.run()` context (Option B above).

The current `nautobot-app-mcp-server` calls `mcp_app(scope, receive, send)` directly as a plain ASGI callable — bypassing the lifespan. This is the root cause of the `asyncio.run()` problem and the session state loss.

**Warning signs:**
- `RuntimeError: Task group is not initialized` when calling `handle_request()`
- ASGI app works once but sessions never survive
- FastMCP logs: "StreamableHTTP session manager started" never appears

**P0 — Addressed in:** v1.1.0 refactor (wire FastMCP lifespan into Django's request lifecycle)

---

### Pitfall 5: Thread-Unsafe `_mcp_app` Singleton

**What goes wrong:**
```python
global _mcp_app
if _mcp_app is None:          # ← Two threads can both pass this
    mcp_instance = _setup_mcp_app()
    _mcp_app = mcp_instance.http_app(...)  # ← second write wins, first leaked
```

Django's threaded workers can handle concurrent requests. Two threads hitting `get_mcp_app()` simultaneously during startup can create duplicate FastMCP instances.

**How to avoid:**
Use double-checked locking with `threading.Lock`:

```python
import threading
_lock = threading.Lock()

def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _lock:
            if _mcp_app is None:  # Second check inside lock
                _mcp_app = _setup_mcp_app()
    return _mcp_app
```

**Warning signs:**
- Two `_setup_mcp_app()` calls in logs during startup under load
- Resource exhaustion if `_setup_mcp_app()` opens connections
- Intermittent test failures with duplicate registrations

**P1 — Addressed in:** v1.1.0 refactor (thread lock on `get_mcp_app()`)

---

### Pitfall 6: `MCPSessionState` Written to Server Session But Never Survives a Request

**What goes wrong:**
Even if `mcp_enable_tools` successfully writes to `session["enabled_scopes"]`, the write is made to the in-memory dict inside `StreamableHTTPSessionManager._server_instances[session_id]`. When `asyncio.run()` tears down the loop, the transport (and its session dict) are destroyed. The next request creates a new transport with a fresh empty session dict.

**Why it happens:**
This is a compound effect of Pitfall 1. With `async_to_sync` (fixing Pitfall 1), the task group survives across requests and the session dict is persistent. With `asyncio.run()`, it is not.

**How to avoid:**
Fixing Pitfall 1 solves this. The session dict lives in `StreamableHTTPSessionServerTransport` (inside the task group), and with `session_manager.run()` active, it persists between requests.

django-mcp-server takes a more robust approach: it delegates session state to **Django's session framework** (cookie-based, survives restarts). This avoids in-memory session loss if the Django process restarts. For v1, in-memory sessions are acceptable, but this should be documented.

**Warning signs:**
- `mcp_enable_tools(scope="dcim")` returns `"Enabled: scope 'dcim'"` but immediately `mcp_list_tools` shows no `dcim` tools
- FastMCP logs show session transport being created fresh each request

**P0 — Addressed in:** v1.1.0 refactor (session dict now survives across requests)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `asyncio.run()` in view | Simple, no external deps | Destroys all session state per request | Never — hard requirement to fix |
| In-memory session storage | No Redis needed | Sessions lost on restart or multi-worker | Only for single-worker dev; document |
| Hardcoded ASGI `server` tuple | Works in dev | Breaks behind reverse proxies or custom ports | Always fix — 2-line change |
| No request-level user cache | Simple code | N token DB queries per batch MCP request | Only for very low traffic; fix with `functools.lru_cache` on thread-local key |
| Mock ToolContext in `_list_tools_mcp` | Tests pass without real session | Test coverage gap for session logic | Only as supplement to integration tests |
| Single `StreamableHTTPSessionManager` reused across requests | Simple architecture | All sessions in one manager — if it crashes, all die | Acceptable for single-process; document |

---

## Integration Gotchas

### Integration: Django ORM ↔ FastMCP Async Handlers

| Common Mistake | Correct Approach |
|---------------|-----------------|
| Calling Django ORM directly from async tool handler without `sync_to_async` | Wrap ORM calls: `sync_to_async(get_user, thread_sensitive=True)(token_key)` |
| `sync_to_async` without `thread_sensitive=True` | Use `thread_sensitive=True` to reuse Django's thread-local connection pool |
| `async_to_sync` wrapping a sync Django ORM call inside an already-async handler | Never nest `async_to_sync` inside `sync_to_async` — use `await` all the way through |
| Calling ORM in FastMCP lifespan/startup hooks | ORM must only be called after Django `ready()` signal fires; use lazy init for server |
| QuerySet iteration in async context without wrapping | Wrap in `sync_to_async(list, thread_sensitive=True)(queryset)` |

### Integration: FastMCP Session Dict ↔ Django Session Framework

| Common Mistake | Correct Approach |
|---------------|-----------------|
| Storing session state only in FastMCP in-memory dict (lost on restart) | For persistence: mirror to Django sessions; for v1: document in-memory limitation |
| Relying on `Mcp-Session-Id` matching Django session key | They are independent — FastMCP generates its own UUID session IDs |
| Calling `session.save()` after writing FastMCP session state | Only needed if delegating to Django sessions; FastMCP manages its own dict |
| Session state read/write race in concurrent tool calls | FastMCP's `ServerSession` dict operations are synchronous within the async task; no extra locking needed |

### Integration: `Server.request_context` ↔ Django Request Lifecycle

| Common Mistake | Correct Approach |
|---------------|-----------------|
| Accessing `Server.request_context` outside `session_manager.run()` task group | Always access inside active lifespan; raise `LookupError` gracefully outside |
| Accessing `Server.request_context` in FastMCP tool handler before handler is called | Context is set in `_handle_request()` before handler dispatch — available during tool execution |
| Overriding `_list_tools_mcp` and accessing `Server.request_context` | Safe if called from within `session_manager.run()`; catches `LookupError` for test/fallback paths |
| Passing Django `HttpRequest` through `Server.request_context` | Use `context.request_context.request` (MCP SDK request) — not Django `HttpRequest` |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Token lookup without caching | N DB queries per MCP request (one per tool call in batch) | `functools.lru_cache` on token key OR thread-local cache set at request entry | Batch operations with 5+ tool calls |
| `MCPToolRegistry.fuzzy_search()` O(n) per term | Linear scan of all tools per fuzzy term | O(n) is fine for <100 tools; add inverted index if registry grows | 500+ tools with 10+ fuzzy terms |
| Session dict rebuilt from scratch per `mcp_list_tools` call | Repeated `MCPSessionState.from_session()` deserialization | Session dict operations are dict reads — negligible overhead | Not a concern at expected scale |
| `_list_tools_mcp` override fetches all tools then filters | Two full tool scans (registry + filter) | Acceptable at <100 tools; defer optimization until measured | 1000+ tools with complex filtering |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Anonymous user returning data silently | Data leakage if auth misconfigured | Log warning when `AnonymousUser` used; fail-closed for sensitive scopes |
| Auth token logged in plaintext | Token exposure in logs | Never log `Authorization` header value; log only prefix (`Token abc...`) |
| Token lookup without rate limiting | Token enumeration via repeated requests | Nautobot's Token model is already DB-backed; add Django throttle class if needed |
| `MCPSessionState` mutable by client | Malicious client manipulates session | Session state only controls tool visibility (read operations); write tools are out of scope for v1 |
| No CORS control on MCP endpoint | Unauthorized cross-origin calls | MCP endpoint is behind Nautobot's auth; add explicit origin allowlist if exposed externally |

---

## "Looks Done But Isn't" Checklist

- [ ] **`asyncio.run()` replaced:** `async_to_sync` is used, but verify `session_manager.run()` is called once at startup (not per-request)
- [ ] **`Server.request_context` works:** `LookupError` no longer fires in production; integration test verifies session dict survives across two sequential MCP requests
- [ ] **Session state persists:** `mcp_enable_tools(scope="dcim")` followed by `mcp_list_tools` shows `dcim` tools — verified by integration test
- [ ] **`StreamableHTTPSessionManager.run()` entered once:** Check that `session_manager.run()` is inside a lifespan context manager (Django startup or Starlette app lifespan), not inside per-request code
- [ ] **Thread-safe singleton:** `get_mcp_app()` uses double-checked locking; two concurrent startup requests don't create duplicate instances
- [ ] **ASGI scope server address:** `request.get_host()` / `request.get_port()` used, not hardcoded `("127.0.0.1", 8080)`
- [ ] **User token cached per request:** Auth layer caches token→user lookup using thread-local or request-level cache, not per-tool
- [ ] **Django ORM sync calls wrapped:** All ORM calls in tool handlers go through `sync_to_async(..., thread_sensitive=True)`
- [ ] **Session dict survives process restart:** If persistence is required: delegate to Django sessions; if not: document as known limitation

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| `asyncio.run()` session destruction | LOW | Replace with `async_to_sync` + lifespan-managed session manager; no data migration needed |
| `Server.request_context` LookupError | LOW | Fixes automatically once `asyncio.run()` is fixed; add defensive `LookupError` catch for test compatibility |
| Session manager `.run()` re-entry | LOW | Create `StreamableHTTPSessionManager` once as module-level singleton; never recreate per request |
| Thread-unsafe singleton | LOW | Add `threading.Lock` around `_mcp_app` creation; no other changes needed |
| In-memory sessions lost on restart | MEDIUM | Implement Django session delegation (django-mcp-server pattern); requires session schema migration if sharing with Django sessions |
| Auth token lookup uncached | LOW | Add `functools.lru_cache(maxsize=128)` on token→user lookup function keyed by token key |

---

## Pitfall-to-Phase Mapping

| Pitfall | Milestone | Verification |
|---------|-----------|---------------|
| P1: `asyncio.run()` destroys session state | v1.1.0 — P0 fix | Integration test: two sequential MCP requests with `Mcp-Session-Id`; second request recognizes session |
| P2: `Server.request_context` LookupError | v1.1.0 — P0 fix | Unit test mocks session dict; integration test verifies real context access |
| P3: `session_manager.run()` per-request | v1.1.0 — P0 fix | Verify "StreamableHTTP session manager started" appears once in logs at startup |
| P4: Lifespan not wired | v1.1.0 — P0 fix | No `RuntimeError: Task group is not initialized` in logs under load |
| P5: Thread-unsafe singleton | v1.1.0 — P1 fix | Concurrent startup under load test; no duplicate `_setup_mcp_app()` calls |
| P6: Session state never survives | v1.1.0 — P0 fix | Covered by P1 verification |
| P1: Auth token lookup uncached | v1.1.0 — P1 fix | Django debug toolbar or query count assertion: N queries for N tool calls → 1 query |
| P1: ASGI scope server hardcoded | v1.1.0 — P1 fix | Verify `request.get_host()` value appears in ASGI scope |

---

## Sources

- [django-mcp-server djangomcp.py](https://raw.githubusercontent.com/gts360/django-mcp-server/main/mcp_server/djangomcp.py) — `async_to_sync` WSGI→ASGI bridge, `StreamableHTTPSessionManager` lifespan wiring, Django session delegation
- [django-mcp-server views.py](https://raw.githubusercontent.com/gts360/django-mcp-server/main/mcp_server/views.py) — `MCPServerStreamableHttpView` DRF APIView pattern
- [mcp/server/lowlevel/server.py](file://.venv/lib/python3.12/site-packages/mcp/server/lowlevel/server.py) — `Server.request_context` contextvar, `_handle_request()` context setup (lines 746–779)
- [mcp/server/streamable_http_manager.py](file://.venv/lib/python3.12/site-packages/mcp/server/streamable_http_manager.py) — `StreamableHTTPSessionManager.run()` once-per-instance guard, stateful vs stateless request handling, session dict per `Mcp-Session-Id`
- [fastmcp/server/http.py](file://.venv/lib/python3.12/site-packages/fastmcp/server/http.py) — `StreamableHTTPASGIApp`, `RequestContextMiddleware`, `create_streamable_http_app` lifespan wiring (lines 365–368), `RuntimeError: Task group is not initialized` helpful message
- [fastmcp/server/mixins/transport.py](file://.venv/lib/python3.12/site-packages/fastmcp/server/mixins/transport.py) — `http_app()` and `run_http_async()` entry points
- `docs/dev/mcp-implementation-analysis.md` — current implementation analysis, bug inventory, P0/P1 priority ranking
- `nautobot_app_mcp_server/mcp/view.py` — current broken implementation (P0: `asyncio.run()`)
- `nautobot_app_mcp_server/mcp/server.py` — current broken implementation (P0: `Server.request_context.get()` → LookupError, P1: thread-unsafe singleton)

---
*Pitfalls research for: Django WSGI → FastMCP ASGI bridge*
*Researched: 2026-04-03*
