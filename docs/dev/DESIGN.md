# Nautobot MCP Server — Implementation Plan

## Context

Nautobot has no built-in MCP server. AI agents (Claude Code, Claude Desktop) must currently connect via a standalone external MCP client calling Nautobot's REST API — inefficient, no permissions integration, no tool discovery across Nautobot apps.

**Goal:** Build a Nautobot app (`nautobot-app-mcp-server`) that:
1. Exposes MCP over HTTP, embedded inside Nautobot's Django process
2. Uses direct Django ORM — zero network overhead
3. Supports **progressive disclosure** of tools (8 Core + discoverable per-model)
4. Allows other Nautobot apps to register tools via signal/registry
5. Includes a separate `nautobot-mcp-skill` SKILL.md package

**Sources referenced:**
- `D:\latuan\Programming\nautobot-project\nautobot` — Nautobot core plugin architecture
- `D:\latuan\Programming\nautobot-project\netnam-cms-core` — production Nautobot app with optimized querysets
- `D:\latuan\Programming\nautobot-project\notebooklm-mcp-cli` — FastMCP + decorator registry pattern

---

## Key Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Option A: FastMCP ASGI app mounted via Django URL view + ASGI bridge | Django view delegates to FastMCP ASGI app; no dependency on unverified internal Nautobot APIs |
| 1b | Option B: Separate worker on different port | Simpler deployment, separate process, for environments where ASGI mount is complex |
| 2 | Signal/Registry for extensibility | `post_migrate` signal (not `ready()`) ensures all apps' `ready()` hooks complete before registration |
| 3 | `stateless_http=False` — session tracking via `Mcp-Session-Id` | Per-conversation scope state works across all MCP clients |
| 4 | Progressive disclosure — Core + Per-model tiers | Avoids tool explosion in Claude context |
| 5 | Cursor-based pagination with `limit=25` default | Stable across concurrent writes, memory-safe |
| 6 | Separate `nautobot-mcp-skill` SKILL.md package | Independent updates, follows Claude skills pattern |
| 7 | Per-model named tools (not generic query tool) | Better Claude discoverability than generic routing |
| 8 | `select_related`/`prefetch_related` chains per tool | Memory optimization, follows netnam-cms-core patterns |
| 9 | `sync_to_async` for ORM calls inside async tool handlers | Bridges FastMCP async handlers with synchronous Django ORM |
| 10 | Explicit `scope` field on `ToolDefinition` | Avoids relying on tool name prefix convention for scope matching |

---

## Architecture

```
Claude Code / Claude Desktop / Antigravity / OpenClaw
        │
        │  Streamable HTTP (stateful)
        │  GET/POST /plugins/nautobot-app-mcp-server/mcp/
        │  Auth: Nautobot session cookie
        │  Mcp-Session-Id: (native MCP, per-conversation)
        ▼
┌─────────────────────────────────────────────┐
│  Nautobot Django Process                     │
│  ┌───────────────────────────────────────┐  │
│  │  FastMCP HTTP Server (mounted route)  │  │
│  │  stateless_http=False, json_response  │  │
│  │  SessionManager tracks per-session     │  │
│  │  scope state by Mcp-Session-Id        │  │
│  └───────────────┬───────────────────────┘  │
│                  │                           │
│  ┌───────────────▼───────────────────────┐  │
│  │  Tool Registry (in-memory dict)        │  │
│  │  CoreTools + RegisteredThirdPartyTools │  │
│  └───────────────┬───────────────────────┘  │
│                  │                           │
│  ┌───────────────▼───────────────────────┐  │
│  │  Tool Executor                         │  │
│  │  → Django ORM (direct, no HTTP)        │  │
│  │  → Optimized querysets                 │  │
│  │  → Cursor pagination                   │  │
│  │  → Nautobot permissions (user auth)    │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
        ▲
        │  register_mcp_tool() signal (Nautobot ready())
        │  Third-party apps call during their ready()
        │
  ┌─────┴─────────────────────────────┐
  │  netnam_cms_core etc.           │
  │  __init__.py                    │
  │  from nautobot_app_mcp_server.mcp   │
  │    import register_mcp_tool      │
  └─────────────────────────────────┘

Also:
  ┌──────────────────────────┐
  │  nautobot-mcp-skill/     │  ← Separate pip package
  │  SKILL.md                │  ← "When to use which tool",
  │  reference/              │     workflow patterns, field guides
  └──────────────────────────┘
```

