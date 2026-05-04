# Project Roadmap — `nautobot-app-mcp-server`

**Project:** Nautobot App MCP Server
**Horizon:** v2.1
**Last updated:** 2026-05-04 — v2.1 GraphQL-Only Mode started

---

## Milestones

- ✅ **v1.0 MVP** — Phases 0–4 (shipped 2026-04-02)
- ✅ **v1.1.0** — Phases 5–6 (shipped 2026-04-04)
- ✅ **v1.2.0** — Phases 7–13 (shipped 2026-04-07)
- ✅ **v2.0** — Phases 14–17 (shipped 2026-04-16)
- 🚀 **v2.1** — Phase 18 (in progress)

---

## Progress

| # | Phase | Milestone | Plans | Status | Completed |
|---|-------|-----------|-------|--------|-----------|
| 0 | Project Setup | v1.0 | 4/4 | Complete | 2026-04-01 |
| 1 | MCP Server Infrastructure | v1.0 | 11/11 | Complete | 2026-04-01 |
| 2 | Auth & Sessions | v1.0 | 7/7 | Complete | 2026-04-01 |
| 3 | Core Read Tools | v1.0 | 3/3 | Complete | 2026-04-02 |
| 4 | SKILL.md Package | v1.0 | 3/3 | Complete | 2026-04-02 |
| 5 | MCP Server Refactor | v1.1.0 | 7/7 | Complete | 2026-04-04 |
| 6 | UAT & Smoke Tests | v1.1.0 | 1/1 | Complete | 2026-04-04 |
| 7 | Setup | v1.2.0 | 3/3 | Complete | 2026-04-05 |
| 8 | Infrastructure | v1.2.0 | 4/4 | Complete | 2026-04-05 |
| 9 | Tool Registration | v1.2.0 | 6/6 | Complete | 2026-04-05 |
| 10 | Session State | v1.2.0 | 4/4 | Complete | 2026-04-05 |
| 11 | Auth Refactor | v1.2.0 | 2/2 | Complete | 2026-04-06 |
| 12 | Bridge Cleanup | v1.2.0 | 6/6 | Complete | 2026-04-06 |
| 13 | UAT & Validation | v1.2.0 | 5/5 | Complete | 2026-04-07 |
| 14 | GraphQL Tool Scaffold | v2.0 | 6/6 | Complete | 2026-04-15 |
| 15 | Introspection & Permissions | v2.0 | 3/3 | Complete | 2026-04-15 |
| 16 | Security Hardening | v2.0 | 4/4 | Complete | 2026-04-16 |
| 17 | UAT & Documentation | v2.0 | 4/4 | Complete | 2026-04-16 |
| 18 | GraphQL-Only Mode | v2.1 | 5/5 | Pending | — |

---

## v1.2.0 Archived

<details>
<summary>✅ v1.2.0 — Separate Process Refactor (SHIPPED 2026-04-07)</summary>

**Goal:** Migrate MCP server from embedded (Option A) to standalone (Option B).

