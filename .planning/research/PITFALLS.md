# Pitfalls — Nautobot MCP Server

> What this project commonly gets wrong. Each pitfall has warning signs, prevention, and phase mapping.

---

## Critical Pitfalls

### PIT-01: Missing MCP Dependencies in pyproject.toml

**Severity:** Critical — blocks any build

**Warning signs:** `ImportError: No module named 'fastmcp'` or `'mcp'` when running the app. `poetry run python -c "import fastmcp"` fails.

**Prevention:** Add to `pyproject.toml` `[tool.poetry.dependencies]` before any MCP code is written:

```toml
mcp = "^1.26.0"          # Official MCP Python SDK (includes FastMCP server)
fastmcp = "^3.2.0"       # fastmcp package (active, maintained by Prefect)
asgiref = "^3.11.1"      # Django ASGI bridge (ships with Django)
```

Run `poetry lock && poetry install` immediately after adding deps.

**Phase:** Phase 1a — MCP server scaffold

---

### PIT-02: Package Name Mismatch — `nautobot_mcp_server` vs `nautobot_app_mcp_server`

**Severity:** Critical — breaks all import paths, invisible until runtime

**Warning signs:** `ImportError: cannot import name 'register_mcp_tool' from 'nautobot_mcp_server'` or `ModuleNotFoundError: No module named 'nautobot_mcp_server'`.

**Root cause:** `DESIGN.md` uses `nautobot_mcp_server/` throughout but the actual package is `nautobot_app_mcp_server/` (matches the Poetry `name` in `pyproject.toml`).

**Prevention:** Use `nautobot_app_mcp_server` consistently everywhere. Do a global find-replace on DESIGN.md before implementing.

**Phase:** Phase 0 — Project setup (resolve before any code is written)

---

### PIT-03: Creating FastMCP ASGI App at Module Import Time

**Severity:** High — causes `RuntimeError: Synchronous only` or Django ORM thread errors

**Warning signs:** `RuntimeError: There is no current event loop` or `sync_to_async called in wrong thread context` when the MCP server starts.

**Root cause:** The `get_mcp_app()` function is called at module import time. `sync_to_async` with `thread_sensitive=True` requires an active request context — there is none at import time.

**Prevention:** Lazy initialization is mandatory. `get_mcp_app()` must be called only from within the Django view (when a request context exists):

```python
# WRONG — crashes at import
_mcp_app = mcp.streamable_http_app(path="/mcp", ...)

# RIGHT — lazy, called from view
_mcp_app: ASGIApplication | None = None

def get_mcp_app() -> ASGIApplication:
    global _mcp_app
    if _mcp_app is None:
        _mcp_app = mcp.streamable_http_app(...)
    return _mcp_app
```

**Phase:** Phase 1b — MCP HTTP endpoint

---

### PIT-04: Wrong ASGI Bridge — `async_to_sync` vs `WsgiToAsgi`

**Severity:** High — bridge doesn't work, 405 or empty responses

**Warning signs:** MCP requests return 405 Method Not Allowed or empty responses. The `streamable_http_app()` returns a Starlette ASGI app (`scope/receive/send` callable) — not something you call with a Django request object.

**Root cause:** The ASGI bridge direction is Django WSGI → FastMCP ASGI. `async_to_sync` converts async→sync (not what we need). The correct bridge is `asgiref.wsgi.WsgiToAsgi` which converts WSGI scope to ASGI scope.

**Prevention:** Use `asgiref.wsgi.WsgiToAsgi`:

```python
from asgiref.wsgi import WsgiToAsgi

def mcp_view(request):
    app = get_mcp_app()
    wsgi_handler = WsgiToAsgi(app)
    # WsgiToAsgi handles the scope/receive/send conversion
    raise NotImplementedError("Use asgiref.wsgi.WsgiToAsgi(app) in the view")
```

**Phase:** Phase 1b — MCP HTTP endpoint

---

### PIT-05: Using `django-starlette` (Does Not Exist)

**Severity:** High — wasted time, broken approach

**Warning signs:** `pip install django-starlette` fails — this package does not exist on PyPI.

**Root cause:** The approach in `DESIGN.md` references `django-starlette` which is not a real package.

