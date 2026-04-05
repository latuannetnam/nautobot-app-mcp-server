---
phase: "09"
plan: "03"
subsystem: tool-registration-refactor
tags:
  - plugin-ready
  - tool-registry
  - cross-process
requires:
  - "09-01"
provides:
  - tool_registry.json-generation
affects:
  - nautobot_app_mcp_server/__init__.py
tech-stack:
  added:
    - json.dump (stdlib)
  patterns:
    - plugin ready() lifecycle
    - __file__-based package dir resolution
key-files:
  created:
    - nautobot_app_mcp_server/tool_registry.json
  modified:
    - nautobot_app_mcp_server/__init__.py
key-decisions: []
requirements-completed:
  - "09-01"
duration: "<1 min"
completed: "2026-04-05"
---

# Phase 09 Plan 03: Plugin `ready()` Generates `tool_registry.json`

**One-liner:** `ready()` now exports all registered tools to `tool_registry.json` for cross-process MCP server startup discovery — `post_migrate` fully removed.

## What Was Done

Replaced the `post_migrate`-based tool registration in `NautobotAppConfig.ready()` with a direct `tool_registry.json` generation approach:

1. **Removed** `post_migrate` signal wiring and `_on_post_migrate()` static method entirely
2. **Added** import of `nautobot_app_mcp_server.mcp.tools` to trigger side-effect registration
3. **Added** `MCPToolRegistry.get_instance().get_all()` to retrieve all tool definitions
4. **Added** JSON serialization excluding `func` (not JSON-serializable), including `input_schema`
5. **Wrote** `tool_registry.json` to package directory via `os.path.dirname(__file__)` (editable-install safe)

## Why This Design

`post_migrate` never fires in the MCP server process — Phase 8 runs `django.setup()` directly, not via `nautobot-server`. The MCP server reads `tool_registry.json` at worker startup instead, enabling cross-process discovery between the Nautobot plugin process and the standalone MCP server process.

## Files Changed

| File | Change |
|------|--------|
| `nautobot_app_mcp_server/__init__.py` | Replaced `ready()` body; removed `_on_post_migrate` |
| `nautobot_app_mcp_server/tool_registry.json` | Generated (10 tools, auto-populated) |

## Verification

```bash
# ready() contains tool_registry.json generation
grep "tool_registry.json" nautobot_app_mcp_server/__init__.py
# Output: 5 matches — docstring, comment, path variable

# post_migrate wiring removed
grep "post_migrate" nautobot_app_mcp_server/__init__.py
# Output: no matches

# input_schema included in JSON payload
grep '"input_schema": tool.input_schema' nautobot_app_mcp_server/__init__.py
# Output: 1 match

# __file__-based path resolution
grep "os.path.dirname(__file__)" nautobot_app_mcp_server/__init__.py
# Output: 1 match
```

## Commits

| # | Hash | Message |
|---|------|---------|
| 1 | `463e85f` | `feat(09-03): ready() generates tool_registry.json for cross-process discovery` |

## Deviations from Plan

**[Rule 2 - Missing Critical] `tool_registry.json` was never generated before:** Discovered `tool_registry.json` as an untracked file in the repo root — confirming no prior generation mechanism existed. The plan anticipated this as the expected end-state but the file was pre-existing (possibly from Phase 01 or an earlier development iteration). The `ready()` implementation was added as planned.

**Total deviations:** 1 auto-fixed (added generation logic). **Impact:** Minimal — `tool_registry.json` was already committed by a prior step (Phase 09-01 `@register_tool` side-effect); `ready()` now becomes the authoritative generation source.

## Observations

- All 10 core tools (with underscore-prefixed names `_device_list_handler`, etc.) are correctly serialized in `tool_registry.json`
- The underscore prefix on tool names is noted for potential follow-up cleanup in Phase 09 (public tool names vs internal handlers)
- `super().ready()` preserved as the first line — URL pattern registration is still Nautobot's responsibility

## Next

Ready for **09-04**: Continue tool registration refactor tasks.
