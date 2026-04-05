"""Session management tools and progressive disclosure handler.

Phase 10 replaces the Phase 5 `RequestContext._mcp_tool_state` monkey-patch
with FastMCP's native `ctx.set_state()`/`ctx.get_state()` session-state API.

Session state is stored in FastMCP's in-memory state store (MemoryStore), keyed
by ``session_id:mcp:enabled_scopes`` and ``session_id:mcp:enabled_searches``.
This requires no monkey-patching and is the official FastMCP 3.2.0 session API.

Scope hierarchy: enabling "dcim" activates "dcim.interface", "dcim.device", etc.
via MCPToolRegistry.get_by_scope() prefix matching.

Core tools are ALWAYS returned by _list_tools_handler() regardless of
session state. Non-core tools require their scope to be enabled first.

The ``ScopeGuardMiddleware`` (in ``middleware.py``) enforces scope at
tool-call time as a security backstop. Progressive disclosure via
_list_tools_handler handles the UX (which tools appear in the manifest).

Registration strategy: tool implementations are defined at module level so
they can be registered in MCPToolRegistry unconditionally on import. The FastMCP
factory functions (``mcp_enable_tools(mcp)`` etc.) apply the ``@mcp.tool()``
decorator. This ensures tools appear in the registry even without a live
FastMCP server (tests, migrations).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastmcp.server.context import Context as ToolContext
from mcp.types import Tool as ToolInstance

from nautobot_app_mcp_server.mcp import register_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

# -------------------------------------------------------------------
# State keys — FastMCP MemoryStore (keyed by session_id prefix)
# -------------------------------------------------------------------

_ENABLED_SCOPES_KEY = "mcp:enabled_scopes"
_ENABLED_SEARCHES_KEY = "mcp:enabled_searches"

# -------------------------------------------------------------------
# Async helpers — read/write FastMCP session state
# -------------------------------------------------------------------


async def _get_enabled_scopes(ctx: ToolContext) -> set[str]:
    """Get the enabled scopes set from FastMCP session state."""
    val = await ctx.get_state(_ENABLED_SCOPES_KEY)
    return set(val) if val else set()


async def _set_enabled_scopes(ctx: ToolContext, scopes: set[str]) -> None:
    """Write the enabled scopes set to FastMCP session state."""
    await ctx.set_state(_ENABLED_SCOPES_KEY, list(scopes))


async def _get_enabled_searches(ctx: ToolContext) -> set[str]:
    """Get the enabled search terms set from FastMCP session state."""
    val = await ctx.get_state(_ENABLED_SEARCHES_KEY)
    return set(val) if val else set()


async def _set_enabled_searches(ctx: ToolContext, searches: set[str]) -> None:
    """Write the enabled search terms set to FastMCP session state."""
    await ctx.set_state(_ENABLED_SEARCHES_KEY, list(searches))


# -------------------------------------------------------------------
# ToolScopeState — per-session visibility state wrapper
# -------------------------------------------------------------------


@dataclass
class ToolScopeState:
    """Per-session tool visibility state via FastMCP state API.

    Attributes:
        enabled_scopes: Dot-separated scope strings currently enabled for
            this session (e.g. {"dcim", "ipam.vlan"}).
        enabled_searches: Fuzzy search terms active for this session.
    """

    async def get_enabled_scopes(self, ctx: ToolContext) -> set[str]:
        return await _get_enabled_scopes(ctx)

    async def set_enabled_scopes(self, ctx: ToolContext, scopes: set[str]) -> None:
        await _set_enabled_scopes(ctx, scopes)

    async def get_enabled_searches(self, ctx: ToolContext) -> set[str]:
        return await _get_enabled_searches(ctx)

    async def set_enabled_searches(self, ctx: ToolContext, searches: set[str]) -> None:
        await _set_enabled_searches(ctx, searches)

    async def apply_enable(
        self, ctx: ToolContext, scope: str | None, search: str | None
    ) -> list[str]:
        """Enable scope and/or search. Returns message parts for the return value."""
        parts: list[str] = []
        if scope:
            current = await self.get_enabled_scopes(ctx)
            current.add(scope)
            await self.set_enabled_scopes(ctx, current)
            parts.append(f"scope '{scope}'")
        if search:
            current = await self.get_enabled_searches(ctx)
            current.add(search)
            await self.set_enabled_searches(ctx, current)
            parts.append(f"search '{search}'")
        return parts

    async def apply_disable(self, ctx: ToolContext, scope: str | None) -> tuple[str, int]:
        """Disable scope(s).

        Args:
            ctx: FastMCP ToolContext.
            scope: Dot-separated scope to disable. None = disable all.

        Returns:
            A 2-tuple of (human-readable message, number of child scopes removed).
        """
        if scope is None:
            await self.set_enabled_scopes(ctx, set())
            await self.set_enabled_searches(ctx, set())
            return ("Disabled all non-core tools.", 0)
        current = await self.get_enabled_scopes(ctx)
        to_remove = {s for s in current if s == scope or s.startswith(f"{scope}.")}
        await self.set_enabled_scopes(ctx, current - to_remove)
        return (f"Disabled scope '{scope}'", len(to_remove))


# -------------------------------------------------------------------
# Progressive disclosure handler (registered via _setup_mcp_app())
# -------------------------------------------------------------------


async def _list_tools_handler(
    ctx: ToolContext,
) -> list[ToolInstance]:
    """Return tools filtered by session state (progressive disclosure).

    Always includes core tools (tier="core"). Non-core tools are included if:
        - Their scope matches any entry in session state (scope hierarchy)
        - OR their name/description fuzzy-matches an enabled search term

    Reads enabled_scopes and enabled_searches from FastMCP's session state
    store (``ctx.get_state()``), NOT from a monkey-patched dict attribute.

    Args:
        ctx: FastMCP ToolContext providing session access.

    Returns:
        List of MCP ToolInstance objects for the MCP manifest.
    """
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

    registry = MCPToolRegistry.get_instance()

    # Core tools: always included
    core_tools = registry.get_core_tools()

    # Non-core tools: filtered by enabled_scopes and enabled_searches
    non_core: dict[str, ToolInstance] = {}

    # Read session state from FastMCP MemoryStore
    scopes_list = await ctx.get_state(_ENABLED_SCOPES_KEY)
    enabled_scopes: set[str] = set(scopes_list) if scopes_list else set()

    searches_list = await ctx.get_state(_ENABLED_SEARCHES_KEY)
    enabled_searches: set[str] = set(searches_list) if searches_list else set()

    for scope in enabled_scopes:
        for tool in registry.get_by_scope(scope):
            non_core[tool.name] = tool

    for term in enabled_searches:
        for tool in registry.fuzzy_search(term):
            non_core[tool.name] = tool

    all_tools = core_tools + list(non_core.values())

    return [
        ToolInstance(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
        )
        for t in all_tools
    ]


# -------------------------------------------------------------------
# Tool implementations — async def using ToolScopeState
# -------------------------------------------------------------------


@register_tool(
    name="mcp_enable_tools",
    description="Enable tool scopes or fuzzy-search matches for this session.",
    tier="core",
)
async def _mcp_enable_tools_impl(
    ctx: ToolContext,
    scope: str | None = None,
    search: str | None = None,
) -> str:
    """Enable tool scopes or fuzzy-search matches for this session.

    Either ``scope`` OR ``search`` (or both) must be provided.

    Scope format: dot-separated string (e.g. ``"dcim.interface"``).
    Enabling a parent scope (e.g. ``"dcim"``) automatically activates all
    child scopes (``"dcim.interface"``, ``"dcim.device"``) because
    MCPToolRegistry.get_by_scope() uses prefix matching.

    Search performs a fuzzy match across all registered tool names and
    descriptions. Matching tools are added to the session.

    Core tools (``tier="core"``) are always available; this tool controls
    only the visibility of app-tier tools.

    Session state is stored via FastMCP's ``ctx.set_state()`` API
    (Phase 10, replacing the Phase 5 ``_mcp_tool_state`` monkey-patch).

    Args:
        ctx: FastMCP ToolContext.
        scope: Dot-separated scope to enable (e.g. ``"ipam"``, ``"dcim"``).
        search: Fuzzy search term to match tool names/descriptions.

    Returns:
        Human-readable summary of what was enabled.
    """
    if scope is None and search is None:
        return "Provide at least one of: scope= or search="

    state = ToolScopeState()
    parts = await state.apply_enable(ctx, scope, search)
    return f"Enabled: {', '.join(parts)}"


@register_tool(
    name="mcp_disable_tools",
    description="Disable a tool scope for this session.",
    tier="core",
)
async def _mcp_disable_tools_impl(
    ctx: ToolContext,
    scope: str | None = None,
) -> str:
    """Disable a tool scope for this session.

    Disabling a parent scope (e.g. ``"dcim"``) disables all child scopes
    (``"dcim.interface"``, ``"dcim.device"``) because the session stores
    only parent scopes and MCPToolRegistry.get_by_scope() matches children
    by prefix.

    If ``scope`` is None, disables ALL non-core tools (resets session state).

    Session state is stored via FastMCP's ``ctx.set_state()`` API
    (Phase 10, replacing the Phase 5 ``_mcp_tool_state`` monkey-patch).

    Args:
        ctx: FastMCP ToolContext.
        scope: Dot-separated scope to disable. None = disable all.

    Returns:
        Human-readable summary of what was disabled.
    """
    state = ToolScopeState()
    msg, child_count = await state.apply_disable(ctx, scope)
    if child_count > 0:
        return f"{msg} and {child_count} child scope(s)."
    return msg


@register_tool(
    name="mcp_list_tools",
    description="Return all registered tools visible to this session.",
    tier="core",
)
async def _mcp_list_tools_impl(ctx: ToolContext) -> str:
    """Return all registered tools visible to this session.

    Returns a summary of:
        - Core tools (always available)
        - Enabled scopes and their tools
        - Active fuzzy search terms

    Core tools are always listed regardless of session state.
    Reads enabled scopes and searches from FastMCP's ``ctx.get_state()`` API
    (Phase 10, replacing the Phase 5 ``_mcp_tool_state`` monkey-patch).

    Args:
        ctx: FastMCP ToolContext.

    Returns:
        Multi-line string describing active tools and session state.
    """
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

    registry = MCPToolRegistry.get_instance()
    core = registry.get_core_tools()

    enabled_scopes = await _get_enabled_scopes(ctx)
    enabled_searches = await _get_enabled_searches(ctx)

    lines = [f"Core tools ({len(core)}):"]
    for t in core:
        lines.append(f"  - {t.name}")

    if enabled_scopes:
        lines.append(f"\nEnabled scopes ({len(enabled_scopes)}):")
        for scope in sorted(enabled_scopes):
            tools = registry.get_by_scope(scope)
            lines.append(f"  [{scope}] ({len(tools)} tools)")
            for t in tools:
                lines.append(f"    - {t.name}")

    if enabled_searches:
        lines.append(f"\nActive searches ({len(enabled_searches)}):")
        for term in sorted(enabled_searches):
            tools = registry.fuzzy_search(term)
            lines.append(f"  '{term}' → {len(tools)} tools")

    return "\n".join(lines)


# -------------------------------------------------------------------
# FastMCP factory functions — apply @mcp.tool() decorator
# -------------------------------------------------------------------


def mcp_enable_tools(mcp: FastMCP) -> None:
    """Register mcp_enable_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_enable_tools_impl(  # noqa: ANN202
        ctx: ToolContext, scope: str | None = None, search: str | None = None
    ) -> str:
        return await _mcp_enable_tools_impl(ctx, scope, search)


def mcp_disable_tools(mcp: FastMCP) -> None:
    """Register mcp_disable_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_disable_tools_impl(  # noqa: ANN202
        ctx: ToolContext, scope: str | None = None
    ) -> str:
        return await _mcp_disable_tools_impl(ctx, scope)


def mcp_list_tools(mcp: FastMCP) -> None:
    """Register mcp_list_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_list_tools_impl(ctx: ToolContext) -> str:  # noqa: ANN202
        return await _mcp_list_tools_impl(ctx)
