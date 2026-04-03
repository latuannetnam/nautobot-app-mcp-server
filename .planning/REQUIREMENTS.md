# Requirements: nautobot-app-mcp-server

**Defined:** 2026-04-03
**Core Value:** AI agents can query Nautobot network inventory data via MCP tools with full Nautobot permission enforcement, zero extra network hops, and progressive tool discovery.

---

## v1 Requirements

Requirements for v1.1.0 milestone — MCP server refactor. All P0 issues share one root cause (`asyncio.run()`); fixing it restores session state and progressive disclosure.

### Bridge Refactor

- [ ] **REFA-01**: `view.py` replaces `asyncio.run()` with `asgiref.sync.async_to_sync(_call_starlette_handler)(request, session_manager)` — session state now persists across requests
- [ ] **REFA-02**: `view.py` calls `async with session_manager.run():` inside `_call_starlette_handler` before `handle_request()` — `Server.request_context.get()` works in all tool handlers
- [ ] **REFA-03**: `view.py` ASGI scope dict built from Django request with all fields: `server` from `request.get_host()`/`get_port()`, `scheme` from `request.is_secure()`, `client` from `request.META`, `Content-Length` from headers, `path`, `query_string`, `headers`, `method`, `http_version`
- [ ] **REFA-04**: `server.py` exposes `get_session_manager()` returning the `StreamableHTTPSessionManager` singleton alongside `get_mcp_app()`
- [ ] **REFA-05**: `server.py` adds `threading.Lock` double-checked locking around `_mcp_app` initialization — prevents duplicate FastMCP instances under concurrent Django workers

### Auth Caching

- [ ] **AUTH-01**: `auth.py` caches Nautobot user object on MCP session dict via `ctx.request_context.session["cached_user"]` — avoids DB lookup on every tool call within a batch MCP request
- [ ] **AUTH-02**: Cache key is the token key; cache hit skips DB query; cache miss falls through to existing `Token.objects.select_related("user").get()` lookup

### Testing & Validation

- [ ] **TEST-01**: All existing unit tests pass after refactor (`poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests`)
- [ ] **TEST-02**: Integration test sends two sequential MCP HTTP requests with `Mcp-Session-Id` header; verifies `mcp_list_tools` response on the second request reflects scopes enabled in the first (session persistence UAT)
- [ ] **TEST-03**: UAT smoke tests pass (`docker exec ... python /source/scripts/run_mcp_uat.py`)

---

## v2 Requirements

Deferred to future release.

### Auto Schema Generation

- **SCHEMA-01**: Type-hint-based `input_schema` generator from function signatures using `inspect.signature` — reduces boilerplate for new tools
- **SCHEMA-02**: Auto-detect Django model fields from function annotations to populate `properties`

### Session Persistence

- **SESS-01**: Persist MCP session state to Nautobot's Django session backend — survives process restarts
- **SESS-02**: `django_request_ctx` context var for passing Django `HttpRequest` to async tool handlers without explicit argument passing

### Extensibility

- **TOOL-01**: Evaluate `MCPToolset` metaclass registry — auto-register public methods as MCP tools from class definition

---

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| DRF integration | Nautobot has no DRF; manual view approach is leaner and sufficient |
| Django `SessionStore` delegation | In-memory FastMCP sessions sufficient for Docker single-process; DB overhead not justified |
| Metaclass-based tool registry | `register_mcp_tool()` explicit API is sufficient for ~10 tools; metaclass overhead not justified |
| Write tools (create/update/delete) | Permission surface widens significantly; deferred to v2 |
| `redis` session backend | Over-engineering for v1; in-memory sessions sufficient |

---

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REFA-01 | Phase 5 | Pending |
| REFA-02 | Phase 5 | Pending |
| REFA-03 | Phase 5 | Pending |
| REFA-04 | Phase 5 | Pending |
| REFA-05 | Phase 5 | Pending |
| AUTH-01 | Phase 5 | Pending |
| AUTH-02 | Phase 5 | Pending |
| TEST-01 | Phase 5 | Pending |
| TEST-02 | Phase 5 | Pending |
| TEST-03 | Phase 5 | Pending |

**Coverage:**

- v1 requirements: 10 total
- Mapped to phases: 10
- Unmapped: 0 ✓

---

*Requirements defined: 2026-04-03*
*Last updated: 2026-04-03 after research synthesis*
