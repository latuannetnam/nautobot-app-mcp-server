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
    from starlette.applications import Starlette

# Module-level globals — NOT initialized at import time (PIT-03)
_mcp_app: Starlette | None = None


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
        mcp = FastMCP(
            "NautobotMCP",
            stateless_http=False,
            json_response=True,
        )
        _mcp_app = mcp.streamable_http_app(path="/mcp")
    return _mcp_app
