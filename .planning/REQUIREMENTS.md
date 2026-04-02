# Requirements: Nautobot App MCP Server

**Defined:** 2026-04-01
**Core Value:** AI agents can query Nautobot network inventory data via MCP tools with full Nautobot permission enforcement, zero extra network hops, and progressive tool discovery.

---

## v1 Requirements

### Foundation

- [ ] **FOUND-01**: Add `mcp`, `fastmcp`, and `asgiref` dependencies to `pyproject.toml`
- [ ] **FOUND-02**: Create `nautobot_app_mcp_server/mcp/` package structure
- [ ] **FOUND-03**: Resolve package name mismatch — use `nautobot_app_mcp_server` everywhere (not `nautobot_mcp_server`)
- [ ] **FOUND-04**: Resolve `base_url` — use `nautobot-app-mcp-server` (matches package name convention), endpoint at `/plugins/nautobot-app-mcp-server/mcp/`
- [ ] **FOUND-05**: Fix `NotImplementedError` in DESIGN.md Option A — implement ASGI bridge via `asgiref.wsgi.WsgiToAsgi`

### MCP Server Infrastructure

- [ ] **SRVR-01**: FastMCP instance with `stateless_http=False`, `json_response=True`
- [ ] **SRVR-02**: `get_mcp_app()` lazy factory — ASGI app created on first HTTP request (not at import time)
- [ ] **SRVR-03**: `streamable_http_app()` mounted at `/plugins/nautobot-app-mcp-server/mcp/` via Django URL route
- [ ] **SRVR-04**: ASGI bridge view (`WsgiToAsgi`) converting Django request → FastMCP ASGI → Django response
- [ ] **SRVR-05**: `urls.py` with `path("mcp/", mcp_view)` — auto-discovered by Nautobot plugin system
- [ ] **SRVR-06**: `post_migrate` signal wiring core tools registration after all apps' `ready()` hooks

### Tool Registry

- [ ] **REGI-01**: `MCPToolRegistry` thread-safe singleton with `threading.Lock`
- [ ] **REGI-02**: `ToolDefinition` dataclass with name, func, description, input_schema, tier, scope fields
- [ ] **REGI-03**: `register_mcp_tool()` public API for third-party Nautobot apps
- [ ] **REGI-04**: `get_core_tools()`, `get_by_scope()`, `fuzzy_search()` registry methods
- [ ] **REGI-05**: `@mcp.list_tools()` override for progressive disclosure — returns session-active tools only

### Authentication & Permissions

- [ ] **AUTH-01**: `get_user_from_request()` extracting Nautobot user from MCP request context `Authorization: Token nbapikey_xxx` header
- [ ] **AUTH-02**: `AnonymousUser` returns empty queryset (not error) with debug warning logged
- [ ] **AUTH-03**: Nautobot object-level permissions via `.restrict(user, action="view")` on every queryset

### Session State

- [ ] **SESS-01**: `MCPSessionState` dataclass with `enabled_scopes` and `enabled_searches`
- [ ] **SESS-02**: Session state stored per `Mcp-Session-Id` via FastMCP `StreamableHTTPSessionManager`
- [ ] **SESS-03**: `mcp_enable_tools(scope=...)` tool enabling exact scope + children and fuzzy search
- [ ] **SESS-04**: `mcp_disable_tools(scope=...)` tool disabling scopes
- [ ] **SESS-05**: `mcp_list_tools()` tool returning all registered tools filtered by session state
- [ ] **SESS-06**: Core tools always enabled regardless of session state

### Core Read Tools

- [x] **TOOL-01**: `device_list` — list devices with status, platform, location; select_related; paginate; restrict(user)
- [x] **TOOL-02**: `device_get` — single device by name or pk with interfaces prefetched
- [x] **TOOL-03**: `interface_list` — list interfaces filtered by device_name; paginate; restrict(user)
- [x] **TOOL-04**: `interface_get` — single interface by pk with ip_addresses prefetched
- [x] **TOOL-05**: `ipaddress_list` — list IP addresses with tenant, vrf; paginate; restrict(user)
- [x] **TOOL-06**: `ipaddress_get` — single IP address by address or pk with interfaces prefetched
- [x] **TOOL-07**: `prefix_list` — list prefixes with vrf, tenant; paginate; restrict(user)
- [x] **TOOL-08**: `vlan_list` — list VLANs with site, group; paginate; restrict(user)
- [x] **TOOL-09**: `location_list` — list locations with location_type, parent; paginate; restrict(user)
- [ ] **TOOL-10**: `search_by_name` — multi-model name search across devices, interfaces, IPs, prefixes, VLANs, locations

### Pagination & Serialization

