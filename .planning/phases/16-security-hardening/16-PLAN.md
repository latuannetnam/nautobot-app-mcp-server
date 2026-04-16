# Phase 16 Plan — Security Hardening

**Phase:** 16-security-hardening
**Goal:** Add depth/complexity limits and structured error handling to `graphql_query`. Requirements GQL-10, GQL-11, GQL-12.
**Plans:** 4 (`16.1`, `16.2`, `16.3`, `16.4`)
**Waves:** 2 (Wave 1: `16.3-syntax-errors`, `16.4-tests` → Wave 2: `16.1-depth`, `16.2-complexity`)
**Status:** Ready for implementation

---

## Wave 1 — Syntax Safety Net (Prerequisite for Wave 2)

Wave 1 establishes the parse-then-execute pattern and tests it. Wave 2 layers the custom validation rules on top.

| Plan | Description | GQL |
|------|-------------|-----|
| 16.3 | Catch `GraphQLError` from `parse()` → HTTP 200 structured errors | GQL-12 |
| 16.4 | 3 security unit tests (depth, complexity, syntax) | GQL-10, GQL-11, GQL-12 |

## Wave 2 — Depth & Complexity Guards

| Plan | Description | GQL |
|------|-------------|-----|
| 16.1 | `MaxDepthRule` (≤8) + enforce in `_sync_graphql_query` | GQL-10 |
| 16.2 | `QueryComplexityRule` (≤1000) + enforce in `_sync_graphql_query` | GQL-11 |

---

## must_haves (derived from phase goal)

- Query depth > 8 returns structured error, no data
- Query complexity > 1000 returns structured error, no data
- Malformed GraphQL query returns HTTP 200 with `errors` dict
- 3 new unit tests pass in `test_graphql_tool.py`
- No new poetry dependencies added

---

## Plan 16.3 — Syntax Errors as Structured `errors` Array

```yaml
wave: 1
depends_on: []
requirements:
  - GQL-12
files_modified:
  - nautobot_app_mcp_server/mcp/tools/graphql_tool.py
```

### Objective

Refactor `_sync_graphql_query` to replace the direct `execute_query()` call with a parse → execute pattern, so that malformed GraphQL queries are caught as `GraphQLError` and returned as structured error dicts (HTTP 200), not propagated as unhandled exceptions (HTTP 500).

### Tasks

```yaml
- id: 16.3-T01
  read_first:
    - .venv/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py
    - .venv/lib/python3.12/site-packages/graphql/execution/execute.py  # ExecutionResult.formatted
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §2.9 ExecutionResult.formatted shape
  action: >
    In `_sync_graphql_query`, replace the `from nautobot.core.graphql import execute_query` lazy import
    and the direct `execute_query(query=query, variables=variables, user=user)` call with a
    parse → execute pattern:

    1. Import `graphql` lazily inside the function body and call `graphql.parse(query)`.
       Wrap in `try/except GraphQLError`; on syntax error, return
       `ExecutionResult(data=None, errors=[e]).formatted`.

    2. Get the schema via `graphene_settings.SCHEMA.graphql_schema` (also a lazy import).

    3. Build a Django `Request` object via `RequestFactory().post("/graphql/")` and set
       `request.user = user`.

    4. Call `graphql.execute(schema=schema, document=document, context_value=request,
       variable_values=variables)`.

    5. Return `result.formatted`.

    Keep the auth guard (user=None check) at the top of the function, before `parse()`.
  acceptance_criteria: >
    - `_sync_graphql_query` no longer imports or calls `nautobot.core.graphql.execute_query`
    - `graphql.parse(query)` is called inside the function body
    - Syntax errors are caught via `try/except GraphQLError` and returned as
      `ExecutionResult(data=None, errors=[e]).formatted`
    - `graphql.execute(...)` is called with the parsed document and request as context
    - The function returns the same `{data, errors}` dict shape as before

- id: 16.3-T02
  read_first:
    - .planning/phases/14-graphql-tool-scaffold/14-CONTEXT.md  # D-07: error handling
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §2.10 parse() raises GraphQLError
  action: >
    Verify the existing `try/except ValueError` block for anonymous auth failures
    (user=None) is preserved above the `parse()` call. This guard is the first statement
    in the refactored function and returns `{"data": None, "errors": [{"message": "Authentication required"}]}`.
  acceptance_criteria: >
    - Calling `_sync_graphql_query` with `user=None` still returns the auth-error dict
    - No change to the ValueError handling pattern from Phase 14
```

