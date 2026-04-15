# Phase 14: GraphQL Tool Scaffold - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 14-graphql-tool-scaffold
**Mode:** discuss
**Areas discussed:** Error handling approach

---

## Error Handling Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Pass through `ExecutionResult.formatted` directly | Return raw errors array from execute_query — no filtering, no reformatting. AI agents see full GraphQL error messages including field names, line numbers, and paths. Simplest implementation. | ✓ |
| Simplify errors — strip locations and extensions | Strip locations/extensions from errors to keep response minimal. Reduces token usage but loses debugging context AI agents might need. | |

**User's choice:** Pass through `ExecutionResult.formatted` directly

**Notes:** User selected the recommended option. Full error context (locations, paths, extensions) is preserved for AI agents doing GraphQL debugging.

---

## Assumptions (Not Discussed — Locked by Established Patterns)

The following implementation details were not discussed — they are locked by existing codebase patterns and research findings:

| Area | Decision | Source |
|------|----------|--------|
| Tool function signature | `async def graphql_query(query: str, variables: dict \| None = None) -> dict` | Established patterns from `core.py` |
| Async boundary | Single `sync_to_async(thread_sensitive=True)` at outer boundary | RESEARCH.md P1 prevention |
| Auth | `get_user_from_request(ctx)` + pass `user=user` to `execute_query` | RESEARCH.md P2 prevention |
| Decorator | `@register_tool` with `output_schema=None` | Existing `core.py` pattern |
| File layout | `graphql_tool.py` + side-effect import in `tools/__init__.py` | Existing `core.py` pattern |
| No-throw boundary | Never raise unhandled exception to FastMCP | RESEARCH.md P5 prevention |

---

## Claude's Discretion

The following are delegated to implementation-time judgment:

- Exact test class/method names — follow project conventions
- Whether to patch `execute_query` or use integration-style testing in unit tests
- Placement of the error boundary try/except (inline in handler vs a wrapper function)
- Whether to add type annotations for the error dict structure

## Deferred Ideas

No new ideas were raised during discussion — all scope creep was redirected appropriately.
