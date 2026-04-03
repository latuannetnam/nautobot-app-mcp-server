# Project Research Summary

**Project:** nautobot-app-mcp-server v1.1.0 — django-mcp-server Deep Dive
**Domain:** Django WSGI App embedding a FastMCP ASGI server (WSGI→ASGI bridge, session persistence)
**Researched:** 2026-04-03
**Confidence:** HIGH — Source-verified from django-mcp-server v0.5.6 and `mcp` SDK `streamable_http_manager.py`

---

## Executive Summary

The v1.1.0 milestone is a **single-root-cause fix** — the entire broken session state and progressive disclosure behavior traces back to one line: `asyncio.run()` inside `view.py`. Every `asyncio.run()` call creates a fresh event loop, executes the FastMCP request handler, then destroys the loop — taking FastMCP's `Server.request_context` ContextVar and in-memory session dict with it. This means `MCPSessionState` written by `mcp_enable_tools` is gone before the next request arrives, `Server.request_context.get()` raises `LookupError` on every production call, and progressive disclosure silently falls back to all-or-nothing behavior.

The fix is sourced directly from `django-mcp-server`: replace `asyncio.run()` with `asgiref.sync.async_to_sync` wrapping an `_call_starlette_handler` async function that builds the ASGI scope from the Django request and calls `session_manager.handle_request()` inside `async with session_manager.run():`. This keeps the event loop alive across requests, making `Server.request_context` available and session dicts persistent. The change touches exactly two files (`mcp/view.py`, `mcp/server.py`) and introduces no new dependencies.

The main risk is the session manager's `run()` context manager — it raises `RuntimeError` if entered more than once per instance, so the session manager itself must be a module-level singleton created once at startup (or lazy-init with double-checked locking), while `run()` is entered once per request inside `async_to_sync`. This is the exact pattern django-mcp-server uses and is well-understood.

## Key Findings

### Recommended Stack

The existing stack is complete — no new packages needed. All required APIs are already installed as transitive dependencies of `fastmcp` and Django. The fix is purely a refactor of how the ASGI app is called from the WSGI Django view.

**Core technologies:**
- `asgiref.sync.async_to_sync` — THE critical fix. Unlike `asyncio.run()`, it reuses or creates a loop on the current thread **without destroying it**, keeping FastMCP's `Server.request_context` ContextVar and `StreamableHTTPSessionManager` task group alive across multiple requests on the same worker thread.
- `mcp.server.streamable_http_manager.StreamableHTTPSessionManager` — Already used. Its `run()` context manager enters the FastMCP session context; its `handle_request()` dispatches to the MCP protocol handler. Both must be called inside an active event loop managed by `async_to_sync`.
- `contextvars.ContextVar` — stdlib thread-safe carrier for the Django `HttpRequest` object into async tool handlers without coupling to MCP internals.
- `starlette.types` (`Scope`, `Receive`, `Send`) and `starlette.datastructures.Headers` — Already transitive deps; used to construct the ASGI scope dict and collect HTTP response parts.

### Expected Features

**Must have (table stakes):**
- `async_to_sync` WSGI→ASGI bridge — restores session state and `Server.request_context`; the single most critical fix
- `async with session_manager.run():` per request — enters FastMCP's task group so `Server.request_context.get()` works inside tool handlers
- Thread-safe singleton for `get_mcp_app()` — double-checked locking with `threading.Lock()` prevents duplicate FastMCP instances under concurrent Django worker load
- ASGI scope server address from `request.get_host()` / `request.get_port()` — replaces hardcoded `("127.0.0.1", 8080)`
- `stateless_http=False` kept — FastMCP in-memory sessions are fine for Docker single-process; needed for progressive disclosure

**Should have (competitive):**
- Request-level auth caching on MCP session dict — `ctx.request_context.session["cached_user"]` avoids N DB queries per batch MCP request (N = tool calls in batch)
- `_nautobot_request_ctx` context var — stores Django `HttpRequest` at entry point so tools access it without explicit passing
- `_call_starlette_handler` factored cleanly in `view.py` — mirrors django-mcp-server's pattern; makes the scope-building logic independently testable

**Defer (v2+):**
- Metaclass-based tool registry (`MCPToolset` / `ToolsetMeta`) — ergonomic for 50+ tools; not needed for ~10 core tools
- Django session backend delegation for persistent scoping across process restarts — only needed for multi-worker deployments
- `generate_input_schema()` from function type hints — reduces boilerplate for new tools; not blocking
- Write tools (create/update/delete) — permission surface widens; agents use Nautobot REST API directly
- Redis session backend for shared MCP sessions across workers — over-engineering for v1

### Architecture Approach

