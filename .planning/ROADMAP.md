# Project Roadmap — `nautobot-app-mcp-server`

**Project:** Nautobot App MCP Server
**Roadmap defined:** 2026-04-01
**Horizon:** v1.1.0
**Phases:** 6 (v1.0: Phases 0–4; v1.1.0: Phase 5)

---

## Overview

This roadmap is derived from 47 v1 requirements across 6 domain areas. Each phase produces a working, testable increment. Phases 1–4 can be developed in parallel by separate workers once Phase 0 is complete.

**Phase dependencies:**
```
Phase 0 ──► Phase 1 ──► Phase 3
                │             ▲
                ▼             │
            Phase 2 ──────────┘
                │
                ▼
            Phase 4
```

- Phase 1 (Infrastructure) must complete before Phase 3 (Tools) can be tested end-to-end.
- Phase 2 (Auth + Sessions) can be started as soon as Phase 1's registry exists.
- Phase 4 (SKILL.md) depends on all previous phases being stable.
- Phase 5 (MCP Server Refactor) can begin immediately — all patterns source-verified from django-mcp-server.

---

## Phase Summary

| Phase | Name | Requirements | Tests | Key Output |
|---|---|---|---|---|
| **Phase 0** | Project Setup | 4 (FOUND-01, 03, 04; TEST-05) | 0 new | `pyproject.toml` updated, coverage threshold set |
| **Phase 1** | MCP Server Infrastructure | 14 (FOUND-02, 05; SRVR-01–06; REGI-01–04; TEST-03, 04) | 2 test files | FastMCP endpoint reachable at `/plugins/nautobot-app-mcp-server/mcp/` |
| **Phase 2** | Authentication & Sessions | 10 (REGI-05; AUTH-01–03; SESS-01–06; TEST-06) | 1 test file | Token auth enforced, session scopes functional |
| **Phase 3** | Core Read Tools | 15 (TOOL-01–10; PAGE-01–05; TEST-02) | 1 test file | 10 core tools + 3 meta tools operational |
| **Phase 4** | SKILL.md Package | 3 (SKILL-01–03) | 0 new | `nautobot-mcp-skill/` pip package published |
| **Phase 5** | MCP Server Refactor | 10 (REFA-01–05; AUTH-01–02; TEST-01–03) | 1 integration test | Session state persists; progressive disclosure works |

**Total: 57 requirements, 6 phases, 5 test files**

---

## Phase 0 — Project Setup

**Purpose:** Resolve the 3 blocking issues identified in the codebase survey before any implementation begins. Set coverage policy.

**Requirements:**

| ID | Requirement |
|---|---|
| FOUND-01 | Add `mcp ^1.26.0`, `fastmcp ^3.2.0`, `asgiref ^3.11.1` to `pyproject.toml` |
| FOUND-03 | Resolve package name — use `nautobot_app_mcp_server` everywhere (not `nautobot_mcp_server`) |
| FOUND-04 | Resolve `base_url` — use `nautobot-app-mcp-server` (matches Nautobot plugin convention); endpoint at `/plugins/nautobot-app-mcp-server/mcp/` |
| TEST-05 | Set `fail_under = 50` for coverage in `pyproject.toml` |

**Not included:** FOUND-02 (package structure creation) belongs in Phase 1 where it is first needed.

**Success Criteria:**

1. `poetry lock && poetry install` succeeds with no resolution errors
2. `poetry run python -c "import mcp, fastmcp, asgiref; print('deps OK')"` succeeds
3. `base_url` in `__init__.py` is `nautobot-app-mcp-server`
4. All imports use `nautobot_app_mcp_server` (not `nautobot_mcp_server`)
5. `poetry run coverage` run on existing tests does not fail due to missing threshold config

**Verification:** `poetry run invoke tests` passes on the minimal shell; deps resolve cleanly.

---

## Phase 1 — MCP Server Infrastructure

**Purpose:** Build the embedded FastMCP server scaffold — plugin wiring, ASGI bridge, URL routing, and the tool registry. No auth, no tools yet. This phase validates the core architectural decision (Option A: ASGI bridge via `asgiref.wsgi.WsgiToAsgi`).