---

## Directory Structure

```
nautobot-app-mcp-server/
├── nautobot_app_mcp_server/              # Nautobot app package
│   ├── __init__.py                   # NautobotAppConfig entry point
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py                 # FastMCP server init + lifespan
│   │   ├── registry.py               # Tool registry (register/discover)
│   │   ├── session.py               # MCPSessionState per Mcp-Session-Id
│   │   ├── auth.py                  # Nautobot token auth extraction
│   │   ├── tools/                    # Core tool implementations
│   │   │   ├── __init__.py
│   │   │   ├── core.py               # Core tools (always visible)
│   │   │   ├── pagination.py         # Cursor + auto-summarize helpers
│   │   │   ├── permissions.py        # Nautobot permission enforcement
│   │   │   └── query_utils.py         # Shared queryset builders
│   │   ├── session.py               # MCPSessionState per Mcp-Session-Id
│   │   ├── auth.py                # Nautobot token auth extraction
│   └── urls.py                       # URL routing: /plugins/nautobot-app-mcp-server/mcp/
├── tests/
│   ├── __init__.py
│   ├── test_registry.py
│   ├── test_core_tools.py
│   └── test_signal_integration.py
└── pyproject.toml

nautobot-mcp-skill/                   # Separate pip package
├── SKILL.md                          # Main skill instructions
├── reference/
│   ├── devices.md
│   ├── interfaces.md
│   ├── ipam.md
│   └── juniper.md                    # For netnam_cms_core
├── workflows/
│   ├── device-investigation.md
│   └── network-change.md
└── pyproject.toml                    # Installed via: claude skill add nautobot-mcp-skill
```

---

## Design Decisions per Component

### 1. MCP Server — FastMCP Stateful HTTP Mount

**File:** `nautobot_app_mcp_server/mcp/server.py`

```python
from fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

mcp = FastMCP(
    "NautobotMCP",
    stateless_http=False,         # Session state per Mcp-Session-Id
    json_response=True,
)

# Lazily initialized ASGI app; created on first request to avoid
# Django startup race conditions.
_mcp_app: ASGIApplication | None = None

def get_mcp_app() -> ASGIApplication:
    global _mcp_app
    if _mcp_app is None:
        _mcp_app = mcp.streamable_http_app(
            path="/mcp",
            session_manager=StreamableHTTPSessionManager(
                entrypoint=mcp,
                max_session_age=3600,  # sessions expire after 1 hour idle
            ),
        )
    return _mcp_app
```

**URL routing — two deployment options:**

**Option A — ASGI bridge via Django view (recommended):**

```python
# nautobot_app_mcp_server/urls.py
from django.urls import path
from starlette.routing import Route
from starlette.testclient import ASGITestClient
from asgiref.sync import async_to_sync

# Lazy import avoids startup race
def mcp_view(request):
    """Django view that delegates to the FastMCP ASGI app."""
    app = get_mcp_app()
    # Wrap Django request as ASGI scope and call the FastMCP app
    scope = {
        "type": "http",
        "method": request.method,
        "path": request.path,
        "query_string": request.META.get("QUERY_STRING", "").encode(),
        "headers": [
            (k.encode(), v.encode())
            for k, v in request.headers.items()
        ],
        "root_path": f"/plugins/nautobot-app-mcp-server",
        "client": (request.META.get("REMOTE_ADDR", "127.0.0.1"), 0),
    }
    # FastMCP handles HTTP body read / response write directly
    # This is the standard Starlette-in-Django bridge pattern.
    raise NotImplementedError("Use asgiref WsgiToAsgiHandler or Starlette ASGI mount instead")
```

