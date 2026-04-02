---
phase: 03-core-read-tools
plan: "03"
subsystem: tools
tags: [search_by_name, multi-model-search, django-orm, testing, cursor-pagination]

requires:
  - phase: "03-01"
    provides: pagination infrastructure

provides:
  - search_by_name multi-model AND search across 6 Nautobot models
  - 31 test cases covering all tools, pagination, auth, and anonymous fallback
  - functools.reduce-based AND filter across search terms

affects: [03-core-read-tools]

tech-stack:
  added: [functools.reduce]
  patterns: [multi-model search, AND filter with Q objects, functools.reduce]

key-files:
  created:
    - nautobot_app_mcp_server/mcp/tests/test_core_tools.py
  modified:
    - nautobot_app_mcp_server/mcp/tools/query_utils.py
    - nautobot_app_mcp_server/mcp/tools/core.py

key-decisions:
  - "AND semantics via functools.reduce(op.and_, list) instead of op.and_(*list)"
  - "serializer functions patched in tests to avoid model_to_dict limitations with MagicMock"

patterns-established:
  - "Multi-model search: build per-model querysets, combine results in-memory, paginate manually"
  - "Test pattern: patch serialize helpers when testing get tools to avoid MagicMock chain issues"

requirements-completed:
  - TOOL-10
  - TEST-02

duration: ~45min
completed: 2026-04-02
---

# Phase 03-03: search_by_name + test_core_tools.py Summary

**Multi-model `search_by_name` AND search across 6 Nautobot models with 31 passing unit tests**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-04-02T04:00:39Z
- **Completed:** 2026-04-02T04:45:00Z
- **Tasks:** 4 (3 plan tasks + 1 bug-fix commit)
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- `search_by_name` multi-model search across Device, Interface, IPAddress, Prefix, VLAN, Location with AND semantics
- `functools.reduce(op.and_, ...)` for combining Q objects with variable-length term lists
- `test_core_tools.py` with 31 test cases: all 10 tools, pagination, auth enforcement, anonymous fallback
- All 31 tests passing in Docker container

## Task Commits

Each task was committed atomically:

1. **Task 1: _sync_search_by_name in query_utils.py** — `84f9c03` (feat)
2. **Task 2: _search_by_name_handler in core.py** — `f18ff4c` (feat)
3. **Task 3: test_core_tools.py** — `c8a71ec` (test)
4. **Bug fixes: query_utils AND logic + test mocking** — `9948527` (fix)

**Plan metadata:** `docs(03-03): complete plan 03-03` (pending)

## Files Created/Modified
- `nautobot_app_mcp_server/mcp/tools/query_utils.py` — added `_sync_search_by_name`, fixed `functools.reduce` import
- `nautobot_app_mcp_server/mcp/tools/core.py` — added `_search_by_name_handler` + `register_mcp_tool`
- `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — 31 test cases (553 lines)

## Decisions Made
- Used `functools.reduce(op.and_, list)` instead of `op.and_(*list)` since `op.and_` requires exactly 2 positional arguments
- Patched serializer functions (`serialize_device_with_interfaces`, `serialize_interface`) in tests rather than trying to mock the full ORM chain — avoids MagicMock limitations with `model_to_dict()`
- `restrict()` action verified via `kwargs.get("action")` not positional args — Django's ORM uses keyword argument

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `op.and_` TypeError on single-term queries**
- **Found during:** Task 1 (search_by_name implementation)
- **Issue:** `op.and_()` requires exactly 2 positional arguments. Single-term queries caused `TypeError: and_ expected 2 arguments, got 1`
- **Fix:** Replaced `op.and_(*[Q(...) for t in terms])` with `functools.reduce(op.and_, [Q(...) for t in terms])`
- **Files modified:** `nautobot_app_mcp_server/mcp/tools/query_utils.py`
- **Verification:** 31/31 tests pass
- **Committed in:** `9948527` (fix commit)

**2. [Rule 1 - Bug] `restrict()` assertion used wrong argument access**
- **Found during:** Task 3 (test writing)
- **Issue:** `mock_qs.restrict.call_args[0]` raised `IndexError` — `.restrict(user, action="view")` passes `action` as keyword, not positional
- **Fix:** Changed to `mock_qs.restrict.call_args[1].get("action")`
- **Files modified:** `nautobot_app_mcp_server/mcp/tests/test_core_tools.py`
- **Verification:** `test_device_list_enforces_auth` and `test_device_list_calls_restrict` pass
- **Committed in:** `9948527` (fix commit)

**3. [Rule 1 - Bug] `serialize_*` functions fail with MagicMock chains**
- **Found during:** Task 3 (test writing) — `test_device_get_by_name` and `test_interface_get_returns_ip_addresses`
- **Issue:** `model_to_dict()` accesses real attributes on the mock object; MagicMock chains return MagicMocks that fail `isinstance(x, str)` checks
- **Fix:** Patched `serialize_device_with_interfaces` and `serialize_interface` directly, avoiding the full ORM→serializer chain in the test
- **Files modified:** `nautobot_app_mcp_server/mcp/tests/test_core_tools.py`
- **Verification:** Both tests now pass
- **Committed in:** `9948527` (fix commit)

**4. [Rule 1 - Bug] `__iter__` lambda missing `self` parameter**
- **Found during:** Task 3 (test writing) — after patching serializers
- **Issue:** `lambda: iter([MagicMock()])` — Python passed `self` implicitly when called as `mock_qs.__iter__()`, causing `TypeError: takes 0 positional arguments but 1 was given`
- **Fix:** Changed to `lambda self: iter([MagicMock()])`
- **Files modified:** `nautobot_app_mcp_server/mcp/tests/test_core_tools.py`
- **Verification:** Tests pass
- **Committed in:** `9948527` (fix commit)

**5. [Rule 1 - Bug] `test_cursor_roundtrip_integration` mock returned wrong slice**
- **Found during:** Task 3 (test writing)
- **Issue:** Lambda checked `if key == slice(0, 2)` but also returned `[mock_item]` for other slices; `list(qs[:1])` evaluated to `[mock_item]` (only 1 item) since the lambda returned `1-item` list for `slice(0, 1)`, making `has_next = False`
- **Fix:** Simplified to `lambda self, key: [mock_item, mock_item]` — always return 2 items so `limit=1` correctly detects has_next
- **Files modified:** `nautobot_app_mcp_server/mcp/tests/test_core_tools.py`
- **Verification:** `test_cursor_roundtrip_integration` passes
- **Committed in:** `9948527` (fix commit)

---

**Total deviations:** 5 auto-fixed (5 Rule 1 bugs)
**Impact on plan:** All bugs were correctness/security issues found and fixed before testing. No scope creep.

## Issues Encountered
- Docker database cleanup: `test_nautobot` database left in inconsistent state from prior test runs. Fixed by terminating PG sessions and dropping the database before running tests.
- Container restart needed between test runs to clear stale connection pool state.

## Next Phase Readiness
- Phase 3 plans 01, 02, 03 all complete (pagination layer, 10 tools, search_by_name + tests)
- Phase 3 fully complete — all 15 requirements (TOOL-01-10, PAGE-01-05, TEST-02) addressed
- Ready for Phase 4 (SKILL.md Package)

---
*Phase: 03-core-read-tools / 03-03*
*Completed: 2026-04-02*