**Requirements:**

| ID | Requirement |
|---|---|
| FOUND-02 | Create `nautobot_app_mcp_server/mcp/` package structure with `__init__.py` |
| FOUND-05 | Fix `NotImplementedError` in DESIGN.md Option A — implement ASGI bridge via `asgiref.wsgi.WsgiToAsgi` |
| SRVR-01 | FastMCP instance with `stateless_http=False`, `json_response=True` |
| SRVR-02 | `get_mcp_app()` lazy factory — ASGI app created on first HTTP request, not at import time |
| SRVR-03 | `streamable_http_app()` mounted at `/plugins/nautobot-app-mcp-server/mcp/` via Django URL route |
| SRVR-04 | ASGI bridge view (`WsgiToAsgi`) converting Django request → FastMCP ASGI → Django response |
| SRVR-05 | `urls.py` with `path("mcp/", mcp_view)` — auto-discovered by Nautobot plugin system |
| SRVR-06 | `post_migrate` signal wiring core tools registration after all apps' `ready()` hooks |
| REGI-01 | `MCPToolRegistry` thread-safe singleton with `threading.Lock` |
| REGI-02 | `ToolDefinition` dataclass with name, func, description, input_schema, tier, scope fields |
| REGI-03 | `register_mcp_tool()` public API for third-party Nautobot apps |
| REGI-04 | `get_core_tools()`, `get_by_scope()`, `fuzzy_search()` registry methods |
| TEST-03 | `test_view.py` — ASGI bridge, HTTP round-trip, endpoint reachability |
| TEST-04 | `test_signal_integration.py` — `post_migrate` timing, tool registration, third-party tool discovery |

**Success Criteria:**

1. `GET /plugins/nautobot-app-mcp-server/mcp/` returns a valid MCP JSON-RPC response (HTTP 200, no 500)
2. `POST /plugins/nautobot-app-mcp-server/mcp/` with an MCP `initialize` request returns a valid MCP `initialize` response
3. `MCPToolRegistry` is a true singleton — two instantiations return the same object; `threading.Lock` prevents race on concurrent `register()`
4. `register_mcp_tool()` can be called from a `post_migrate` signal and the tool appears in `get_core_tools()`
5. `get_mcp_app()` called twice returns the same app object (lazy factory, not re-created)
6. `test_view.py` endpoint reachability test passes
7. `test_signal_integration.py` `post_migrate` timing test passes

**Known pitfalls to avoid (from PITFALLS.md):**
- PIT-02: Package name `nautobot_mcp_server` vs `nautobot_app_mcp_server` — must match
- PIT-03: ASGI app created at import time (use lazy factory)
- PIT-04: Wrong ASGI bridge (`async_to_sync` instead of `WsgiToAsgi`)
- PIT-09: `base_url` mismatch
- PIT-14: `search_by_name` complexity underestimated (defer to Phase 3)

---

## Phase 2 — Authentication & Sessions

**Purpose:** Add token-based auth and per-session tool visibility state. Auth extracts the Nautobot user from the MCP request context; sessions track which tool scopes are enabled per `Mcp-Session-Id`.

**Requirements:**

| ID | Requirement |
|---|---|
| REGI-05 | `@mcp.list_tools()` override for progressive disclosure — returns session-active tools only |
| AUTH-01 | `get_user_from_request()` extracting Nautobot user from MCP request context `Authorization: Token nbapikey_xxx` header |
| AUTH-02 | `AnonymousUser` returns empty queryset (not error) with debug warning logged |
| AUTH-03 | Nautobot object-level permissions via `.restrict(user, action="view")` on every queryset |
| SESS-01 | `MCPSessionState` dataclass with `enabled_scopes` and `enabled_searches` |
| SESS-02 | Session state stored per `Mcp-Session-Id` via FastMCP `StreamableHTTPSessionManager` |
| SESS-03 | `mcp_enable_tools(scope=...)` tool enabling exact scope + children and fuzzy search |
| SESS-04 | `mcp_disable_tools(scope=...)` tool disabling scopes |
| SESS-05 | `mcp_list_tools()` tool returning all registered tools filtered by session state |
| SESS-06 | Core tools always enabled regardless of session state |
| TEST-06 | Auth test: valid token → data, invalid token → empty + warning logged |

