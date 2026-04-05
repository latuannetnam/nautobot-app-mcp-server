# High-Level Design: Standalone Nautobot MCP Server

> **Version:** 1.0
> **Date:** 2026-04-04
> **Based on:** `docs/dev/ARCHITECTURE.md` — verified on live Nautobot 3.0.0

---

## 1. Goal

Replace `nautobot-app-mcp-server` (currently embedded as a Nautobot app with a WSGI/ASGI bridge) with a standalone Python package that:
- Runs as a separate OS process alongside Nautobot
- Exposes an MCP HTTP server via FastMCP
- Calls Nautobot's ORM directly via `nautobot.setup()`
- Supports progressive tool disclosure
- Allows other Nautobot plugins to register MCP tools via a `mcp_tools.py` convention
- Uses Nautobot's Token auth for permission enforcement

---

## 2. Architecture Overview

```
┌── Nautobot (gunicorn, port 8080) ─────────────────────────────────────────┐
│  WSGI process, unchanged.                                                 │
│  Serves Nautobot web UI + REST API.                                      │
└───────────────────────────────────────────────────────────────────────────┘
         ▲
         │ NAUTOBOT_DB_* env vars / NAUTOBOT_CONFIG
         │ (same PostgreSQL database)
         │
┌────────┴────────────────────────────────────────────────────────────────┐
│  MCP Server (uvicorn, port 8005)                                        │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ main.py                                                           │   │
│  │ 1. nautobot.setup()                                             │   │
│  │ 2. discover_plugins()  → auto-import plugin mcp_tools.py        │   │
│  │ 3. register_core_tools()                                        │   │
│  │ 4. app = mcp.streamable_http_app()                             │   │
│  │ 5. uvicorn.run(app)  ← lifespan handled automatically         │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────────────┐    │
│  │ auth.py      │  │ registry.py   │  │ tools/                   │    │
│  │ Token lookup │  │ MCPToolRegistry│  │ core.py (10 tools)      │    │
│  │ Permission   │  │ register_     │  │ session_tools.py        │    │
│  │ restrict()   │  │ mcp_tool()    │  │ pagination.py           │    │
│  └──────────────┘  └───────────────┘  └──────────────────────────┘    │
│                                                                          │
│  Claude Desktop/Code ──HTTP──► uvicorn (port 8005) ──► ORM ──► DB   │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key insight from verification:** uvicorn handles FastMCP's `session_manager.run()` lifespan automatically. No daemon thread, no lazy factory, no WSGI/ASGI bridge needed.

---

## 3. Components

### 3.1 `main.py` — Entry Point

Single startup file. No class hierarchy.

```
1. Read NAUTOBOT_CONFIG env var (default: ~/.nautobot/nautobot_config.py)
2. Call nautobot.setup()
3. Call discover_plugins() — auto-imports plugin mcp_tools.py modules
4. Call register_core_tools() — registers built-in tools on MCPToolRegistry
5. Create FastMCP instance with all tools
6. app = mcp.streamable_http_app()
7. uvicorn.run(app, host, port, workers)
```

No lazy initialization. No threading. The startup is linear and predictable.

### 3.2 `auth.py` — Token Auth

Reads `Authorization: Token <key>` from FastMCP's request context headers. Looks up the token in the DB, returns the associated user. AnonymousUser for missing/invalid tokens.

```python
def get_user_from_token(token_key: str) -> User | AnonymousUser:
    try:
        token = Token.objects.select_related("user").get(key=token_key)
        if token.is_expired:
            return AnonymousUser()
        return token.user
    except Token.DoesNotExist:
        return AnonymousUser()
```

Every tool handler calls `get_user_from_token(ctx.request_context.auth_token)`. AnonymousUser produces empty querysets via `.restrict()` — graceful degradation, no error.

### 3.3 `registry.py` — Tool Registry

Thread-safe singleton holding all registered tools.

```python
class MCPToolRegistry:
    _instance = None
    _tools: dict[str, ToolDefinition] = {}

    def register(tool: ToolDefinition) -> None
    def get_all() -> list[ToolDefinition]
    def get_core_tools() -> list[ToolDefinition]
    def get_by_scope(scope: str) -> list[ToolDefinition]
    def fuzzy_search(term: str) -> list[ToolDefinition]

