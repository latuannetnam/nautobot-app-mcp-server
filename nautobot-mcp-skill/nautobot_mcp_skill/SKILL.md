# Nautobot MCP Server — AI Agent Skill

Version: 0.1.0a0
Last Updated: 2026-04-06
Nautobot: >=3.0.0, <4.0.0

---

## Overview

This skill provides MCP tools for querying Nautobot network inventory data. All tools enforce Nautobot object-level permissions. Tool visibility is controlled via session scopes (`mcp_enable_tools` / `mcp_disable_tools`).

---

## Quick Start

**MCP Endpoint:** `http://localhost:8005/mcp/` (standalone FastMCP server, v1.2.0+)

- Call `mcp_list_tools()` to discover all available tools for the current session
- Call `mcp_enable_tools(scope="dcim")` to enable DCIM tools (devices, interfaces)
- Call `mcp_enable_tools(scope="ipam")` to enable IPAM tools (prefixes, VLANs, IP addresses)
- Core tools (`device_list`, `device_get`, etc.) are always available without enabling

---

## Pagination

All list tools use cursor-based pagination:

- **Default limit:** 25 items per request
- **Maximum limit:** 1000 items per request
- **Cursor format:** `base64(str(pk))` — opaque token returned in the `cursor` field of the previous response
- **Summarize at 100:** When total results exceed 100, the response includes a `summary` dict with `total_count` and a message. Raw items are still returned.
- **Next page:** Pass the `cursor` value from the previous response as the `cursor` parameter

---

## Core Tools

| Tool | Description | Parameters | Paginated |
|---|---|---|---|
| device_list | List network devices with status, platform, location, and more. | `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| device_get | Get a single device by name or ID, with interfaces prefetched. | `name_or_id: str` | No |
| interface_list | List network interfaces, optionally filtered by device name. | `device_name?: str`, `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| interface_get | Get a single interface by name or ID, with IP addresses prefetched. | `name_or_id: str` | No |
| ipaddress_list | List IP addresses with tenant, VRF, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| ipaddress_get | Get a single IP address by address or ID, with interfaces prefetched. | `name_or_id: str` | No |
| prefix_list | List network prefixes with VRF, tenant, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| vlan_list | List VLANs with site/group, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| location_list | List locations with location type, parent, and tenant. | `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| search_by_name | Multi-model name search across devices, interfaces, IP addresses, prefixes, VLANs, and locations. All search terms must match (AND semantics). | `query: str`, `limit?: int (default=25, max=1000)`, `cursor?: str` | Yes |
| graphql_query | Execute an arbitrary GraphQL query against Nautobot's GraphQL API. Returns {data, errors}. | `query: str`, `variables?: dict | None` | No |
| graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. Use to discover available types and fields. | (none) | No |

---

## GraphQL Tools

Nautobot exposes a full [graphene-django](https://docs.graphene-python.org/projects/django/)
GraphQL API. These tools let you execute arbitrary GraphQL queries and introspect the
schema directly from the MCP server.

| Tool | Description | Parameters |
|------|-------------|------------|
| graphql_query | Execute an arbitrary GraphQL query. Returns `{"data": ..., "errors": [...]}` — both keys always present. | `query: str`, `variables?: dict | None` |
| graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. Use to discover available types and fields before writing queries. | (none) |

### graphql_query

Execute arbitrary GraphQL queries against Nautobot's graphene-django schema.
Auth token is required — anonymous queries return `{"data": null, "errors": [{"message": "Authentication required"}]}`.

**Parameters:**
- `query: str` — GraphQL query string (required)
- `variables: dict | None` — Optional variables for parameterized queries (default: `None`)

**Result shape:**
```json
{
  "data": { ... } | null,
  "errors": [ { "message": "...", "locations": [...], "path": [...] } ] | null
}
```
Both `data` and `errors` keys are always present. If a query succeeds with no errors,
`errors` is `null`. If a query fails, `data` is `null`.

**Error cases:** Errors are returned in the `errors` array (HTTP 200, no HTTP 500):
- `"Authentication required"` — missing or invalid token
- `"Query depth N exceeds maximum allowed depth of 8"` — query too deeply nested
- `"Query complexity N exceeds maximum allowed complexity of 1000"` — query selects too many fields
- `"Syntax Error: ..."` — malformed GraphQL syntax

**Example — Simple device listing:**
```graphql
query {
  devices(limit: 10) {
    name
    status {
      name
    }
  }
}
```
```python
result = mcp.call_tool("graphql_query", {
    "query": "query { devices(limit: 10) { name status { name } } }"
})
# → {"data": {"devices": [...]}, "errors": null}
```

**Example — With variables:**
```graphql
query GetDevices($limit: Int!) {
  devices(limit: $limit) {
    name
    status {
      name
    }
    platform { name }
    location { name }
  }
}
```
```python
result = mcp.call_tool("graphql_query", {
    "query": "query GetDevices($limit: Int!) { devices(limit: $limit) { name status { name } platform { name } location { name } } }",
    "variables": {"limit": 5}
})
# → {"data": {"devices": [...]}, "errors": null}
```

### graphql_introspect

Returns the full Nautobot GraphQL schema as a GraphQL SDL string. Use this to discover
available object types, fields, and relationships before writing queries. Auth token required.

**Returns:** Multi-line SDL string (e.g. `"type Query {\\n  devices: [Device]!\\n  ...\\n}"`)

**Example:**
```python
sdl = mcp.call_tool("graphql_introspect", {})
# "schema {\\n  query: Query\\n}\\ntype Query {\\n  devices(first: Int): [Device]\\n  ..."
print(sdl)  # View all available types and fields
```

---

## GraphQL-Only Mode

By default, the MCP server runs in GraphQL-only mode — only `graphql_query` and `graphql_introspect` are visible and callable. All other tools (10 core read tools + 3 session tools) are hidden from the manifest and blocked at call time.

To enable all 15 tools, set `NAUTOBOT_MCP_ENABLE_ALL=true` and restart the server.

| Env Variable | Default | Effect |
|---|---|---|
| `NAUTOBOT_MCP_ENABLE_ALL` | not set (=GQL-only mode) | `true` = all 15 tools visible; unset = only GraphQL tools visible |

---

## Meta Tools

| Tool | Description | Parameters |
|---|---|---|
| mcp_enable_tools | Enable tool scopes or fuzzy-search matches for this session. | `scope?: str`, `search?: str` |
| mcp_disable_tools | Disable a tool scope for this session. | `scope?: str` |
| mcp_list_tools | Return all registered tools visible to this session. | (none) |

---

## Scope Management

Three tool scopes are available:

- `core` — Always enabled. Contains: `device_list`, `device_get`, `interface_list`, `interface_get`, `ipaddress_list`, `ipaddress_get`, `prefix_list`, `vlan_list`, `location_list`, `search_by_name`, `graphql_query`, `graphql_introspect`, plus `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools`.
- `dcim` — Devices and interfaces. Child scopes: `dcim.device`, `dcim.interface`.
- `ipam` — IP addresses, prefixes, VLANs, locations. Child scopes: `ipam.prefix`, `ipam.vlan`, `ipam.ip`, `ipam.location`.

### Enable/Disable Examples

- `mcp_enable_tools(scope="dcim")` — Enables all DCIM tools. Stays active for the session.
- `mcp_enable_tools(scope="dcim.interface")` — Enables only interface tools.
- `mcp_disable_tools(scope="dcim")` — Disables DCIM tools and all their child scopes.
- `mcp_disable_tools()` (no args) — Disables all non-core tools.
- `mcp_enable_tools(search="bgp")` — Enables all tools whose name or description fuzzy-matches "bgp".

### Scope Hierarchy

Enabling a parent scope (e.g. `dcim`) automatically activates all child scopes (e.g. `dcim.device`, `dcim.interface`) via prefix matching. The `mcp_disable_tools(scope="dcim")` call removes `dcim` and any scopes starting with `dcim.` from the session.

### Session State Persistence

Session state is stored per `Mcp-Session-Id` header. State persists for the duration of the MCP session but is lost on server restart (in-memory, not persisted to disk).

### Tool Visibility Flow

1. MCP client connects → session created with no enabled scopes
2. Client calls `mcp_list_tools()` → only core tools returned (13 total)
3. Client calls `mcp_enable_tools(scope="ipam")` → IPAM tools now visible in `mcp_list_tools()`
4. Client calls `mcp_disable_tools(scope="ipam")` → IPAM tools hidden again
5. Client calls `mcp_enable_tools(search="vlan")` → tools matching "vlan" in name/description become visible

### Scope and Search Combination

Scopes and searches can be combined. Multiple `mcp_enable_tools` calls accumulate:

```
mcp_enable_tools(scope="dcim")
mcp_enable_tools(scope="ipam")
mcp_enable_tools(search="router")
```

Result: All tools in `dcim` + all tools in `ipam` + all tools matching "router" are visible.

### Resetting Session State

To reset all non-core tools:

```
mcp_disable_tools()  # no arguments — clears all enabled scopes and searches
```

### mcp_list_tools Response Format

`mcp_list_tools()` returns a multi-line string:

```
Core tools (13):
  - device_list
  - device_get
  ...