**Prevention:** Use `asgiref.wsgi.WsgiToAsgi` (from the `asgiref` package already included with Django) to bridge Django → Starlette ASGI. No extra package needed.

**Phase:** Phase 1b — MCP HTTP endpoint

---

### PIT-06: Wrong Thread Mode for `sync_to_async`

**Severity:** High — Django connection pool exhaustion, `connection already closed` errors

**Warning signs:** Sporadic `connection already closed` errors in tool handlers. Memory growth over time.

**Root cause:** Using `sync_to_async(fn)` without `thread_sensitive=True`. Default thread mode may use a different thread per call, losing Django's thread-local connection pool.

**Prevention:** Always use `thread_sensitive=True` for Django ORM calls:

```python
from asgiref.sync import sync_to_async

_get_devices = sync_to_async(
    _sync_device_list,
    thread_sensitive=True,  # Reuses Django's thread-local connection pool
)
```

**Phase:** Phase 3 — Core tools

---

### PIT-07: Pagination Counts After Slicing (Auto-Summarize Never Fires)

**Severity:** High — auto-summarize never triggers, memory issues on large datasets

**Warning signs:** `device_list(limit=1000)` on a 10,000-device database returns all 1000 items without a `summary` field, even though it should summarize at 100.

**Root cause:** The `paginate_queryset` implementation in `DESIGN.md` slices first, then counts the sliced result. Auto-summarize fires based on the sliced count, not the original count.

**Prevention:** Count BEFORE slicing:

```python
# WRONG (from DESIGN.md):
items = list(qs[:limit + 1])
has_next = len(items) > limit  # counts AFTER slice
if len(items) > LIMIT_SUMMARIZE:  # always false for small limits
    summary = {...}

# RIGHT:
raw_items = list(qs[:limit + 1])
has_next = len(raw_items) > limit
items = raw_items[:limit]
if len(raw_items) > LIMIT_SUMMARIZE:  # counts BEFORE slice
    full_count = qs.count()  # accurate count
    summary = {"total_count": full_count, ...}
```

**Phase:** Phase 3 — Core tools (pagination module)

---

### PIT-08: Option B (Separate Worker) as Primary Approach — Anti-Feature

**Severity:** High — violates core value proposition, requires Redis, complex deployment

**Warning signs:** Running `uvicorn nautobot_mcp_server.mcp.server:app --port 9001` as a separate process. Redis session errors.

**Root cause:** DESIGN.md lists Option B (separate worker) as simpler, but it requires Redis for session state sharing, creates a separate process that must authenticate against Nautobot separately, and contradicts the "embedded in Django" value proposition.

**Prevention:** Option A (embedded via Django URL route with `WsgiToAsgi`) is the correct approach:
- Zero extra ports or firewall rules
- Shares Django's ORM directly (no auth sync needed)
- FastMCP session state is in-memory (acceptable for v1)

Option B is only needed if Nautobot is deployed with multiple gunicorn workers AND sessions are lost between workers — defer to v2 if this becomes a problem.

**Phase:** Phase 1b — MCP HTTP endpoint

---

## High-Severity Pitfalls

### PIT-09: `base_url` Mismatch — `mcp-server` vs `nautobot-mcp-server`

**Severity:** High — URL routing mismatch, 404 on MCP endpoint

**Warning signs:** `curl http://localhost:8080/plugins/nautobot-mcp-server/mcp/` returns 404.

**Root cause:** `__init__.py` sets `base_url = "mcp-server"` → mounted at `/plugins/mcp-server/`. DESIGN.md references `/plugins/nautobot-mcp-server/mcp/`. These must match.

**Prevention:** Decide on one. `base_url = "mcp-server"` (from `__init__.py`) is the authoritative value. Update DESIGN.md to use `/plugins/mcp-server/mcp/`.

**Phase:** Phase 0 — Project setup

---

### PIT-10: Anonymous Auth Returns Empty — Can Hide Misconfiguration

**Severity:** High — silent failures, misconfigured tokens return no data with no error

**Warning signs:** Requests with invalid tokens return `{"items": []}` with HTTP 200 — no indication that auth failed.

**Prevention:** Log a warning when AnonymousUser is detected:

