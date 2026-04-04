# Design: MCP Server Patterns Adopted from gt732/nautobot-app-mcp

**Date:** 2026-04-04
**Status:** Draft
**Author:** Claude (brainstorming with project owner)

## Context

The project `nautobot-app-mcp-server` uses an embedded FastMCP server running inside Nautobot's Django process, communicating over StreamableHTTP. The reference implementation `gt732/nautobot-app-mcp` (archived, Nautobot 2.x) takes a standalone-process approach but offers patterns worth adopting:

1. **Tool introspection and DB tracking** via an `MCPTool` Django model
2. **Per-tool `@sync_to_async` wrapping** (pattern already present; confirmed sufficient)
3. **Custom tools directory discovery** via `discover_tools_from_directory()`
4. **Management command runner** for standalone MCP server startup

This design is a **targeted enhancement** — the existing embedded architecture is retained.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Nautobot Django Process                      │
│                                                                  │
│  ┌──────────────┐   ┌─────────────────────┐                      │
│  │ FastMCP app  │◄──│  MCPToolRegistry    │ (in-memory, singleton│
│  │ (ASGI bridge)│   │  + tool definitions │  — runtime truth)   │
│  └──────┬───────┘   └──────────┬──────────┘                      │
│         │                       │                                 │
│         │              ┌────────▼────────┐                       │
│         │              │  MCPToolIndex     │ (Django model —       │
│         │              │  (Django ORM)     │  admin UI + stale    │
│         │              └────────┬────────┘  detection only)      │
│         │                       │                                 │
│  ┌──────▼───────────────────────▼───────┐                       │
│  │  Management Commands                   │                       │
│  │  • start_mcp_server  (SSE transport)  │                       │
│  │  • sync_tool_registry (post_migrate)   │                       │
│  └───────────────────────────────────────┘                       │
│                                                                  │
│  ┌──────────────────────────────────────┐                       │
│  │ Custom tools directory (optional)      │                       │
│  │ MCP_CUSTOM_TOOLS_DIR → discover_tools  │                       │
│  └──────────────────────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

**Key invariant:** The `MCPToolRegistry` singleton is the runtime source of truth. `MCPToolIndex` is derived from it — populated at startup and by `sync_tool_registry`, never mutated at runtime by the MCP server.

---

## Components

### 1. `mcp/models.py` — MCPToolIndex Django Model

```python
"""Django models for MCP tool registry admin support."""

from django.db import models
from nautobot.core.models import BaseModel


class MCPToolIndex(BaseModel):
    """Read-only administrative index of MCP tools.

    Populated from MCPToolRegistry at startup and by sync_tool_registry.
    NOT the runtime source of truth — MCPToolRegistry is.
    """

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    module_path = models.CharField(max_length=255, blank=True)
    parameters = models.JSONField(blank=True, null=True)
    tier = models.CharField(max_length=32, default="app")
    app_label = models.CharField(max_length=128, blank=True, null=True)
    scope = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "MCP Tool"
        verbose_name_plural = "MCP Tools"

    def __str__(self) -> str:
        return self.name
```

**Permissions:** `nautobot_app_mcp_server.view_mcptoolindex` — matches Nautobot convention for read-only models.

**Why this model exists:** Enables the Nautobot admin UI to list all registered tools, show their parameters, and detect tools that were registered in a previous run but are now missing (stale tools from removed modules).

---

### 2. `mcp/management/commands/sync_tool_registry.py`

Populates `MCPToolIndex` from the current `MCPToolRegistry`. Called by the `post_migrate` signal in `__init__.py`.

```python
"""Management command to sync MCPToolRegistry into MCPToolIndex DB rows."""

from django.core.management.base import BaseCommand
from nautobot_app_mcp_server.mcp.models import MCPToolIndex
from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry


class Command(BaseCommand):
    help = "Sync current MCPToolRegistry state into MCPToolIndex database rows."

    def handle(self, *args, **options):
        registry = MCPToolRegistry.get_instance()
        seen_names: set[str] = set()

        for tool in registry.get_all():
            MCPToolIndex.objects.update_or_create(
                name=tool.name,
                defaults={
                    "description": tool.description,
                    "module_path": getattr(tool.func, "__module__", ""),
                    "parameters": tool.input_schema,
                    "tier": tool.tier,
                    "app_label": tool.app_label,
                    "scope": tool.scope,
                },
            )
            seen_names.add(tool.name)

        # Remove stale rows (tools that no longer exist)
        stale = MCPToolIndex.objects.exclude(name__in=seen_names)
        count, _ = stale.delete()
        if count:
            self.stdout.write(f"Removed {count} stale tool row(s).")
```

Called from `nautobot_app_mcp_server/__init__.py`:

```python
# In NautobotAppMcpServerConfig.ready()
from django.db.models.signals import post_migrate

def sync_registry_on_migrate(*, apps, **kwargs):
    # Use apps.get_model to support Django migrations
    ...

post_migrate.connect(sync_registry_on_migrate, sender=__name__)
```

