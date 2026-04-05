"""Django management command: start_mcp_server.

Production entry point for the standalone FastMCP server. Bootstrap Django via
nautobot.setup(), then run the FastMCP HTTP server indefinitely.

Usage:
    poetry run nautobot-server start_mcp_server
    poetry run nautobot-server start_mcp_server --host 0.0.0.0 --port 8005

The command blocks forever (mcp.run() does not return). Manage via systemd.
"""

from __future__ import annotations

import os

# STEP 1: nautobot.setup() — MUST be called before any relative imports.
# This satisfies P1-01 / D-03 and prevents "Django wasn't set up yet".
NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG

import nautobot  # noqa: E402

nautobot.setup()

# STEP 2: Now that Django is bootstrapped, safe to import MCP components.
from django.core.management.base import BaseCommand  # noqa: E402

from nautobot_app_mcp_server.mcp.commands import create_app  # noqa: E402


class Command(BaseCommand):
    """Production MCP server management command."""

    help = "Start the standalone FastMCP server (production mode). Blocks indefinitely."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host to bind to (default: 0.0.0.0)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8005,
            help="Port to bind to (default: 8005)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        self.stdout.write(
            self.style.HTTP_INFO(
                f"[start_mcp_server] Starting FastMCP (host={host}, port={port})..."
            )
        )

        try:
            mcp, bound_host, bound_port = create_app(host=host, port=port)
        except RuntimeError as exc:
            self.stderr.write(self.style.ERROR(f"[start_mcp_server] {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"[start_mcp_server] FastMCP listening on {bound_host}:{bound_port}"
            )
        )

        # mcp.run() blocks forever — correct for a production server.
        # Using HTTP transport (modern, recommended over legacy SSE).
        # FastMCP 3.x: stateless_http passed at run time, not constructor.
        mcp.run(transport="http", host=bound_host, port=bound_port, stateless_http=False)
