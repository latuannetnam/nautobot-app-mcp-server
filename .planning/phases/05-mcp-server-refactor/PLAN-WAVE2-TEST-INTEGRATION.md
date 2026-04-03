---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified:
  - nautobot_app_mcp_server/mcp/tests/test_session_persistence.py
autonomous: false
---

# Phase 5 — Wave 2 Task: WAVE2-TEST-INTEGRATION

**Task ID:** WAVE2-TEST-INTEGRATION
**File:** `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` (NEW FILE)
**Requirements:** TEST-02
**Priority:** P0 (the key acceptance test for the entire refactor)

---

## read_first

- `nautobot_app_mcp_server/mcp/view.py` (after WAVE2-VIEW refactor — the endpoint being tested)
- `nautobot_app_mcp_server/mcp/server.py` (after WAVE1-SERVER — `get_session_manager()`)
- `nautobot_app_mcp_server/mcp/session_tools.py` (after WAVE1-SESSION — `MCPSessionState` on request_context)
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` (existing test style to follow)
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — D-17 through D-20 (test design decisions)

---

## context

**What this test verifies:** After REFA-01/REFA-02 fix the `asyncio.run()` issue, session state persists across sequential MCP HTTP requests. The MCP client sends the same `Mcp-Session-Id` header on both requests. On request 1, `mcp_enable_tools(scope="dcim")` is called. On request 2, `mcp_list_tools` returns tools from the `dcim` scope (proving the scope was persisted).

**Why a real integration test is needed:** Unit tests mock `ctx.request_context` with `MagicMock`. After the refactor, the real `ctx.request_context` is a `RequestContext` dataclass (from `mcp/server/lowlevel/servertypes.py`). The integration test verifies the end-to-end flow: Django request → ASGI bridge → `session_manager.run()` → `Server.request_context` set → `_list_tools_handler` reads `request_context._mcp_tool_state`.

**Test location:** Runs inside the Docker container (`docker exec ... python .../test_session_persistence.py`). This is necessary because it needs a live Nautobot DB (for Token auth) and a live FastMCP server.

**Approach:** Use `requests.Session` to send real HTTP POST requests to `http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/`. Use a real Nautobot API token. Verify `Mcp-Session-Id` header flows correctly and progressive disclosure works.

---

## action

### Create the file `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py`

```python
"""Integration test: MCP session persistence across HTTP requests (TEST-02).

Verifies that after fixing asyncio.run() → async_to_sync, session state
persists across sequential MCP HTTP requests sharing the same Mcp-Session-Id
header. This is the primary acceptance test for the Phase 5 refactor.

Run inside the Docker container:
    docker exec -it nautobot-app-mcp-server-nautobot-1 bash
    poetry run python -m pytest \
        nautobot_app_mcp_server/mcp/tests/test_session_persistence.py \
        -v

Or via invoke:
    poetry run invoke unittest -- --pattern test_session_persistence
"""

from __future__ import annotations

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from nautobot.users.models import Token