### Verification

```yaml
command: >
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool
criteria: >
  All existing tests in `GraphQLQueryHandlerTestCase` pass without modification.
  The parse → execute refactor preserves all existing behavior.
```

---

## Plan 16.1 — Enforce Query Depth Limit (≤8)

```yaml
wave: 2
depends_on: [16.3]
requirements:
  - GQL-10
files_modified:
  - nautobot_app_mcp_server/mcp/tools/graphql_tool.py
```

### Objective

Add a `MaxDepthRule` custom `ValidationRule` (subclass of `ASTValidationRule`) that traverses the query AST and rejects queries whose field nesting depth exceeds 8. Integrate it into `_sync_graphql_query` via `graphql.validate()`.

### Tasks

```yaml
- id: 16.1-T01
  read_first:
    - .venv/lib/python3.12/site-packages/graphql/validation/rules/max_introspection_depth_rule.py
    - .venv/lib/python3.12/site-packages/graphql/language/ast.py  # FieldNode, SelectionSetNode, FragmentSpreadNode, InlineFragmentNode
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §2.3 MaxIntrospectionDepthRule reference
  action: >
    Create `graphql_validation.py` (sibling to `graphql_tool.py` in `mcp/tools/`) containing:

    ```python
    from __future__ import annotations

    from typing import TYPE_CHECKING, Any

    from graphql import (
        FieldNode,
        FragmentSpreadNode,
        GraphQLError,
        InlineFragmentNode,
        SKIP,
        validate,
    )
    from graphql.validation import ValidationContext, ValidationRule, specified_rules
    from graphql.language.ast import DocumentNode, Node

    MAX_DEPTH = 8
    _INTROSPECTION_FIELDS = frozenset({"__schema", "__type", "__typename"})

    __all__ = ["MaxDepthRule", "QueryComplexityRule", "validate_with_security_rules"]


    class MaxDepthRule(ValidationRule):
        """ASTValidationRule that rejects queries with field nesting depth > MAX_DEPTH."""

        def __init__(self, context: ValidationContext) -> None:
            super().__init__(context)
            self._visited_fragments: dict[str, None] = {}

        def _get_depth(self, node: Node, depth: int = 0) -> int:
            """Return maximum nesting depth below this node."""
            selection_set = getattr(node, "selection_set", None)
            if selection_set is None:
                return depth

            max_child_depth = depth + 1
            for selection in selection_set.selections:
                if isinstance(selection, FragmentSpreadNode):
                    fragment_name = selection.name.value
                    if fragment_name in self._visited_fragments:
                        continue
                    fragment = self.context.get_fragment(fragment_name)
                    if fragment is None:
                        continue
                    self._visited_fragments[fragment_name] = None
                    try:
                        child_depth = self._get_depth(fragment, depth + 1)
                    finally:
                        del self._visited_fragments[fragment_name]
                    max_child_depth = max(max_child_depth, child_depth)
                elif isinstance(selection, InlineFragmentNode):
                    child_depth = self._get_depth(selection, depth + 1)
                    max_child_depth = max(max_child_depth, child_depth)
                else:
                    child_depth = self._get_depth(selection, depth + 1)
                    max_child_depth = max(max_child_depth, child_depth)
            return max_child_depth

        def enter_field(self, node: FieldNode, *_args: Any) -> Any:
            """Called for each field in the query; report error if depth > MAX_DEPTH."""
            if node.name.value in _INTROSPECTION_FIELDS:
                return None  # introspection fields do not count toward depth

            depth = self._get_depth(node, depth=0)
            if depth > MAX_DEPTH:
                self.report_error(
                    GraphQLError(
                        f"Query depth {depth} exceeds maximum allowed depth of {MAX_DEPTH}",
                        nodes=[node],
                    )
                )
                return SKIP
            return None
    ```

    Place `QueryComplexityRule` stubs in the same file (plan 16.2 fills them in), or place
    only `MaxDepthRule` now. The stub for `QueryComplexityRule` should import cleanly
    but raise `NotImplementedError` if instantiated, or be a no-op placeholder.
    The shared helper `validate_with_security_rules(schema, document)` can also be stubbed.
  acceptance_criteria: >
    - `graphql_validation.py` created in `mcp/tools/`
    - `MaxDepthRule` subclasses `ValidationRule` from graphql-core
    - `enter_field` returns `SKIP` after reporting error (short-circuits traversal)
    - Introspection fields `__schema`, `__type`, `__typename` are excluded from depth count
    - Fragment cycles are handled via `_visited_fragments` dict (same pattern as MaxIntrospectionDepthRule)

- id: 16.1-T02
  read_first:
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §3.1 parse-then-execute design
  action: >
    In `graphql_tool.py`, update `_sync_graphql_query` to call `graphql.validate()`
    with `MaxDepthRule` (and the stub `QueryComplexityRule`) after `parse()` succeeds:

    ```python
    from nautobot_app_mcp_server.mcp.tools.graphql_validation import (
        MaxDepthRule,
        QueryComplexityRule,
    )

    # After parse() succeeds and before execute():
    validation_errors = validate(
        schema=schema,
        document_ast=document,
        rules=[MaxDepthRule, QueryComplexityRule, *specified_rules],
    )
    if validation_errors:
        return ExecutionResult(data=None, errors=validation_errors).formatted
    ```

    Import `validate`, `ExecutionResult` from graphql inside the lazy import block.
    Import `MaxDepthRule`, `QueryComplexityRule` at the top of `_sync_graphql_query`'s
    lazy import block (local sibling import, lazy to avoid Django setup issues).
  acceptance_criteria: >
    - `graphql.validate()` is called with `rules=[MaxDepthRule, QueryComplexityRule, *specified_rules]`
    - If `validate()` returns a non-empty list of errors, execution is short-circuited
    - The over-limit error is returned as `ExecutionResult(data=None, errors=errors).formatted`
    - `data` is `None` in the error response (no partial data leaked)
```

