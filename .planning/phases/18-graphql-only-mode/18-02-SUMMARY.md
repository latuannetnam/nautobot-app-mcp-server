---
phase: "18-graphql-only-mode"
plan: "18-02"
subsystem: Two-Layer Enforcement
tags:
  - graphql-only-mode
  - session-tools
  - middleware
key-files:
  created: []
  modified:
    - nautobot_app_mcp_server/mcp/session_tools.py
    - nautobot_app_mcp_server/mcp/middleware.py
metrics:
  commits: 1
  tasks: 2
  lines_added: 38
---

## Summary

Implemented two-layer GQL-only enforcement:

**Layer 1 (`session_tools.py`):** `_list_tools_handler` returns exactly `graphql_query` and `graphql_introspect` when `GRAPHQL_ONLY_MODE=True`. Core tools are hidden. Session tools are hidden.

**Layer 2 (`middleware.py`):** `ScopeGuardMiddleware.on_call_tool` blocks calls to any non-GraphQL tool with `ToolNotFoundError("Tool '{name}' is not available in GraphQL-only mode. Only graphql_query and graphql_introspect are available.")`.

Both layers import `GRAPHQL_ONLY_MODE` and `_ALLOWED_GQL_ONLY_TOOLS` from `commands.py`.

## Commits

| # | Hash | Description |
|---|------|-------------|
| 1 | `b1d9a2f` | feat(phase-18): add two-layer GQL-only enforcement |

## Deviations

None — implementation matched plan exactly.

## Self-Check

**PASSED**

- `grep -n "GRAPHQL_ONLY_MODE\|_ALLOWED_GQL_ONLY_TOOLS" session_tools.py` → 3 matches
- `grep -n "GRAPHQL_ONLY_MODE\|_ALLOWED_GQL_ONLY_TOOLS" middleware.py` → 4 matches
- `_list_tools_handler` has `if GRAPHQL_ONLY_MODE:` branch returning exactly 2 tools
- `ScopeGuardMiddleware.on_call_tool` has `if GRAPHQL_ONLY_MODE:` block with correct error message