**What shipped:**
- `start_mcp_server.py` + `start_mcp_dev_server.py` management commands
- FastMCP runs as standalone process on port 8005; `invoke start` launches it automatically
- `tool_registry.json` for cross-process plugin discovery
- All 10 core tools async + `sync_to_async(thread_sensitive=True)`
- Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` (no monkey-patching)
- Auth: token from FastMCP headers, cached via `ctx.set_state("mcp:cached_user")`
- Embedded architecture deleted: `view.py`, `server.py`, `urls.py` removed
- UAT: 37/37 passed | Unit tests: 91/91 passed (89 pass, 2 skipped)
- FastMCP/MCP SDK `outputSchema` conflict fixed via `output_schema=None` in source

**Phase details:** `.planning/milestones/v1.2.0-ROADMAP.md`
**Requirements:** `.planning/milestones/v1.2.0-REQUIREMENTS.md`

</details>

---

## v2.0 Archived

<details>
<summary>✅ v2.0 — GraphQL MCP Tool (SHIPPED 2026-04-16)</summary>

**Goal:** Add `graphql_query` and `graphql_introspect` MCP tools wrapping `nautobot.core.graphql.execute_query()` for arbitrary GraphQL queries against Nautobot with permission enforcement, depth/complexity limits, and structured error handling.

**What shipped:**

- `graphql_query` MCP tool: async handler → auth guard → parse → validate (depth ≤8, complexity ≤1000) → execute
- `graphql_introspect` MCP tool: returns Nautobot schema as SDL string, auth-gated
- `graphql_validation.py`: `MaxDepthRule` and `QueryComplexityRule` (graphql-core `ValidationRule` subclasses)
- Structured errors: syntax errors and auth failures return `{"data": null, "errors": [...]}` (HTTP 200, not 500)
- UAT: 44/44 passed (T-06 cursor pagination fixed post-ship)
- SKILL.md updated with `graphql_query` and `graphql_introspect` documentation
- 15 unit tests in `test_graphql_tool.py` (all passing)
- No new poetry dependencies — all from Nautobot transitive deps

**Key decisions:**

- Reuse `nautobot.core.graphql.execute_query()` — stable since Nautobot 1.x; handles permissions internally
- Reuse `nautobot.core.graphql.schema` — parallel schema misses `extend_schema_type` custom fields
- Structured errors, not HTTP 500s — syntax errors never throw unhandled exceptions

**Phase details:** `.planning/milestones/v2.0-ROADMAP.md`
**Requirements:** `.planning/milestones/v2.0-REQUIREMENTS.md`

</details>

---

## v2.1 — GraphQL-Only Mode

**Status:** In progress (Phase 18)

### Phase 18: GraphQL-Only Mode

**Goal:** Implement `NAUTOBOT_MCP_GRAPHQL_ONLY` env var that restricts the MCP server to exposing only `graphql_query` and `graphql_introspect`.

**Requirements:** GQLONLY-01, GQLONLY-02, GQLONLY-03, GQLONLY-04, GQLONLY-05, GQLONLY-06

**Plans:** 5 plans

Plans:
- [ ] 18-01-PLAN.md — Add GRAPHQL_ONLY_MODE constant + ALLOWED_GQL_ONLY_TOOLS tuple to commands.py
- [ ] 18-02-PLAN.md — Implement two-layer enforcement in session_tools.py and middleware.py
- [ ] 18-03-PLAN.md — Create unit tests for GQLONLY-01 through GQLONLY-05
- [ ] 18-04-PLAN.md — Add UAT tests T-45, T-46, T-47 with auto-detection
- [ ] 18-05-PLAN.md — Document NAUTOBOT_MCP_GRAPHQL_ONLY in CLAUDE.md and SKILL.md

**Success criteria:**

1. `NAUTOBOT_MCP_GRAPHQL_ONLY=true` env var can be set and is read at server startup in `commands.py` / `create_app()`
2. When the flag is active, `_list_tools_handler` returns exactly `graphql_query` and `graphql_introspect` — verified by calling `tools/list` with the flag set
3. When the flag is active, calling any non-GraphQL tool (e.g. `device_list`) raises a `ToolNotFoundError` — verified by unit test of `ScopeGuardMiddleware`
4. Without the env var, all 15 tools appear in the tool list (existing behavior unchanged)
5. Unit tests for GQLONLY-02, GQLONLY-03, GQLONLY-04 pass (`invoke unittest`)
6. `NAUTOBOT_MCP_GRAPHQL_ONLY` appears in CLAUDE.md (Environment or Gotchas section) and SKILL.md

---

## v3.0 — Future Planning

**Status:** Not started

Candidate features for next milestone:

- Write tools (create/update/delete) — requires permission modeling and transactional safety
- Redis session backend for `--workers > 1` horizontal scaling
- Tool-level field permissions
- Dry-run / validation mode for GraphQL queries
- Query result caching (TTL cache keyed on `user_pk + query_hash`)

---

*Roadmap last updated: 2026-05-04 — v2.1 GraphQL-Only Mode started*
*Archived milestones: `.planning/milestones/`*
