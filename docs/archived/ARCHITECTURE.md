# Architecture Analysis: Nautobot MCP Server — From Embedded to Standalone

> **Date:** 2026-04-04
> **Purpose:** Analysis and design for rewriting `nautobot-app-mcp-server` as a standalone process instead of a Nautobot app.
> **Status:** Analysis complete — design to follow.

---

## 1. Comparative Analysis: Three Implementations

### 1.1 Implementation Landscape

| | **nautobot-app-mcp-server** (this repo) | **gt732/nautobot-mcp** | **nautobot-mcp-cli** |
|---|---|---|---|
| **Architecture** | Embedded in Nautobot Django process | Sidecar (separate OS process) | Sidecar (CLI + REST API) |
| **MCP Transport** | Streamable HTTP inside WSGI | SSE standalone | stdio / REST |
| **FastMCP Version** | `^3.2.0` | `^1.6.0` | `^3.0.0` |
| **Auth** | Token (Nautobot ORM) | **None** | Token (REST) |
| **Session State** | Progressive disclosure, in-memory | None | None |
| **Tool Discovery** | Programmatic `register_mcp_tool()` | `@register_tool` + directory scan | 3 universal tools + workflows |
| **ORM vs REST** | Direct ORM | Direct ORM (same process DB) | REST API |
| **Testing** | Unit + integration | **None** | Unit |
| **Status** | Active | **Archived** (May 2025) | Active |
| **Complexity** | High (WSGI/ASGI bridge) | Low | Medium |

### 1.2 Key Insight: Architecture Determines Complexity

All three approaches call the same Nautobot ORM or REST API. The architectural choice that drives complexity is **where the MCP server runs**:

```
gt732 (sidecar ORM):     MCP process ──calls──► Nautobot ORM (direct DB)
                         Problem: called nautobot.setup() wrong, no auth

nautobot-mcp-cli (sidecar REST):  MCP process ──calls──► REST API
                         Problem: N+1 on complex relationships, N REST calls

nautobot-app-mcp-server (embedded):  Inside Nautobot Django process
                         Problem: WSGI can't provide ASGI lifespan
```

The embedded approach's complexity (daemon thread, lazy factory, `async_to_sync`, monkey-patching `_list_tools_mcp`) is entirely caused by **one root constraint**: Nautobot runs as WSGI, and FastMCP requires an ASGI lifespan.

---

## 2. Verification: Can a Standalone Process Access Nautobot's ORM?

**Answer: Yes, fully verified.**

Tests run against live Nautobot 3.0.0 with production data (5 devices, 19,516 prefixes, 6,330 IP addresses, 44 locations).

### 2.1 Verified Working

| Test | Result | Evidence |
|---|---|---|
| `nautobot.setup()` standalone | ✅ PASS | `Nautobot 3.0.0 initialized!` — idempotent |
| Core model imports | ✅ PASS | Device, Interface, Prefix, IPAddress, VLAN, VRF, Tenant, Status, Token |
| Basic data queries | ✅ PASS | 5 devices, 19,516 prefixes, 44 locations, 6,330 IPs |
| `RestrictedQuerySet` active | ✅ PASS | `DeviceQuerySet` MRO includes `RestrictedQuerySet` |
| Token auth | ✅ PASS | `Token.objects.get(key=...)` → `token.user` works standalone |
| `ObjectPermissionBackend` callable | ✅ PASS | `has_perm(user, "dcim.view_device")` works without middleware |
| Permission filtering | ✅ PASS | `AnonymousUser` → 0 results; superuser → all data |
| `select_related` chains | ✅ PASS | 2 rows in **1 SQL query** |
| `prefetch_related` chains | ✅ PASS | 3 rows in **2 SQL queries** |
| `validated_save()` | ✅ PASS | Runs `full_clean()` validation; rejects stale FKs |
| FastMCP `lifespan` under uvicorn | ✅ PASS | `streamable_http_app()` has `lifespan=lambda: session_manager.run()` |
| MCP JSON-RPC `tools/list` via HTTP | ✅ PASS | Session manager started, returned tools |
| End-to-end `call_tool` → ORM → JSON | ✅ PASS | `device_echo` → ORM query → JSON-RPC response |

### 2.2 Key Verified Behaviors

