# Phase 16 Verification — Security Hardening

**Phase:** 16-security-hardening
**Date:** 2026-04-16
**Verification by:** Phase gate review

---

## Phase Goal

> Add depth/complexity limits and structured error handling to `graphql_query`. Requirements GQL-10, GQL-11, GQL-12.

---

## must_haves (from 16-PLAN.md §"must_haves")

| # | Must-have | Verification | Status |
|---|-----------|--------------|--------|
| MH-1 | Query depth > 8 returns structured error, no data | `test_depth_limit_enforced`: `assertIsNone(result["data"])`, `"depth" in error.lower()` | ✅ |
| MH-2 | Query complexity > 1000 returns structured error, no data | `test_complexity_limit_enforced`: `assertIsNone(result["data"])`, `"complexity" in error.lower()` | ✅ |
| MH-3 | Malformed GraphQL query returns HTTP 200 with `errors` dict | `test_syntax_error_returns_200_with_errors`: `assertIsNone(result["data"])`, `"Syntax Error" in error` | ✅ |
| MH-4 | 3 new unit tests pass in `test_graphql_tool.py` | `GraphQLSecurityTestCase` (3 methods) confirmed in file; all 103 tests pass | ✅ |
| MH-5 | No new poetry dependencies added | `pyproject.toml` — no `graphql-core`, `graphql`, or any new dep entries | ✅ |

---

## Requirement Traceability

| Req | Requirement | Evidence | Status |
|-----|-------------|----------|--------|
| **GQL-10** | Query depth limit enforced (max_depth ≤ 8) | `MaxDepthRule` in `graphql_validation.py`, `test_depth_limit_enforced` | ✅ |
| **GQL-11** | Query complexity limit enforced (max_complexity ≤ 1000) | `QueryComplexityRule` in `graphql_validation.py`, `test_complexity_limit_enforced` | ✅ |
| **GQL-12** | GraphQL syntax errors returned as structured `errors` array, not HTTP 500 | `parse()` → `GraphQLError` → `ExecutionResult.formatted` in `_sync_graphql_query`, `test_syntax_error_returns_200_with_errors` | ✅ |

Updated `REQUIREMENTS.md` GQL-10/11/12 status: Pending → see open issue below.

---

## File Audit

| File | Change | Plan ref | Verified |
|------|--------|----------|----------|
| `nautobot_app_mcp_server/mcp/tools/graphql_validation.py` | **Created** — `MaxDepthRule`, `QueryComplexityRule`, `parse()` wrapper | 16.1, 16.2 | ✅ |
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | **Modified** — parse → validate → execute pipeline in `_sync_graphql_query` | 16.3 | ✅ |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` | **Modified** — `GraphQLSecurityTestCase` with 3 new test methods | 16.4 | ✅ |

---

## Plan Acceptance Criteria — Cross-Reference

### Plan 16.1 — MaxDepthRule (GQL-10)

| Criterion | Evidence | Pass |
|-----------|----------|------|
| `graphql_validation.py` created in `mcp/tools/` | File confirmed at `nautobot_app_mcp_server/mcp/tools/graphql_validation.py` | ✅ |
| `MaxDepthRule` subclasses `ValidationRule` | `class MaxDepthRule(ValidationRule)` — line 38 | ✅ |
| `enter_field` returns `SKIP` after reporting error | `return SKIP` — line 95 | ✅ |
| Introspection fields `__schema`, `__type`, `__typename` excluded from depth | `_INTROSPECTION_FIELDS` frozenset + check at line 84 | ✅ |
| Fragment cycles handled via `_visited_fragments` dict | `self._visited_fragments: dict[str, None]` at line 51, try/finally at lines 68-72 | ✅ |
| `MAX_DEPTH = 8` constant | Line 19 | ✅ |

### Plan 16.2 — QueryComplexityRule (GQL-11)

| Criterion | Evidence | Pass |
|-----------|----------|------|
| `QueryComplexityRule` subclasses `ValidationRule` | `class QueryComplexityRule(ValidationRule)` — line 121 | ✅ |
| `_count_complexity` counts every `FieldNode` in the AST | Recursive function, line 99–118; inline fragments + fragment spreads included | ✅ |
| Fragments and inline fragments traversed recursively | `_count_complexity` calls itself on `InlineFragmentNode` and `FragmentSpreadNode` | ✅ |
| `enter_document` calls `_count_complexity(node)` once and reports error if > 1000 | Line 129–140 | ✅ |
| Error message includes the actual complexity value | f-string: `f"Query complexity {complexity} exceeds..."` — line 135 | ✅ |
| `MAX_COMPLEXITY = 1000` constant | Line 20 | ✅ |

### Plan 16.3 — Syntax Errors as Structured `errors` Array (GQL-12)

| Criterion | Evidence | Pass |
|-----------|----------|------|
| `_sync_graphql_query` no longer imports or calls `nautobot.core.graphql.execute_query` | Confirmed — no reference to `execute_query` in current file | ✅ |
| `graphql.parse(query)` called inside function body | `document = graphql_validation.parse(query)` — line 83 | ✅ |
| Syntax errors caught via `try/except GraphQLError`, returned as `ExecutionResult(data=None, errors=[e]).formatted` | Lines 82–85 | ✅ |
| `graphql.execute(...)` called with parsed document and request as context | Lines 101–108 | ✅ |
| Function returns `{data, errors}` dict shape | `result.formatted` at line 110 — `ExecutionResult.formatted` always returns dict | ✅ |
| Auth guard (user=None / AnonymousUser) preserved before `parse()` | Line 78 check at top of execution path | ✅ |

### Plan 16.4 — Security Unit Tests

| Criterion | Evidence | Pass |
|-----------|----------|------|
| 3 new test methods added | `GraphQLSecurityTestCase` lines 382–464 | ✅ |
| `@patch` targets `nautobot_app_mcp_server.mcp.tools.graphql_validation.validate` | Lines 399, 422 | ✅ |
| `GraphQLSecurityTestCase` follows `TestCase` base class | `class GraphQLSecurityTestCase(TestCase)` — line 382 | ✅ |
| `_get_or_create_superuser()` fixture helper present | Lines 385–397 | ✅ |
| All 3 tests pass independently | `invoke unittest` — 103 tests OK | ✅ |

---

## Full-Phase Gate

| Gate | Command | Result | Pass |
|------|---------|--------|------|
| All tests pass | `poetry run invoke unittest -b -f -k -s` | **103 tests OK** | ✅ |
| Depth test correct behavior | `data=None`, `"depth"` in error | ✅ (test verified) | ✅ |
| Complexity test correct behavior | `data=None`, `"complexity"` in error` | ✅ (test verified) | ✅ |
| Syntax test correct behavior | `data=None`, `"Syntax Error"` in error | ✅ (test verified) | ✅ |
| No new poetry dependencies | `pyproject.toml` — no new entries | ✅ | ✅ |
| `ruff check` on changed files | `graphql_validation.py` clean; `test_graphql_tool.py` clean | ✅ partial |

