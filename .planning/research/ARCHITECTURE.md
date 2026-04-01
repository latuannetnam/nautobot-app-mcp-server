# Architecture Research — MCP Server in Django

**Domain:** Embedded Protocol Adapter (MCP/FastMCP inside a Django/Nautobot process)
**Researched:** 2026-04-01
**Confidence:** HIGH (verified via Nautobot plugin URL system + FastMCP ASGI structure)

---

## 1. Standard Architecture — MCP over Streamable HTTP in Django

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        External Layer (Outside Django)                        │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  MCP Client  (Claude Code, Claude Desktop)                         │    │
│  │  Sends:  POST /plugins/nautobot-app-mcp-server/mcp/                │    │
│  │          Headers: Authorization: Token nbapikey_xxx               │    │
│  │                    Mcp-Session-Id: <opaque>                       │    │
│  └───────────────────────────────┬──────────────────────────────────────┘    │
└──────────────────────────────────┼────────────────────────────────────────────┘
                                   │  Streamable HTTP (JSON-RPC)
┌──────────────────────────────────▼────────────────────────────────────────────┐
│                        Django Process (Nautobot)                               │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 1: URL Router  (Django urls.py)                               │    │
│  │  /plugins/nautobot-app-mcp-server/mcp/  →  mcp_view()              │    │
│  │  (from nautobot.extras.plugins.urls → plugin_patterns registry)    │    │
│  └───────────────────────────────┬──────────────────────────────────────┘    │
│                                  │                                              │
│  ┌───────────────────────────────▼──────────────────────────────────────┐    │
│  │  Layer 2: ASGI Bridge  (mcp_view)                                    │    │
│  │  Converts Django request → ASGI scope → calls FastMCP ASGI app       │    │
│  │  Returns ASGI response → Django HttpResponse                          │    │
│  └───────────────────────────────┬──────────────────────────────────────┘    │
│                                  │  ASGI call()                                │
│  ┌───────────────────────────────▼──────────────────────────────────────┐    │
│  │  Layer 3: FastMCP HTTP App  (streamable_http_app)                     │    │
│  │  StreamableHTTPSessionManager: session state by Mcp-Session-Id        │    │
│  │  Routes: POST /tools/call → tool handler                              │    │
│  │          GET  /tools/list → list_tools()                             │    │
│  │          POST /tools/list → list_tools()                             │    │
│  └───────────────────────────────┬──────────────────────────────────────┘    │
│                                  │                                              │
│  ┌───────────────────────────────▼──────────────────────────────────────┐    │
│  │  Layer 4: MCPToolRegistry  (in-memory singleton, thread-safe)         │    │
│  │  .get_all() / .get_core_tools() / .get_by_scope() / .fuzzy_search()   │    │
│  └───────────────────────────────┬──────────────────────────────────────┘    │
│                                  │                                              │
│  ┌───────────────────────────────▼──────────────────────────────────────┐    │
│  │  Layer 5: Tool Executor  (sync_to_async bridge)                       │    │
│  │  async def tool_handler()  →  sync_to_async(sync_func)               │    │
│  │  → Django ORM (Device.objects.select_related(...).restrict())        │    │
│  └───────────────────────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────────────────┤
│  Nautobot ORM (direct, no HTTP)   Device, Interface, IPAddress, Prefix…      │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Responsibilities