### Verification

```yaml
command: >
  # Manual verification: deeply nested query should return depth error
  # (verified via unit test in plan 16.4)
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool
criteria: >
  `test_depth_limit_enforced` passes (data=None, "depth" in error message).
  All other tests in the module continue to pass.
```

---

## Plan 16.2 — Enforce Query Complexity Limit (≤1000)

```yaml
wave: 2
depends_on: [16.1]
requirements:
  - GQL-11
files_modified:
  - nautobot_app_mcp_server/mcp/tools/graphql_validation.py
```

### Objective

Add a `QueryComplexityRule` custom `ValidationRule` that counts every `FieldNode` in the query AST (each contributes 1 to complexity) and rejects queries with complexity > 1000. Integrate it alongside `MaxDepthRule` already placed in `graphql_validation.py` in plan 16.1.

### Tasks

```yaml
- id: 16.2-T01
  read_first:
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §3.3 QueryComplexityRule design
    - .planning/phases/16-security-hardening/16-CONTEXT.md  # D-02: complexity counting
  action: >
    In `graphql_validation.py`, replace the `QueryComplexityRule` stub (or add) with the full
    implementation:

    ```python
    MAX_COMPLEXITY = 1000


    def _count_complexity(node: Node) -> int:
        """Count total field selections across all paths (simple field-count heuristic)."""
        selection_set = getattr(node, "selection_set", None)
        if selection_set is None:
            return 1  # scalar leaf = 1 field

        total = 0
        for selection in selection_set.selections:
            if isinstance(selection, FragmentSpreadNode):
                total += 1  # fragment spread itself counts as a selection
            elif isinstance(selection, InlineFragmentNode):
                total += _count_complexity(selection)
            else:
                total += _count_complexity(selection)
        return total


    class QueryComplexityRule(ValidationRule):
        """ASTValidationRule that rejects queries with complexity > MAX_COMPLEXITY."""

        def enter_document(self, node: DocumentNode, *_args: Any) -> Any:
            """Called once per document; check total field count."""
            complexity = _count_complexity(node)
            if complexity > MAX_COMPLEXITY:
                self.report_error(
                    GraphQLError(
                        f"Query complexity {complexity} exceeds maximum allowed complexity of {MAX_COMPLEXITY}",
                        nodes=[node],
                    )
                )
                return SKIP
            return None
    ```

    Use `enter_document` (called once per query document) rather than field-by-field counting
    for efficiency. The `_count_complexity` helper recursively counts all `FieldNode` selections.
    Introspection fields are included (they are fields too) — no special exclusion.
  acceptance_criteria: >
    - `QueryComplexityRule` subclasses `ValidationRule`
    - `_count_complexity` counts every `FieldNode` in the AST (1 per field)
    - Fragments and inline fragments are traversed recursively
    - `enter_document` calls `_count_complexity(node)` once and reports error if > 1000
    - Error message includes the actual complexity value
```