- [ ] **PAGE-01**: `paginate_queryset(qs, limit, cursor)` with `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`
- [ ] **PAGE-02**: `LIMIT_SUMMARIZE=100` — auto-summarize when raw count > 100, count BEFORE slicing
- [ ] **PAGE-03**: `PaginatedResult` dataclass with items, cursor, total_count, summary fields
- [ ] **PAGE-04**: Cursor encoding as `base64(str(pk))` — works for UUID and string PKs
- [x] **PAGE-05**: `sync_to_async(fn, thread_sensitive=True)` for all ORM calls inside async tool handlers

### SKILL.md Package

- [ ] **SKILL-01**: `nautobot-mcp-skill/` pip package with SKILL.md
- [ ] **SKILL-02**: SKILL.md with Core Tools reference table, scope management patterns, pagination docs
- [ ] **SKILL-03**: SKILL.md with investigation workflows (investigate device, find by name, explore Juniper BGP)

### Testing

- [ ] **TEST-01**: `test_registry.py` — singleton thread safety, registration, scope matching, fuzzy search
- [ ] **TEST-02**: `test_core_tools.py` — ORM mocking, pagination, auth enforcement, anonymous fallback
- [ ] **TEST-03**: `test_view.py` — ASGI bridge, HTTP round-trip, endpoint reachability
- [ ] **TEST-04**: `test_signal_integration.py` — `post_migrate` timing, tool registration, third-party tool discovery
- [ ] **TEST-05**: Coverage threshold `fail_under = 50` in `pyproject.toml`
- [ ] **TEST-06**: Auth test: valid token → data, invalid token → empty + warning logged

---

## Out of Scope

| Feature | Reason |
|---|---|
| Write tools (create/update/delete) | Focus on read-only v1 |
| MCP `resources` or `prompts` endpoints | Tools first |
| Redis session backend | In-memory sessions sufficient for v1 |
| Option B separate worker process | Option A (embedded) is correct path |
| Tool-level field permissions | Deferred |
| Streaming SSE rows | Cursor pagination handles memory |

---

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| FOUND-01 | Phase 0 | Pending |
| FOUND-02 | Phase 1 | Pending |
| FOUND-03 | Phase 0 | Pending |
| FOUND-04 | Phase 0 | Pending |
| FOUND-05 | Phase 1 | Pending |
| SRVR-01 | Phase 1 | Pending |
| SRVR-02 | Phase 1 | Pending |
| SRVR-03 | Phase 1 | Pending |
| SRVR-04 | Phase 1 | Pending |
| SRVR-05 | Phase 1 | Pending |
| SRVR-06 | Phase 1 | Pending |
| REGI-01 | Phase 1 | Pending |
| REGI-02 | Phase 1 | Pending |
| REGI-03 | Phase 1 | Pending |
| REGI-04 | Phase 1 | Pending |
| REGI-05 | Phase 2 | Pending |
| AUTH-01 | Phase 2 | Pending |
| AUTH-02 | Phase 2 | Pending |
| AUTH-03 | Phase 2 | Pending |
| SESS-01 | Phase 2 | Pending |
| SESS-02 | Phase 2 | Pending |
| SESS-03 | Phase 2 | Pending |
| SESS-04 | Phase 2 | Pending |
| SESS-05 | Phase 2 | Pending |
| SESS-06 | Phase 2 | Pending |
| TOOL-01 | Phase 3 | Complete |
| TOOL-02 | Phase 3 | Complete |
| TOOL-03 | Phase 3 | Complete |
| TOOL-04 | Phase 3 | Complete |
| TOOL-05 | Phase 3 | Complete |
| TOOL-06 | Phase 3 | Complete |
| TOOL-07 | Phase 3 | Complete |
| TOOL-08 | Phase 3 | Complete |
| TOOL-09 | Phase 3 | Complete |
| TOOL-10 | Phase 3 | Pending |
| PAGE-01 | Phase 3 | Pending |
| PAGE-02 | Phase 3 | Pending |
| PAGE-03 | Phase 3 | Pending |
| PAGE-04 | Phase 3 | Pending |
| PAGE-05 | Phase 3 | Complete |
| SKILL-01 | Phase 4 | Pending |
| SKILL-02 | Phase 4 | Pending |
| SKILL-03 | Phase 4 | Pending |
| TEST-01 | Phase 1 | Pending |
| TEST-02 | Phase 3 | Pending |
| TEST-03 | Phase 1 | Pending |
| TEST-04 | Phase 1 | Pending |
| TEST-05 | Phase 0 | Pending |
| TEST-06 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 47 total
- Mapped to phases: 47
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-01*
*Last updated: 2026-04-01 after initial definition*
