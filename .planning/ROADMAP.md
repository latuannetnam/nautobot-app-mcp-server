# Project Roadmap — `nautobot-app-mcp-server`

**Project:** Nautobot App MCP Server
**Horizon:** v2.0
**Last updated:** 2026-04-15 — v2.0 GraphQL MCP Tool roadmap created

---

## Milestones

- ✅ **v1.0 MVP** — Phases 0–4 (shipped 2026-04-02)
- ✅ **v1.1.0** — Phases 5–6 (shipped 2026-04-04)
- ✅ **v1.2.0** — Phases 7–13 (shipped 2026-04-07)
- 📋 **v2.0** — Phases 14–17 (planned 2026-04-15)

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
<<<<<<< Updated upstream
| 9 | Tool Registration | v1.2.0 | 6/6 | Complete | 2026-04-05 |
| 10 | Session State | v1.2.0 | 4/4 | Complete | 2026-04-05 |
| 11 | Auth Refactor | v1.2.0 | 2/2 | Complete | 2026-04-06 |
| 12 | Bridge Cleanup | v1.2.0 | 6/6 | Complete | 2026-04-06 |
| 13 | UAT & Validation | v1.2.0 | 5/5 | Complete | 2026-04-07 |
| 14 | GraphQL Tool Scaffold | v2.0 | 5/5 | Planned | — |
| 15 | Introspection & Permissions | v2.0 | 3/3 | Planned | — |
| 16 | Security Hardening | v2.0 | 4/4 | Planned | — |
| 17 | UAT & Documentation | v2.0 | 3/3 | Planned | — |
=======
| 9 | Tool Registration | v1.2.0 | 4/6 | In Progress | — |
| 10 | Session State | v1.2.0 | 0/4 | Not started | — |
| 11 | Auth Refactor | v1.2.0 | 0/4 | Not started | — |
| 12 | Bridge Cleanup | v1.2.0 | 0/6 | Not started | — |
| 13 | UAT & Validation | v1.2.0 | 0/5 | Not started | — |
>>>>>>> Stashed changes

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
- FastMCP/MCP SDK outputSchema conflict fixed via `output_schema=None` in source

**Phase details:** `.planning/milestones/v1.2.0-ROADMAP.md`
**Requirements:** `.planning/milestones/v1.2.0-REQUIREMENTS.md`

</details>

---

## v2.0 — GraphQL MCP Tool

**Status:** Planned — roadmap created 2026-04-15
**Goal:** Add `graphql_query` and `graphql_introspect` MCP tools wrapping `nautobot.core.graphql.execute_query()` so AI agents can execute arbitrary GraphQL queries against Nautobot with full permission enforcement, depth/complexity limits, and structured error handling.

**Key decisions:**

| Decision | Rationale |
|----------|-----------|
| Reuse `nautobot.core.graphql.execute_query()` | Stable since Nautobot 1.x; handles permissions internally; avoids duplicating `extend_schema_type` dynamic features |
| Reuse `nautobot.core.graphql.schema` | Parallel schema misses Nautobot's custom fields, tags, computed fields |
| Depth ≤8, Complexity ≤1000 | Conservative defaults; prevents deeply-nested and expensive DoS without blocking useful queries |
| `graphql_introspect` as separate tool | Returns schema SDL so AI agents discover available types/fields without out-of-band docs |
| No new poetry dependencies | All required packages (graphene-django, graphql-core) are already Nautobot transitive deps |
| Structured errors, not HTTP 500s | GraphQL errors returned as `errors` array in response dict; syntax errors never throw unhandled exceptions |

**Requirements source:** `.planning/REQUIREMENTS.md` — v2.0 Requirements section
**Research:** `.planning/research/SUMMARY.md`

---

### Phase 14 — GraphQL Tool Scaffold

**Goal:** Create `graphql_query` MCP tool wrapping `nautobot.core.graphql.execute_query()` with unit tests.

**Requirements covered:** GQL-01, GQL-02, GQL-03, GQL-04, GQL-05, GQL-06, GQL-07, GQL-14, GQL-15, GQL-16, GQL-17

**Plans:**

