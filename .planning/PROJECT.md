# Nautobot App MCP Server

## What This Is

A Nautobot App that exposes a Model Context Protocol (MCP) server as a standalone FastMCP process (separate from Nautobot's Django process), enabling AI agents (Claude Code, Claude Desktop) to interact with Nautobot data via MCP tools. The MCP server runs on port 8005, uses direct Django ORM, and supports progressive disclosure of tools — 13 core tools always available, with GraphQL access via `graphql_query` and `graphql_introspect`.

## Core Value

AI agents can query Nautobot network inventory data via MCP tools with full Nautobot permission enforcement, zero extra network hops, and progressive tool discovery — now including arbitrary GraphQL access.

## Requirements

### Validated

- [x] Standalone MCP server on port 8005 via Django management commands (`start_mcp_server.py`, `start_mcp_dev_server.py`) — v1.2.0
- [x] `start_mcp_dev_server.py` — `create_app()` factory + uvicorn with auto-reload — v1.2.0
- [x] `tool_registry.json` — cross-process discovery; written by plugin `ready()`, read by MCP server `create_app()` at startup — v1.2.0
- [x] `@register_tool` decorator — auto-generates JSON Schema from Python type hints; dual registration (in-memory `MCPToolRegistry` + FastMCP) — v1.2.0
- [x] 15 Core tools: 10 read tools + 3 meta tools + 2 GraphQL tools — v1.0/v2.0
- [x] Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` (no monkey-patching) — v1.2.0
- [x] Auth: token from FastMCP request headers, cached via `ctx.set_state("mcp:cached_user")` — v1.2.0
- [x] Nautobot token auth + object-level permissions via `.restrict(user, action="view")` — v1.0
- [x] Cursor-based pagination (limit default=25, max=1000) — v1.0
- [x] `nautobot-mcp-skill` SKILL.md package with tool reference — v1.0
- [x] `graphql_query` MCP tool — arbitrary GraphQL queries via `nautobot.core.graphql.execute_query()` — v2.0
- [x] `graphql_introspect` MCP tool — returns Nautobot schema as SDL string — v2.0
- [x] Query depth limit (≤8) and complexity limit (≤1000) — v2.0
- [x] Structured GraphQL errors (HTTP 200, `{"data": null, "errors": [...]}`) — v2.0

### Active

- [ ] Write tools (create/update/delete) — deferred to v3.0
- [ ] Redis session backend for `--workers > 1` horizontal scaling — deferred to v3.0

### Out of Scope

- Write tools — deferred to v3.0 (permission surface widens significantly)
- MCP `resources` or `prompts` endpoints — focus is tools first
- Tool-level field permissions — deferred

## Context

**Current state (v2.0 shipped):**
- MCP server: standalone FastMCP process on port 8005, managed via Docker Compose `mcp-server` service
- `invoke start` launches both Nautobot (8080) and MCP server (8005) automatically
- 15 tools registered: 10 read (device, interface, ipaddress, prefix, vlan, location, search) + 3 meta + 2 GraphQL
- Auth: Nautobot API token via `Authorization: Token <hex>` header; user cached per FastMCP session
- GraphQL: `graphql_query` (arbitrary queries) + `graphql_introspect` (schema SDL), both depth/complexity limited
- Unit tests: 103/103 pass; UAT: 44/44 passed
- Tech stack: FastMCP 3.2.0, uvicorn, Django ORM via `sync_to_async(thread_sensitive=True)`, graphql-core 3.2.8

**v1.0/v1.1 legacy (deleted in v1.2.0):**
- `view.py`, `server.py`, `urls.py` — WSGI→ASGI bridge removed
- `mcp._list_tools_mcp` override — replaced by `ScopeGuardMiddleware`
- `RequestContext._mcp_tool_state` monkey-patch — replaced by FastMCP `ctx.get_state()`

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Standalone FastMCP process (Option B) | Cleaner separation; avoids WSGI→ASGI bridge complexity; production-realistic | ✅ Shipped v1.2.0 |
| FastMCP HTTP transport (not SSE) | Standard MCP client compatibility | ✅ Shipped v1.2.0 |
| `tool_registry.json` replaces `post_migrate` | `post_migrate` never fires in standalone MCP server process | ✅ Shipped v1.2.0 |
| `output_schema=None` in `register_all_tools_with_mcp()` | Fixes FastMCP/MCP SDK outputSchema conflict (auto-derivation triggers MCP SDK validation error) | ✅ Shipped v1.2.0 |
| Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` | `ServerSession` has no dict interface; `MemoryStore` is the native FastMCP API | ✅ Shipped v1.2.0 |
| Cursor separator `@` not `.` | UUIDs contain dots; base64-encoded cursor would split UUID at wrong position | ✅ Shipped v1.2.0 |
| `--workers 1` documented | In-memory sessions; multi-worker requires Redis backend (v2.0) | ✅ Shipped v1.2.0 |
| Reuse `nautobot.core.graphql.execute_query()` | Stable since Nautobot 1.x; handles permissions internally; avoids duplicating `extend_schema_type` dynamic features | ✅ Shipped v2.0 |
| Reuse `nautobot.core.graphql.schema` | Parallel schema misses Nautobot's custom fields, tags, computed fields | ✅ Shipped v2.0 |
| Depth ≤8, Complexity ≤1000 | Conservative defaults; prevents deeply-nested and expensive DoS without blocking useful queries | ✅ Shipped v2.0 |
| `graphql_introspect` as separate tool | Returns schema SDL so AI agents discover available types/fields without out-of-band docs | ✅ Shipped v2.0 |
| Structured errors, not HTTP 500s | GraphQL errors returned as `errors` array; syntax errors never throw unhandled exceptions | ✅ Shipped v2.0 |
| No new poetry dependencies | All required packages (graphene-django, graphql-core) are already Nautobot transitive deps | ✅ Shipped v2.0 |

---

## Current Milestone: v2.1 — GraphQL-Only Mode

**Goal:** Add a config-driven env var (`NAUTOBOT_MCP_GRAPHQL_ONLY=true`) that restricts the MCP server to exposing only `graphql_query` and `graphql_introspect`, hiding all session tools and core read tools.

**Target features:**
- `NAUTOBOT_MCP_GRAPHQL_ONLY` env var support — read at server startup
- `_list_tools_handler` filter — returns only the two GraphQL tools when flag is active
- `ScopeGuardMiddleware` enforcement — blocks calls to all non-GraphQL tools at tool-call time
- Unit tests for the new filtering logic
- CLAUDE.md / SKILL.md documentation update

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):

1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):

1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

*Last updated: 2026-05-04 — milestone v2.1 GraphQL-Only Mode started*
