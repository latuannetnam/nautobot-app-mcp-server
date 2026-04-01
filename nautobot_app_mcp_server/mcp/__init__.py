"""MCP server package for nautobot_app_mcp_server.

This module exposes the public API for the MCP tool registry. Third-party
Nautobot apps can call :func:`register_mcp_tool` to register their own
MCP tools, which become available to AI agents once session scope is enabled.

Example:
    From a third-party Nautobot app (``netnam_cms_core/__init__.py``)::

        from nautobot_app_mcp_server.mcp import register_mcp_tool

        register_mcp_tool(
            name="juniper_bgp_neighbor_list",
            func=juniper_bgp_neighbor_list,
            description="List BGP neighbors on Juniper devices.",
            input_schema={
                "type": "object",
                "properties": {
                    "device_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
            tier="app",
            app_label="netnam_cms_core",
            scope="netnam_cms_core.juniper",
        )
"""

from __future__ import annotations

from typing import Any, Callable

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

__all__ = ["MCPToolRegistry", "ToolDefinition", "register_mcp_tool"]


def register_mcp_tool(
    name: str,
    func: Callable,
    description: str,
    input_schema: dict[str, Any],
    tier: str = "app",
    app_label: str | None = None,
    scope: str | None = None,
) -> None:
    """Register a tool with the MCP tool registry.

    Called by third-party Nautobot apps in their :meth:`ready` hook,
    or by the MCP server's own post_migrate handler for core tools.

    Args:
        name: Unique tool name (e.g. ``"device_list"``).
        func: The callable tool function.
        description: Human-readable description for the MCP tool manifest.
        input_schema: JSON Schema dict describing the tool's input parameters.
        tier: ``"core"`` for always-available tools, ``"app"`` for registered tools.
        app_label: Django app label (e.g. ``"netnam_cms_core"``). Required for app-tier tools.
        scope: Dot-separated scope string (e.g. ``"netnam_cms_core.juniper"``).
            Optional for app-tier tools; required when progressive disclosure is used.

    Raises:
        ValueError: If a tool with the same name is already registered.

    Example:
        >>> from nautobot_app_mcp_server.mcp import register_mcp_tool
        >>> def my_tool(name: str): pass
        >>> register_mcp_tool(name="my_tool", func=my_tool,
        ...                   description="My tool",
        ...                   input_schema={"type": "object",
        ...                                "properties": {"name": {"type": "string"}}})
    """
    registry = MCPToolRegistry.get_instance()
    registry.register(
        ToolDefinition(
            name=name,
            func=func,
            description=description,
            input_schema=input_schema,
            tier=tier,
            app_label=app_label,
            scope=scope,
        )
    )
