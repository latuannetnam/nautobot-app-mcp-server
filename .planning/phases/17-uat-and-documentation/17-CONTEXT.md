# Phase 17: UAT & Documentation - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Add smoke test P-09, full UAT suite T-37–T-43, and update SKILL.md with `graphql_query` and `graphql_introspect` documentation. All 7 UAT tests must pass. `invoke tests` must exit with code 0.

</domain>

<decisions>
## Implementation Decisions

### Smoke test (P-09) — scope
- **D-01:** P-09 verifies a valid GraphQL query returns data (not errors) from `graphql_query`
- Follows the same pattern as P-01–P-08: single assertion, timed, passes/fails cleanly
- Adds `graphql_query` to `scripts/test_mcp_simple.py`
- No auth check in smoke test (auth tested in T-40)

### UAT suite (T-37 to T-43) — scope
- **D-02:** 7 UAT tests added to `scripts/run_mcp_uat.py`:
  - T-37: Valid `graphql_query` returns data with no errors
  - T-38: Invalid/syntax-error query returns `errors` dict (no HTTP 500)
  - T-39: `graphql_introspect` returns valid SDL schema string
  - T-40: Permission enforcement — auth propagation (anonymous token → empty/restricted data)
  - T-41: Query variables injection via `variables` parameter
  - T-42: Auth token propagation (valid token → full data access)
  - T-43: Depth/complexity limit enforcement (queries that exceed limits return errors dict)
- Tests added to a new `### 4. GraphQL Tools` section in `run_mcp_uat.py`

### Test organization
- **D-03:** All GraphQL tests live in `scripts/run_mcp_uat.py` (new section `### 4. GraphQL Tools`)
- P-09 in `scripts/test_mcp_simple.py` (standalone smoke)
- T-37–T-43 in `scripts/run_mcp_uat.py` (full UAT suite alongside existing T-01–T-29 and P-01–P-08)
- New test category label: `"GraphQL Tools": ["T-37", "T-38", "T-39", "T-40", "T-41", "T-42", "T-43"]`

### SKILL.md documentation
- **D-04:** SKILL.md updated with `graphql_query` and `graphql_introspect` tool signatures
- Documents result shape: `{data: ..., errors: [...]}` (both always present; errors may be null)
- Includes ≥2 example GraphQL queries:
  1. Simple device list query
  2. Query with variables injection
- Minimum viable documentation per GQL-20 requirement

### Claude's Discretion
- Exact test function names — follow existing conventions (`t37()`, `t38()`, etc.)
- Specific Nautobot GraphQL queries used in test fixtures (query a device field or similar)
- How to handle T-40 auth test when no anonymous write token is available (follow T-27 pattern)
- SKILL.md placement (before or after existing tool sections)
- Whether T-43 tests the depth limit (≤8) or complexity limit (≤1000) or both

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase context (GraphQL tools)
- `.planning/phases/14-graphql-tool-scaffold/14-CONTEXT.md` — `graphql_query` tool signature, async/sync boundary, auth integration, return shape decisions
- `.planning/phases/15-introspection-permissions/15-CONTEXT.md` — `graphql_introspect` tool decisions
- `.planning/phases/16-security-hardening/16-PLAN.md` — depth ≤8, complexity ≤1000 limits; parse-then-execute pattern

### Test patterns
- `scripts/run_mcp_uat.py` — existing T/P test patterns, `MCPClient`, `MCPToolError`, `TestRunner`, `TestResult` classes; T-27/T-29 auth test pattern
- `scripts/test_mcp_simple.py` — P-01 through P-08 smoke test patterns; `MCPClient` implementation

### Requirements
- `.planning/REQUIREMENTS.md` §v2 Requirements — GQL-18, GQL-19, GQL-20

### Documentation
- `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — existing SKILL.md structure; where GraphQL tools fit in the tool table and workflows

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `MCPClient`, `MCPToolError`, `TestRunner`, `TestResult` in `run_mcp_uat.py` — all reused for T-37–T-43
- `MCPClient` in `test_mcp_simple.py` — reused for P-09
- `TestRunner.test(name, fn)` pattern — consistent with all existing tests
- T-27 auth test pattern for T-40 (anonymous client, empty result assertion)

### Established Patterns
- Test naming: `def t37():` → `runner.test("T-37 ...", t37)`
- Categories dict in `summary()` maps test IDs to groups
- SKILL.md tool table: `| tool | description | parameters | paginated |`
- SKILL.md tool signatures include parameter types and defaults

### Integration Points
- `scripts/run_mcp_uat.py` — add new `### 4. GraphQL Tools` section between existing sections and the final `summary()` block
- `scripts/test_mcp_simple.py` — add P-09 after existing smoke tests
- `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — add `graphql_query` and `graphql_introspect` to the tool table, add example queries section

</code_context>

<specifics>
## Specific Ideas

- P-09 should follow the same minimal smoke pattern as P-01–P-08 (single assertion, timed)
- SKILL.md example queries: `query { devices { name status } }` and a variables example
- T-43 should test that depth/complexity limits return structured errors (not HTTP 500) — consistent with Phase 16 GQL-12 behavior

</specifics>

<deferred>
## Deferred Ideas

None — all 4 areas discussed and resolved.

### Reviewed Todos (not folded)
None

</deferred>

---

*Phase: 17-uat-and-documentation*
*Context gathered: 2026-04-16*
