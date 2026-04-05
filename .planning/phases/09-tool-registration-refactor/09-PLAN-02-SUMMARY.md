---
phase: 09-tool-registration-refactor
plan: 02
subsystem: mcp
tags: [fastmcp, registry, tool-registration]

# Dependency graph
requires:
  - phase: 09-01
    provides: "@register_tool decorator, MCPToolRegistry singleton, func_signature_to_input_schema"
provides:
  - "register_all_tools_with_mcp(mcp) wires all registry tools to FastMCP at startup"
  - "create_app() now fully wires the MCP server — both prod and dev entrypoints benefit"
affects:
  - phase: 10-session-state
  - phase: 11-auth-refactor
  - phase: 12-bridge-cleanup

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Side-effect import pattern: import mcp.tools.core → @register_tool decorators fire → tools registered in MCPToolRegistry"
    - "register_all_tools_with_mcp() bridges in-memory registry to FastMCP live instance"

key-files:
  created: []
  modified:
    - nautobot_app_mcp_server/mcp/__init__.py
    - nautobot_app_mcp_server/mcp/commands.py

key-decisions:
  - "mcp.tool() is called with kwargs (name=, description=) not positional — FastMCP 3.x API"
  - "input_schema NOT passed to mcp.tool() — FastMCP 3.x auto-derives from function type hints"

patterns-established:
  - "Pattern: startup_wiring() → import side-effects → register_all_tools_with_mcp()"
  - "Pattern: two-phase wiring (STEP 3 create FastMCP, STEP 4 wire tools)"

requirements-completed:
  - ["09-01: @register_tool decorator and MCPToolRegistry singleton"]
  - ["09-01: register_mcp_tool() public API"]
  - ["09-02: register_all_tools_with_mcp() wires all registered tools to FastMCP instance"]
  - ["09-02: create_app() calls register_all_tools_with_mcp() inside STEP 4"]

# Metrics
duration: 10min
completed: 2026-04-05
---

# Phase 09 Plan 2: `register_all_tools_with_mcp()` Summary

**`register_all_tools_with_mcp(mcp)` wires all MCPToolRegistry tools to FastMCP at startup — completing the create_app() wiring**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-05
- **Completed:** 2026-04-05
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `register_all_tools_with_mcp(mcp)` added to `mcp/__init__.py` — iterates `MCPToolRegistry.get_all()` and calls `mcp.tool(func, name=tool.name, description=tool.description)` for each registered tool
- `__all__` in `mcp/__init__.py` updated to export `register_all_tools_with_mcp`
- `mcp/commands.py` STEP 4 replaced placeholder with real wiring — import `nautobot_app_mcp_server.mcp.tools.core` (side-effect registration) then call `register_all_tools_with_mcp(mcp)`
- Both `start_mcp_server` and `start_mcp_dev_server` benefit automatically (both call `create_app()`)

## Task Commits

Each task was committed atomically:

1. **Task 1 & 2 combined (feat):** `17817a3` — `feat: add register_all_tools_with_mcp() and wire it into create_app()`

**Plan metadata:** `17817a3` (feat: add register_all_tools_with_mcp() and wire it into create_app())

## Files Created/Modified
- `nautobot_app_mcp_server/mcp/__init__.py` — added `register_all_tools_with_mcp()` + `__all__` update
- `nautobot_app_mcp_server/mcp/commands.py` — replaced STEP 4 placeholder with real wiring

## Decisions Made
- Did NOT pass `input_schema` to `mcp.tool()` — FastMCP 3.x auto-derives schema from Python type hints
- Used `mcp.tool(func, name=..., description=...)` kwargs syntax — FastMCP 3.x decorator-style API
- Side-effect import of `mcp.tools.core` chosen over lazy registration — consistent with Phase 09 architecture

## Deviations from Plan
None — plan executed exactly as written.

## Issues Encountered
- **Pre-existing test failure:** `test_on_post_migrate_only_runs_for_this_app` in `test_signal_integration.py` was failing before our changes (confirmed by stashing and running tests in isolation). `NautobotAppMcpServerConfig._on_post_migrate` AttributeError — unrelated to plan 09-02. 79/80 MCP tests pass.

## Next Phase Readiness
- Phase 09-03 ready to execute — plan exists at `09-PLAN-03.md`
- MCPToolRegistry wiring is complete, ready for session state and progressive disclosure

---
*Phase: 09-tool-registration-refactor | Plan: 02*
*Completed: 2026-04-05*
