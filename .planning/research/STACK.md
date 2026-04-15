# Stack Research — GraphQL MCP Tool

<research_type>Project Research — Stack for GraphQL MCP tool.</research_type>

<summary>
Adding a GraphQL MCP tool requires no new Python packages: Nautobot already bundles graphene-django and related GraphQL libraries as transitive dependencies. The new MCP tool wraps `nautobot.core.graphql.execute_query()` (already used internally by Nautobot's REST API GraphQL endpoint) inside a standard `sync_to_async(thread_sensitive=True)` pattern, following the exact same auth and FastMCP wiring already established in the codebase. Key decisions are: (1) reuse Nautobot's built-in schema rather than building a parallel one, (2) pass the authenticated user into GraphQL's context so row-level permission filtering works automatically, and (3) wrap the raw GraphQL result dict directly as the MCP tool output.
</summary>

## Libraries & Dependencies

**No new poetry dependencies required.** Nautobot's own transitive dependencies cover everything needed:

| Package | Already present via | Notes |
|---|---|---|
| `graphene-django` | `nautobot` core | Provides `graphene` base types used throughout `nautobot.core.graphql.*` |
| `graphene` | `graphene-django` | `graphene.String()`, `graphene.List()`, etc. |
| `graphql-core` | `graphene-django` | `graphql.execute()` and `graphql.parse()` used in `execute_query()` |
| `graphene-django-optimizer` (`gql_optimizer`) | `nautobot` core | Powers `OptimizedNautobotObjectType` — auto-applies `prefetch_related`/`select_related` |

Key functions already in the venv (do NOT duplicate):

- `nautobot.core.graphql.execute_query(query, variables=None, user=None)` — canonical query execution function; accepts a user directly and passes it as `request.user` in the GraphQL context
- `nautobot.core.graphql.schema` — pre-built schema exposing all Nautobot models (devices, interfaces, prefixes, VLANs, locations, etc.)

If a **custom schema** (not reusing Nautobot's) is needed in a future iteration for app-specific types only, add `graphene-django >= 3.0, < 4.0` explicitly to `pyproject.toml`. This is not required for v1 of the GraphQL MCP tool.

## Integration Points

### 1. New tool function (`mcp/tools/graphql_tool.py`)

```python
"""GraphQL MCP tool — wraps nautobot.core.graphql.execute_query as an MCP tool."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext

from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot.core.graphql import execute_query

TOOLS_TIER = "core"
TOOLS_SCOPE = "core"


@register_tool(
    name="graphql_query",
    description="Execute an arbitrary GraphQL query against Nautobot's schema. "
    "Supports all Nautobot models: devices, interfaces, prefixes, VLANs, locations, and more.",
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a GraphQL query against Nautobot.

    Args:
        ctx: FastMCP ToolContext providing request/session access.
        query: GraphQL query string (e.g. "{ devices { name status { name } } }").
        variables: Optional dict of GraphQL variable values.

    Returns:
        dict with "data" and/or "errors" keys — raw GraphQL result dict.
    """
    user = await get_user_from_request(ctx)
    return await sync_to_async(
        lambda: execute_query(query, variables=variables, user=user),
        thread_sensitive=True,
    )()
```

**Key integration points:**
- Auth: `get_user_from_request(ctx)` — same pattern as all 10 existing tools
- Thread safety: `sync_to_async(..., thread_sensitive=True)` — same as `query_utils` functions
- Output: returns a dict with `data` and/or `errors` keys directly; `output_schema=None` is passed to `mcp.tool()` to suppress FastMCP output validation
- No new ORM models, filters, forms, or serializers needed

### 2. Tool registration (side-effect import)

Add to `mcp/tools/__init__.py`:

```python
from nautobot_app_mcp_server.mcp.tools import core      # noqa: F401
from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401
```

The `@register_tool` decorator fires on import, populating `MCPToolRegistry` automatically — identical to how `core.py` is registered.

### 3. FastMCP wiring (already in `commands.py`)

`create_app()` already calls:

```python
from nautobot_app_mcp_server.mcp import register_all_tools_with_mcp
from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401
from nautobot_app_mcp_server.mcp import session_tools  # noqa: F401

register_all_tools_with_mcp(mcp)
```

The `graphql_tool` side-effect import added above wires it automatically. **No changes to `commands.py` are needed.**

### 4. Auth / user context

`execute_query` accepts `user=user` directly and passes it as `request.user` in the GraphQL context. This means Nautobot's row-level permission system (`QuerySet.restrict()`) works transparently — the same as the REST API GraphQL endpoint. No custom permission logic needed.

The user comes from `get_user_from_request(ctx)`, which reads the `Authorization: Token <hex>` header from the MCP request (cached per FastMCP session). This is identical to all existing tools.

### 5. `tool_registry.json` (cross-process discovery)

The `MCPToolRegistry` is already written to `tool_registry.json` at `ready()` time. The new `graphql_query` tool will be automatically included because it is registered via `@register_tool` in the same side-effect import path. No changes needed.

### 6. Input schema generation

`func_signature_to_input_schema` (used by `@register_tool`) derives the JSON Schema from Python type hints automatically. The handler signature:

```python
async def _graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Produces `inputSchema` with `query: { type: "string" }` and `variables: { type: "object" }` — no manual schema needed.

## What NOT to Add

- **Do NOT add `graphene-django` explicitly to `pyproject.toml`** — it is already available as a transitive dep of `nautobot`. Pinning a conflicting version risks breaking Nautobot's own GraphQL stack.
- **Do NOT create a new Django schema** — reuse `nautobot.core.graphql.schema` (or call `execute_query` which uses `graphene_settings.SCHEMA.graphql_schema` internally). Building a parallel schema would miss Nautobot's `extend_schema_type` dynamic features (custom fields, relationships, tags, config contexts, computed fields, multi-level filtering).
- **Do NOT add `models.py`, `filters.py`, `forms.py`, `api/`, or `migrations/`** — the app has no database models and adding them would violate the established app architecture (documented in CLAUDE.md).
- **Do NOT add a new HTTP endpoint** — the GraphQL tool is an MCP tool callable via `tools/call`, not a standalone HTTP route. FastMCP handles transport.
- **Do NOT add authentication logic beyond `get_user_from_request`** — token auth and session caching are already implemented. The GraphQL tool inherits them automatically.
- **Do NOT wrap `execute_query` in a custom async function with its own thread pool** — use `sync_to_async(..., thread_sensitive=True)` exactly as `query_utils.py` does. Custom executors risk the same "Connection not available" errors documented in the gotchas.
- **Do NOT add a separate GraphQL HTTP endpoint** — not needed; the MCP tool IS the GraphQL interface.

## Version Considerations

### Nautobot compatibility

Nautobot 3.x bundles GraphQL via `nautobot.core.graphql` with a stable API:

- `execute_query(query, variables, user)` — stable since Nautobot 1.x
- `nautobot.core.graphql.schema` — dynamically generated at startup, stable interface
- `OptimizedNautobotObjectType` (from `nautobot.core.graphql.types`) — base class for all Nautobot GraphQL types
- `graphene_settings.SCHEMA.graphql_schema` — the canonical schema used by `execute_query`
- `graphene_django_optimizer` (`gql_optimizer.OptimizedDjangoObjectType`) — powers efficient ORM queries

All of these are internal Nautobot APIs, not third-party APIs. They have been stable across Nautobot 2.x and 3.x. No version-gating is required for Nautobot `>=3.0.0, <4.0.0`.

### graphene-django version constraint

If a future custom schema is needed and `graphene-django` must be pinned explicitly, constrain it to be compatible with what Nautobot already resolves:

```toml
graphene-django = ">=3.0,<4.0"  # matches nautobot's own requirement
```

However, for this milestone, rely on Nautobot's transitive dependency and do not add an explicit pin or a new direct dependency.

### Python version

No constraints beyond the existing `>=3.10,<3.15`. All GraphQL libraries support this range.

### Thread sensitivity

`execute_query` calls Django ORM internally. All ORM calls triggered by the GraphQL resolver chain (e.g., `device.tags.all()`, `location.devices.all()`) go through Nautobot's filtersets and custom resolvers. Using `sync_to_async(..., thread_sensitive=True)` is required to route those ORM calls through Django's main-thread database connection pool, matching the established pattern in `query_utils.py`.

### FastMCP compatibility

The new tool follows the exact same handler pattern as the 10 existing tools:
- `async def handler(ctx: ToolContext, ...)` signature
- `await get_user_from_request(ctx)` for auth
- `sync_to_async(..., thread_sensitive=True)` for ORM
- `output_schema=None` passed to `mcp.tool()` via `register_all_tools_with_mcp`

This is fully compatible with FastMCP 3.x and the existing tool registration architecture.

## Files to Add

| File | Purpose |
|---|---|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | New GraphQL MCP tool (`graphql_query` handler) |
| `nautobot_app_mcp_server/mcp/tools/__init__.py` | Add `graphql_tool` side-effect import |

No modifications to existing files are required for the tool registration wiring — the side-effect import in `__init__.py` and the existing `register_all_tools_with_mcp()` call in `commands.py` handle everything automatically.