**`nautobot.setup()` is a first-class entry point:**
- Used by `nautobot-server` CLI, Celery workers, `nbshell`
- Reads `NAUTOBOT_CONFIG` env var or `~/.nautobot/nautobot_config.py`
- Loads all `INSTALLED_APPS` including `PLUGINS`
- `PLUGINS_CONFIG` is respected

**ORM is fully functional without web context:**

```python
import nautobot
nautobot.setup()  # No error, idempotent

from nautobot.dcim.models import Device
from nautobot.users.models import Token
from nautobot.core.authentication import ObjectPermissionBackend

# Token auth — works standalone
token = Token.objects.get(key="0123456789abcdef...")
user = token.user  # Direct relationship

# Permission filtering — works without middleware
backend = ObjectPermissionBackend()
backend.has_perm(user, "dcim.view_device")  # True for superuser

# RestrictedQuerySet — always active
Device.objects.count()        # With permissions applied
Device.objects.restrict(user, "view").count()  # Explicit

# Select/prefetch — efficient queries
Device.objects.select_related("status", "device_type", "role").filter(name="rtr-01")
# Result: 1 SQL query regardless of result size
```

**Validated save runs full Nautobot validation:**

```python
device.comments = "test"
device.validated_save()  # Runs full_clean() including:
                          # - Foreign key existence
                          # - Custom field validation
                          # - Status constraints
                          # - Any model-level validators
```

**FastMCP lifespan works under uvicorn:**

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("NautobotMCP")
http_app = mcp.streamable_http_app()

# Under uvicorn: lifespan=lambda: session_manager.run() is called
# automatically. Sessions persist. No daemon thread needed.

# Under direct test: must enter lifespan manually
async with mcp.session_manager.run():
    await http_app(scope, receive, send)  # works
```

**Django `SynchronousOnlyOperation` guard:**
- ORM calls inside `async def` must use `sync_to_async`
- This is the ONE pattern required — no daemon threads, no `async_to_sync` at the bridge layer
- Standard `thread_sensitive=True` reuses Django's connection pool

### 2.3 What Is NOT Required in Standalone

| Current complexity | Not needed in standalone |
|---|---|
| Daemon thread (`_ensure_lifespan_started`) | uvicorn handles lifespan |
| Lazy factory (`get_mcp_app()`) | `nautobot.setup()` runs at import time |
| `async_to_sync` at bridge level | FastMCP runs in its own event loop |
| `ContextVar` for request passthrough | No Django request to pass through |
| WSGI→ASGI bridge (`view.py`) | Standalone uvicorn ASGI app |
| Monkey-patching `_list_tools_mcp` | Still needed for progressive disclosure |

---

## 3. Architecture Decision: App vs Standalone

### 3.1 The Core Constraint

```
Nautobot runs as WSGI only (gunicorn/uWSGI).
FastMCP requires ASGI lifespan (session_manager.run()).
WSGI cannot provide an ASGI lifespan.
Therefore: FastMCP HTTP transport cannot be embedded in Nautobot's WSGI process.
```

Confirmed by:
- Nautobot's `nautobot/core/wsgi.py` → `get_wsgi_application()` — no ASGI equivalent
- Documentation: "Nautobot runs as a WSGI application"
- No `asgi.py` in Nautobot source
- Verified: `streamable_http_app()` lifespan requires uvicorn/Starlette to call it

### 3.2 Three Options Evaluated

**Option A: Keep embedded with daemon thread (current)**
- Current approach works but is complex
- Daemon thread, lazy factory, `async_to_sync` everywhere
- Monkey-patching FastMCP internals — fragile across versions
- Verdict: **Not recommended** — unnecessary complexity

**Option B: Nautobot App that starts a subprocess**
- Thin app calls `subprocess.Popen(["uvicorn", ...])` from `ready()`
- App structure adds no value (no web UI planned)
- Adds subprocess management complexity
- Verdict: **Not recommended** — worst of both worlds

**Option C: Fully standalone package (RECOMMENDED)**
- No Nautobot app structure
- Calls `nautobot.setup()` at startup
- FastMCP + uvicorn as standard ASGI app
- Same DB, same auth, same ORM power
- Verdict: **Recommended** — eliminates all WSGI complexity

### 3.3 What the App Structure Was Buying

| Current app feature | Standalone equivalent |
|---|---|
| URL auto-discovery | Set `NAUTOBOT_CONFIG` env var |
| Settings via `PLUGINS_CONFIG` | `nautobot_config.py` or env vars |
| `nautobot-server` management commands | Standalone CLI (`nautobot-app-mcp-server`) |
| Nautobot startup lifecycle | Standalone process startup |
| Docs view in Nautobot UI | Static docs or separate service |

**If the MCP server doesn't need a web UI in Nautobot's UI, the app structure provides no value.**

---

## 4. Recommended Architecture: Standalone MCP Server

### 4.1 High-Level Diagram

```
┌── Nautobot (gunicorn/uWSGI) ─────────────────────────────────────┐
│  WSGI process, unchanged                                          │
│  PLUGINS = ["nautobot_app_mcp_server"]  ← removed for MCP server │
│  Serves Nautobot web UI and REST API at :8080                    │
└──────────────────────────────────────────────────────────────────┘
         ▲
         │ NAUTOBOT_DB_* env vars (same PostgreSQL connection)
         │
