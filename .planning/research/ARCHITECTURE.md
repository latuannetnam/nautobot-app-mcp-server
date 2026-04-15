# Architecture Research — GraphQL MCP Tool

<research_type>Project Research — Architecture for GraphQL MCP tool.</research_type>

<summary>
A graphene-django GraphQL endpoint integrates with the existing standalone FastMCP
architecture by running in the same process (after `nautobot.setup()`), executing
queries via `sync_to_async(thread_sensitive=True)` from within a FastMCP async tool
handler, and sharing the same auth layer (token from `Authorization: Token` header).
The GraphQL tool is a new MCP tool (`graphql_query`) that accepts a query string
and optional variables, resolves Nautobot objects with full permission enforcement
(via `.restrict()`), and returns a JSON result. No Django URL routing, views, or
WSGI wiring is needed — the GraphQL schema executes entirely inside the FastMCP
async event loop.
</summary>

## Integration Points

### 1. Django ORM bootstrap (existing)

`nautobot.setup()` is already called once at FastMCP worker startup in
`commands.py`. This bootstraps the Django ORM and registers all Nautobot apps,
making `nautobot.dcim.models`, `nautobot.ipam.models`, etc. importable in the
same process.

**For GraphQL:** The graphene-django schema can call Django ORM models freely
because Django is already initialized. No additional `nautobot.setup()` calls
are needed per request.

### 2. Auth layer (existing)

`get_user_from_request(ctx)` already extracts the `Authorization: Token <hex>`
header from the FastMCP request and returns a Nautobot `User` (or `AnonymousUser`).
GraphQL resolvers must receive the authenticated user to call `.restrict(user)` on
querysets — enforcing Nautobot's object-level permissions.

**For GraphQL:** The `graphql_query` tool handler calls `get_user_from_request(ctx)`
first, then passes the user to the schema execution context. Two integration
options:

- **Option A (proxy):** Forward the raw GraphQL query to Nautobot's built-in
  `/api/graphql/` endpoint, preserving Nautobot's auth/permission handling entirely.
  Requires a Django process (Nautobot) to be reachable from the MCP server.
- **Option B (in-process):** Execute the GraphQL query directly against a
  `graphene_django.DjangoSchema` inside the FastMCP process. Requires passing
  the user context into graphene-django's execution context (via `context_value`).

### 3. FastMCP tool registration (existing)

`MCPToolRegistry` and `@register_tool` already support adding new tools.
The GraphQL tool follows the same pattern: `@register_tool(tier="core", scope="core")`
for the base tool, with additional scope-gated variants for advanced queries.

### 4. FastMCP session state (existing)

`ctx.get_state()` / `ctx.set_state()` already store per-session state
(session ID → MemoryStore). The GraphQL tool can use the same mechanism to
cache the validated user, avoiding repeated DB lookups per query batch.

### 5. FastMCP async event loop (existing)

FastMCP owns the async event loop. All tool handlers are `async def`.
GraphQL schema execution via graphene-django is a **sync** operation (runs on
the Django ORM thread). It must be wrapped in `sync_to_async(..., thread_sensitive=True)`
just like the existing 10 core tools in `tools/core.py`.

## New Components

### 1. `nautobot_app_mcp_server/mcp/graphql_schema.py` (NEW)

Django-level GraphQL schema definition:

```python
import graphene
from graphene_django import DjangoObjectType
from nautobot.dcim.models import Device, Interface
from nautobot.ipam.models import IPAddress, Prefix, VLAN

# GraphQL ObjectType wrappers for Nautobot models
class DeviceType(DjangoObjectType):
    class Meta:
        model = Device
        fields = "__all__"

class InterfaceType(DjangoObjectType):
    class Meta:
        model = Interface
        fields = "__all__"

class Query(graphene.ObjectType):
    devices = graphene.List(DeviceType, limit=graphene.Int())
    device = graphene.Field(DeviceType, name=graphene.String())

    def resolve_devices(self, info, limit=25):
        # Called from GraphQL — info.context carries the Django user
        user = info.context
        qs = Device.objects.all().restrict(user, "view")
        return qs[:limit]

class NautobotGraphQLSchema(graphene.Schema):
    """Root schema for Nautobot GraphQL queries."""
```

