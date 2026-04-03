---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified:
  - nautobot_app_mcp_server/mcp/tests/test_session_tools.py
autonomous: false
---

# Phase 5 — Wave 2 Task: WAVE2-TEST-SESSION

**Task ID:** WAVE2-TEST-SESSION
**File:** `nautobot_app_mcp_server/mcp/tests/test_session_tools.py`
**Requirements:** TEST-01 (verify MCPSessionState request_context pattern)
**Blockers:** Wave 1 complete (WAVE1-SESSION must be done first)

---

## read_first

- `nautobot_app_mcp_server/mcp/tests/test_session_tools.py` (current state — lines 1–204)
- `nautobot_app_mcp_server/mcp/session_tools.py` (after WAVE1-SESSION refactor — `_get_tool_state()` helpers)
- `.planning/phases/05-mcp-server-refactor/05-RESEARCH.md` §3 (latent bug explanation)

---

## context

The existing tests in `test_session_tools.py` pass a plain `dict` to `MCPSessionState.from_session()`. These tests are unaffected by the WAVE1-SESSION refactor because:
- `MCPSessionState` itself is unchanged — `from_session(dict)` still works with any dict
- The existing tests don't call `_get_tool_state()` directly; they test `MCPSessionState` in isolation

Two tests to add:
1. A test that verifies `_get_tool_state()` works with a mock `ctx.request_context` (the new state storage pattern)
2. A test that verifies `_list_tools_handler` uses `_get_tool_state()` instead of `ctx.request_context.session`

---

## action

### 1. Add test for `_get_tool_state()` helper

Add this to the end of `test_session_tools.py`:

```python
class GetToolStateTestCase(TestCase):
    """Test _get_tool_state() helper (WAVE1-SESSION fix for ServerSession latent bug)."""

    def test_get_tool_state_returns_existing_state(self):
        """If _mcp_tool_state exists on request_context, return it."""
        from nautobot_app_mcp_server.mcp.session_tools import _get_tool_state

        mock_ctx = MagicMock()
        existing_state = {"enabled_scopes": {"dcim"}, "enabled_searches": set()}
        mock_ctx.request_context._mcp_tool_state = existing_state

        result = _get_tool_state(mock_ctx)
        self.assertIs(result, existing_state)

    def test_get_tool_state_creates_state_on_first_access(self):
        """If _mcp_tool_state does not exist, create and attach it."""
        from nautobot_app_mcp_server.mcp.session_tools import _get_tool_state

        mock_ctx = MagicMock()
        # No _mcp_tool_state attribute initially
        del mock_ctx.request_context._mcp_tool_state
        with self.assertRaises(AttributeError):
            _ = mock_ctx.request_context._mcp_tool_state  # noqa: F841

        result = _get_tool_state(mock_ctx)

        # State should be created and attached
        self.assertIsInstance(result, dict)
        self.assertIn("enabled_scopes", result)
        self.assertIn("enabled_searches", result)
        self.assertEqual(mock_ctx.request_context._mcp_tool_state, result)

    def test_get_tool_state_initializes_empty_sets(self):
        """New state has empty enabled_scopes and enabled_searches sets."""
        from nautobot_app_mcp_server.mcp.session_tools import _get_tool_state

        mock_ctx = MagicMock()
        del mock_ctx.request_context._mcp_tool_state

        result = _get_tool_state(mock_ctx)

        self.assertEqual(result["enabled_scopes"], set())
        self.assertEqual(result["enabled_searches"], set())
```

### 2. Add test for progressive disclosure using `_get_tool_state()`

Add this test to `ProgressiveDisclosureTestCase` (after the existing `test_non_core_tool_requires_scope_enabled`):

```python
def test_list_tools_handler_uses_request_context_state(self):
    """After refactor, _list_tools_handler reads from request_context._mcp_tool_state.

    The old pattern (ctx.request_context.session) is replaced by
    _get_tool_state() which reads from ctx.request_context._mcp_tool_state.
    """
    from nautobot_app_mcp_server.mcp.session_tools import _list_tools_handler

    # Register a known app-scoped tool
    registry = MCPToolRegistry.get_instance()
    registry.register(
        ToolDefinition(
            name="test_rctx_tool",
            func=lambda: None,
            description="Test tool for request_context state",
            input_schema={"type": "object"},
            tier="app",
            app_label="test_app",
            scope="test_app.rctx",
        )
    )
    try:
        # Build a mock ctx with _mcp_tool_state (new pattern)
        mock_ctx = MagicMock()
        mock_ctx.request_context._mcp_tool_state = {
            "enabled_scopes": {"test_app.rctx"},
            "enabled_searches": set(),
        }

        # Run _list_tools_handler
        import asyncio
        tools = asyncio.get_event_loop().run_until_complete(
            _list_tools_handler(mock_ctx)
        )

        tool_names = [t.name for t in tools]
        # test_app.rctx scope is enabled → tool should be returned
        self.assertIn("test_rctx_tool", tool_names)
        # Core tools should always be present
        self.assertIn("mcp_enable_tools", tool_names)
    finally:
        del registry._tools["test_rctx_tool"]  # pylint: disable=protected-access
```

---

## acceptance_criteria

1. `grep -n "GetToolStateTestCase" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — shows the new test class
2. `grep -n "test_get_tool_state_returns_existing_state\|test_get_tool_state_creates_state_on_first_access\|test_get_tool_state_initializes_empty_sets" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — shows all three helper tests
3. `grep -n "test_list_tools_handler_uses_request_context_state" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — shows the progressive disclosure integration test
4. `grep -n "_mcp_tool_state" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — shows at least 4 occurrences (3 helper tests + 1 integration test)
5. `grep -n "ctx.request_context.session" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — returns 0 matches (old pattern not used in new tests)
6. `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — scores 10.00/10
7. `poetry run invoke ruff` passes on test_session_tools.py
8. `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_session_tools` — passes