| Component | File (planned) | Responsibility | Implementation |
|-----------|---------------|---------------|----------------|
| **URL registration** | `nautobot_app_mcp_server/urls.py` | Expose `/mcp/` route to Nautobot plugin URL system | Django `path()` + ASGI bridge view |
| **ASGI bridge** | `nautobot_app_mcp_server/mcp/view.py` | Convert Django `HttpRequest` ↔ ASGI `scope`/`call` protocol | `ASGIRequestHandler` from `asgiref` |
| **FastMCP server** | `nautobot_app_mcp_server/mcp/server.py` | ASGI app factory, session manager, lifespan | `FastMCP()` + `streamable_http_app()` |
| **Tool registry** | `nautobot_app_mcp_server/mcp/registry.py` | Thread-safe in-memory singleton, tool registration/discovery | `threading.Lock` singleton |
| **Session state** | `nautobot_app_mcp_server/mcp/session.py` | Per-conversation enabled scopes + fuzzy searches | Dataclass stored in FastMCP session manager |
| **Auth** | `nautobot_app_mcp_server/mcp/auth.py` | Extract Nautobot user from request token | `Token.objects.get(key=...)` |
| **Pagination** | `nautobot_app_mcp_server/mcp/tools/pagination.py` | Cursor-based pagination + auto-summarize | `base64(pk)` cursors |
| **Core tools** | `nautobot_app_mcp_server/mcp/tools/core.py` | 10 read tools + 3 meta tools | Sync functions wrapped by FastMCP decorator |
| **Query utilities** | `nautobot_app_mcp_server/mcp/tools/query_utils.py` | Shared `select_related`/`restrict` chains | Reusable queryset builder functions |
| **Plugin entry** | `nautobot_app_mcp_server/__init__.py` | Nautobot plugin hook, `post_migrate` signal | `NautobotAppConfig` subclass |

---

## 3. Recommended Project Structure

```
nautobot_app_mcp_server/
├── __init__.py                     # NautobotAppConfig: name="nautobot_app_mcp_server"
│                                 # base_url = "nautobot-app-mcp-server"
├── urls.py                        # path("mcp/", mcp_view)  ← Entry point
├── apps.py                        # post_migrate → register_mcp_tools()
├── mcp/
│   ├── __init__.py                # register_mcp_tool() public API
│   ├── view.py                    # ASGI bridge (Django → FastMCP)
│   ├── server.py                  # FastMCP instance + streamable_http_app factory
│   ├── registry.py                # MCPToolRegistry singleton + ToolDefinition
│   ├── session.py                 # MCPSessionState dataclass
│   ├── auth.py                    # get_user_from_request()
│   └── tools/
│       ├── __init__.py
│       ├── core.py                # @register_core_tool + 10 core sync functions
│       ├── pagination.py          # paginate_queryset() + PaginatedResult
│       └── query_utils.py         # Shared queryset builders (select_related chains)
└── tests/
    ├── __init__.py
    ├── test_registry.py
    ├── test_core_tools.py
    ├── test_view.py               # ASGI bridge tests
    └── test_signal_integration.py
```

**Structure Rationale:**
- **`mcp/view.py`**: Isolates the Django↔ASGI boundary so `server.py` stays pure FastMCP. The view is the only file that knows about Django request/response objects.
- **`mcp/tools/` subdirectory**: Core tools, pagination, and query utilities are separate because each has distinct responsibilities and different testing strategies.
- **`apps.py` separate from `__init__.py`**: `post_migrate` signal registration is its own concern, keeping the Nautobot app config class minimal.

---

## 4. Architectural Patterns

### Pattern 1: Embedded Protocol Adapter

**What:** A protocol server (MCP) lives inside the same process as a Django/Nautobot app, accessed via a Django URL route. No separate port, no extra service to manage.

**When to use:** When you want zero network overhead, direct ORM access, and unified permission enforcement without deploying a separate microservice.

**Trade-offs:**
- ✅ Direct ORM access — no HTTP serialization/deserialization overhead
- ✅ Nautobot permissions work out of the box via `.restrict(user, action)`
- ✅ Single deployment unit — one `PLUGINS = ["nautobot_app_mcp_server"]` entry
- ✅ No extra port to expose or firewall rule to manage
- ❌ Couples MCP lifecycle to Django worker lifecycle
- ❌ Django's multi-threaded (not async-native) workers require `sync_to_async` bridging

