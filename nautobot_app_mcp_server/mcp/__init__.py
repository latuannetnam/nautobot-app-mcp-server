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

from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition
from nautobot_app_mcp_server.mcp.schema import func_signature_to_input_schema

__all__ = [
    "MCPToolRegistry",
    "ToolDefinition",
    "get_user_from_request",
    "register_all_tools_with_mcp",
    "register_mcp_tool",
    "register_tool",
]


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


def register_tool(
    description: str,
    *,
    tier: str = "app",
    scope: str | None = None,
    input_schema: dict[str, Any] | None = None,
    name: str | None = None,
) -> Callable[[Callable], Callable]:
    """Register a tool with auto-generated input_schema from the function signature.

    This is a convenience decorator that wraps :func:`register_mcp_tool`.
    It extracts the function name (or explicit ``name``) and derives the
    ``input_schema`` from the function's type annotations using
    :func:`func_signature_to_input_schema`.

    Args:
        description: Human-readable description for the MCP tool manifest.
        tier: ``"core"`` for always-available tools, ``"app"`` for registered tools.
        scope: Dot-separated scope string (e.g. ``"netnam_cms_core.juniper"``).
        input_schema: Optional explicit schema. If omitted, auto-generated from
            the function's type annotations.
        name: Optional explicit tool name. If omitted, uses ``func.__name__``.

    Returns:
        A decorator that registers the tool and returns the original function.

    Example::

        @register_tool(description="List devices.", tier="core", scope="core")
        async def device_list_handler(ctx: ToolContext, limit: int = 25) -> dict:
            ...

    Note:
        ``mcp.tool()`` does NOT accept ``input_schema`` as a direct parameter —
        FastMCP 3.x auto-derives the schema from Python type hints. The schema
        stored in MCPToolRegistry is for cross-process discovery and documentation.
        The FastMCP runtime uses its own auto-derived schema from the same function
        signature.
    """

    def decorator(func: Callable) -> Callable:
        tool_name = name if name is not None else func.__name__
        schema = input_schema if input_schema is not None else func_signature_to_input_schema(func)
        register_mcp_tool(
            name=tool_name,
            func=func,
            description=description,
            input_schema=schema,
            tier=tier,
            scope=scope,
        )
        return func

    return decorator


def register_all_tools_with_mcp(mcp: Any) -> None:
    """Register all tools from MCPToolRegistry with a FastMCP instance.

    Called at MCP server startup (inside ``create_app()``) to attach every
    tool that has been registered via :func:`register_mcp_tool` or
    :func:`register_tool` to the live FastMCP instance.

    FastMCP 3.x does NOT accept ``input_schema`` as a parameter to
    ``mcp.tool()`` — the schema is auto-derived from the function's Python
    type hints at decoration/wiring time. The ``input_schema`` stored in
    MCPToolRegistry is for cross-process discovery (e.g. ``tool_registry.json``)
    and is NOT passed to FastMCP here.

    Args:
        mcp: A FastMCP instance returned by ``FastMCP(...)``.

    Note:
        Must be called AFTER ``nautobot.setup()`` so that Django is bootstrapped
        and lazy imports inside tool functions can succeed.
    """
    registry = MCPToolRegistry.get_instance()
    for tool in registry.get_all():
        # mcp.tool() is a decorator in FastMCP 3.x — call it with kwargs
        mcp.tool(tool.func, name=tool.name, description=tool.description)
