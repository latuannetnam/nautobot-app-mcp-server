# Architecture — `nautobot-app-mcp-server`

> How the app is structured, why it is structured that way, and what the key design decisions mean in code.

---

## 1. What This App Actually Is

This is **not a traditional Nautobot app**. It has no database models, no REST API views, no forms, no tables, and no navigation menu. Its single job is to:

1. Expose a **Model Context Protocol (MCP)** server **inside Nautobot's Django process**.
2. Allow AI agents (Claude Code, Claude Desktop) to query Nautobot data using MCP tools instead of calling the REST API externally.

```
External AI Agent
        │
        │  MCP / Streamable HTTP
        │  (Authorization: Token nbapikey_xxx)
        ▼
┌─────────────────────────────────────────────────────────┐
│  Nautobot Django Process                                 │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  MCP Server (FastMCP, ASGI)                    │    │
│  │  Mounted at /plugins/nautobot-mcp-server/mcp/ │    │
│  └──────────────┬──────────────────────────────────┘    │
│                 │                                       │
│  ┌──────────────▼──────────────────────────────────┐    │
│  │  Tool Registry  (in-memory singleton dict)      │    │
│  │  • Core tools (always active)                  │    │
│  │  • App tools (registered by third-party apps)  │    │
│  └──────────────┬──────────────────────────────────┘    │
│                 │                                       │
│  ┌──────────────▼──────────────────────────────────┐    │
│  │  Tool Executor Layer                            │    │
│  │  • sync_to_async (Django ORM → async)          │    │
│  │  • paginate_queryset (cursor-based)            │    │
│  │  • restrict(user, action) (Nautobot perms)    │    │
│  └──────────────┬──────────────────────────────────┘    │
│                 │                                       │
│  ┌──────────────▼──────────────────────────────────┐    │
│  │  Nautobot ORM (direct, no HTTP overhead)        │    │
│  │  Device, Interface, IPAddress, Prefix, VLAN…   │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Design Pattern: Embedded Protocol Adapter

The app follows the **Embedded Protocol Adapter** pattern. Rather than building an external service that proxies the REST API, it embeds the MCP server inside the Django process.

**Why this matters:**

| Approach | Pros | Cons |
|---|---|---|
| External MCP server calling REST API | Simpler deployment | Extra network hop, no direct ORM access |
| **Embedded in Django process (this app)** | Direct ORM, permissions integration, no extra port | Couples MCP lifecycle to Django |
| Option B: Separate gunicorn worker on port 9001 | Simpler deployment, separate process | Requires separate startup, different URL |

The design document (`docs/dev/DESIGN.md`) notes that **Option A (ASGI mount via Django URL)** is the recommended path, with **Option B (separate worker)** as the fallback if ASGI mounting proves complex in production Nautobot.

**Planned (`docs/dev/DESIGN.md`):** Lazy ASGI app initialization — `_mcp_app` is `None` at import time, created on first HTTP request to avoid Django startup race conditions.

```python
# nautobot_app_mcp_server/mcp/server.py  (planned per DESIGN.md)
_mcp_app: ASGIApplication | None = None

def get_mcp_app() -> ASGIApplication:
    global _mcp_app
    if _mcp_app is None:
        _mcp_app = mcp.streamable_http_app(...)
    return _mcp_app
```

---

## 3. Layer-by-Layer Data Flow

### Layer 1 — Entry Point (Django → MCP)

```
Django request  →  /plugins/nautobot-mcp-server/mcp/  (urls.py)
                     │
                     ▼
                  Django view / ASGI bridge
                     │
                     ▼
                  FastMCP HTTP app  (StreamableHTTPSessionManager)
                     │
                     ▼
                  MCP protocol handler  (list_tools / call_tool)
```

**Current state:** `urls.py` does not yet exist — this is the first piece to implement.

**Planned URL routing:**

```python
# nautobot_app_mcp_server/urls.py  (planned per DESIGN.md)
urlpatterns = [
    path("mcp/", mcp_view, name="mcp"),
]
```

The MCP endpoint uses `stateless_http=False` so FastMCP's `StreamableHTTPSessionManager` tracks sessions per `Mcp-Session-Id` header. Missing or invalid session ID → **automatically creates a new session**.

---

### Layer 2 — Authentication

```
Authorization: Token nbapikey_xxx
        │
        ▼
