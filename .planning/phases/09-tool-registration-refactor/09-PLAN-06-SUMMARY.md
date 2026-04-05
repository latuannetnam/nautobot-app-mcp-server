---
phase: 09-tool-registration-refactor
plan: 06
subsystem: testing
tags: [pytest, django-testcase, mcp, decorator, registry]

# Dependency graph
requires:
  - phase: 09-01
    provides: "@register_tool decorator, func_signature_to_input_schema(), MCPToolRegistry singleton"
  - phase: 09-02
    provides: "register_all_tools_with_mcp() wiring function"
provides:
  - Unit tests for func_signature_to_input_schema() (3 tests)
  - Unit tests for @register_tool decorator (5 tests)
  - Unit tests for register_all_tools_with_mcp() (3 tests)
affects:
  - Phase 09 (exit gate verification)
  - Phase 10 (session state tests)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Django TestCase with setUp() singleton reset for isolation"
    - "Mock assertions on mcp.tool() call_args_list"
    - "pytest-free test suite (no pytest dependency in project)"

key-files:
  created:
    - nautobot_app_mcp_server/mcp/tests/test_register_tool.py
  modified:
    - (none)

key-decisions:
  - "Used Django TestCase instead of pytest — project uses django.test.TestCase exclusively"
  - "setUp() resets MCPToolRegistry._instance and MCPToolRegistry._tools for test isolation"
  - "The unused _FakeToolDefinition helper class is preserved for documentation clarity"
  - "pylint astroid crash on test file is an environment bug (astroid 2.15.8 vs 3.x) — not a code issue"

patterns-established:
  - "Singleton reset pattern: MCPToolRegistry._instance = None; MCPToolRegistry._tools = {} in setUp()"
  - "mock_mcp.tool.assert_not_called() for empty-registry noop test"
  - "call.kwargs.get('name') for extracting positional-decorator tool name"

requirements-completed: []

# Metrics
duration: ~7min
completed: 2026-04-05
---

# Phase 09 Plan 06: Unit Tests for `@register_tool` and `register_all_tools_with_mcp()` Summary

**11 unit tests covering func_signature_to_input_schema, @register_tool decorator, and register_all_tools_with_mcp() wiring — all passing**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-04-05T12:00:00Z
- **Completed:** 2026-04-05T12:07:00Z
- **Tasks:** 1 (1 task with 3 sub-categories)
- **Files modified:** 1 new file (249 lines)

## Accomplishments
- Created `test_register_tool.py` with 11 unit tests covering the full `register_tool`/`register_all_tools_with_mcp()` surface area
- 3 tests for `func_signature_to_input_schema()`: simple params, required params, ctx exclusion
- 5 tests for `@register_tool` decorator: registry registration, auto-schema, explicit schema override, explicit name, duplicate detection
- 3 tests for `register_all_tools_with_mcp()`: tool wiring, empty registry noop, no input_schema passed
- All 91 MCP tests pass (1 pre-existing failure in `test_signal_integration.py` unrelated to this plan)
- ruff clean: sorted isort groups, removed unused `patch` import

## Task Commits

Each task was committed atomically:

1. **Task 1: Unit tests for @register_tool and register_all_tools_with_mcp()** - `a1ebef2` (test)

**Plan metadata:** `a1ebef2` (amended to include ruff fix)

## Files Created/Modified

- `nautobot_app_mcp_server/mcp/tests/test_register_tool.py` - 11 Django TestCase tests (249 lines); covers func_signature_to_input_schema, @register_tool decorator, register_all_tools_with_mcp()

## Decisions Made

- **Used `django.test.TestCase` instead of pytest**: Project convention (no pytest dependency). The plan specified `import pytest` but the project's `test_core_tools.py` uses `from django.test import TestCase` exclusively. Adapted accordingly.
- **`setUp()` singleton reset**: `MCPToolRegistry._instance = None` + `MCPToolRegistry._tools = {}` in each test class's `setUp()` for isolation.
- **Unused `_FakeToolDefinition` class**: Kept for documentation clarity even though it's not referenced in tests (matches plan template).

## Deviations from Plan

[None — plan executed with minor adaptation: pytest → Django TestCase]

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest not in project dependencies**
- **Found during:** Task 1 (test file creation)
- **Issue:** Plan specified `import pytest` and `pytest.raises()` — pytest is not in the project dependencies
- **Fix:** Rewrote all 11 tests to use `django.test.TestCase` with `self.assertRaises()` instead of `pytest.raises()`; used `setUp()` for singleton reset instead of pytest fixtures
- **Files modified:** nautobot_app_mcp_server/mcp/tests/test_register_tool.py
- **Verification:** `nautobot-server test nautobot_app_mcp_server.mcp.tests.test_register_tool --keepdb --noinput` → 11 tests OK
- **Committed in:** `a1ebef2`

**2. [Rule 3 - Blocking] ruff I001 import block un-sorted**
- **Found during:** Task 1 (post-commit lint check)
- **Issue:** `from __future__ import annotations` not separated into its own isort group
- **Fix:** ruff `--fix` auto-fixed the isort grouping
- **Files modified:** nautobot_app_mcp_server/mcp/tests/test_register_tool.py
- **Verification:** `ruff check test_register_tool.py` → All checks passed!
- **Committed in:** `a1ebef2` (amended)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes were necessary for tests to run at all. No scope creep.

## Issues Encountered

- **pylint F0002 crash on test file**: `astroid 2.15.8` lacks `visit_typealias` (added in astroid 3.x). `test_core_tools.py` doesn't trigger the crash because it doesn't use Python 3.12 `type` syntax at module level. The test file is correct — the environment is outdated. Not fixed as part of this plan (would require upgrading pylint/astroid across the Docker image). Documented in key-decisions.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 09-06 complete — 11 unit tests for tool registration layer written and passing
- Phase 09 exit gate: 91 MCP tests pass (1 pre-existing failure in `test_signal_integration.py` unrelated to Phase 09)
- Ready for plan 09-07 (if any) or next phase in the roadmap

---
*Phase: 09-tool-registration-refactor*
*Completed: 2026-04-05*
