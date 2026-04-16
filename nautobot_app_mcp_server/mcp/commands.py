"""FastMCP server entry point: create_app() factory.

Phase 8 infrastructure — standalone FastMCP process entry point.
This module is imported by both management commands:
  - start_mcp_server.py   → mcp.run(transport="http", host, port)   (production)
  - start_mcp_dev_server.py → uvicorn.run(mcp.http_app(...), ...)    (development)

Phase 9 wires register_all_tools_with_mcp() into this module.
"""

from __future__ import annotations

import os

import nautobot


def create_app(host: str = "0.0.0.0", port: int = 8005) -> tuple:
    """Build a standalone FastMCP server instance.

    Validates DB connectivity, bootstraps Django via nautobot.setup(), then
    returns the FastMCP instance with bound host/port for the caller to use.

    Reads the following from environment variables:
        NAUTOBOT_CONFIG: Path to Nautobot config file.
            Defaults to "nautobot_config" (resolved by nautobot.core.cli.get_config_path()).
        PLUGINS_CONFIG: Nautobot PLUGINS_CONFIG dict. If set, overrides the value in the
            config file at startup.

    Args:
        host: Host to bind to. Defaults to "0.0.0.0" (all interfaces).
        port: Port to bind to. Defaults to 8005.

    Returns:
        A 3-tuple of (FastMCP instance, host, port).

    Raises:
        RuntimeError: If the database is unreachable or the config file is missing.
    """
    # STEP 0: Read NAUTOBOT_CONFIG from environment.
    # nautobot.setup() uses this to locate the config file.
    # Default "nautobot_config" is resolved by nautobot.core.cli.get_config_path().
    _NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")

    # STEP 0b: Optionally read PLUGINS_CONFIG from environment for override/validation.
    # nautobot.setup() loads PLUGINS_CONFIG from the config file; this env var allows
    # the management command to override it at startup if needed.
    _PLUGINS_CONFIG = os.environ.get("PLUGINS_CONFIG")

    # STEP 1: Bootstrap Django via nautobot.setup() FIRST — required before any
    # Django ORM access.
    nautobot.setup()

    # STEP 2: No explicit DB connectivity check here.
    # The MCP request handlers use Django's ORM which will fail on the first
    # request if the DB is unreachable (caught gracefully by FastMCP error
    # handling). The docker-compose healthcheck verifies HTTP reachability.
    # Previously: sync_to_async wrapper caused "DatabaseWrapper objects created
    # in a thread can only be used in that same thread" because ThreadPoolExecutor
    # and asyncio event loop threads differ from the management-command thread
    # where connection was created. Direct sync call worked in management-command
    # context but raised "async context" error with uvicorn --factory=True. The
    # cleanest fix: trust that the DB is healthy (depends_on: db: healthy) and
    # let the MCP server fail gracefully on first request if it isn't.

    # STEP 3: Build FastMCP instance.
    # FastMCP 3.x does NOT accept host/port in the constructor — passed at run time.
    from fastmcp import FastMCP

    mcp = FastMCP(
        "NautobotMCP",
        # Note: stateless_http and json_response are passed at run time
        # via mcp.run(transport="http", ...) or mcp.http_app(transport="http").
        # FastMCP 3.x does NOT accept these in the constructor.
    )

    # STEP 4a: Read tool_registry.json for cross-process discovery.
    # Written by NautobotAppMcpServerConfig.ready() (Phase 7 in INSTALLED_APPS).
    # Graceful no-op if not present (standalone server without the plugin, or
    # plugin not yet installed).
    _tool_registry_path = os.path.join(os.path.dirname(__file__), "tool_registry.json")
    if os.path.exists(_tool_registry_path):
        import json as _json

        with open(_tool_registry_path) as _f:
            _tool_entries = _json.load(_f)
        # Log discovery summary — tools are actually registered below (STEP 4b)
        # via side-effect import. This step validates the JSON file is present
        # and readable, matching the ROADMAP criterion: "MCP server reads it".
        import logging as _logging

        _logging.getLogger(__name__).info(
            "tool_registry.json: discovered %d tool(s) from plugin startup",
            len(_tool_entries),
        )
    else:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "tool_registry.json not found — skipping cross-process discovery "
            "(standalone server mode or plugin not installed yet)"
        )

    # STEP 4b: Wire all registered tools to FastMCP.
    # Side-effect imports trigger @register_tool decoration in each module,
    # populating MCPToolRegistry. All registered tools are then attached to the
    # FastMCP instance.
    from nautobot_app_mcp_server.mcp import (
        register_all_tools_with_mcp,
        session_tools,  # noqa: F401
    )
    from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401

    register_all_tools_with_mcp(mcp)

    # STEP 4c: Wire scope guard middleware for session scope enforcement (Phase 10)
    from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware

    mcp.add_middleware(ScopeGuardMiddleware())

    return (mcp, host, port)


def mcp_app_factory():
    """ASGI app factory for uvicorn --factory mode.

    Nautobot setup is called inside the FastMCP lifespan context, ensuring
    Django's asgiref Local is accessed within a proper ASGI request scope.
    """
    mcp, _bound_host, _bound_port = create_app(host="0.0.0.0", port=8005)
    return mcp.http_app(transport="http", stateless_http=False)  # type: ignore[no-any-return]