**Revised Option A (cleaner):** Use `django-starlette` / `asgiref.WsgiToAsgiHandler` to mount FastMCP's Starlette app as a Django URL route, or use Nautobot's existing pattern for mounting ASGI apps in `nautobot_config.py`:

```python
# In nautobot_config.py — mount MCP server ASGI app at plugin URL prefix:
# (This is the verified approach; the specific API depends on Nautobot version.
#  Fall back to Option B if ASGI mounting is unavailable.)
```

**Option B — Separate worker on different port (most reliable):**

```python
# Run as separate gunicorn worker:
# gunicorn nautobot_app_mcp_server.mcp.server:asgi_app --bind 0.0.0.0:9001
#
# Claude Code connects to port 9001 directly:
# {"mcpServers": {"nautobot": {"url": "http://nautobot:9001/mcp"}}}
```

**Auth:** Token extracted from `Authorization: Token nbapikey_xxx` header. Server attaches `request.user` to the FastMCP request context for use inside tool handlers.

**Session behavior:** FastMCP's `StreamableHTTPSessionManager` tracks session state keyed by `Mcp-Session-Id` header. Missing or invalid session ID → **automatically creates a new session** (never fails). All MCP-compliant clients send `Mcp-Session-Id` natively. Session storage is in-memory. Redis backend is a future swap-in.

**Scope hierarchy:**
```
core                          ← Core tools, always enabled
netnam_cms_core               ← App-level scope (parent)
├── netnam_cms_core.juniper  ← Exact scope
│   ├── netnam_cms_core.juniper.bgp
│   ├── netnam_cms_core.juniper.firewall
│   └── netnam_cms_core.juniper.interface
```

**Option B/C tools (session management):**
```python
@mcp.tool()
def mcp_enable_tools(scope: str | None = None, search: str | None = None):
    """Enable tool scopes or fuzzy-search matches for this session.
    Core tools are always enabled. Changes persist for this session only."""
    # scope="netnam_cms_core.juniper" → activates that exact scope + all children
    # scope="netnam_cms_core"         → activates all scopes under that app
    # search="BGP"                   → fuzzy match across all tool names/descriptions
    # No args → returns current session tool summary

@mcp.tool()
def mcp_disable_tools(scope: str | None = None):
    """Disable tool scopes for this session. scope=None → disable ALL non-core tools."""

@mcp.tool()
def mcp_list_tools(scope: str | None = None, search: str | None = None):
    """List all registered tools matching scope or search.
    Without args: returns tools currently active in this session."""
```

**Option C (no Option B):** SKILL.md teaches Claude all tool names. Any tool can be called by name from SKILL.md regardless of whether it is in the current session manifest. The registry is the source of truth for execution — the manifest only controls Claude's awareness. This means Claude can call `bgp_neighbor_list` directly if SKILL.md taught it about that tool, even if that scope is not enabled.

### 2. Tool Registry

**File:** `nautobot_app_mcp_server/mcp/registry.py`

```python
from dataclasses import dataclass
from typing import Any, Callable
import threading

@dataclass
class ToolDefinition:
    name: str
    func: Callable
    description: str
    input_schema: dict[str, Any]
    tier: str = "core"                    # "core" | "app"
    app_label: str | None = None          # Django app label, e.g. "netnam_cms_core"
    scope: str | None = None              # Explicit scope, e.g. "netnam_cms_core.juniper"
                                             # Required for app-tier tools so scope
                                             # matching doesn't rely on naming conventions

class MCPToolRegistry:
    _instance: "MCPToolRegistry | None" = None
    _lock = threading.Lock()
    _tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> "MCPToolRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_by_tier(self, tier: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if t.tier == tier]

    def get_core_tools(self) -> list[ToolDefinition]:
        return self.get_by_tier("core")

    def get_by_scope(self, scope: str) -> list[ToolDefinition]:
        """Return all tools matching an exact scope or a parent scope.

        scope="core"          → all core tools
        scope="netnam_cms_core" → all tools from that app (any sub-scope)
        scope="netnam_cms_core.juniper" → tools with that exact scope
        """
        if scope == "core":
            return self.get_core_tools()

        return [
            t for t in self._tools.values()
            if t.scope == scope
            or (t.scope is not None and t.scope.startswith(f"{scope}."))
        ]

    def fuzzy_search(self, term: str) -> list[ToolDefinition]:
        """Fuzzy match by name or description (case-insensitive)."""
        term = term.lower()
        return [
            t for t in self._tools.values()
            if term in t.name.lower() or term in t.description.lower()
        ]
```

