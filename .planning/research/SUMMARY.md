# Research Summary — v2.0 GraphQL MCP Tool

<research_type>Synthesized research for v2.0 GraphQL MCP Tool milestone.</research_type>

---

## 1. Summary

Adding a GraphQL MCP tool to the standalone FastMCP server is a low-dependency,
high-leverage addition: Nautobot already bundles graphene-django and exposes a
canonical execution function (`nautobot.core.graphql.execute_query`), so no new
poetry packages are needed. The tool wraps that function inside a standard
`async def` handler using the exact same `sync_to_async(thread_sensitive=True)`
pattern already proven across all 10 existing tools. The main work is wiring
auth propagation into GraphQL's execution context (so `.restrict()` works),
deciding whether to reuse Nautobot's built-in schema or build a parallel one,
and adding a schema-introspection companion tool so AI agents can discover
available types. Twelve pitfalls have been catalogued — the most critical are
the async/sync boundary (P1), auth context not reaching resolvers (P2), raw-query
scope bypass (P3), and Django setup sequencing (P4). All are preventable with
well-understood patterns.

---

## 2. Stack Additions

**No new poetry dependencies.** All required libraries are already present as
Nautobot transitive dependencies:

| Package | Via | Purpose |
|---|---|---|
| `graphene-django` | Nautobot core | `DjangoObjectType`, `DjangoSchema` |
| `graphene` | `graphene-django` | Base types (`graphene.String()`, `graphene.List()`, etc.) |
| `graphql-core` | `graphene-django` | `graphql.execute()`, `graphql.parse()` |
| `graphene-django-optimizer` | Nautobot core | `OptimizedNautobotObjectType` — auto `prefetch_related`/`select_related` |

**Canonical integration points — use these, do not duplicate:**

- `nautobot.core.graphql.execute_query(query, variables, user)` — stable since
  Nautobot 1.x; accepts a user directly, handles permission enforcement internally
- `nautobot.core.graphql.schema` — pre-built graphene-django schema exposing all
  Nautobot models with `OptimizedNautobotObjectType` wrappers
- `graphene_settings.SCHEMA.graphql_schema` — what `execute_query` uses internally
- `nautobot.core.graphql.types.OptimizedNautobotObjectType` — base class for all
  Nautobot GraphQL types

**Files to add:**

| File | Purpose |
|---|---|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | `graphql_query` handler + optional `graphql_introspect` |
| `nautobot_app_mcp_server/mcp/tools/__init__.py` | Add `graphql_tool` side-effect import |

No changes to `commands.py`, no new ORM models, no migrations, no `api/` dir.
If a future iteration needs a custom schema (app-specific types only), add
`graphene-django >=3.0,<4.0` explicitly to `pyproject.toml`. Not required for v1.

---

## 3. Feature Table Stakes

These are the minimum requirements for a safe, working GraphQL MCP tool:

| Feature | Requirement | Implementation |
|---|---|---|
| **Token auth** | Resolve `Authorization: Token <hex>` to Nautobot User | Reuse `get_user_from_request(ctx)` — already cached per session |
| **Permission enforcement** | Row-level `.restrict(user, "view")` filtering active in all resolvers | `execute_query(user=user)` handles this; verify `request.user` is propagated |
| **Query execution** | Accept `query: str` + `variables: dict \| None`; return `data`/`errors` | Wrap `execute_query(query, variables, user)` |
| **JSON-serializable return** | FastMCP requires dict/list/primitives | `execute_query` returns a dict directly; pass `output_schema=None` |
| **async/sync bridge** | Route Django ORM calls through Django's thread pool | `sync_to_async(..., thread_sensitive=True)` at the tool boundary — single wrapper, not per-resolver |
| **Input schema** | FastMCP needs typed inputs | `query: str`, `variables: dict \| None` — auto-derived from type hints via `@register_tool` |
| **Error handling** | Structured `errors` array, not HTTP 500s | `execute_query` returns `{"data": ..., "errors": [...]}`; pass through unchanged |
| **Query complexity limits** | Prevent DoS via deeply nested queries | Configure graphene `max_depth`/`max_complexity`; default conservatively (depth ≤8, complexity ≤1000) |
| **Django bootstrap ordering** | Schema must build after `nautobot.setup()` | Entry point calls `nautobot.setup()` first; schema imported after |
| **Tool registration** | GraphQL tool appears in MCP tool list | Side-effect import in `mcp/tools/__init__.py` — same pattern as `core.py` |

