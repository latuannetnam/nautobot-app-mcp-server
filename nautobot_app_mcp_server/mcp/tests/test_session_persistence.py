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

import requests  # noqa: I001 — requests is a test-only dependency
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings, tag
from django.test.utils import skipUnless
from nautobot.users.models import Token


def _is_live_server_available() -> bool:
    """Return True if a live Nautobot server is reachable at localhost:8080."""
    import socket

    try:
        sock = socket.create_connection(("localhost", 8080), timeout=1)
        sock.close()
        return True
    except (socket.error, OSError):
        return False


@override_settings(
    PLUGINS=["nautobot_app_mcp_server"],
    ROOT_URLCONF="nautobot_app_mcp_server.urls",
    APPEND_SLASH=False,  # POST must not be redirected by APPEND_SLASH middleware
)
@skipUnless(
    _is_live_server_available(),
    "Live Nautobot server not reachable at localhost:8080 — run via docker exec for E2E verification",
)
@tag("requires_live_server")
class MCPSessionPersistenceTestCase(TestCase):
    """TEST-02: Two sequential MCP HTTP POSTs share Mcp-Session-Id; second
    mcp_list_tools reflects scopes enabled in the first (session persistence)."""

    @classmethod
    def setUpClass(cls):
        """Create a test token for auth (requires live Nautobot DB)."""
        super().setUpClass()
        user_model = get_user_model()
        if not user_model.objects.filter(is_superuser=True).exists():
            user_model.objects.create_superuser(
                username="mcp_test_admin",
                email="mcp_test@test.local",
                password="testpass",  # noqa: S106
            )
        cls.user = user_model.objects.filter(is_superuser=True).first()
        cls.token = Token.objects.create(user=cls.user)
        # Trailing slash required by Django APPEND_SLASH; do NOT follow redirects
        # since Django can't preserve POST body on 307 redirect.
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
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {self.token.key}",
        }
        if session_id:
            headers["mcp-session-id"] = session_id  # lowercase as per ASGI spec

        response = requests.post(
            f"{self.base_url}{self.endpoint}",
            json=payload,
            headers=headers,
            timeout=10,
            allow_redirects=False,  # POST with body must NOT follow 307 to /mcp/ (404s)
        )
        return response

    def _mcp_rpc_request(self, method: str, params: dict, session_id: str | None):
        """Send an MCP JSON-RPC request tool call (tools/call)."""
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
            "Accept": "application/json",
            "Authorization": f"Token {self.token.key}",
        }
        if session_id:
            headers["mcp-session-id"] = session_id  # lowercase as per ASGI spec

        response = requests.post(
            f"{self.base_url}{self.endpoint}",
            json=payload,
            headers=headers,
            timeout=10,
            allow_redirects=False,  # POST with body must NOT follow 307 to /mcp/ (404s)
        )
        return response

    def test_session_persistence_progressive_disclosure(self):
        """TEST-02: Session state persists across requests.

        Step 1: Send initialize + mcp_enable_tools(scope="dcim") with session_id
        Step 2: Send mcp_list_tools with same session_id
        Verify: mcp_list_tools response includes dcim-scoped tools
        """
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
