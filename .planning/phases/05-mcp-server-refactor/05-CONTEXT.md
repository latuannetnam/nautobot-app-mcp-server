# Phase 5: MCP Server Refactor - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the broken `asyncio.run()` WSGI→ASGI bridge in `view.py` and add auth caching. The refactor restores FastMCP session state persistence and progressive disclosure (broken since Phase 1/2). Scope: `view.py` rewrite, `server.py` thread-safety + session manager exposure, `auth.py` caching, new integration test.

Phase 5 delivers: REFA-01 through REFA-05, AUTH-01, AUTH-02, TEST-01 through TEST-03.

</domain>

<decisions>
## Implementation Decisions

### ASGI Scope Builder
- **D-01:** Server address: `request.get_host()` and `request.get_port()` — NOT hardcoded `("127.0.0.1", 8080)`
- **D-02:** Scheme: `request.is_secure()` — returns `"https"` or `"http"` based on Django's request detection
- **D-03:** Client IP: `request.META.get("REMOTE_ADDR")` — NOT trust X-Forwarded-For (simple approach; proxy handling deferred to production infra config)
- **D-04:** `Content-Length` header included in ASGI scope `headers` list (from django-mcp-server pattern)

### Session Manager Architecture
- **D-05:** Two separate singletons in `server.py`: `_mcp_app` (Starlette ASGI app) + `_session_mgr` (`StreamableHTTPSessionManager` instance)
- **D-06:** `get_session_manager()` exposed as separate function from `get_mcp_app()` — clean separation of concerns
- **D-07:** Separate `threading.Lock` per singleton (double-checked locking for each independently)
- **D-08:** `_session_mgr` initialized alongside `_mcp_app` in `_setup_mcp_app()` — session manager created when FastMCP instance is created, NOT lazily on first request

### Bridge Implementation (REFA-01, REFA-02)
- **D-09:** `view.py` uses `asgiref.sync.async_to_sync(_call_starlette_handler)(request, session_manager)` — replaces `asyncio.run()`
- **D-10:** `_call_starlette_handler()` is an `async def` that:
  1. Builds ASGI scope dict from Django request (D-01 through D-04)
  2. Calls `async with session_manager.run():` to enter FastMCP task group
  3. Calls `await session_manager.handle_request(scope, receive, send)` inside the context
- **D-11:** `receive()` returns actual request body from `request.body` (not always empty as current code does)
- **D-12:** `send()` collects `http.response.start` (status, headers) and `http.response.body` (chunks) into a `list[dict]` for assembly into `HttpResponse`

### Session Storage (CRITICAL — surfaced during Phase 5 planning)
- **D-24 (REFA-06):** `ctx.request_context.session` in tool handlers is `MCPToolSession` (an MCP SDK class, NOT a plain dict). The `MCPSessionState.from_session()` and `apply_to_session()` methods use `session.get()`/`session["key"]` syntax — this ONLY works if `MCPToolSession` implements `__getitem__`/`__setitem__`. Source-verify this by checking `mcp/server/lowlevel/servertypes.py` in the installed `.venv/`. If it does NOT have dict methods, the fix is: store state as attributes on `ctx.request_context` itself (which IS a plain Python object with dict-access), NOT on `ctx.request_context.session`.

### Auth Caching
- **D-13:** User cached on `ctx.request_context` attribute `_cached_user` (NOT on session dict, since session may not be dict-like). Pattern: `if not hasattr(ctx.request_context, '_cached_user'): ctx.request_context._cached_user = token.user`
- **D-14:** Cache key: token key string; cache hit returns cached user directly; cache miss falls through to `Token.objects.select_related("user").get()`
- **D-15:** Cache populated immediately after successful token lookup, before returning user
- **D-16:** Cache scoped to FastMCP's MCP session dict (not Django session) — survives across tool calls within same MCP request batch, cleared on MCP session expiry

### Integration Test (TEST-02)
- **D-17:** Uses real `StreamableHTTPSessionManager` — not mocked
- **D-18:** Runs inside Docker container (`docker exec ... python /source/nautobot_app_mcp_server/mcp/tests/test_session_persistence.py`)
- **D-19:** Test verifies: send MCP HTTP POST #1 (initialize + mcp_enable_tools scope="dcim"), send MCP HTTP POST #2 (mcp_list_tools) with same `Mcp-Session-Id` — second response includes tools from enabled scope
- **D-20:** Test file location: `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py`