**Note:** REGI-05 (progressive disclosure via `@mcp.list_tools()`) requires the FastMCP instance from Phase 1.

**Success Criteria:**

1. Valid `Authorization: Token nbapikey_xxx` header → `request.user` is the correct Nautobot user
2. Missing or invalid token → `AnonymousUser`, empty queryset returned, `WARNING` log line emitted
3. `mcp_enable_tools(scope="ipam")` enables all IPAM tools; `mcp_disable_tools(scope="ipam")` disables them
4. `mcp_list_tools()` returns 3 core meta tools + all enabled scope tools (core tools always present)
5. All querysets call `.restrict(user, action="view")` — verified by mock assertion in tests
6. `test_auth` (TEST-06) passes: valid token → queryset has data; invalid token → queryset is empty

**Known pitfalls to avoid:**
- PIT-10: Anonymous auth silent empty results (must log warning)
- PIT-16: Auth token from wrong request object (use MCP request context, not Django `request`)

---

## Phase 3 — Core Read Tools

**Purpose:** Implement all 10 core read tools and 3 meta tools with pagination, serialization, and permission enforcement. This is the largest phase — 15 requirements.

**Requirements:**

| ID | Requirement |
|---|---|
| TOOL-01 | `device_list` — list devices with status, platform, location; `select_related`; paginate; `restrict(user)` |
| TOOL-02 | `device_get` — single device by name or pk with interfaces prefetched |
| TOOL-03 | `interface_list` — list interfaces filtered by device_name; paginate; `restrict(user)` |
| TOOL-04 | `interface_get` — single interface by pk with ip_addresses prefetched |
| TOOL-05 | `ipaddress_list` — list IP addresses with tenant, vrf; paginate; `restrict(user)` |
| TOOL-06 | `ipaddress_get` — single IP address by address or pk with interfaces prefetched |
| TOOL-07 | `prefix_list` — list prefixes with vrf, tenant; paginate; `restrict(user)` |
| TOOL-08 | `vlan_list` — list VLANs with site, group; paginate; `restrict(user)` |
| TOOL-09 | `location_list` — list locations with location_type, parent; paginate; `restrict(user)` |
| TOOL-10 | `search_by_name` — multi-model name search across devices, interfaces, IPs, prefixes, VLANs, locations |
| PAGE-01 | `paginate_queryset(qs, limit, cursor)` with `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000` |
| PAGE-02 | `LIMIT_SUMMARIZE=100` — auto-summarize when raw count > 100, count BEFORE slicing |
| PAGE-03 | `PaginatedResult` dataclass with items, cursor, total_count, summary fields |
| PAGE-04 | Cursor encoding as `base64(str(pk))` — works for UUID and string PKs |
| PAGE-05 | `sync_to_async(fn, thread_sensitive=True)` for all ORM calls inside async tool handlers |
| TEST-02 | `test_core_tools.py` — ORM mocking, pagination, auth enforcement, anonymous fallback |

**Implementation note:** TOOL-10 (`search_by_name`) requires multi-model queries — see PIT-14. Estimate it as 2–3× the effort of a single-model tool.

**Success Criteria:**

1. Each tool returns a `PaginatedResult` with `items`, `cursor`, `total_count`, and `summary` (when count > 100)
2. `paginate_queryset` counts BEFORE slicing — auto-summarize fires correctly at 100+
3. Cursor encoding/decoding round-trips correctly for both UUID and string primary keys
4. All ORM calls use `sync_to_async(..., thread_sensitive=True)` — no thread-local pool errors
5. `device_get` returns interfaces prefetched; `interface_get` returns ip_addresses prefetched
6. `search_by_name(" juniper ")` fuzzy-matches device names; results limited to 25 by default, max 1000
7. All tools respect `.restrict(user, action="view")` — mock test asserts this on every queryset call
8. `test_core_tools.py` passes with mocked ORM (no real Nautobot database required for unit tests)