### Verification

```yaml
command: >
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool
criteria: >
  `test_complexity_limit_enforced` passes (data=None, "complexity" in error message).
  All other tests in the module continue to pass.
```

---

## Plan 16.4 — Security Unit Tests

```yaml
wave: 1
depends_on: [16.3]
requirements:
  - GQL-10
  - GQL-11
  - GQL-12
files_modified:
  - nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py
```

### Objective

Add `GraphQLSecurityTestCase` — 3 new test methods covering depth limit enforcement, complexity limit enforcement, and syntax error structured responses (GQL-10, GQL-11, GQL-12).

### Tasks

```yaml
- id: 16.4-T01
  read_first:
    - .planning/phases/16-security-hardening/16-RESEARCH.md  # §4 Test design
    - .planning/phases/16-security-hardening/16-CONTEXT.md  # D-06: test approach
    - nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py  # existing test patterns
  action: >
    Add `GraphQLSecurityTestCase` class at the end of `test_graphql_tool.py`:

    ```python
    class GraphQLSecurityTestCase(TestCase):
        """Test depth/complexity limits and structured error handling (GQL-10, GQL-11, GQL-12)."""

        def _get_or_create_superuser(self):
            """Return an existing superuser or create one for test fixtures."""
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                user = User.objects.create_superuser(
                    username="testadmin",
                    email="admin@test.local",
                    password="testpass",
                )
            return user

        @patch(
            "nautobot_app_mcp_server.mcp.tools.graphql_validation.validate"
        )
        def test_depth_limit_enforced(self, mock_validate):
            """GQL-10: Query with depth 9 is rejected with data=None and 'depth' in message.

            _sync_graphql_query calls graphql.validate() before execute().
            Patch graphql_validation.validate to simulate MaxDepthRule rejecting the query.
            """
            from graphql import GraphQLError

            fake_error = GraphQLError(
                "Query depth 9 exceeds maximum allowed depth of 8"
            )
            mock_validate.return_value = [fake_error]

            user = self._get_or_create_superuser()
            result = graphql_tool._sync_graphql_query(
                query="{ a { b { c { d { e { f { g { h { i } } } } } } } } }",  # depth 9
                variables=None,
                user=user,
            )

            self.assertIsNone(result["data"])
            self.assertIsNotNone(result["errors"])
            self.assertIn("depth", result["errors"][0]["message"].lower())

        @patch(
            "nautobot_app_mcp_server.mcp.tools.graphql_validation.validate"
        )
        def test_complexity_limit_enforced(self, mock_validate):
            """GQL-11: Over-complex query is rejected with data=None and 'complexity' in message.

            Patch graphql_validation.validate to simulate QueryComplexityRule rejecting the query.
            """
            from graphql import GraphQLError

            fake_error = GraphQLError(
                "Query complexity 1001 exceeds maximum allowed complexity of 1000"
            )
            mock_validate.return_value = [fake_error]

            # Build a query with > 1000 field selections
            many_fields = ", ".join(f"field{i}: name" for i in range(1001))
            query = f"{{ {many_fields} }}"

            user = self._get_or_create_superuser()
            result = graphql_tool._sync_graphql_query(
                query=query,
                variables=None,
                user=user,
            )

            self.assertIsNone(result["data"])
            self.assertIsNotNone(result["errors"])
            self.assertIn("complexity", result["errors"][0]["message"].lower())

        def test_syntax_error_returns_200_with_errors(self):
            """GQL-12: Malformed query returns HTTP 200 with structured errors dict.

            parse() raises GraphQLError for unclosed braces, invalid syntax, etc.
            This is caught in _sync_graphql_query and returned as
            ExecutionResult.formatted. No unhandled exception propagates from the tool.
            """
            user = self._get_or_create_superuser()
            result = graphql_tool._sync_graphql_query(
                query="{ devices {",  # unclosed brace — syntax error
                variables=None,
                user=user,
            )

            self.assertIsNone(result["data"])
            self.assertIsNotNone(result["errors"])
            self.assertIn("Syntax Error", result["errors"][0]["message"])
    ```

    Use `@patch("nautobot_app_mcp_server.mcp.tools.graphql_validation.validate")`
    for the depth and complexity tests (patches the local module where `validate`
    is called from `graphql_validation.py`). For the syntax error test, no mock
    is needed — the real `parse()` raises `GraphQLError` naturally.
  acceptance_criteria: >
    - 3 new test methods added to `test_graphql_tool.py`
    - `@patch` targets `nautobot_app_mcp_server.mcp.tools.graphql_validation.validate`
    - `GraphQLSecurityTestCase` follows the same `TestCase` base class as existing tests
    - `_get_or_create_superuser()` fixture helper follows the existing pattern
    - All 3 tests pass independently
```

