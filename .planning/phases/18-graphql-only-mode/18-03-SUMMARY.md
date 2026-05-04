---
phase: "18-graphql-only-mode"
plan: "18-03"
subsystem: Unit Tests
tags:
  - graphql-only-mode
  - tests
key-files:
  created:
    - nautobot_app_mcp_server/mcp/tests/test_graphql_only_mode.py
  modified: []
metrics:
  commits: 1
  tasks: 1
  lines_added: 230
---

## Summary

Created `test_graphql_only_mode.py` with 10 test methods covering GQLONLY-01 through GQLONLY-05:

- **GQLONLY-01**: `GRAPHQL_ONLY_MODE` defaults to True; `NAUTOBOT_MCP_ENABLE_ALL=true` disables GQL-only
- **GQLONLY-02**: `_list_tools_handler` returns exactly 2 tools (graphql_query, graphql_introspect) in GQL-only mode; correct filter logic for all-tools mode
- **GQLONLY-03**: `ScopeGuardMiddleware` blocks non-GraphQL tools in GQL-only mode; allows graphql_query/graphql_introspect; blocks session tools; core tools pass when GQL-only disabled
- **GQLONLY-04**: Default mode (no env var) = GQL-only mode active

Tests use `unittest.mock.patch`, `sys.exc_info()`, and source inspection — no `assertRaises` context manager (Django test runner incompatibility).

## Commits

| # | Description |
|---|-------------|
| 1 | test(phase-18): add test_graphql_only_mode.py with 10 tests for GQLONLY-01 through GQLONLY-05 |

## Deviations

None — implementation matched plan exactly.

## Self-Check

**PASSED**

- 10 test methods covering all GQLONLY requirements
- `invoke unittest -b -f -s -l nautobot_app_mcp_server.mcp.tests.test_graphql_only_mode` → 10/10 OK