@override_settings(
    PLUGINS=["nautobot_app_mcp_server"],
    ROOT_URLCONF="nautobot_app_mcp_server.urls",
)
class MCPSessionPersistenceTestCase(TestCase):
    """TEST-02: Two sequential MCP HTTP POSTs share Mcp-Session-Id; second
    mcp_list_tools reflects scopes enabled in the first (session persistence)."""

    @classmethod
    def setUpClass(cls):
        """Create a test token for auth (requires live Nautobot DB)."""
        super().setUpClass()
        User = get_user_model()
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                username="mcp_test_admin",
                email="mcp_test@test.local",
                password="testpass",  # noqa: S106
            )
        cls.user = User.objects.filter(is_superuser=True).first()
        cls.token = Token.objects.create(
            user=cls.user,
            key="nbapikey_test_session_persist_123",
        )
        cls.endpoint = "/plugins/nautobot-app-mcp-server/mcp/"
        cls.base_url = "http://localhost:8080"
        cls.session_id = str(uuid.uuid4())  # Fresh session ID for this test

    @classmethod
    def tearDownClass(cls):
        """Clean up test token."""
        cls.token.delete()
        super().tearDownClass()

    def _mcp_request(self, method: str, params: dict, session_id: str | None):
        """Send an MCP JSON-RPC POST request and return the parsed response."""
        import json
        import requests

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {self.token.key}",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        response = requests.post(
            f"{self.base_url}{self.endpoint}",
            json=payload,
            headers=headers,
            timeout=10,
        )
        return response

    def _mcp_rpc_request(self, method: str, params: dict, session_id: str | None):
        """Send an MCP JSON-RPC request tool call (tools/call)."""
        import json
        import requests

        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": method,
                "arguments": params,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {self.token.key}",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        response = requests.post(
            f"{self.base_url}{self.endpoint}",
            json=payload,
            headers=headers,
            timeout=10,
        )
        return response

    def test_session_persistence_progressive_disclosure(self):
        """TEST-02: Session state persists across requests.

        Step 1: Send initialize + mcp_enable_tools(scope="dcim") with session_id
        Step 2: Send mcp_list_tools with same session_id
        Verify: mcp_list_tools response includes dcim-scoped tools
        """
        import json

        # Step 1a: Send initialize to establish the session
        init_response = self._mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
            session_id=self.session_id,
        )
        self.assertEqual(init_response.status_code, 200, init_response.text)

        # Step 1b: Send mcp_enable_tools(scope="dcim") in the same session
        enable_response = self._mcp_rpc_request(
            "mcp_enable_tools",
            {"scope": "dcim"},
            session_id=self.session_id,
        )
        self.assertEqual(enable_response.status_code, 200, enable_response.text)
        enable_data = enable_response.json()
        # Should succeed (no error key)
        self.assertNotIn("error", enable_data, enable_data)

        # Parse the result — tools/call wraps the tool's return in a "result" key
        enable_result = enable_data.get("result", {})
        enable_content = enable_result.get("content", [{}])
        enable_text = enable_content[0].get("text", "") if enable_content else ""
        self.assertIn("dcim", enable_text.lower(), f"Expected 'dcim' in enable result: {enable_text}")

        # Step 2: Send mcp_list_tools with the SAME session_id
        list_response = self._mcp_rpc_request(
            "mcp_list_tools",
            {},
            session_id=self.session_id,
        )
        self.assertEqual(list_response.status_code, 200, list_response.text)
        list_data = list_response.json()
        self.assertNotIn("error", list_data, list_data)

        list_result = list_data.get("result", {})
        list_content = list_result.get("content", [{}])
        list_text = list_content[0].get("text", "") if list_content else ""

        # Verify: dcim-scoped tools appear in mcp_list_tools output
        # (core tools + dcim tools should both be present)
        self.assertIn("dcim", list_text.lower(), f"Expected 'dcim' tools in list result: {list_text}")
        # Core tools should also be present
        self.assertIn("mcp_enable_tools", list_text, f"Expected core tools in list result: {list_text}")

    def test_session_without_id_resets_state(self):
        """Verify that requests WITHOUT a session ID do NOT share state.

        Enable dcim scope with session_id=A, then call mcp_list_tools
        WITHOUT session_id — the scope should NOT be visible.
        """
        import json

        # Step 1: Enable dcim with a session ID
        init_response = self._mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
            session_id=self.session_id,
        )
        self.assertEqual(init_response.status_code, 200)

        enable_response = self._mcp_rpc_request(
            "mcp_enable_tools",
            {"scope": "dcim"},
            session_id=self.session_id,
        )
        self.assertEqual(enable_response.status_code, 200)

        # Step 2: Call mcp_list_tools WITHOUT session_id (new implicit session)
        other_session_id = str(uuid.uuid4())
        list_response = self._mcp_rpc_request(
            "mcp_list_tools",
            {},
            session_id=other_session_id,
        )
        self.assertEqual(list_response.status_code, 200)
        list_data = list_response.json()
        list_result = list_data.get("result", {})
        list_content = list_result.get("content", [{}])
        list_text = list_content[0].get("text", "") if list_content else ""

        # The new session should NOT have dcim tools enabled
        # (only core tools should be listed, no dcim scope)
        self.assertNotIn(
            "dcim",
            list_text.lower(),
            f"New session should not have dcim tools: {list_text}",
        )
        # But core tools should still be there
        self.assertIn("mcp_enable_tools", list_text)
```

---

## acceptance_criteria

1. `grep -n "test_session_persistence_progressive_disclosure\|test_session_without_id_resets_state" nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — shows both test methods
2. `grep -n "Mcp-Session-Id" nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — shows the session header sent on both requests
3. `grep -n "mcp_enable_tools\|mcp_list_tools" nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — shows the tools being called in sequence
4. `grep -n "dcim" nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — shows the scope verification
5. `grep -n "session_id" nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — shows same session ID used across requests
6. `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — scores 10.00/10
7. `poetry run invoke ruff` passes on test_session_persistence.py
8. Running the test inside Docker (`docker exec ... python -m pytest ...`) passes — **this is the primary acceptance criterion for the entire Phase 5 refactor**

---

## notes

- Uses `requests` library (available in Nautobot's test environment) for real HTTP calls
- Uses a real Nautobot Token from the test DB (created in `setUpClass`)
- `session_id` is a fresh UUID per test run to avoid cross-test pollution
- The `tools/call` method is FastMCP's standard tool invocation method for JSON-RPC over HTTP
- The test validates both positive (same session = state persists) and negative (different session = state resets) cases
- Test is placed in `mcp/tests/` alongside existing tests — it uses Django's `TestCase` so it can access the test DB for token creation
- If `requests` is not available in the container, install it with `pip install requests` temporarily, or use `urllib.request` instead