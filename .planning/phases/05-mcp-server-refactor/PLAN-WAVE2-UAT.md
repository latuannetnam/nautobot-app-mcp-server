---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified: []
autonomous: false
---

# Phase 5 — Wave 2 Task: WAVE2-UAT

**Task ID:** WAVE2-UAT
**Requirements:** TEST-03
**Priority:** P0
**Note:** This is an external verification task — no code changes. Executor runs smoke tests.

---

## read_first

- `docs/dev/import_and_uat.md` — UAT procedure and expected setup
- `scripts/run_mcp_uat.py` — the UAT script being executed (read before running)
- `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — the integration test from WAVE2-TEST-INTEGRATION

---

## context

**TEST-03** requires that the UAT smoke tests pass. The UAT script (`scripts/run_mcp_uat.py`) exercises the MCP endpoint end-to-end with a real Nautobot database. After the Phase 5 refactor fixes `asyncio.run()` → `async_to_sync`, the UAT should now show:

1. Session state persists across multiple MCP HTTP requests
2. `mcp_enable_tools(scope="dcim")` enables `dcim` tools
3. `mcp_list_tools` reflects enabled scopes
4. Auth works with Nautobot Token
5. `Server.request_context.get()` succeeds inside tool handlers (no `LookupError`)

If the UAT was previously broken (due to the P0 `asyncio.run()` issue), it should now pass. If it still fails, the refactor is incomplete.

---

## action

### Step 1: Verify Docker container is running

```bash
docker ps | grep nautobot-app-mcp-server
```

If not running, start it:
```bash
poetry run invoke start
docker exec -it nautobot-app-mcp-server-nautobot-1 bash
```

### Step 2: Run the UAT smoke test script

Inside the container:
```bash
docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py
```

Or if the script needs a Nautobot shell:
```bash
docker exec nautobot-app-mcp-server-nautobot-1 bash -c "cd /source && poetry run python scripts/run_mcp_uat.py"
```

### Step 3: Inspect UAT output

**Expected success indicators:**
- Session state persists: `mcp_enable_tools(scope="dcim")` succeeds and subsequent `mcp_list_tools` shows `dcim` tools
- Auth: valid `Authorization: Token nbapikey_...` returns data; missing token returns empty + warning log
- `Server.request_context.get()`: no `LookupError` in tool handler logs
- Endpoint reachable: HTTP 200 responses for MCP JSON-RPC requests

**If UAT fails:** Check which step failed and return to the relevant task:
- Auth failure → check `auth.py` (WAVE1-AUTH)
- Session not persisting → check `view.py` bridge (WAVE2-VIEW)
- `Server.request_context.get()` error → check `session_tools.py` (WAVE1-SESSION)
- Endpoint unreachable → check `server.py` singletons (WAVE1-SERVER)

### Step 4: Run the integration test directly

If `run_mcp_uat.py` is not available or incomplete, run the integration test directly:
```bash
docker exec nautobot-app-mcp-server-nautobot-1 bash -c \
  "cd /source && poetry run python -m pytest \
     nautobot_app_mcp_server/mcp/tests/test_session_persistence.py \
     -v --tb=short"
```

---

## acceptance_criteria

1. `docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py` exits with code 0 — UAT smoke tests pass
2. OR `poetry run python -m pytest nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` inside the container exits with 0 — integration tests pass
3. UAT output shows `mcp_enable_tools(scope="dcim")` followed by `mcp_list_tools` showing `dcim` tools (session persistence verified)
4. No `LookupError` in container logs during UAT run (`grep "LookupError" /dev/null || echo "no LookupError"`)
5. `docker ps` shows container is healthy and running
