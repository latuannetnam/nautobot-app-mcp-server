# Extending the App

!!! warning
    Extending the application is welcome, however it is best to open an issue first, to ensure that a PR would be accepted and makes sense in terms of features and design.

This app exposes a **plugin API** (`register_mcp_tool()` / `@register_tool()`) that any Nautobot app can use to contribute its own MCP tools. Third-party tools become available to AI agents once the session scope is enabled via `mcp_enable_tools`.

## Overview

Third-party tools are registered **during Django app bootstrap**, not at module import time. The correct pattern is:

1. Define the async tool function in a **separate module** (e.g. `mcp_tools/juniper_routing.py`).
2. Import and call `register_mcp_tool()` (or use `@register_tool()`) **at module scope** in that module — the decorator fires immediately when Python evaluates the import.
3. In your app's `ready()` hook, import that module by name — this fires the registration side-effects.
4. The MCP server (loaded before your app) already has `MCPToolRegistry` alive, so registration succeeds.

Key constraint: **Never import Django models at module scope** in tool modules. Use lazy imports (`from django.db import models` inside functions) to avoid bootstrap ordering failures.

## The Two Registration Options

### Option 1 — `register_mcp_tool()` (explicit schema)

Call `register_mcp_tool()` directly with a pre-built JSON Schema:

```python
# my_nautobot_app/mcp_tools/juniper_routing.py
from nautobot_app_mcp_server.mcp import register_mcp_tool
from nautobot_app_mcp_server.mcp.schema import func_signature_to_input_schema


def juniper_static_route_list(device_name: str | None = None, limit: int = 25) -> dict:
    """List Juniper static routes."""
    # ... implementation ...


# Register at module scope — fires on every import of this module
register_mcp_tool(
    name="juniper_static_route_list",
    func=juniper_static_route_list,
    description="List Juniper static routes for a device.",
    input_schema=func_signature_to_input_schema(juniper_static_route_list),
    tier="app",
    app_label="my_nautobot_app",
    scope="my_nautobot_app.juniper",
)
```

### Option 2 — `@register_tool()` (recommended, auto-generated schema)

The decorator derives the `input_schema` automatically from the function's Python type annotations. This is the preferred pattern used by all core tools:

```python
# my_nautobot_app/mcp_tools/juniper_routing.py
from fastmcp.server.context import Context as ToolContext
from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from asgiref.sync import sync_to_async


@register_tool(
    description="List Juniper static routes for a device.",
    tier="app",
    scope="my_nautobot_app.juniper",
)
async def juniper_static_route_list(
    ctx: ToolContext,
    device_name: str | None = None,
    limit: int = 25,
) -> dict:
    user = await get_user_from_request(ctx)
    return await sync_to_async(_sync_list, thread_sensitive=True)(user=user, device_name=device_name, limit=limit)


# Decorator fires immediately → register_mcp_tool() is called at module scope
```

### Which option to use?

|   | `register_mcp_tool()` | `@register_tool()` |
| --- | ---------------------- | --------------------- |
| Schema | Manual JSON Schema dict | Auto-derived from type hints |
| Imports | `func_signature_to_input_schema` needed | No schema imports needed |
| Best for | Complex schemas, override specific params | Standard parameter lists |
| Used by | Core tools (legacy), library-level helpers | All core tools in `core.py` |

## Parameters Reference

`register_mcp_tool()` and `@register_tool()` accept these parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes (for `register_mcp_tool`) | Unique tool name (e.g. `"device_list"`). |
| `func` | `Callable` | Yes (for `register_mcp_tool`) | The callable tool function. |
| `description` | `str` | Yes | Human-readable description for the MCP manifest. |
| `input_schema` | `dict[str, Any]` | Yes (for `register_mcp_tool`) | JSON Schema for tool input. |
| `tier` | `str` | No | `"core"` (always visible) or `"app"` (progressive, default). |
| `app_label` | `str \| None` | No | Django app label. Required for app-tier tools. |
| `scope` | `str \| None` | No | Dot-separated scope string (e.g. `"my_app.juniper"`). |
| `output_schema` | `dict \| None` | No | JSON Schema for output. Defaults to `{"type": "object"}`. |

## Tier System

Tools are classified into two tiers:

| Tier | Visibility | Registration |
|------|------------|--------------|
| `"core"` | Always in the MCP manifest | Used by the MCP server itself for built-in tools |
| `"app"` | Visible only after `mcp_enable_tools` is called for their scope | Used by third-party Nautobot apps |

