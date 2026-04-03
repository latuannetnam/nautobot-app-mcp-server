---
phase: 05-mcp-server-refactor
plan: wave2
subsystem: infra
tags: [fastmcp, django, asyncio, async_to_sync, session, asgi]

# Dependency graph
requires:
  - phase: 05-mcp-server-refactor/wave1
    provides: get_session_manager() returning StreamableHTTPSessionManager singleton
provides:
  - ASGI bridge: asyncio.run() replaced with async_to_sync + session_manager.run()
  - Server.request_context available inside tool handlers (REFA-02)
  - Full ASGI scope derived from Django request (REFA-03)
  - Django request accessible in async tool calls via _django_request_ctx ContextVar
affects:
  - Phase 05/WAVE2-TEST-VIEW
  - Phase 05/WAVE2-UPDATE-DOCS
  - Phase 05/TEST-02 session persistence integration test

# Tech tracking
tech-stack:
  added: [contextvars.ContextVar]
  patterns: [WSGI→ASGI bridge via async_to_sync, session_manager.run() context manager, ASGI scope from Django request]

key-files:
  created: []
  modified:
    - nautobot_app_mcp_server/mcp/view.py

key-decisions:
  - "Used asgiref.sync.async_to_sync instead of asyncio.run — keeps FastMCP event loop alive across requests"
  - "Called get_session_manager() (not get_mcp_app()) to get StreamableHTTPSessionManager"
  - "Entered session_manager.run() inside _call_starlette_handler before handle_request()"
  - "Used ValueError instead of assert for path validation (S101 ruff rule)"
  - "Changed test assertion from 'asyncio.run' substring to 'import asyncio' to avoid docstring false-positive"

patterns-established:
  - "WSGI→ASGI bridge pattern: async_to_sync(_call_starlette_handler)(request, session_manager)"
  - "FastMCP session context: async with session_manager.run()"
  - "ASGI scope from Django: server/get_host/get_port, scheme/is_secure, client/REMOTE_ADDR"

requirements-completed:
  - REFA-01
  - REFA-02
  - REFA-03

# Metrics
duration: 5min
completed: 2026-04-03
---

# Phase 5 Wave 2: ASGI Bridge Refactor Summary

**async_to_sync WSGI→ASGI bridge with session_manager.run() — FastMCP event loop now persists across requests, fixing session state and Server.request_context access (P0 fix)**

## Performance

- **Duration:** ~5 min (implementation + test fix)
- **Started:** 2026-04-03T18:45:00Z
- **Completed:** 2026-04-03T19:00:00Z
- **Tasks:** 2 (WAVE2-VIEW + test fix)
- **Files modified:** 2 (`mcp/view.py`, `mcp/tests/test_view.py`)

## Accomplishments

- Replaced `asyncio.run()` bridge with `asgiref.sync.async_to_sync(_call_starlette_handler)(request, session_manager)` — event loop no longer destroyed per request
- Entered `session_manager.run()` inside async handler — FastMCP's `Server.request_context` is now set, `Server.request_context.get()` works inside tool handlers
- Built full ASGI scope from Django request — `server`, `scheme`, `client` derived from `request`, not hardcoded
- Stored Django `HttpRequest` in `_django_request_ctx: ContextVar` for tool access
- Fixed test assertion: checked `"import asyncio"` (not substring `"asyncio.run"`) to avoid false-positive from docstring

## Task Commits

Each task was committed atomically:

1. **WAVE2-VIEW: Replace asyncio.run() bridge** - `21e2f6d` (feat/fix/refactor)
2. **Test fix: assert import asyncio not substring match** - `67cdef5` (fix)

**Plan metadata:** `PLAN-WAVE2.md` (docs: complete plan)

## Files Created/Modified

- `nautobot_app_mcp_server/mcp/view.py` - Complete rewrite: async_to_sync bridge, session_manager.run(), full ASGI scope, ContextVar for Django request
- `nautobot_app_mcp_server/mcp/tests/test_view.py` - Updated tests for new pattern + fixed assertion for "import asyncio"

## Decisions Made

- Used `asgiref.sync.async_to_sync` over `asyncio.run` — keeps FastMCP event loop alive, session state persists
- Called `get_session_manager()` (from WAVE1-SERVER) instead of `get_mcp_app()` — session manager is the correct bridge entry point
- Entered `session_manager.run()` inside `_call_starlette_handler` (async) wrapped by `async_to_sync` — pattern matches django-mcp-server exactly
- Used `ValueError` (not `assert`) for path validation — satisfies S101 ruff rule
- Changed `assertNotIn("asyncio.run")` to `assertNotIn("import asyncio")` in test — old check matched docstring `"NOT asyncio.run"` substring

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - S101] Replaced assert with if/raise ValueError**
- **Found during:** WAVE2-VIEW implementation
- **Issue:** Plan used `assert` for path validation; ruff S101 flags `assert` usage
- **Fix:** Replaced with `if not ...: raise ValueError(msg)` pattern
- **Files modified:** `nautobot_app_mcp_server/mcp/view.py`
- **Verification:** `ruff check view.py` passes with no S101 errors
- **Committed in:** `21e2f6d` (WAVE2-VIEW commit)

**2. [Rule 1 - False-positive test] Changed substring assertion to import check**
- **Found during:** WAVE2-VIEW test execution (67cdef5)
- **Issue:** `assertNotIn("asyncio.run")` matched docstring `"NOT asyncio.run"` causing test failure
- **Fix:** Changed to `assertNotIn("import asyncio")` — checks for the actual broken import pattern
- **Files modified:** `nautobot_app_mcp_server/mcp/tests/test_view.py`
- **Verification:** `nautobot-server test test_view` — 9 tests, all pass
- **Committed in:** `67cdef5` (test fix commit)

---

**Total deviations:** 2 auto-fixed (1 linter rule, 1 false-positive test assertion)
**Impact on plan:** Both auto-fixes are necessary for correctness and test reliability. No scope creep.

## Issues Encountered

- Test database `test_nautobot` locked by orphaned worker connection — resolved by killing connections via db container (`psql`) and recreating fresh DB
- Pylint 10.00/10 blocked by astroid crash on Python 3.12 type aliases — verified with `ruff` (all checks pass) and tests (all pass)
- Parallel agent committed WAVE2-VIEW (21e2f6d) with docstring containing `"NOT asyncio.run"` which caused test to fail — fixed in `67cdef5`

## Next Phase Readiness

- REFA-01, REFA-02, REFA-03 complete — ASGI bridge fully refactored
- Phase 5 remaining: TEST-02 (session persistence integration test), TEST-03 (UAT smoke tests)
- All prerequisites satisfied: WAVE1-SERVER, WAVE1-AUTH, WAVE1-SESSION all complete

---
*Phase: 05-mcp-server-refactor/wave2*
*Completed: 2026-04-03*