**Singleton with thread lock** — safe for Django's multi-threaded worker model.
**Explicit `scope` on every `ToolDefinition`** — scope matching does not rely on tool name prefixes.

### 3. Tool Registration API

**File:** `nautobot_app_mcp_server/mcp/__init__.py`

```python
# Public API exposed to third-party Nautobot apps.
# Import path for third-party apps: from nautobot_app_mcp_server.mcp import register_mcp_tool
# (not from nautobot.apps — that package does not exist)

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

def register_mcp_tool(
    name: str,
    func: Callable,
    description: str,
    input_schema: dict,
    tier: str = "app",
    app_label: str | None = None,
    scope: str | None = None,
) -> None:
    """Register a tool with the MCP tool registry.

    Called by third-party Nautobot apps in their `ready()` hook, after
    the MCP server has registered its core tools (see Section 4).
    """
    registry = MCPToolRegistry.get_instance()
    registry.register(ToolDefinition(
        name=name,
        func=func,
        description=description,
        input_schema=input_schema,
        tier=tier,
        app_label=app_label,
        scope=scope,
    ))
```

**Usage by netnam_cms_core:**
```python
# netnam_cms_core/__init__.py
from nautobot_app_mcp_server.mcp import register_mcp_tool

def juniper_interface_unit_list(device_name: str, limit: int = 25, cursor: str | None = None):
    ...

register_mcp_tool(
    name="juniper_interface_unit_list",
    func=juniper_interface_unit_list,
    description="List Juniper interface units. Filter by device_name.",
    input_schema={
        "type": "object",
        "properties": {
            "device_name": {"type": "string"},
            "limit": {"type": "integer", "default": 25},
            "cursor": {"type": "string"},
        },
    },
    tier="app",
    app_label="netnam_cms_core",
    scope="netnam_cms_core.juniper",
)
```

### 4. NautobotAppConfig — Registration and MCPSessionState

**File:** `nautobot_app_mcp_server/__init__.py`

Registration uses `post_migrate` (not `ready()`). Django's `post_migrate` fires after all app migrations — which is after every `ready()` hook has completed. This guarantees the MCP server's core tools are registered before any third-party app calls `register_mcp_tool()` in its own `ready()` hook.

```python
class NautobotMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    base_url = "nautobot-app-mcp-server"

    def ready(self):
        # FastMCP ASGI app is lazily initialized on first HTTP request.
        # Not started here — avoids Django startup race conditions.
        pass

    def register_mcp_tools(self, **kwargs):
        # Called by post_migrate signal after ALL apps' ready() hooks complete.
        from .mcp.tools import core as core_tools
        from .mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry.get_instance()
        for tool in core_tools.get_core_tool_definitions():
            registry.register(tool)
```

**File:** `nautobot_app_mcp_server/mcp/session.py`

Per-conversation scope state, stored in FastMCP's session manager:

