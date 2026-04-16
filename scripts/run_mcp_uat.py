#!/usr/bin/env python3
"""Python UAT test suite for nautobot-app-mcp-server MCP tools.

This script calls the MCP HTTP endpoint directly using JSON-RPC 2.0
over HTTP (streamable http transport with json_response=True).

Usage:
    # Inside the Nautobot container:
    docker exec -it nautobot-app-mcp-server-nautobot-1 \
        python /source/scripts/run_mcp_uat.py

    # Or via poetry (from host):
    unset VIRTUAL_ENV && cd /path/to/project && poetry run python scripts/run_mcp_uat.py

Environment variables (from nautobot_import.env):
    MCP_DEV_URL      MCP server URL (default: http://localhost:8005)
    MCP_DEV_TOKEN     Dev auth token (default: from development/creds.env)

Prerequisites:
    1. poetry run invoke start          # Start dev stack
    2. poetry run invoke import          # Or: reset_dev_db.sh import (once data is configured)
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENV_FILE = Path(__file__).parent.parent / "development" / "creds.env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

MCP_DEV_URL = os.environ.get("MCP_DEV_URL", "http://localhost:8005")
MCP_ENDPOINT = f"{MCP_DEV_URL}/mcp/"
DEV_TOKEN = os.environ.get(
    "NAUTOBOT_DEV_TOKEN",
    os.environ.get("NAUTOBOT_SUPERUSER_API_TOKEN", "0123456789abcdef0123456789abcdef01234567"),
)


# ---------------------------------------------------------------------------
# MCP JSON-RPC 2.0 Client
# ---------------------------------------------------------------------------


class MCPClient:
    """Minimal JSON-RPC 2.0 client for FastMCP streamable http transport.

    Handles:
    - JSON-RPC 2.0 request/response
    - MCP-Session-Id header for session continuity
    - Auth token injection
    """

    def __init__(self, endpoint: str, token: str):
        # Strip trailing slash to avoid HTTP 307 redirect (loses POST body)
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.session_id: str | None = None
        self._tool_cache: list[dict[str, Any]] = []
        # Serialize HTTP requests to avoid SSE stream interleaving from
        # concurrent calls sharing the same requests.Session().
        self._lock = threading.Lock()
        # Send initialize() to establish a session with the MCP server.
        # Required by FastMCP's StreamableHTTPSessionManager (stateless_http=False).
        self._init_session()

    def _init_session(self) -> None:
        """Send MCP initialize to establish a session."""
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
        """Send a JSON-RPC 2.0 request and return the parsed result.

        Thread-safe: serializes requests through a lock to prevent SSE stream
        interleaving when multiple threads share this client instance.
        """
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

            # Extract session ID from response headers
            if session_id := resp.headers.get("MCP-Session-Id"):
                self.session_id = session_id

            # Parse SSE response (text/event-stream with "data: {...}" lines)
            data = None
            for line in resp.text.split("\n"):
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    break
            if data is None:
                raise RuntimeError(f"No data line in SSE response: {resp.text[:200]}")

        # Handle JSON-RPC error responses (outside the lock — no I/O)
        if "error" in data:
            raise MCPToolError(data["error"].get("code"), data["error"].get("message"), data["error"])

        return data.get("result", {})

    def list_tools(self) -> list[dict[str, Any]]:
        """List all available MCP tools."""
        result = self.call("tools/list")
        self._tool_cache = result.get("tools", [])
        return self._tool_cache

    def call_tool(self, name: str, arguments: dict | None = None) -> dict[str, Any]:
        """Call an MCP tool by name.

        Raises:
            MCPToolError: when the MCP server returns isError=true (e.g., tool raised a
                Python exception). The tool's error message is extracted from content[0].text.
        """
        arguments = arguments or {}
        result = self.call("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])

        # Surface isError=true as MCPToolError so callers can catch it (T-16/18/21/24).
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
                    # Unwrap session-tool responses that embed the result in {"result": "..."}
                    if isinstance(parsed, dict) and "result" in parsed and len(parsed) == 1:
                        return parsed["result"]
                    # Normalize GraphQL responses: always include 'errors' key
                    # Success: {"data": ...}  Failure: {"data": null, "errors": [...]}
                    if isinstance(parsed, dict) and "data" in parsed and "errors" not in parsed:
                        parsed["errors"] = None
                    return parsed
                except json.JSONDecodeError:
                    # Non-JSON text responses (plain strings) are returned as-is.
                    return text
        return result


class MCPToolError(Exception):
    """Raised when an MCP tool returns an error."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# Test Runner Infrastructure