┌────────┴──────────────────────────────────────────────────────────┐
│  MCP Server (uvicorn, port 8005)                               │
│  Standalone Python process — NOT part of Nautobot Django app   │
│                                                                  │
│  1. Read NAUTOBOT_CONFIG (or env vars)                         │
│  2. nautobot.setup() → full ORM access                         │
│  3. FastMCP streamable_http_app() → uvicorn handles lifespan  │
│  4. Token auth: extract from Authorization header              │
│  5. ORM queries via sync_to_async                              │
│                                                                  │
│  Claude Desktop/Code ──HTTP──► uvicorn (port 8005)            │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Key Design Points

#### Transport: FastMCP Streamable HTTP

```python
# Entry point: main.py
import nautobot
nautobot.setup()  # Must be before any model imports

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("NautobotMCP", json_response=True)

# Register tools (at import time, after nautobot.setup())
from nautobot_app_mcp_server.tools import register_all_tools
register_all_tools(mcp)

# uvicorn handles lifespan automatically
# No daemon thread, no lazy factory, no async_to_sync bridge
app = mcp.streamable_http_app()
```

```bash
# Run
uvicorn main:app --host 0.0.0.0 --port 8005

# Or with multiple workers
uvicorn main:app --host 0.0.0.0 --port 8005 --workers 4
```

#### Auth: Token from HTTP Header

```python
# auth.py
def get_user_from_token(token_key: str) -> User | AnonymousUser:
    """Look up user by token key. No middleware needed."""
    try:
        token = Token.objects.select_related("user").get(key=token_key)
        if token.is_expired:
            return AnonymousUser()
        return token.user
    except Token.DoesNotExist:
        return AnonymousUser()
```

The token is read from FastMCP's request context (set by MCP client's `Authorization` header).

#### ORM Bridge: `sync_to_async` Per Tool

```python
# Every async tool handler wraps the sync ORM call:
from asgiref.sync import sync_to_async

@mcp.tool()
async def device_list(ctx, limit: int = 25, cursor: str | None = None) -> list[dict]:
    token_key = ctx.request_context.auth_token  # FastMCP sets this
    user = get_user_from_token(token_key)
    if user is None:
        return {"error": "Invalid or missing token"}

    @sync_to_async
    def _query():
        return Device.objects.select_related(
            "status", "device_type", "role", "location"
        ).restrict(user, "view")

    devices = await _query()
    return [serialize_device(d) for d in devices]
```

#### Plugin Discovery: Django App Registry

```python
# Auto-discover tools from installed plugins at startup:
from django.apps import apps

def discover_plugin_tools():
    """Called at startup after nautobot.setup()."""
    for app_config in apps.get_app_configs():
        # Skip Django and Nautobot core
        if app_config.name.startswith(("django.", "nautobot.core")):
            continue
        # Check if app has a mcp_tools module
        try:
            import importlib
            mcp_module = importlib.import_module(f"{app_config.name}.mcp_tools")
            # Tool registration functions found
        except ImportError:
            continue
```