def register_mcp_tool(
    name, func, description, input_schema,
    tier="app", app_label=None, scope=None
) -> None
```

Third-party plugins call `register_mcp_tool()` in their `mcp_tools.py` module (see Section 3.5).

### 3.4 `server.py` — FastMCP Setup

```python
def create_app() -> Starlette:
    mcp = FastMCP("NautobotMCP", json_response=True)
    register_core_tools(mcp)
    register_session_tools(mcp)
    _setup_progressive_disclosure(mcp)   # overrides _list_tools_mcp
    return mcp.streamable_http_app()
```

Registers tools on FastMCP using `@mcp.tool()` decorators, then returns the Starlette ASGI app. Lifespan (session manager) handled by uvicorn.

**Progressive disclosure:** FastMCP 3.x has no public API for filtering `tools/list` responses. The implementation overrides `mcp._list_tools_mcp` to filter tools by session state (`enabled_scopes`, `enabled_searches`). This pattern is identical to the current embedded implementation — the override source code can be carried over unchanged.

### 3.5 `plugins.py` — Plugin Discovery

Convention-based auto-discovery: any Nautobot plugin that ships a `mcp_tools.py` module has its tools auto-registered at startup.

```python
def discover_plugins() -> None:
    for app_config in apps.get_app_configs():
        if app_config.name.startswith(("django.", "nautobot.core")):
            continue  # Skip core apps
        try:
            importlib.import_module(f"{app_config.name}.mcp_tools")
        except ImportError:
            pass  # Plugin has no MCP tools
```

**Plugin author experience:**

```python
# netnam_cms_core/mcp_tools.py
from nautobot_app_mcp_server import register_mcp_tool

def bgp_neighbor_list(device_name: str, limit: int = 25):
    ...

register_mcp_tool(
    name="bgp_neighbor_list",
    func=bgp_neighbor_list,
    description="List BGP neighbors for a device.",
    input_schema={...},
    tier="app",
    app_label="netnam_cms_core",
    scope="netnam_cms_core.juniper.bgp",
)
```

No config needed. Plugin ships → tools auto-discovered → available to MCP clients.

### 3.6 `tools/` — Tool Implementations

#### `core.py` — 10 Built-in Read Tools

| Tool | Description | Key ORM Pattern |
|---|---|---|
| `device_list` | List devices | `select_related("status","device_type","role","location").restrict(user,"view")` |
| `device_get` | Get one device | `prefetch_related("interfaces__ip_addresses")` |
| `interface_list` | List interfaces | `filter(device__name=...).select_related("device","type","status")` |
| `interface_get` | Get one interface | Prefetch IP addresses |
| `ipaddress_list` | List IP addresses | `select_related("vrf","role").restrict(user,"view")` |
| `prefix_list` | List prefixes | `select_related("vrf","status").restrict(user,"view")` |
| `vlan_list` | List VLANs | `select_related("site","group").restrict(user,"view")` |
| `location_list` | List locations | `select_related("location_type","parent").restrict(user,"view")` |
| `tenant_list` | List tenants | `.restrict(user,"view")` |
| `search_by_name` | Search across models | AND across 6 models |

All tools follow the same pattern:

```python
@mcp.tool()
async def device_list(ctx, limit: int = 25, cursor: str | None = None) -> list[dict]:
    token = ctx.request_context.auth_token
    user = get_user_from_token(token)
    if user is None:
        return []

    @sync_to_async
    def _query():
        qs = Device.objects.select_related(
            "status", "device_type", "role", "location"
        ).restrict(user, "view")
        return paginate_queryset(qs, limit, cursor)

    return await _query()
```

#### `session_tools.py` — Progressive Disclosure

Three session-management tools always visible to MCP clients:

| Tool | Action |
|---|---|
| `mcp_enable_tools(scope, search)` | Add scope to `enabled_scopes`, term to `enabled_searches` |
| `mcp_disable_tools(scope)` | Remove scope + all child scopes from `enabled_scopes` |
| `mcp_list_tools()` | Return human-readable summary of active tools |

Session state stored in FastMCP's `StreamableHTTPSessionManager` (per `Mcp-Session-Id`, in-memory). Scope hierarchy: `scope="netnam_cms_core"` activates `netnam_cms_core.*`.

#### `pagination.py` — Cursor + Auto-Summarize

```python
def paginate_queryset(qs, limit=25, cursor=None) -> PaginatedResult:
    # Cursor = base64(pk)
    # If result > 100 items: summarize (return sample + count, cap at 100)
    # Returns PaginatedResult(items, cursor, total_count, summary)
