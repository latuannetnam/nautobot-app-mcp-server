# Phase 14: GraphQL Tool Scaffold - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Create `graphql_query` MCP tool wrapping `nautobot.core.graphql.execute_query()` with unit tests. Covers GQL-01 to GQL-07 (tool implementation) and GQL-14 to GQL-17 (unit tests). Depth/complexity limits (GQL-10, GQL-11) and `graphql_introspect` (GQL-08, GQL-09) are deferred to Phases 15 and 16.

</domain>

<decisions>
## Implementation Decisions

### Tool function signature
- **D-01:** `graphql_query(query: str, variables: dict | None = None) -> dict`
- Accepts `query: str` and optional `variables: dict | None`; no operation_name parameter in this phase
- Return type is `dict` — FastMCP auto-derives schema from type hints via `@register_tool`
- `output_schema=None` on the `@register_tool` / `@mcp.tool()` decorator (same as all existing tools)

### Async/sync boundary
- **D-02:** Tool function is `async def` with a single `sync_to_async(..., thread_sensitive=True)` wrapping the entire `execute_query()` call at the outer boundary
- Do NOT add per-resolver sync guards — one wrapper at the tool entry point
- Auth resolved once before the `sync_to_async` call

### Auth integration
- **D-03:** Reuse `get_user_from_request(ctx)` from `nautobot_app_mcp_server.mcp.auth` — resolves token → User before the `sync_to_async` call
- Pass `user` as the named argument to `execute_query(query, variables, user=user)`
- Do NOT construct a Django `Request` manually — `execute_query` handles `request.user = user` internally when no request is passed

### Return shape
- **D-04:** Return `ExecutionResult.formatted` directly — a dict with `{"data": ..., "errors": [...]}` (both always present, errors may be null)
- Do NOT filter, reformat, or strip any fields from the error response
- AI agents receive full GraphQL error messages including field names, line numbers, and paths via `ExecutionResult.formatted`

### File layout
- **D-05:** Create `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — contains `graphql_query` async handler only
- Add `graphql_tool` side-effect import in `nautobot_app_mcp_server/mcp/tools/__init__.py` (same pattern as `core.py`)
- No changes to `commands.py`, `registry.py`, or any existing files except `tools/__init__.py`

### Unit tests (`test_graphql_tool.py`)
- **D-06:** 4 test cases: auth propagation, valid query, invalid query, variables injection
- Use Nautobot's `create_test_user()` for test fixtures (same pattern as `test_auth.py`)
- Mock or patch `nautobot.core.graphql.execute_query` as needed to isolate unit tests from DB
- Run via `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool`

### Error handling (no-throw boundary)
- **D-07:** `graphql_query` must never raise an unhandled exception to FastMCP
- `execute_query` raises on null user — guard with try/except at the tool boundary; return `{"data": None, "errors": [{"message": "Authentication required"}]}` on failure
- All GraphQL errors (syntax, validation, runtime) are returned in the `errors` array via `ExecutionResult.formatted`

### Claude's Discretion
- Exact test class/method names — follow project conventions (`TestXxx` class, `test_xxx` methods)
- Whether to patch `execute_query` or use integration-style testing in unit tests
- Placement of the error boundary try/except (inline in handler vs a wrapper function)
- Whether to add type annotations for the error dict structure

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### GraphQL execution
- `.venv/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py` — `execute_query(query, variables, user)` function signature and behavior; creates a Django Request and sets `request.user = user` internally
- `.venv/lib/python3.12/site-packages/nautobot/dcim/tests/test_graphql.py` — Nautobot's own GraphQL test patterns; `execute_query` returns `ExecutionResult` with `.formatted` property

### Auth
- `nautobot_app_mcp_server/mcp/auth.py` — `get_user_from_request(ctx)`; use as-is for Phase 14 auth resolution

### Existing tool patterns
- `nautobot_app_mcp_server/mcp/tools/core.py` — all 10 existing async tool handlers; `async def` + `sync_to_async(thread_sensitive=True)` at outer boundary; `output_schema=None` on decorator
- `nautobot_app_mcp_server/mcp/tools/__init__.py` — side-effect import pattern for tool registration
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — `create_test_user()` fixture usage

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` §v2 Requirements — GQL-01 through GQL-17 trace matrix
- `.planning/ROADMAP.md` §Phase 14 — goal, success criteria, and plan table
- `.planning/research/SUMMARY.md` — full stack analysis, pitfalls P1–P12, build order

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- `get_user_from_request(ctx)` in `auth.py` — direct reuse, no modification needed
- `sync_to_async(..., thread_sensitive=True)` pattern from all `core.py` handlers
- `PaginatedResult` and pagination helpers in `tools/pagination.py`
- Nautobot test utilities: `create_test_user()` from `nautobot.core.testing`

### Established Patterns
- Async tool handlers: `async def _handler(ctx, ...) -> dict` with one `sync_to_async` wrapper
- Decorator pattern: `@register_tool(name=..., description=..., tier=..., scope=...)`
- Error handling: `ValueError` raised for not-found cases; MCP tool error responses handled by FastMCP
- Side-effect imports in `tools/__init__.py` trigger registration at import time

### Integration Points
- `mcp/tools/__init__.py` — add `graphql_tool` side-effect import to register the tool
- FastMCP `ctx.get_state` / `ctx.set_state` already wired for session auth in `auth.py`
- Docker Compose service already exposes port 8005 — no network changes needed

</codebase_context>

<specifics>
## Specific Ideas

- Reuse `nautobot.core.graphql.execute_query` — do NOT build a parallel schema
- Depth ≤8 and complexity ≤1000 will be configured in Phase 16 (not in Phase 14 scope)
- `graphql_introspect` comes in Phase 15, not Phase 14
- No new poetry dependencies — all required packages (graphene-django, graphql-core) are already Nautobot transitive deps

</specifics>

<deferred>
## Deferred Ideas

- `graphql_introspect` companion tool — Phase 15
- Permission enforcement verification test — Phase 15 (GQL-13)
- Query depth limit (max_depth ≤ 8) — Phase 16 (GQL-10)
- Query complexity limit (max_complexity ≤ 1000) — Phase 16 (GQL-11)
- GraphQL syntax errors → HTTP 500 fix — Phase 16 (GQL-12)
- UAT smoke test P-09 — Phase 17 (GQL-18)
- UAT full suite T-37+ — Phase 17 (GQL-19)
- SKILL.md update — Phase 17 (GQL-20)

</deferred>

---

*Phase: 14-graphql-tool-scaffold*
*Context gathered: 2026-04-15*
