# Phase 15: Introspection & Permissions - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Add `graphql_introspect` MCP tool returning GraphQL SDL string, and verify permission enforcement for GraphQL queries (GQL-08, GQL-09, GQL-13). Covers:
- New `graphql_introspect` async tool handler
- Unit test for `graphql_introspect` returning valid SDL
- Permission enforcement verification (anonymous → empty, authed → filtered)

GQL-10/GQL-11 (depth/complexity limits) deferred to Phase 16. GQL-18/GQL-19 (UAT tests) deferred to Phase 17.

</domain>

<decisions>
## Implementation Decisions

### Introspection return format
- **D-01:** `graphql_introspect` returns a plain `str` — the raw SDL text, not a dict envelope
- Do NOT wrap in `{sdl: ...}` or `{schema: ..., errors: ...}` — plain string matches the GraphQL spec convention for schema introspection responses

### Introspection auth policy
- **D-02:** `graphql_introspect` requires auth — same token requirement as `graphql_query`
- Auth resolved via `get_user_from_request(ctx)` before the `sync_to_async` boundary
- Anonymous callers receive an error response (structured dict), not the SDL
- This is consistent with all other MCP tools and prevents internal schema exposure

### Permission enforcement strategy
- **D-03:** Unit tests verify that `AnonymousUser` gets empty results and an authenticated user with view permissions gets non-empty results
- Use two test fixtures: one `AnonymousUser`, one user with real or mocked view permissions
- Verify `execute_query` is called with the correct user for each case
- Do NOT just verify user is passed through — explicitly verify the permission filtering behavior

### Permission test style
- **D-04:** Mock-based unit tests (not integration tests)
- Follow Phase 14 pattern: mock or patch `execute_query` to isolate the permission integration logic
- Use `create_test_user()` fixture pattern from `test_auth.py`
- Run via `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool`

### SDL validation approach
- **D-05:** Use `graphql_core.parse()` (from `graphql-core`) to parse the SDL string — raises `GraphQLError` on malformed SDL
- Test passes if `build_schema(sdl)` executes without raising an exception
- Result must be a valid GraphQL schema with `Query` type present
- Do NOT use keyword presence checks (`assertIn`) — parse-only validation is more robust and explicit

### File layout
- **D-06:** `graphql_introspect` goes in the same `graphql_tool.py` file as `graphql_query`
- No new file needed — add the handler to the existing module
- `graphql_tool` side-effect import already exists in `tools/__init__.py` — no changes needed there

### Error handling boundary
- **D-07:** Auth failure returns `{"error": "Authentication required"}` as a plain dict
- Since the return type is `str` (not `dict`), error responses may be wrapped in a different structure or handled via an exception raised to FastMCP
- Decision needed during implementation: should auth failure return an error dict (string) or raise a `ValueError` that FastMCP handles as a tool error?

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### GraphQL implementation
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — Phase 14 `graphql_query` handler to model `graphql_introspect` after
- `nautobot_app_mcp_server/mcp/auth.py` — `get_user_from_request(ctx)` for auth resolution pattern
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — Phase 14 test patterns, `_create_token` helper

### Auth and permissions
- `nautobot_app_mcp_server/mcp/auth.py` — `AnonymousUser` fallback behavior; auth token resolution
- `nautobot_app_mcp_server/mcp/tools/core.py` — existing async tool patterns with `sync_to_async(thread_sensitive=True)`

### Requirements and roadmap
- `.planning/REQUIREMENTS.md` §v2.0 Requirements — GQL-08, GQL-09, GQL-13 trace matrix
- `.planning/ROADMAP.md` §Phase 15 — goal, success criteria, and plan table
- `.planning/phases/14-graphql-tool-scaffold/14-CONTEXT.md` — prior decisions that constrain this phase (auth pattern, async boundary, file layout)

### Phase 14 context (prior)
- `.planning/phases/14-graphql-tool-scaffold/14-CONTEXT.md` — D-01 through D-07 from Phase 14 apply: async boundary, auth integration, return shape, file layout, unit test patterns, error handling

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- `get_user_from_request(ctx)` in `auth.py` — direct reuse for `graphql_introspect` auth
- `_create_token()` in `test_graphql_tool.py` — bypasses ORM side effects for test token creation
- `sync_to_async(..., thread_sensitive=True)` pattern — same as `graphql_query`

### Established Patterns
- Async tool handlers: `async def _handler(ctx, ...) -> return_type` with one `sync_to_async` wrapper
- Decorator: `@register_tool(name=..., description=..., tier=..., scope=...)`
- Side-effect imports in `tools/__init__.py` already cover `graphql_tool` — no registration changes needed
- Error handling: `ValueError` raised for not-found cases; MCP tool error responses handled by FastMCP

### Integration Points
- `graphql_tool.py` — add `graphql_introspect` handler alongside existing `graphql_query`
- `tools/__init__.py` — `graphql_tool` already registered, no changes needed
- `test_graphql_tool.py` — add new test class for `graphql_introspect` and permission tests

</codebase_context>

<specifics>
## Specific Ideas

- `graphql_introspect` should feel like the introspection endpoint of GitHub's or Shopify's GraphQL API — discoverable, but requires auth
- Anonymous schema exposure is not desired — Nautobot's schema may reveal internal model details
- SDL parse validation catches the "tool registered but returns garbage" failure mode

</specifics>

<deferred>
## Deferred Ideas

- Depth limit (max_depth ≤ 8) — Phase 16 (GQL-10)
- Complexity limit (max_complexity ≤ 1000) — Phase 16 (GQL-11)
- GraphQL syntax errors → HTTP 500 fix — Phase 16 (GQL-12)
- UAT smoke test P-09 — Phase 17 (GQL-18)
- UAT full suite T-37+ — Phase 17 (GQL-19)
- SKILL.md update — Phase 17 (GQL-20)

</deferred>

---

*Phase: 15-introspection-permissions*
*Context gathered: 2026-04-15*