---

## 4. Differentiators

Features that elevate the GraphQL tool from "functional" to "genuinely useful
for AI agents":

| Feature | Complexity | Value |
|---|---|---|
| **`graphql_introspect` companion tool** | LOW | Returns schema SDL so agents discover available types/fields without out-of-band docs |
| **Named query registry** | LOW–MED | Pre-registered query snippets (e.g. `device_with_full_network_stack`) agents call by name instead of writing raw queries |
| **Dry-run / validation mode** | LOW | `validate_only: bool` flag — parse and validate without executing; lets agents check query validity cheaply |
| **Nested prefetch hints** | MED | Accept `prefetch`/`select` param or auto-detect; `OptimizedNautobotObjectType` already handles most cases, but arbitrary queries may bypass it |
| **Query result caching** | MED | Cache repeated identical GraphQL queries for N seconds using FastMCP session TTL cache |
| **Multi-query execution** | MED | Support multiple named operations in one request; return results keyed by `operation_name` |
| **Rich error formatting** | LOW | Pass through graphene's `ExecutionResult.to_dict()` which already includes `path`, `locations`, `extensions` |

**The single highest-value differentiator is `graphql_introspect`.** Without it,
the schema is opaque to AI agents and the tool is underutilized. Add it in
Phase 2 alongside the main tool.

---

## 5. Watch Out For

Critical pitfalls with prevention strategies:

| # | Pitfall | Prevention |
|---|---|---|
| **P1** | `SynchronousOnlyOperation` — ORM call inside resolver without `sync_to_async` at the outer boundary | Wrap the *entire* `execute_query()` call in a single `sync_to_async(thread_sensitive=True)`. Do NOT add per-resolver guards. |
| **P2** | Auth context invisible to resolvers — `AnonymousUser.restrict()` silently filters everything | Resolve user before `execute_query()`, pass as `context_value={"request": ..., "user": user}`. Access via `info.context.get("user")` in resolvers. |
| **P3** | Raw GraphQL query bypasses `ScopeGuardMiddleware` — scopes enforced at MCP tool name, not query AST | If scope enforcement matters: expose named tools per operation (`graphql_list_devices`) OR validate query AST field paths against session scopes before execution. |
| **P4** | `ImportError` / empty schema — schema imported before `django.setup()` | Call `nautobot.setup()` at the very top of the server entry point; import schema module *after*. |
| **P5** | `/graphql/` URL returns 404 — GraphQL is an MCP tool, not a URL endpoint | Accept `{query, variables, operation_name}` as tool arguments. Document explicitly. |
| **P6** | Inconsistent field values — `DjangoObjectType` thread issues under non-`thread_sensitive=True` | Single `sync_to_async(thread_sensitive=True)` at tool boundary; test under concurrent load. |
| **P7** | N+1 query explosion — nested relations trigger separate ORM query per node | Configure `prefetch_related`/`select_related` on `DjangoObjectType`; `OptimizedNautobotObjectType` handles the common cases. |
| **P8** | Schema opaque to AI agents — tool is underutilized | Add `graphql_introspect` tool that returns the schema SDL; document that agents should call it first. |
| **P9** | Schema built in `post_migrate` signal — never fires in standalone process | Build schema at startup (lazy singleton after `nautobot.setup()`), not in a signal handler. |
| **P10** | Token DB lookup per resolver — `auth_token` table hit repeatedly | Use the cached `mcp:cached_user` from session state; `execute_query(user=user)` already does this correctly. |
| **P11** | Schema built from wrong `INSTALLED_APPS` — missing third-party plugin models | MCP server must use the *same* `nautobot_config.py` as Nautobot; verify `NAUTOBOT_CONFIG` env var. |
| **P12** | Cross-session data leakage — threads not isolated | Always `sync_to_async(..., thread_sensitive=True)`; add concurrent-query integration tests verifying no data leaks. |

**Warning signs to watch in logs:**
- `SynchronousOnlyOperation` → P1: ORM call without outer `sync_to_async`
- Empty results with valid token → P2: user context not propagated
- Wrong model data with narrow scope → P3: raw-query scope bypass
- Schema has no `Query` type → P4: `django.setup()` not called before import
- `/graphql/` 404 → P5: GraphQL is a tool, not a URL
- Inconsistent field values → P6: `DjangoObjectType` thread issue
- High DB query count for nested query → P7: N+1 problem

