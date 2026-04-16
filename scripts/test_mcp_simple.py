#!/usr/bin/env python3
"""Minimal MCP smoke test — verify the server responds correctly over HTTP."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = Path(__file__).parent.parent / "nautobot_import.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

MCP_DEV_URL = os.environ.get("MCP_DEV_URL", "http://localhost:8005")
MCP_ENDPOINT = f"{MCP_DEV_URL}/mcp/"
DEV_TOKEN = os.environ.get(
    "NAUTOBOT_DEV_TOKEN",
    os.environ.get("NAUTOBOT_SUPERUSER_API_TOKEN", "0123456789abcdef0123456789abcdef01234567"),
)


# ---------------------------------------------------------------------------
# MCP Client
# ---------------------------------------------------------------------------


class MCPClient:
    def __init__(self, endpoint: str, token: str):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.session_id: str | None = None
        self._init_session()

    def _init_session(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "simple-smoke", "version": "1.0.0"},
                "capabilities": {},
            },
        }
        resp = requests.post(
            self.endpoint,
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        if session_id := resp.headers.get("MCP-Session-Id"):
            self.session_id = session_id
        print(f"  [init] session_id={self.session_id}, status={resp.status_code}")

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Token {self.token}",
        }
        if self.session_id:
            h["MCP-Session-Id"] = self.session_id
        return h

    def _post(self, payload: dict) -> requests.Response:
        resp = requests.post(
            self.endpoint,
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        if session_id := resp.headers.get("MCP-Session-Id"):
            self.session_id = session_id
        return resp

    def list_tools(self) -> list[dict]:
        resp = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        data = self._parse_sse(resp.text)
        if "error" in data:
            raise RuntimeError(f"list_tools error: {data['error']}")
        return data.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        resp = self._post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        data = self._parse_sse(resp.text)
        if "error" in data:
            raise RuntimeError(f"call_tool error: {data['error']}")
        result = data.get("result", {})
        # Unwrap content text
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                parsed = json.loads(item["text"])
                if isinstance(parsed, dict) and "result" in parsed and len(parsed) == 1:
                    return parsed["result"]
                # Normalize GraphQL responses: always include 'errors' key
                # Success: {"data": ...}  Failure: {"data": null, "errors": [...]}
                if isinstance(parsed, dict) and "data" in parsed and "errors" not in parsed:
                    parsed["errors"] = None
                return parsed
        return result

    def _parse_sse(self, text: str) -> dict:
        for line in text.split("\n"):
            if line.startswith("data:"):
                return json.loads(line[5:])
        raise RuntimeError(f"No SSE data line in response: {text[:200]!r}")


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


def run() -> bool:
    print("=" * 60)
    print("MCP Simple Smoke Test")
    print("=" * 60)
    print(f"Endpoint : {MCP_ENDPOINT}")
    print(f"Token    : {DEV_TOKEN[:8]}...")
    print()

    try:
        # 1. Initialize session
        print("1. Initialize session...")
        client = MCPClient(MCP_ENDPOINT, DEV_TOKEN)
        print("   OK")

        # 2. List tools
        print("2. List tools...")
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        print(f"   Found {len(tools)} tools: {tool_names}")
        print("   OK")

        # 3. Call device_list
        print("3. Call device_list...")
        result = client.call_tool("device_list", {"limit": 5})
        items = result.get("items", [])
        total = result.get("total_count", "?")
        print(f"   Returned {len(items)} devices (total={total})")
        for item in items:
            print(
                f"     - {item['name']} | status={item.get('status')} | "
                f"device_type={item.get('device_type')} | "
                f"location={item.get('location')}"
            )
        print("   OK")

        # 4. Call device_get on first device
        if items:
            dev = items[0]
            print(f"4. Call device_get(name_or_id='{dev['name']}')...")
            detail = client.call_tool("device_get", {"name_or_id": dev["name"]})
            ifaces = detail.get("interfaces", [])
            print(f"   {detail['name']} has {len(ifaces)} interfaces")
            for iface in ifaces[:3]:
                print(f"     - {iface['name']} | type={iface.get('type')} | enabled={iface.get('enabled')}")
            print("   OK")

        # 5. Call graphql_query
        print("5. Call graphql_query...")
        result = client.call_tool("graphql_query", {"query": "{ devices(limit: 3) { name status { name } } }"})
        assert "data" in result, "graphql_query result must have 'data' key"
        assert result["data"] is not None, f"Expected data, got: {result}"
        assert "errors" in result, "graphql_query result must have 'errors' key"
        print(f"   Returned data (errors={result.get('errors')})")
        print("   OK")

        print()
        print("All smoke tests PASSED")
        return True

    except Exception as e:
        print(f"\nFAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
