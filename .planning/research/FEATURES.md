# Features Research — GraphQL MCP Tool

<research_type>Project Research — Features for GraphQL MCP tool.</research_type>

<summary>
A GraphQL MCP tool for Nautobot exposes a single MCP endpoint (e.g. `graphql_query`) that accepts
arbitrary GraphQL query strings, variables, and operation names, then executes them against
Nautobot's built-in GraphQL schema via graphene-django. Unlike the existing 10 pre-built
RPC-style tools (device_list, interface_get, etc.), a GraphQL tool lets AI agents craft
precise, nested data fetches (e.g. "all devices in site X with their interfaces, IPs, and VLANs
in a single round-trip"). The tool must integrate with Nautobot's existing token auth and
ORM permission model, wrapping the Django ORM in sync_to_async, and must return results in
a JSON-serializable dict that FastMCP can surface to the agent. Nautobot already ships with
graphene-django and exposes /api/graphql/ natively; the MCP tool wraps that capability as a
single tool rather than requiring the agent to know the REST or GraphQL endpoint URL.
</summary>

## Table Stakes Features

These are required for any GraphQL MCP tool — without them it simply won't work or will be
dangerous in production.

| Feature | What It Is | Why Required | Implementation Note |
|---------|------------|--------------|---------------------|
| **Auth token enforcement** | Read `Authorization: Token <hex>` from MCP request headers; resolve to Nautobot User | Nautobot's `.restrict(user, action="view")` depends on knowing the calling user; anonymous = empty results | Reuse existing `get_user_from_request()` from `mcp/auth.py` inside the async handler |
| **GraphQL query execution** | Accept a GraphQL query string + optional variables + operation name; return the JSON result | The core of the tool — what makes it a "GraphQL" tool, not just a REST wrapper | `execute_graphql(query, variables, operation_name, user)` — wraps Nautobot's `execute_graphql()` or graphene's `schema.execute()` |
| **Permission enforcement** | Apply Nautobot object permissions to the GraphQL result (not just auth — actual row-level filtering) | Without it, any authenticated user sees everything, bypassing Nautobot's permission model | Graphene-django `DjangoPermissionMode` or manual `.restrict()` on every queryset referenced in the query |
| **JSON-serializable return** | Return a plain `dict` — `{data, errors, extensions}` from the GraphQL execution | FastMCP requires dict/list/primitives; graphene returns `ExecutionResult` which must be `.to_dict()`-ed | `result.to_dict()` on graphene `ExecutionResult` |
| **Query complexity / depth limits** | Prevent deeply nested or expensive queries (e.g. 10 levels of interfaces→IPs→DNS→...) | No limit = DoS vector against the database | graphene `max_depth` or a custom validation rule; Nautobot's own GraphQL layer may have limits |
| **Error handling** | Return GraphQL errors as structured `errors` array in the response dict, not as HTTP 500s | AI agents need structured errors to understand what went wrong; crashing the tool is bad UX | Catch graphene `GraphQLError`, format as `{"errors": [{"message": ..., "path": ..., "locations": ...}]}` |
| **async wrapper** | All ORM calls inside GraphQL execution must be thread-safe; MCP tools are async | FastMCP thread pool ≠ Django main thread; skipping `thread_sensitive=True` causes "Connection not available" errors | `await sync_to_async(execute_graphql_fn, thread_sensitive=True)(...)` |
| **Input schema** | Accept at minimum: `query: str`, `variables: dict | None`, `operation_name: str | None` | FastMCP needs typed inputs; agents need to know what to pass | Standard MCP input schema with these three string/optional-object fields |

## Differentiators

These features go beyond "it works" and make the GraphQL tool genuinely useful for AI agents
querying network inventory.

| Feature | Value to AI Agent | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Schema introspection tool** | Agent can ask "what types are available?" and get the full Nautobot GraphQL schema | LOW | Register a second tool `graphql_introspect` that returns the schema SDL; agents use this to learn what to query |
| **Nested prefetch optimization hints** | Accept a `prefetch` or `select` param (or auto-detect) to add `select_related`/`prefetch_related` to reduce N+1 queries | MEDIUM | Nautobot's graphene-django types already define `get_queryset()` with prefetch; but arbitrary user queries may bypass these |
| **Pagination relay support** | GraphQL pagination (cursor/offset) via the Connection/slice spec | MEDIUM | Nautobot's GraphQL schema uses `django-filter` + graphene relay; exposing this correctly is complex but powerful |
| **Named query registry (saved queries)** | Allow agents to execute pre-registered named queries (e.g. "device_with_full_network_stack") by name | LOW-MED | Store named GraphQL query strings in a config dict or JSON; agents reference by name instead of writing raw queries |
| **Dry-run / validation mode** | Accept `validate_only: bool = True` — parse and validate the query without executing it | LOW | Useful for AI agents to check query validity before running expensive queries |
| **Query result caching** | Cache repeated identical queries for N seconds using the FastMCP session or a TTL cache | MEDIUM | GraphQL queries are deterministic; caching reduces DB load for repeated agent questions |
| **Multi-query execution** | GraphQL spec allows multiple operations in one request; support executing all at once | MEDIUM | Each operation returns separately in the `data` dict keyed by operation name |
| **Rich error formatting** | Return structured error objects with `path`, `locations`, `extensions` (not just a message string) | LOW | graphene's `ExecutionResult.to_dict()` already provides this; ensure it is passed through unchanged |

## Complexity Notes

What makes a GraphQL MCP tool non-trivial to implement correctly.

### 1. Permission enforcement is not automatic

GraphQL's flexibility is also its danger: an agent can write `query { ip_addresses { host tenant { name } } }`
and see everything in the database unless permissions are enforced. Nautobot's GraphQL layer uses
`DjangoPermissionMode` from graphene-django which applies `.restrict(user, "view")` to every
Django-model-backed type automatically. However, if the MCP tool bypasses Nautobot's GraphQL
layer and calls `schema.execute()` directly, it must ensure the permission middleware is active.
**Best approach:** Use Nautobot's built-in GraphQL execution path (`nautobot_graphql_django schema.execute`)
rather than building a new graphene schema from scratch.

### 2. N+1 query problem with arbitrary queries

Pre-built tools (device_list, interface_get) use `select_related`/`prefetch_related` chains
to fetch FK/M2M relations in 1-2 queries. Arbitrary GraphQL queries can request any depth of
relations (devices → interfaces → ip_addresses → dns_name → ...) triggering N+1 queries
on every resolve. The DataLoader pattern (batching + caching per request) is the standard fix
but requires careful implementation per type.

### 3. Query depth/complexity limits

Without a depth limiter, an adversarial or careless query can recurse infinitely or explode
into thousands of DB rows. Graphene supports `max_depth`, `max_complexity` validation options.
Set these conservatively (e.g., depth ≤ 8, complexity ≤ 1000) and make them configurable.

### 4. Variable injection security

GraphQL variables (`$device_id: UUID!`) must be validated separately from the query string.
If the tool accepts raw variables dicts from the MCP caller, it must validate that variable
values are of the expected types (not arbitrary Python objects). graphene handles this safely
but the interface between MCP (JSON-RPC) and GraphQL (variables dict) must be clean.

### 5. Thread sensitivity in async context

GraphQL execution in Django typically runs synchronously. The `schema.execute()` call must
be wrapped in `sync_to_async(..., thread_sensitive=True)` — not `False`. Using `False`
causes "Connection not available" errors in the FastMCP thread pool because Django's
connection pool is thread-sensitive. This is the same gotcha as all other ORM tools in
this codebase.

### 6. MCP output_schema compatibility

FastMCP auto-derives the output schema from the Python return type annotation. Since the
return is `dict[str, Any]` (generic), FastMCP sets `outputSchema = {"type": "object"}` by
default. The GraphQL result is a dict with `data`, `errors`, and optionally `extensions` —
this is compatible. Pass `output_schema=None` to the `@mcp.tool()` decorator to suppress
any output validation (same pattern used by all existing tools in `core.py`).

### 7. No standalone graphene-django dependency needed

Nautobot already bundles graphene-django. The MCP tool should not add a new direct dependency
on `graphene-django` if Nautobot already provides it transitively. Query execution should go
through `nautobot_graphql_django` or the registered Nautobot GraphQL schema, not by building
a new schema from scratch. This avoids schema duplication and ensures permission enforcement
is inherited automatically.

## Dependencies

The GraphQL MCP tool builds on existing patterns and infrastructure in this codebase.

```
[get_user_from_request() — mcp/auth.py]
    └── Already implemented: resolves Authorization: Token header to Nautobot User
          └── Used by: all existing tools (core.py) — no new auth code needed

[MCPToolRegistry — mcp/registry.py]
    └── Already implemented: register_mcp_tool() / @register_tool decorator
          └── GraphQL tool: @register_tool(name="graphql_query", tier="core", scope="core")
                └── Same decorator pattern as all 10 existing tools

[sync_to_async(..., thread_sensitive=True) — query_utils.py pattern]
    └── Already implemented: wraps all ORM calls in async context
          └── GraphQL tool: wrap schema.execute() or Nautobot GraphQL executor in same wrapper

[PAGINATED_RESULT — mcp/tools/pagination.py]
    └── Not directly used: GraphQL handles its own pagination via Connection/slice spec
          └── Exception: if pagination is added as an MCP-layer wrapper, use existing PaginatedResult

[tool_registry.json — __init__.py ready() hook]
    └── Already implemented: writes tool definitions at startup
          └── GraphQL tool: auto-registered via @register_tool decorator import

[output_schema=None — mcp/tools/__init__.py register_all_tools_with_mcp()]
    └── Already implemented: pass output_schema=None to suppress FastMCP output validation
          └── GraphQL tool: same pattern — return dict, pass output_schema=None

[Nautobot graphene-django]
    └── Already present as Nautobot transitive dep
          └── GraphQL tool: use Nautobot's registered GraphQL schema, not a new schema
```

## Nautobot Models to Expose

Nautobot's built-in GraphQL schema already exposes these models via graphene-django types.
The MCP tool's query executor delegates to this schema. The agent can query any of these
types (and their relations) as long as they are present in Nautobot's GraphQL schema.

| Model | App | GraphQL Type Name | Key Fields | Relations to Include |
|-------|-----|-------------------|------------|----------------------|
| `dcim.Device` | dcim | `Device` | `id`, `name`, `serial`, `status`, `role`, `platform`, `asset_tag`, `description` | `device_type`, `manufacturer`, `location`, `tenant`, `primary_ip4`, `primary_ip6`, `interfaces`, `console_ports`, `power_ports` |
| `dcim.Interface` | dcim | `Interface` | `id`, `name`, `enabled`, `type`, `mtu`, `mac_address`, `mode`, `description`, `mgmt_only` | `device`, `status`, `role`, `lag`, `parent_interface`, `bridge`, `ip_addresses`, `untagged_vlan`, `tagged_vlans` |
| `ipam.IPAddress` | ipam | `IPAddress` | `id`, `host`, `dns_name`, `ip_version`, `status`, `role`, `description` | `tenant`, `vrf`, `interfaces`, `nat_inside`, `nat_outside` |
| `ipam.Prefix` | ipam | `Prefix` | `id`, `prefix`, `status`, `role`, `description`, `date_allocated` | `tenant`, `vrf`, `namespace`, `locations`, `vlans`, `rir` |
| `ipam.VLAN` | ipam | `VLAN` | `id`, `name`, `vid`, `status`, `role`, `description` | `tenant`, `site`, `group`, `locations`, `prefixes` |
| `dcim.Location` | dcim | `Location` | `id`, `name`, `description`, `status` | `location_type`, `parent`, `tenant`, `devices`, `prefixes`, `vlans` |
| `dcim.Platform` | dcim | `Platform` | `id`, `name`, `slug`, `manufacturer` | `devices`, `napalm_args` |
| `dcim.DeviceType` | dcim | `DeviceType` | `id`, `model`, `slug`, `part_number` | `manufacturer`, `device_count`, `interfaces` |
| `dcim.Manufacturer` | dcim | `Manufacturer` | `id`, `name`, `slug` | `device_types`, `platforms` |
| `ipam.VRF` | ipam | `VRF` | `id`, `name`, `rd`, `description` | `prefixes`, `ip_addresses` |
| `ipam.Namespace` | ipam | `Namespace` | `id`, `name`, `description` | `prefixes` |
| `ipam.RIR` | ipam | `RIR` | `id`, `name`, `slug` | `aggregates`, `rir_count` |
| `extras.Status` | extras | `Status` | `id`, `name`, `slug`, `color` | Used as enum on all status fields |
| `extras.Role` | extras | `Role` | `id`, `name`, `slug` | Used as enum on role fields |
| `extras.Tenant` | extras | `Tenant` | `id`, `name`, `slug`, `description` | `devices`, `prefixes`, `vlans`, `ip_addresses`, `tenant_group` |
| `extras.Tag` | extras | `Tag` | `id`, `name`, `slug`, `color` | M2M on most models |

### Relationships available for nested queries

```
Device
  ├── interfaces[] ──→ Interface
  │                      ├── ip_addresses[] ──→ IPAddress
  │                      ├── tagged_vlans[] ──→ VLAN
  │                      └── untagged_vlan ──→ VLAN
  ├── location ──→ Location
  │                  ├── parent ──→ Location (recursive)
  │                  └── location_type ──→ LocationType
  ├── platform ──→ Platform
  │                 └── manufacturer ──→ Manufacturer
  ├── device_type ──→ DeviceType
  │                   └── manufacturer ──→ Manufacturer
  ├── tenant ──→ Tenant
  │               └── tenant_group ──→ TenantGroup
  └── primary_ip4 ──→ IPAddress

Prefix
  ├── vrf ──→ VRF
  ├── locations[] ──→ Location
  ├── vlans[] ──→ VLAN
  └── namespace ──→ Namespace

VLAN
  ├── location ──→ Location
  ├── group ──→ VLANGroup
  ├── tenant ──→ Tenant
  └── prefixes[] ──→ Prefix
```

### Important: Not all fields are exposed in GraphQL

Nautobot's GraphQL schema intentionally omits certain fields (e.g., `custom_field_data`,
`computed_fields`) and some sensitive fields. The MCP tool is constrained by what
Nautobot's GraphQL schema exposes. Agents writing GraphQL queries must introspect the schema
to discover available fields. A `graphql_introspect` tool that returns the SDL is therefore
a high-value companion tool.

---

*Feature research for: GraphQL MCP tool addition to nautobot-app-mcp-server*
*Researched: 2026-04-15*