**Example:**
```python
# urls.py — Django URL at /plugins/nautobot-app-mcp-server/mcp/
from nautobot_app_mcp_server.mcp.view import mcp_view
urlpatterns = [path("mcp/", mcp_view)]
```
```python
# mcp/view.py — Bridge Django → FastMCP ASGI
from asgiref.wsgi import WsgiToAsgi
from nautobot_app_mcp_server.mcp.server import get_mcp_app

def mcp_view(request):
    """Delegate a Django request to the FastMCP ASGI app."""
    app = get_mcp_app()          # Lazily-created ASGI app
    handler = WsgiToAsgi(app)    # Wrap ASGI → WSGI bridge for Django
    return handler(request)      # Returns Django HttpResponse
```

---

### Pattern 2: Lazy ASGI App Initialization

**What:** The FastMCP ASGI app is `None` at module import time and is created on the first HTTP request, not during Django startup.

**When to use:** Always for FastMCP in Django. Django's startup sequence (app loading, migrations, signals) runs before any HTTP requests arrive. Creating the ASGI app during `apps.py ready()` or module-level import risks:
1. Circular import cycles (FastMCP imports tools → tools import Nautobot ORM → ORM not ready)
2. Thread state not initialized (Django ORM requires a request context for thread-sensitive mode)
3. `post_migrate` signal not yet connected

**Trade-offs:**
- ✅ No Django startup race conditions
- ✅ First request always has a fully-initialized ORM connection pool
- ❌ First request is slightly slower (ASGI app created on-demand)
- ❌ Global mutable state (`_mcp_app`) — mitigated by thread-safety of FastMCP session manager

**Example:**
```python
# mcp/server.py
_mcp_app: ASGIApplication | None = None

def get_mcp_app() -> ASGIApplication:
    """Lazily build the FastMCP ASGI app on first HTTP request."""
    global _mcp_app
    if _mcp_app is None:
        mcp = FastMCP("NautobotMCP", stateless_http=False, json_response=True)
        _register_core_tools(mcp)
        session_manager = StreamableHTTPSessionManager(
            entrypoint=mcp,
            max_session_age=3600,
        )
        _mcp_app = mcp.streamable_http_app(
            path="/mcp",
            session_manager=session_manager,
        )
    return _mcp_app
```

---

### Pattern 3: sync_to_async Bridge with thread_sensitive=True

**What:** Every FastMCP async tool handler calls Django ORM via `asgiref.sync.sync_to_async(fn, thread_sensitive=True)`. The sync function does the actual ORM work.

**When to use:** Every time FastMCP (async-native) calls Django ORM (sync by default). Required for all tool handlers.

**Trade-offs:**
- ✅ Thread-sensitive mode reuses Django's thread-local connection pool — safe, no connection leaks
- ✅ Tool functions remain sync and testable without async infrastructure
- ✅ Nautobot ORM middleware (request-scoped state) works because the same thread handles the full request
- ❌ One thread per concurrent tool call — fine for I/O-bound workloads, but consider `run_in_executor` if ORM becomes a bottleneck
- ❌ `sync_to_async` with `thread_sensitive=True` requires the caller is already running in an async context with a Django request active (guaranteed in FastMCP tool handlers)

**Example:**
```python
# mcp/tools/core.py
from asgiref.sync import sync_to_async

@mcp.tool()
async def device_list(name: str | None = None, limit: int = 25, cursor: str | None = None):
    _get = sync_to_async(_sync_device_list, thread_sensitive=True)
    user = get_user_from_request(request_context.request)
    return await _get(name=name, limit=limit, cursor=cursor, user=user)

def _sync_device_list(name, limit, cursor, user):
    qs = Device.objects.select_related("status", "platform", "location")
    qs = qs.restrict(user=user, action="view")
    if name:
        qs = qs.filter(name__icontains=name)
    return paginate_queryset(qs, limit=limit, cursor=cursor)
```

---

### Pattern 4: Thread-Safe Singleton Registry