```python
from dataclasses import dataclass, field

@dataclass
class MCPSessionState:
    """Per-MCP-session (per-conversation) state. FastMCP stores one of these
    per Mcp-Session-Id. Core tools are always enabled regardless of state."""

    enabled_scopes: set[str] = field(default_factory=set)    # {"netnam_cms_core.juniper", "ipam.vlan"}
    enabled_searches: set[str] = field(default_factory=set)  # {"BGP"} — fuzzy matches active

    def enable_scope(self, scope: str) -> None:
        self.enabled_scopes.add(scope)

    def disable_scope(self, scope: str) -> None:
        self.enabled_scopes.discard(scope)

    def enable_search(self, term: str) -> None:
        self.enabled_searches.add(term.lower())

    def get_active_tools(self, registry: "MCPToolRegistry") -> list["ToolDefinition"]:
        """All tools visible in this session: core + scoped + searched."""
        from .registry import ToolDefinition
        tools: list[ToolDefinition] = []
        seen: set[str] = set()

        for t in registry.get_core_tools():
            seen.add(t.name)
            tools.append(t)

        for scope in self.enabled_scopes:
            for t in registry.get_by_scope(scope):
                if t.name not in seen:
                    seen.add(t.name)
                    tools.append(t)

        for term in self.enabled_searches:
            for t in registry.fuzzy_search(term):
                if t.name not in seen:
                    seen.add(t.name)
                    tools.append(t)

        return tools
```

**File:** `nautobot_app_mcp_server/mcp/apps.py`

Connect `register_mcp_tools` to `post_migrate` so it runs after all migrations and all `ready()` hooks:

```python
from nautobot.apps import NautobotAppConfig
from django.db.models.signals import post_migrate

class NautobotMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    base_url = "nautobot-app-mcp-server"

    def ready(self):
        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs):
        if app_config.name == "nautobot_app_mcp_server":
            # Only run once (when this app's migrations complete)
            # At this point all other apps' ready() hooks have already run,
            # so their register_mcp_tool() calls are already in the registry.
            app_config.register_mcp_tools()
```

### 5. Core Tools (Tier: Core, Always Visible)

**File:** `nautobot_app_mcp_server/mcp/tools/core.py`

All core tools are sync functions decorated with `@register_core_tool`. They are wrapped by the async FastMCP handler which calls them via `sync_to_async`.

**Core tools (always in manifest):**

| Tool | Description | Queryset |
|---|---|---|
| `device_list` | List devices (name, status, platform, location) | `Device.objects.select_related("status","platform","location").restrict(user)` |
| `device_get` | Get single device by name or pk | `Device.objects.select_related(...).prefetch_related("interfaces")` |
| `interface_list` | List interfaces, filtered by device | `Interface.objects.select_related("device","type").restrict(user)` |
| `interface_get` | Get single interface by pk | `Interface.objects.select_related(...).prefetch_related("ip_addresses")` |
| `ipaddress_list` | List IP addresses | `IPAddress.objects.select_related("tenant","vrf").restrict(user)` |
| `ipaddress_get` | Get single IP address | `IPAddress.objects.select_related(...).prefetch_related("interfaces")` |
| `prefix_list` | List prefixes | `Prefix.objects.select_related("vrf","tenant").restrict(user)` |
| `vlan_list` | List VLANs | `VLAN.objects.select_related("site","group").restrict(user)` |
| `location_list` | List locations | `Location.objects.select_related("location_type","parent").restrict(user)` |
| `search_by_name` | Global search by name across models | Custom multi-model query |

**Meta tools (always in manifest, needed for scope management):**

| Tool | Description |
|---|---|
| `mcp_enable_tools` | Enable tool scopes / fuzzy search for this session |
| `mcp_disable_tools` | Disable tool scopes for this session |
| `mcp_list_tools` | List all registered tools (all tiers, optionally filtered by scope) |

Note: meta tools are registered as `"core"` tier so they appear in the manifest always. Their scope management behavior is handled by session state, not by tier.

### 6. Pagination + Auto-Summarize

**File:** `nautobot_app_mcp_server/mcp/tools/pagination.py`

Key fix: count items **before** slicing to determine whether to summarize. Also fetch all items first to get an accurate count, then slice.

