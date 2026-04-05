"""Scope guard middleware for FastMCP 3.2.0.

This module provides ScopeGuardMiddleware, which enforces session scope gating
at tool-call time as a security backstop for progressive disclosure.

The middleware intercepts tool calls and checks whether the called tool's scope
is enabled in the session's state store (written by mcp_enable_tools).
Core tools (tier="core") always pass through. App-tier tools pass only if
their scope matches an enabled scope (including scope hierarchy).

Progressive disclosure (which tools appear in the manifest) is handled separately
by _list_tools_handler in session_tools.py.
"""

from __future__ import annotations

from typing import Any

from fastmcp.server.middleware import Middleware as FastMCPMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext
from mcp.types import CallToolRequestParams

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

# State key — must match session_tools._ENABLED_SCOPES_KEY
_ENABLED_SCOPES_KEY = "mcp:enabled_scopes"


class ToolNotFoundError(Exception):
    """Raised when a scoped tool is called without the required scope enabled."""


class ScopeGuardMiddleware(FastMCPMiddleware):
    """Enforces session scope gating at tool call time.

    Core tools (``tier="core"``) are always callable. App-tier tools are
    callable only if their scope matches an enabled scope in the session state
    store.

    This middleware is a security backstop for progressive disclosure. The primary
    UX mechanism is ``_list_tools_handler`` (which filters the tool manifest at
    ``tools/list`` time). This middleware blocks ``tools/call`` for tools whose
    scope is not enabled — preventing clients from bypassing the manifest.

    Scope hierarchy: enabling "dcim" also enables "dcim.interface", "dcim.device"
    etc. via prefix matching on the tool's ``scope`` field.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next,
    ) -> Any:
        params = context.method  # CallToolRequestParams — has .name
        registry = MCPToolRegistry.get_instance()
        tool = registry._tools.get(params.name)

        # Core tools: always pass through (no scope check needed)
        if tool is None or tool.tier == "core":
            return await call_next(context)

        # Read enabled scopes from FastMCP session state store
        ctx = context.fastmcp_context
        enabled_list = await ctx.get_state(_ENABLED_SCOPES_KEY)
        enabled: set[str] = set(enabled_list) if enabled_list else set()

        if not enabled:
            # No scopes enabled yet — allow through. The tool will return
            # empty results (or a clear message) if it checks session state.
            return await call_next(context)

        # Check scope hierarchy: enabling parent scope enables all children
        tool_scope = tool.scope or ""
        matches = any(
            tool_scope == s or tool_scope.startswith(f"{s}.")
            for s in enabled
        )
        if matches:
            return await call_next(context)

        # Scope not enabled — raise ToolNotFoundError
        raise ToolNotFoundError(
            f"Tool '{params.name}' requires scope '{tool.scope}' which is not "
            f"enabled for this session. Call mcp_enable_tools first."
        )
