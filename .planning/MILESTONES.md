# Milestones

## v2.0 GraphQL MCP Tool (Shipped: 2026-04-16)

**Phases completed:** 5 phases, 6 plans, 10 tasks

**Key accomplishments:**

- Confirmed: All 10 core read tools correctly use `async def` + `sync_to_async(thread_sensitive=True)` pattern
- GraphQL MCP tool scaffold with `graphql_query` handler wrapping `nautobot.core.graphql.execute_query()`, 5 unit tests, and side-effect registration
- GraphQL introspection MCP tool added: returns Nautobot schema as SDL string, auth-gated via ValueError
- GQL-13 permission enforcement tests: AnonymousUser → empty/error, AuthenticatedUser → non-empty data via mock patches of nautobot.core.graphql.execute_query
- Verified graphql_introspect unit tests; removed duplicate class from bad merge
- New file: `graphql_validation.py`
- Phase:

---

## v1.2.0 Separate Process Refactor (Shipped: 2026-04-07)

**Phases completed:** 7 phases (7–13), 27 requirements, all complete

**Key accomplishments:**

- Migrated MCP server from embedded Django process (Option A) to standalone FastMCP process (Option B) via Django management commands
- `start_mcp_server.py` (production) + `start_mcp_dev_server.py` (development) as canonical entry points
- `tool_registry.json` replaces `post_migrate` signal for cross-process plugin discovery
- All 10 core tools refactored to `async def` + `sync_to_async(thread_sensitive=True)` ORM wrappers
- Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` (no monkey-patching)
- Auth refactored: token from FastMCP headers, cached via `ctx.set_state("mcp:cached_user")`
- Embedded architecture deleted: `view.py`, `server.py`, `urls.py` removed; old endpoint returns 404
- UAT: 37/37 tests pass; unit tests: 91/91 pass (89 pass, 2 skipped)
- Fixed FastMCP/MCP SDK outputSchema conflict with `output_schema=None` in source (not in-container patch)

---
