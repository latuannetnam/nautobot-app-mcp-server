"""FastMCP server instance and lazy ASGI app factory.

The ASGI app is NOT created at module import time (lazy factory).
It is created on the first HTTP request via get_mcp_app(), which
avoids Django startup race conditions where the ORM is not yet ready.

Architecture:
    Django request → urls.py → mcp_view (view.py)
                              → get_mcp_app() [lazy]
                              → mcp.streamable_http_app() [ASGI app]
                              → FastMCP handles MCP protocol
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from mcp.server import Context as ToolContext
    from mcp.server import ToolInstance
    from starlette.applications import Starlette

# Module-level globals — NOT initialized at import time (PIT-03)
_mcp_app: Starlette | None = None


def _setup_mcp_app() -> FastMCP:
    """Build and configure the FastMCP instance.

    Registers session tools and the list_tools() override.
    Must be called from within get_mcp_app() only (lazy, inside Django request).
    """
    # noqa: F401 — imports register decorators on the returned `mcp` instance
    from nautobot_app_mcp_server.mcp.session_tools import (  # pylint: disable=import-outside-toplevel
        _list_tools_handler,
        mcp_disable_tools,
        mcp_enable_tools,
        mcp_list_tools,
    )

    mcp = FastMCP(
        "NautobotMCP",
        stateless_http=False,
        json_response=True,
    )

    # Register session tools as MCP tools (decorators capture `mcp`)
    mcp_enable_tools(mcp)
    mcp_disable_tools(mcp)
    mcp_list_tools(mcp)

    # Register progressive disclosure handler (D-20)
    @mcp.list_tools()  # type: ignore[arg-type]
    async def list_tools_override(ctx: ToolContext) -> list[ToolInstance]:  # pylint: disable=unused-variable
        return await _list_tools_handler(ctx)

    return mcp


def get_mcp_app() -> Starlette:
    """Lazily build the FastMCP ASGI app on first HTTP request.

    This MUST be called from within a Django request context (e.g., from
    mcp_view). Calling it at module import time causes Django ORM errors
    because no request thread context exists yet.

    Returns:
        The FastMCP Starlette ASGI application, mounted at the /mcp/ path.

    Raises:
        RuntimeError: If called outside of a Django request context.
    """
    global _mcp_app  # pylint: disable=global-statement
    if _mcp_app is None:
        mcp = _setup_mcp_app()
        _mcp_app = mcp.streamable_http_app(path="/mcp")
    return _mcp_app
