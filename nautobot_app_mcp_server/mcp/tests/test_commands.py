"""Tests for mcp/commands.py — create_app() factory."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase


class TestCreateApp(TestCase):
    """Test create_app() factory."""

    def test_create_app_returns_tuple_of_three(self):
        """create_app() returns (mcp, host, port) when DB is reachable."""
        from nautobot_app_mcp_server.mcp.commands import create_app

        result = create_app(host="127.0.0.1", port=9000)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        mcp, host, port = result
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 9000)

    def test_create_app_no_explicit_db_check(self):
        """create_app() does not perform an explicit DB connectivity check at startup.

        The MCP server trusts that the DB is healthy (depends_on: db: healthy in
        Docker Compose) and defers connectivity checks to request time.  This
        means create_app() does NOT call connection.ensure_connection(), so
        mocking it has no effect on the return value.
        """
        from nautobot_app_mcp_server.mcp.commands import create_app

        with patch(
            "nautobot_app_mcp_server.mcp.commands.connection.ensure_connection",
            side_effect=Exception("unreachable"),
        ):
            # create_app() must still return a valid (mcp, host, port) tuple
            # even when ensure_connection would fail — there is no explicit call.
            result = create_app(host="127.0.0.1", port=9000)
            self.assertIsInstance(result, tuple)
            self.assertEqual(len(result), 3)
