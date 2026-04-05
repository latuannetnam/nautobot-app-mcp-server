"""Django management command: start_mcp_dev_server.

Development entry point for the standalone FastMCP server. Calls create_app()
to validate DB and build the FastMCP instance, then serves via uvicorn with
hot-reload.

Usage (run inside the Nautobot container):
    poetry run nautobot-server start_mcp_dev_server
    poetry run nautobot-server start_mcp_dev_server --port 8005

Reload watch is scoped to nautobot_app_mcp_server/ only (not the entire project
root) for faster restarts and fewer spurious reloads.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG

import nautobot  # noqa: E402

nautobot.setup()

from django.core.management.base import BaseCommand  # noqa: E402

from nautobot_app_mcp_server.mcp.commands import create_app  # noqa: E402


class Command(BaseCommand):
    """Development MCP server management command with hot-reload."""

    help = "Start the standalone FastMCP server in dev mode (uvicorn reload)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host to bind to (default: 127.0.0.1 — localhost only)",
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
                f"[start_mcp_dev_server] Starting FastMCP dev server " f"(host={host}, port={port}, reload=True)..."
            )
        )

        try:
            mcp, bound_host, bound_port = create_app(host=host, port=port)
        except RuntimeError as exc:
            self.stderr.write(self.style.ERROR(f"[start_mcp_dev_server] {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"[start_mcp_dev_server] FastMCP dev server listening on "
                f"{bound_host}:{bound_port} (auto-reload active)"
            )
        )

        # mcp.http_app() returns a StarletteWithLifespan ASGI callable.
        # FastMCP 3.x: stateless_http passed at run time via http_app().
        mcp_app = mcp.http_app(transport="http", stateless_http=False)

        # reload_dirs scoped to nautobot_app_mcp_server/ only (D-08).
        package_root = Path(__file__).resolve().parents[3] / "nautobot_app_mcp_server"

        uvicorn.run(
            mcp_app,
            host=bound_host,
            port=bound_port,
            reload=True,
            reload_dirs=[str(package_root)],
            log_level="info",
        )
