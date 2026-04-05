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

    def test_create_app_db_failure_raises_runtime_error(self):
        """connection.ensure_connection() failure raises RuntimeError with descriptive message."""
        from nautobot_app_mcp_server.mcp.commands import create_app

        with patch("nautobot_app_mcp_server.mcp.commands.connection.ensure_connection") as mock_ensure:
            mock_ensure.side_effect = Exception("connection refused")

            with self.assertRaises(RuntimeError) as ctx:
                create_app()

            self.assertIn("Database connectivity check failed:", str(ctx.exception))
            self.assertIn("connection refused", str(ctx.exception))