**What:** Tool registry is a module-level singleton using `threading.Lock` (not Django models). Safe for Django's threaded workers.

**When to use:** When tools need to be registered dynamically by multiple Django apps at startup, but reads happen on every MCP request from multiple threads.

**Trade-offs:**
- ✅ Thread-safe, works with Django threaded workers
- ✅ Single global source of truth for all MCP tools
- ✅ Third-party apps can call `register_mcp_tool()` at any time after Django startup
- ❌ No persistence — tools re-registered on every Django restart
- ❌ No cross-process sharing (if you scale to multiple Django processes, each has its own registry — mitigated by sticky sessions or shared-nothing design)

**Example:**
```python
# mcp/registry.py
class MCPToolRegistry:
    _instance: "MCPToolRegistry | None" = None
    _lock = threading.Lock()
    _tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> "MCPToolRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:   # Double-checked locking
                    cls._instance = cls()
        return cls._instance
```

---

## 5. Data Flow

### Request Flow (Complete)

```
MCP Client
    │
    │  POST /plugins/nautobot-app-mcp-server/mcp/  (JSON-RPC body)
    │  Headers: Authorization: Token nbapikey_xxx
    │            Mcp-Session-Id: abc123
    │            Content-Type: application/json
    ▼
Django URL Router
    │
    │  /plugins/nautobot-app-mcp-server/mcp/
    │  → plugin_patterns auto-included from nautobot_app_mcp_server/urls.py
    ▼
urls.py  →  path("mcp/", mcp_view)
    │
    ▼
mcp_view()  [Django view]
    │
    │  request.META, request.body, request.headers
    │
    ▼
get_mcp_app()  [lazy init, first request only]
    │
    ▼
FastMCP streamable_http_app  [ASGI app]
    │
    │  FastMCP session manager looks up Mcp-Session-Id → MCPSessionState
    │  FastMCP parses JSON-RPC body → MCP protocol
    │
    ├── GET /mcp/  or  POST /mcp/  (MCP initialize/ping)
    │
    ├── POST /mcp/  (tools/list)  →  list_tools()
    │                                    │
    │                               MCPToolRegistry.get_all()
    │                               MCPSessionState.get_active_tools()
    │                               → [Tool(name, description, inputSchema)...]
    │
    └── POST /mcp/  (tools/call)  →  tool_handler()
                                         │
                                    get_user_from_request(request)
                                         │
                                    sync_to_async(sync_func)()
                                         │
                                    Django ORM: Device.objects.select_related()...
                                         │
                                    paginate_queryset(qs)
                                         │
                                    PaginatedResult(items, cursor, summary)
                                         │
    ▼
ASGI Response  →  WsgiToAsgi()  →  Django HttpResponse
    │
    │  JSON-RPC body: {"jsonrpc": "2.0", "result": {...}}
    ▼
MCP Client receives response
```

### Key Data Flows

1. **Tool registration flow:** `NautobotAppConfig.ready()` → `post_migrate` signal → `register_mcp_tools()` → `MCPToolRegistry.register()` — happens once at Django startup, before any HTTP requests.
2. **Request→user flow:** HTTP `Authorization: Token` header → `auth.py get_user_from_request()` → `request.user` / `AnonymousUser` → `.restrict(user, action)` on every queryset.
3. **Session state flow:** HTTP `Mcp-Session-Id` header → FastMCP session manager → `MCPSessionState` (scopes + searches) → `list_tools()` filters registry → tool manifest returned to client.
4. **Tool call flow:** JSON-RPC `call_tool` → FastMCP → `sync_to_async` bridge → Django ORM → `paginate_queryset()` → serialized `PaginatedResult` → JSON-RPC response.

---

## 6. Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0–100 concurrent MCP sessions | Single Django worker — in-memory registry + FastMCP sessions are fine |
| 100–1000 concurrent sessions | Django gunicorn with multiple workers — each has its own registry copy (acceptable; registry is write-once at startup) |
| 1000+ concurrent sessions | Option B (separate MCP worker) or Redis-backed session store; sticky sessions on load balancer |

