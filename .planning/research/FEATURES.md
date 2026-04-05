# Feature Research

**Domain:** Architecture migration — embedded (Option A) → separate-process (Option B) for `nautobot-app-mcp-server`
**Researched:** 2026-04-05
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These — Preserved in Both Architectures)

Features that remain unchanged by the architecture shift. They must continue working post-migration.

| Feature | Why Expected | Embedded (Option A) | Separate-Process (Option B) | Complexity | Notes |
|---------|--------------|---------------------|----------------------------|------------|-------|
| 10 core read tools | Core product value | ✅ Implemented | ✅ Implemented | LOW | Serializers, query builders, and ORM calls transfer directly |
| 3 session tools (mcp_enable/disable/list_tools) | Progressive disclosure contract | ✅ Implemented | ✅ Implemented | LOW | FastMCP `StreamableHTTPSessionManager` session API is identical |
| Token auth (`Authorization: Token <hex>`) | Required for Nautobot permission enforcement | ✅ Implemented | ✅ Implemented | LOW | Auth logic transfers; token lives in HTTP headers in both cases |
| Nautobot `.restrict(user, action="view")` | Permission enforcement | ✅ Implemented | ✅ Implemented | LOW | ORM is bootstrapped via `nautobot.setup()`; same queryset API |
| Cursor-based pagination | Memory safety for large result sets | ✅ Implemented | ✅ Implemented | LOW | `paginate_queryset` is pure Python, no HTTP layer dependency |
| `PaginatedResult` (items, cursor, total_count, summary) | Consistent response format | ✅ Implemented | ✅ Implemented | LOW | Dataclass + serialization helpers unchanged |
| `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`, `LIMIT_SUMMARIZE=100` | Predictable API behavior | ✅ Implemented | ✅ Implemented | LOW | Constants are module-level, not HTTP-dependent |
| `MCPToolRegistry` singleton | Tool registration API | ✅ Implemented | ✅ Needed | MEDIUM | Registry code transfers; initialization timing changes |
| `register_mcp_tool()` public API | Third-party app extensibility | ✅ Implemented | ⚠️ Requires redesign | HIGH | Mechanism to expose third-party tools changes fundamentally |

### Differentiators (New Capabilities from Separate-Process Architecture)

