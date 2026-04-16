# Phase 16: Security Hardening - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Add query depth limits (≤8), complexity limits (≤1000), and structured error handling to `graphql_query`. Covers GQL-10, GQL-11, GQL-12. Unit tests (3 new cases) are included in scope.

</domain>

<decisions>
## Implementation Decisions

### Limit enforcement location
- **D-01:** Limits enforced via **parse-then-execute** pattern inside `_sync_graphql_query`
- First: `graphql.parse(query)` → `graphql.validate(schema, doc, rules=[...])` with custom rules
- If validation errors exist → return `ExecutionResult(data=None, errors=validation_errors).formatted` immediately
- If validation passes → call `execute_query` as normal
- This keeps all logic in `_sync_graphql_query` without patching Nautobot internals

### Depth/complexity implementation
- **D-02:** Two custom `ASTValidationRule` subclasses in `graphql_tool.py` (or a `validation.py` sibling):
  1. **`MaxDepthRule`** — visitor pattern traversing the DocumentNode AST, counting nesting level of field selections (excluding introspection fields). Rejects at depth > 8.
  2. **`QueryComplexityRule`** — static field-count analysis: sum total field selections across all paths. Rejects at complexity > 1000.
- Pattern modeled on `graphql_core.max_introspection_depth_rule.MaxIntrospectionDepthRule` (stdlib reference implementation)
- Both rules subclass `ASTValidationRule` and call `self.report_error(GraphQLError(...))`
- No new poetry dependencies — all graphql-core 3.2.8 APIs

### Error response format
- **D-03:** Over-limit queries return `ExecutionResult(data=None, errors=[GraphQLError("...")]).formatted`
- Same shape as Phase 14 D-07: `{"data": None, "errors": [{"message": "...", ...}]}`
- `errors[0]["message"]` contains the human-readable rejection reason
- Consistent with all existing GraphQL error responses in the tool

### Validation pass order
- **D-04:** Syntax validation runs first (via `graphql.parse()`). If parse fails → `parse()` raises `GraphQLError` naturally → caught by existing error path
- Depth/complexity rules run via `graphql.validate()` after successful parse
- This ordering is standard in graphql-core: parse → validate → execute

### Error handling boundary
- **D-05:** `_sync_graphql_query` already has a `try/except ValueError` for auth failures — the validation step adds errors to the `errors` list before `execute_query` is called
- Over-limit queries are **not exceptions** — they are `ExecutionResult` objects with `data=None` and populated `errors`
- No unhandled exceptions propagate to FastMCP from validation failures

### Unit test approach
- **D-06:** 3 new test cases added to `test_graphql_tool.py` as a new test class `GraphQLSecurityTestCase`:
  1. `test_depth_limit_enforced` — mock/patch `_sync_graphql_query` or `graphql.validate` to return over-depth query; verify `data=None` and `"depth"` in error message
  2. `test_complexity_limit_enforced` — same pattern for over-complexity query
  3. `test_syntax_error_returns_200_with_errors` — malformed query returns HTTP 200 with `errors` dict (GQL-12)
- Mock at module level (`@patch` on `graphql_tool._sync_graphql_query` or `graphql.validate`) — consistent with Phase 14/15 pattern
- Run via `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool`

### File layout
- **D-07:** Custom validation rules in `graphql_tool.py` (or optionally `graphql_validation.py` sibling)
- No new files beyond the 3 test methods in `test_graphql_tool.py`
- `tools/__init__.py` — no changes needed (graphql_tool already registered)

### Claude's Discretion
- Exact class names for the validation rules (`MaxDepthRule` vs `QueryDepthRule`, etc.)
- Whether to place validation rules at module level in `graphql_tool.py` or a separate `graphql_validation.py` file
- Whether to use `__all__` to export the rule classes
- Test class/method names — follow existing `TestXxx` / `test_xxx` convention
- How to patch in tests: at `graphql.validate` vs `execute_query` vs `_sync_graphql_query` directly

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### GraphQL execution
- `.venv/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py` — `execute_query()` function: `parse(query)` → `execute(...)` chain; create a `_limited_execute_query` variant or wrap in `_sync_graphql_query`
- `.venv/lib/python3.12/site-packages/graphql/validation/rules/max_introspection_depth_rule.py` — **reference implementation** for custom `ASTValidationRule`: visitor pattern, `enter_field`, `report_error`, `SKIP`
- `.venv/lib/python3.12/site-packages/graphql/validation/validate.py` — `validate(schema, document, rules=None)` standalone function; accepts sequence of `ValidationRule` classes
- `.venv/lib/python3.12/site-packages/graphql/validation/rules/__init__.py` — exports `ASTValidationRule` base class
- `.venv/lib/python3.12/site-packages/graphql/__init__.py` — `parse()`, `execute()`, `GraphQLError`, `ExecutionResult`

### Existing tool patterns
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — Phase 14 `graphql_query` handler; `_sync_graphql_query` sync helper; auth + sync boundary pattern to extend
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — Phase 14/15 test patterns; `_create_token` helper; `@patch` at module level; `AsyncToSync` runner

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` §v2.0 Requirements — GQL-10, GQL-11, GQL-12 trace matrix
- `.planning/ROADMAP.md` §Phase 16 — goal, success criteria, plan table
- `.planning/phases/14-graphql-tool-scaffold/14-CONTEXT.md` — Phase 14 decisions: D-01 through D-07 apply (async boundary, auth, return shape, file layout, error handling)
- `.planning/phases/15-introspection-permissions/15-CONTEXT.md` — Phase 15 decisions: SDL validation, auth enforcement, file layout

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- `ASTValidationRule` base class in graphql-core — subclass for both depth and complexity rules
- `GraphQLError` — used in `report_error()` call inside validation rules
- `ExecutionResult.formatted` — produces the `{"data": None, "errors": [...]}` dict
- `sync_to_async(..., thread_sensitive=True)` pattern — wraps `_sync_graphql_query` at the tool handler level
- `_create_token()` in `test_graphql_tool.py` — test token creation without ORM side effects

### Established Patterns
- Sync helper function (`_sync_graphql_query`) — called via `sync_to_async` at handler boundary; add parse+validate step here
- Error dict shape: `{"data": ..., "errors": [...]}` from `ExecutionResult.formatted`
- Module-level patching in tests: `@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")`
- Lazy imports inside sync helper functions (import `nautobot.core.graphql` inside function body)

### Integration Points
- `graphql_tool.py` — add validation step to `_sync_graphql_query` before calling `execute_query`
- `test_graphql_tool.py` — add 3 security test cases in new `GraphQLSecurityTestCase` class
- `tools/__init__.py` — no changes needed (graphql_tool already registered)

</codebase_context>

<specifics>
## Specific Ideas

- Model custom rules directly on `MaxIntrospectionDepthRule` — it shows exactly the visitor pattern and error reporting
- Depth counts field nesting level (not introspection fields like `__schema`, `__type`)
- Complexity = total field selections across all paths (simple count, no type weights)
- No new dependencies — all graphql-core 3.2.8 APIs already available as Nautobot transitive deps

</specifics>

<deferred>
## Deferred Ideas

- None — all GQL-10/GQL-11/GQL-12 scope items addressed

</deferred>

---

*Phase: 16-security-hardening*
*Context gathered: 2026-04-16*