```python
def get_user_from_request(request) -> User | AnonymousUser:
    if auth_header.startswith("Token "):
        token_key = auth_header[6:]
        try:
            token = Token.objects.select_related("user").get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            logger.warning("MCP: Invalid token attempted")
            return AnonymousUser()
    ...
    if not request.user.is_authenticated:
        logger.debug("MCP: Anonymous request")
    return request.user or AnonymousUser()
```

Add a verification test: valid token → data, invalid token → empty, no token → empty + warning log.

**Phase:** Phase 2 — Auth layer

---

### PIT-11: Multi-Worker Deployment — In-Memory Session Loss

**Severity:** High — sessions lost between gunicorn workers

**Warning signs:** First request works, second request (different worker) loses enabled scopes. `mcp_enable_tools` works on first call, then tools disappear.

**Root cause:** FastMCP's session state is stored in-memory on the worker that handled the first request. Gunicorn workers are separate processes — session state is not shared.

**Known deferred item:** DESIGN.md explicitly defers Redis session backend to v2. For v1, document this as a known limitation. Single-worker deployments (dev, `runserver`) are unaffected.

**Prevention:** For v1, use a single gunicorn worker or note in docs that multi-worker requires v2 Redis session backend. Add a startup warning:

```python
import os
if os.environ.get("GUNICORN_WORKERS", "1") != "1":
    logger.warning(
        "MCP session state is in-memory. "
        "Multi-worker deployments require Redis session backend (v2)."
    )
```

**Phase:** Phase 5 — Production hardening

---

### PIT-12: `post_migrate` Signal Registration Order

**Severity:** High — tools from third-party apps not registered, `register_mcp_tool()` calls fail silently

**Warning signs:** Third-party app tools (e.g., `netnam_cms_core.juniper.*`) don't appear in `mcp_list_tools()`.

**Root cause:** `post_migrate` fires per app when that app's migrations complete. If a third-party app's `ready()` calls `register_mcp_tool()` before the MCP server's `post_migrate` fires, the tool is registered to the singleton but then... actually the order in `DESIGN.md` is correct: `post_migrate` fires AFTER all `ready()` hooks. But the design uses `post_migrate` from within `ready()` — this means `post_migrate` connects itself at `ready()` time, and `post_migrate` fires when migrations run (which includes the MCP server's own migrations).

**Prevention:** Use a two-step connect:
```python
def ready(self):
    post_migrate.connect(self._on_post_migrate, sender=self)

@staticmethod
def _on_post_migrate(app_config, **kwargs):
    if app_config.name == "nautobot_app_mcp_server":
        # Only run for THIS app's migrations
        MCPToolRegistry.get_instance().register_core_tools()
```

**Phase:** Phase 1c — Nautobot plugin integration

---

### PIT-13: `@mcp.list_tools()` Return Type for Progressive Disclosure

**Severity:** High — wrong approach, breaks MCP protocol

**Warning signs:** Tools disappear from the MCP manifest entirely when scopes change.

**Root cause:** The `list_tools()` MCP protocol handler should return ALL tools that COULD be called (not just the currently enabled ones). Claude Code can call any tool by name regardless of manifest. The session state should filter WHICH tools Claude is AWARE of, not WHICH can be called.

**Prevention:** Override `@mcp.list_tools()` to return currently active tools, but document that tools can always be called by name. The registry is the source of truth for execution, the manifest controls discoverability.

**Phase:** Phase 3 — Core tools (session management)

---

### PIT-14: `search_by_name` Complexity — Multi-Model Query Without Ranking

**Severity:** High — slow, returns unordered results

**Warning signs:** `search_by_name("core")` returns 50+ mixed results in arbitrary order. No indication of relevance.

**Root cause:** The DESIGN.md `search_by_name` is listed as a single core tool but is actually a multi-model search with ranking. Implementing it as a simple `Q(name__icontains=query)` across multiple models returns unordered results.

**Prevention:** Implement `search_by_name` with:
1. Per-model name searches using `Q(name__icontains=query) | Q(display_name__icontains=query)`
2. Results ranked by exact match > startswith > contains
3. Return `{"model": "device", "name": "...", "relevance": "high"}` in results
4. Consider limiting to top 25 results to avoid context overflow

**Phase:** Phase 4 — Additional tools

---

## Medium-Severity Pitfalls

### PIT-15: CI Passes on Empty Tests — False Confidence