Features that become possible or significantly better with Option B.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Standalone MCP binary distribution** | MCP server installable/runnable independently of Nautobot; no plugin dependency required for the MCP runtime | MEDIUM | Package `nautobot-app-mcp-server` splits into: (a) Nautobot plugin (tool registration + metadata) and (b) `nautobot-mcp-server` pip package (FastMCP process + management commands) |
| **Redis session backend** | Session state persists across MCP server restarts; enables horizontal scaling of MCP workers | MEDIUM | FastMCP sessions are in-process dict in Option A; Option B can swap in Redis via `StreamableHTTPSessionManager` custom store. `OUT_OF_SCOPE` in v1 becomes viable. |
| **Horizontal worker scaling** | Multiple MCP server workers share load; session affinity via sticky sessions or shared Redis | HIGH | Requires Redis backend; introduces complexity around session state sharing. Anti-feature if not carefully scoped. |
| **True FastMCP lifecycle management** | No more `asyncio.run()` hacks, no `async_to_sync` bridge, no `mcp._list_tools_mcp` override | LOW | Option A required complex Phase 5 fixes to make FastMCP work inside Django. Option B is FastMCP's natural habitat — `mcp.run()` just works. |
| **Native progressive disclosure via `@mcp.list_tools()` decorator** | Cleaner code — no `mcp._list_tools_mcp` monkey-patch needed | LOW | Option A overrides internal `mcp._list_tools_mcp` (fragile). Option B uses FastMCP's `@mcp.list_tools()` decorator naturally since FastMCP owns the event loop. |
| **Standard FastMCP transports** | `streamable-http` without Django WSGI→ASGI bridge constraints | LOW | FastMCP's native HTTP transport is battle-tested. Option A's custom ASGI bridge was the source of Phase 5 session-state bugs. |
| **Uvicorn dev server with auto-reload** | Standard Python web dev DX — file-watch restarts, hot reload | LOW | `uvicorn` added as dev dependency; `start_mcp_dev_server.py` calls `create_app()` factory. Option A has no equivalent. |
| **Systemd service management** | Standard Linux production deployment — `systemctl start nautobot-mcp-server` | LOW | `start_mcp_server.py` entry point; `nautobot-mcp-server.service` systemd unit file. Option A is Django-managed (no separate lifecycle). |
| **Independent versioning** | MCP server can be released/patched independently of Nautobot app plugin | MEDIUM | Two packages: `nautobot-app-mcp-server` (plugin) and `nautobot-mcp-server` (server binary). More release flexibility. |
| **Process isolation — no Django worker crashes affecting MCP** | Fault boundary: Django app crash does not kill MCP server | LOW | Separate process is its own crash domain. Option A: Django OOM kills the MCP endpoint too. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem logical for separate-process but create disproportionate complexity.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Real-time bidirectional streaming (SSE rows)** | "MCP should push device updates live" | Requires event pub/sub infrastructure (Redis pub/sub or Kafka); changes response model from request/response to long-lived streams; complicates all clients | Cursor pagination is sufficient for large datasets. Real-time can be added via a separate event streaming layer if genuinely needed. |
| **Automatic third-party app tool discovery without config** | "Third-party Nautobot apps should auto-register their MCP tools" | Requires IPC between Nautobot Django process and separate MCP server process. Options: Redis pub/sub, file-based tool registry written by Nautobot on `post_migrate`, or REST API from MCP server back to Nautobot. All add significant complexity. | Document the `register_mcp_tool()` call in third-party app's `post_migrate` or `__init__.py`, but have the MCP server read tool definitions from a JSON registry file generated by the Nautobot plugin at startup. |
| **Horizontal scaling without sticky sessions** | "Run multiple MCP workers behind a load balancer" | Session state lives in FastMCP's in-process `StreamableHTTPSessionManager`. Without shared storage, requests from the same MCP session can land on different workers and lose session state. | Redis-backed session store; or accept single-worker deployment as the default (suitable for most deployments). |
| **Write tools (create/update/delete) in v1** | "Users will want to modify data via MCP" | Write operations require careful permission modeling, validation, and transactional safety. Defer to v2 where read tool behavior is stable and tested. | Keep write tools out of scope for the architecture migration milestone. Add in v2 as a separate feature. |

## Feature Dependencies

```
[MCPToolRegistry singleton]
    └──requires──> [register_mcp_tool() API]
                      └──requires──> [Tool discovery mechanism]
                                            └──requires──> [Tool registry file / IPC]

[FastMCP lifecycle (separate process)]
    ├──enables──> [Native progressive disclosure]
    │               └──enables──> [No mcp._list_tools_mcp override]
    │
    └──removes──> [view.py ASGI bridge, async_to_sync wrapper, daemon thread pattern]

[Tool registry file]
    ├──generated by──> [nautobot-app-mcp-server plugin (ready())]
    └──consumed by──> [nautobot-mcp-server (startup)]

[Django plugin (nautobot-app-mcp-server)]
    ├──generates──> [tool_registry.json]
    ├──exposes──> [Auth token validation via nautobot.setup() Token.objects]
    └──serves──> [No MCP URL routing — separate process owns the endpoint]

[nautobot.setup() bootstrapping]
    ├──requires──> [NAUTOBOT_ROOT env var]
    └──requires──> [Django settings module import]

[StreamableHTTPSessionManager]
    └──enhances──> [Session tools: mcp_enable/disable/list_tools]
                      └──native──> [Direct session dict access — no ServerSession workaround needed]
```

### Dependency Notes