```

---

## 4. Data Flow

```
Claude Desktop HTTP Request
  → uvicorn (port 8005)
  → Starlette ASGI app (FastMCP streamable_http_app)
  → FastMCP routes to tool handler
  → Tool handler:
       1. Extract token from Authorization header
       2. get_user_from_token(token) → User
       3. sync_to_async(ORM query with .restrict(user))
       4. paginate_queryset()
       5. serialize results
  → JSON-RPC response
  → HTTP 200
```

**Auth on every request:** Token read from MCP headers → DB lookup → cached on request context. No sessions, no cookies.

**ORM bridge:** `sync_to_async(thread_sensitive=True)` reuses Django's request thread and connection pool. No connection exhaustion.

---

## 5. Deployment

### 5.1 Docker Sidecar (Recommended)

```yaml
services:
  nautobot-mcp:
    image: nautobot-app-mcp-server:latest
    environment:
      NAUTOBOT_CONFIG: /config/nautobot_config.py
    volumes:
      - ./nautobot_config.py:/config/nautobot_config.py:ro
    ports:
      - "8005:8005"
    command: uvicorn nautobot_app_mcp_server.main:app --host 0.0.0.0 --port 8005
```

### 5.2 Systemd

```ini
[Service]
ExecStart=/opt/nautobot/bin/uvicorn nautobot_app_mcp_server.main:app --host 127.0.0.1 --port 8005 --workers 4
Environment="NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py"
Restart=always
```

### 5.3 Development

```bash
NAUTOBOT_CONFIG=development/nautobot_config.py \
uvicorn nautobot_app_mcp_server.main:app --reload --port 8005
```

---

## 6. Not in Scope for V1

- **Write tools** (create/update/delete) — deferred
- **SSE transport** — streamable HTTP is sufficient
- **Redis-backed session persistence** — in-memory is fine for v1
- **Tool-level field permissions** — Nautobot's `.restrict()` handles object-level only
- **MCP resources/prompts** — tools only for now
- **CMS plugin model access** — verify with `netnam_cms_core` when available

---

## 7. Open Questions (Deferred)

| Question | Decision for V1 |
|---|---|
| Web UI for MCP server status? | None — MCP clients connect directly |
| Health check endpoint? | `/health` returning `{"status": "ok"}` |
| Metrics? | None — defer to observability phase |
| TLS termination? | At reverse proxy layer (Nginx) — not in server |

---

## 8. Directory Structure

```
nautobot_app_mcp_server/
├── pyproject.toml
├── src/nautobot_app_mcp_server/
│   ├── __init__.py          # Empty — package marker
│   ├── main.py               # Entry point: setup + uvicorn
│   ├── server.py             # FastMCP factory
│   ├── auth.py               # Token auth
│   ├── registry.py           # MCPToolRegistry
│   ├── plugins.py            # Plugin discovery (mcp_tools.py convention)
│   ├── tools/
│   │   ├── __init__.py      # register_all_tools(), register_core_tools()
│   │   ├── core.py          # 10 built-in read tools
│   │   ├── session_tools.py # Progressive disclosure
│   │   ├── pagination.py   # Cursor + summarize
│   │   └── query_utils.py  # Serializer helpers
│   └── tests/
│       ├── test_auth.py
│       ├── test_core_tools.py
│       ├── test_session_tools.py
│       ├── test_registry.py
│       └── test_plugins.py
└── deployment/
    ├── Dockerfile
    └── nautobot-app-mcp-server.service
```

---

## 9. Verification Plan

| Test | Method |
|---|---|
| `nautobot.setup()` succeeds | `python -c "import nautobot; nautobot.setup(); print('ok')"` |
| All core models queryable | Script with 5 devices, 19K prefixes |
| Token auth returns correct user | Lookup by known token key |
| `RestrictedQuerySet` filters anonymous | AnonymousUser → 0 results |
| `select_related` produces 1 SQL query | `django.db.connection.queries` count |
| FastMCP `tools/list` returns tools | `curl -X POST http://localhost:8005/mcp` with JSON-RPC |
| `call_tool` → ORM → JSON response | End-to-end `device_list` call |
| Plugin discovery auto-imports `mcp_tools.py` | Install mock plugin, check registry |