1/1 plans complete
|---|------|-------------------|
| 14.1 | Create `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | File created; contains `graphql_query` async handler; imports `nautobot.core.graphql.execute_query` |
| 14.2 | Implement `graphql_query` — `async def` + `sync_to_async(thread_sensitive=True)` at outer boundary | Tool function is `async def`; single `sync_to_async(thread_sensitive=True)` wraps the entire `execute_query()` call |
| 14.3 | Accept `query: str` and `variables: dict \| None`; return `{"data": ..., "errors": [...]}` | Function signature accepts both params; return type is `dict`; no HTTP-level errors |
| 14.4 | Pass `output_schema=None` to `@register_tool` / `mcp.tool()` decorator | Tool registered without custom output schema; FastMCP auto-derives from type hints |
| 14.5 | Add side-effect import in `mcp/tools/__init__.py`; register via `@register_tool()` | GraphQL tool appears in tool registry and responds to `tools/list` |
| 14.6 | Write unit tests: auth propagation, valid query, invalid query, variables injection | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool` passes; all 4 cases covered |

**Gate:** `poetry run invoke unittest` passes with ≥4 new tests for GraphQL tool; `graphql_query` callable via MCP `tools/call` with valid token.

---

### Phase 15 — Introspection & Permissions

**Goal:** Add `graphql_introspect` tool and verify permission enforcement.

**Requirements covered:** GQL-08, GQL-09, GQL-13

**Plans:**

3/3 plans complete
|---|------|-------------------|
| 15.1 | Create `graphql_introspect` MCP tool returning GraphQL SDL string | Tool registered; calling it returns a multi-line SDL string; introspection succeeds without auth |
| 15.2 | Verify permission enforcement: `AnonymousUser` → empty results, authenticated user → filtered results | Integration test passes; restricted user gets zero rows on all queries; permitted user gets ≥1 row |
| 15.3 | Write unit test: `graphql_introspect` returns valid SDL | Test calls `graphql_introspect` and asserts response contains `"type"` and `"Query"` |

**Gate:** Two GraphQL tools registered; `graphql_introspect` returns valid SDL; permission test passes for both anonymous and authenticated users.

---

### Phase 16 — Security Hardening

**Goal:** Add depth/complexity limits and structured error handling.

**Requirements covered:** GQL-10, GQL-11, GQL-12

**Plans:**

1/1 plans complete
|---|------|-------------------|
| 16.1 | Enforce query depth limit (max_depth ≤ 8) | Deeply nested query (9+ levels) returns `{"errors": [{"message": "..."}]}` with no data |
| 16.2 | Enforce query complexity limit (max_complexity ≤ 1000) | Over-complex query returns `{"errors": [{"message": "..."}]}` with no data |
| 16.3 | GraphQL syntax errors returned as structured `errors` array, not HTTP 500s | Malformed query (unclosed bracket, invalid field) returns HTTP 200 with `errors` dict; no unhandled exception logged |
| 16.4 | Write unit tests for depth, complexity, and syntax error cases | 3 new tests in `test_graphql_tool.py`; all pass |

**Gate:** Depth/complexity limits block DoS queries; malformed queries return HTTP 200 with structured errors; no unhandled exceptions.

---

### Phase 17 — UAT & Documentation

**Goal:** Add smoke tests and full UAT suite; update SKILL.md.

**Requirements covered:** GQL-18, GQL-19, GQL-20

**Plans:**

1/1 plans complete
|---|------|-------------------|
| 17.1 | Add smoke test P-09 to `scripts/test_mcp_simple.py` | `python scripts/test_mcp_simple.py` includes P-09 and exits with code 0 |
| 17.2 | Add full UAT suite T-37+ (≥4 tests) to `scripts/run_mcp_uat.py` | `python scripts/run_mcp_uat.py` includes T-37, T-38, T-39, T-40; all pass |
| 17.3 | Document `graphql_query` and `graphql_introspect` in SKILL.md with example queries | SKILL.md updated; includes both tool signatures and ≥2 example queries |
| 17.4 | Run full `invoke tests` pipeline | `invoke tests` exits with code 0; all linters clean; all unit + UAT tests pass |

**Gate:** `invoke tests` passes end-to-end; P-09 and T-37+ green; SKILL.md updated.

---

## v3.0 — Future Milestone

**Status:** Not started

**Candidate features:**
- Write tools (create/update/delete) — requires permission modeling and transactional safety
- Redis session backend for `--workers > 1` horizontal scaling
- Tool-level field permissions
- Dry-run / validation mode for GraphQL queries
- Query result caching (TTL cache keyed on user_pk + query hash)

**Next step:** `/gsd-new-milestone` after v2.0 ships

---

*Roadmap last updated: 2026-04-15 — v2.0 GraphQL MCP Tool roadmap created*
*Archived milestones: `.planning/milestones/`*
