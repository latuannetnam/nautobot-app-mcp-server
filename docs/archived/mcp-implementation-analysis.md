# MCP Implementation Analysis: nautobot-app-mcp-server vs django-mcp-server

**Date:** 2026-04-03
**Reference:** https://github.com/gts360/django-mcp-server
**Goal:** Validate the current implementation against a reference Django MCP pattern, identify correctness and design issues, and document findings to guide future refactoring.

---

## 1. Reference Implementation: django-mcp-server

### 1.1 Overview

`django-mcp-server` is a general-purpose Django extension that exposes Django models and business logic as MCP tools. It provides three layers of tooling:

| Layer | Component | Purpose |
|-------|-----------|---------|
| **HTTP Bridge** | `MCPServerStreamableHttpView` (DRF APIView) | Exposes the MCP endpoint at `/mcp` |
| **Server Core** | `DjangoMCP` (extends `FastMCP`) | Owns session manager, request lifecycle, session persistence |
| **Tool Registration** | `MCPToolset`, `ModelQueryToolset` (metaclass registries) | Declarative tool discovery and registration |

### 1.2 Architecture

```
MCPServerStreamableHttpView (Django REST Framework APIView)
    └── MCPServerStreamableHttpView.handle_django_request()
            └── DjangoMCP.handle_django_request()
                    └── async_to_sync(_call_starlette_handler)
                            └── StreamableHTTPSessionManager.handle_request()
                                    └── FastMCP MCP protocol handlers
                                            └── MCP tool execution
```

Key design decisions:

1. **`DjangoMCP` extends `FastMCP`** directly, composing a `StreamableHTTPSessionManager` that owns session state. Session persistence is delegated to Django's session backend (cookie-based, `Mcp-Session-Id` header).
2. **ASGI scope is built from the Django request** in `_call_starlette_handler()`, using `asgiref.sync.async_to_sync` to bridge the WSGI→ASGI gap.
3. **Tool registration uses metaclass-based registries** (`ToolsetMeta`, `ModelQueryToolsetMeta`). Subclasses auto-register by defining themselves — no explicit `register_mcp_tool()` call needed per class.
4. **`ModelQueryToolset`** auto-generates JSON Schema from Django model field introspection. Foreign keys, choices enums, required fields, and field descriptions are all inferred.
5. **DRF integration layer** (`_DRFRequestWrapper`, `_DRFCreate/List/Update/DeleteAPIViewCallerTool`) converts DRF views and serializers into MCP tools with `@drf_publish_create_mcp_tool` decorators.
6. **Auth is handled at the DRF view level**, configurable via `DJANGO_MCP_AUTHENTICATION_CLASSES` in Django settings. Unauthenticated requests are rejected before reaching the MCP handler.

### 1.3 Session Management