**Key design decisions:**
- `DjangoObjectType` auto-generates GraphQL fields from Django model fields
- Resolver `info.context` carries the authenticated user from the tool handler
- QuerySets use `.restrict(user, "view")` for permission enforcement
- Schema lives in a standalone Python module (Django-level) separate from the
  FastMCP layer (async-level) — boundary: `graphql_query` tool → sync resolver

### 2. `nautobot_app_mcp_server/mcp/tools/graphql.py` (NEW)

FastMCP tool handler for GraphQL execution:

```python
from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext

from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request

@register_tool(
    name="graphql_query",
    description="Execute a GraphQL query against Nautobot's data model.",
    tier="core",
    scope="core",
)
async def graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict | None = None,
) -> dict:
    """Execute a GraphQL query.

    Args:
        ctx: FastMCP ToolContext (provides auth headers + session state).
        query: GraphQL query string (e.g. '{ devices { name status { name } } }').
        variables: Optional dict of GraphQL variable values.

    Returns:
        dict with 'data', 'errors', and 'extensions' from the GraphQL execution.
    """
    user = await get_user_from_request(ctx)

    async def execute_graphql_sync():
        from nautobot_app_mcp_server.mcp.graphql_schema import NautobotGraphQLSchema
        result = NautobotGraphQLSchema.execute(
            query,
            variables=variables or {},
            context_value={"request": ctx},  # pass user via context
        )
        return result

    return await sync_to_async(execute_graphql_sync, thread_sensitive=True)()
```

**Key design decisions:**
- `sync_to_async(..., thread_sensitive=True)` routes the GraphQL sync execution
  to Django's request thread where the DB connection pool is valid
- User context is passed through `context_value` so resolvers can call
  `.restrict(user, "view")` on querysets
- Returns the graphene execution result as a dict (JSON-serializable)

### 3. `nautobot_app_mcp_server/mcp/tools/__init__.py` (MODIFIED)

Side-effect import for the new GraphQL module triggers tool registration:

```python
from nautobot_app_mcp_server.mcp.tools import core    # noqa: F401
from nautobot_app_mcp_server.mcp.tools import graphql  # noqa: F401 — registers graphql_query
```

### 4. `nautobot_app_mcp_server/mcp/graphql_auth.py` (NEW, optional)

A thin helper that extracts the user from graphene's `info.context` in resolvers,
decoupling resolver code from how the context is structured:

```python
def get_user_from_graphql_info(info) -> User:
    """Extract Nautobot user from graphene info.context."""
    ctx = info.context.get("request")
    if ctx is None:
        from django.contrib.auth.models import AnonymousUser
        return AnonymousUser()
    # Reuse the cached user already stored by get_user_from_request
    return ctx  # ctx already is the authenticated User
```

### 5. Tests (NEW)

| File | Purpose |
|------|---------|
| `mcp/tests/test_graphql_tool.py` | Unit tests for `graphql_query` handler: auth, error handling, variables |
| `mcp/tests/test_graphql_schema.py` | Unit tests for `DjangoObjectType` wrappers and resolver permission enforcement |

## Data Flow

```
AI Agent
  └─ MCP request (HTTP POST /mcp/, Authorization: Token <key>)
       │
       ▼
FastMCP StreamableHTTPSessionManager
  │
  ▼
graphql_query tool handler [tools/graphql.py]
  │
  ├── get_user_from_request(ctx)         [auth.py — token → User, cached per session]
  │
  ├── sync_to_async(execute_graphql_sync, thread_sensitive=True)
  │       │
  │       ▼
  │   NautobotGraphQLSchema.execute(query, context_value={"request": user})
  │       │
  │       ▼
  │   graphene-django traverses Query resolvers
  │       │
  │       ▼
  │   Django ORM: Device.objects.all().restrict(user, "view")
  │       │
  │       ▼
  │   PostgreSQL DB (same pool as Nautobot)
  │
  ▼
JSON-RPC response: {"data": {...}, "errors": [...]}
```

