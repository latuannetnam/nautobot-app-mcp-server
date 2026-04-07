# Phase 13: UAT & Validation — Discussion Log

**Gathered:** 2026-04-06

---

## Discussion Round 1: Phase 13 Scope Framing

### What is Phase 13?

Phase 13 is the final integration gate for v1.2.0. The separate-process refactor (Option A → Option B) is mechanically complete: Phases 7–12 delivered the new architecture. Phase 13 validates that everything works end-to-end.

**Requirements (P6-01–P6-05):**
- P6-01: UAT scripts updated to port 8005
- P6-02: Token auth UAT passes
- P6-03: Session UAT passes
- P6-04: All unit tests pass
- P6-05: UAT smoke test exits 0

### Gray Areas Identified

#### G-01: MCP server container lifecycle

The `mcp` service in `docker-compose.dev.yml` has `entrypoint: "tail -f /dev/null"` — a placeholder from Phase 8 that was never wired up. The ROADMAP says "MCP server runs as its own service" but doesn't specify how to start it.

**Options:**
- **Option A:** Auto-start (`entrypoint: "nautobot-server start_mcp_dev_server"`). Simpler, but MCP server restarts on every `invoke start`.
- **Option B:** On-demand (`docker compose up mcp`). Lighter footprint, more production-realistic.
- **Option C:** Separate `mcp-server` service in a new `docker-compose.mcp.yml` override. Cleanest separation; doesn't touch the existing `mcp` placeholder in dev.

**Decision:** Option C. The new `docker-compose.mcp.yml` file replaces the placeholder `mcp` service entirely.

#### G-02: UAT test execution context

Where does the UAT smoke test run?

**Options:**
- **From mcp container:** `docker exec mcp-1 python /source/scripts/run_mcp_uat.py`
- **From host (poetry run):** `poetry run python scripts/run_mcp_uat.py`
- **Both contexts supported**

**Decision:** From host (poetry run). The UAT script runs from the host, hitting `http://localhost:8005/mcp/` via Docker port mapping.

#### G-03: run_mcp_uat.py endpoint URL

The script hardcodes `http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` (old embedded endpoint). Must change.

**Options:**
- `http://localhost:8005/mcp/` (separate process)
- Keep `http://localhost:8080` as fallback

**Decision:** `http://localhost:8005/mcp/`. The MCP server is no longer at port 8080. Users who want a custom endpoint set `MCP_DEV_URL` explicitly.

#### G-04: Token for UAT auth

Where does a valid 40-char hex token come from?

**Decision:** `NAUTOBOT_SUPERUSER_API_TOKEN` from `creds.env` (already the default fallback in the script). No change needed.

#### G-05: invoke start behavior

Should `invoke start` also bring up the MCP server?

**Decision:** Yes — via the new `docker-compose.mcp.yml` included in `compose_files`. `invoke start` now starts both Nautobot (8080) and MCP server (8005).

---

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| G-01 | Option C: new `docker-compose.mcp.yml` with `mcp-server` service | Cleanest separation; replaces placeholder `mcp` service entirely |
| G-02 | From host via `poetry run python scripts/run_mcp_uat.py` | Works with Docker port mapping `8005:8005`; no container exec needed |
| G-03 | `http://localhost:8005/mcp/` as default | Old embedded endpoint (8080) no longer exists; must point to new port |
| G-04 | `NAUTOBOT_SUPERUSER_API_TOKEN` from `creds.env` | Already the default fallback; no code change needed |
| G-05 | `invoke start` includes `docker-compose.mcp.yml` | Users get a working stack with both servers; no extra commands needed |

---

## Implementation Summary

Phase 13 has **mechanical work** (3 files: new compose file, modified tasks.py, modified run_mcp_uat.py) and **verification work** (run tests, verify UAT passes). No architectural decisions needed — all were made in Phases 7–12.

**Phase 13 plan structure (5 plans):**
- 13-01: Create `docker-compose.mcp.yml` + add to `compose_files` + remove placeholder `mcp` service from dev compose
- 13-02: Update `run_mcp_uat.py` endpoint default to port 8005
- 13-03: Run unit tests (`invoke unittest` / `nautobot-server test`)
- 13-04: Start stack, verify MCP server container is running
- 13-05: Run UAT smoke test (`poetry run python scripts/run_mcp_uat.py`) → exit 0

---

---

## Discussion Round 2: FastMCP `outputSchema` Bug (2026-04-07)

### Symptom

UAT run revealed that `device_get`, `interface_list`, `ipaddress_list`, `prefix_list`, `vlan_list`, `location_list`, and `search_by_name` all returned:
```
"Output validation error: outputSchema defined but no structured output returned"
```

### Root Cause Analysis

**Execution path for FastMCP 3.2.0 HTTP transport:**

```
HTTP POST /mcp/ (tools/call)
  → StreamableHTTPSessionManager.handle_request()
    → MCP SDK ServerSession._handle_message()
      → LowLevelServer.request_handlers[CallToolRequest]
        → mcp.server.lowlevel.server.handle_call_tool()   ← validation fires HERE
        → FastMCP._call_tool_mcp()                      ← NOT reached
        → FastMCP.call_tool()
          → tool._run()
            → FunctionTool.run()
              → convert_result() → ToolResult
```

**The chain:**
1. FastMCP `FunctionTool.from_function()` derives `output_schema` from return annotation `dict[str, Any]` → `{"type": "object"}`
2. `tool.to_mcp_tool()` exposes this as the MCP `Tool.outputSchema`
3. MCP SDK `handle_call_tool()` checks: if `tool.outputSchema is not None AND maybe_structured_content is None` → error
4. Our `convert_result()` returns `ToolResult(content=[TextContent(...)], structured_content=None)` (no structured content because result is not JSON-parseable as structured)
5. MCP SDK detects mismatch → `"Output validation error: outputSchema defined but no structured output returned"`

**Why `device_list` worked**: Different result structure or timing — the same error applies, but it may have been handled differently in FastMCP's internal path.

### Temporary Fix Applied

Patched `fastmcp/tools/function_tool.py` in the running container:
```python
# Line 234
output_schema=None,  # Force None to avoid MCP SDK output validation errors
```

### Why This Fix is Not Clean

1. **Doesn't survive `invoke build`**: The patch lives in `/usr/local/lib/python3.12/site-packages/fastmcp/` inside the container image. `invoke build` rebuilds the image from scratch, removing the patch.
2. **Not in source control**: The patch is applied via `docker exec` — not committed anywhere.
3. **Fragile**: Relies on line number staying at 234 in future FastMCP versions.

### Alternative Approaches (to discuss)

See `docs/dev/patch_fastmcp_issue.md` for full analysis.

*Discussion: 2026-04-07*
*Phase: 13-uat-validation*