```python
from dataclasses import dataclass
from typing import Any
import base64

@dataclass
class PaginatedResult:
    items: list[dict[str, Any]]
    cursor: str | None       # Next page cursor (base64-encoded last PK)
    total_count: int | None  # Set only when result exceeds LIMIT_SUMMARIZE
    summary: dict | None      # Populated when result exceeds LIMIT_SUMMARIZE

LIMIT_DEFAULT = 25
LIMIT_MAX = 1000
LIMIT_SUMMARIZE = 100   # Summarize when result has > 100 items

def _encode_cursor(pk) -> str:
    return base64.b64encode(str(pk).encode()).decode()

def _decode_cursor(cursor: str) -> Any:
    return base64.b64decode(cursor).decode()

def paginate_queryset(qs, limit: int = LIMIT_DEFAULT, cursor: str | None = None) -> PaginatedResult:
    """Cursor-based pagination. limit is capped at LIMIT_MAX.

    Fix: count items BEFORE slicing so auto-summarize fires correctly.
    """
    limit = min(limit, LIMIT_MAX)

    qs = qs.order_by("pk")
    if cursor:
        last_pk = _decode_cursor(cursor)
        qs = qs.filter(pk__gt=last_pk)

    # Fetch one extra to detect next page (avoids extra DB round-trip)
    raw_items = list(qs[:limit + 1])
    has_next = len(raw_items) > limit
    items = raw_items[:limit]

    # Serialize BEFORE checking summary threshold
    serialized = [_serialize(i) for i in items]

    next_cursor = None
    summary = None
    total_count = None

    if has_next and items:
        next_cursor = _encode_cursor(items[-1].pk)

    # Auto-summarize when > LIMIT_SUMMARIZE items would have been returned
    if len(raw_items) > LIMIT_SUMMARIZE:
        # Count the full result set (not just the page)
        full_count = qs.count() if not cursor else len(raw_items)
        summary = {
            "total_count": full_count,
            "returned_count": len(items),
            "sample": serialized[:5],
            "note": f"{full_count} items exist. Use cursor pagination to page through results.",
        }
        # Still return items (capped at LIMIT_SUMMARIZE)
        serialized = serialized[:LIMIT_SUMMARIZE]

    return PaginatedResult(
        items=serialized,
        cursor=next_cursor,
        total_count=summary["total_count"] if summary else None,
        summary=summary,
    )
```

**Async bridge for tool execution** — all async tool handlers must call Django ORM via `sync_to_async` with `thread_sensitive=True`:

```python
# In each async tool:
from asgiref.sync import sync_to_async

@mcp.tool()
async def device_list(name: str | None = None, limit: int = 25, cursor: str | None = None):
    # thread_sensitive=True reuses Django's thread → safe for ORM connection pool
    _get_devices = sync_to_async(_sync_device_list, thread_sensitive=True)

    user = get_user_from_request(request_context.request)
    result = await _get_devices(name=name, limit=limit, cursor=cursor, user=user)
    return result

def _sync_device_list(name, limit, cursor, user):
    qs = Device.objects.select_related("status", "platform", "location")
    qs = qs.restrict(user=user, action="view")
    if name:
        qs = qs.filter(name__icontains=name)
    return paginate_queryset(qs, limit=limit, cursor=cursor)
```

### 7. /tools/list — Progressive Disclosure

The `list_tools()` MCP protocol handler returns tools **active in the current session**. It uses the `Mcp-Session-Id` header to look up `MCPSessionState` from the FastMCP session manager, then calls `session_state.get_active_tools(registry)`.

`mcp_enable_tools`, `mcp_disable_tools`, and `mcp_list_tools` are meta tools that **modify and query session state** respectively. They are **not listed in the Core tools table** — they are always available (always returned by `list_tools`) since they are needed to manage scope.

```python
from mcp.types import Tool
from mcp.server.context import RequestContext

@mcp.list_tools()
async def list_tools(ctx: RequestContext):
    """MCP protocol handler for tools/list.

    Returns tools active in this session:
    - Core tools (always)
    - Tools from enabled scopes
    - Tools matching enabled fuzzy searches
    """
    registry = MCPToolRegistry.get_instance()

    # Get or create session state for this Mcp-Session-Id
    session_id = ctx.session_id
    session_state = _get_or_create_session_state(session_id)

    active_tools = session_state.get_active_tools(registry)

    return [
        Tool(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
        )
        for t in active_tools
    ]

def _get_or_create_session_state(session_id: str) -> MCPSessionState:
    """Look up session state from FastMCP session manager, create if missing."""
    # FastMCP's session manager stores arbitrary state per session:
    #   session_manager.get_session_state(session_id, MCPSessionState)
    # If session is new, FastMCP auto-creates it; we initialize our state on first access.
    state = mcp.session_manager.get_session_state(session_id, MCPSessionState)
    if state is None:
        state = MCPSessionState()
        mcp.session_manager.set_session_state(session_id, state)
    return state
```

