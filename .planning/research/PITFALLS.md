# Pitfalls Research — GraphQL MCP Tool

<research_type>Project Research — Pitfalls for GraphQL MCP tool.</research_type>

<summary>
Adding a graphene-django GraphQL layer to this standalone FastMCP process introduces risks around async/sync boundaries, auth middleware gaps, Django setup sequencing, URL routing assumptions, schema introspection, and N+1 query performance. Careful attention to thread-sensitive ORM calls, explicit auth propagation, and treating GraphQL as an MCP tool rather than a URL endpoint is required to avoid runtime failures and security holes.
</summary>

---

## Pitfalls Specific to This Project

### P1: `sync_to_async` Boundary in Graphene Resolvers

**What goes wrong:**
GraphQL resolvers in graphene-django run synchronously. If they access the Django ORM directly from a FastMCP async thread, they fail with `SynchronousOnlyOperation: You cannot call this from an async context`.

**Why it happens:**
FastMCP tool handlers are `async def`. The ORM call is synchronous. This is the same class of issue already documented in the project's Gotchas — the project has correctly handled it in existing tools, but graphene-django's `DjangoObjectType` field resolvers also run synchronously. Any custom resolver method that touches the ORM triggers the error.

**How it manifests:**
```python
# This raises SynchronousOnlyOperation inside a graphene resolver
class DeviceType(DjangoObjectType):
    class Meta:
        model = Device

    def resolve_location(self, info):
        return self.location.name  # ← Django model access inside resolver
```

**How to avoid:**
Wrap the entire `schema.execute()` call at the MCP tool boundary with a single `sync_to_async(thread_sensitive=True)` call. All resolver tree traversal then happens on Django's main thread:
```python
@mcp.tool()
async def graphql_query(ctx, query: str, variables: str = None):
    @sync_to_async
    def _execute():
        kwargs = {"query": query}
        if variables:
            kwargs["variable_values"] = json.loads(variables)
        kwargs["context_value"] = {"request": _build_request(ctx)}
        return schema.execute(**kwargs)
    result = await _execute()
    return {"data": result.data, "errors": [str(e) for e in result.errors] if result.errors else None}
```

**Warning signs:**
- `SynchronousOnlyOperation` in resolver traceback
- Logs show resolver execution before `sync_to_async` boundary

**Phase:** Phase 1 — Tool scaffold

---

### P2: Auth State Not Propagated into GraphQL Execution Context

**What goes wrong:**
The existing session tools store the authenticated user in FastMCP's MemoryStore (`mcp:cached_user`). GraphQL resolvers run outside the FastMCP `ctx` scope — they cannot call `ctx.get_state()`. If resolvers call `model.objects.restrict(user, ...)`, they get `AnonymousUser` restrictions even with a valid token.

**Why it happens:**
`ScopeGuardMiddleware` runs at the MCP tool-call boundary. Once inside `schema.execute()`, there is no MCP session context. `graphene.execute()` does not automatically forward HTTP headers or user identity.

**How it manifests:**
- Valid token passed to MCP tool
- `mcp_enable_tools` works
- GraphQL query returns empty results for objects the user should see
- `AnonymousUser.restrict()` silently filters everything

**How to avoid:**
Resolve the user **before** calling `schema.execute()`, then pass it into the GraphQL context:
```python
async def graphql_query(ctx, query: str, variables: str = None):
    # Resolve user from session state (already cached by previous auth)
    user_pk = ctx.request_context.session.get("mcp:cached_user")
    user = await _get_user(user_pk)  # sync_to_async lookup
    context = {"request": _build_django_request(ctx), "user": user}
    result = await _execute(query, context_value=context)
```

Then in resolvers, access `info.context.get("user")` instead of `info.context["request"].user`.

**Phase:** Phase 1 — Auth integration

---

### P3: Raw Query Bypasses Scope Guard Authorization

**What goes wrong:**
If the GraphQL tool exposes a free-form query parameter (client sends arbitrary GQL), `ScopeGuardMiddleware` only sees the single tool call `graphql_query`. It cannot inspect which fields the inner query requests. Scopes are enforced at the MCP boundary, not at the GraphQL field level.

**Why it happens:**
`ScopeGuardMiddleware.checkScopes()` runs on the MCP tool name, not the GraphQL query AST. A client with `scope="dcim"` can call `graphql_query(query="{ ipam_aggregates { id } }")` and retrieve IPAM data through a DCIM-scope session.

**How it manifests:**
- Client with narrow scope retrieves data from a type outside their scope
- No error raised at MCP layer
- GraphQL resolves normally

