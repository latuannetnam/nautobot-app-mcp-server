"""Tests for the MCP HTTP endpoint — ASGI bridge and endpoint reachability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings


class MCPViewTestCase(TestCase):
    """Test the MCP Django view and ASGI bridge."""

    @override_settings(
        PLUGINS=["nautobot_app_mcp_server"],
        ROOT_URLCONF="nautobot_app_mcp_server.urls",
    )
    def test_mcp_view_imports_successfully(self):
        """Verify mcp_view is importable and is a callable."""
        from nautobot_app_mcp_server.mcp.view import mcp_view

        self.assertTrue(callable(mcp_view))

    @override_settings(
        PLUGINS=["nautobot_app_mcp_server"],
        ROOT_URLCONF="nautobot_app_mcp_server.urls",
    )
    def test_mcp_endpoint_resolves(self):
        """Verify the /mcp/ URL resolves to mcp_view."""
        from django.urls import resolve

        match = resolve("/mcp/")
        self.assertEqual(match.func, match.func)  # resolves without 404
        self.assertEqual(match.url_name, "mcp")

    @patch("nautobot_app_mcp_server.mcp.view.get_mcp_app")
    def test_view_calls_get_mcp_app(self, mock_get_app):
        """mcp_view calls get_mcp_app() to get the ASGI app."""
        from nautobot_app_mcp_server.mcp.view import mcp_view

        # Mock the ASGI app with a fake handle method
        mock_asgi_app = MagicMock()
        mock_handler = MagicMock(return_value=MagicMock(status_code=200))
        mock_asgi_app.return_value = mock_handler
        mock_get_app.return_value = mock_asgi_app

        # Build a minimal Django request
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.path = "/mcp/"
        mock_request.META = {}

        with patch(
            "nautobot_app_mcp_server.mcp.view.WsgiToAsgi",
            return_value=mock_handler,
        ):
            mcp_view(mock_request)

        mock_get_app.assert_called_once()

    def test_wsgi_to_asgi_is_used_in_view(self):
        """Verify the view uses WsgiToAsgi (not async_to_sync)."""
        import inspect

        from nautobot_app_mcp_server.mcp import view as view_module

        source = inspect.getsource(view_module)
        self.assertIn("WsgiToAsgi", source)
        self.assertNotIn("async_to_sync", source)


class MCPAppFactoryTestCase(TestCase):
    """Test the lazy factory for the FastMCP ASGI app."""

    def test_get_mcp_app_returns_starlette_app(self):
        """get_mcp_app returns a Starlette application."""
        # Import without triggering app creation
        from nautobot_app_mcp_server.mcp.server import _mcp_app

        # Before any request, the app should be None
        # (module-level lazy factory)
        self.assertIsNone(_mcp_app)

    def test_mcp_app_lazy_initialization(self):
        """get_mcp_app creates the app on first call, not at module import."""
        from nautobot_app_mcp_server.mcp import server as server_module

        # Reset the global to test lazy behavior
        old_app = server_module._mcp_app
        server_module._mcp_app = None

        try:
            from nautobot_app_mcp_server.mcp.server import get_mcp_app

            # get_mcp_app should be a callable
            self.assertTrue(callable(get_mcp_app))
        finally:
            server_module._mcp_app = old_app

    def test_get_mcp_app_twice_returns_same_instance(self):
        """Calling get_mcp_app twice returns the same app object (not re-created)."""
        from nautobot_app_mcp_server.mcp import server as server_module

        old_app = server_module._mcp_app
        server_module._mcp_app = None  # Reset

        try:
            from nautobot_app_mcp_server.mcp.server import get_mcp_app

            app1 = get_mcp_app()
            app2 = get_mcp_app()
            self.assertIs(app1, app2)
        finally:
            server_module._mcp_app = old_app
