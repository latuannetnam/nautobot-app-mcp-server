---
phase: "18-graphql-only-mode"
plan: "18-04"
subsystem: UAT Tests
tags:
  - graphql-only-mode
  - UAT
key-files:
  created: []
  modified:
    - scripts/run_mcp_uat.py
metrics:
  commits: 1
  tasks: 1
  lines_added: 65
---

## Summary

Added UAT tests T-45, T-46, T-47 to `scripts/run_mcp_uat.py` and implemented auto-detection at startup:

- **Auto-detection:** Calls `client.list_tools()` once at startup. If exactly 2 tools (`graphql_query` + `graphql_introspect`) → GQL-only mode. Otherwise → normal mode.
- **T-45**: Verifies GQL-only manifest has exactly 2 tools; session tools (mcp_enable_tools etc.) are not visible.
- **T-46**: Verifies calling `device_list` in GQL-only mode returns an error/blocked response (not a successful data response).
- **T-47**: Verifies normal mode shows all 15 tools (runs only when GQL-only mode NOT detected).

Categories summary updated to include "GraphQL-Only Mode: T-45, T-46, T-47".

## Commits

| # | Description |
|---|-------------|
| 1 | test(phase-18): add T-45, T-46, T-47 UAT tests and auto-detection to run_mcp_uat.py |

## Deviations

None — implementation matched plan exactly.

## Self-Check

**PASSED**

- `grep -n "T-45\|T-46\|T-47\|GraphQL-Only Mode\|auto-detect" run_mcp_uat.py` shows all required elements
- T-45/T-46 only run when GQL-only mode detected; T-47 only runs in normal mode
- `"GraphQL-Only Mode": ["T-45", "T-46", "T-47"]` added to categories dict