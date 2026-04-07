# Extending the App

!!! warning
    Extending the application is welcome, however it is best to open an issue first, to ensure that a PR would be accepted and makes sense in terms of features and design.

This app exposes a **plugin API** (`register_mcp_tool()`) that any other Nautobot app can use to contribute its own MCP tools. When a third-party tool is registered, AI agents can enable it for their session using the `mcp_enable_tools` session tool.

## Registering a Tool

### Option 1 — `register_mcp_tool()` (explicit schema)

Call `register_mcp_tool()` directly from your Nautobot app's `__init__.py` or a module imported at startup:

```python
# my_nautobot_app/__init__.py
from nautobot_app_mcp_server.mcp import register_mcp_tool


def get_juniper_bgp_neighbors(name: str, limit: int = 25) -> dict:
    """List BGP neighbors on a Juniper device by device name."""
    # Your implementation here — query Nautobot ORM, return a dict
    ...


register_mcp_tool(
    name="juniper_bgp_neighbor_list",
    func=get_juniper_bgp_neighbors,
    description="List BGP neighbors on a Juniper device by device name.",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Device name"},
            "limit": {"type": "integer", "default": 25, "description": "Max results"},
        },
    },
    tier="app",                        # "app" tier → progressive disclosure
    app_label="my_nautobot_app",       # Your Django app label
    scope="my_nautobot_app.juniper",   # Dot-separated scope for enable/disable
)
```

`register_mcp_tool()` accepts these parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | `str` | Yes | Unique tool name (e.g. `"juniper_bgp_neighbor_list"`). |
| `func` | `Callable` | Yes | The callable that implements the tool. |
| `description` | `str` | Yes | Human-readable description for the MCP manifest. |
| `input_schema` | `dict[str, Any]` | Yes | JSON Schema describing the tool's input parameters. |
| `tier` | `str` | No | `"core"` (always visible) or `"app"` (progressive, default). |
| `app_label` | `str \| None` | No | Django app label. Required for app-tier tools. |
| `scope` | `str \| None` | No | Dot-separated scope string (e.g. `"my_app.juniper"`). |
| `output_schema` | `dict \| None` | No | JSON Schema for output. Defaults to `{"type": "object"}`. |

### Option 2 — `@register_tool()` (auto-generated schema)

The `@register_tool()` decorator derives the `input_schema` automatically from the function's Python type annotations:

```python
# my_nautobot_app/juniper_tools.py
from fastmcp.server.context import Context as ToolContext
from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from asgiref.sync import sync_to_async


@register_tool(
    description="List BGP neighbors on a Juniper device by device name.",
    tier="app",
    scope="my_nautobot_app.juniper",
)
async def juniper_bgp_neighbor_list(
    ctx: ToolContext,
    name: str,
    limit: int = 25,
) -> dict[str, object]:
    """List BGP neighbors on a Juniper device by device name."""
    user = await get_user_from_request(ctx)
    return await sync_to_async(_sync_bgp_neighbor_list, thread_sensitive=True)(
        user=user, name=name, limit=limit
    )
```

The decorator infers parameter names, types, and default values from the function signature. If you need to override the auto-generated schema for a specific parameter, pass an explicit `input_schema` dict.

## Tier System

Tools are classified into two tiers:

| Tier | Visibility | Registration |
|------|------------|--------------|
| `"core"` | Always in the MCP manifest, regardless of session state | Used by the MCP server itself for built-in tools |
| `"app"` | Visible only after `mcp_enable_tools` is called for their scope | Used by third-party Nautobot apps |

## Scope Hierarchy

Scopes are **dot-separated strings** that form a hierarchy:

```
my_nautobot_app           ← enabling this activates everything below
  └── my_nautobot_app.juniper
  └── my_nautobot_app.cisco
```

When an AI agent calls `mcp_enable_tools(scope="my_nautobot_app")`, the MCP server uses `MCPToolRegistry.get_by_scope()` to find all tools whose scope is exactly `"my_nautobot_app"` **or** starts with `"my_nautobot_app."`. This means enabling the parent scope automatically activates all child tools.

Disabling (`mcp_disable_tools(scope="my_nautobot_app")`) removes the parent and all children in one call.

## Cross-Process Discovery

The MCP server's `MCPToolRegistry` is an in-process singleton — it starts empty and is populated as each Nautobot app is imported at Django startup. Third-party tools call `register_mcp_tool()` in their own module scope, and those calls execute when Django imports the app's `__init__.py` (which itself imports the tool modules).

The registration sequence is:

1. Nautobot Django starts and loads `nautobot_app_mcp_server`.
2. `MCPToolRegistry` singleton is created (empty).
3. Core tools in `nautobot_app_mcp_server.mcp.tools.core` are registered.
4. Other Nautobot apps (`INSTALLED_APPS`) are imported — each may call `register_mcp_tool()` in their `__init__.py`.
5. FastMCP server starts and calls `register_all_tools_with_mcp(mcp)`, wiring every registered tool to the live FastMCP instance.
6. MCP server begins accepting connections on port 8005.

## Complete Working Example

Here is a minimal but complete third-party Nautobot app that registers an MCP tool:

### `my_nautobot_app/__init__.py`

```python
"""my_nautobot_app/__init__.py"""

from nautobot.apps import NautobotAppConfig


class MyNautobotAppConfig(NautobotAppConfig):
    name = "my_nautobot_app"
    description = "Example Nautobot app with an MCP tool"

    def ready(self):
        super().ready()
        # Register MCP tools after Django is fully initialized.
        # Import here so MCPToolRegistry is already available.
        from my_nautobot_app.juniper_tools import juniper_bgp_neighbor_list  # noqa: F401


config = MyNautobotAppConfig
```

### `my_nautobot_app/juniper_tools.py`

```python
"""my_nautobot_app/juniper_tools.py"""

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext

from nautobot_app_mcp_server.mcp import register_tool, get_user_from_request
from nautobot.dcim.models import Device
from nautobot.extras.models import Status


async def _sync_bgp_neighbor_list_impl(user, device_name: str, limit: int) -> dict:
    """Sync implementation — must be called via sync_to_async."""
    devices = Device.objects.restrict(user).filter(name=device_name)
    device = devices.first()
    if not device:
        return {"items": [], "total_count": 0, "summary": f"Device '{device_name}' not found."}
    # Your BGP logic here — return a dict with items, total_count, summary
    return {"items": [], "total_count": 0, "summary": "Not implemented."}


@register_tool(
    description="List BGP neighbors on a Juniper device by device name.",
    tier="app",
    scope="my_nautobot_app.juniper",
)
async def juniper_bgp_neighbor_list(
    ctx: ToolContext,
    name: str,
    limit: int = 25,
) -> dict[str, object]:
    """List BGP neighbors on a Juniper device by device name."""
    user = await get_user_from_request(ctx)
    return await sync_to_async(_sync_bgp_neighbor_list_impl, thread_sensitive=True)(
        user=user, device_name=name, limit=limit
    )
```

### Enabling the tool in an MCP session

Once the app is installed in `PLUGINS` and Nautobot is restarted, an AI agent enables and uses the tool:

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

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "juniper_bgp_neighbor_list",
    "arguments": { "name": "router-01", "limit": 10 }
  },
  "id": 2
}
```