The architecture is a thin WSGI→ASGI bridge: Django receives an HTTP request, `mcp_view` calls `async_to_sync(_call_starlette_handler)(request, session_manager)`, which builds an ASGI scope dict from the Django request, then calls `session_manager.handle_request()` inside `async with session_manager.run():`. FastMCP's `Server.request_context.set(ctx)` fires inside `handle_request()`, making `Server.request_context.get()` available to the `_list_tools_mcp` override and all tool handlers for the duration of that request. The session dict lives in `StreamableHTTPSessionServerTransport` inside the task group and persists across requests because the event loop is not destroyed.

**Major components:**
1. `mcp/view.py` — Django WSGI entry (`mcp_view`). Rewritten to use `async_to_sync` + `_call_starlette_handler`. Gets or creates the `StreamableHTTPSessionManager` singleton from `server.py`.
2. `mcp/server.py` — FastMCP factory + lazy singleton. Adds `threading.Lock` double-checked locking to `get_mcp_app()` and exposes `get_session_manager()` for `view.py`. The `StreamableHTTPSessionManager` is created alongside the `http_app()` call.
3. `mcp/auth.py` — Token auth layer. Adds session-level caching via `ctx.request_context.session["cached_user"]` to avoid per-tool-call DB lookups.

### Critical Pitfalls

1. **`asyncio.run()` destroys FastMCP session state on every request** — The loop is created and destroyed per call. `Server.request_context` is cleared. `MCPSessionState` writes vanish. Fix: `async_to_sync(_call_starlette_handler)(request, session_manager)`. **P0 — v1.1.0.**

2. **`Server.request_context.get()` raises `LookupError` on every production request** — ContextVar only set inside `session_manager.run()`. With `asyncio.run()`, the task group never survives. Fix: `async_to_sync` + `session_manager.run()` (fixes Pitfall 1 automatically). **P0 — v1.1.0.**

3. **`session_manager.run()` must be entered once and only once per instance** — `StreamableHTTPSessionManager.run()` raises `RuntimeError` if called twice. Fix: one manager instance (module-level singleton or lazy with lock), `run()` entered per-request inside `async_to_sync` via `_call_starlette_handler`. **P0 — v1.1.0.**

4. **FastMCP lifespan must be wired to the ASGI app** — `http_app()` returns a Starlette app with a lifespan that wraps `session_manager.run()`. Calling it as a plain ASGI callable without Starlette routing bypasses the lifespan. Fix: never call `http_app()` directly as a callable; always go through `session_manager.handle_request()` inside an active `run()` context. **P0 — v1.1.0.**

5. **Thread-unsafe `_mcp_app` singleton in `get_mcp_app()`** — Two concurrent first requests can create duplicate FastMCP instances. Fix: `threading.Lock` double-checked locking. **P1 — v1.1.0.**

---

## Implications for Roadmap

The research narrows the v1.1.0 milestone to exactly one phase: a concentrated, low-risk refactor of two files using source-verified patterns from django-mcp-server. All P0 issues share the same root cause and fix.

### Phase 1: WSGI→ASGI Bridge Refactor
**Rationale:** All broken behavior (session state loss, LookupError, progressive disclosure failure) traces to `asyncio.run()`. Fixing it with `async_to_sync` is the single change that restores correctness. No new features, no schema changes, no data migration.

**Delivers:**
- `view.py`: `_call_starlette_handler` async function building ASGI scope from Django request; `async_to_sync` wrapper replacing `asyncio.run()`; `async with session_manager.run():` context; `receive()` returns actual request body; `send()` collects status + headers + body
- `server.py`: `get_session_manager()` exposing `StreamableHTTPSessionManager`; `threading.Lock` double-checked locking on `_mcp_app` singleton; `stateless_http=False` confirmed
- `auth.py`: `ctx.request_context.session["cached_user"]` caching

**Addresses:**
- P0: `asyncio.run()` destroys session → `async_to_sync` preserves loop
- P0: `Server.request_context` LookupError → resolved by `session_manager.run()` keeping task group alive
- P0: lifespan wiring → `session_manager.run()` called per-request inside `async_to_sync`
- P1: thread-unsafe singleton → double-checked locking
- P1: hardcoded server address → `request.get_host()` / `request.get_port()`
- P1: uncached token lookups → MCP session dict cache

**Avoids:**
- `session_manager.run()` re-entry error — one manager instance, one `run()` per request
- Django ORM in async context without `sync_to_async` — all ORM calls are sync in current tool implementations

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (integration test design):** Need an integration test that sends two sequential MCP HTTP requests with `Mcp-Session-Id` header and verifies the second request's `mcp_list_tools` response reflects scopes enabled in the first. This is non-trivial to set up and must be designed carefully before implementation.

