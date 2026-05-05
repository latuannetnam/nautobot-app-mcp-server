#!/usr/bin/env python3
"""UAT for GraphQL-Only Mode (Phase 18) — T-45, T-46.

This script runs ONLY the GraphQL-Only Mode tests:
    T-45: Manifest shows exactly 2 tools
    T-46: Non-GraphQL tool call is blocked

The MCP server MUST be running in GQL-only mode (default).
Restart with:
    docker compose -f development/docker-compose.mcp.yml restart nautobot

NOTE: GQL-only mode is the default. If NAUTOBOT_MCP_ENABLE_ALL=true is set in
      development/creds.env, comment it out and restart to test GQL-only mode.

Usage:
    unset VIRTUAL_ENV && poetry run python scripts/run_mcp_uat_gql_only.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ENV_FILE = Path(__file__).parent.parent / "development" / "creds.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

MCP_DEV_URL = os.environ.get("MCP_DEV_URL", "http://localhost:8005")
MCP_ENDPOINT = f"{MCP_DEV_URL}/mcp/"
DEV_TOKEN = os.environ.get(
    "NAUTOBOT_DEV_TOKEN",
    os.environ.get("NAUTOBOT_SUPERUSER_API_TOKEN", "0123456789abcdef0123456789abcdef01234567"),
)


class MCPClient:
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.session_id: str | None = None
        self._lock = threading.Lock()
        self._init_session()

    def _init_session(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "nautobot-mcp-uat", "version": "1.0.0"},
                "capabilities": {},
            },
        }
        resp = requests.post(
            self.endpoint,
            json=payload,
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        if session_id := resp.headers.get("MCP-Session-Id"):
            self.session_id = session_id

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Token {self.token}",
        }
        if self.session_id:
            h["MCP-Session-Id"] = self.session_id
        return h

    def call(self, method: str, params: dict | None = None) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params:
            payload["params"] = params

        with self._lock:
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()

            if session_id := resp.headers.get("MCP-Session-Id"):
                self.session_id = session_id

            data = None
            for line in resp.text.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    break
            if data is None:
                raise RuntimeError(f"No data line in SSE response: {resp.text[:200]}")

        if "error" in data:
            raise MCPToolError(data["error"].get("code"), data["error"].get("message"), data["error"])

        return data.get("result", {})

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.call("tools/list")
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        result = self.call("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        if result.get("isError"):
            error_text = next(
                (item.get("text", "") for item in content if item.get("type") == "text"),
                "Unknown error",
            )
            raise MCPToolError(code=-32602, message=error_text)
        for item in content:
            if item.get("type") == "text":
                text = item["text"]
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and "data" in parsed and "errors" not in parsed:
                        parsed["errors"] = None
                    return parsed
                except json.JSONDecodeError:
                    return text
        return result


class MCPToolError(Exception):
    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error: str | None = None
        self.duration_ms: float = 0
        self.result: Any = None

    def ok(self, result: Any = None, duration_ms: float = 0):
        self.passed = True
        self.result = result
        self.duration_ms = duration_ms

    def fail(self, error: str):
        self.error = error
        self.passed = False

    def __str(self):
        status = "PASS" if self.passed else "FAIL"
        ms = f" ({self.duration_ms:.0f}ms)" if self.duration_ms else ""
        msg = f"[{status}]{ms} {self.name}"
        if self.error:
            msg += f"\n   Error: {self.error}"
        return msg


class TestRunner:
    def __init__(self, client: MCPClient):
        self.client = client
        self.results: list[TestResult] = []

    def test(self, name: str, fn):
        result = TestResult(name)
        t0 = time.perf_counter()
        try:
            rv = fn()
            result.ok(rv, duration_ms=(time.perf_counter() - t0) * 1000)
        except MCPToolError as e:
            result.fail(f"MCP Error [{e.code}]: {e.message}")
        except Exception as e:  # noqa: BLE001
            result.fail(str(e))
        self.results.append(result)
        return result

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        print("\n" + "=" * 70)
        print(f"GraphQL-Only Mode UAT: {passed}/{total} passed")
        if failed:
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error}")
        return failed == 0


def run_gql_only_uat() -> bool:
    print("=" * 70)
    print("GraphQL-Only Mode UAT — T-45, T-46")
    print("=" * 70)
    print(f"Endpoint: {MCP_ENDPOINT}")
    print(f"Token:   {DEV_TOKEN[:8]}... (first 8 chars)")
    print()
    print("NOTE: Ensure MCP server is in GQL-only mode (default).")
    print("      Restart container after any env var changes:")
    print("      docker compose -f development/docker-compose.mcp.yml restart nautobot")
    print()

    client = MCPClient(MCP_ENDPOINT, DEV_TOKEN)
    runner = TestRunner(client)

    # T-45: GQLONLY-02 — manifest shows exactly 2 tools
    def t45():
        all_tools = client.list_tools()
        tool_names = [t["name"] for t in all_tools]
        print(f"\n  [T-45] tools/list returned: {tool_names}")
        assert len(all_tools) == 2, f"Expected 2 tools in GQL-only mode, got {len(all_tools)}: {tool_names}"
        assert "graphql_query" in tool_names
        assert "graphql_introspect" in tool_names
        assert "mcp_enable_tools" not in tool_names, "Session tool 'mcp_enable_tools' should be hidden in GQL-only mode"
        return {"tool_count": len(all_tools)}

    runner.test("T-45 GQL-only manifest: exactly 2 tools, session tools hidden", t45)

    # T-46: GQLONLY-03 — non-GraphQL tool call blocked
    def t46():
        print("\n  [T-46] Calling device_list (should be blocked)...")
        try:
            result = client.call_tool("device_list", {"limit": 1})
            raise AssertionError(f"device_list should have been blocked but returned: {result}")
        except MCPToolError as e:
            print(f"  [T-46] Correctly blocked with error: {e.message}")
            assert "not available in GraphQL-only mode" in e.message, f"Expected 'not available' error, got: {e.message}"
        return {"blocked": True}

    runner.test("T-46 GQL-only: device_list call blocked", t46)

    print()
    all_passed = runner.summary()
    return all_passed


if __name__ == "__main__":
    try:
        success = run_gql_only_uat()
        sys.exit(0 if success else 1)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)