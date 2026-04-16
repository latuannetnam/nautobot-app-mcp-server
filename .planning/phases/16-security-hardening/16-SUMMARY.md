---
phase: 16
plan: security-hardening
subsystem: graphql
tags:
  - security
  - graphql
  - validation
key-files:
  created:
    - nautobot_app_mcp_server/mcp/tools/graphql_validation.py
  modified:
    - nautobot_app_mcp_server/mcp/tools/graphql_tool.py
    - nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py
metrics:
  new_tests: 3
  new_files: 1
  modified_files: 2
---

## Summary

Implemented all four plans (16.1, 16.2, 16.3, 16.4) for Phase 16 — Security Hardening.

### What was built

**New file: `graphql_validation.py`** — Houses `MaxDepthRule` and `QueryComplexityRule`, both `ValidationRule` subclasses that run as part of `graphql.validate()` before query execution. Also exports a `parse()` wrapper enabling test-level mocking.

**Refactored: `_sync_graphql_query`** — Replaced the direct `nautobot.core.graphql.execute_query()` call with a three-phase pipeline:
1. **Auth guard** — `user is None or user.is_anonymous` → `{"data": None, "errors": [{"message": "Authentication required"}]}`
2. **`parse()` → `GraphQLError`** → Caught and returned as `ExecutionResult(data=None, errors=[e]).formatted` (HTTP 200, not 500)
3. **`validate()` → depth + complexity rules** → If non-empty error list, short-circuits with `data=None`
4. **`execute()`** → Runs the pre-validated document against the Nautobot schema

**Extended: `test_graphql_tool.py`** — `GraphQLSecurityTestCase` with 3 new tests; existing tests updated to patch the new code path.

### Commits

| Task | Description |
|------|-------------|
| 16.3 | refactor(graphql): parse→execute pipeline in _sync_graphql_query |
| 16.3 | fix(graphql): auth guard catches AnonymousUser not just user=None |
| 16.4 | test(graphql): update existing tests for new code path |
| 16.1 | feat(graphql): add MaxDepthRule (depth ≤8) validation |
| 16.2 | feat(graphql): add QueryComplexityRule (complexity ≤1000) |
| 16.4 | test(graphql): add GraphQLSecurityTestCase (depth/complexity/syntax) |
| lint | style(graphql): fix ruff lint issues across all changed files |

### Deviations from plan

1. **`_graphql` module reference** — Plan 16.3 specified patching `graphql.execute` at the module namespace path. Since `execute` is imported lazily inside the function (required for Django compatibility), a module-level `_graphql` reference (`_gt._graphql = _graphql_module`) was added so the test patch target `nautobot_app_mcp_server.mcp.tools.graphql_tool._graphql.execute` resolves correctly.

2. **`MockExecutionResult`** — Plan 16.4 specified using `mock_validate.return_value = [fake_error]`. The test for successful authenticated execution needed `ExecutionResult` with a `.formatted` property that omits the `"errors"` key when `errors=None`. A simple `MockExecutionResult` subclass overrides the property since `formatted` has no setter.

3. **`__init__` docstring** — `MaxDepthRule.__init__` carries `# noqa: D107` since the 1-line override (`super().__init__(context)`) is self-explanatory and adding a docstring would be noise.

### Self-Check: PASSED

- All 103 tests pass (14 graphql_tool tests, 3 new)
- `ruff check` clean on all changed files
- `ruff format` applied to all changed files
- No new dependencies added (all APIs from graphql-core 3.2.8 / graphene_django transitive deps)
- Auth guard covers both `user=None` and `AnonymousUser`
- Security rules run before `execute()` — over-limit queries return `data=None`, no partial data leaked
