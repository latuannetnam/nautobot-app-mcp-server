# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v2.0 — GraphQL MCP Tool

**Shipped:** 2026-04-16
**Phases:** 4 | **Plans:** 17 | **Sessions:** ~4

### What Was Built
- `graphql_query` MCP tool: arbitrary GraphQL queries via `nautobot.core.graphql.execute_query()`, with depth ≤8 and complexity ≤1000
- `graphql_introspect` MCP tool: returns Nautobot schema as SDL string for AI agent schema discovery
- `graphql_validation.py`: `MaxDepthRule` and `QueryComplexityRule` (graphql-core `ValidationRule` subclasses)
- Structured error handling: all GraphQL errors return HTTP 200 with `{"data": null, "errors": [...]}` — no unhandled exceptions
- UAT suite: 44/44 tests passed | Unit tests: 103/103 passed
- SKILL.md updated with `graphql_query` and `graphql_introspect` documentation

### What Worked
- Reusing `nautobot.core.graphql.execute_query()` avoided building a parallel schema and preserved all Nautobot dynamic fields (`extend_schema_type`)
- Per-plan summary files (15.1/15.2/15.3) kept each sub-plan self-contained and reviewable independently
- Mock patching at the source module (`nautobot.core.graphql.execute_query`) worked cleanly for lazy-imported functions
- Phase 17 code review: 10 findings (Critical ×1, High ×1, Medium ×2, Low ×6) all fixed in 2 commits before milestone close

### What Was Inefficient
- Phase 15 had a bad cherry-pick merge that duplicated `GraphQLIntrospectHandlerTestCase` — required manual cleanup with full file rewrite
- Phase 17 skipped phase directories archival (workflow step deferred) — tech debt carried forward to milestone close
- ROADMAP.md had unresolved merge conflict markers at milestone close — needed manual resolution before archiving
- T-06 cursor pagination duplicate bug (`.order_by("pk")` missing from all `build_*_qs()` functions) was a pre-existing bug discovered and fixed post-UAT-passing

### Patterns Established
- Lazy import pattern: `from nautobot.core.graphql import execute_query` inside function body avoids Django setup failures at module load time
- Async tool pattern: `async def handler` → `get_user_from_request()` → `sync_to_async(thread_sensitive=True)` → `_sync_*` helper
- Structured error dict pattern: `ValueError("Authentication required")` raised in async handler → FastMCP converts to tool error dict
- ValidationRule subclasses for graphql-core: `MaxDepthRule` and `QueryComplexityRule` run before `execute()` — no partial data leakage
- Per-plan summary files: each sub-plan gets its own SUMMARY.md, consolidated into phase SUMMARY at end

### Key Lessons
1. Always add `.order_by("pk")` (or any stable sort) to querysets used with cursor pagination — without it, `pk__gt` filtering is non-deterministic across page boundaries
2. Lazy imports for Django models/functions must patch at the source module, not the local namespace — patch target must match where the name is *defined*, not where it is *used*
3. Phase directories should be archived immediately after phase close, not deferred to milestone completion — reduces merge conflict surface and keeps milestone close clean
4. ROADMAP.md merge conflict markers indicate incomplete workflow state — resolve before running `milestone complete`

### Cost Observations
- Sessions: ~4 (planning/research ×2, execution ×2)
- Notable: v2.0 was a focused 4-phase feature addition (vs. v1.2.0's 7-phase architecture refactor) — smaller scope, faster completion

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~5 | 5 | MVP: 10 core read tools + auth + pagination |
| v1.1 | ~2 | 2 | Embedded FastMCP bridge refactor |
| v1.2 | ~6 | 7 | Separate process refactor (Option B), tool registry |
| v2.0 | ~4 | 4 | GraphQL MCP tools + validation + structured errors |

### Cumulative Quality

| Milestone | UAT | Unit Tests | Zero-Dep Additions |
|-----------|-----|------------|-------------------|
| v1.0 | 37/37 | ~80 | 10 tools (nautobot core only) |
| v1.1 | ~37 | ~80 | 3 session tools |
| v1.2 | 37/37 | 91/91 | full standalone architecture |
| v2.0 | 44/44 | 103/103 | 2 GraphQL tools + validation layer |

### Top Lessons (Verified Across Milestones)

1. `sync_to_async(..., thread_sensitive=True)` is mandatory for all ORM calls — skipping it causes "Connection not available" errors in FastMCP thread pool (confirmed across v1.2 and v2.0)
2. Cursor pagination requires explicit `.order_by()` on querysets — non-deterministic ordering causes duplicate/skip bugs (confirmed v1.0 → v2.0)
3. Structured errors > exceptions for API boundaries — both v1.2 (tool errors) and v2.0 (GraphQL errors) benefited from dict-based error returns