**Cross-cutting concerns handled by existing infrastructure:**

| Concern | Who handles it |
|---------|----------------|
| Token auth | `get_user_from_request` (existing) |
| Session state | FastMCP MemoryStore (existing) |
| Scope gating | `ScopeGuardMiddleware` (existing) — `graphql_query` is `tier="core"` |
| Thread safety | `sync_to_async(thread_sensitive=True)` (existing pattern) |
| Error serialization | FastMCP JSON-RPC response (existing) |

## Suggested Build Order

```
Phase 1 — Django schema foundation
  └─ Create mcp/graphql_schema.py
       └─ Define DjangoObjectType wrappers for Device, Interface, IPAddress, Prefix, VLAN
       └─ Define Query root with sample fields
       └─ Verify schema executes in isolation (Django shell test)
  └─ Add tests: mcp/tests/test_graphql_schema.py

Phase 2 — MCP tool entry point
  └─ Create mcp/tools/graphql.py
       └─ graphql_query tool with get_user_from_request + sync_to_async wrapper
       └─ Verify FastMCP routing (start dev server, call tool via MCP client)
  └─ Add tests: mcp/tests/test_graphql_tool.py
  └─ Register tool via mcp/tools/__init__.py side-effect import

Phase 3 — Full Nautobot model coverage
  └─ Expand graphql_schema.py with remaining Nautobot models (Location, Rack, Cluster,
     VirtualMachine, VRF, Namespace, Prefix, VLAN, etc.)
  └─ Add relationship fields (Device.interfaces, Interface.ip_addresses, etc.)
  └─ Verify query complexity is acceptable for MCP tool use

Phase 4 — Error handling and edge cases
  └─ Handle GraphQL syntax errors → MCP tool error response
  └─ Handle permission-denied results → structured error with path
  └─ Handle deep recursion / query complexity → depth limit config
  └─ Handle variable injection safety (graphene uses parameterized queries)

Phase 5 — Documentation and UAT
  └─ Add example queries to docs (how to query devices, interfaces, IPs)
  └─ Add UAT tests: scripts/test_mcp_simple.py smoke test for graphql_query
```

## How GraphQL Execution Fits Into FastMCP's Async Framework

FastMCP async handlers **cannot** call sync Django ORM code directly. The async
tool handler (`graphql_query`) runs in FastMCP's asyncio event loop, but Django's
ORM and the graphene-django schema execution are sync functions that require Django's
request thread (the thread that owns the DB connection pool).

The pattern, identical to the existing 10 core tools:

```
async def graphql_query_handler(...):        # FastMCP async context
    user = await get_user_from_request(ctx)  # FastMCP async — reads HTTP headers
    return await sync_to_async(              # bridge: async → sync
        execute_graphql,                     # sync: runs in Django's thread
        thread_sensitive=True                # critical: routes to correct thread
    )(query, variables, user)
```

`thread_sensitive=True` ensures the sync function runs on the same thread that
Django's `DatabaseWrapper` uses for connection management. Without it, FastMCP's
thread pool uses a different thread, and the ORM raises "Connection not available".

The GraphQL execution itself (`NautobotGraphQLSchema.execute(...)`) is a blocking
call — graphene-django walks the schema tree, calls resolvers, and builds the
response synchronously. This is why `sync_to_async` is the correct wrapper: it
blocks the asyncio coroutine until the sync function completes, then resumes
the coroutine with the result. FastMCP handles the underlying thread handoff
automatically via `sync_to_async`.

The graphene execution result (a dict with `data` and `errors` keys) is returned
to the async handler, which then returns it as the MCP tool result. FastMCP
serializes it as JSON and wraps it in a JSON-RPC response.