### Scaling Priorities

1. **First bottleneck: ASGI bridge thread contention.** Django threaded workers with `sync_to_async` calls can saturate threads if many concurrent tool calls hit the ORM simultaneously. Fix: increase gunicorn worker count or migrate to gevent worker.
2. **Second bottleneck: Tool registry reads.** `MCPToolRegistry` reads (every `list_tools` call) dominate at scale. Dictionary reads are O(1) — fine up to thousands of tools. No optimization needed in v1.
3. **Third bottleneck: Session state memory.** FastMCP `StreamableHTTPSessionManager` stores `MCPSessionState` in memory per session. Sessions expire after 1 hour idle. For 10k+ concurrent sessions, swap to Redis-backed session storage (future enhancement, not v1 scope).

---

## 7. Anti-Patterns

### Anti-Pattern 1: Creating ASGI App at Import Time

**What people do:**
```python
# mcp/server.py — WRONG
mcp = FastMCP("NautobotMCP", ...)  # Created at module import
_mcp_app = mcp.streamable_http_app(...)  # Also at import
```

**Why it's wrong:** Django app loading runs before the request thread is set up. `sync_to_async(thread_sensitive=True)` requires a Django request context on the thread. If the FastMCP app is created during import, the first call from a worker thread may fail with `"RuntimeError: AuthenticationGuards can't be accessed outside of an active HTTP request"`.

**Do this instead:** Lazy initialization (`get_mcp_app()` called from the view function, not at module load time).

---

### Anti-Pattern 2: Using sync ORM directly in async tool handler (no sync_to_async)

**What people do:**
```python
# WRONG
@mcp.tool()
async def device_list(name: str | None = None):
    qs = Device.objects.filter(name__icontains=name)  # No sync_to_async!
    return list(qs)
```

**Why it's wrong:** Blocks the asyncio event loop thread, causing all concurrent tool calls to stall. In a thread-per-worker Django deployment, this causes request queuing.

**Do this instead:** Wrap with `sync_to_async(sync_fn, thread_sensitive=True)` — always.

---

### Anti-Pattern 3: Mixing DJANGO_SETTINGS_MODULE ASGI with plugin ASGI

**What people do:** Trying to override Nautobot's `asgi.py` to mount the MCP server at a root path. This modifies core Nautobot files, breaking upgrades and CI reproducibility.

**Why it's wrong:** Changes are lost on Nautobot upgrade. Breaks the plugin contract — the MCP server should be a drop-in plugin, not a core modification.

**Do this instead:** Use the Django URL route via `nautobot_app_mcp_server/urls.py` — Nautobot's `plugin_patterns` system handles this automatically. No core files modified.

---

### Anti-Pattern 4: Storing Sessions in Django Database

**What people do:** Using `django.contrib.sessions` or a Django model to store MCP session state.

**Why it's wrong:** MCP session state (enabled scopes, fuzzy searches) is ephemeral, per-connection metadata — not persistent data that needs ACID guarantees. A database round-trip on every MCP request adds unnecessary latency and schema complexity.

**Do this instead:** FastMCP `StreamableHTTPSessionManager` stores session state in memory. Redis swap-in is available when needed (not v1).

---