### Carry-Forward Decisions (from earlier phases)
- **D-20 (from Phase 2, D-20):** Progressive disclosure via `_list_tools_mcp` override — already implemented in `server.py`. After P0 fix, `Server.request_context.get()` works inside tool handlers.
- **D-21 (from Phase 2, D-21):** Scope hierarchy: enabling parent scope enables all children (`startswith(f"{scope}.")` matching). Unchanged.
- **D-22 (from Phase 2, D-22):** Auth token extraction from `ctx.request_context.request.headers.get("Authorization", "")`. Unchanged.
- **D-23 (from Phase 2, D-23):** Anonymous auth logging: missing → `logger.warning`, invalid → `logger.debug`. Unchanged.

### Claude's Discretion
- Exact `Content-Length` header parsing: whether to read `request.META.get("CONTENT_LENGTH")` as int or str
- How `send()` handles `http.response.trailers` (HTTP/2 feature — FastMCP may not emit these)
- Exact test assertions: exact tool names expected in `mcp_list_tools` response after scope enable
- Whether `_call_starlette_handler` is defined inside `mcp_view()` or at module level in `view.py`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Refactor Patterns (PRIMARY)
- `.planning/research/SUMMARY.md` — executive summary, all 6 P0/P1 pitfalls, architecture approach
- `.planning/research/ARCHITECTURE.md` — exact `_call_starlette_handler` pattern, ASGI scope fields, `session_manager.run()` context
- `.planning/research/STACK.md` — `async_to_sync` vs `asyncio.run()`, `StreamableHTTPSessionManager.run()` semantics
- `.planning/research/PITFALLS.md` — P0: asyncio.run() destroys loop, P0: Server.request_context LookupError, P1: `run()` re-entry, P1: thread-unsafe singleton
- `.planning/research/FEATURES.md` — django-mcp-server DjangoMCP class structure, session manager property

### Implementation Source (django-mcp-server)
- `https://github.com/gts360/django-mcp-server` — `mcp_server/djangomcp.py` `_call_starlette_handler`, `DjangoMCP.handle_django_request`
- `https://github.com/gts360/django-mcp-server` — `mcp_server/views.py` `MCPServerStreamableHttpView`

### Prior Phase Context
- `.planning/phases/02-authentication-sessions/02-CONTEXT.md` — session decisions (D-19 through D-27)
- `.planning/phases/01-mcp-server-infrastructure/01-CONTEXT.md` — Phase 1 decisions (D-01 through D-18)

### Requirements
- `.planning/REQUIREMENTS.md` — REFA-01 through REFA-05, AUTH-01, AUTH-02, TEST-01 through TEST-03
- `.planning/ROADMAP.md` §Phase 5 — Phase 5 requirements table, success criteria

### Implementation Analysis
- `docs/dev/mcp-implementation-analysis.md` — root cause analysis, P0/P1 ranking, scorecard

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Files to Modify
- `nautobot_app_mcp_server/mcp/view.py` — 82 lines; REFA-01, REFA-02, REFA-03: replace `asyncio.run()` with `async_to_sync` pattern
- `nautobot_app_mcp_server/mcp/server.py` — 131 lines; REFA-04 (add `get_session_manager()`), REFA-05 (add threading locks)
- `nautobot_app_mcp_server/mcp/auth.py` — 75 lines; AUTH-01, AUTH-02: add session-level user caching

### Files to Create
- `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — TEST-02: integration test

### Reusable Assets
- `MCPToolRegistry` — unchanged, still used by `register_mcp_tool()`
- `session_tools.py` — unchanged, `_list_tools_handler` still called from `progressive_list_tools_mcp` override
- `_setup_mcp_app()` in `server.py` — still runs; `_session_mgr` created alongside FastMCP instance

### Integration Points
- `view.py` → `server.py`: calls both `get_mcp_app()` and `get_session_manager()`
- `view.py` → `auth.py`: unchanged (tools call `get_user_from_request()` directly)
- `auth.py` → FastMCP session: `ctx.request_context.session["cached_user"]` read/write

### Key Patterns
- `asgiref.sync.async_to_sync` — wraps async callable; current import not present in `view.py`
- `from mcp.server.streamable_http_manager import StreamableHTTPSessionManager` — needed for type hints
- `from mcp.server.lowlevel.server import Server` — `Server.request_context` ContextVar already imported in `server.py`

</codebase_context>

<deferred>
## Deferred Ideas

- Proxy support (X-Forwarded-Host, X-Forwarded-For) — add when deploying behind reverse proxy
- Django session backend delegation for persistent scoping across process restarts — v2
- `django_request_ctx` context var for passing Django HttpRequest to async tool handlers — v2

</deferred>

---

*Phase: 05-mcp-server-refactor*
*Context gathered: 2026-04-03*