## Scope Hierarchy

Scopes are **dot-separated strings** that form a hierarchy:

```
my_nautobot_app           ← enabling this activates everything below
  └── my_nautobot_app.juniper
  └── my_nautobot_app.cisco
```

When an AI agent calls `mcp_enable_tools(scope="my_nautobot_app")`, the MCP server uses `MCPToolRegistry.get_by_scope()` to find all tools whose scope is exactly `"my_nautobot_app"` **or** starts with `"my_nautobot_app."`. Enabling the parent scope automatically activates all child tools.

Disabling (`mcp_disable_tools(scope="my_nautobot_app")`) removes the parent and all children in one call.

## Cross-Process Discovery

The MCP server's `MCPToolRegistry` is an in-process singleton — it starts empty and is populated as each Nautobot app is imported at Django startup. Third-party apps call `register_mcp_tool()` in their tool modules, and those calls execute when Django imports the app's `__init__.py` (which itself imports the tool modules).

`tool_registry.json` is **automatically generated** — you never edit it by hand. `NautobotAppMcpServerConfig.ready()` (the MCP server app, placed last in `INSTALLED_APPS`) dumps the full `MCPToolRegistry` contents to `tool_registry.json` after all third-party apps have already registered. The standalone MCP server reads this file at startup for cross-process discovery.

The registration sequence is:

1. Nautobot Django starts.
2. `nautobot_app_mcp_server` is imported — `MCPToolRegistry` singleton is created (empty).
3. Core tools in `nautobot_app_mcp_server.mcp.tools.core` are registered.
4. Other Nautobot apps (`INSTALLED_APPS`) are imported — each calls `@register_tool()` or `register_mcp_tool()` in their tool modules.
5. `nautobot_app_mcp_server.ready()` fires (last in `INSTALLED_APPS`) — dumps `MCPToolRegistry` to `tool_registry.json`.
6. FastMCP server starts and calls `register_all_tools_with_mcp(mcp)`, wiring every registered tool to the live FastMCP instance.
7. MCP server begins accepting connections on port 8005.

## Complete Working Example

This example shows the **recommended pattern** (`@register_tool()` + async wrapper + sync implementation), which is what `netnam_cms_core` uses for its `juniper_static_route_list` and `juniper_static_route_get` tools.

### `my_nautobot_app/__init__.py`

```python
"""my_nautobot_app/__init__.py — Nautobot app declaration."""

from nautobot.apps import NautobotAppConfig


class MyNautobotAppConfig(NautobotAppConfig):
    name = "my_nautobot_app"
    description = "Example Nautobot app with MCP tools"

    def ready(self):
        # Import the module by name — this fires @register_tool() at module scope
        # and registers the tools with MCPToolRegistry.
        from my_nautobot_app.mcp_tools import juniper_routing  # noqa: F401


config = MyNautobotAppConfig
```

!!! warning
    The `ready()` import must name the **specific module file** (e.g. `juniper_routing`), not the package (`mcp_tools`). Importing the package triggers `__init__.py` which has no registration side-effects.

### `my_nautobot_app/mcp_tools/juniper_routing.py`

```python
"""my_nautobot_app/mcp_tools/juniper_routing.py — MCP tool definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext
from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request

if TYPE_CHECKING:
    from django.db.models import QuerySet


# ---------------------------------------------------------------------------
# Sync implementation (called via sync_to_async)
# ---------------------------------------------------------------------------


_STANDARD_EXCLUDE = [
    "created",
    "last_updated",
    "custom_field_data",
    "computed_fields",
    "comments",
]


def build_route_qs(user, device_name: str | None = None) -> "QuerySet":
    """Build a restricted QuerySet for JuniperStaticRoute.

    Uses lazy import to avoid Django bootstrap ordering issues.
    """
    # Lazy import — required to avoid importing Django models before bootstrap
    from my_nautobot_app.models import JuniperStaticRoute  # noqa: F811

    qs: QuerySet = JuniperStaticRoute.objects.select_related(
        "device",
        "destination",
        "routing_instance",
    )
    if device_name:
        qs = qs.filter(device__name=device_name)
    return qs.restrict(user, "view")


def serialize_route(route) -> dict[str, Any]:
    """Serialize a route for the MCP list response (counts only)."""
    from django.forms.models import model_to_dict

    data = model_to_dict(route, exclude=_STANDARD_EXCLUDE)
    data["pk"] = str(route.pk)
    data["device"] = {"name": route.device.name, "pk": str(route.device.pk)}
    data["destination"] = str(route.destination.network)
    return data


# ---------------------------------------------------------------------------
# Async MCP tool handlers (decorated with @register_tool)
# ---------------------------------------------------------------------------


@register_tool(
    description="List Juniper static routes, optionally filtered by device.",
    tier="app",
    scope="my_nautobot_app.juniper",
)
async def juniper_static_route_list(
    ctx: ToolContext,
    device_name: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """List Juniper static routes with pagination.

    Args:
        ctx: FastMCP tool context (provides request).
        device_name: Filter by device name.
        limit: Maximum items per page (default 25, max 1000).

    Returns:
        dict with items, cursor, total_count, and summary fields.
    """
    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    user = await get_user_from_request(ctx)
    qs = await sync_to_async(build_route_qs, thread_sensitive=True)(
        user=user, device_name=device_name
    )
    result = await sync_to_async(paginate_queryset, thread_sensitive=True)(qs, limit)
    items = await sync_to_async(
        lambda qs: [serialize_route(r) for r in qs], thread_sensitive=True
    )(result.items)

    return {
        "items": items,
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }
```