**Alternative (simpler):** Call `sync_tool_registry` directly from `post_migrate` signal in `__init__.py` without a separate management command, since the registry is already populated by the time `ready()` runs.

---

### 3. `mcp/management/commands/start_mcp_server.py`

Starts the embedded FastMCP server in SSE transport mode, useful for:
- Local development with external MCP clients (e.g., Claude Desktop)
- Standalone deployment where the MCP server runs separately from Nautobot's web UI

```python
"""Management command to run the MCP server in standalone SSE mode."""

from django.core.management.base import BaseCommand
from django.conf import settings
from nautobot_app_mcp_server.mcp.server import _setup_mcp_app


class Command(BaseCommand):
    help = "Start the MCP server in SSE transport mode."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default=settings.PLUGINS_CONFIG.get("nautobot_app_mcp_server", {}).get(
                "MCP_HOST", "127.0.0.1"
            ),
            help="Host to bind to (default: 127.0.0.1)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=settings.PLUGINS_CONFIG.get("nautobot_app_mcp_server", {}).get(
                "MCP_PORT", 8050
            ),
            help="Port to bind to (default: 8050)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        self.stdout.write(f"Starting MCP server on http://{host}:{port}")
        mcp = _setup_mcp_app()
        mcp.run(transport="sse", host=host, port=port)
```

**Configuration** (`nautobot_config.py`):

```python
PLUGINS_CONFIG = {
    "nautobot_app_mcp_server": {
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": 8050,
        "MCP_CUSTOM_TOOLS_DIR": "/opt/nautobot/custom_mcp_tools",
    },
}
```

---

### 4. `mcp/registry.py` — Add `discover_tools_from_directory()`

Extends the existing registry with directory-based tool discovery, matching gt732's pattern but using the existing `register_mcp_tool()` API.

```python
def discover_tools_from_directory(tools_dir: str) -> int:
    """Discover and register MCP tools from a Python package directory.

    Looks for modules in ``tools_dir`` and registers any function decorated
    with ``@register_mcp_tool`` found in those modules.

    Args:
        tools_dir: Absolute path to a directory containing Python modules.

    Returns:
        Number of functions registered.

    Raises:
        OSError: If tools_dir does not exist or is not a directory.
    """
    tools_path = Path(tools_dir)

    if not tools_path.exists() or not tools_path.is_dir():
        raise OSError(f"Tools directory does not exist or is not a directory: {tools_dir}")

    parent_dir = str(tools_path.parent)
    tools_dir_name = tools_path.name

    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    discovered = 0
    try:
        for _, module_name, is_pkg in pkgutil.iter_modules([str(tools_path)]):
            if is_pkg:
                continue
            try:
                module = importlib.import_module(f"{tools_dir_name}.{module_name}")
                # Functions decorated with @register_mcp_tool are already
                # registered at import time; this just triggers that side effect.
                discovered += 1
            except Exception as e:
                logger.warning(f"Error loading custom tool module {module_name}: {e}")
        return discovered
    finally:
        if parent_dir in sys.path:
            sys.path.remove(parent_dir)
```

**Called from `__init__.py`:**

```python
# In NautobotAppMcpServerConfig.ready()
custom_tools_dir = settings.PLUGINS_CONFIG.get(
    "nautobot_app_mcp_server", {}
).get("MCP_CUSTOM_TOOLS_DIR")
if custom_tools_dir:
    discover_tools_from_directory(custom_tools_dir)
```

---

### 5. `mcp/tools/admin.py` — Nautobot Admin UI View

A read-only view listing all tools from `MCPToolIndex` with server status.

```python
"""Nautobot UI view listing all registered MCP tools."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.shortcuts import render
from django.conf import settings
from nautobot_app_mcp_server.mcp.models import MCPToolIndex

PLUGIN_SETTINGS = settings.PLUGINS_CONFIG.get("nautobot_app_mcp_server", {})
HOST = PLUGIN_SETTINGS.get("MCP_HOST", "127.0.0.1")
PORT = PLUGIN_SETTINGS.get("MCP_PORT", 8050)


class MCPToolsView(LoginRequiredMixin, View):
    """Admin view for MCP tools."""

    def _check_server_status(self) -> tuple[bool, str | None]:
        import requests
        server_url = f"http://{HOST}:{PORT}/sse"
        try:
            response = requests.get(server_url, timeout=1)
            response.close()
            return response.status_code == 200, None
        except requests.exceptions.ConnectionError:
            return False, f"Cannot connect to MCP server at {HOST}:{PORT}"
        except requests.exceptions.Timeout:
            return False, f"Connection to MCP server at {HOST}:{PORT} timed out"
        except Exception as e:
            return False, f"Error: {e}"

    def get(self, request):
        tools = MCPToolIndex.objects.all().order_by("tier", "name")

        is_running, error = self._check_server_status()

        tools_list = []
        for tool in tools:
            tools_list.append({
                "name": tool.name,
                "description": tool.description or "—",
                "module_path": tool.module_path,
                "tier": tool.tier,
                "scope": tool.scope,
            })

        context = {
            "tools": tools_list,
            "server_status": {
                "running": is_running,
                "error": error or ("MCP server is not running" if not is_running else None),
                "host": HOST,
                "port": PORT,
            },
        }
        return render(request, "nautobot_app_mcp_server/mcp_tools.html", context)
```