**Known pitfalls to avoid:**
- PIT-07: Pagination counts after slice (auto-summarize never fires) — count BEFORE `qs[:limit]`

---

## Phase 4 — SKILL.md Package

**Purpose:** Package the SKILL.md documentation as a standalone pip package consumable by AI agents. This closes the "progressive disclosure" loop — agents can read the skill file to understand available tools and workflows.

**Requirements:**

| ID | Requirement |
|---|---|
| SKILL-01 | `nautobot-mcp-skill/` pip package with SKILL.md |
| SKILL-02 | SKILL.md with Core Tools reference table, scope management patterns, pagination docs |
| SKILL-03 | SKILL.md with investigation workflows (investigate device, find by name, explore Juniper BGP) |

**Package structure:**
```
nautobot-mcp-skill/
├── SKILL.md              # Primary skill definition
├── pyproject.toml
└── nautobot_mcp_skill/
    └── __init__.py        # Version, metadata
```

**Success Criteria:**

1. `pip install nautobot-mcp-skill` installs the package without errors
2. `SKILL.md` exists at package root with a Core Tools reference table (all 10 core + 3 meta tools)
3. `SKILL.md` documents scope management: `mcp_enable_tools(scope=...)`, `mcp_disable_tools(scope=...)`, `mcp_list_tools()`
4. `SKILL.md` documents pagination: default=25, max=1000, summarize-at-100 behavior, cursor format
5. `SKILL.md` includes at least 3 investigation workflows with step-by-step tool sequences:
   - Investigate device by name
   - Find IP address by prefix
   - Explore device interfaces and BGP addresses

---

## Phase 5 — MCP Server Refactor

**Purpose:** Fix the single root cause (P0) that breaks session state and progressive disclosure: `asyncio.run()` in `view.py` destroys FastMCP's event loop on every request. Replacing it with `asgiref.sync.async_to_sync` + `session_manager.run()` restores `Server.request_context` availability and in-memory session persistence. All 10 requirements map to this single phase.

**Root cause (from `docs/dev/mcp-implementation-analysis.md`):**
- `asyncio.run()` creates and destroys an event loop per request
- FastMCP's `Server.request_context` ContextVar and in-memory session dict are cleared between requests
- `MCPSessionState` written by `mcp_enable_tools` vanishes before the next request
- `Server.request_context.get()` raises `LookupError` on every production call

**Fix (source-verified from django-mcp-server):**
- `async_to_sync` reuses the current thread's event loop without destroying it
- `session_manager.run()` enters FastMCP's task group so `Server.request_context.set(ctx)` fires
- One `StreamableHTTPSessionManager` singleton, `run()` entered once per request

**Requirements:**

| ID | Requirement | File |
|---|---|---|
| REFA-01 | `view.py` replaces `asyncio.run()` with `asgiref.sync.async_to_sync(_call_starlette_handler)(request, session_manager)` — session state now persists across requests | `mcp/view.py` |
| REFA-02 | `view.py` calls `async with session_manager.run():` inside `_call_starlette_handler` before `handle_request()` — `Server.request_context.get()` works in all tool handlers | `mcp/view.py` |
| REFA-03 | `view.py` ASGI scope dict built from Django request with all fields: `server` from `request.get_host()`/`get_port()`, `scheme` from `request.is_secure()`, `client` from `request.META`, `Content-Length` from headers, `path`, `query_string`, `headers`, `method`, `http_version` | `mcp/view.py` |
| REFA-04 | `server.py` exposes `get_session_manager()` returning the `StreamableHTTPSessionManager` singleton alongside `get_mcp_app()` | `mcp/server.py` |
| REFA-05 | `server.py` adds `threading.Lock` double-checked locking around `_mcp_app` initialization — prevents duplicate FastMCP instances under concurrent Django workers | `mcp/server.py` |
| AUTH-01 | `auth.py` caches Nautobot user object on MCP session dict via `ctx.request_context.session["cached_user"]` — avoids DB lookup on every tool call within a batch MCP request | `mcp/auth.py` |
| AUTH-02 | Cache key is the token key; cache hit skips DB query; cache miss falls through to existing `Token.objects.select_related("user").get()` lookup | `mcp/auth.py` |
| TEST-01 | All existing unit tests pass after refactor (`poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests`) | — |
| TEST-02 | Integration test sends two sequential MCP HTTP requests with `Mcp-Session-Id` header; verifies `mcp_list_tools` response on the second request reflects scopes enabled in the first (session persistence UAT) | `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` |
| TEST-03 | UAT smoke tests pass (`docker exec ... python /source/scripts/run_mcp_uat.py`) | — |

