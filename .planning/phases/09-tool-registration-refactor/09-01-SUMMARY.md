---
phase: 09-tool-registration-refactor
plan: "01"
subsystem: mcp
tags: [fastmcp, decorator, schema, python-types, json-schema]

# Dependency graph
requires: []
provides:
  - func_signature_to_input_schema() for auto-deriving JSON Schema from Python type hints
  - @register_tool decorator as ergonomic alternative to register_mcp_tool()
  - All 10 core tools converted to @register_tool (no explicit input_schema needed)
affects: [Phase 09, Phase 10, Phase 11]

# Tech tracking
tech-stack:
  added: [schema.py, func_signature_to_input_schema, register_tool decorator]
  patterns: [decorator-based tool registration, auto-schema derivation from type hints]

key-files:
  created:
    - nautobot_app_mcp_server/mcp/schema.py
  modified:
    - nautobot_app_mcp_server/mcp/__init__.py
    - nautobot_app_mcp_server/mcp/tools/core.py

key-decisions:
  - "FastMCP 3.x auto-derives schema from type hints at runtime — stored schema is for registry documentation only"
  - "@register_tool decorator skips ctx parameter (injected by FastMCP), auto-detects required vs optional fields"
  - "Optional[X] and X | None both handled with default=None in generated schema"

patterns-established:
  - "Pattern: @register_tool(description=..., tier=..., scope=...) on async def — replaces register_mcp_tool() call"
  - "Pattern: input_schema omitted entirely; func_signature_to_input_schema() derives it from signature"

requirements-completed: []

# Metrics
duration: 2min
completed: 2026-04-05T11:12:00Z
---

# Phase 09 Plan 01: `@register_tool` Decorator Summary

**JSON Schema auto-generated from Python type hints via `@register_tool` decorator — all 10 core tools converted**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-05T11:09:17Z
- **Completed:** 2026-04-05T11:12:00Z
- **Tasks:** 3
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- Created `schema.py` with `func_signature_to_input_schema()` — derives JSON Schema from Python type hints, handles Optional[X], list[X], defaults
- Added `@register_tool` decorator to `mcp/__init__.py` — ergonomic wrapper around `register_mcp_tool()` with auto-schema derivation
- Converted all 10 core tools in `core.py` from `register_mcp_tool()` calls to `@register_tool` decorators — removes all explicit `input_schema` args

## Task Commits

Each task was committed atomically:

1. **Task 1: schema.py creation** - `2bdc01f` (feat)
2. **Task 2: register_tool decorator** - `e2b310d` (feat)
3. **Task 3: Convert 10 tools to @register_tool** - `38e1a87` (refactor)

**Plan metadata:** `09-01` (docs: complete plan)

## Files Created/Modified
- `nautobot_app_mcp_server/mcp/schema.py` - `func_signature_to_input_schema()` for JSON Schema auto-derivation
- `nautobot_app_mcp_server/mcp/__init__.py` - `register_tool` decorator + `func_signature_to_input_schema` import
- `nautobot_app_mcp_server/mcp/tools/core.py` - All 10 tools use `@register_tool` (net: 54 insertions, 245 deletions)

## Decisions Made
- FastMCP 3.x auto-derives schema from Python type hints at runtime — the schema in `MCPToolRegistry` is for cross-process discovery/documentation only
- `ctx` parameter (ToolContext) is always skipped in schema generation — FastMCP injects it
- Required fields inferred from parameters without defaults; optional fields include `default` value in schema
- `Optional[X]` and `X | None` both produce `{"type": ..., "default": None}`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Local Poetry venv permission error during test run — switched to Docker exec container execution
- Test DB already existed (non-empty DB state from prior runs) — resolved with `--keepdb` flag

## Next Phase Readiness
- `schema.py` and `@register_tool` available for Phase 09 remaining plans
- Phase 09 plan 02 (`register_all_tools_with_mcp()`) can proceed immediately
- All 80 MCP tests pass

---
*Phase: 09-tool-registration-refactor, Plan 01*
*Completed: 2026-04-05*
