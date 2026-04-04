---
wave: 0
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/server.py
  - nautobot_app_mcp_server/mcp/view.py
  - nautobot_app_mcp_server/mcp/auth.py
  - nautobot_app_mcp_server/mcp/session_tools.py
  - nautobot_app_mcp_server/mcp/tests/test_view.py
  - nautobot_app_mcp_server/mcp/tests/test_auth.py
  - nautobot_app_mcp_server/mcp/tests/test_session_tools.py
autonomous: false
---

# Phase 5 Plan: MCP Server Refactor

**Phase:** 05-mcp-server-refactor
**Wave:** 0 (plan only — execution in waves 1–2)
**Status:** Draft

---

## Overview

Fix the `asyncio.run()` WSGI→ASGI bridge in `view.py` (the P0 root cause that destroys FastMCP session state), add thread-safe singletons in `server.py`, fix auth caching in `auth.py`, and fix the session dict latent bug in `session_tools.py`. Write integration test.

**Root cause (from `docs/dev/mcp-implementation-analysis.md`):** `asyncio.run()` in `view.py:61` creates and destroys a new event loop on every request. FastMCP's `Server.request_context` ContextVar and in-memory session dict live in that loop — they are wiped between requests. Fixing this with `async_to_sync(_call_starlette_handler)` + `session_manager.run()` restores session persistence and makes `Server.request_context.get()` work inside tool handlers.

**Latent bug surfaced by research:** `MCPSessionState.from_session(session)` calls `session.get("enabled_scopes", set())` but `session` is a `ServerSession` instance (not a dict). `ServerSession` has no `get()`/`__getitem__`/`__setitem__` methods. This only "works" today because `asyncio.run()` causes `Server.request_context.get()` to raise `LookupError` before that code is reached. Phase 5 must fix both issues.

---

## Requirements Coverage

| ID | Requirement | File | Wave |
|----|-------------|------|------|
| REFA-01 | Replace `asyncio.run()` with `async_to_sync(_call_starlette_handler)(request, session_manager)` | `view.py` | 2 |
| REFA-02 | `async with session_manager.run():` before `handle_request()` | `view.py` | 2 |
| REFA-03 | ASGI scope: `server` from `request.get_host()`/`get_port()`, `scheme` from `request.is_secure()`, `client` from `request.META`, `Content-Length` from headers, `path`, `query_string`, `headers`, `method`, `http_version` | `view.py` | 2 |
| REFA-04 | `get_session_manager()` returning `StreamableHTTPSessionManager` singleton | `server.py` | 1 |
| REFA-05 | `threading.Lock` double-checked locking on `_mcp_app` initialization | `server.py` | 1 |
| AUTH-01 | Cache Nautobot user on `ctx.request_context.session["cached_user"]` | `auth.py` | 1 |
| AUTH-02 | Cache key is token key; hit skips DB, miss falls through | `auth.py` | 1 |
| TEST-01 | All existing unit tests pass after refactor | All files | 2 |
| TEST-02 | Integration test: two sequential MCP HTTP requests with `Mcp-Session-Id`; second `mcp_list_tools` reflects scopes enabled in first | `tests/test_session_persistence.py` | 2 (skipped from test runner — APPEND_SLASH env constraint) |
| TEST-03 | UAT smoke tests pass | External | 2 |

---

## Wave 1: Foundation (server.py, auth.py, session_tools.py)

**Files:** `server.py`, `auth.py`, `session_tools.py`
**Blockers:** None
**Executors:** Can run in parallel (3 separate files)

### Tasks

| # | Task ID | File | Description |
|---|---------|------|-------------|
| 1 | WAVE1-SERVER | `server.py` | Thread-safe singletons + `get_session_manager()` (REFA-04, REFA-05) |
| 2 | WAVE1-AUTH | `auth.py` | Token-key cache on `ctx.request_context.session` (AUTH-01, AUTH-02) |
| 3 | WAVE1-SESSION | `session_tools.py` | Fix `MCPSessionState` to store on `ctx.request_context` (not `ServerSession`) |

---

## Wave 2: Bridge (view.py) + Tests

**Files:** `view.py`, `tests/test_view.py`, `tests/test_session_persistence.py`, `tests/test_auth.py`
**Blockers:** Wave 1 complete (provides `get_session_manager()`)
**Executors:** `view.py` first, then tests in parallel

### Tasks

| # | Task ID | File | Description |
|---|---------|------|-------------|
| 4 | WAVE2-VIEW | `view.py` | Replace `asyncio.run()` bridge; add `async_to_sync` + `session_manager.run()` + full ASGI scope (REFA-01, REFA-02, REFA-03) |
| 5 | WAVE2-TEST-VIEW | `tests/test_view.py` | Update test that asserts `WsgiToAsgi` (now uses `async_to_sync`); add test for `get_session_manager()` |
| 6 | WAVE2-TEST-INTEGRATION | `tests/test_session_persistence.py` | Integration test: two sequential MCP HTTP POSTs, same `Mcp-Session-Id`, verify progressive disclosure (TEST-02) |
| 7 | WAVE2-TEST-AUTH | `tests/test_auth.py` | Add test: second call within same session hits cache (no DB query) |
| 8 | WAVE2-TEST-SESSION | `tests/test_session_tools.py` | Update tests to use `MCPToolSession`-compatible session dict |
| 9 | WAVE2-UAT | External | UAT smoke tests pass (`docker exec ... python /source/scripts/run_mcp_uat.py`) (TEST-03) |

---

## Verification

After all waves:
```bash
# Wave 1 verification
poetry run invoke ruff
poetry run invoke pylint

# Wave 2 verification
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests
docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py
```

---

## must_haves (Goal-Backward Verification)

1. `view.py` does not contain `asyncio.run` anywhere in the file
2. `view.py` contains `async_to_sync` and `session_manager.run()` in `_call_starlette_handler`
3. `server.py` contains `get_session_manager()` function returning `StreamableHTTPSessionManager`
4. `server.py` contains `threading.Lock` and double-checked locking around `_mcp_app`
5. `auth.py` contains `cached_user` cache logic with token key lookup
6. `session_tools.py` `MCPSessionState` stores state on `ctx.request_context` (not `ServerSession`)
7. `tests/test_session_persistence.py` exists and contains `Mcp-Session-Id` header usage
8. `tests/test_view.py` asserts `async_to_sync` usage (not `WsgiToAsgi`)
9. All 10 requirements from `REQUIREMENTS.md` are addressed by at least one task
10. `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` passes