- **MCPToolRegistry requires register_mcp_tool():** The registry singleton is the storage; `register_mcp_tool()` is the write API. Both must exist in Option B.
- **Tool discovery requires a new mechanism:** In Option A, tools are registered via Django's `post_migrate` signal (same process). In Option B, the MCP server is a separate process — it cannot call Django signals. A tool registry file (JSON) written by the Nautobot plugin and read by the MCP server at startup replaces this.
- **Auth requires Nautobot user resolution:** The separate MCP server cannot access Nautobot's `request.user` directly. It must use `nautobot.setup()` with a Django settings module to access `Token.objects` directly (the approach used in `django-mcp-server`).
- **Redis backend enhances sessions but is not blocking:** In-memory FastMCP sessions are sufficient for v1 of Option B. Redis can be added in v1.x if horizontal scaling becomes necessary.
- **Django plugin generates, MCP server consumes:** The Nautobot plugin (`nautobot-app-mcp-server`) writes tool definitions to a registry file at startup. The separate MCP server reads this file. This decouples the two processes.

## What BREAKS or CHANGES with Separate-Process Architecture

These are not missing features — they are existing behaviors that must be reimplemented or replaced.

| What Changes | Embedded (Option A) | Separate-Process (Option B) | Migration Action |
|---|---|---|---|
| **HTTP endpoint** | `GET/POST /plugins/nautobot-app-mcp-server/mcp/` via Django URL routing | Standalone FastMCP transport on a separate port (e.g., `localhost:8001`) via `mcp.run(transport="streamable-http")` | UAT tests must use new URL. No more Django plugin URL required for MCP traffic. |
| **ASGI bridge (`view.py`)** | `async_to_sync(_call_starlette_handler)` + `session_manager.run()` + `_bridge_django_to_asgi()` | Deleted. FastMCP owns the event loop. `view.py` is removed entirely. | Rewrite view tests to test the FastMCP app directly. |
| **`mcp._list_tools_mcp` override** | Required hack to implement progressive disclosure (FastMCP 3.x `@mcp.list_tools()` raises `TypeError`) | No longer needed. FastMCP's event loop is native; `@mcp.list_tools()` decorator works as intended. | Replace override with a clean `@mcp.list_tools()` implementation. |
| **`asyncio.run()` per-request pattern** | Phase 5 fix replaced `asyncio.run()` with `async_to_sync` (a workaround) | Gone. FastMCP's `run()` is called once at startup (or once per uvicorn worker via lifespan). No per-request async management. | Delete Phase 5 workarounds. |
| **`_cached_user` on `RequestContext`** | Auth user cached on FastMCP's `request_context` ContextVar | FastMCP's `request_context` ContextVar still exists and works naturally. No special handling needed. | `auth.py` code transfers directly; the ContextVar access pattern is the same. |
| **`post_migrate` signal → tool registration** | Django signal fires after app migrations; same process = tools registered immediately | Cannot use `post_migrate` directly (different process). Nautobot plugin writes tool registry JSON on startup. | Generate `tool_registry.json` in `NautobotAppMcpServerConfig.ready()`; MCP server reads at startup. |
| **`MCPToolRegistry` singleton initialization timing** | Lazy singleton via double-checked locking on first HTTP request | Same singleton, but initialized on MCP server startup (not on first request) | `create_app()` factory initializes registry at startup |
| **In-memory session dict via `request_context._mcp_tool_state`** | Option A workaround: `ServerSession` is NOT dict-like, so state stored on `request_context` | FastMCP `StreamableHTTPSessionManager` sessions ARE dict-like; direct `session["key"] = value` works natively. | `session_tools.py` `_get_tool_state()` can simplify to direct dict access. The workaround is no longer needed. |
| **Third-party app tool registration** | Third-party app calls `register_mcp_tool()` in its own `ready()` or `post_migrate`; registry is shared in-process | Third-party app must write to the shared tool registry JSON file | Recommended: third-party apps call a helper that appends to `tool_registry.json`; MCP server reads at startup. Document the API. |
| **Django `PluginConfig` for MCP routing** | `nautobot_app_mcp_server/urls.py` with `path("mcp/", mcp_view)` auto-included by Nautobot | Nautobot plugin still exists but serves only tool registration (generates `tool_registry.json`) and auth bootstrapping. No MCP URL routing. | Retain plugin for `nautobot.setup()` bootstrapping info and tool registration. Remove `urls.py` MCP route. |
| **ASGI server (Daphne/gunicorn workers handling MCP)** | Django ASGI workers handle MCP requests alongside Django requests | Standalone FastMCP/uvicorn process. Django workers are pure Django (no MCP handling). | Separate Docker service in `docker-compose.yml`: `nautobot-mcp-server` container alongside `nautobot`. |
| **Event loop persistence daemon thread** | Option A requires a daemon thread to keep FastMCP's event loop alive across Django requests | Not needed. FastMCP's `run()` / uvicorn lifespan manages the event loop naturally. | Delete `server.py` daemon thread pattern (`threading.Thread` + `Event.wait()`). |
| **`sync_to_async` in tool handlers** | Required because Django ORM is sync and FastMCP handlers are async | Still required for ORM calls. The surrounding bridge (`async_to_sync(_call_starlette_handler)`) is gone but `sync_to_async(fn, thread_sensitive=True)` per tool is unchanged. | `sync_to_async(fn, thread_sensitive=True)` in tool handlers transfers directly. |