**Success Criteria:**

1. `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` passes — all existing unit tests green after refactor
2. Two sequential MCP HTTP POST requests sharing `Mcp-Session-Id` header: first enables a scope via `mcp_enable_tools`, second's `mcp_list_tools` response includes tools from that scope (session persistence verified)
3. `Server.request_context.get()` succeeds inside `device_list` tool handler (no LookupError)
4. `server.py` `get_session_manager()` returns the same singleton object across multiple calls
5. Two concurrent first requests to `get_mcp_app()` produce one FastMCP instance (double-checked locking verified)
6. `ctx.request_context.session["cached_user"]` is populated after first auth call; second call within same request batch hits cache (verified via mock/assertion)
7. UAT smoke test `scripts/run_mcp_uat.py` passes end-to-end

**Known pitfalls to avoid (from research/SUMMARY.md):**
- `session_manager.run()` raises `RuntimeError` if entered twice on the same instance — one singleton, one `run()` per request
- Starlette lifespan must wrap `session_manager.run()` — never call `http_app()` directly as a plain callable
- `asgiref.sync.async_to_sync` must wrap an async callable (`_call_starlette_handler`)

**Patterns sourced from django-mcp-server:**
- `mcp_server/djangomcp.py`: `_call_starlette_handler`, `DjangoMCP.handle_django_request`, `StreamableHTTPSessionManager` property
- `mcp_server/views.py`: `MCPServerStreamableHttpView`, DRF APIView, `@csrf_exempt`
- `mcp/server/streamable_http_manager.py`: `StreamableHTTPSessionManager.__init__`, `run()`, `handle_request()`, `_has_started` guard
- `asgiref/sync.py`: `AsyncToSync.__call__` — ThreadPoolExecutor + loop reuse

---

## Requirements Traceability

### Phase 0 — Project Setup

| Req ID | Requirement | Status |
|---|---|---|
| FOUND-01 | Add `mcp`, `fastmcp`, `asgiref` dependencies to `pyproject.toml` | **Completed** |
| FOUND-03 | Use `nautobot_app_mcp_server` everywhere (not `nautobot_mcp_server`) | **Completed** |
| FOUND-04 | Use `nautobot-app-mcp-server` as `base_url` | **Completed** |
| TEST-05 | Coverage threshold `fail_under = 50` in `pyproject.toml` | **Completed** |

### Phase 1 — MCP Server Infrastructure

| Req ID | Requirement | Status |
|---|---|---|
| FOUND-02 | Create `nautobot_app_mcp_server/mcp/` package structure | **Completed** |
| FOUND-05 | Implement ASGI bridge via `asgiref.wsgi.WsgiToAsgi` | **Completed** |
| SRVR-01 | FastMCP instance with `stateless_http=False`, `json_response=True` | **Completed** |
| SRVR-02 | `get_mcp_app()` lazy factory — not created at import time | **Completed** |
| SRVR-03 | `streamable_http_app()` mounted at `/plugins/nautobot-app-mcp-server/mcp/` | **Completed** |
| SRVR-04 | ASGI bridge view (`WsgiToAsgi`) | **Completed** |
| SRVR-05 | `urls.py` with `path("mcp/", mcp_view)` auto-discovered by Nautobot | **Completed** |
| SRVR-06 | `post_migrate` signal wiring for tool registration | **Completed** |
| REGI-01 | `MCPToolRegistry` thread-safe singleton with `threading.Lock` | **Completed** |
| REGI-02 | `ToolDefinition` dataclass | **Completed** |
| REGI-03 | `register_mcp_tool()` public API | **Completed** |
| REGI-04 | `get_core_tools()`, `get_by_scope()`, `fuzzy_search()` registry methods | **Completed** |
| TEST-03 | `test_view.py` — ASGI bridge, HTTP round-trip, endpoint reachability | **Completed** |
| TEST-04 | `test_signal_integration.py` — `post_migrate` timing | **Completed** |

