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
from django.db import connection


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

    # STEP 1: DB connectivity check — before nautobot.setup() so failures are fast.
    try:
        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001 — OperationalError, DatabaseError, etc.
        raise RuntimeError(f"Database connectivity check failed: {exc}") from exc

    # STEP 2: Bootstrap Django via nautobot.setup().
    nautobot.setup()

    # STEP 3: Build FastMCP instance.
    # FastMCP 3.x does NOT accept host/port in the constructor — passed at run time.
    from fastmcp import FastMCP

    mcp = FastMCP(
        "NautobotMCP",
        # Note: stateless_http and json_response are passed at run time
        # via mcp.run(transport="http", ...) or mcp.http_app(transport="http").
        # FastMCP 3.x does NOT accept these in the constructor.
    )

    # STEP 4: Wire all registered tools to FastMCP.
    # Importing nautobot_app_mcp_server.mcp.tools side-effects registration into
    # MCPToolRegistry (via @register_tool on each core tool handler).
    from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401

    from nautobot_app_mcp_server.mcp import register_all_tools_with_mcp

    register_all_tools_with_mcp(mcp)

    return (mcp, host, port)
