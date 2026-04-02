"""Session management tools and progressive disclosure handler.

Exports 4 symbols for server.py registration:
    mcp_enable_tools  — factory: register as FastMCP tool + MCPToolRegistry
    mcp_disable_tools  — factory: register as FastMCP tool + MCPToolRegistry
    mcp_list_tools    — factory: register as FastMCP tool + MCPToolRegistry
    _list_tools_handler — coroutine: progressive disclosure logic

Session state lives in FastMCP's session dict (D-19):
    session["enabled_scopes"]  — set[str]: enabled scope strings
    session["enabled_searches"] — set[str]: fuzzy search terms

Scope hierarchy (D-21): enabling "dcim" activates "dcim.interface",
"dcim.device", etc. via MCPToolRegistry.get_by_scope() startswith matching.

Core tools are ALWAYS returned by _list_tools_handler() regardless of
session state (D-27, SESS-06, REGI-05).

Registration strategy: Tool implementations are defined at module level so
they can be registered in MCPToolRegistry unconditionally. The FastMCP
factory functions (passed to _setup_mcp_app()) apply the @mcp.tool()
decorator. This ensures tools appear in the registry even without a live
FastMCP server (tests, migrations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.server import Context as ToolContext
    from mcp.server import ToolInstance

from nautobot_app_mcp_server.mcp import register_mcp_tool

# -------------------------------------------------------------------
# MCPSessionState — thin wrapper over FastMCP session dict (D-26)
# -------------------------------------------------------------------


@dataclass
class MCPSessionState:
    """Per-conversation tool visibility state.

    Stored directly in FastMCP's session dict as:
        session["enabled_scopes"]  — set[str]
        session["enabled_searches"] — set[str]

    Attributes:
        enabled_scopes: Dot-separated scope strings that are currently
            enabled for this session (e.g. {"dcim", "ipam.vlan"}).
        enabled_searches: Fuzzy search terms active for this session.
    """

    enabled_scopes: set[str] = field(default_factory=set)
    enabled_searches: set[str] = field(default_factory=set)

    @classmethod
    def from_session(cls, session: dict) -> MCPSessionState:
        """Load session state from a FastMCP session dict.

        Args:
            session: FastMCP StreamableHTTPSessionManager session object
                (a dict-like with get/setitem).

        Returns:
            MCPSessionState with scopes/searches loaded from the session,
            or empty state if not yet initialized.
        """
        return cls(
            enabled_scopes=set(session.get("enabled_scopes", set())),
            enabled_searches=set(session.get("enabled_searches", set())),
        )

    def apply_to_session(self, session: dict) -> None:
        """Persist state back into the FastMCP session dict.

        Args:
            session: FastMCP session dict to update in-place.
        """
        session["enabled_scopes"] = self.enabled_scopes
        session["enabled_searches"] = self.enabled_searches


# -------------------------------------------------------------------
# Progressive disclosure handler (registered as @mcp.list_tools())
# -------------------------------------------------------------------


async def _list_tools_handler(
    ctx: ToolContext,
) -> list[ToolInstance]:  # noqa: ANN201
    """Return tools filtered by session state (progressive disclosure, REGI-05).

    Always included core tools (D-27). Non-core tools are included if:
        - Their scope matches any entry in session["enabled_scopes"]
        - OR their name/description fuzzy-matches any entry in
          session["enabled_searches"]

    Args:
        ctx: FastMCP ToolContext providing request and session access.

    Returns:
        List of MCP ToolInstance objects for the MCP manifest.
    """
    from mcp.server import ToolInstance

    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

    session = ctx.request_context.session
    state = MCPSessionState.from_session(session)

    registry = MCPToolRegistry.get_instance()

    # Core tools: always included (D-27, SESS-06)
    core_tools = registry.get_core_tools()

    # Non-core tools: filtered by enabled_scopes and enabled_searches
    non_core: dict[str, ToolDefinition] = {}

    for scope in state.enabled_scopes:
        for tool in registry.get_by_scope(scope):
            non_core[tool.name] = tool

    for term in state.enabled_searches:
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
# Tool implementations — module level for unconditional MCPToolRegistry
# registration. Each is registered in MCPToolRegistry on import, so
# tests and post_migrate can find them without a live FastMCP server.
# -------------------------------------------------------------------


async def _mcp_enable_tools_impl(  # noqa: ANN202
    ctx: ToolContext,
    scope: str | None = None,
    search: str | None = None,
) -> str:
    """Enable tool scopes or fuzzy-search matches for this session.

    Either ``scope`` OR ``search`` (or both) must be provided.

    Scope format: dot-separated string (e.g. ``"dcim.interface"``).
    Enabling a parent scope (e.g. ``"dcim"``) automatically activates all
    child scopes (``"dcim.interface"``, ``"dcim.device"``) because
    MCPToolRegistry.get_by_scope() uses startswith matching (D-21).

    Search performs a fuzzy match across all registered tool names and
    descriptions. Matching tools are added to the session.

    Core tools (``tier="core"``) are always available; this tool controls
    only the visibility of app-tier tools.

    Args:
        ctx: FastMCP ToolContext.
        scope: Dot-separated scope to enable (e.g. ``"ipam"``, ``"dcim"``).
        search: Fuzzy search term to match tool names/descriptions.

    Returns:
        Human-readable summary of what was enabled.
    """
    if scope is None and search is None:
        return "Provide at least one of: scope= or search="

    session = ctx.request_context.session
    state = MCPSessionState.from_session(session)
    parts: list[str] = []

    if scope is not None:
        state.enabled_scopes.add(scope)
        parts.append(f"scope '{scope}'")

    if search is not None:
        state.enabled_searches.add(search)
        parts.append(f"search '{search}'")

    state.apply_to_session(session)
    return f"Enabled: {', '.join(parts)}"


register_mcp_tool(
    name="mcp_enable_tools",
    func=_mcp_enable_tools_impl,
    description="Enable tool scopes or fuzzy-search matches for this session.",
    input_schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": (
                    "Dot-separated scope to enable (e.g. 'ipam', 'dcim'). "
                    "Enabling a parent scope activates all child scopes."
                ),
            },
            "search": {
                "type": "string",
                "description": "Fuzzy search term to match tool names/descriptions.",
            },
        },
        "additionalProperties": False,
    },
    tier="core",
)


async def _mcp_disable_tools_impl(  # noqa: ANN202
    ctx: ToolContext,
    scope: str | None = None,
) -> str:
    """Disable a tool scope for this session.

    Disabling a parent scope (e.g. ``"dcim"``) disables all child scopes
    (``"dcim.interface"``, ``"dcim.device"``) because the session stores
    only parent scopes and MCPToolRegistry.get_by_scope() matches children
    by prefix (D-21).

    If ``scope`` is None, disables ALL non-core tools (resets session state).

    Args:
        ctx: FastMCP ToolContext.
        scope: Dot-separated scope to disable. None = disable all.

    Returns:
        Human-readable summary of what was disabled.
    """
    session = ctx.request_context.session
    state = MCPSessionState.from_session(session)

    if scope is None:
        state.enabled_scopes.clear()
        state.enabled_searches.clear()
        state.apply_to_session(session)
        return "Disabled all non-core tools."

    # Find all scopes that start with this prefix (children included)
    to_remove = {s for s in state.enabled_scopes if s == scope or s.startswith(f"{scope}.")}
    state.enabled_scopes -= to_remove
    state.apply_to_session(session)
    return f"Disabled scope '{scope}' and {len(to_remove)} child scope(s)."


register_mcp_tool(
    name="mcp_disable_tools",
    func=_mcp_disable_tools_impl,
    description="Disable a tool scope for this session.",
    input_schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": ("Dot-separated scope to disable (e.g. 'dcim'). " "None disables all non-core tools."),
            },
        },
        "additionalProperties": False,
    },
    tier="core",
)


async def _mcp_list_tools_impl(ctx: ToolContext) -> str:  # noqa: ANN202
    """Return all registered tools visible to this session.

    Returns a summary of:
    - Core tools (always available)
    - Enabled scopes and their tools
    - Active fuzzy search terms

    Core tools are always listed regardless of session state.

    Args:
        ctx: FastMCP ToolContext.

    Returns:
        Multi-line string describing active tools and session state.
    """
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

    session = ctx.request_context.session
    state = MCPSessionState.from_session(session)
    registry = MCPToolRegistry.get_instance()

    core = registry.get_core_tools()
    lines = [f"Core tools ({len(core)}):"]
    for t in core:
        lines.append(f"  - {t.name}")

    if state.enabled_scopes:
        lines.append(f"\nEnabled scopes ({len(state.enabled_scopes)}):")
        for scope in sorted(state.enabled_scopes):
            tools = registry.get_by_scope(scope)
            lines.append(f"  [{scope}] ({len(tools)} tools)")
            for t in tools:
                lines.append(f"    - {t.name}")

    if state.enabled_searches:
        lines.append(f"\nActive searches ({len(state.enabled_searches)}):")
        for term in sorted(state.enabled_searches):
            tools = registry.fuzzy_search(term)
            lines.append(f"  '{term}' → {len(tools)} tools")

    return "\n".join(lines)


register_mcp_tool(
    name="mcp_list_tools",
    func=_mcp_list_tools_impl,
    description="Return all registered tools visible to this session.",
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    tier="core",
)


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