**Severity:** Medium — PRs merged without actual coverage

**Warning signs:** `poetry run invoke tests` passes but `coverage` shows 0% coverage.

**Root cause:** `nautobot_app_mcp_server/tests/__init__.py` is empty. CI runs the test suite which exercises nothing.

**Prevention:** Phase 1d must include tests for the scaffold (app config loads, URL route resolves). Add coverage thresholds to `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 50  # Enforce minimum coverage
```

Increase threshold as more code is written.

**Phase:** Phase 1d — Testing scaffold

---

### PIT-16: Auth Token Extracted from Wrong Source

**Severity:** Medium — tokens not recognized, anonymous fallback

**Warning signs:** Valid Nautobot API token in `Authorization` header → AnonymousUser.

**Root cause:** In FastMCP, the raw HTTP headers come from `ctx.request_context.request` (MCP SDK request object, not Django `HttpRequest`). `request.headers.get("Authorization")` on the MCP request works differently than on Django's request.

**Prevention:** In tool handlers, extract auth from the FastMCP request context:
```python
from mcp.server import Context

@mcp.tool()
async def device_list(ctx: Context, name: str | None = None, limit: int = 25):
    # MCP request object, not Django HttpRequest
    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")
    ...
```

**Phase:** Phase 2 — Auth layer

---

### PIT-17: `cursor` Encoding for Non-String PKs

**Severity:** Medium — `base64.b64decode` fails on UUID primary keys

**Warning signs:** `cursor` parameter causes `UnicodeDecodeError` on devices with UUID PKs.

**Root cause:** DESIGN.md encodes cursor as `base64(pk)` where `pk` is a UUID string. But `str(uuid_obj)` produces a human-readable UUID like `"a3f8b2c0-..."`. `base64.b64decode` returns bytes, and `.decode()` assumes UTF-8 which works. However, if PK is stored as a UUID object (not string) the encoding could be inconsistent.

**Prevention:** Always convert to string explicitly before encoding:
```python
def _encode_cursor(pk) -> str:
    return base64.b64encode(str(pk).encode("utf-8")).decode("ascii")

def _decode_cursor(cursor: str) -> str:
    return base64.b64decode(cursor.encode("ascii")).decode("utf-8")
```

And when using in filter:
```python
pk_field = qs.model._meta.pk
if isinstance(last_pk, str):
    last_pk = last_pk  # use as-is for UUID/string PKs
qs = qs.filter(**{f"{pk_field.name}__gt": last_pk})
```

**Phase:** Phase 3 — Core tools (pagination)

---

### PIT-18: Pylint Score < 10.00 — PR Blocked

**Severity:** Medium — PRs rejected in CI

**Warning signs:** `poetry run invoke pylint` reports score below 10.00.

**Prevention:** Run `poetry run invoke pylint` before every commit. Keep all code clean. When adding new code:
- Use `from __future__ import annotations` to avoid forward-reference warnings
- Use `# type: ignore` only for third-party stubs
- Never skip pylint with `--disable`

**Phase:** All phases

---

## Quality Gates Summary

| Pitfall | Gate | How to Verify |
|---|---|---|
| PIT-01 | Dependencies added | `poetry run python -c "import fastmcp, mcp"` succeeds |
| PIT-02 | Package name consistent | `poetry run python -c "import nautobot_app_mcp_server"` succeeds |
| PIT-03 | Lazy init | `poetry run python -c "from nautobot_app_mcp_server.mcp import server"` succeeds without DB |
| PIT-04 | ASGI bridge works | `curl -X POST http://localhost:8080/plugins/mcp-server/mcp/` → MCP JSON-RPC response |
| PIT-06 | Thread sensitivity | Load test with 100 concurrent requests → no `connection already closed` |
| PIT-07 | Auto-summarize fires | `device_list(limit=100)` on 500-device DB → `summary` field present |
| PIT-10 | Auth warning logged | Request with invalid token → warning in logs + empty results |
| PIT-15 | Coverage > 0 | `coverage report` shows >50% on `nautobot_app_mcp_server/` |
| PIT-18 | Pylint 10.00 | `poetry run invoke pylint` → 10.00/10 |

---

*Last updated: 2026-04-01 after research synthesis*