`@register_tool()` fires **at module scope** — as soon as Python evaluates the import of `juniper_routing`, the decorator calls `register_mcp_tool()` and the tool is registered in `MCPToolRegistry`.

### `my_nautobot_app/models.py` (schema reference)

```python
"""my_nautobot_app/models.py — domain models."""

from nautobot.core.models.generics import PrimaryModel
from nautobot.dcim.models import Device
from nautobot.ipam.models import Prefix


class JuniperStaticRoute(PrimaryModel):
    """Static route on a Juniper device."""

    device = models.ForeignKey(
        Device, on_delete=models.CASCADE, related_name="juniper_static_routes"
    )
    destination = models.ForeignKey(
        Prefix, on_delete=models.CASCADE, related_name="juniper_static_routes"
    )
    routing_instance = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="static_routes",
    )
    routing_table = models.CharField(max_length=50, default="inet.0")
    preference = models.IntegerField(default=5)
    metric = models.IntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["destination__network"]
```

## Enabling Tools in an MCP Session

Once the app is installed in `PLUGINS` and Nautobot is restarted, the tools are registered but **hidden** (app tier). An AI agent must enable the scope first:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "mcp_enable_tools",
    "arguments": { "scope": "my_nautobot_app.juniper" }
  },
  "id": 1
}
```

Then the tools appear in `tools/list` and can be called:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "juniper_static_route_list",
    "arguments": { "device_name": "router-01", "limit": 10 }
  },
  "id": 2
}
```

Or enable all scopes for the app at once:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "mcp_enable_tools",
    "arguments": { "scope": "my_nautobot_app" }
  },
  "id": 3
}
```

## Common Pitfalls

### Wrong: importing the package instead of the module

```python
# WRONG — imports my_nautobot_app/mcp_tools/__init__.py (no side-effects)
def ready(self):
    import my_nautobot_app.mcp_tools  # noqa: F401

# CORRECT — imports the specific module, fires @register_tool() at module scope
def ready(self):
    from my_nautobot_app.mcp_tools import juniper_routing  # noqa: F401
```

The package `__init__.py` has no `@register_tool()` calls — only the **specific module files** do. Importing the package only evaluates `__init__.py`.

### Wrong: importing Django models at module scope

```python
# WRONG — fires when Django is not yet bootstrapped
from my_nautobot_app.models import JuniperStaticRoute  # noqa: F401

def build_route_qs(user):
    ...

# CORRECT — lazy import inside the function
def build_route_qs(user):
    from my_nautobot_app.models import JuniperStaticRoute  # noqa: F811
    ...
```

### Wrong: calling `list()` synchronously in an async handler

```python
# WRONG — raises "cannot call from async context"
async def juniper_static_route_get(...):
    qs_filtered = qs.filter(destination__network=destination_prefix)
    routes = list(qs_filtered)  # sync call inside async!

# CORRECT — wrap in sync_to_async with thread_sensitive=True
async def juniper_static_route_get(...):
    qs_filtered = qs.filter(destination__network=destination_prefix)
    routes = await sync_to_async(lambda qs: list(qs), thread_sensitive=True)(qs_filtered)
```

The `thread_sensitive=True` flag is required so Django ORM queries are routed to the correct database connection thread.