Phases with standard patterns (skip research-phase):
- **All of Phase 1:** Every pattern is source-verified from django-mcp-server with direct code references. No further research needed — execute directly.
- **P2 auth caching (`contextvars`):** django-mcp-server pattern is well-documented; implement directly.

### Phase Ordering Rationale

- This is a single-phase milestone because all P0s share one root cause — fixing `asyncio.run()` resolves the entire class of failures simultaneously.
- No feature work is included in v1.1.0. Locking in the correct bridge pattern first ensures progressive disclosure, session tools, and auth caching are built on a sound foundation.
- v1.2+ can then add `generate_input_schema()`, the `django_request_ctx` context var, and metaclass registry evaluation with confidence the session layer is solid.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All APIs source-verified in installed `.venv/` packages and django-mcp-server GitHub source. No new dependencies. |
| Features | HIGH | All patterns extracted verbatim from django-mcp-server source. `MCPToolRegistry` singleton retained (not replaced). |
| Architecture | HIGH | Exact data flow verified from django-mcp-server `handle_django_request()` + `_call_starlette_handler()` source. Current broken flow also verified from `view.py` + `server.py`. |
| Pitfalls | HIGH | All 6 pitfalls derived from source analysis: `asgiref/sync.py` loop lifetime, `StreamableHTTPSessionManager.run()` guard, `Server.request_context` ContextVar behavior, FastMCP lifespan wiring. |

**Overall confidence:** HIGH

### Gaps to Address

- **Integration test for session persistence:** There is currently no test that sends two sequential MCP HTTP requests and verifies session state survives. Designing and implementing this test is needed to verify the fix before shipping. The test must use the real `StreamableHTTPSessionManager` (not mocked) and assert on actual tool list filtering.
- **`run()` per-request vs. once-at-startup behavior:** django-mcp-server uses Starlette's lifespan to call `session_manager.run()` once at startup. The current Nautobot approach (calling `run()` per-request inside `async_to_sync`) needs verification that `run()` can be safely re-entered across multiple requests on the same session manager instance in a ThreadPoolExecutor loop. Source-verified as correct but should be covered by integration test.

---

## Sources

### Primary (HIGH confidence)
- `mcp/server/streamable_http_manager.py` (mcp SDK, via fastmcp) — `StreamableHTTPSessionManager.__init__`, `run()`, `handle_request()`, `_has_started` guard — **source-verified in `.venv/`**
- `asgiref/sync.py` (via Django/fastmcp) — `AsyncToSync.__call__` (lines 211–325), ThreadPoolExecutor + `asyncio.run` fallback — **source-verified in `.venv/`**
- `https://github.com/gts360/django-mcp-server` (`mcp_server/djangomcp.py`) — `_call_starlette_handler`, `DjangoMCP.handle_django_request`, `StreamableHTTPSessionManager` property — **source-verified via WebFetch**
- `https://github.com/gts360/django-mcp-server` (`mcp_server/views.py`) — `MCPServerStreamableHttpView`, DRF APIView, `@csrf_exempt` — **source-verified via WebFetch**
- `mcp/server/lowlevel/server.py` (mcp SDK, via fastmcp) — `Server.request_context` ContextVar, `_handle_request()` context setup — **source-verified in `.venv/`**
- `fastmcp/server/http.py` (via fastmcp) — `StreamableHTTPASGIApp`, lifespan wiring, `RuntimeError: Task group is not initialized` message — **source-verified in `.venv/`**
- `docs/dev/mcp-implementation-analysis.md` — existing correctness analysis, P0/P1 priority ranking — **source-verified**
- `nautobot_app_mcp_server/mcp/server.py` — current broken `get_mcp_app()` — **source-verified**
- `nautobot_app_mcp_server/mcp/view.py` — current broken `asyncio.run()` bridge — **source-verified**

### Secondary (MEDIUM confidence)
- `https://github.com/gts360/django-mcp-server` (`mcp_server/query_tool.py`) — `generate_json_schema()`, `MCPToolset` metaclass — **source-verified via WebFetch; not directly applicable to Nautobot's approach but useful for future P2 work**
- `https://github.com/gts360/django-mcp-server` (`mcp_server/urls.py`) — DRF auth wiring at URL level — **source-verified; Nautobot has no DRF, so pattern is illustrative only**

### Tertiary (LOW confidence)
- Thread-safety of `async_to_sync` + `StreamableHTTPSessionManager` under uWSGI threaded workers — documented pattern from django-mcp-server assumes gunicorn; Nautobot Docker uses Runserver; verify under uWSGI before production multi-threaded deployment

---
*Research completed: 2026-04-03*
*Ready for roadmap: yes*