`mcp_enable_tools` / `mcp_disable_tools` modify `MCPSessionState` on the session manager, so subsequent calls to `list_tools` reflect the updated scope.

### 8. SKILL.md (Separate Package)

**File:** `nautobot-mcp-skill/SKILL.md`

```yaml
---
name: Nautobot
description: Network infrastructure management via Nautobot MCP server.
---

# Nautobot MCP Skill

This skill provides access to Nautobot's network inventory system.
Agents access Nautobot via the MCP server — see your MCP configuration
for the connection URL.

## Authentication

Set your Nautobot API token in the MCP server config:
`Authorization: Token nbapikey_xxxxxxx`

## Core Tools (Always Available — 10 tools)

| Tool | When to Use |
|------|-------------|
| `device_list` | Inventory of all devices. Always start here. |
| `device_get` | Full details of a specific device by name or ID. |
| `interface_list` | All interfaces on a device. Filter by `device_name`. |
| `interface_get` | Interface details including IP addresses, VLANs. |
| `ipaddress_list` | IP address inventory. Filter by address, tenant. |
| `ipaddress_get` | Get IP address details including assigned interfaces. |
| `prefix_list` | IP prefix space. Filter by VRF, location. |
| `vlan_list` | VLAN inventory. Filter by site, group. |
| `location_list` | Locations (sites, buildings, racks). Filter by name, type. |
| `search_by_name` | Find any object by name across all models. |

## Scope Management (Enable App-Specific Tools)

Nautobot apps (e.g. netnam_cms_core) register additional tools. To enable them:

| Action | Tool |
|--------|------|
| Enable Juniper tools | `mcp_enable_tools(scope="netnam_cms_core")` |
| Enable only BGP tools | `mcp_enable_tools(scope="netnam_cms_core.juniper.bgp")` |
| Search all tools | `mcp_enable_tools(search="BGP")` |
| List all available tools | `mcp_list_tools()` |
| Disable a scope | `mcp_disable_tools(scope="netnam_cms_core.juniper.bgp")` |

## Pagination

All list tools accept:
- `limit` (default: 25, max: 1000) — items per page
- `cursor` — opaque string for the next page

## Workflows

### Investigate a Device
1. `device_get(name="core-rtr-01")` — get device overview
2. `interface_list(device_name="core-rtr-01")` — list interfaces
3. `ipaddress_list()` — find IPs on this device

### Find a Device by Name
1. `search_by_name(name="core-rtr")` — searches across all models
2. `device_get(pk="...")` — get full details

### Explore Juniper BGP (netnam_cms_core)
1. `mcp_enable_tools(scope="netnam_cms_core.juniper.bgp")`
2. `bgp_neighbor_list(device_name="core-rtr-01")`

## Performance Rules
- Never call `device_list()` without `limit` or a name filter
- Always use `device_name` filter on `interface_list`
- For bulk operations, request one page at a time
- Use `mcp_disable_tools()` when done with a domain to keep the manifest lean
```

---

## Critical Files to Modify/Create

