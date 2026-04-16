# Phase 17: UAT & Documentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-16
**Phase:** 17-uat-and-documentation
**Areas discussed:** GraphQL smoke test (P-09) — what to verify, UAT suite (T-37+) — what to cover, Test organization — where tests live, SKILL.md — how to document GraphQL tools

---

## GraphQL smoke test (P-09) — what to verify

| Option | Description | Selected |
|--------|-------------|----------|
| Valid query returns data (recommended) | Call graphql_query with known query, assert data returned and errors null/empty | ✓ |
| Valid query + error handling | Test both valid query and invalid query returns errors dict | |
| Valid query + auth check | Valid query returns data + anonymous token returns empty | |

**User's choice:** Valid query returns data (recommended)
**Notes:** Follows same pattern as P-01–P-08 smoke tests. Auth checked in T-40.

---

## UAT suite (T-37+) — what to cover

| Option | Description | Selected |
|--------|-------------|----------|
| 4 tests (T-37 to T-40, minimum per roadmap) | T-37: valid query, T-38: invalid/syntax, T-39: introspect SDL, T-40: auth enforcement | |
| 7 tests (T-37 to T-43) | Above + auth propagation (T-41), variables (T-42), depth/complexity limits (T-43) | ✓ |
| 6 tests (T-37 to T-42) | Valid, syntax, introspect, auth, variables, depth/complexity | |

**User's choice:** 7 tests (T-37 to T-43)
**Notes:** Covers auth propagation (T-42), variables injection (T-41), and limit enforcement (T-43).

---

## Test organization — where tests live

| Option | Description | Selected |
|--------|-------------|----------|
| Add to run_mcp_uat.py (recommended) | New section ### 4. GraphQL Tools alongside T-01–T-29 and P-01–P-08 | ✓ |
| New scripts/run_graphql_uat.py | Separate file with own MCPClient/TestRunner | |
| Split: smoke test in test_mcp_simple.py, rest in run_mcp_uat.py | P-09 smoke + T-37+ full suite | |

**User's choice:** Add to run_mcp_uat.py (recommended)
**Notes:** Single command runs all UAT. Consistent with existing structure.

---

## SKILL.md — how to document GraphQL tools

| Option | Description | Selected |
|--------|-------------|----------|
| Tool signatures + 2 example queries (recommended) | Both tool signatures, result shape, 2 example queries | ✓ |
| Tool signatures + 2 examples + workflows | Above + integration into investigation workflows | |
| Tool signatures + 2 examples + troubleshooting | Above + common error patterns and troubleshooting | |

**User's choice:** Tool signatures + 2 example queries (recommended)
**Notes:** Minimum viable documentation per GQL-20 requirement.

---

## Claude's Discretion

- Exact test function names and Nautobot GraphQL query fixtures
- T-40 auth test handling when no anonymous write token available (follow T-27 pattern)
- SKILL.md section placement and exact example queries

---

## Deferred Ideas

None
