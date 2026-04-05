"""Unit tests for @register_tool decorator and register_all_tools_with_mcp()."""

from __future__ import annotations

from unittest.mock import MagicMock

from django.test import TestCase

from nautobot_app_mcp_server.mcp import (
    MCPToolRegistry,
    register_all_tools_with_mcp,
    register_mcp_tool,
    register_tool,
)
from nautobot_app_mcp_server.mcp.schema import func_signature_to_input_schema

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


class _FakeToolDefinition:
    """Lightweight stand-in for ToolDefinition to avoid importing it in tests."""

    def __init__(self, name, func, description, input_schema, tier, app_label, scope):
        self.name = name
        self.func = func
        self.description = description
        self.input_schema = input_schema
        self.tier = tier
        self.app_label = app_label
        self.scope = scope


# -------------------------------------------------------------------
# func_signature_to_input_schema tests
# -------------------------------------------------------------------


class TestFuncSignatureToInputSchema(TestCase):
    """Tests for func_signature_to_input_schema()."""

    def test_func_signature_to_input_schema_simple(self):
        """Auto-generates input_schema for a simple function with typed params."""

        async def my_handler(ctx, limit: int = 10, cursor: str | None = None):
            pass  # noqa: ARG001

        schema = func_signature_to_input_schema(my_handler)
        self.assertEqual(schema["type"], "object")
        self.assertIn("limit", schema["properties"])
        self.assertEqual(schema["properties"]["limit"]["type"], "integer")
        self.assertEqual(schema["properties"]["limit"]["default"], 10)
        self.assertIn("cursor", schema["properties"])
        self.assertEqual(schema["properties"]["cursor"]["type"], "string")
        self.assertEqual(schema["properties"]["cursor"]["default"], None)
        self.assertNotIn("ctx", schema["properties"])
        self.assertNotIn("limit", schema["required"])

    def test_func_signature_to_input_schema_required_param(self):
        """Required params (no default) appear in 'required' list."""
        async def my_handler(ctx, query: str):
            pass  # noqa: ARG001

        schema = func_signature_to_input_schema(my_handler)
        self.assertIn("query", schema["required"])
        self.assertIn("query", schema["properties"])
        self.assertEqual(schema["properties"]["query"]["type"], "string")

    def test_func_signature_to_input_schema_skips_ctx(self):
        """ToolContext param 'ctx' is excluded from the schema."""
        from fastmcp.server.context import Context as ToolContext

        async def my_handler(ctx: ToolContext, name: str):
            pass  # noqa: ARG001

        schema = func_signature_to_input_schema(my_handler)
        self.assertNotIn("ctx", schema["properties"])
        self.assertIn("name", schema["properties"])


# -------------------------------------------------------------------
# @register_tool decorator tests
# -------------------------------------------------------------------