### Verification

```yaml
command: >
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool.GraphQLSecurityTestCase -v 2
criteria: >
  - `test_depth_limit_enforced`: data=None, "depth" in error message
  - `test_complexity_limit_enforced`: data=None, "complexity" in error message
  - `test_syntax_error_returns_200_with_errors`: data=None, "Syntax Error" in error message
  - All tests in `GraphQLQueryHandlerTestCase` and `GraphQLIntrospectHandlerTestCase` still pass
```

---

## Full-Phase Gate

```yaml
command: poetry run invoke unittest -b -f -k -s
criteria: >
  - All tests in `test_graphql_tool.py` pass (≥10 total: 7 existing + 3 new)
  - `test_depth_limit_enforced` → data=None, "depth" in error message
  - `test_complexity_limit_enforced` → data=None, "complexity" in error message
  - `test_syntax_error_returns_200_with_errors` → data=None, "Syntax Error" in error message
  - No new poetry dependencies added (check `pyproject.toml` unchanged)
  - `ruff check nautobot_app_mcp_server/mcp/tools/` → no new violations
  - `ruff check nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` → no violations
```

---

## Implementation Order Summary

```
Wave 1 (Foundation)
  Plan 16.3 → Refactor _sync_graphql_query: parse → execute pattern
  Plan 16.4 → 3 security unit tests

Wave 2 (Validation Rules)
  Plan 16.1 → graphql_validation.py + MaxDepthRule + wired into _sync_graphql_query
  Plan 16.2 → QueryComplexityRule in graphql_validation.py

Full gate → invoke unittest (all pass)
```

---

## File Summary

| File | Change |
|------|--------|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | Refactor `_sync_graphql_query` to parse → validate → execute; import validation rules |
| `nautobot_app_mcp_server/mcp/tools/graphql_validation.py` | **New:** `MaxDepthRule`, `QueryComplexityRule`, constants |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` | Add `GraphQLSecurityTestCase` with 3 test methods |

---

*Plan: 16-security-hardening*
*must_haves: GQL-10 depth ≤8, GQL-11 complexity ≤1000, GQL-12 structured errors, 3 unit tests, no new deps*