## 8. Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Nautobot Django ORM** | Direct import: `from nautobot.dcim.models import Device` | No HTTP, no serialization. ORM is the primary data source. |
| **Nautobot Token auth** | `Token.objects.get(key=token_key)` from `nautobot.users.models` | Looks up user for `.restrict()` permission enforcement |
| **MCP Client** | Streamable HTTP, JSON-RPC over POST | Standard MCP protocol; no special client config needed |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `urls.py` → `mcp/view.py` | Django `request` object | `urls.py` routes to `mcp_view()` |
| `mcp/view.py` → `mcp/server.py` | `get_mcp_app()` lazy factory | View never imports FastMCP directly — only the bridge |
| `mcp/server.py` → `mcp/registry.py` | In-memory function call | Registry is a singleton; server reads tools at request time |
| `mcp/tools/core.py` → `mcp/auth.py` | In-memory function call | Auth module extracts user for ORM `.restrict()` |
| `mcp/tools/core.py` → `mcp/tools/pagination.py` | In-memory function call | Pagination called inside sync tool functions |
| `MCPToolRegistry` → third-party apps | `register_mcp_tool()` public API | Called in third-party `ready()` hooks; registry is write-once |

---

## 9. Resolution: Option A vs Option B (ASGI Mount vs Separate Worker)

### Decision: **Option A — Django URL Route + ASGI Bridge (RECOMMENDED)**

Evidence:
1. **Nautobot plugin URL system supports this natively.** `nautobot.extras.plugins.urls` iterates `settings.PLUGINS` and auto-includes each plugin's `urls.urlpatterns`. A plugin `urls.py` with `path("mcp/", mcp_view)` is automatically mounted at `/plugins/<base_url>/mcp/`. No core Nautobot files are modified.
2. **FastMCP `streamable_http_app()` is a pure ASGI application.** It accepts ASGI `scope`/`receive`/`send` — identical to what `asgiref`'s `WsgiToAsgi` wrapper converts from Django's WSGI interface. The bridge is a standard pattern.
3. **`django-starlette` is unnecessary complexity.** The stated goal of `django-starlette` is mounting multiple ASGI apps under Django. FastMCP is a single app, callable via a Django view. The `asgiref` bridge is a one-liner.
4. **No extra port exposure.** Claude Code connects to `http://nautobot:8080/plugins/nautobot-app-mcp-server/mcp/` — same port, same host, no additional firewall rules or Docker port mappings needed.
5. **Permissions integration is automatic.** Since the MCP server runs in the Django process, `MCPToolRegistry` and all tool handlers have direct access to the Django request context, Nautobot's token auth, and the ORM with `.restrict()` enforcement.

### Option B — Separate Worker (Fallback)

**When to use:** If Option A proves unstable under production gunicorn workers with `threads > 1`, or if the MCP server needs to be independently restarted without affecting Nautobot.

**Trade-offs:**
- ✅ Independent lifecycle — Nautobot restarts don't interrupt MCP
- ✅ Can use async-native worker (uvicorn) for higher concurrency
- ❌ Extra port (9001) to expose and firewall
- ❌ Requires Docker Compose service definition changes
- ❌ Harder to share Nautobot ORM permissions context without additional auth overhead
- ❌ Adds deployment complexity (two processes instead of one)

### Implementation: Option A — Verified Path

```python
# nautobot_app_mcp_server/urls.py
from django.urls import path

from nautobot_app_mcp_server.mcp.view import mcp_view

urlpatterns = [
    path("mcp/", mcp_view, name="mcp"),
]
```

```python
# nautobot_app_mcp_server/mcp/view.py
from asgiref.wsgi import WsgiToAsgi

from nautobot_app_mcp_server.mcp.server import get_mcp_app

def mcp_view(request):
    """Bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""
    app = get_mcp_app()          # Lazy: created on first request
    handler = WsgiToAsgi(app)    # FastMCP ASGI → ASGI→WSGI bridge
    return handler(request)      # Django expects WSGI (HttpResponse)
```

```python
# nautobot_app_mcp_server/__init__.py
class NautobotAppMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    base_url = "nautobot-app-mcp-server"   # → /plugins/nautobot-app-mcp-server/
```

**How it works:** Nautobot's `plugin_patterns` registry calls `import_object("nautobot_app_mcp_server.urls.urlpatterns")` for each plugin. This auto-mounts `/plugins/nautobot-app-mcp-server/mcp/` with zero configuration in core files.

---

