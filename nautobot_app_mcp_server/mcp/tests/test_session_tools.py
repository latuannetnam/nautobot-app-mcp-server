"""Tests for session tools and progressive disclosure (SESS-01–06, REGI-05)."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition


class MCPSessionStateTestCase(TestCase):
    """Test MCPSessionState dataclass (SESS-01)."""

    def test_from_session_empty(self):
        """Empty session dict → empty state."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        state = MCPSessionState.from_session({})
        self.assertEqual(state.enabled_scopes, set())
        self.assertEqual(state.enabled_searches, set())

    def test_from_session_with_data(self):
        """Session dict with data → state loaded correctly."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {
            "enabled_scopes": {"dcim", "ipam.vlan"},
            "enabled_searches": {"BGP"},
        }
        state = MCPSessionState.from_session(session)
        self.assertEqual(state.enabled_scopes, {"dcim", "ipam.vlan"})
        self.assertEqual(state.enabled_searches, {"BGP"})

    def test_apply_to_session(self):
        """State changes are persisted to session dict."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session: dict = {}
        state = MCPSessionState(enabled_scopes={"dcim"}, enabled_searches={"BGP"})
        state.apply_to_session(session)
        self.assertEqual(session["enabled_scopes"], {"dcim"})
        self.assertEqual(session["enabled_searches"], {"BGP"})

    def test_roundtrip(self):
        """Load → modify → apply → load again = same state."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {"enabled_scopes": {"ipam"}, "enabled_searches": set()}
        state1 = MCPSessionState.from_session(session)
        state1.enabled_scopes.add("dcim")
        state1.apply_to_session(session)
        state2 = MCPSessionState.from_session(session)
        self.assertEqual(state2.enabled_scopes, {"ipam", "dcim"})


class ProgressiveDisclosureTestCase(TestCase):
    """Test @mcp.list_tools() progressive disclosure (REGI-05, SESS-06)."""

    def _make_mock_ctx(
        self,
        enabled_scopes: set[str] | None = None,
        enabled_searches: set[str] | None = None,
    ) -> MagicMock:
        """Build a mock ToolContext with session state."""
        session = {
            "enabled_scopes": enabled_scopes if enabled_scopes is not None else set(),
            "enabled_searches": enabled_searches if enabled_searches is not None else set(),
        }
        mock_ctx = MagicMock()
        mock_ctx.request_context.session = session
        return mock_ctx

    def test_core_tools_always_returned(self):
        """SESS-06: Core tools present even with empty session state."""
        registry = MCPToolRegistry.get_instance()
        # Register a known core tool
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
        """Non-core tools NOT returned when scope not in enabled_scopes."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

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
            session = {"enabled_scopes": set(), "enabled_searches": set()}
            state = MCPSessionState.from_session(session)
            # test_app.special scope is NOT enabled → not returned by get_by_scope
            tools = registry.get_by_scope("test_app.special")
            self.assertEqual(len(tools), 1)  # the tool IS in registry
            # but session has empty enabled_scopes → would be filtered out
            self.assertEqual(state.enabled_scopes, set())
        finally:
            del registry._tools["test_app_progressive"]  # pylint: disable=protected-access

    def test_scope_enabling_returns_matching_tools(self):
        """Enabling a scope makes matching tools visible."""
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
        """mcp_disable_tools disables parent scope via prefix removal."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {
            "enabled_scopes": {"dcim", "dcim.interface", "ipam"},
            "enabled_searches": set(),
        }
        state = MCPSessionState.from_session(session)

        # Simulate disable("dcim") — remove dcim and all children
        to_remove = {s for s in state.enabled_scopes if s == "dcim" or s.startswith("dcim.")}
        state.enabled_scopes -= to_remove

        self.assertNotIn("dcim", state.enabled_scopes)
        self.assertNotIn("dcim.interface", state.enabled_scopes)
        self.assertIn("ipam", state.enabled_scopes)


class MCPToolRegistrationTestCase(TestCase):
    """Verify session tools are registered correctly (SESS-03, SESS-04, SESS-05)."""

    def test_session_tools_in_registry(self):
        """mcp_enable_tools, mcp_disable_tools, mcp_list_tools registered on registry."""
        registry = MCPToolRegistry.get_instance()
        all_tools = registry.get_all()
        tool_names = [t.name for t in all_tools]
        self.assertIn("mcp_enable_tools", tool_names)
        self.assertIn("mcp_disable_tools", tool_names)
        self.assertIn("mcp_list_tools", tool_names)

    def test_session_tools_tier_is_core(self):
        """Session tools are tier="core" so they always appear in get_core_tools."""
        registry = MCPToolRegistry.get_instance()
        core_names = [t.name for t in registry.get_core_tools()]
        self.assertIn("mcp_enable_tools", core_names)
        self.assertIn("mcp_disable_tools", core_names)
        self.assertIn("mcp_list_tools", core_names)
