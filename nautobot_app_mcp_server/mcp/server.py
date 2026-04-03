"""FastMCP server instance and lazy ASGI app factory.

The ASGI app is NOT created at module import time (lazy factory).
It is created on the first HTTP request via get_mcp_app(), which
avoids Django startup race conditions where the ORM is not yet ready.

Architecture:
    Django request → urls.py → mcp_view (view.py)
                              → get_mcp_app() [lazy]
                              → mcp.http_app() [ASGI app]
                              → FastMCP handles MCP protocol
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.context import Context as ToolContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

if TYPE_CHECKING:
    from starlette.applications import Starlette

# Shared FastMCP instance — ensures only one server is ever created
_mcp_instance: FastMCP | None = None

# Lazy ASGI app (Starlette) + session manager singletons
_mcp_app: Starlette | None = None
_mcp_session_manager: StreamableHTTPSessionManager | None = None

# Double-checked locking locks
_app_lock = threading.Lock()
_session_lock = threading.Lock()


def _setup_mcp_app() -> FastMCP:
    """Build and configure the FastMCP instance.

    Registers session tools and overrides _list_tools_mcp for progressive disclosure.
    Must be called from within get_mcp_app() only (lazy, inside Django request).
    """
    # noqa: F401 — imports register decorators on the returned `mcp` instance
    from nautobot_app_mcp_server.mcp.session_tools import (  # pylint: disable=import-outside-toplevel
        _list_tools_handler,
        mcp_disable_tools,
        mcp_enable_tools,
        mcp_list_tools,
    )

    mcp = FastMCP("NautobotMCP")

    # Register session tools as MCP tools (decorators capture `mcp`)
    mcp_enable_tools(mcp)
    mcp_disable_tools(mcp)
    mcp_list_tools(mcp)

    # Override _list_tools_mcp for progressive disclosure (D-20, REGI-05).
    # FastMCP 3.2.0: @mcp.list_tools() is async and cannot be used as a decorator.
    # The override pattern is the same used internally by FastMCP.
    original_list_tools_mcp = mcp._list_tools_mcp

    async def progressive_list_tools_mcp(request=None) -> object:
        # Access the MCP session from FastMCP's low-level server request context.
        # During live HTTP requests: request_ctx is set by _handle_request before
        # calling handlers. In tests / outside request: LookupError is raised.
        session_dict: dict = {}
        try:
            from mcp.server.lowlevel.server import Server

            req_ctx = Server.request_context
            ctx_obj = req_ctx.get()
            if ctx_obj is not None:
                session = ctx_obj.session
                # session is ServerSession — dict-like with get/setitem
                if hasattr(session, "get") and hasattr(session, "__setitem__"):
                    session_dict = session  # type: ignore[assignment]
        except LookupError:
            pass  # No request context (e.g., in tests) — fall through to all tools

        # Build mock ToolContext that passes the real session dict
        mock_ctx = _make_mock_tool_context(session_dict)
        filtered_tool_names = await _list_tools_handler(mock_ctx)
        filtered_names_set = {t.name for t in filtered_tool_names}

        # Get all tools from the original handler
        result = await original_list_tools_mcp(request)

        # Filter to only the session-filtered tools + core tools
        result.tools = [tool for tool in result.tools if tool.name in filtered_names_set]
        return result

    mcp._list_tools_mcp = progressive_list_tools_mcp  # type: ignore[method-assign]

    return mcp


def _make_mock_tool_context(session_dict: dict) -> ToolContext:
    """Build a mock ToolContext that forwards session to _list_tools_handler.

    The mock only needs request_context.session to return the session dict.
    """
    from unittest.mock import MagicMock

    mock_session = MagicMock()
    mock_session.get = session_dict.get  # type: ignore[method-assign]
    mock_session.__setitem__ = session_dict.__setitem__  # type: ignore[method-assign]
    mock_session.__contains__ = session_dict.__contains__  # type: ignore[method-assign]

    mock_req_ctx = MagicMock()
    mock_req_ctx.session = mock_session

    mock_ctx = MagicMock(spec=ToolContext)
    mock_ctx.request_context = mock_req_ctx
    return mock_ctx  # type: ignore[return-value]


def get_mcp_app() -> Starlette:
    """Lazily build the FastMCP ASGI app on first HTTP request.

    This MUST be called from within a Django request context (e.g., from
    mcp_view). Calling it at module import time causes Django ORM errors
    because no request thread context exists yet.

    Thread-safe: uses double-checked locking with threading.Lock to prevent
    duplicate FastMCP instances under concurrent Django workers.

    Returns:
        The FastMCP Starlette ASGI application, mounted at the /mcp/ path.

    Raises:
        RuntimeError: If called outside of a Django request context.
    """
    global _mcp_app, _mcp_instance  # pylint: disable=global-statement
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:  # double-checked locking
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_app = _mcp_instance.http_app(
                    path="/mcp",
                    transport="streamable-http",
                    stateless_http=False,
                    json_response=True,
                )
    return _mcp_app


def get_session_manager() -> StreamableHTTPSessionManager:
    """Return the StreamableHTTPSessionManager singleton.

    Lazily created alongside the FastMCP instance on first call.
    Both share the same _mcp_instance so only one FastMCP server is created.

    The session manager is the entry point for view.py's ASGI bridge:
    it must be passed to _call_starlette_handler() inside async_to_sync
    so that session_manager.run() can be entered (which sets
    Server.request_context and allows tool handlers to access session state).

    Returns:
        The StreamableHTTPSessionManager instance for this process.

    Raises:
        RuntimeError: If called before Django is fully initialized.
    """
    global _mcp_session_manager, _mcp_instance  # pylint: disable=global-statement
    if _mcp_session_manager is None:
        with _session_lock:
            if _mcp_session_manager is None:  # double-checked locking
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_session_manager = StreamableHTTPSessionManager(
                    app=_mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
    return _mcp_session_manager