auth.py  →  get_user_from_request()
        │    Extracts token, looks up User via nautobot.users.models.Token
        │    Falls back to request.user (session cookie)
        │    Returns AnonymousUser on failure (never raises — empty results instead)
        │
        ▼
User / AnonymousUser  →  passed into tool handlers
        │
        ▼
Every queryset  →  .restrict(user=user, action="view")
                   (Nautobot's built-in permission filtering)
```

**File:** `nautobot_app_mcp_server/mcp/auth.py` — planned per `DESIGN.md`.

**Security guarantee:** An unauthenticated request returns an empty list, not an error. No data is ever exposed without auth.

---

### Layer 3 — Tool Registry (In-Memory Singleton)

```
MCPToolRegistry  (thread-safe singleton)
    │
    ├── _tools: dict[str, ToolDefinition]
    │            name → ToolDefinition(func, description, input_schema, tier, scope)
    │
    ├── register(tool: ToolDefinition)        → add to dict
    ├── get_core_tools()                       → tier == "core"
    ├── get_by_scope(scope)                    → exact + child scope matches
    ├── fuzzy_search(term)                    → name/description contains
    └── get_all()                              → everything
```

**File:** `nautobot_app_mcp_server/mcp/registry.py` — planned per `DESIGN.md`.

The registry is a **singleton with `threading.Lock`** — safe for Django's multi-threaded worker model.

**`ToolDefinition` dataclass fields:**

```python
@dataclass
class ToolDefinition:
    name: str
    func: Callable
    description: str
    input_schema: dict[str, Any]
    tier: str = "core"           # "core" | "app"
    app_label: str | None = None  # Django app label, e.g. "netnam_cms_core"
    scope: str | None = None      # e.g. "netnam_cms_core.juniper"
```

**Scope hierarchy** (planned):

```
core                               ← Core tools, always enabled
netnam_cms_core                    ← App-level scope (parent)
├── netnam_cms_core.juniper        ← Exact scope
│   ├── netnam_cms_core.juniper.bgp
│   ├── netnam_cms_core.juniper.firewall
│   └── netnam_cms_core.juniper.interface
```

**Explicit `scope` field** avoids relying on tool name prefix conventions for scope matching.

---

### Layer 4 — Tool Registration Lifecycle

```
1. Django starts
         │
         ▼
   NautobotAppMcpServerConfig.ready()
         │
         ▼
   post_migrate signal connects  →  _on_post_migrate()
         │
         │  (runs after ALL apps' ready() hooks complete)
         │
         ▼
   register_mcp_tools()  is called
         │
         ├── Core tools registered first  (from mcp/tools/core.py)
         │
         └── Third-party app tools already in registry
             (they called register_mcp_tool() in their own ready() hooks)
```

**Why `post_migrate` instead of `ready()`:** Django's `post_migrate` fires after all app migrations — which is after every `ready()` hook has completed. This guarantees the MCP server's core tools are registered **before** any third-party app calls `register_mcp_tool()` in its own `ready()` hook.

```python
# nautobot_app_mcp_server/__init__.py  (current — shell only)
class NautobotAppMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    base_url = "mcp-server"     # URLs at /plugins/mcp-server/
    # ...
```

**Planned (`apps.py`):**

```python
# nautobot_app_mcp_server/apps.py  (planned per DESIGN.md)
class NautobotMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    base_url = "mcp-server"

    def ready(self):
        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs):
        if app_config.name == "nautobot_app_mcp_server":
            # Only runs once (when this app's migrations complete)
            # At this point all other apps' ready() hooks have already run
            app_config.register_mcp_tools()
```

---

### Layer 5 — Third-Party Tool Registration API

```python
# In third-party app: netnam_cms_core/__init__.py
from nautobot_mcp_server.mcp import register_mcp_tool

register_mcp_tool(
    name="juniper_interface_unit_list",
    func=juniper_interface_unit_list,
    description="List Juniper interface units.",
    input_schema={...},
    tier="app",
    app_label="netnam_cms_core",
    scope="netnam_cms_core.juniper",
)
```

**File:** `nautobot_app_mcp_server/mcp/__init__.py` — planned per `DESIGN.md`.

---

### Layer 6 — Tool Executor (Sync → Async Bridge)

Every MCP tool handler is `async def` (FastMCP requirement), but Django ORM is synchronous. The bridge is `asgiref.sync.sync_to_async` with `thread_sensitive=True` (safe for Django's ORM connection pool):

```python
# Inside each async tool handler  (planned per DESIGN.md)
from asgiref.sync import sync_to_async

@mcp.tool()
async def device_list(name: str | None = None, limit: int = 25, cursor: str | None = None):
    _get_devices = sync_to_async(_sync_device_list, thread_sensitive=True)
    user = get_user_from_request(request_context.request)
    result = await _get_devices(name=name, limit=limit, cursor=cursor, user=user)
    return result

def _sync_device_list(name, limit, cursor, user):
    qs = Device.objects.select_related("status", "platform", "location")
    qs = qs.restrict(user=user, action="view")   # Nautobot permission enforcement
    if name:
        qs = qs.filter(name__icontains=name)
    return paginate_queryset(qs, limit=limit, cursor=cursor)
```

---

### Layer 7 — Pagination and Summarization

**File:** `nautobot_app_mcp_server/mcp/tools/pagination.py` — planned per `DESIGN.md`.

```python
@dataclass
class PaginatedResult:
    items: list[dict[str, Any]]      # Serialized objects
    cursor: str | None               # base64(last_pk), None if last page
    total_count: int | None          # Only set when result exceeds threshold
    summary: dict | None             # Populated when > LIMIT_SUMMARIZE (100) items
```

**Key rule:** Count items **before** slicing so auto-summarize threshold fires correctly.

**Cursor encoding:** `base64(pk)` — opaque, URL-safe, avoids offset-based pagination instability.

**Limits:** `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`, `LIMIT_SUMMARIZE=100`.

```python
def paginate_queryset(qs, limit=25, cursor=None):
    limit = min(limit, LIMIT_MAX)
    qs = qs.order_by("pk")
    if cursor:
        last_pk = _decode_cursor(cursor)
        qs = qs.filter(pk__gt=last_pk)
    raw_items = list(qs[:limit + 1])      # fetch one extra to detect next page
    has_next = len(raw_items) > limit
    items = raw_items[:limit]
    serialized = [_serialize(i) for i in items]
    next_cursor = _encode_cursor(items[-1].pk) if has_next and items else None
    # Auto-summarize when raw count > LIMIT_SUMMARIZE
    if len(raw_items) > LIMIT_SUMMARIZE:
        full_count = qs.count()
        summary = {"total_count": full_count, "sample": serialized[:5], ...}
        serialized = serialized[:LIMIT_SUMMARIZE]
    return PaginatedResult(items=serialized, cursor=next_cursor, ...)
```

---

### Layer 8 — Session State (Per-Conversation Scoping)

```python
# nautobot_app_mcp_server/mcp/session.py  (planned per DESIGN.md)
@dataclass
class MCPSessionState:
    enabled_scopes: set[str]       # {"netnam_cms_core.juniper", "ipam.vlan"}
    enabled_searches: set[str]     # {"BGP"} — fuzzy matches active

    def get_active_tools(self, registry):
        # core tools (always) + scoped tools + searched tools
        ...
```

Sessions are stored in FastMCP's `StreamableHTTPSessionManager`, keyed by `Mcp-Session-Id` header (sent natively by all MCP-compliant clients). Sessions expire after 1 hour idle.

**Meta tools** (`mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools`) are `core` tier so they always appear in the manifest. They **modify and query** `MCPSessionState`:

```python
@mcp.tool()
def mcp_enable_tools(scope: str | None = None, search: str | None = None):
    """Enable tool scopes or fuzzy-search matches for this session.
    scope="netnam_cms_core.juniper" → activates that scope + all children
    search="BGP"                    → fuzzy match across all tool names"""

@mcp.tool()
def mcp_disable_tools(scope: str | None = None):
    """Disable tool scopes. scope=None → disable ALL non-core tools."""

@mcp.tool()
def mcp_list_tools(scope: str | None = None, search: str | None = None):
    """List all registered tools. Without args: returns currently active tools."""
```

---

## 4. Key Abstractions

| Abstraction | File | Purpose |
|---|---|---|
| `NautobotAppMcpServerConfig` | `nautobot_app_mcp_server/__init__.py` | Nautobot plugin entry point |
| `MCPToolRegistry` | `nautobot_app_mcp_server/mcp/registry.py` | Thread-safe in-memory tool registry singleton |
| `ToolDefinition` | `nautobot_app_mcp_server/mcp/registry.py` | Dataclass describing one tool |
| `MCPSessionState` | `nautobot_app_mcp_server/mcp/session.py` | Per-conversation enabled-scopes/searches state |
| `PaginatedResult` | `nautobot_app_mcp_server/mcp/tools/pagination.py` | Cursor page + optional summary |
| `register_mcp_tool()` | `nautobot_app_mcp_server/mcp/__init__.py` | Public API for third-party apps |
| `get_user_from_request()` | `nautobot_app_mcp_server/mcp/auth.py` | Extract Nautobot user from request auth |

---

## 5. Entry Points

### Django Plugin Entry
```
PLUGINS = ["nautobot_app_mcp_server"]  in development/nautobot_config.py
         │
         ▼
Nautobot discovers nautobot_app_mcp_server/__init__.py
         │
         ▼
NautobotAppMcpServerConfig is loaded
         │
         ▼
.ready() runs → connects post_migrate signal
```

### MCP HTTP Request Entry
```
Client  →  GET/POST /plugins/mcp-server/mcp/
              │
              ▼
         urls.py  →  mcp_view()
              │
              ▼
         get_mcp_app()  →  returns lazily-created FastMCP ASGI app
              │
              ▼
         FastMCP handles MCP protocol
         (list_tools → session → registry → tool func → ORM)
```

### CLI / Development Entry
```
poetry run invoke start
         │
         ▼
docker compose up  (development/docker-compose.dev.yml)
         │
         ├── nautobot  (runserver 0.0.0.0:8080)
         ├── worker    (celery worker)
         ├── beat      (celery beat)
         └── docs      (mkdocs serve on :8001)
```

---

## 6. Permissions Model

```
Every tool query:
    │
    ▼
get_user_from_request(request)
    │
    ├── Authorization: Token nbapikey_xxx  →  Token.objects.get(key=xxx) → User
    ├── request.user.is_authenticated      →  use session cookie user
    └── Otherwise                           →  AnonymousUser
    │
    ▼
Device.objects.restrict(user=user, action="view")
    │
    ▼
Nautobot's object-level permissions applied
    (same as REST API enforcement)
    │
    ▼
AnonymousUser → empty queryset (no error)
```

---

## 7. Out of Scope for V1

| Feature | Reason |
|---|---|
| Write tools (create/update/delete) | Focus on read-only v1 |
| MCP `resources` or `prompts` endpoints | Tools first |
| Redis session backend | In-memory sessions sufficient for v1 |
| Tool-level field permissions | Deferred |
| Streaming (SSE rows) | Cursor pagination handles memory |

---

## 8. Influences and Source Patterns

| Source | Pattern Reused |
|---|---|
| `netnam-cms-core/models/querysets.py` | `for_list_view()` / `for_detail_view()` queryset builder patterns |
| `notebooklm-mcp-cli` | FastMCP + decorator registry pattern |
| Nautobot core plugin architecture | `NautobotAppConfig`, `post_migrate` signal timing |
| Nautobot `NautobotModelViewSet` | Cursor pagination with `limit` capping |
