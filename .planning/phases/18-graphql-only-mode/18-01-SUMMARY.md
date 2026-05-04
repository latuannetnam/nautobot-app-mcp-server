---
phase: "18-graphql-only-mode"
plan: "18-01"
subsystem: MCP Server Configuration
tags:
  - graphql-only-mode
  - env-var
  - commands.py
key-files:
  created:
    - nautobot_app_mcp_server/mcp/commands.py
  modified: []
metrics:
  commits: 1
  tasks: 1
  lines_added: 7
---

## Summary

Added `GRAPHQL_ONLY_MODE` constant and `_ALLOWED_GQL_ONLY_TOOLS` tuple to `commands.py`. Default is GQL-only mode on (True). Set `NAUTOBOT_MCP_ENABLE_ALL=true` to show all 15 tools.

## Commits

| # | Hash | Description |
|---|------|-------------|
| 1 | `40cb1cd` | docs(phase-18): update environment variable references from NAUTOBOT_MCP_GRAPHQL_ONLY to NAUTOBOT_MCP_ENABLE_ALL across documentation and code |

## Deviations

None — implementation matched plan exactly.

## Self-Check

**PASSED**

- `grep -n "GRAPHQL_ONLY_MODE\|_ALLOWED_GQL_ONLY_TOOLS\|NAUTOBOT_MCP_ENABLE_ALL" commands.py` returns 3 matches
- Constant defined at module level before `nautobot.setup()` call
- `_ALLOWED_GQL_ONLY_TOOLS` contains exactly `graphql_query` and `graphql_introspect`