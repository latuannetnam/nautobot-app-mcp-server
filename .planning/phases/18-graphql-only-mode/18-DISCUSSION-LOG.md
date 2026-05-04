# Phase 18: GraphQL-Only Mode - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-04
**Phase:** 18-graphql-only-mode
**Areas discussed:** Enforcement architecture, UAT coverage, CLAUDE.md / SKILL.md doc scope, Session tools visibility

---

## Enforcement Architecture

### Q1: Error type for blocked calls

| Option | Description | Selected |
|--------|-------------|----------|
| ToolNotFoundError (reuse existing) | Reuse existing exception from middleware.py with a GQL-only specific message | ✓ |
| New GqlOnlyModeError exception | Distinct exception for easier grep/test | |
| You decide | Claude's discretion | |

**User's choice:** ToolNotFoundError (reuse existing)
**Notes:** Consistent with existing blocked-call behavior in ScopeGuardMiddleware.

---

### Q2: Which layer owns enforcement

| Option | Description | Selected |
|--------|-------------|----------|
| Both layers (Recommended) | _list_tools_handler filters manifest + ScopeGuardMiddleware blocks calls | ✓ |
| Middleware only | Blocks calls but tools still appear in manifest | |
| list_tools_handler only | Hides tools but no call-time enforcement | |

**User's choice:** Both layers
**Notes:** Belt-and-suspenders; satisfies GQLONLY-02 (manifest) and GQLONLY-03 (call-time) separately.

---

### Q3: How flag is passed to enforcement layers

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level constant (Recommended) | create_app() sets a module-level bool; both layers import it | ✓ |
| Pass as arg to middleware constructor | ScopeGuardMiddleware(graphql_only=True) | |
| Re-read env var at call time | os.environ checked on every tool call | |

**User's choice:** Module-level constant
**Notes:** Simple, no threading concerns at startup. Both _list_tools_handler and ScopeGuardMiddleware import the same constant.

---

## UAT Coverage

### Q1: Test IDs

| Option | Description | Selected |
|--------|-------------|----------|
| T-45 through T-47 (Recommended) | 3 tests covering GQLONLY-02, GQLONLY-03, GQLONLY-04 | ✓ |
| T-45 through T-48 | 4 tests, separate test for session tools | |
| You decide | Claude's discretion | |

**User's choice:** T-45–T-47

---

### Q2: Where tests live

| Option | Description | Selected |
|--------|-------------|----------|
| New section in run_mcp_uat.py (Recommended) | ### 5. GraphQL-Only Mode section | ✓ |
| New standalone UAT script | scripts/test_mcp_gql_only.py | |
| You decide | Claude's discretion | |

**User's choice:** run_mcp_uat.py — with additional requirement: auto-detect server mode and modify existing tests if GQL-only mode breaks them.
**Notes:** User explicitly asked to check whether GQL-only mode breaks T-01–T-44. Resolution: auto-detect at script startup and skip T-01–T-44 in GQL-only mode rather than modifying them.

---

### Q3: Handling env var at UAT script level

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-detect server mode at start (Recommended) | Call tools/list first; branch based on tool count | ✓ |
| --gql-only flag to UAT script | Explicit mode selection via CLI arg | |
| Separate UAT script for GQL-only mode | Complete isolation | |

**User's choice:** Auto-detect
**Notes:** Self-adapting, no flags to remember. Prints mode banner so test output is self-explanatory.

---

## CLAUDE.md / SKILL.md Doc Scope

### Q1: Where in CLAUDE.md

| Option | Description | Selected |
|--------|-------------|----------|
| Gotchas table (Recommended) | One row: Issue + Fix | ✓ |
| Environment Setup section | Near NAUTOBOT_CONFIG | |
| Both Gotchas and Env Setup | Document in both places | |

**User's choice:** Gotchas table

---

### Q2: What SKILL.md includes

| Option | Description | Selected |
|--------|-------------|----------|
| Env var + behavior summary (Recommended) | Short section: env var, what it does, how to enable | ✓ |
| Full section with example workflow | Includes AI agent usage example | |
| You decide | Claude's discretion | |

**User's choice:** Env var + behavior summary

---

## Session Tools Visibility

### Q1: Should mcp_enable_tools / mcp_disable_tools / mcp_list_tools be visible in GQL-only mode?

| Option | Description | Selected |
|--------|-------------|----------|
| Hide them too (Recommended) | Manifest shows exactly 2 tools; scope management irrelevant | ✓ |
| Keep them visible | Simpler implementation; confusing UX | |
| You decide | Claude's discretion | |

**User's choice:** Hide them too
**Notes:** In GQL-only mode, there are no non-GraphQL tools to enable/disable. Showing session tools would confuse AI agents.

---

### Q2: What happens if session tools are called despite being hidden?

| Option | Description | Selected |
|--------|-------------|----------|
| ToolNotFoundError same as other blocked tools | Consistent, uniform behavior | ✓ |
| Silently succeed (no-op) | Returns a message instead of raising | |
| You decide | Claude's discretion | |

**User's choice:** ToolNotFoundError — uniform with all other blocked calls

---

## Claude's Discretion

- Exact module/location for `GRAPHQL_ONLY_MODE` constant
- Constant name
- Exact error message string in `ToolNotFoundError`
- Unit test naming conventions

## Deferred Ideas

None — discussion stayed within phase scope.
