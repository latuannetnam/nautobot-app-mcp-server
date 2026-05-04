"""Tests for mcp/commands.py — create_app() factory."""

from __future__ import annotations

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
        means create_app() does NOT call connection.ensure_connection(), and
        connection is not imported at module level in commands.py.
        """
        import nautobot_app_mcp_server.mcp.commands as commands_module

        # Verify connection is not imported at module level
        self.assertFalse(
            hasattr(commands_module, "connection"),
            "django.db.connection should not be imported at module level",
        )