**Template:** `templates/nautobot_app_mcp_server/mcp_tools.html`

**URL:** `mcp/tools/` registered in `mcp/urls.py` under `mcp/` prefix.

**Navigation:** Add to Nautobot UI via `nautobot_app_mcp_server/navigation.py` — same pattern as gt732's `navigation.py`.

---

### 6. `urls.py` — Merge admin view into existing MCP endpoint file

The existing `urls.py` already mounts `/mcp/` for the MCP endpoint. Add the admin view at `/mcp/tools/` by extending the existing `urlpatterns` in `nautobot_app_mcp_server/urls.py`:

```python
"""Django URL routing for the MCP server endpoint and admin UI."""

from django.urls import path

from nautobot_app_mcp_server.mcp.view import mcp_view
from nautobot_app_mcp_server.mcp.tools.admin import MCPToolsView

urlpatterns = [
    path("mcp/", mcp_view, name="mcp"),
    path("mcp/tools/", MCPToolsView.as_view(), name="mcp-tools"),
]
```

---

## Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `MCP_HOST` | `str` | `"127.0.0.1"` | Host for SSE transport in `start_mcp_server` |
| `MCP_PORT` | `int` | `8050` | Port for SSE transport |
| `MCP_CUSTOM_TOOLS_DIR` | `str` | `None` | Optional path to custom tools directory |

---

## Data Flow: Tool Registration

```
1. nautobot-app-mcp-server loads
   └─ __init__.py → ready() → imports mcp/tools/__init__.py
       └─ imports mcp/tools/core.py → @register_mcp_tool calls populate registry

2. Third-party app loads (e.g. netnam_cms_core)
   └─ ready() → register_mcp_tool(...) → MCPToolRegistry.register()

3. post_migrate signal fires (after all migrations)
   └─ sync_tool_registry() → MCPToolIndex.objects.update_or_create()

4. User visits /mcp/tools/ (admin UI)
   └─ MCPToolsView → MCPToolIndex.objects.all() → rendered template

5. MCP client connects via StreamableHTTP
   └─ _list_tools_handler() → MCPToolRegistry.get_core_tools() + scopes
```

---

## Testing

| Test | File | Coverage |
|---|---|---|
| `MCPToolIndex` model CRUD | `mcp/tests/test_models.py` | `name`, `parameters` JSONField, `tier` |
| `discover_tools_from_directory()` — valid dir | `mcp/tests/test_registry.py` | registers tools, handles errors |
| `discover_tools_from_directory()` — invalid dir | `mcp/tests/test_registry.py` | raises `OSError` |
| `sync_tool_registry` command | `mcp/tests/test_sync_command.py` | `update_or_create`, stale deletion |
| `start_mcp_server` command | `mcp/tests/test_start_command.py` | server starts on configured host/port |
| `MCPToolsView` GET | `mcp/tests/test_admin_view.py` | renders tool list + status |
| `MCPToolsView` server down | `mcp/tests/test_admin_view.py` | shows error state gracefully |

---

## Files to Create/Modify

| File | Action |
|---|---|
| `nautobot_app_mcp_server/mcp/models.py` | **Create** — `MCPToolIndex` model |
| `nautobot_app_mcp_server/mcp/management/commands/sync_tool_registry.py` | **Create** — populate DB from registry |
| `nautobot_app_mcp_server/mcp/management/commands/start_mcp_server.py` | **Create** — SSE standalone server |
| `nautobot_app_mcp_server/mcp/registry.py` | **Modify** — add `discover_tools_from_directory()` |
| `nautobot_app_mcp_server/mcp/tools/admin.py` | **Create** — `MCPToolsView` |
| `nautobot_app_mcp_server/urls.py` | **Modify** — add `MCPToolsView` to existing `urlpatterns` |
| `nautobot_app_mcp_server/mcp/navigation.py` | **Create** — Nautobot nav menu item |
| `nautobot_app_mcp_server/__init__.py` | **Modify** — call `discover_tools_from_directory()`, wire `post_migrate` |
| `nautobot_app_mcp_server/urls.py` | **Modify** — include MCP URLs under `mcp/` |
| `templates/nautobot_app_mcp_server/mcp_tools.html` | **Create** — tool listing template |

---

## Open Questions

- [ ] **Systemd vs Docker**: gt732 documents a systemd service for production. Should `start_mcp_server` be docker-aware (check `NAUTOBOT_DOCKER` env var), or is Docker Compose the only supported deployment?
- [ ] **Permission level**: Should `MCPToolIndex` have only `view` permission, or also `add`/`change`/`delete`? Given it's derived from the registry, `view`-only is most appropriate.
- [ ] **gt732's `MCPTool` model tracks only registered tools** (not the MCP server process). The admin view currently checks server status by hitting `/sse`. Should it also add a `status` field to `MCPToolIndex` updated by the MCP server process itself?