Enabled scopes (2):
  [ipam] (4 tools)
    - ipaddress_list
    ...

Active searches (1):
  'router' → 3 tools
```

This helps you audit what is currently enabled without guessing.

---

## Investigation Workflows

### Workflow 1: Investigate a Device by Name

**Goal:** Get full device details and its network interfaces.

1. `search_by_name(query="router-01")` — Find the device; note its `pk`.
2. `device_get(name_or_id="router-01")` — Get device with status, platform, location, and nested interfaces.
3. `interface_list(device_name="router-01", limit=50)` — List all interfaces on this device.
4. `interface_get(name_or_id="<interface pk>")` — Get a specific interface with its IP addresses.

### Workflow 2: Find IP Addresses in a Prefix

**Goal:** List all IP addresses within a given prefix.

1. `prefix_list(limit=25)` — Browse prefixes; find the target prefix, note its `pk`.
2. `ipaddress_list(limit=100)` — List IP addresses; use cursor pagination to scan through addresses in the target range.
3. Alternatively: `search_by_name(query="10.0.0")` — Fuzzy search for IPs in the 10.0.0.x range.

### Workflow 3: Explore Device Interfaces and IP Addresses

**Goal:** Get a device's interfaces and their assigned IP addresses.

1. `device_get(name_or_id="router-01")` — Verify the device exists; note its name.
2. `interface_list(device_name="router-01", limit=100)` — List all interfaces with `mac_address` and `description`.
3. `interface_get(name_or_id="<interface pk>")` — Get a specific interface; response includes nested `ip_addresses` with `address`, `tenant`, `vrf`.
4. Use the IPs from step 3 in `ipaddress_get(name_or_id="<ip pk>")` for full IP details.

---

## Limitations

- Write tools (create/update/delete) are not available in v1.
- Results are subject to Nautobot object-level permissions (`.restrict(user, action="view")`).
- Cursor pagination uses `pk__gt` — results are ordered by primary key insertion order.
- Session state is in-memory (not persisted across server restarts).
- `search_by_name` performs sequential per-model queries with in-memory merge (no cross-model DB cursor).
