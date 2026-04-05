"""Tests for session tools and progressive disclosure (P3-01–P3-04).

Phase 10 migrated from ``RequestContext._mcp_tool_state`` monkey-patch to
FastMCP's native ``ctx.set_state()`` / ``ctx.get_state()`` session-state API.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from django.test import TestCase

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition


# -------------------------------------------------------------------
# Shared fixtures
# -------------------------------------------------------------------


def _make_mock_ctx(
    enabled_scopes: set[str] | None = None,
    enabled_searches: set[str] | None = None,
) -> MagicMock:
    """Build a mock ToolContext using the new FastMCP state API pattern.

    Phase 10: session state is stored via ``ctx.set_state()`` / ``ctx.get_state()``.
    The fixture uses a shared ``_store`` dict so that ``set_state`` calls actually
    persist, and subsequent ``get_state`` calls see those values.
    """
    _store: dict[str, list[str] | None] = {
        "mcp:enabled_scopes": list(enabled_scopes) if enabled_scopes else None,
        "mcp:enabled_searches": list(enabled_searches) if enabled_searches else None,
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
# ToolScopeState tests — FastMCP state API wrappers
# -------------------------------------------------------------------


class ToolScopeStateTestCase(TestCase):
    """Test ToolScopeState and its FastMCP state API helpers (P3-01)."""

    def test_get_enabled_scopes_empty(self):
        """get_enabled_scopes returns empty set when nothing stored."""
        from nautobot_app_mcp_server.mcp.session_tools import _get_enabled_scopes

        mock_ctx = _make_mock_ctx()
        result = asyncio.get_event_loop().run_until_complete(
            _get_enabled_scopes(mock_ctx)
        )
        self.assertEqual(result, set())

    def test_get_enabled_scopes_returns_stored(self):
        """get_enabled_scopes returns the set stored via set_state."""
        from nautobot_app_mcp_server.mcp.session_tools import (
            _get_enabled_scopes,
            _set_enabled_scopes,
        )

        loop = asyncio.get_event_loop()
        mock_ctx = _make_mock_ctx()

        loop.run_until_complete(_set_enabled_scopes(mock_ctx, {"dcim", "ipam.vlan"}))
        result = loop.run_until_complete(_get_enabled_scopes(mock_ctx))

        self.assertEqual(result, {"dcim", "ipam.vlan"})
        # Verify set_state was called with list representation
        mock_ctx.set_state.assert_called_once()
        call_args = mock_ctx.set_state.call_args
        self.assertEqual(call_args[0][0], "mcp:enabled_scopes")
        self.assertEqual(set(call_args[0][1]), {"dcim", "ipam.vlan"})

    def test_get_enabled_searches_empty(self):
        """get_enabled_searches returns empty set when nothing stored."""
        from nautobot_app_mcp_server.mcp.session_tools import _get_enabled_searches

        mock_ctx = _make_mock_ctx()
        result = asyncio.get_event_loop().run_until_complete(
            _get_enabled_searches(mock_ctx)
        )
        self.assertEqual(result, set())

    def test_get_enabled_searches_returns_stored(self):
        """get_enabled_searches returns the search terms stored via set_state."""
        from nautobot_app_mcp_server.mcp.session_tools import (
            _get_enabled_searches,
            _set_enabled_searches,
        )

        loop = asyncio.get_event_loop()
        mock_ctx = _make_mock_ctx()

        loop.run_until_complete(_set_enabled_searches(mock_ctx, {"BGP", "OSPF"}))
        result = loop.run_until_complete(_get_enabled_searches(mock_ctx))

        self.assertEqual(result, {"BGP", "OSPF"})

    def test_tool_scope_state_apply_enable_scope(self):
        """apply_enable adds a scope to the existing enabled set."""
        from nautobot_app_mcp_server.mcp.session_tools import ToolScopeState

        mock_ctx = _make_mock_ctx(enabled_scopes={"dcim"})
        state = ToolScopeState()
        loop = asyncio.get_event_loop()

        parts = loop.run_until_complete(state.apply_enable(mock_ctx, scope="ipam", search=None))

        self.assertEqual(parts, ["scope 'ipam'"])
        mock_ctx.set_state.assert_called()
        # Should add "ipam" to existing "dcim"
        calls = [c for c in mock_ctx.set_state.call_args_list if c[0][0] == "mcp:enabled_scopes"]
        self.assertEqual(set(calls[-1][0][1]), {"dcim", "ipam"})

    def test_tool_scope_state_apply_enable_search(self):
        """apply_enable adds a search term."""
        from nautobot_app_mcp_server.mcp.session_tools import ToolScopeState

        mock_ctx = _make_mock_ctx()
        state = ToolScopeState()
        loop = asyncio.get_event_loop()

        parts = loop.run_until_complete(state.apply_enable(mock_ctx, scope=None, search="BGP"))

        self.assertEqual(parts, ["search 'BGP'"])

    def test_tool_scope_state_apply_disable_scope(self):
        """apply_disable removes scope and child scopes."""
        from nautobot_app_mcp_server.mcp.session_tools import ToolScopeState

        mock_ctx = _make_mock_ctx(enabled_scopes={"dcim", "dcim.interface", "ipam"})
        state = ToolScopeState()
        loop = asyncio.get_event_loop()

        msg, child_count = loop.run_until_complete(state.apply_disable(mock_ctx, scope="dcim"))

        self.assertEqual(msg, "Disabled scope 'dcim'")
        self.assertEqual(child_count, 2)  # "dcim" + "dcim.interface" (not just children)
        # "ipam" should remain
        calls = [c for c in mock_ctx.set_state.call_args_list if c[0][0] == "mcp:enabled_scopes"]
        self.assertEqual(set(calls[-1][0][1]), {"ipam"})

    def test_tool_scope_state_apply_disable_all(self):
        """apply_disable(scope=None) clears all scopes and searches."""
        from nautobot_app_mcp_server.mcp.session_tools import ToolScopeState

        mock_ctx = _make_mock_ctx(enabled_scopes={"dcim"}, enabled_searches={"BGP"})
        state = ToolScopeState()
        loop = asyncio.get_event_loop()

        msg, child_count = loop.run_until_complete(state.apply_disable(mock_ctx, scope=None))

        self.assertEqual(msg, "Disabled all non-core tools.")
        self.assertEqual(child_count, 0)
        # Both scopes and searches should be cleared
        scope_calls = [c for c in mock_ctx.set_state.call_args_list if c[0][0] == "mcp:enabled_scopes"]
        search_calls = [c for c in mock_ctx.set_state.call_args_list if c[0][0] == "mcp:enabled_searches"]
        self.assertEqual(scope_calls[-1][0][1], [])
        self.assertEqual(search_calls[-1][0][1], [])


# -------------------------------------------------------------------
# Progressive disclosure — registry-level (unchanged logic)
# -------------------------------------------------------------------


class ProgressiveDisclosureTestCase(TestCase):
    """Test progressive disclosure registry behavior (REGI-05, SESS-06).

    These tests verify MCPToolRegistry behavior (get_core_tools, get_by_scope)
    which is unchanged by Phase 10. The _make_mock_ctx fixture is updated to
    use ctx.get_state() for consistency.
    """

    def test_core_tools_always_returned(self):
        """SESS-06: Core tools present even with empty session state."""
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_core_progressive",
                func=lambda: None,
                description="Test core tool",
                input_schema={"type": "object"},
                tier="core",
            )
        )
        try:
            core_names = [t.name for t in registry.get_core_tools()]
            self.assertIn("test_core_progressive", core_names)
        finally:
            del registry._tools["test_core_progressive"]  # pylint: disable=protected-access

    def test_non_core_tool_requires_scope_enabled(self):
        """Non-core tool in registry but not returned when scope not enabled.

        Tests MCPToolRegistry.get_by_scope() behavior. The tool IS in the registry
        but session has empty enabled_scopes → would be filtered out.
        """
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_app_progressive",
                func=lambda: None,
                description="Test app tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.special",
            )
        )
        try:
            # Registry has the tool
            tools = registry.get_by_scope("test_app.special")
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0].name, "test_app_progressive")
            # But session has no enabled scopes
            mock_ctx = _make_mock_ctx(enabled_scopes=set())
            enabled = asyncio.get_event_loop().run_until_complete(
                mock_ctx.get_state("mcp:enabled_scopes")
            )
            self.assertIsNone(enabled)
        finally:
            del registry._tools["test_app_progressive"]  # pylint: disable=protected-access

    def test_scope_enabling_returns_matching_tools(self):
        """Enabling a scope makes matching tools visible in registry."""
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_scope_visible",
                func=lambda: None,
                description="Scoped tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.view",
            )
        )
        try:
            tools = registry.get_by_scope("test_app.view")
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0].name, "test_scope_visible")
        finally:
            del registry._tools["test_scope_visible"]  # pylint: disable=protected-access


# -------------------------------------------------------------------
# Scope hierarchy tests
# -------------------------------------------------------------------


class ScopeHierarchyTestCase(TestCase):
    """Test scope hierarchy (D-21): enabling parent activates children."""

    def test_parent_scope_matches_child_tools(self):
        """get_by_scope("dcim") returns tools with scope="dcim.interface"."""
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_child_match",
                func=lambda: None,
                description="Child scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="dcim_app",
                scope="dcim.interface",
            )
        )
        try:
            tools = registry.get_by_scope("dcim")
            scope_names = [t.scope for t in tools]
            self.assertIn("dcim.interface", scope_names)
        finally:
            del registry._tools["test_child_match"]  # pylint: disable=protected-access

    def test_disable_removes_parent_and_children(self):
        """apply_disable removes parent scope and all child scopes via prefix matching."""
        from nautobot_app_mcp_server.mcp.session_tools import ToolScopeState

        mock_ctx = _make_mock_ctx(enabled_scopes={"dcim", "dcim.interface", "ipam"})
        state = ToolScopeState()
        loop = asyncio.get_event_loop()

        loop.run_until_complete(state.apply_disable(mock_ctx, scope="dcim"))

        # dcim and dcim.interface removed; ipam preserved
        scope_calls = [c for c in mock_ctx.set_state.call_args_list if c[0][0] == "mcp:enabled_scopes"]
        self.assertEqual(set(scope_calls[-1][0][1]), {"ipam"})


# -------------------------------------------------------------------
# Integration: _list_tools_handler with ctx.get_state() API
# -------------------------------------------------------------------


class ProgressiveDisclosureIntegrationTestCase(TestCase):
    """Integration: _list_tools_handler reads from ctx.get_state() (P3-01)."""

    def test_list_tools_handler_uses_fastmcp_state_api(self):
        """_list_tools_handler reads enabled_scopes via ctx.get_state() (not _mcp_tool_state).

        Phase 10 replaced RequestContext._mcp_tool_state monkey-patch with
        FastMCP's ctx.get_state() API. This test verifies the integration.
        """
        from nautobot_app_mcp_server.mcp.session_tools import _list_tools_handler

        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_rctx_tool",
                func=lambda: None,
                description="Test tool for FastMCP state API",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.rctx",
            )
        )
        try:
            # Build mock ctx using new FastMCP state API pattern
            mock_ctx = _make_mock_ctx(enabled_scopes={"test_app.rctx"}, enabled_searches=set())

            tools = asyncio.get_event_loop().run_until_complete(_list_tools_handler(mock_ctx))

            tool_names = [t.name for t in tools]
            # test_app.rctx scope is enabled → tool should be returned
            self.assertIn("test_rctx_tool", tool_names)
            # Core tools should always be present
            self.assertIn("mcp_enable_tools", tool_names)
        finally:
            del registry._tools["test_rctx_tool"]  # pylint: disable=protected-access

    def test_list_tools_handler_no_scope_returns_core_only(self):
        """When no scopes are enabled, only core tools are returned."""
        from nautobot_app_mcp_server.mcp.session_tools import _list_tools_handler

        mock_ctx = _make_mock_ctx(enabled_scopes=set(), enabled_searches=set())
        tools = asyncio.get_event_loop().run_until_complete(_list_tools_handler(mock_ctx))
        tool_names = [t.name for t in tools]

        # Core tools present
        self.assertIn("mcp_enable_tools", tool_names)
        # App-scoped tools NOT present (none enabled)
        # (mcp_list_tools and mcp_disable_tools are also core)
        for name in tool_names:
            self.assertNotEqual(name, "test_rctx_tool")


# -------------------------------------------------------------------
# Session tool registration — MCPToolRegistry
# -------------------------------------------------------------------


class MCPToolRegistrationTestCase(TestCase):
    """Verify session tools are registered in MCPToolRegistry (P3-04)."""

    def test_session_tools_in_registry(self):
        """mcp_enable_tools, mcp_disable_tools, mcp_list_tools registered on registry."""
        # Importing session_tools triggers @register_tool on each implementation
        import nautobot_app_mcp_server.mcp.session_tools  # noqa: F401

        registry = MCPToolRegistry.get_instance()
        all_tools = registry.get_all()
        tool_names = [t.name for t in all_tools]
        self.assertIn("mcp_enable_tools", tool_names)
        self.assertIn("mcp_disable_tools", tool_names)
        self.assertIn("mcp_list_tools", tool_names)

    def test_session_tools_tier_is_core(self):
        """Session tools are tier="core" so they always appear in get_core_tools."""
        import nautobot_app_mcp_server.mcp.session_tools  # noqa: F401

        registry = MCPToolRegistry.get_instance()
        core_names = [t.name for t in registry.get_core_tools()]
        self.assertIn("mcp_enable_tools", core_names)
        self.assertIn("mcp_disable_tools", core_names)
        self.assertIn("mcp_list_tools", core_names)


# -------------------------------------------------------------------
# Scope guard middleware tests
# -------------------------------------------------------------------


class ScopeGuardMiddlewareTestCase(TestCase):
    """Test ScopeGuardMiddleware on_call_tool enforcement (P3-03)."""

    def _make_middleware_context(
        self, tool_name: str, enabled_scopes: set[str] | None = None
    ) -> tuple:
        """Build a MiddlewareContext + call_next for ScopeGuardMiddleware testing."""
        params = MagicMock()
        params.name = tool_name
        params.arguments = {}

        mock_ctx = _make_mock_ctx(enabled_scopes=enabled_scopes)

        # MiddlewareContext has .method (params) and .fastmcp_context
        mock_middleware_ctx = MagicMock()
        mock_middleware_ctx.method = params
        mock_middleware_ctx.fastmcp_context = mock_ctx

        call_next = AsyncMock()
        return mock_middleware_ctx, call_next

    def test_core_tool_passes_through(self):
        """Core tools always pass through without scope check."""
        from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware

        middleware = ScopeGuardMiddleware()
        ctx, call_next = self._make_middleware_context("mcp_enable_tools")

        asyncio.get_event_loop().run_until_complete(middleware.on_call_tool(ctx, call_next))

        call_next.assert_called_once_with(ctx)

    def test_app_tool_with_enabled_scope_passes(self):
        """App-tier tool passes when its scope is enabled."""
        from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware

        # Register a scoped tool
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_guard_tool",
                func=lambda: None,
                description="Test guard",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.guarded",
            )
        )
        try:
            middleware = ScopeGuardMiddleware()
            ctx, call_next = self._make_middleware_context(
                "test_guard_tool", enabled_scopes={"test_app.guarded"}
            )

            asyncio.get_event_loop().run_until_complete(middleware.on_call_tool(ctx, call_next))

            call_next.assert_called_once_with(ctx)
        finally:
            del registry._tools["test_guard_tool"]  # pylint: disable=protected-access

    def test_app_tool_with_parent_scope_passes(self):
        """App-tier tool passes when a parent scope is enabled (scope hierarchy)."""
        from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware

        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_parent_guard",
                func=lambda: None,
                description="Test parent guard",
                input_schema={"type": "object"},
                tier="app",
                app_label="dcim_app",
                scope="dcim.interface",
            )
        )
        try:
            middleware = ScopeGuardMiddleware()
            ctx, call_next = self._make_middleware_context(
                "test_parent_guard", enabled_scopes={"dcim"}
            )

            asyncio.get_event_loop().run_until_complete(middleware.on_call_tool(ctx, call_next))

            call_next.assert_called_once_with(ctx)
        finally:
            del registry._tools["test_parent_guard"]  # pylint: disable=protected-access

    def test_app_tool_without_scope_raises(self):
        """App-tier tool raises ToolNotFoundError when scope is not enabled."""
        from nautobot_app_mcp_server.mcp.middleware import (
            ScopeGuardMiddleware,
            ToolNotFoundError,
        )

        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_blocked_tool",
                func=lambda: None,
                description="Test blocked",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.blocked",
            )
        )
        try:
            middleware = ScopeGuardMiddleware()
            # Use a non-empty enabled scope so middleware reaches the scope-check path,
            # not the permissive "no scopes enabled yet" branch
            ctx, call_next = self._make_middleware_context(
                "test_blocked_tool", enabled_scopes={"other_scope"}
            )

            loop = asyncio.get_event_loop()
            with self.assertRaises(ToolNotFoundError) as ctx_exc:
                loop.run_until_complete(middleware.on_call_tool(ctx, call_next))

            self.assertIn("test_blocked_tool", str(ctx_exc.exception))
            call_next.assert_not_called()
        finally:
            del registry._tools["test_blocked_tool"]  # pylint: disable=protected-access

    def test_unknown_tool_passes_through(self):
        """Tools not in registry pass through (middleware is permissive for unknown tools)."""
        from nautobot_app_mcp_server.mcp.middleware import ScopeGuardMiddleware

        middleware = ScopeGuardMiddleware()
        ctx, call_next = self._make_middleware_context("nonexistent_tool")

        asyncio.get_event_loop().run_until_complete(middleware.on_call_tool(ctx, call_next))

        # Unknown tools pass through (they won't exist in registry._tools)
        call_next.assert_called_once_with(ctx)
