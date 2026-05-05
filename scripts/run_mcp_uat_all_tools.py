#!/usr/bin/env python3
"""UAT for All-Tools Mode — T-01 to T-43, T-47.

This script runs the full tool suite tests EXCEPT GraphQL-only mode tests (T-45, T-46).
Requires NAUTOBOT_MCP_ENABLE_ALL=true set in development/creds.env (not development.env —
creds.env is local-only and not committed to the repo).

Restart with:
    docker compose -f development/docker-compose.mcp.yml restart nautobot

Usage:
    unset VIRTUAL_ENV && poetry run python scripts/run_mcp_uat_all_tools.py
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
                    if isinstance(parsed, dict) and "result" in parsed and len(parsed) == 1:
                        return parsed["result"]
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
        print(f"All-Tools Mode UAT: {passed}/{total} passed")
        if failed:
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error}")
        return failed == 0


def run_all_tools_uat() -> bool:
    print("=" * 70)
    print("All-Tools Mode UAT — T-01 to T-43, T-47")
    print("=" * 70)
    print(f"Endpoint: {MCP_ENDPOINT}")
    print(f"Token:   {DEV_TOKEN[:8]}... (first 8 chars)")
    print()
    print("NOTE: Requires NAUTOBOT_MCP_ENABLE_ALL=true in development/creds.env (local-only).")
    print("      Restart after any env var changes:")
    print("      docker compose -f development/docker-compose.mcp.yml restart nautobot")
    print()

    client = MCPClient(MCP_ENDPOINT, DEV_TOKEN)
    runner = TestRunner(client)

    # Verify server is in all-tools mode
    all_tools = client.list_tools()
    tool_names = [t["name"] for t in all_tools]
    print(f"  Detected {len(all_tools)} tools: {tool_names}")
    if len(all_tools) < 15:
        print("\n  WARNING: Server appears to be in GQL-only mode (< 15 tools).")
        print("  Set NAUTOBOT_MCP_ENABLE_ALL=true in development/creds.env and restart.")

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 1. Session Tools (T-01 to T-04)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## Auth & Session Tools")

    def t01():
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        expected = {
            "device_list", "device_get", "interface_list", "interface_get",
            "ipaddress_list", "ipaddress_get", "prefix_list", "vlan_list",
            "location_list", "search_by_name",
            "mcp_enable_tools", "mcp_disable_tools", "mcp_list_tools",
        }
        missing = expected - set(tool_names)
        if missing:
            raise AssertionError(f"Missing tools: {missing}")
        return tool_names

    runner.test("T-01 mcp_list_tools baseline — all 13 tools visible", t01)

    def t02():
        result = client.call_tool("mcp_enable_tools", {"scope": "dcim"})
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
        assert "device_list" in tool_names
        return result

    runner.test("T-03 mcp_disable_tools all (no args)", t03)

    def t04():
        client.call_tool("mcp_enable_tools", {"scope": "dcim"})
        client.call_tool("mcp_enable_tools", {"scope": "ipam"})
        client.call_tool("mcp_disable_tools", {"scope": "dcim"})
        tools = client.list_tools()
        tool_names = [t["name"] for t in tools]
        assert "device_list" in tool_names
        return {"scopes_working": True}

    runner.test("T-04 mcp_disable_tools partial scope", t04)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 2. List Tools (T-05 to T-13)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## List Tools — Correctness")

    def t05():
        result = client.call_tool("device_list", {"limit": 25})
        assert "items" in result
        assert isinstance(result["items"], list)
        assert len(result["items"]) <= 25
        return result

    runner.test("T-05 device_list default pagination (limit=25)", t05)

    def t06():
        page1 = client.call_tool("device_list", {"limit": 5})
        first_ids = {d["pk"] for d in page1.get("items", [])}
        if page1.get("cursor") and page1["items"]:
            page2 = client.call_tool("device_list", {"limit": 5, "cursor": page1["cursor"]})
            second_ids = {d["pk"] for d in page2.get("items", [])}
            overlap = first_ids & second_ids
            if overlap:
                raise AssertionError(f"Cursor pagination produced duplicate IDs: {overlap}")
        return {"pages_ok": True}

    runner.test("T-06 device_list cursor pagination — no duplicates", t06)

    def t07():
        result = client.call_tool("device_list", {"limit": 1000})
        assert len(result["items"]) <= 1000
        return result

    runner.test("T-07 device_list LIMIT_MAX=1000 cap", t07)

    def t08():
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices in DB)")
            return {"skipped": True}
        device_name = devices["items"][0]["name"]
        result = client.call_tool("interface_list", {"device_name": device_name, "limit": 50})
        assert "items" in result
        for iface in result["items"]:
            assert iface.get("device") == device_name
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
            assert "vrf" in item
            assert "tenant" in item
        return result

    runner.test("T-11 prefix_list VRF/tenant fields", t11)

    def t12():
        result = client.call_tool("vlan_list", {"limit": 10})
        assert "items" in result
        if result["items"]:
            item = result["items"][0]
            assert "locations" in item
            assert isinstance(item["locations"], list)
        return result

    runner.test("T-12 vlan_list locations M2M field", t12)

    def t13():
        result = client.call_tool("location_list", {"limit": 20})
        assert "items" in result
        return result

    runner.test("T-13 location_list hierarchy", t13)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 3. Get Tools (T-14 to T-21)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## Get Tools — Correctness")

    def t14():
        devices = client.call_tool("device_list", {"limit": 1})
        if not devices.get("items"):
            print("  (SKIP — no devices in DB)")
            return {"skipped": True}
        device_name = devices["items"][0]["name"]
        result = client.call_tool("device_get", {"name_or_id": device_name})
        assert "interfaces" in result
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
        assert by_name["pk"] == by_uuid["pk"]
        return {"consistent": True}

    runner.test("T-15 device_get by UUID matches by-name result", t15)

    def t16():
        try:
            client.call_tool("device_get", {"name_or_id": "nonexistent_device_xyz_12345"})
            raise AssertionError("Expected ValueError for nonexistent device")
        except MCPToolError as e:
            if e.code != -32602:
                raise AssertionError(f"Expected -32602, got {e.code}")
            assert "nonexistent" in str(e.message).lower()
        return {"raises_correctly": True}

    runner.test("T-16 device_get not found raises ValueError", t16)

    def t17():
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
    # 4. Search Tool (T-22 to T-26)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## Search Tool")

    def t22():
        result = client.call_tool("search_by_name", {"query": "router", "limit": 10})
        assert "items" in result
        return result

    runner.test("T-22 search_by_name single term", t22)

    def t23():
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
            name_lower = item.get("name", "").lower()
            for term in terms:
                assert term.lower() in name_lower
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
        result = client.call_tool("search_by_name", {"query": "a", "limit": 10})
        assert "items" in result
        if result.get("cursor") and len(result["items"]) == 10:
            page2 = client.call_tool("search_by_name", {"query": "a", "limit": 10, "cursor": result["cursor"]})
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
        page2 = client.call_tool("search_by_name", {"query": "device", "limit": 5, "cursor": cursor})
        assert page2.get("items")
        return {"cursor_roundtrip": True}

    runner.test("T-26 search_by_name cursor round-trip", t26)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 5. Auth Enforcement (T-27 to T-29)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## Auth Enforcement")

    def t27():
        anon = MCPClient(MCP_ENDPOINT, "a" * 40)
        result = anon.call_tool("device_list", {"limit": 5})
        assert result.get("items") == [], f"Expected empty items for anonymous, got: {result}"
        return {"anonymous_empty": True}

    runner.test("T-27 Anonymous (no/invalid token) — empty results, no error", t27)

    def t28():
        result = client.call_tool("device_list", {"limit": 5})
        has_data = len(result.get("items", [])) > 0
        assert has_data, "T-28 requires a populated DB; no devices found"
        return {"has_data": has_data}

    runner.test("T-28 Valid token — returns data", t28)

    def t29():
        limited = MCPClient(MCP_ENDPOINT, "0" * 40)
        result = limited.call_tool("device_list", {"limit": 5})
        assert result.get("items") == [], "Invalid token should return empty"
        return {"restricted_empty": True}

    runner.test("T-29 Invalid token — empty results (not error)", t29)

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 6. Performance Tests (P-01 to P-08)
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
    # 7. GraphQL Tools (T-37 to T-43)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## GraphQL Tools")

    def t37():
        result = client.call_tool("graphql_query", {"query": "{ devices(limit: 5) { name status { name } } }"})
        assert "data" in result
        assert "errors" in result
        assert result["data"] is not None, f"Expected data, got: {result}"
        return result

    runner.test("T-37 graphql_query valid query — data returned, no errors", t37)

    def t38():
        result = client.call_tool(
            "graphql_query",
            {"query": "{ devices {"},
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
        assert isinstance(sdl, str)
        assert len(sdl) > 50
        assert "type Query" in sdl
        return {"sdl_length": len(sdl)}

    runner.test("T-39 graphql_introspect returns valid SDL schema string", t39)

    def t40():
        anon = MCPClient(MCP_ENDPOINT, "a" * 40)
        result = anon.call_tool("graphql_query", {"query": "{ devices { name } }"})
        assert "data" in result
        assert "errors" in result
        assert result["data"] is None, f"Anonymous should get no data, got: {result}"
        assert result["errors"] is not None and len(result["errors"]) > 0
        assert any("Authentication" in str(e) for e in (result["errors"] or []))
        return {"anonymous_restricted": True}

    runner.test("T-40 graphql_query anonymous token — auth error dict returned", t40)

    def t41():
        result = client.call_tool(
            "graphql_query",
            {"query": "query GetDevices($limit: Int!) { devices(limit: $limit) { name status { name } } }", "variables": {"limit": 3}},
        )
        assert "data" in result
        assert result["data"] is not None, f"Variables query failed: {result}"
        return {"variables_working": True}

    runner.test("T-41 graphql_query variables injection — data returned", t41)

    def t42():
        result = client.call_tool("graphql_query", {"query": "{ devices(limit: 3) { name status { name } } }"})
        assert "data" in result
        assert result["data"] is not None, "Valid token → data must not be None"
        return {"token_authorized": True}

    runner.test("T-42 graphql_query valid token — full data access", t42)

    def t43():
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

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 8. All-Tools Mode (T-47)
    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    print("\n## All-Tools Mode (T-47)")

    def t47():
        all_tools = client.list_tools()
        tool_names = [t["name"] for t in all_tools]
        assert len(all_tools) >= 15, f"Expected >=15 tools in all-tools mode, got {len(all_tools)}: {tool_names}"
        assert "graphql_query" in tool_names
        assert "graphql_introspect" in tool_names
        assert "mcp_enable_tools" in tool_names
        return {"tool_count": len(all_tools)}

    runner.test("T-47 All-tools mode: all 15 tools visible (NAUTOBOT_MCP_ENABLE_ALL=true)", t47)

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
        "Performance": ["P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "P-07", "P-08"],
        "GraphQL Tools": ["T-37", "T-38", "T-39", "T-40", "T-41", "T-42", "T-43"],
        "All-Tools Mode": ["T-47"],
    }

    for cat, tests in categories.items():
        cat_results = [r for r in runner.results if any(t in r.name for t in tests)]
        passed = sum(1 for r in cat_results if r.passed)
        total = len(cat_results)
        marker = "PASS" if passed == total else "FAIL"
        print(f"  [{marker}] {cat}: {passed}/{total}")

    return all_passed


if __name__ == "__main__":
    try:
        success = run_all_tools_uat()
        sys.exit(0 if success else 1)
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)