"""Tests for MCPToolRegistry and tool registration API.

Phase 9 replaced post_migrate signal wiring with ready() writing tool_registry.json.
See NautobotAppMcpServerConfig.ready() in the package __init__.py.
"""

from __future__ import annotations

from django.test import TestCase

from nautobot_app_mcp_server.mcp import register_mcp_tool
from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition


class RegistrySingletonTestCase(TestCase):
    """Test the MCPToolRegistry singleton thread-safety."""

    def setUp(self) -> None:
        """Snapshot registry state before each test."""
        self._snapshot = dict(MCPToolRegistry._tools)

    def tearDown(self) -> None:
        """Restore registry state after each test."""
        MCPToolRegistry._tools.clear()
        MCPToolRegistry._tools.update(self._snapshot)

    def test_singleton_returns_same_instance(self):
        """Two calls to get_instance() return the same object."""
        r1 = MCPToolRegistry.get_instance()
        r2 = MCPToolRegistry.get_instance()
        self.assertIs(r1, r2)

    def test_singleton_has_lock(self):
        """The registry has a threading.Lock for thread-safety."""
        self.assertTrue(hasattr(MCPToolRegistry, "_lock"))
        lock = MCPToolRegistry._lock
        # threading.Lock() creates _thread.lock instances; verify by calling acquire
        self.assertTrue(callable(lock.acquire))
        self.assertTrue(callable(lock.release))

    def test_register_raises_on_duplicate_name(self):
        """Registered two tools with the same name raises ValueError."""
        registry = MCPToolRegistry.get_instance()

        def dummy_func():
            pass

        registry.register(
            ToolDefinition(
                name="test_duplicate",
                func=dummy_func,
                description="First registration",
                input_schema={"type": "object"},
            )
        )
        with self.assertRaises(ValueError) as ctx:
            registry.register(
                ToolDefinition(
                    name="test_duplicate",
                    func=dummy_func,
                    description="Second registration",
                    input_schema={"type": "object"},
                )
            )
        self.assertIn("test_duplicate", str(ctx.exception))

    def test_get_core_tools_returns_only_core_tier(self):
        """get_core_tools() returns only tools with tier == 'core'."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_core_tool",
                func=lambda: None,
                description="A core tool",
                input_schema={"type": "object"},
                tier="core",
            )
        )
        registry.register(
            ToolDefinition(
                name="test_app_tool",
                func=lambda: None,
                description="An app tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.read",
            )
        )

        core_tools = registry.get_core_tools()
        core_names = [t.name for t in core_tools]
        self.assertIn("test_core_tool", core_names)
        self.assertNotIn("test_app_tool", core_names)

    def test_get_by_scope_exact_match(self):
        """get_by_scope() returns tools with exact scope match."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_exact_scope",
                func=lambda: None,
                description="Exact scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.juniper",
            )
        )

        tools = registry.get_by_scope("test_app.juniper")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "test_exact_scope")

    def test_get_by_scope_child_match(self):
        """get_by_scope() returns tools with child scopes."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_child_scope",
                func=lambda: None,
                description="Child scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.juniper.bgp",
            )
        )

        # Parent scope should match child scopes
        tools = registry.get_by_scope("test_app.juniper")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "test_child_scope")

    def test_fuzzy_search_matches_name(self):
        """fuzzy_search() matches tool names (case-insensitive)."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="qwerty_asdf_12345_tool",
                func=lambda: None,
                description="A tool with a unique name",
                input_schema={"type": "object"},
                tier="core",
            )
        )

        results = registry.fuzzy_search("QWERTY_ASDF_12345")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "qwerty_asdf_12345_tool")

    def test_fuzzy_search_matches_description(self):
        """fuzzy_search() matches tool descriptions (case-insensitive)."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="unique_zxcv_987_tool",
                func=lambda: None,
                description="A unique description term zxcv_unique_term_987",
                input_schema={"type": "object"},
                tier="core",
            )
        )

        results = registry.fuzzy_search("ZXCV_UNIQUE_TERM_987")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "unique_zxcv_987_tool")

    def test_fuzzy_search_no_match(self):
        """fuzzy_search() returns empty list when no match."""
        registry = MCPToolRegistry.get_instance()
        results = registry.fuzzy_search("nonexistent_tool_xyz")
        self.assertEqual(results, [])


class RegisterMCPToolAPITestCase(TestCase):
    """Test the public register_mcp_tool() API."""

    def setUp(self) -> None:
        """Snapshot registry state before each test."""
        self._snapshot = dict(MCPToolRegistry._tools)

    def tearDown(self) -> None:
        """Restore registry state after each test."""
        MCPToolRegistry._tools.clear()
        MCPToolRegistry._tools.update(self._snapshot)

    def test_register_mcp_tool_works(self):
        """register_mcp_tool() successfully registers a tool."""

        def dummy_func():
            pass

        register_mcp_tool(
            name="test_api_tool",
            func=dummy_func,
            description="Test tool from API",
            input_schema={"type": "object"},
            tier="app",
            app_label="test_app",
            scope="test_app.read",
        )

        registry = MCPToolRegistry.get_instance()
        tools = registry.get_all()
        names = [t.name for t in tools]
        self.assertIn("test_api_tool", names)

    def test_register_mcp_tool_default_tier_is_app(self):
        """register_mcp_tool() defaults tier to 'app'."""

        def dummy_func():
            pass

        register_mcp_tool(
            name="test_default_tier",
            func=dummy_func,
            description="Test default tier",
            input_schema={"type": "object"},
        )

        registry = MCPToolRegistry.get_instance()
        tools = registry.get_all()
        tool = next(t for t in tools if t.name == "test_default_tier")
        self.assertEqual(tool.tier, "app")


# post_migrate signal tests removed.
# post_migrate never fires in the MCP server process (Phase 8 runs django.setup()
# directly, not nautobot-server). Phase 9 replaced it with ready() writing
# tool_registry.json — see NautobotAppMcpServerConfig.ready() in __init__.py.