## 10. Build Order (Dependencies Between Components)

The components must be built in dependency order. Building out of order causes import failures or runtime errors.

```
Phase 1: Infrastructure Foundation
├── 1a. Package scaffolding + pyproject.toml (add fastmcp, mcp dependencies)
├── 1b. mcp/server.py  — FastMCP instance + streamable_http_app factory
│       (No Django imports — pure FastMCP. Can be tested with ASGITestClient.)
└── 1c. mcp/view.py    — ASGI bridge + urls.py
        (Connects Django → FastMCP. Testable with Django test client.)

Phase 2: Core Data Layer
├── 2a. mcp/registry.py   — MCPToolRegistry singleton
│       (No Django, no FastMCP. Pure Python. Fully unit-testable.)
├── 2b. mcp/tools/query_utils.py  — Reusable queryset builders
│       (No FastMCP. Imports Nautobot ORM. Testable with Django ORM mocks.)
├── 2c. mcp/tools/pagination.py  — Cursor pagination + PaginatedResult
│       (No FastMCP, no Django ORM. Testable with plain Django model mocks.)
└── 2d. mcp/tools/core.py  — 10 core sync tool functions
        (Depends on registry, pagination, auth. No FastMCP decorator yet.)

Phase 3: MCP Integration
├── 3a. mcp/server.py  — Update to call _register_core_tools() on init
│       (Wires registry into FastMCP. Imports core.py.)
├── 3b. mcp/session.py  — MCPSessionState dataclass
│       (No dependencies. Testable standalone.)
├── 3c. mcp/auth.py  — get_user_from_request()
│       (Depends on Nautobot Token model. No FastMCP.)
└── 3d. mcp/tools/core.py  — Add @mcp.tool() decorators (depends on mcp/server.py)
        (FastMCP decorators. All previous layers now wired together.)

Phase 4: Nautobot Plugin Integration
├── 4a. apps.py  — post_migrate signal + register_mcp_tools()
│       (Nautobot plugin hook. Connects registry → plugin lifecycle.)
├── 4b. __init__.py  — NautobotAppConfig with base_url, ready() → post_migrate
│       (Entry point. Assumes all above modules exist.)
└── 4c. urls.py  — Django URL route (final piece that activates the whole chain)

Phase 5: Testing & Polish
├── 5a. test_registry.py  — Thread safety, singleton, registration
├── 5b. test_view.py  — ASGI bridge, HTTP round-trip
├── 5c. test_core_tools.py  — ORM mocking, pagination, auth
└── 5d. test_signal_integration.py  — post_migrate, tool registration
```

**Critical path insight:** `mcp/server.py` is the hub — it imports both FastMCP (external) and all tool modules (internal). Build it in two passes: first pass (1b) establishes the ASGI app skeleton, second pass (3a) wires in the full tool registry.

---

## Sources

- **Nautobot plugin URL routing:** `nautobot/nautobot/extras/plugins/urls.py` — verified auto-discovery pattern
- **FastMCP ASGI structure:** `streamable_http_app()` returns a callable ASGI app (`scope`/`receive`/`send`)
- **asgiref bridge:** `asgiref.wsgi.WsgiToAsgi` — standard Django↔ASGI bridge used by uvicorn, gunicorn
- **Django ASGI integration:** `nautobot/core/settings.py` — `ROOT_URLCONF = "nautobot.core.urls"`, standard Django WSGI stack
- **`sync_to_async` threading:** `asgiref.sync.sync_to_async(..., thread_sensitive=True)` — Django-ORM-compatible async bridge
- **Nautobot permission model:** `Device.objects.restrict(user, action)` — object-level permissions, the same enforcement used by Nautobot's REST API
- **`netnam-cms-core` queryset patterns:** `for_list_view()` / `for_detail_view()` — production-tested queryset builder patterns

---
*Architecture research for: MCP server embedded in Django/Nautobot*
*Researched: 2026-04-01*