## MVP Definition

### Launch With (v1 — Separate-Process Architecture)

Minimum viable to validate the architecture migration works end-to-end.

- [ ] **FastMCP standalone server** (`start_mcp_server.py` / `start_mcp_dev_server.py`) — `mcp.run(transport="streamable-http")` on port 8001; uvicorn for dev auto-reload; systemd unit for production
- [ ] **`nautobot.setup()` bootstrapping** — MCP server initializes Django ORM via `nautobot.setup()` at startup; same ORM access as embedded
- [ ] **10 core read tools operational** — All tools transferred from `core.py`; `MCPToolRegistry` populated at server startup
- [ ] **Token auth** (`Authorization: Token <hex>`) — `get_user_from_request()` reads from FastMCP HTTP headers; `.restrict()` applied to all querysets
- [ ] **3 session tools** (mcp_enable/disable/list_tools) — FastMCP `StreamableHTTPSessionManager` sessions work natively; no monkey-patch
- [ ] **Cursor-based pagination** — `paginated_queryset` unchanged; works identically
- [ ] **Tool registry JSON** — `nautobot-app-mcp-server` plugin writes `tool_registry.json` in `ready()`; MCP server reads at startup
- [ ] **Native progressive disclosure** — `@mcp.list_tools()` decorator replaces `mcp._list_tools_mcp` override
- [ ] **All existing unit tests pass** — `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests`
- [ ] **UAT smoke tests pass** against new standalone endpoint

### Add After Validation (v1.x)

Features to add once the standalone architecture is stable.

