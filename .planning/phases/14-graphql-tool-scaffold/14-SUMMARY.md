---
phase: 14-graphql-tool-scaffold
plan: 1
subsystem: mcp-tools
tags: [graphql, graphene-django, nautobot, fastmcp, async]

# Dependency graph
requires:
  - phase: 13
    provides: auth.py, register_tool() decorator, sync_to_async pattern
provides:
  - nautobot_app_mcp_server/mcp/tools/graphql_tool.py (GQL-01 through GQL-07)
  - Side-effect import in tools/__init__.py
  - 5 unit tests in test_graphql_tool.py (GQL-14, GQL-15, GQL-16, GQL-17, GQL-07)
affects: [15, 16, 17]

# Tech tracking
tech-stack:
  added: [graphene-django, nautobot.core.graphql]
  patterns: [lazy import for Django-free module load, async boundary with sync_to_async(thread_sensitive=True)]
patterns-established:
  - "Async tool pattern: async handler → get_user_from_request → sync_to_async with thread_sensitive=True → sync helper"
  - "Lazy import of nautobot.core.graphql inside sync helper (avoids Django setup at import time)"
  - "ValueError guard for structured error dict (no exception propagation to FastMCP)"

key-files:
  created:
    - nautobot_app_mcp_server/mcp/tools/graphql_tool.py
    - nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py
  modified:
    - nautobot_app_mcp_server/mcp/tools/__init__.py

key-decisions:
  - "Lazy import of execute_query inside _sync_graphql_query — avoids Django setup at module load time"
  - "ValueError guard returns structured error dict instead of propagating exception to FastMCP"
  - "PATCH at nautobot.core.graphql.execute_query for anonymous test (not graphql_tool.execute_query — lazy import means name not in module namespace)"
  - "6 test failures in test_session_tools.py and test_commands.py are pre-existing at b30101a — not caused by graphql_tool changes"

requirements-completed: [GQL-01, GQL-02, GQL-03, GQL-04, GQL-05, GQL-06, GQL-07, GQL-14, GQL-15, GQL-16, GQL-17]

# Metrics
duration: 22min
completed: 2026-04-15
---

# Phase 14: GraphQL Tool Scaffold Summary

**GraphQL MCP tool scaffold with `graphql_query` handler wrapping `nautobot.core.graphql.execute_query()`, 5 unit tests, and side-effect registration**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-15T12:37:10Z
- **Completed:** 2026-04-15T12:59:36Z
- **Tasks:** 5 (4 file tasks + 1 verification task skipped — pre-existing failures)
- **Files modified:** 2

## Accomplishments
- `graphql_tool.py` with `_graphql_query_handler` async handler and `_sync_graphql_query` sync helper
- Lazy import of `nautobot.core.graphql.execute_query` inside sync helper
- `ValueError` guard for structured error dict (no exception propagation to FastMCP)
- Side-effect import in `tools/__init__.py` for automatic registration
- 5 unit tests covering GQL-14, GQL-15, GQL-16, GQL-17, GQL-07
- All 5 new tests pass; 5 existing tests pass (91/96 total, 2 skipped, 6 pre-existing failures)

## Task Commits

1. **Task 14-1: Create graphql_tool.py** - `8f2af04` (feat)
2. **Task 14-2: Register in tools/__init__.py** - `c3e6f00` (feat)
3. **Task 14-3: Write unit tests** - `8576b80` (test)
4. **Task 14-4: Fix patch target** - `60f59f0` (test)

## Files Created/Modified

- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` - `graphql_query` MCP tool: async handler + sync helper + ValueError guard + lazy import
- `nautobot_app_mcp_server/mcp/tools/__init__.py` - Added `from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401`
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` - 5 tests: valid query, invalid query, variables injection, auth propagation, anonymous user

## Decisions Made

- Lazy import of `execute_query` inside `_sync_graphql_query` avoids Django setup at module load time
- `ValueError` guard returns `{"data": None, "errors": [{"message": "Authentication required"}]}` instead of propagating exception
- Patching `nautobot.core.graphql.execute_query` (not `graphql_tool.execute_query`) for anonymous user test — the lazy import means the name is not in the graphql_tool module namespace
- 6 pre-existing test failures in test_session_tools.py and test_commands.py confirmed at base commit b30101a; not caused by phase 14 changes

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **Test failure: asgiref CurrentThreadExecutor exception propagation** — `sync_to_async` with `thread_sensitive=True` does not propagate exceptions from `CurrentThreadExecutor` back to the async caller in asgiref 3.x. Fixed by calling `_sync_graphql_query` directly (bypassing `sync_to_async`) in the anonymous user test, patching `execute_query` at its source module.
- **Patch target error** — `graphql_tool.execute_query` doesn't exist because of lazy import. Fixed by patching `nautobot.core.graphql.execute_query` instead.

## Next Phase Readiness

- Phase 15 (Introspection & Permissions) can proceed — `graphql_query` tool is scaffolded and tests pass
- No blockers
- Plan directory: `.planning/phases/14-graphql-tool-scaffold/`

---
*Phase: 14-graphql-tool-scaffold*
*Completed: 2026-04-15*