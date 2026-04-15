# Phase 15: Introspection & Permissions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 15-introspection-permissions
**Areas discussed:** Return format, Auth policy, Permission tests, SDL validation

---

## Return Format

| Option | Description | Selected |
|--------|-------------|----------|
| Plain string | Raw SDL text — `type Query { ... }` | ✓ |
| Dict {sdl: string} | Matches graphql_query response shape | |
| Dict {schema: string, errors: list} | Both SDL and errors in one structure | |

**User's choice:** Plain string
**Notes:** Matches GraphQL spec convention. Simple. AI agents parse it directly.

---

## Auth Policy

| Option | Description | Selected |
|--------|-------------|----------|
| Require auth | Consistent with all other MCP tools; prevents schema exposure | ✓ |
| Allow anonymous | GraphQL spec standard; GitHub/Shopify allow it | |

**User's choice:** Require auth
**Notes:** Consistent with graphql_query and all other MCP tools. Prevents internal schema exposure.

---

## Permission Test Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Integration tests (real DB) | Simulate anonymous vs permitted user against actual DB | |
| Mock-based unit tests | Fast, isolated, follows Phase 14 pattern | ✓ |

**User's choice:** Mock-based unit tests
**Notes:** Follow Phase 14 pattern. Fast and isolated.

---

## Permission Test Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Anonymous vs permitted user | Verify anonymous gets empty, permitted gets non-empty | ✓ |
| Auth propagation only | Just verify user is passed through to execute_query | |

**User's choice:** Anonymous vs permitted user
**Notes:** Explicitly verify permission filtering behavior, not just user pass-through.

---

## SDL Validation Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Keyword presence checks | assertIn('type Query', sdl) | |
| Pattern/regex checks | regex 'type Query\s*\{' | |
| Parse + validate AST | graphql_core.build_schema(sdl) — raises on error | ✓ |

**User's choice:** Parse + validate AST
**Notes:** Most robust. Catches syntax errors explicitly.

---

## SDL Parse Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Parse only (exception on error) | build_schema raises GraphQLError on malformed SDL | ✓ |
| Parse + type name checks | Parse + assert key types present | |
| Parse + introspection query | Execute introspection query against parsed schema | |

**User's choice:** Parse only
**Notes:** Simple pass/fail — test passes if build_schema executes without raising.

---

## Deferred Ideas

None — discussion stayed within phase scope.

