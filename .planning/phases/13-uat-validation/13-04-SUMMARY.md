---
wave: 1
plan_id: 13-04
status: complete
completed: 2026-04-06
---

## Plan 13-04: Start Stack & Verify MCP Server on Port 8005

### Objective

Verify `invoke start` brings up `mcp-server` container on port 8005 and the standalone FastMCP server responds correctly.

---

## Execution Summary

### Issues Found and Fixed

The initial `docker-compose.mcp.yml` from plan 13-01 had three problems that caused the mcp-server container to crash or restart in a loop:

#### Issue 1: Wrong entrypoint (caused DB thread error)

**Original (broken):**
```yaml
entrypoint:
  - "bash"
  - "-c"
  - >
    exec uvicorn nautobot_app_mcp_server.mcp.commands:mcp_app_factory
      --factory --host 0.0.0.0 --port 8005 ...
```

**Problem:** `uvicorn --factory` expects an import string, not a module attribute. This caused `ModuleNotFoundError` or, when corrected, ran `create_app()` in the wrong thread context, triggering:
```
RuntimeError: Database connectivity check failed:
  DatabaseWrapper objects created in a thread can only be used in that same thread.
```

**Fix:** Replaced with `command: nautobot-server start_mcp_dev_server --host 0.0.0.0` — the management command handles threading correctly.

#### Issue 2: `sync_to_async` DB check (caused async context error)

**Original:**
```python
_check_db = sync_to_async(connection.ensure_connection)
asyncio.get_event_loop().run_until_complete(_check_db())
```

**Problem:** `run_until_complete` raises `"You cannot call this from an async context"` when called from uvicorn's async event loop (with `--factory`).

**Fix:** Removed the explicit DB check entirely. The docker-compose `depends_on: db: service_healthy` gate plus uvicorn's lifespan startup is sufficient.

#### Issue 3: `uvicorn.run(mcp_app, ...)` without `factory=True` (reload warning)

**Original:**
```python
uvicorn.run(mcp_app, host=bound_host, port=bound_port, reload=True, ...)
```

**Problem:** uvicorn logs: `"You must pass the application as an import string to enable 'reload' or 'workers'."` — reload did not work.

**Fix:**
```python
uvicorn.run(
    "nautobot_app_mcp_server.mcp.commands:mcp_app_factory",
    host=bound_host, port=bound_port,
    reload=True, reload_dirs=[...],
    factory=True,
)
```

#### Issue 4: Healthcheck used `curl` (not installed in image)

**Original:**
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://127.0.0.1:8005/mcp/"]
```

**Problem:** `curl` is not installed in the Nautobot base image → healthcheck always fails → container restarts continuously.

**Fix:** Python-based POST with MCP JSON-RPC `initialize` call (no trailing slash, correct headers):
```yaml
healthcheck:
  test: ["CMD-SHELL", "python -c \"import urllib.request; r=urllib.request.Request('http://127.0.0.1:8005/mcp', data=b'{\\\"jsonrpc\\\":\\\"2.0\\\",\\\"id\\\":1,\\\"method\\\":\\\"initialize\\\",\\\"params\\\":{\\\"protocolVersion\\\":\\\"2024-11-05\\\",\\\"clientInfo\\\":{\\\"name\\\":\\\"healthcheck\\\",\\\"version\\\":\\\"1\\\"},\\\"capabilities\\\":{}}}', headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}, method='POST'); urllib.request.urlopen(r, timeout=10)\""]
  start_period: "120s"
```

#### Issue 5: `start_period: 30s` too short

Nautobot takes ~45–60s to boot. Short `start_period` caused premature unhealthy → restart loop.

**Fix:** Increased to `start_period: 120s`.

---

## Acceptance Criteria Results

| Criterion | Result |
|---|---|
| `docker ps` shows `nautobot-app-mcp-server-mcp-server-1` as `running` | ✅ |
| Port 8005 returns HTTP 200 (MCP `initialize`) | ✅ |
| Old endpoint `http://localhost:8080/plugins/.../mcp/` returns 404 (Phase 12 gate) | ✅ |
| Container logs show FastMCP startup — no RuntimeError | ✅ |
| Container healthcheck passes (Python POST healthcheck) | ✅ |

### Files Modified

| File | Change |
|---|---|
| `development/docker-compose.mcp.yml` | Simplified `command: nautobot-server start_mcp_dev_server --host 0.0.0.0`; Python healthcheck; `start_period: 120s` |
| `nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` | `uvicorn.run(..., factory=True)` with import string for reload support |
| `nautobot_app_mcp_server/mcp/commands.py` | Removed broken `sync_to_async` DB check; STEP 2 now skips explicit DB check |

### Commands Run

```bash
poetry run invoke build   # Rebuild image with fixed code
poetry run invoke start   # Start full stack including mcp-server

# Verification:
curl -X POST http://localhost:8005/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1"},"capabilities":{}}}'
# → HTTP 200
```