class TestRegisterToolDecorator(TestCase):
    """Tests for @register_tool decorator."""

    def setUp(self):
        """Reset the singleton before each test."""
        MCPToolRegistry._instance = None
        MCPToolRegistry._tools = {}

    def test_register_tool_decorator_registers_in_registry(self):
        """@register_tool registers the tool in MCPToolRegistry."""
        @register_tool(description="A test tool.", tier="core", scope="core")
        async def my_tool(ctx, name: str = "default"):
            return {"ok": True}

        registry = MCPToolRegistry.get_instance()
        tools = registry.get_all()
        tool_names = [t.name for t in tools]

        self.assertIn("my_tool", tool_names)
        tool = next(t for t in tools if t.name == "my_tool")
        self.assertEqual(tool.description, "A test tool.")
        self.assertEqual(tool.tier, "core")
        self.assertEqual(tool.scope, "core")

    def test_register_tool_auto_generates_schema(self):
        """@register_tool auto-generates input_schema from the function signature."""

        @register_tool(description="Auto-schema test.", tier="core", scope="core")
        async def my_handler2(ctx, limit: int = 5, q: str = ""):
            pass

        registry = MCPToolRegistry.get_instance()
        tool = next(t for t in registry.get_all() if t.name == "my_handler2")
        self.assertEqual(tool.input_schema["type"], "object")
        self.assertIn("limit", tool.input_schema["properties"])
        self.assertEqual(tool.input_schema["properties"]["limit"]["type"], "integer")
        self.assertEqual(tool.input_schema["properties"]["limit"]["default"], 5)

    def test_register_tool_explicit_schema_overrides_auto(self):
        """An explicit input_schema passed to @register_tool overrides auto-generated."""
        explicit_schema = {"type": "object", "properties": {"x": {"type": "string"}}}

        @register_tool(description="Override test.", input_schema=explicit_schema, tier="core", scope="core")
        async def my_tool_override(ctx, limit: int = 99):
            pass

        registry = MCPToolRegistry.get_instance()
        tool = next(t for t in registry.get_all() if t.name == "my_tool_override")
        self.assertEqual(tool.input_schema, explicit_schema)
        self.assertNotIn("limit", tool.input_schema["properties"])

    def test_register_tool_explicit_name(self):
        """An explicit name passed to @register_tool overrides the function's __name__."""

        @register_tool(description="Named tool.", name="custom_tool_name", tier="core", scope="core")
        async def my_handler_impl(ctx, x: int = 1):
            pass

        registry = MCPToolRegistry.get_instance()
        tool_names = [t.name for t in registry.get_all()]
        self.assertIn("custom_tool_name", tool_names)

    def test_register_tool_duplicate_name_raises(self):
        """Registering a tool with a name already in the registry raises ValueError."""
        async def dup_tool(ctx, x: int = 1):
            pass

        @register_tool(description="First tool.", tier="core", scope="core")
        async def dup_tool_registered(ctx, x: int = 1):
            pass

        # Second registration with same name should raise
        with self.assertRaises(ValueError) as ctx:
            register_mcp_tool(
                name="dup_tool_registered",
                func=dup_tool,
                description="Duplicate.",
                input_schema={"type": "object", "properties": {}},
                tier="core",
                scope="core",
            )
        self.assertIn("already registered", str(ctx.exception))


# -------------------------------------------------------------------
# register_all_tools_with_mcp tests
# -------------------------------------------------------------------


class TestRegisterAllToolsWithMcp(TestCase):
    """Tests for register_all_tools_with_mcp()."""

    def setUp(self):
        """Reset the singleton before each test."""
        MCPToolRegistry._instance = None
        MCPToolRegistry._tools = {}

    def test_register_all_tools_with_mcp_wires_tools(self):
        """register_all_tools_with_mcp calls mcp.tool() for every registered tool."""
        async def tool_a(ctx, x: int = 1):
            return {}

        async def tool_b(ctx, y: str = "hi"):
            return {}

        register_mcp_tool(
            name="tool_a",
            func=tool_a,
            description="Tool A",
            input_schema={"type": "object", "properties": {}},
            tier="core",
            scope="core",
        )
        register_mcp_tool(
            name="tool_b",
            func=tool_b,
            description="Tool B",
            input_schema={"type": "object", "properties": {}},
            tier="core",
            scope="core",
        )

        mock_mcp = MagicMock()
        register_all_tools_with_mcp(mock_mcp)

        self.assertEqual(mock_mcp.tool.call_count, 2)
        # Verify mcp.tool was called with the correct name and description
        calls = mock_mcp.tool.call_args_list
        names_called = {call.kwargs.get("name") or call.args[0].__name__ for call in calls}
        self.assertEqual(names_called, {"tool_a", "tool_b"})

    def test_register_all_tools_with_mcp_empty_registry_noop(self):
        """register_all_tools_with_mcp with no registered tools calls mcp.tool() zero times."""
        mock_mcp = MagicMock()
        register_all_tools_with_mcp(mock_mcp)
        mock_mcp.tool.assert_not_called()

    def test_register_all_tools_with_mcp_does_not_pass_input_schema(self):
        """register_all_tools_with_mcp does NOT pass input_schema to mcp.tool().

        FastMCP 3.x mcp.tool() does NOT accept input_schema as a direct parameter —
        schema is auto-derived from Python type hints. This test ensures the wiring
        function does not try to pass it.
        """
        async def my_tool(ctx, x: int = 1):
            return {}

        register_mcp_tool(
            name="my_tool",
            func=my_tool,
            description="Schema test",
            input_schema={"type": "object", "properties": {}},
            tier="core",
            scope="core",
        )

        mock_mcp = MagicMock()
        register_all_tools_with_mcp(mock_mcp)

        # Ensure input_schema is NOT passed to mcp.tool()
        for call in mock_mcp.tool.call_args_list:
            self.assertNotIn("input_schema", call.kwargs)