**Executed:** 2026-04-01, commit `13ca60e`

### Phase 2 — Authentication & Sessions

| Req ID | Requirement | Status |
|---|---|---|
| REGI-05 | `@mcp.list_tools()` override for progressive disclosure | **Completed** |
| AUTH-01 | `get_user_from_request()` from MCP request context `Authorization: Token` | **Completed** |
| AUTH-02 | `AnonymousUser` returns empty queryset + debug warning | **Completed** |
| AUTH-03 | `.restrict(user, action="view")` on every queryset | **Completed** |
| SESS-01 | `MCPSessionState` dataclass with `enabled_scopes` and `enabled_searches` | **Completed** |
| SESS-02 | Session state stored per `Mcp-Session-Id` via FastMCP session manager | **Completed** |
| SESS-03 | `mcp_enable_tools(scope=...)` tool | **Completed** |
| SESS-04 | `mcp_disable_tools(scope=...)` tool | **Completed** |
| SESS-05 | `mcp_list_tools()` tool | **Completed** |
| SESS-06 | Core tools always enabled regardless of session state | **Completed** |
| TEST-06 | Auth test: valid token → data, invalid → empty + warning | **Completed** |

**Executed:** 2026-04-01, commits `c8469cb`→`750878f`

### Phase 3 — Core Read Tools

| Req ID | Requirement | Status |
|---|---|---|
| TOOL-01 | `device_list` | **Completed** |
| TOOL-02 | `device_get` | **Completed** |
| TOOL-03 | `interface_list` | **Completed** |
| TOOL-04 | `interface_get` | **Completed** |
| TOOL-05 | `ipaddress_list` | **Completed** |
| TOOL-06 | `ipaddress_get` | **Completed** |
| TOOL-07 | `prefix_list` | **Completed** |
| TOOL-08 | `vlan_list` | **Completed** |
| TOOL-09 | `location_list` | **Completed** |
| TOOL-10 | `search_by_name` | **Completed** |
| PAGE-01 | `paginate_queryset(qs, limit, cursor)` with `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000` | **Completed** |
| PAGE-02 | `LIMIT_SUMMARIZE=100` — count BEFORE slicing, auto-summarize | **Completed** |
| PAGE-03 | `PaginatedResult` dataclass | **Completed** |
| PAGE-04 | Cursor encoding as `base64(str(pk))` | **Completed** |
| PAGE-05 | `sync_to_async(fn, thread_sensitive=True)` for all ORM calls | **Completed** |
| TEST-02 | `test_core_tools.py` — ORM mocking, pagination, auth | **Completed** |

**Executed:** 2026-04-02 (Plans 01+02+03), commits (5b3dca1→0341f98→373c770→...)

### Phase 4 — SKILL.md Package

| Req ID | Requirement | Status |
|---|---|---|
| SKILL-01 | `nautobot-mcp-skill/` pip package | **Completed** |
| SKILL-02 | SKILL.md with tools table, scope docs, pagination docs | **Completed** |
| SKILL-03 | SKILL.md with investigation workflows | **Completed** |

**Executed:** 2026-04-02

### Phase 5 — MCP Server Refactor