# ---------------------------------------------------------------------------


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

    def __str__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        ms = f" ({self.duration_ms:.0f}ms)" if self.duration_ms else ""
        msg = f"{status}{ms} — {self.name}"
        if self.error:
            msg += f"\n   Error: {self.error}"
        return msg


class TestRunner:
    def __init__(self, client: MCPClient):
        self.client = client
        self.results: list[TestResult] = []

    def test(self, name: str, fn):
        """Run a test function, capturing result and timing."""
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
        print(f"UAT Results: {passed}/{total} passed")
        if failed:
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error}")
        return failed == 0


# ---------------------------------------------------------------------------
# UAT Test Cases
# ---------------------------------------------------------------------------


def run_uat() -> bool:
    """Run all UAT test cases."""
    print("=" * 70)
    print("nautobot-app-mcp-server UAT — Functional & Performance Tests")
    print("=" * 70)
    print(f"Endpoint: {MCP_ENDPOINT}")
    print(f"Token:   {DEV_TOKEN[:8]}... (first 8 chars)")
    print()

    client = MCPClient(MCP_ENDPOINT, DEV_TOKEN)
    runner = TestRunner(client)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2a. Session Tools (T-01 to T-04)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## Auth & Session Tools")

    def t01():
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        # All 13 core tools should be visible
        expected = {
            "device_list",
            "device_get",
            "interface_list",
            "interface_get",
            "ipaddress_list",
            "ipaddress_get",
            "prefix_list",
            "vlan_list",
            "location_list",
            "search_by_name",
            "mcp_enable_tools",
            "mcp_disable_tools",
            "mcp_list_tools",
        }
        missing = expected - set(tool_names)
        if missing:
            raise AssertionError(f"Missing tools: {missing}")
        return tool_names

    runner.test("T-01 mcp_list_tools baseline — all 13 tools visible", t01)

    def t02():
        result = client.call_tool("mcp_enable_tools", {"scope": "dcim"})
        # Enable dcim scope, then list tools — should still show all (all are core)
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "device_list" in tool_names
        assert "ipaddress_list" in tool_names
        return result

    runner.test("T-02 mcp_enable_tools scope=dcim", t02)

    def t03():
        result = client.call_tool("mcp_disable_tools", {})
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        # All tools still visible (all are core)
        assert "device_list" in tool_names
        return result

    runner.test("T-03 mcp_disable_tools all (no args)", t03)

    def t04():
        # Enable then disable partially
        client.call_tool("mcp_enable_tools", {"scope": "dcim"})
        client.call_tool("mcp_enable_tools", {"scope": "ipam"})
        client.call_tool("mcp_disable_tools", {"scope": "dcim"})
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "device_list" in tool_names  # Still visible (core tier)
        return {"scopes_working": True}

    runner.test("T-04 mcp_disable_tools partial scope", t04)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2b. List Tools Correctness (T-05 to T-13)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## List Tools — Correctness")

    def t05():
        result = client.call_tool("device_list", {"limit": 25})
        assert "items" in result, "device_list must return 'items'"
        assert isinstance(result["items"], list), "'items' must be a list"
        assert len(result["items"]) <= 25, f"Expected ≤25 items, got {len(result['items'])}"
        # Cursor present if count > limit (we don't know count here)
        return result

    runner.test("T-05 device_list default pagination (limit=25)", t05)

    def t06():
        # Get first page
        page1 = client.call_tool("device_list", {"limit": 5})
        first_ids = {d["pk"] for d in page1.get("items", [])}
        if page1.get("cursor") and page1["items"]:
            # Get second page using cursor
            page2 = client.call_tool("device_list", {"limit": 5, "cursor": page1["cursor"]})
            second_ids = {d["pk"] for d in page2.get("items", [])}
            overlap = first_ids & second_ids
            if overlap:
                raise AssertionError(f"Cursor pagination produced duplicate IDs: {overlap}")
        return {"pages_ok": True}

    runner.test("T-06 device_list cursor pagination — no duplicates", t06)

    def t07():
        result = client.call_tool("device_list", {"limit": 1000})
        assert len(result["items"]) <= 1000, f"Over limit: {len(result['items'])}"
        return result

    runner.test("T-07 device_list LIMIT_MAX=1000 cap", t07)

    def t08():
        # Get a known device name first
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices in DB)")
            return {"skipped": True}
        device_name = devices["items"][0]["name"]
        result = client.call_tool("interface_list", {"device_name": device_name, "limit": 50})
        assert "items" in result
        for iface in result["items"]:
            assert iface.get("device") == device_name, f"Expected device={device_name}, got {iface.get('device')}"
        return result

    runner.test("T-08 interface_list device_name filter", t08)

    def t09():
        result = client.call_tool("interface_list", {"limit": 10})
        assert "items" in result
        return result

    runner.test("T-09 interface_list without filter", t09)

    def t10():
        result = client.call_tool("ipaddress_list", {"limit": 100})
        assert "items" in result
        assert len(result["items"]) <= 100
        return result

    runner.test("T-10 ipaddress_list large page", t10)

    def t11():
        result = client.call_tool("prefix_list", {"limit": 10})
        assert "items" in result
        if result["items"]:
            item = result["items"][0]
            # VRF and tenant fields should be present (may be null)
            assert "vrf" in item, "'vrf' field missing from prefix item"
            assert "tenant" in item, "'tenant' field missing from prefix item"
        return result

    runner.test("T-11 prefix_list VRF/tenant fields", t11)

    def t12():
        result = client.call_tool("vlan_list", {"limit": 10})
        assert "items" in result
        if result["items"]:
            item = result["items"][0]
            assert "locations" in item, "'locations' field missing from vlan item"
            assert isinstance(item["locations"], list), "'locations' must be a list"
        return result

    runner.test("T-12 vlan_list locations M2M field", t12)

    def t13():
        result = client.call_tool("location_list", {"limit": 20})
        assert "items" in result
        return result

    runner.test("T-13 location_list hierarchy", t13)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2c. Get Tools Correctness (T-14 to T-21)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## Get Tools — Correctness")

    def t14():
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices in DB)")
            return {"skipped": True}
        device_name = devices["items"][0]["name"]
        result = client.call_tool("device_get", {"name_or_id": device_name})
        assert "interfaces" in result, "'interfaces' must be nested in device_get"
        assert isinstance(result["interfaces"], list)
        return result

    runner.test("T-14 device_get by name with nested interfaces", t14)

    def t15():
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices in DB)")
            return {"skipped": True}
        device = devices["items"][0]
        by_name = client.call_tool("device_get", {"name_or_id": device["name"]})
        by_uuid = client.call_tool("device_get", {"name_or_id": device["pk"]})
        assert by_name["pk"] == by_uuid["pk"], "Name and UUID lookup must return same device"
        return {"consistent": True}

    runner.test("T-15 device_get by UUID matches by-name result", t15)

    def t16():
        try:
            client.call_tool("device_get", {"name_or_id": "nonexistent_device_xyz_12345"})
            raise AssertionError("Expected ValueError for nonexistent device")
        except MCPToolError as e:
            if e.code != -32602:
                raise AssertionError(f"Expected -32602 (invalid params), got {e.code}")
            # Check message mentions the device name
            assert "nonexistent" in str(e.message).lower(), f"Error message should mention name: {e.message}"
        return {"raises_correctly": True}

    runner.test("T-16 device_get not found raises ValueError", t16)

    def t17():
        # Find an interface with IPs
        ifaces = client.call_tool("interface_list", {"limit": 20})
        for iface in ifaces.get("items", []):
            if iface.get("ip_addresses"):
                result = client.call_tool("interface_get", {"name_or_id": iface["name"]})
                assert "ip_addresses" in result
                assert isinstance(result["ip_addresses"], list)
                return result
        print("  (SKIP — no interfaces with IPs found)")
        return {"skipped": True}

    runner.test("T-17 interface_get with IP addresses", t17)

    def t18():
        try:
            client.call_tool("interface_get", {"name_or_id": "nonexistent_iface_xyz"})
            raise AssertionError("Expected ValueError")
        except MCPToolError as e:
            if e.code != -32602:
                raise AssertionError(f"Expected -32602, got {e.code}")
        return {"raises_correctly": True}

    runner.test("T-18 interface_get not found raises ValueError", t18)

    def t19():
        ips = client.call_tool("ipaddress_list", {"limit": 5})
        if not ips.get("items"):
            print("  (SKIP — no IPs in DB)")
            return {"skipped": True}
        ip = ips["items"][0]["address"]
        result = client.call_tool("ipaddress_get", {"name_or_id": ip})
        assert "interfaces" in result
        return result

    runner.test("T-19 ipaddress_get by address with nested interfaces", t19)

    def t20():
        ips = client.call_tool("ipaddress_list", {"limit": 1})
        if not ips.get("items"):
            print("  (SKIP — no IPs in DB)")
            return {"skipped": True}
        ip = ips["items"][0]
        by_addr = client.call_tool("ipaddress_get", {"name_or_id": ip["address"]})
        by_uuid = client.call_tool("ipaddress_get", {"name_or_id": ip["pk"]})
        assert by_addr["pk"] == by_uuid["pk"]
        return {"consistent": True}

    runner.test("T-20 ipaddress_get by UUID matches by-address result", t20)

    def t21():
        try:
            client.call_tool("ipaddress_get", {"name_or_id": "99.99.99.99/99"})
            raise AssertionError("Expected ValueError")
        except MCPToolError as e:
            if e.code != -32602:
                raise AssertionError(f"Expected -32602, got {e.code}")
        return {"raises_correctly": True}

    runner.test("T-21 ipaddress_get not found raises ValueError", t21)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2d. Search Tool (T-22 to T-26)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## Search Tool")

    def t22():
        result = client.call_tool("search_by_name", {"query": "router", "limit": 10})
        assert "items" in result
        return result

    runner.test("T-22 search_by_name single term", t22)

    def t23():
        # Single known device to test AND semantics
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices)")
            return {"skipped": True}
        device_name = devices["items"][0]["name"]
        terms = device_name.split()
        if len(terms) < 2:
            print(f"  (SKIP — device name '{device_name}' has <2 terms)")
            return {"skipped": True}
        result = client.call_tool("search_by_name", {"query": " ".join(terms), "limit": 10})
        assert "items" in result
        for item in result["items"]:
            q_lower = " ".join(terms).lower()
            name_lower = item.get("name", "").lower()
            # Both terms should appear somewhere in the name
            for term in terms:
                assert term.lower() in name_lower, f"AND semantics violated: term '{term}' not in '{name_lower}'"
        return result

    runner.test("T-23 search_by_name AND semantics", t23)

    def t24():
        try:
            client.call_tool("search_by_name", {"query": "   "})
            raise AssertionError("Expected ValueError for empty query")
        except MCPToolError as e:
            if e.code != -32602:
                raise AssertionError(f"Expected -32602, got {e.code}")
        return {"raises_correctly": True}

    runner.test("T-24 search_by_name empty/whitespace query raises", t24)

    def t25():
        # Use a query likely to return many results
        result = client.call_tool("search_by_name", {"query": "a", "limit": 10})
        assert "items" in result
        if result.get("cursor") and len(result["items"]) == 10:
            # Paginate
            page2 = client.call_tool(
                "search_by_name",
                {"query": "a", "limit": 10, "cursor": result["cursor"]},
            )
            page1_pks = {it["pk"] for it in result["items"]}
            page2_pks = {it["pk"] for it in page2.get("items", [])}
            if page1_pks & page2_pks:
                raise AssertionError("Duplicate PKs across pages")
        return result

    runner.test("T-25 search_by_name pagination — no duplicates", t25)

    def t26():
        result = client.call_tool("search_by_name", {"query": "device", "limit": 5})
        if not result.get("cursor") or not result.get("items"):
            print("  (SKIP — insufficient results for cursor test)")
            return {"skipped": True}
        cursor = result["cursor"]
        page2 = client.call_tool(
            "search_by_name",
            {"query": "device", "limit": 5, "cursor": cursor},
        )
        assert page2.get("items"), "Second page should not be empty"
        return {"cursor_roundtrip": True}

    runner.test("T-26 search_by_name cursor round-trip", t26)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2e. Auth Enforcement (T-27 to T-29)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## Auth Enforcement")

    def t27():
        # Anonymous client (no token)
        anon = MCPClient(MCP_ENDPOINT, "a" * 40)
        result = anon.call_tool("device_list", {"limit": 5})
        # Must return empty, not error
        assert result.get("items") == [], f"Expected empty items for anonymous, got: {result}"
        return {"anonymous_empty": True}

    runner.test("T-27 Anonymous (no/invalid token) — empty results, no error", t27)

    def t28():
        # Valid token — assert data is present (DB must be populated)
        result = client.call_tool("device_list", {"limit": 5})
        has_data = len(result.get("items", [])) > 0
        assert has_data, "T-28 requires a populated DB; no devices found"
        return {"has_data": has_data}

    runner.test("T-28 Valid token — returns data", t28)

    def t29():
        # Write-only token scenario (simulated with invalid token)
        limited = MCPClient(MCP_ENDPOINT, "0" * 40)
        result = limited.call_tool("device_list", {"limit": 5})
        assert result.get("items") == [], "Invalid token should return empty"
        return {"restricted_empty": True}

    runner.test("T-29 Invalid token — empty results (not error)", t29)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 3. Performance Tests (P-01 to P-08)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## Performance Tests")

    def p01():
        t0 = time.perf_counter()
        result = client.call_tool("device_list", {"limit": 1000})
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  device_list limit=1000: {elapsed:.0f}ms ({len(result.get('items', []))} items)")
        assert elapsed < 5000, f"device_list(1000) took {elapsed:.0f}ms > 5000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-01 device_list(limit=1000) < 5s", p01)

    def p02():
        t0 = time.perf_counter()
        result = client.call_tool("device_list", {"limit": 50})
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  device_list limit=50: {elapsed:.0f}ms")
        assert elapsed < 2000, f"device_list(50) took {elapsed:.0f}ms > 2000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-02 device_list(limit=50) < 2s", p02)

    def p03():
        devices = client.call_tool("device_list", {"limit": 3})
        if not devices.get("items"):
            print("  (SKIP — no devices)")
            return {"skipped": True}
        for dev in devices["items"][:1]:
            t0 = time.perf_counter()
            ifaces = client.call_tool("interface_list", {"device_name": dev["name"], "limit": 100})
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"\n  interface_list({dev['name']}): {elapsed:.0f}ms ({len(ifaces.get('items', []))} ifaces)")
            assert elapsed < 3000, f"interface_list took {elapsed:.0f}ms > 3000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-03 interface_list on device < 3s", p03)

    def p04():
        t0 = time.perf_counter()
        result = client.call_tool("ipaddress_list", {"limit": 1000})
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  ipaddress_list limit=1000: {elapsed:.0f}ms ({len(result.get('items', []))} items)")
        assert elapsed < 5000, f"ipaddress_list(1000) took {elapsed:.0f}ms > 5000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-04 ipaddress_list(limit=1000) < 5s", p04)

    def p05():
        t0 = time.perf_counter()
        result = client.call_tool("search_by_name", {"query": "a", "limit": 100})
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  search_by_name('a'): {elapsed:.0f}ms ({len(result.get('items', []))} results)")
        assert elapsed < 10000, f"search_by_name took {elapsed:.0f}ms > 10000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-05 search_by_name single term < 10s", p05)

    def p06():
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices)")
            return {"skipped": True}
        dev_name = devices["items"][0]["name"]
        t0 = time.perf_counter()
        result = client.call_tool("device_get", {"name_or_id": dev_name})
        elapsed = (time.perf_counter() - t0) * 1000
        n_ifaces = len(result.get("interfaces", []))
        print(f"\n  device_get({dev_name}): {elapsed:.0f}ms ({n_ifaces} interfaces)")
        assert elapsed < 5000, f"device_get took {elapsed:.0f}ms > 5000ms"
        return {"elapsed_ms": elapsed, "interfaces": n_ifaces}

    runner.test("P-06 device_get with interfaces < 5s", p06)

    def p07():
        t0 = time.perf_counter()
        result = client.call_tool("search_by_name", {"query": "a b", "limit": 50})
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  search_by_name('a b'): {elapsed:.0f}ms")
        assert elapsed < 10000
        return {"elapsed_ms": elapsed}

    runner.test("P-07 search_by_name multi-term < 10s", p07)

    def p08():
        import concurrent.futures

        t0 = time.perf_counter()

        def call_device_list():
            return client.call_tool("device_list", {"limit": 20})

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futures = [ex.submit(call_device_list) for _ in range(2)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        elapsed = (time.perf_counter() - t0) * 1000
        print(f"\n  2 concurrent device_list calls: {elapsed:.0f}ms")
        assert all(r.get("items") is not None for r in results), "Some requests failed"
        assert elapsed < 30000, f"Concurrent load took {elapsed:.0f}ms > 30000ms"
        return {"elapsed_ms": elapsed}

    runner.test("P-08 Concurrent 2 parallel requests < 30s", p08)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 4. GraphQL Tools (T-37 to T-43)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    print("\n## GraphQL Tools")

    def t37():
        # Note: uses `limit` (not `first`) and `status { name }` (status is non-nullable enum)
        result = client.call_tool("graphql_query", {"query": "{ devices(limit: 5) { name status { name } } }"})
        assert "data" in result, "Result must have 'data' key"
        assert "errors" in result, "Result must have 'errors' key"
        assert result["data"] is not None, f"Expected data, got: {result}"
        return result

    runner.test("T-37 graphql_query valid query — data returned, no errors", t37)

    def t38():
        result = client.call_tool(
            "graphql_query",
            {
                "query": "{ devices {"  # unclosed brace — syntax error
            },
        )
        assert "data" in result
        assert "errors" in result
        assert result["data"] is None, "Syntax error → data must be None"
        assert result["errors"] is not None and len(result["errors"]) > 0
        assert "Syntax Error" in result["errors"][0]["message"]
        return {"syntax_error_handled": True}

    runner.test("T-38 graphql_query syntax error — structured errors dict, no HTTP 500", t38)

    def t39():
        sdl = client.call_tool("graphql_introspect", {})
        assert isinstance(sdl, str), "Introspect must return string"
        assert len(sdl) > 50, "SDL should be > 50 chars"
        assert "type Query" in sdl, "SDL must contain 'type Query'"
        return {"sdl_length": len(sdl)}

    runner.test("T-39 graphql_introspect returns valid SDL schema string", t39)

    def t40():
        anon = MCPClient(MCP_ENDPOINT, "a" * 40)
        result = anon.call_tool("graphql_query", {"query": "{ devices { name } }"})
        assert "data" in result
        assert "errors" in result
        # graphql_query returns dict with auth error, not exception
        assert result["data"] is None, f"Anonymous should get no data, got: {result}"
        assert result["errors"] is not None and len(result["errors"]) > 0
        assert any(
            "Authentication" in str(e) for e in (result["errors"] or [])
        ), f"Expected auth error, got: {result['errors']}"
        return {"anonymous_restricted": True}

    runner.test("T-40 graphql_query anonymous token — auth error dict returned", t40)

    def t41():
        # Note: uses `limit` (not `first`) and `status { name }` (non-nullable enum)
        result = client.call_tool(
            "graphql_query",
            {"query": "query GetDevices($limit: Int!) { devices(limit: $limit) { name status { name } } }", "variables": {"limit": 3}},
        )
        assert "data" in result
        assert result["data"] is not None, f"Variables query failed: {result}"
        return {"variables_working": True}

    runner.test("T-41 graphql_query variables injection — data returned", t41)

    def t42():
        # Note: uses `limit` (not `first`) and `status { name }` (non-nullable enum)
        result = client.call_tool("graphql_query", {"query": "{ devices(limit: 3) { name status { name } } }"})
        assert "data" in result
        assert result["data"] is not None, "Valid token → data must not be None"
        return {"token_authorized": True}

    runner.test("T-42 graphql_query valid token — full data access", t42)

    def t43():
        # Structured error handling — graphql_query returns errors dict, not MCPToolError.
        # Depth-limit and complexity-exceeded are enforced by graphql_validation rules.
        # Confirm the server returns HTTP 200 with a structured errors dict (no exception).
        # T-38 already covers "Syntax Error" for unclosed-brace; T-43 targets field errors.
        result = client.call_tool(
            "graphql_query",
            {"query": "{ devices(limit: 5) { nonexistent_field } }"},
        )
        assert result["data"] is None
        assert result["errors"] is not None and len(result["errors"]) > 0
        assert any(
            "nonexistent_field" in str(e) or "Unknown field" in str(e)
            for e in result["errors"]
        ), f"Expected field-not-found error, got: {result['errors']}"
        return {"structured_field_errors_verified": True}

    runner.test("T-43 graphql_query structured field errors — no exception thrown", t43)

    # ---------------------------------------------------------------------------
    # Print results
    # ---------------------------------------------------------------------------

    print()
    all_passed = runner.summary()

    print("\n## Test Case Summary by Category")

    categories = {
        "Auth & Session": ["T-01", "T-02", "T-03", "T-04"],
        "List Tools": ["T-05", "T-06", "T-07", "T-08", "T-09", "T-10", "T-11", "T-12", "T-13"],
        "Get Tools": ["T-14", "T-15", "T-16", "T-17", "T-18", "T-19", "T-20", "T-21"],
        "Search": ["T-22", "T-23", "T-24", "T-25", "T-26"],
        "Auth Enforcement": ["T-27", "T-28", "T-29"],
        "GraphQL Tools": ["T-37", "T-38", "T-39", "T-40", "T-41", "T-42", "T-43"],
        "Performance": ["P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "P-07", "P-08"],
    }

    for cat, tests in categories.items():
        cat_results = [r for r in runner.results if any(t in r.name for t in tests)]
        passed = sum(1 for r in cat_results if r.passed)
        total = len(cat_results)
        marker = "✅" if passed == total else "⚠️"
        print(f"  {marker} {cat}: {passed}/{total} passed")

    return all_passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        success = run_uat()
        sys.exit(0 if success else 1)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(2)