Plugins can also register via the `register_mcp_tool()` API called from their own `ready()` — but since this is standalone (not a Nautobot app), the mechanism would be a convention: `plugin.mcp_tools` module auto-imported at startup.

---

## 5. Important Notes and Gotchas

### 5.1 Nautobot Version-Specific Behaviors

These were discovered during verification against Nautobot 3.0.0:

| Behavior | Note |
|---|---|
| `Status` model | Has no `slug` field. Use `name` for lookups. |
| `Status.objects.get_for_model(Model)` | Correct API for getting statuses for a model |
| `Device` | Uses `comments` field (not `description`). Uses `primary_ip4`/`primary_ip6` (not `primary_ip`). |
| `Manufacturer` | Uses `name` as natural key (no `slug` field for get_or_create) |
| `Role` | Requires `content_types` field set via `Role.objects.get_for_model(Model)` |
| `Interface` | Relationship to IP is `ip_addresses` (not `ip_address_assignments`) |
| `Tenant.description` | Use for test writes (unlike Device which requires valid FKs) |

### 5.2 Verified: What Works Without Dependencies

| Feature | Works without middleware/Redis/Celery |
|---|---|
| All model queries | ✅ Yes |
| Token auth (`Token.objects.get()`) | ✅ Yes |
| Permission filtering (`.restrict()`) | ✅ Yes |
| `ObjectPermissionBackend.has_perm()` | ✅ Yes |
| `validated_save()` (full_clean) | ✅ Yes |
| Custom fields | ✅ Yes |
| ContentType lookup | ✅ Yes (falls back to DB) |
| Session middleware features | ❌ No (not applicable) |
| `cache.lock()` (Redis) | ⚠️ Redis needed — fails gracefully |

### 5.3 Critical: `sync_to_async` is Mandatory

```python
# WRONG — raises SynchronousOnlyOperation
@mcp.tool()
async def device_list(ctx):
    devices = Device.objects.all()  # ❌ ORM in async context

# CORRECT
@mcp.tool()
async def device_list(ctx):
    @sync_to_async
    def _query():
        return list(Device.objects.all())
    devices = await _query()  # ✅
```

This is the only ORM bridge pattern needed. No `async_to_sync`, no daemon thread, no event loop juggling.

### 5.4 Multi-Worker Deployment

Running uvicorn with `--workers N`:

- Each worker = separate Python process
- Each has its own `nautobot.setup()` call → own Django ORM state
- Each has its own DB connection pool
- Session state in `StreamableHTTPSessionManager` is per-worker (in-memory)
- If you need shared session state → Redis-backed session store (future enhancement)

This is the same as running N Celery workers with Django ORM. Works correctly.

### 5.5 Database Connection

- MCP server connects to the **same PostgreSQL instance** as Nautobot
- No Django middleware, no WSGI process coupling
- Connection params from `NAUTOBOT_CONFIG` (or env vars)
- `CONN_MAX_AGE=300` (5-minute persistent connections) — works with uvicorn workers

### 5.6 What `nautobot.setup()` Does

```python
# Pseudocode of what nautobot.setup() does:
def setup(config_path=None):
    if __initialized:  # idempotent guard
        return
    os.environ["DJANGO_SETTINGS_MODULE"] = "nautobot_config"
    load_settings(config_path)  # Loads ~/.nautobot/nautobot_config.py
    django.setup()  # Standard Django init
    __initialized = True
```

It reads `NAUTOBOT_CONFIG` env var or `~/.nautobot/nautobot_config.py`. Both are the same file Nautobot itself uses.

### 5.7 `nautobot_database_ready` Signal

The `post_migrate` signal that fires `nautobot_database_ready` is **not triggered** by standalone `django.setup()`. This means:
- Default CustomFields are not auto-populated
- Default Status objects must already exist (they do if Nautobot ran migrations)
- For fresh DB with no data: run `nautobot-server migrate` first from the Nautobot deployment

In practice: the DB is already seeded by the running Nautobot instance. The MCP server reads from that DB.

---

## 6. Migration Strategy

### 6.1 What to Keep