**How to avoid (pick one):**
- **Pre-approved queries only:** Design named tools per operation (`graphql_list_devices`, `graphql_get_device`) — each is a separate MCP tool with its own scope guard. Scopes map to tools.
- **Query allowlist:** Validate the query AST against an allowlist of permitted field paths for the current session's scopes before execution.
- **Schema-level middleware:** Wrap the graphene schema with a middleware that checks `info.context["user"]` permissions per field and raises `GraphQLError` for unauthorized fields.

**Phase:** Phase 1 — Architecture decision + Phase 2 — Authorization enforcement

---

### P4: Django App / `django.setup()` Not Called Before Schema Import

**What goes wrong:**
`ImportError: cannot import name 'schema'` or fields/models not appearing in the GraphQL schema.

**Why it happens:**
Graphene-django auto-generates `schema_django` by introspecting `INSTALLED_APPS` models. This requires `django.setup()` to have run. The standalone FastMCP process may call `nautobot.setup()` but if the GraphQL schema module is imported before that call completes, the schema will be empty or raise import errors.

**How it manifests:**
- Schema has no `Query` or `Mutation` types
- `DjangoObjectType`-registered fields return empty
- `ImportError` on `schema` import during module load

**How to avoid:**
Ensure `nautobot.setup()` (which calls `django.setup()`) runs at the **very top** of the server entry point, before any graphene or schema imports:
```python
# Entry point — FIRST
import nautobot
nautobot.setup()  # django.setup() fires here

# NOW safe
from .graphql.schema import schema  # ✅
```

**Phase:** Phase 1 — Server bootstrap

---

### P5: GraphQL as URL Endpoint vs MCP Tool

**What goes wrong:**
Attempting to add a `/graphql/` Django-style URL route to the standalone FastMCP process. Requests return 404 because FastMCP's `StreamableHTTPSessionManager` only routes MCP protocol messages, not arbitrary URLs.

**Why it happens:**
The project already uses a custom FastMCP HTTP transport — there is no Django URL router in the standalone process. A `/graphql/` URL would require adding a separate ASGI app or route handler, which is not the natural architecture.

**How it manifests:**
- `curl http://localhost:8005/graphql/` → 404
- Documentation suggests GraphQL is at a URL endpoint
- AI agent tries to GET/POST to `/graphql/` directly

**How to avoid:**
Implement GraphQL as an MCP tool (the natural pattern for this architecture):
```python
@mcp.tool()
async def graphql_query(query: str, variables: str = None, operation_name: str = None):
    """Execute a GraphQL query against Nautobot's schema."""
```
This preserves the existing authz pattern, session management, and tool discovery mechanism.

**Phase:** Phase 1 — Architecture decision

---

### P6: `DjangoObjectType` Meta Thread Issues Under `thread_sensitive=True`

**What goes wrong:**
`DjangoObjectType` uses the Django model's `pk` as its identity and may cache instances using thread-local state. Under `thread_sensitive=True`, the async-to-sync transition in `sync_to_async` does not guarantee the same thread for the entire resolver tree.

**Why it happens:**
`sync_to_async(thread_sensitive=True)` runs the wrapped function on Django's main thread pool, but each call may pick a different thread from the pool. `DjangoObjectType`'s internal `get_node()` method may resolve an object by ID on one thread, then hydrate field values on another — causing field data to be missing or stale.

**How it manifests:**
- Some device fields resolve correctly, others return `None`
- Inconsistent data across repeated identical queries
- No error raised, just silent `None` values

**How to avoid:**
- Use `sync_to_async` at the **outer tool boundary only** — not per resolver
- Ensure the entire `schema.execute()` call is a single `sync_to_async` call so all resolver tree execution happens in one thread context
- Test under concurrent load

**Phase:** Phase 2 — Concurrency testing

---

### P7: N+1 Query Problem in GraphQL Resolvers

**What goes wrong:**
A GraphQL query like `{ devices { location { site { name } } } }` generates N+1 ORM queries in naive graphene-django resolvers if `select_related` or `prefetch_related` are not configured.

**Why it happens:**
Each `DjangoObjectType` field resolver issues a separate ORM query for related objects. For a nested query returning 100 devices with 2 levels of relations, this can generate 200+ queries.

**How it manifests:**
- GraphQL queries timeout or are very slow
- DB query count in logs is disproportionately high vs result count
- List tools (existing) are optimized with `select_related`, but GraphQL resolvers are not

**How to avoid:**
Configure `DjangoObjectType` with `only` and `exclude` fields, and use `prefetch_related` in the root resolver's queryset:
```python
class DeviceNode(DjangoObjectType):
    class Meta:
        model = Device
        fields = "__all__"
        extras = {"prefetch_related": lambda info: ["location__site"]}
```
Alternatively, use DataLoader patterns to batch ID lookups.

