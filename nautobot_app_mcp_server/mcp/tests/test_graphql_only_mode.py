"""Tests for GraphQL-only mode (GQLONLY-01 through GQLONLY-05).

Phase 18 adds NAUTOBOT_MCP_ENABLE_ALL env var that switches between GQL-only mode (default, 2 tools)
and all-tools mode (15 tools). Tests cover:
- GQLONLY-01: Env var switches GQL-only mode on/off
- GQLONLY-02: _list_tools_handler returns only 2 tools in GQL-only mode (default)
- GQLONLY-03: ScopeGuardMiddleware blocks non-GraphQL tools in GQL-only mode
- GQLONLY-04: Default (no NAUTOBOT_MCP_ENABLE_ALL) is GQL-only mode (GRAPHQL_ONLY_MODE=True)
- GQLONLY-05: Unit tests cover manifest filtering, call-time blocking, default-on
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

# Side-effect imports: register tools before tests
import nautobot_app_mcp_server.mcp.session_tools  # noqa: F401
from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware
from nautobot_app_mcp_server.mcp.middleware import ToolNotFoundError  # noqa: F401
from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry


# -------------------------------------------------------------------
# Shared fixtures
# -------------------------------------------------------------------


def _make_mock_ctx(
    enabled_scopes: set[str] | None = None,
    enabled_searches: set[str] | None = None,
) -> MagicMock:
    """Build a mock ToolContext using the FastMCP state API pattern."""
    _store: dict[str, list[str] | None] = {
        "mcp:enabled_scopes": list(enabled_scopes) if enabled_scopes is not None else None,
        "mcp:enabled_searches": list(enabled_searches) if enabled_searches is not None else None,
    }

    async def mock_set_state(key: str, value: list[str]) -> None:
        _store[key] = value

    async def mock_get_state(key: str):
        return _store.get(key)

    mock_ctx = MagicMock()
    mock_ctx.get_state = AsyncMock(side_effect=mock_get_state)
    mock_ctx.set_state = AsyncMock(side_effect=mock_set_state)
    return mock_ctx


# -------------------------------------------------------------------
# GQLOnlyModeTestCase
# -------------------------------------------------------------------


class GQLOnlyModeTestCase(TestCase):
    """Test GQL-only mode manifest filtering and call blocking."""

    # ~~~~~~~~~~~~~~~~~~~~~
    # GQLONLY-01: Env var read
    # ~~~~~~~~~~~~~~~~~~~~~

    def test_graphql_only_mode_default_is_true(self):
        """GQLONLY-01: GRAPHQL_ONLY_MODE defaults to True (GQL-only mode on by default)."""
        from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE

        self.assertTrue(GRAPHQL_ONLY_MODE)

    def test_env_var_enable_all_true_disables_gql_only(self):
        """GQLONLY-01: NAUTOBOT_MCP_ENABLE_ALL=true disables GQL-only mode."""
        with patch.dict(os.environ, {"NAUTOBOT_MCP_ENABLE_ALL": "true"}):
            import importlib
            import nautobot_app_mcp_server.mcp.commands as cmd_module
            importlib.reload(cmd_module)

            self.assertFalse(cmd_module.GRAPHQL_ONLY_MODE)

        import importlib
        import nautobot_app_mcp_server.mcp.commands as cmd_module
        importlib.reload(cmd_module)

    # ~~~~~~~~~~~~~~~~~~~~~
    # GQLONLY-04: Default-on
    # ~~~~~~~~~~~~~~~~~~~~~

    def test_default_mode_no_env_var_gql_only_active(self):
        """GQLONLY-04: Without NAUTOBOT_MCP_ENABLE_ALL, GQL-only mode is active."""
        from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE

        self.assertTrue(GRAPHQL_ONLY_MODE)

    # ~~~~~~~~~~~~~~~~~~~~~
    # GQLONLY-02: Manifest filtering
    # ~~~~~~~~~~~~~~~~~~~~~

    def test_list_tools_handler_gql_only_mode_returns_2_tools(self):
        """GQLONLY-02: _list_tools_handler returns exactly 2 tools in GQL-only mode (default)."""
        from nautobot_app_mcp_server.mcp.session_tools import _list_tools_handler

        mock_ctx = _make_mock_ctx()
        tools = asyncio.get_event_loop().run_until_complete(_list_tools_handler(mock_ctx))
        tool_names = [t.name for t in tools]

        self.assertEqual(len(tools), 2, f"Expected 2 tools, got {len(tools)}: {tool_names}")
        self.assertIn("graphql_query", tool_names)
        self.assertIn("graphql_introspect", tool_names)
        self.assertNotIn("mcp_enable_tools", tool_names)
        self.assertNotIn("mcp_disable_tools", tool_names)
        self.assertNotIn("mcp_list_tools", tool_names)

    def test_list_tools_handler_filter_logic_inspection(self):
        """GQLONLY-02: _list_tools_handler has correct filtering logic for all-tools mode."""
        from nautobot_app_mcp_server.mcp import session_tools as st_module

        source = inspect.getsource(st_module._list_tools_handler)
        self.assertIn("_ALLOWED_GQL_ONLY_TOOLS", source)
        self.assertIn("if GRAPHQL_ONLY_MODE:", source)

    # ~~~~~~~~~~~~~~~~~~~~~
    # GQLONLY-03: Call blocking
    # ~~~~~~~~~~~~~~~~~~~~~

    def _make_middleware_context(self, tool_name: str) -> tuple:
        """Build MiddlewareContext + call_next for ScopeGuardMiddleware testing."""
        params = MagicMock()
        params.name = tool_name
        params.arguments = {}

        mock_ctx = _make_mock_ctx()

        mock_middleware_ctx = MagicMock()
        mock_middleware_ctx.message = params
        mock_middleware_ctx.fastmcp_context = mock_ctx

        call_next = AsyncMock()
        return mock_middleware_ctx, call_next

    def test_middleware_blocks_non_graphql_tools(self):
        """GQLONLY-03: ScopeGuardMiddleware blocks non-GraphQL tools in GQL-only mode."""
        import nautobot_app_mcp_server.mcp.middleware as mw_module

        middleware = mw_module.ScopeGuardMiddleware()
        ctx, call_next = self._make_middleware_context("device_list")

        loop = asyncio.get_event_loop()
        exception_raised = False
        exc_info = None
        try:
            loop.run_until_complete(middleware.on_call_tool(ctx, call_next))
        except Exception:  # noqa: BLE001
            exception_raised = True
            exc_info = sys.exc_info()

        self.assertTrue(exception_raised, "Expected exception was not raised")
        exc = exc_info[1]
        self.assertIn("device_list", str(exc))
        self.assertIn("not available in GraphQL-only mode", str(exc))
        call_next.assert_not_called()

    def test_middleware_allows_graphql_query(self):
        """GQLONLY-03: graphql_query passes through in GQL-only mode."""
        import nautobot_app_mcp_server.mcp.middleware as mw_module

        middleware = mw_module.ScopeGuardMiddleware()
        ctx, call_next = self._make_middleware_context("graphql_query")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(middleware.on_call_tool(ctx, call_next))

        call_next.assert_called_once_with(ctx)

    def test_middleware_allows_graphql_introspect(self):
        """GQLONLY-03: graphql_introspect passes through in GQL-only mode."""
        import nautobot_app_mcp_server.mcp.middleware as mw_module

        middleware = mw_module.ScopeGuardMiddleware()
        ctx, call_next = self._make_middleware_context("graphql_introspect")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(middleware.on_call_tool(ctx, call_next))

        call_next.assert_called_once_with(ctx)

    def test_middleware_blocks_session_tools_in_gql_only_mode(self):
        """GQLONLY-03: Session tools raise ToolNotFoundError in GQL-only mode."""
        import nautobot_app_mcp_server.mcp.middleware as mw_module

        middleware = mw_module.ScopeGuardMiddleware()

        for tool_name in ("mcp_enable_tools", "mcp_disable_tools", "mcp_list_tools"):
            ctx, call_next = self._make_middleware_context(tool_name)
            loop = asyncio.get_event_loop()
            exception_raised = False
            exc_info = None
            try:
                loop.run_until_complete(middleware.on_call_tool(ctx, call_next))
            except Exception:  # noqa: BLE001
                exception_raised = True
                exc_info = sys.exc_info()

            self.assertTrue(exception_raised, f"Expected exception for {tool_name}")
            self.assertIn("not available in GraphQL-only mode", str(exc_info[1]))
            call_next.assert_not_called()

    def test_middleware_allows_core_tools_when_gql_only_disabled(self):
        """GQLONLY-03: Core tools pass through when NAUTOBOT_MCP_ENABLE_ALL=true."""
        import nautobot_app_mcp_server.mcp.commands as cmd_module

        with patch.object(cmd_module, "GRAPHQL_ONLY_MODE", False):
            import importlib
            import nautobot_app_mcp_server.mcp.middleware as mw_module
            importlib.reload(mw_module)

            middleware = mw_module.ScopeGuardMiddleware()
            ctx, call_next = self._make_middleware_context("mcp_enable_tools")

            loop = asyncio.get_event_loop()
            loop.run_until_complete(middleware.on_call_tool(ctx, call_next))

            call_next.assert_called_once_with(ctx)

        import importlib
        import nautobot_app_mcp_server.mcp.middleware as mw_module
        importlib.reload(mw_module)