- [ ] **Redis session backend** — Swap in-memory sessions for Redis via `StreamableHTTPSessionManager` custom store; enables horizontal worker scaling
- [ ] **Docker Compose integration** — `nautobot-mcp-server` container in `development/docker-compose.yml` alongside `nautobot`
- [ ] **`nautobot-mcp-server` pip package** — Extract FastMCP server into its own installable package (`pyproject.toml`); separate from Nautobot plugin
- [ ] **Auth caching on session** — `ctx.request_context.session["cached_user"]` caches auth result per session; avoids repeated DB lookups on batched requests
- [ ] **`search_by_name` in-memory pagination fix** — Current implementation loads all 6 models into memory before paginating; for very large datasets this is problematic. Fix: apply limit per-model, merge, then return top-N.

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Write tools (create/update/delete)** — Requires permission modeling, transactional safety, and comprehensive testing. Keep out of scope for migration milestone.
- [ ] **Horizontal worker scaling with Redis** — Multiple MCP workers sharing Redis session store. Only needed at scale; single worker handles most deployments.
- [ ] **Tool-level field permissions** — Per-field visibility control beyond `.restrict()` row-level permissions.
- [ ] **MCP `resources` and `prompts` endpoints** — Focus is tools-first. Resources/prompts add conceptual surface area.
- [ ] **Streaming (SSE rows)** — Real-time push for large query results. Cursor pagination handles most cases. Add if users request it.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| FastMCP standalone server (mcp.run) | HIGH — core of the migration | LOW | P1 |
| nautobot.setup() bootstrapping | HIGH — enables all ORM tools | MEDIUM | P1 |
| 10 core read tools (transfer) | HIGH — core product value | LOW | P1 |
| Token auth (get_user_from_request) | HIGH — permission enforcement | LOW | P1 |
| 3 session tools (session state) | HIGH — progressive disclosure UX | LOW | P1 |
| Tool registry JSON (plugin → server) | HIGH — third-party extensibility contract | MEDIUM | P1 |
| Remove view.py / ASGI bridge | MEDIUM — reduces complexity significantly | MEDIUM | P1 |
| Native @mcp.list_tools() decorator | MEDIUM — cleaner progressive disclosure | LOW | P1 |
| Docker Compose integration | MEDIUM — dev environment parity | MEDIUM | P1 |
| Systemd unit file | MEDIUM — production deployment | LOW | P1 |
| Unit tests pass | HIGH — quality gate | LOW | P1 |
| UAT smoke tests pass | HIGH — end-to-end validation | LOW | P1 |
| Redis session backend | MEDIUM — horizontal scaling | MEDIUM | P2 |
| nautobot-mcp-server pip package extraction | MEDIUM — independent versioning | MEDIUM | P2 |
| Auth caching on session | LOW — micro-optimization | LOW | P2 |
| Multi-worker horizontal scaling | MEDIUM — scale deployment | HIGH | P3 |
| Write tools (create/update/delete) | MEDIUM — user request | HIGH | P3 |
| search_by_name in-memory pagination fix | MEDIUM — correctness for large DBs | MEDIUM | P3 |
| MCP resources/prompts endpoints | LOW — conceptual surface | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch (architecture migration validated)
- P2: Should have, add when possible (post-migration polish)
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Embedded MCP (nautobot-app-mcp-server v1.1) | django-mcp-server (separate-process reference) | nautobot-app-mcp (reference impl) | Our Approach (Option B) |
|---------|---|---|---|---|
| Architecture | Embedded in Django via WSGI→ASGI bridge | Separate-process FastMCP via `django-mcp-server` | Embedded | Separate-process FastMCP |
| Tool discovery | `post_migrate` signal (same process) | Django management command reads `MCPTool` model | `@register_tool` decorator + DB model | Tool registry JSON generated by plugin, read at server startup |
| Session state | In-process dict on `StreamableHTTPSessionManager` | In-process dict on `StreamableHTTPSessionManager` | N/A (stateless) | In-process dict (v1); Redis store (v1.x) |
| Auth | Token from MCP request context → Django ORM | Token from HTTP headers → Django ORM via `nautobot.setup()` | Token → Nautobot REST API | Token from HTTP headers → Django ORM via `nautobot.setup()` |
| Progressive disclosure | Override `mcp._list_tools_mcp` (hack) | Clean `@mcp.list_tools()` decorator | N/A | Clean `@mcp.list_tools()` decorator |
| Production deployment | Django workers (gunicorn/uwsgi) | Systemd-managed FastMCP process | N/A | Systemd-managed FastMCP process |
| Third-party extensibility | `register_mcp_tool()` in-process | `MCPTool` model + Django management command | `@register_tool` + DB model | `register_mcp_tool()` writes to JSON registry; MCP server reads at startup |
| Lifecycle management | Daemon thread + async_to_sync bridge (complex) | FastMCP `run()` (natural) | N/A | FastMCP `run()` (natural) |

**Sources:**

- `django-mcp-server` (reference for Option B patterns): `mcp_server/djangomcp.py`, `mcp_server/views.py`, `mcp/server/streamable_http_manager.py`
- `nautobot-app-mcp` (reference for `@register_tool` decorator pattern): `nautobot_mcp/tools/registry.py`, `nautobot_mcp/tools/device_tools.py`
- `nautobot-app-mcp-server` existing codebase: `core.py`, `query_utils.py`, `pagination.py`, `session_tools.py`, `auth.py`, `server.py`, `view.py`

---
*Feature research for: nautobot-app-mcp-server v1.2 separate-process architecture migration*
*Researched: 2026-04-05*