| Action | File |
|---|---|
| CREATE | `nautobot-app-mcp-server/pyproject.toml` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/__init__.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/apps.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/urls.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/__init__.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/server.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/registry.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/session.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/auth.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/tools/__init__.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/tools/core.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/tools/pagination.py` |
| CREATE | `nautobot-app-mcp-server/nautobot_app_mcp_server/mcp/tools/query_utils.py` |
| CREATE | `nautobot-mcp-skill/pyproject.toml` |
| CREATE | `nautobot-mcp-skill/SKILL.md` |
| CREATE | `nautobot-mcp-skill/reference/*.md` |
| MODIFY | `netnam_cms_core/__init__.py` — add `from nautobot_app_mcp_server.mcp import register_mcp_tool` call |

**Removed:** `signals.py` — replaced by `apps.py` (`post_migrate` signal handler) + `session.py` (`MCPSessionState`).

**Reuse from existing code:**
- `nautobot_app_mcp_server/mcp/tools/query_utils.py` reuses `for_list_view()` / `for_detail_view()` patterns from `netnam-cms-core/netnam_cms_core/models/querysets.py`
- Pagination approach mirrors `NautobotModelViewSet.get_queryset()` action-based queryset splitting

---

## Verification

1. **Install the app:** Add `nautobot_app_mcp_server` to `PLUGINS` in `nautobot_config.py`, run migrations
2. **MCP endpoint reachable:** `curl http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` → returns MCP JSON-RPC response (not 404)
3. **List tools:** MCP `POST /tools/list` with session → returns 13 tools (10 core + 3 meta)
4. **Call a tool:** `POST /tools/call` with `device_list(limit=5)` → returns 5 devices, cursor present
5. **Scope enable:** `mcp_enable_tools(scope="netnam_cms_core")` → returns summary showing scope activated
6. **List scoped tools:** `mcp_list_tools()` → returns all tools including Juniper (after scope enabled)
7. **Register third-party:** Install `netnam_cms_core` → its tools appear in `mcp_list_tools()`
8. **Claude Code (Option B):** `claude mcp add nautobot-app-mcp-server http://localhost:9001/mcp`
9. **Skill install:** `claude skill add /path/to/nautobot-mcp-skill`
10. **Large query test:** `device_list(limit=1000)` → verifies cursor pagination works, memory bounded
11. **Auto-summarize:** `device_list(limit=1000)` on a >100-device result → summary dict returned with sample
12. **Auth test:** Request without `Authorization` header → returns empty list (not error)
13. **Auth valid token:** Request with valid `Authorization: Token nbapikey_xxx` → returns real data
14. **Run tests:** `pytest nautobot-app-mcp-server/tests/`

---

### 9. Authentication

**File:** `nautobot_app_mcp_server/mcp/auth.py`

Each tool enforces Nautobot permissions via `.restrict(user, action)`. Auth is via Nautobot API token sent in the `Authorization: Token nbapikey_xxx` header on every request.

```python
def get_user_from_request(request) -> User | AnonymousUser:
    """Extract Nautobot user from Authorization header or session."""
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Token "):
        token_key = auth_header[6:]
        try:
            token = Token.objects.select_related("user").get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            return AnonymousUser()

    if hasattr(request, "user") and request.user.is_authenticated:
        return request.user

    return AnonymousUser()
```

**In each tool:**
```python
@mcp.tool()
async def device_list(name: str | None = None, limit: int = 25, cursor: str | None = None):
    user = get_user_from_request(request_context.request)
    # AnonymousUser → .restrict() returns empty queryset
    qs = Device.objects.select_related("status", "platform", "location")
    qs = qs.restrict(user=user, action="view")   # Enforces Nautobot permissions
```

**Claude Code MCP config:**
```json
{
  "mcpServers": {
    "nautobot": {
      "command": "uvicorn",
      "args": ["nautobot_app_mcp_server.mcp.server:app", "--host", "0.0.0.0", "--port", "9001"],
      "env": {
        "NAUTOBOT_MCP_SERVER__TOKEN": "nbapikey_xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

**Recommended:** Create a dedicated Nautobot user for the MCP agent with appropriate read permissions. Anonymous/unauthenticated requests return empty results — no error, no exposure.

---

## Out of Scope for V1

- Write tools (create/update/delete) — deferred to v2
- Streaming (SSE rows) — cursor pagination handles memory; streaming as future enhancement
- Tool-level permissions (field-level hide/show per user role)
- MCP `resources` or `prompts` endpoints — focus is tools first