`DjangoMCP` uses a `StreamableHTTPSessionManager` with `stateless=True` (sessions managed via Django, not FastMCP's in-memory store):

```python
@property
def session_manager(self) -> StreamableHTTPSessionManager:
    return StreamableHTTPSessionManager(
        app=self._mcp_server,
        event_store=self._event_store,
        json_response=True,
        stateless=True,  # Sessions managed via Django sessions
    )
```

On each request:
1. Read `Mcp-Session-Id` header → load Django `SessionStore`
2. Pass session to FastMCP's session manager
3. On response, persist Django session and return `Mcp-Session-Id` in response header

This means **session state survives process restarts** and works correctly with WSGI workers.

---

## 2. Current Implementation: nautobot-app-mcp-server

### 2.1 Architecture

```
mcp_view() (Django view function)
    └── get_mcp_app()  [lazy, thread-unsafe]
            └── _setup_mcp_app()
                    └── FastMCP.http_app(path="/mcp", transport="streamable-http", stateless_http=False)
                            └── FastMCP handles MCP protocol
```

Key design decisions:

1. **Lazy factory** (`get_mcp_app()`) avoids Django ORM race conditions at startup (PIT-03).
2. **`MCPToolRegistry`** is a **thread-safe singleton** using double-checked locking — manually managed, not metaclass-based.
3. **Progressive disclosure** via `_list_tools_mcp` override — tools are filtered by session state.
4. **Session state** lives in FastMCP's in-memory `StreamableHTTPSessionManager` dict — per-connection, not persisted.
5. **Auth is per-tool**, reading the `Authorization` header from the MCP request and looking up Nautobot's Token model.
6. **No DRF integration** — plain Django view function, not a DRF APIView.

---

## 3. Critical Correctness Issues

### 3.1 `asyncio.run()` Breaks FastMCP Session State (CRITICAL)

**File:** `nautobot_app_mcp_server/mcp/view.py`, line 61

**Problem:** Every HTTP request is handled by:
```python
asyncio.run(mcp_app(scope, receive, send))
```

`asyncio.run()` creates a **new event loop**, executes the coroutine, then **closes the loop and destroys all its state** when done. This means:

- The FastMCP `StreamableHTTPSessionManager`'s in-memory session store is **wiped on every request**.
- Even though `stateless_http=False` is set, sessions do not actually persist — every request starts fresh.
- The `Mcp-Session-Id` header sent by the MCP client is ignored because FastMCP's session lookup happens in a loop that no longer exists.

**Reference approach (correct):** `django-mcp-server` uses `asgiref.sync.async_to_sync`:
```python
from asgiref.sync import async_to_sync
result = async_to_sync(_call_starlette_handler)(request, self.session_manager)
```

`async_to_sync` reuses or creates a loop on the **current thread without destroying it**, keeping the session store alive across requests.

**Impact:** Session-dependent features (progressive disclosure via `mcp_enable_tools`, `mcp_disable_tools`) are non-functional. Users cannot scope tool visibility persistently.

**Severity:** Critical — session state is fundamentally broken.

---

### 3.2 Progressive Disclosure Silently Falls Back to Empty Set on Every Request (CRITICAL)

**File:** `nautobot_app_mcp_server/mcp/server.py`, lines 54–82

**Problem:** The `_list_tools_mcp` override attempts to access FastMCP's internal request context:
```python
try:
    req_ctx = Server.request_context.get()  # LookupError — every time
    ...
except LookupError:
    pass  # No request context (e.g., in tests) — fall through
```

Because `asyncio.run()` creates a loop-less execution context, `Server.request_context.get()` raises `LookupError` on **every production request** (not just tests). The code falls through to building a mock context with an **empty `session_dict = {}`**, which `MCPSessionState.from_session()` converts to empty `enabled_scopes` and `enabled_searches`.

The final filter then produces either:
- Zero tools returned (if `filtered_names_set` is empty and the filter is applied strictly), or
- All tools returned (if the filter gracefully falls back to all tools)

Either way, progressive disclosure does not work in production.

**Impact:** The `mcp_enable_tools`, `mcp_disable_tools`, and `mcp_list_tools` tools are effectively no-ops. All tools are always visible regardless of session state.

**Severity:** Critical — the core session-based tool scoping feature is broken.

---

### 3.3 Unguarded `_mcp_app` Singleton Race Condition (MODERATE)

**File:** `nautobot_app_mcp_server/mcp/server.py`, lines 122–131

**Problem:**
```python
global _mcp_app
if _mcp_app is None:
    mcp_instance = _setup_mcp_app()
    _mcp_app = mcp_instance.http_app(...)
```

Django's threaded workers can handle concurrent requests. Two threads hitting `get_mcp_app()` simultaneously could both pass the `None` check and create duplicate FastMCP instances. While the write is atomic, the double-checked locking pattern is not thread-safe as written — the second thread could overwrite the first instance.

**Reference approach:** `django-mcp-server` creates `global_mcp_server` as a plain module-level singleton, not lazily. This avoids the race entirely. Alternatively, use a threading lock:
```python
_lock = threading.Lock()
if _mcp_app is None:
    with _lock:
        if _mcp_app is None:
            _mcp_app = _setup_mcp_app()
```

**Severity:** Moderate — requires concurrent requests at startup to trigger; may only manifest under load.

---

### 3.4 Server Address Hardcoded in ASGI Scope (MINOR)

**File:** `nautobot_app_mcp_server/mcp/view.py`, line 43

```python
"server": ("127.0.0.1", 8080),
```

This should be derived from `request.get_host()` and `request.get_port()`. Hardcoding can cause incorrect behavior behind reverse proxies or on non-standard ports.

**Reference approach (from django-mcp-server):**
```python
"server": (request.get_host(), request.get_port()),
"scheme": "https" if request.is_secure() else "http",
```

**Severity:** Minor — primarily affects request logging and debugging; unlikely to break MCP functionality.

---

## 4. Performance Issues

### 4.1 Per-Request Event Loop Creation

Even after fixing `asyncio.run()` → `async_to_sync()`, the bridge still creates a new async execution context per request. `async_to_sync` is the correct approach for WSGI, but it carries synchronization overhead.

**Alternative (for future consideration):** Run Nautobot under an ASGI server (e.g., Uvicorn) and expose the MCP endpoint directly as an ASGI app, bypassing the WSGI bridge entirely. This would eliminate the `async_to_sync` overhead but requires changing Nautobot's deployment model.

**For the current WSGI setup:** `async_to_sync` is the right solution; the overhead is acceptable for the request volume expected.

---

### 4.2 Auth Token Lookup Without Request-Level Caching

**File:** `nautobot_app_mcp_server/mcp/auth.py`, line 70

```python
token = Token.objects.select_related("user").get(key=real_token_key)
```

Each tool call executes this query. If a single MCP request triggers multiple tool calls (batch execution), the token is looked up once per tool call. For batch operations, an `lru_cache` or thread-local cache keyed on token key would reduce DB load:

```python
from functools import lru_cache
@lru_cache(maxsize=128)
def _get_user_from_token(token_key: str):
    ...
```

Note: `lru_cache` on a mutable object (the function) needs careful consideration for Django's request lifecycle. A thread-local cache is safer.

---

### 4.3 MCPToolRegistry Fuzzy Search is O(n) Per Term

**File:** `nautobot_app_mcp_server/mcp/registry.py`, lines 85–95

```python
def fuzzy_search(self, term: str) -> list[ToolDefinition]:
    term_lower = term.lower()
    return [t for t in self._tools.values()
            if term_lower in t.name.lower() or term_lower in t.description.lower()]
```

With hundreds of tools and many fuzzy terms per session, this is a linear scan. For the current scale (tens of tools), this is negligible. If the tool registry grows to hundreds, consider a simple inverted index on word tokens.

---

## 5. Extensibility and API Design

### 5.1 What nautobot-app-mcp-server Does Well

**`register_mcp_tool()` public API** (`mcp/__init__.py`) provides a clean, explicit plugin interface for third-party Nautobot apps:

```python
from nautobot_app_mcp_server.mcp import register_mcp_tool

register_mcp_tool(
    name="juniper_bgp_neighbor_list",
    func=juniper_bgp_neighbor_list,
    description="List BGP neighbors on Juniper devices.",
    input_schema={...},
    tier="app",
    app_label="netnam_cms_core",
    scope="netnam_cms_core.juniper",
)
```

Called from a third-party app's `ready()` hook, this is a conventional and well-understood pattern. The `tier`, `scope`, and `app_label` fields provide enough metadata for progressive disclosure.

**Custom session state** via `MCPSessionState` is a good abstraction — it cleanly wraps FastMCP's session dict and provides typed access to `enabled_scopes` and `enabled_searches`.

### 5.2 Where django-mcp-server Is More Ergonomic

**Metaclass-based auto-discovery (higher productivity):**

`MCPToolset` subclasses auto-register via `ToolsetMeta.registry`. Every public method becomes an MCP tool automatically — no per-method registration:

```python
class MyAppTools(MCPToolset):
    def list_devices(self, region: str) -> list[dict]:
        """List devices in a region."""
        ...
    def get_device(self, id: str) -> dict:
        """Get a device by ID."""
        ...
# Both methods are automatically exposed as MCP tools.
```

In contrast, nautobot-app-mcp-server requires **hand-written `input_schema`** dicts for every tool. For a Nautobot app with 20+ CRUD tools, this is significant boilerplate.

**Auto-generated JSON Schema from Django models:**

`ModelQueryToolset.generate_json_schema()` introspects Django model fields and produces MongoDB-style `$jsonSchema`. Foreign keys, choices enums, required fields, and help text are all inferred. Nautobot's models already have rich field metadata — this could be leveraged similarly.

**DRF integration:**

The `_DRFRequestWrapper` + caller tool pattern in django-mcp-server is sophisticated — it converts DRF views into MCP tools while preserving serializer validation, permissions, and filtering. This is powerful for apps that already have a REST API.

### 5.3 Recommendation on Extensibility

The current explicit `register_mcp_tool()` API is **correct and maintainable** for the project's current scope. Adopting a metaclass-based registry is a larger refactor with diminishing returns unless the number of tools grows significantly.

A practical middle ground: a **type-hint-based schema generator** that auto-builds `input_schema` from function signatures using `inspect.signature` and PEP 704 type hints. This would reduce boilerplate for new tools without a full metaclass overhaul.

---

## 6. Additional Design Observations

### 6.1 Auth Placement

| Approach | Pros | Cons |
|----------|------|------|
| **Per-tool auth (current)** | Works for Nautobot's Token model; per-call granularity | DB lookup on every tool call; no early rejection |
| **DRF view-level (django-mcp-server)** | Single lookup per request; clean rejection before tool execution | Requires DRF; doesn't map cleanly to Nautobot's auth model |

For Nautobot specifically, the per-tool approach is reasonable since Nautobot's Token model is app-specific. However, **caching the user on the request object** (set once at MCP request entry, reused by all tools) would eliminate redundant DB lookups for batch operations.

### 6.2 Session Persistence Model

`nautobot-app-mcp-server` stores session state in FastMCP's **in-memory** `StreamableHTTPSessionManager` (per-connection, not persisted). `django-mcp-server` delegates to **Django's session backend** (cookie-based, survives restarts).

For a tool scoping feature where a user enables `dcim` scope for the duration of a conversation (across multiple HTTP requests), in-memory sessions mean **state is lost if the server restarts or the client reconnects**. If this is acceptable for the use case (ephemeral MCP clients), the current approach is fine. If persistent scoping is desired, consider delegating to Nautobot's session framework.

### 6.3 DRF Not Used — Trade-off

`MCPServerStreamableHttpView` in django-mcp-server is a DRF `APIView`, giving it free access to DRF's authentication, permission, and throttle classes. `mcp_view()` in nautobot-app-mcp-server is a plain Django view function — leaner, but all auth and permissions must be hand-rolled.

For Nautobot's custom Token auth, the manual approach is acceptable. If the app grows to need rate limiting or more sophisticated permissions, a DRF view migration would be straightforward.

---

## 7. Scorecard Summary

| Dimension | nautobot-app-mcp-server | django-mcp-server | Status |
|-----------|--------------------------|-------------------|--------|
| Session persistence | ❌ Broken (`asyncio.run()` destroys loop) | ✅ Works (`async_to_sync` + Django sessions) | Must fix |
| Progressive disclosure | ❌ Broken (LookupError on every request) | N/A (no equivalent feature) | Must fix |
| Lazy init (Django ORM safety) | ✅ Correct | ✅ Correct (module-level, no ORM at import) | Good |
| `_mcp_app` thread safety | ❌ Race condition on singleton | ✅ Module-level singleton | Should fix |
| Server address in ASGI scope | ❌ Hardcoded `("127.0.0.1", 8080)` | ✅ Derived from `request.get_host()` | Minor fix |
| Auth (per-tool, Nautobot Token) | ✅ Appropriate for Nautobot | DRF class-based (doesn't map cleanly to Nautobot) | OK — add request-level cache |
| Session state storage | In-memory (per-connection) | Django session backend (persistent) | Design choice — document tradeoff |
| Tool registration API | Explicit `register_mcp_tool()` | Declarative metaclass + DRF decorators | Current is fine; metaclass is ergonomic |
| JSON Schema for tools | Hand-written `input_schema` dict | Auto-generated from model fields | django-mcp-server more maintainable |
| DRF integration | None | Full (views, serializers, permissions → MCP tools) | N/A — Nautobot doesn't use DRF |
| Nautobot-specific features | ✅ Built for Nautobot Token auth, scoping | ❌ Generic Django | nautobot-app-mcp-server wins |
| Tool scope hierarchy (dcim.*, etc.) | ✅ `get_by_scope()` startswith matching | ❌ Not implemented | nautobot-app-mcp-server wins |
| Package model | App plugin (`register_mcp_tool()` in `ready()`) | Django app + toolset classes | Both are valid |

---

## 8. Priority Ranking for Refactoring

| Priority | Issue | Fix Effort |
|----------|-------|------------|
| **P0 — Critical** | Fix `asyncio.run()` → `async_to_sync` in `view.py` | ~10 lines |
| **P0 — Critical** | Fix progressive disclosure session access in `server.py` | Medium (requires P0 fix first) |
| **P1 — Moderate** | Add thread-safe locking to `get_mcp_app()` singleton | ~5 lines |
| **P1 — Moderate** | Cache user lookup in auth (`@lru_cache` or thread-local) | ~5 lines |
| **P1 — Moderate** | Derive server address from request in ASGI scope | ~2 lines |
| **P2 — Lower** | Auto-generate `input_schema` from type hints | Medium (nice-to-have) |
| **P2 — Lower** | Adopt metaclass-based tool registry | Higher effort, diminishing returns |
| **P2 — Lower** | Document session persistence tradeoffs (in-memory vs Django sessions) | Documentation only |

---

## 9. Key Files Reference

### Current Implementation

| File | Purpose | Key Concern |
|------|---------|-------------|
| `mcp/server.py` | FastMCP instance factory, `_list_tools_mcp` override | Session context access broken |
| `mcp/view.py` | Django WSGI → FastMCP ASGI bridge | `asyncio.run()` destroys session state |
| `mcp/session_tools.py` | `MCPSessionState`, session tools, `_list_tools_handler` | Depends on working session access |
| `mcp/registry.py` | `MCPToolRegistry` singleton, `ToolDefinition` | Thread-safe but not metaclass-based |
| `mcp/auth.py` | `get_user_from_request()` — Nautobot Token auth | No request-level caching |
| `mcp/__init__.py` | `register_mcp_tool()` — public API | Clean and well-designed |

### Reference Implementation

| File | Purpose | Worth Borrowing |
|------|---------|----------------|
| `mcp_server/djangomcp.py` | `DjangoMCP` + `async_to_sync` bridge | Yes — fix `asyncio.run()` issue |
| `mcp_server/query_tool.py` | `ModelQueryToolset`, `generate_json_schema()` | Partial — schema auto-generation |
| `mcp_server/views.py` | `MCPServerStreamableHttpView` (DRF) | Partial — DRF auth/plumbing |
| `mcp_server/urls.py` | URL routing with auth config | Reference only |

---

## 10. Document History

| Date | Author | Change |
|------|--------|--------|
| 2026-04-03 | Claude | Initial analysis: architecture, correctness, performance, extensibility |
