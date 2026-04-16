# Phase 16: Security Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-16
**Phase:** 16-security-hardening
**Areas discussed:** Limit enforcement location, Depth/complexity strategy, Error response format, Unit test approach

---

## Limit enforcement location

| Option | Description | Selected |
|--------|-------------|----------|
| Parse-then-execute in _sync_graphql_query | Call graphql.parse() + validate() with custom rules first. If over-limit, return formatted errors immediately. If OK, call execute_query. Cleanest — one file, surgical change. | ✓ |
| New wrapper function | Create a new _graphql_query_with_limits() that re-implements execute_query's logic with validation_rules passed to execute(). Duplicates code but fully isolated. | |
| Patch execute_query import | Monkey-patch or pre-bind Nautobot's execute_query to add validation_rules. Fragile — depends on execute_query internals. | |

**User's choice:** Parse-then-execute in _sync_graphql_query (recommended)
**Notes:** Cleanest approach, surgical change to one file.

---

## Depth/complexity strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Two custom ASTValidationRules | Custom ASTValidationRule subclass using visitor pattern. Proven pattern from graphql-core's own MaxIntrospectionDepthRule. No new dependencies. Complexity = static field-count analysis. | ✓ |
| Library for depth, custom for complexity | Adds graphql-depth-limit package. Handles depth out of the box. Complexity still custom. More deps but depth is battle-tested. | |

**User's choice:** Two custom ASTValidationRules (recommended)
**Notes:** Model directly on MaxIntrospectionDepthRule in graphql-core stdlib — exact visitor pattern reference.

---

## Error response format

| Option | Description | Selected |
|--------|-------------|----------|
| ExecutionResult.formatted dict | Return ExecutionResult({'data': None}, errors=[GraphQLError('Query depth exceeds maximum of 8')]). Full consistency with existing pattern, returns dict via .formatted. | ✓ |
| Plain dict error | Return plain {'errors': [{'message': '...'}]} without a GraphQLError. Simpler but not using graphql-core's structured error type. | |

**User's choice:** ExecutionResult.formatted dict (recommended)
**Notes:** Consistent with Phase 14 D-07 error handling pattern.

---

## Unit test approach

| Option | Description | Selected |
|--------|-------------|----------|
| Add to test_graphql_tool.py | Patch graphql.parse and validate to return deep/complex queries with specific GraphQLError. Consistent with Phase 14/15 — mock at module level. Tests are fast, isolated, no DB needed. | ✓ |
| New test_graphql_security.py | Create test_graphql_security.py. More file separation but splits GraphQL tests across two files. | |

**User's choice:** Add to test_graphql_tool.py (recommended)
**Notes:** Consistent with Phase 14/15 mock-based testing pattern.

---

## Research Findings Applied

- graphql-core 3.2.8 provides `MaxIntrospectionDepthRule` as a reference implementation in the stdlib
- `execute()` accepts `validation_rules` param but `execute_query` builds this internally — cannot use it directly
- `graphql.validate(schema, doc, rules=[...])` is a standalone function callable before `execute_query`
- Both custom rules follow the same pattern: subclass `ASTValidationRule`, use visitor methods, call `self.report_error(GraphQLError(...))`
- No built-in max depth or complexity rules in graphql-core 3.2.8 — must implement both custom