**Phase:** Phase 2 — Performance

---

### P8: No Schema Discovery for AI Agents

**What goes wrong:**
AI agents using the MCP server cannot discover what types, fields, or operations the GraphQL schema exposes. The MCP tool registry shows `graphql_query` but not what queries are valid.

**Why it happens:**
GraphQL schemas are self-describing via introspection. However, FastMCP's tool discovery returns only the tool signature, not the schema SDL. Agents must either guess fields or have the schema SDL provided out-of-band.

**How it manifests:**
- Agent submits `{ devices { name } }` — works by coincidence
- Agent does not know available fields on `Device` type
- Tool is underutilized because schema is opaque to the agent

**How to avoid:**
Add a companion tool or session tool:
```python
@mcp.tool()
async def graphql_introspect(ctx) -> str:
    """Return the GraphQL schema SDL for discovery."""
    import graphql
    schema_sdl = graphql.get_schema(schema)
    return schema_sdl
```
Document the output and encourage agents to call it first.

**Phase:** Phase 2 — Discovery UX

---

### P9: `post_migrate` Signal Not Firing for Schema Registration

**What goes wrong:**
In the standalone FastMCP process, `post_migrate` does not fire (already documented in the existing PITFALLS.md). If a graphene-django schema is built dynamically based on installed apps or if `graphene_django.DjangoSchema` is created inside a `post_migrate` signal handler, the schema is never built.

**Why it happens:**
Same root cause as existing Pitfall 3: `nautobot_database_ready` / `post_migrate` only fires during `nautobot-server migrate`, not during standalone `django.setup()`. The GraphQL schema generation should be a startup action, not a signal handler.

**How to avoid:**
Build the schema at server startup, after `nautobot.setup()` completes, as a module-level or startup-initialized singleton — not in a signal handler:
```python
# graphql/schema.py — module level, built after django.setup()
def get_schema():
    if not hasattr(get_schema, "_instance"):
        get_schema._instance = graphene.Schema(query=Query)
    return get_schema._instance
```

**Phase:** Phase 1 — Tool scaffold

---

### P10: Token Auth Repeatedly Hit DB Per Request

**What goes wrong:**
Each GraphQL query re-authenticates the user by looking up the token in the DB. If the schema resolver tree makes many ORM calls already, adding a per-request token lookup compounds DB load.

**Why it happens:**
`get_user_from_request()` does a DB lookup on every tool call. Existing tools handle this by caching the user PK in session state (`mcp:cached_user`). If a GraphQL resolver re-authenticates without using the session cache, it hits the DB on every resolver invocation.

**How it manifests:**
- DB query log shows many `auth_token` table lookups per GraphQL request
- High DB load for moderate query volumes
- Auth works but is slower than expected

**How to avoid:**
Use the existing session state pattern: `ctx.request_context.session.get("mcp:cached_user")` is already cached per session. Propagate that user PK into the GraphQL context without re-querying the token table.

**Phase:** Phase 1 — Auth integration

---

## Integration Pitfalls

### P11: Schema Built from Wrong `INSTALLED_APPS`

**What goes wrong:**
The GraphQL schema includes models from apps that are not in the standalone process's `INSTALLED_APPS` but are in Nautobot's `PLUGINS`. Fields for third-party app models are missing, or the schema includes stale types.

**Why it happens:**
`django.setup()` from the standalone process may load a different set of apps than Nautobot's own Django process. If the MCP server is started with its own `DJANGO_SETTINGS_MODULE` pointing to a minimal config, not all Nautobot plugin apps are loaded.

**How to avoid:**
Verify the MCP server uses the **same** `nautobot_config.py` as Nautobot, so `INSTALLED_APPS` + `PLUGINS` are identical. The Docker Compose env var `NAUTOBOT_CONFIG` must point to the shared config file.

**Phase:** Phase 0 — Environment setup

---

### P12: Concurrent GraphQL Requests Leak Data Across Sessions

**What goes wrong:**
Thread-sensitivity issues cause data from one user's query to appear in another's results.

**Why it happens:**
If `sync_to_async` is not `thread_sensitive=True`, async threads pick arbitrary pool threads. Django's `connection.cursor()` and some middleware state are not fully isolated. If `thread_sensitive=False`, cross-request state can leak.

**How to avoid:**
Always use `sync_to_async(..., thread_sensitive=True)` for the GraphQL tool boundary. This is already the standard in existing tools — must be maintained for the new GraphQL tool.

**Phase:** Phase 1 — Tool scaffold

---

## Warning Signs

