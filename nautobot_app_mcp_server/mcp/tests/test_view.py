"""Tests for the MCP HTTP endpoint — ASGI bridge and endpoint reachability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


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

    def test_async_to_sync_is_used_in_view(self):
        """REFA-01: Verify the view uses async_to_sync (not asyncio.run or WsgiToAsgi)."""
        import inspect

        from nautobot_app_mcp_server.mcp import view as view_module

        source = inspect.getsource(view_module)
        self.assertIn("async_to_sync", source)
        self.assertNotIn("import asyncio", source)  # asyncio.run is the broken pattern
        self.assertNotIn("WsgiToAsgi", source)  # old pattern replaced
        self.assertIn("session_manager.run()", source)  # REFA-02

    @override_settings(
        PLUGINS=["nautobot_app_mcp_server"],
        ROOT_URLCONF="nautobot_app_mcp_server.urls",
    )
    @patch("nautobot_app_mcp_server.mcp.view.get_session_manager")
    def test_view_calls_get_session_manager(self, mock_get_mgr):
        """REFA-04: mcp_view calls get_session_manager() (not get_mcp_app())."""
        from nautobot_app_mcp_server.mcp.view import mcp_view

        mock_manager = MagicMock()
        mock_get_mgr.return_value = mock_manager

        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.path = "/plugins/nautobot-app-mcp-server/mcp/"
        mock_request.META = {"QUERY_STRING": ""}
        mock_request.body = b""
        mock_request.get_host.return_value = "localhost"
        mock_request.get_port.return_value = "8080"
        mock_request.is_secure.return_value = False
        mock_request.headers = {}

        # Mock async_to_sync to return a fake HttpResponse
        with patch(
            "nautobot_app_mcp_server.mcp.view.async_to_sync",
            return_value=MagicMock(status=200, content=b"{}"),
        ):
            mcp_view(mock_request)

        mock_get_mgr.assert_called_once()


class MCPAppFactoryTestCase(TestCase):
    """Test the lazy factory for the FastMCP ASGI app."""

    def setUp(self) -> None:
        """Reset _mcp_app before each test."""
        # pylint: disable=protected-access
        from nautobot_app_mcp_server.mcp import server as server_module

        self._old_app = server_module._mcp_app
        self._old_instance = server_module._mcp_instance
        server_module._mcp_app = None
        server_module._mcp_instance = None

    def tearDown(self) -> None:
        """Restore _mcp_app after each test."""
        # pylint: disable=protected-access
        from nautobot_app_mcp_server.mcp import server as server_module

        server_module._mcp_app = self._old_app
        server_module._mcp_instance = self._old_instance

    def test_get_mcp_app_returns_starlette_app(self):
        """get_mcp_app returns a Starlette application."""
        # Import without triggering app creation
        from nautobot_app_mcp_server.mcp.server import _mcp_app

        # Before any request, the app should be None
        # (module-level lazy factory)
        self.assertIsNone(_mcp_app)

    def test_mcp_app_lazy_initialization(self):
        """get_mcp_app creates the app on first call, not at module import."""
        # _mcp_app already reset to None by setUp
        from nautobot_app_mcp_server.mcp.server import get_mcp_app

        # get_mcp_app should be a callable
        self.assertTrue(callable(get_mcp_app))

    def test_get_mcp_app_twice_returns_same_instance(self):
        """Calling get_mcp_app twice returns the same app object (not re-created)."""
        # _mcp_app already reset to None by setUp
        # Patch http_app to avoid real HTTP setup during tests
        with patch(
            "nautobot_app_mcp_server.mcp.server.FastMCP.http_app",
            return_value=MagicMock(),
        ):
            from nautobot_app_mcp_server.mcp.server import get_mcp_app

            app1 = get_mcp_app()
            app2 = get_mcp_app()
            self.assertIs(app1, app2)


class SessionManagerTestCase(TestCase):
    """Test get_session_manager() singleton and type."""

    def setUp(self) -> None:
        """Reset _mcp_instance before each test."""
        # pylint: disable=protected-access
        from nautobot_app_mcp_server.mcp import server as server_module

        self._old_instance = server_module._mcp_instance
        server_module._mcp_instance = None

    def tearDown(self) -> None:
        """Restore _mcp_instance after each test."""
        # pylint: disable=protected-access
        from nautobot_app_mcp_server.mcp import server as server_module

        server_module._mcp_instance = self._old_instance

    def test_get_session_manager_returns_fresh_instance(self):
        """REFA-04: get_session_manager() returns a fresh manager per call (factory, not singleton)."""
        # Each call creates a new StreamableHTTPSessionManager instance
        with patch(
            "nautobot_app_mcp_server.mcp.server.FastMCP.http_app",
            return_value=MagicMock(),
        ):
            from nautobot_app_mcp_server.mcp.server import get_session_manager

            mgr1 = get_session_manager()
            mgr2 = get_session_manager()
            self.assertIsNot(mgr1, mgr2)  # Fresh instances — factory pattern

    def test_session_manager_type(self):
        """REFA-04: get_session_manager() returns a StreamableHTTPSessionManager instance."""
        # Patch FastMCP and http_app to avoid real initialization
        with patch(
            "nautobot_app_mcp_server.mcp.server.FastMCP.http_app",
            return_value=MagicMock(),
        ):
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

            from nautobot_app_mcp_server.mcp.server import get_session_manager

            mgr = get_session_manager()
            self.assertIsInstance(mgr, StreamableHTTPSessionManager)