---

## 6. Build Order

Recommended phased structure with gate criteria:

```
Phase 0 — Environment verification
  ├─ Verify MCP server uses same nautobot_config.py as Nautobot (P11)
  ├─ Confirm Nautobot GraphQL schema loads in standalone process
  └─ Verify `execute_query` works with `user=None` (AnonymousUser baseline)
  Gate: single GraphQL query returns data without errors in Django shell

Phase 1 — Tool scaffold
  ├─ Create graphql_tool.py with graphql_query handler
  │   ├─ get_user_from_request(ctx) → execute_query(query, variables, user)
  │   ├─ sync_to_async(thread_sensitive=True) at tool boundary
  │   └─ output_schema=None
  ├─ Add graphql_tool side-effect import to mcp/tools/__init__.py
  ├─ Create mcp/tests/test_graphql_tool.py
  │   ├─ auth propagates correctly
  │   ├─ query returns structured data
  │   ├─ invalid query returns errors dict
  │   └─ variables injection works
  └─ Gate: unit tests pass, MCP tool callable via `tools/call`

Phase 2 — Permission + introspection
  ├─ Verify `.restrict()` active in results (empty results for restricted user)
  ├─ Add graphql_introspect companion tool (returns schema SDL)
  ├─ Add integration test: concurrent queries — no cross-session leakage (P12)
  └─ Gate: 2-tool MCP server, introspection returns valid SDL

Phase 3 — Error handling + hardening
  ├─ Add depth/complexity limits to prevent DoS
  ├─ Handle GraphQL syntax errors → MCP tool error response (not HTTP 500)
  ├─ Handle permission-denied results → structured error with path
  └─ Gate: malformed queries and deep queries handled gracefully

Phase 4 — UAT + docs
  ├─ Add UAT smoke test to scripts/test_mcp_simple.py (P-09)
  ├─ Add full UAT suite to scripts/run_mcp_uat.py (T-37–T-40+)
  ├─ Document graphql_query + graphql_introspect in SKILL.md
  └─ Gate: `invoke tests` passes, UAT 100%, all linters clean
```

---

## 7. Requirements Hints

Based on research, the v2.0 roadmap should include:

### Must have (MVP)
1. **`graphql_query` MCP tool** — wraps `nautobot.core.graphql.execute_query`,
   accepts `query: str` and `variables: dict | None`, returns `dict` with
   `data`/`errors`; uses `sync_to_async(thread_sensitive=True)`,
   `get_user_from_request()`, and `output_schema=None`
2. **`graphql_introspect` companion tool** — returns GraphQL schema SDL so AI
   agents can discover types; single `mcp.tool()` returning a string
3. **Auth propagation verification** — integration test confirming
   `AnonymousUser` returns empty, authenticated user gets filtered results
4. **UAT smoke test** — add `graphql_query` to `scripts/test_mcp_simple.py`
5. **UAT full suite** — add 4+ GraphQL tests to `scripts/run_mcp_uat.py`

### Should have (v2.0 full)
6. **Query depth/complexity limits** — configurable `max_depth` (default ≤8)
   and `max_complexity` (default ≤1000) to prevent DoS
7. **Named query registry** — config dict of pre-approved queries agents can
   invoke by name, each as a separate MCP tool for scope-gating
8. **Concurrent load test** — verify no cross-session data leakage under
   concurrent GraphQL requests
9. **SKILL.md update** — document `graphql_query` usage, example queries,
   `graphql_introspect` pattern

### Could have (post-v2.0)
10. **Dry-run mode** — `validate_only: bool` flag to parse/validate without exec
11. **Query result caching** — TTL cache keyed on `(user_pk, query_hash)`
12. **Multi-operation support** — execute all named operations in one request,
    return results keyed by `operation_name`

### Explicitly out of scope (based on research)
- **Custom GraphQL schema** — reuse `nautobot.core.graphql.schema`; a parallel
  schema misses Nautobot's `extend_schema_type` dynamic features (custom fields,
  tags, config contexts, computed fields)
- **GraphQL as URL endpoint** — not a URL route; the MCP tool IS the interface
- **`models.py` / `filters.py` / `api/` / `migrations/`** — this app has no DB
  models; adding them violates established architecture
- **Multi-worker support** — in-memory sessions; `--workers 1` remains required

---

*Research synthesized from: STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md*
*Date: 2026-04-15*