| Warning Sign | Likely Cause |
|---|---|
| `SynchronousOnlyOperation` in resolver traceback | ORM call inside resolver without `sync_to_async` wrapper at tool boundary |
| GraphQL query returns empty for valid-token session | User context not propagated; `AnonymousUser.restrict()` filtering all results |
| IPAM data returned with `scope="dcim"` session | Raw query scope bypass — scopes only enforced at MCP tool name, not query AST |
| Schema has no `Query` type on startup | `django.setup()` not called before schema import |
| `/graphql/` URL returns 404 | GraphQL is an MCP tool, not a URL endpoint |
| Inconsistent field values across identical queries | `DjangoObjectType` under non-`thread_sensitive=True` `sync_to_async` |
| Schema introspection returns empty SDL | `graphene.Schema()` built before models loaded; wrong `INSTALLED_APPS` |
| Many `auth_token` DB queries per GraphQL request | Token re-looked up in each resolver instead of session-cached user |
| High DB query count for simple nested GraphQL query | N+1 problem; `prefetch_related` not configured |

---

## Prevention Strategies

1. **Wrap `schema.execute()` at the tool boundary.** One `sync_to_async(thread_sensitive=True)` call wrapping the entire GraphQL execution, not per-resolver guards.

2. **Propagate user into GraphQL context manually.** Resolve from session state before `execute()`, set `context["user"]`, access in resolvers via `info.context["user"]`. Never rely on HTTP request context inside resolvers.

3. **Expose GraphQL as an MCP tool, not a URL endpoint.** Accept `{ query, variables, operation_name }` as tool arguments. Document this clearly.

4. **Scope enforcement: named tools over raw queries.** If scope enforcement matters, expose pre-named operations (`graphql_list_devices`, `graphql_get_ip_prefixes`) rather than a single raw query tool. Each tool name maps to a scope in `ScopeGuardMiddleware`.

5. **Validate queries against scope allowlists if raw queries are exposed.** Use the GraphQL AST to check field paths against session scopes before execution.

6. **Build schema at startup, not in signals.** Use a lazy singleton after `nautobot.setup()` completes.

7. **Use same `nautobot_config.py` as Nautobot.** Verify `INSTALLED_APPS` + `PLUGINS` are identical in both processes.

8. **Add `graphql_introspect` tool.** Return the schema SDL so AI agents can discover types without out-of-band documentation.

9. **Configure `prefetch_related` / `select_related` on `DjangoObjectType`.** Prevent N+1 query problems in nested queries.

10. **Add integration tests:** concurrent GraphQL queries through the MCP tool layer, verify auth is enforced, no cross-session data leakage, no `SynchronousOnlyOperation` in logs.

---

## Phase Addressing Concerns

| Concern | Phase |
|---|---|
| P1: `sync_to_async` boundary in resolvers | Phase 1 — Tool scaffold |
| P2: Auth state not propagated to GraphQL context | Phase 1 — Auth integration |
| P3: Raw query bypasses scope guard | Phase 1 — Architecture decision + Phase 2 — Authz enforcement |
| P4: Django setup before schema import | Phase 1 — Server bootstrap |
| P5: GraphQL as URL endpoint vs MCP tool | Phase 1 — Architecture decision |
| P6: `DjangoObjectType` thread issues | Phase 2 — Concurrency testing |
| P7: N+1 query problem | Phase 2 — Performance |
| P8: No schema discovery for agents | Phase 2 — Discovery UX |
| P9: Schema built in `post_migrate` signal | Phase 1 — Tool scaffold |
| P10: Token DB lookup per request | Phase 1 — Auth integration |
| P11: Schema built from wrong `INSTALLED_APPS` | Phase 0 — Environment setup |
| P12: Cross-session data leakage | Phase 1 — Tool scaffold |

---

## Sources

- `docs/dev/ARCHITECTURE.md` — standalone FastMCP architecture, session state, `sync_to_async` patterns
- `.planning/research/PITFALLS.md` (prior) — existing standalone server pitfalls for reference
- `nautobot_app_mcp_server/mcp/tools/core.py` — existing tool implementation patterns (thread-sensitivity, session state)
- `nautobot_app_mcp_server/mcp/auth.py` — `get_user_from_request()` token auth flow
- `nautobot_app_mcp_server/mcp/session_tools.py` — session state pattern
- `nautobot_app_mcp_server/mcp/middleware.py` — `ScopeGuardMiddleware` scope enforcement logic
- `nautobot_app_mcp_server/mcp/commands.py` — `create_app()` FastMCP factory
- graphene-django documentation — `DjangoObjectType`, `DjangoSchema`, `DataLoader`, introspection patterns

---

*Pitfalls research for: Adding graphene-django GraphQL MCP tool to standalone FastMCP process*
*Researched: 2026-04-15*