| Req ID | Requirement | Status |
|---|---|---|
| REFA-01 | `view.py`: replace `asyncio.run()` with `async_to_sync(_call_starlette_handler)` | **Completed** (WAVE2-VIEW, 21e2f6d) |
| REFA-02 | `view.py`: `async with session_manager.run():` before `handle_request()` | **Completed** (WAVE2-VIEW, 21e2f6d) |
| REFA-03 | `view.py`: ASGI scope dict built from Django request (server, scheme, client, path, query_string, headers, method, http_version) | **Completed** (WAVE2-VIEW, 21e2f6d) |
| REFA-04 | `server.py`: `get_session_manager()` returning `StreamableHTTPSessionManager` singleton | **Completed** (WAVE1-SERVER, 5010d32) |
| REFA-05 | `server.py`: `threading.Lock` double-checked locking on `_mcp_app` | **Completed** (WAVE1-SERVER, 5010d32) |
| AUTH-01 | `auth.py`: `ctx.request_context._cached_user` caching (D-13, D-14) | **Completed** (WAVE1-AUTH, 52c235c) |
| AUTH-02 | `auth.py`: token key cache; hit skips DB query, miss falls through | **Completed** (WAVE1-AUTH, 52c235c) |
| SESS-fix | `session_tools.py`: `_get_tool_state()` replaces `ctx.request_context.session` (ServerSession has no dict interface — latent bug) | **Completed** (WAVE1-SESSION, a5a11f2) |
| TEST-01 | All existing unit tests pass after refactor | **Completed** (WAVE2-TEST-SESSION, 18c1148) |
| TEST-02 | Integration test: two sequential MCP requests with `Mcp-Session-Id`; second `mcp_list_tools` reflects scopes enabled in first | **Completed** (WAVE2-TEST-INTEGRATION, a9f9d63) |
| TEST-03 | UAT smoke tests pass | Pending |

**Coverage:** 11 v1.1.0 requirements mapped to Phase 5 (10 from roadmap + SESS-fix latent bug). 100% traceability.

---

## Phase Exit Gates

| Phase | Gate | Verification Command |
|---|---|---|
| Phase 0 | All 3 deps resolve; `base_url` and package name correct | `poetry lock && poetry install` |
| Phase 1 | MCP endpoint returns valid JSON-RPC; registry tests green | `poetry run invoke tests` |
| Phase 2 | Auth tests pass; session tools respond correctly | `poetry run invoke tests` |
| Phase 3 | All 10 core + 3 meta tools return `PaginatedResult`; coverage ≥ 50% | `poetry run invoke coverage` |
| Phase 4 | `pip install nautobot-mcp-skill` succeeds; SKILL.md complete | `pip install ./nautobot-mcp-skill` |
| Phase 5 | All unit tests pass; session persistence integration test passes; UAT smoke tests pass | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` |

---

## Quick Reference

**MCP Endpoint:** `GET/POST /plugins/nautobot-app-mcp-server/mcp/`

**Package name:** `nautobot_app_mcp_server`

**Stack (resolved):**
- `mcp ^1.26.0` — official Anthropic MCP SDK
- `fastmcp ^3.2.0` — Prefect's FastMCP framework
- `asgiref ^3.11.1` — ASGI bridge (`WsgiToAsgi` + `async_to_sync`)
- No `django-starlette` (does not exist on PyPI)
- No `channels` or `uvicorn` (not needed for Option A)

**Architecture:** Option A — FastMCP ASGI app embedded in Django via `plugin_patterns` + `asgiref.wsgi.WsgiToAsgi`

**Phase 5 critical fix:**
- Replace `asyncio.run()` → `asgiref.sync.async_to_sync(_call_starlette_handler)` in `view.py`
- Add `async with session_manager.run():` inside `_call_starlette_handler`
- Add `get_session_manager()` + double-checked locking in `server.py`
- Add `ctx.request_context.session["cached_user"]` caching in `auth.py`

**Pagination:** Cursor-based, `base64(str(pk))` cursor, `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`, `LIMIT_SUMMARIZE=100`

**Auth:** Token from MCP request context `Authorization: Token nbapikey_xxx`; `.restrict(user, action="view")` on all querysets; user cached on MCP session dict

**Session:** In-memory per `Mcp-Session-Id`; 3 scope tiers (core, dcim, ipam); core tools always enabled

---

*Roadmap defined: 2026-04-01*
*Phase 5 added: 2026-04-03*
*Derived from: REQUIREMENTS.md (57 requirements), research/SUMMARY.md, config.json*