| Current component | Action |
|---|---|
| Tool implementations (`core.py`) | **Keep** — port `sync_to_async` wrappers |
| Auth (`auth.py`) | **Keep** — `get_user_from_request()` logic |
| Registry (`registry.py`) | **Keep** — `MCPToolRegistry` singleton |
| `register_mcp_tool()` API | **Keep** — public plugin API |
| Session tools (`session_tools.py`) | **Keep** — progressive disclosure |
| Query utilities (`query_utils.py`) | **Keep** — serializer helpers |
| Pagination (`pagination.py`) | **Keep** — cursor + summarize |
| Tests | **Keep** — adapt to standalone server |

### 6.2 What to Drop

| Current component | Reason |
|---|---|
| `server.py` (daemon thread, lazy factory) | Replaced by uvicorn lifespan |
| `view.py` (WSGI→ASGI bridge) | No longer needed |
| `urls.py` (Django URL routing) | Not a Django app |
| `NautobotAppConfig` | Not a Nautobot app |
| `post_migrate` signal wiring | Plugin discovery via Django `apps` registry |

### 6.3 New Structure

```
nautobot-app-mcp-server/          # Standalone pip package
├── pyproject.toml
├── README.md
├── src/
│   └── nautobot_app_mcp_server/
│       ├── __init__.py              # Calls nautobot.setup() at import
│       ├── main.py                   # uvicorn entry point
│       ├── server.py                 # FastMCP setup + tool registration
│       ├── auth.py                  # Token auth (kept)
│       ├── registry.py              # MCPToolRegistry (kept)
│       ├── tools/
│       │   ├── __init__.py          # register_all_tools(mcp)
│       │   ├── core.py             # 10 core tools (ported)
│       │   ├── session_tools.py    # Progressive disclosure (ported)
│       │   ├── pagination.py       # Cursor + summarize (kept)
│       │   └── query_utils.py      # Serializers (kept)
│       └── tests/
│           ├── test_auth.py
│           ├── test_core_tools.py
│           ├── test_session_tools.py
│           └── test_registry.py
├── deployment/
│   ├── Dockerfile
│   └── nautobot-app-mcp-server.service
└── docs/
```

### 6.4 Deployment Options

**Option 1: Docker sidecar**
```yaml
# docker-compose.yml
services:
  nautobot:
    image: nautobot-app-mcp-server:latest
    environment:
      NAUTOBOT_CONFIG: /config/nautobot_config.py
    volumes:
      - ./nautobot_config.py:/config/nautobot_config.py:ro
    depends_on: nautobot-db
    ports:
      - "8005:8005"
    command: uvicorn nautobot_app_mcp_server.main:app --host 0.0.0.0 --port 8005
```

**Option 2: Systemd service**
```ini
[Unit]
Description=Nautobot MCP Server
After=network.target

[Service]
Type=simple
User=nautobot
Environment="NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py"
ExecStart=/opt/nautobot/bin/uvicorn nautobot_app_mcp_server.main:app --host 127.0.0.1 --port 8005 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

**Option 3: Built into Nautobot Docker image**
```dockerfile
# In Nautobot's Dockerfile, add:
RUN pip install nautobot-app-mcp-server
# Add startup command for the MCP server process
```

---

## 7. Open Questions

1. **Plugin tool discovery:** How do plugins register tools without the `post_migrate` signal? Convention: `plugin.mcp_tools` module auto-imported at startup?
2. **Session state persistence:** In-memory sessions are lost on restart. Is Redis-backed session storage needed for v1?
3. **Multi-worker session sharing:** Sessions are per-worker. Is this acceptable for v1, or is shared session storage needed?
4. **Web UI:** Does this MCP server need a status dashboard in Nautobot's web UI? If yes, keep a thin Nautobot app for that.
5. **CMS plugin models:** The original motivation for embedding. With direct ORM access, CMS plugin models should be accessible via `django.apps.apps.get_model()`. Worth testing with `netnam_cms_core` when available.

---

## 8. References

- Verification script: `/tmp/nautobot-mcp-verify/verify_all.py`
- FastMCP 1.26.0 `streamable_http_app()` source: `site-packages/mcp/server/fastmcp/server.py` line 95
- `nautobot.setup()` entry point: `nautobot/__init__.py`
- Nautobot app vs plugin docs: https://docs.nautobot.com/projects/core/en/stable/development/apps/
- MCP Python SDK: https://github.com/ModelContextProtocol/python-sdk