---

## Open Issue

### ruff I001 — `graphql_tool.py` lazy import block unsorted

**Introduced by:** Phase 16 commit `088a6f6` ("feat(graphql): parse→execute pipeline with depth/complexity validation"), present through commit `184e3a5` ("fix(graphql): remove dead write-only _gt._graphql assignment").

**Location:** `nautobot_app_mcp_server/mcp/tools/graphql_tool.py`, line 63 — lazy import block inside `_sync_graphql_query`.

**Cause:** The import of `nautobot_app_mcp_server.mcp.tools.graphql_tool as _self` is placed before the `import graphql as _graphql_module` within the `hasattr` guard, causing ruff's import sorter to flag the block as unsorted.

**Fix:** `unset VIRTUAL_ENV && poetry run ruff check nautobot_app_mcp_server/mcp/tools/graphql_tool.py --fix` — auto-fixable (ruff I001 is a single `isort` fix).

**Note:** The I001 in `tools/__init__.py` is **pre-existing** (confirmed: file unchanged since Phase 14 commit `c3e6f00`). Not a Phase 16 regression.

**Impact:** Low — auto-fixable with `ruff --fix`. Code is functionally correct; all 103 tests pass. The `ruff format` self-check in the plan was run at commit time but the I001 ordering issue was introduced in the same commit, bypassing the gate.

**Action required:** Run `unset VIRTUAL_ENV && poetry run ruff check nautobot_app_mcp_server/mcp/tools/graphql_tool.py --fix` then commit the fix. Alternatively, commit `ruff format .` inside the container.

---

## Deviations (from 16-SUMMARY.md §"Deviations from plan")

| # | Deviation | Verified | Notes |
|---|-----------|----------|-------|
| D-1 | `_graphql` module reference via `_self._graphql` attribute instead of direct lazy import | ✅ | Enables test patch target `nautobot_app_mcp_server.mcp.tools.graphql_tool._graphql.execute` |
| D-2 | `MockExecutionResult` subclass overrides `formatted` property | ✅ | `ExecutionResult.formatted` has no setter; subclass required |
| D-3 | `MaxDepthRule.__init__` carries `# noqa: D107` | ✅ | 1-line override; docstring would be noise |

---

## Commits (from 16-SUMMARY.md §"Commits")

| Commit | Description | In repo | Status |
|--------|-------------|---------|--------|
| `088a6f6` | feat(graphql): parse→execute pipeline with depth/complexity validation | ✅ | Present |
| `184e3a5` | fix(graphql): remove dead write-only _gt._graphql assignment | ✅ | Present |
| `78f3ced` | docs(16): add code review report | ✅ | Present |

---

## Conclusion

| Dimension | Result |
|-----------|--------|
| All must_haves | ✅ 5/5 |
| All requirements (GQL-10, GQL-11, GQL-12) | ✅ 3/3 |
| All plan acceptance criteria | ✅ |
| All 103 tests pass | ✅ |
| New file created | ✅ `graphql_validation.py` |
| Modified files | ✅ `graphql_tool.py`, `test_graphql_tool.py` |
| No new poetry dependencies | ✅ |
| `ruff check` on changed files | ⚠️ `graphql_tool.py` has 1 auto-fixable I001 (Phase 16 issue) |
| `ruff check` on test file | ✅ clean |

**Verdict: GO — with 1 open issue (ruff I001 auto-fix pending)**

The phase goal is substantively achieved. All functional requirements (GQL-10, GQL-11, GQL-12) are implemented and tested. The single ruff lint issue in `graphql_tool.py` is a pre-commit ordering violation introduced in the same Phase 16 commit — auto-fixable with `ruff --fix`.
