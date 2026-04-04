---
wave: 1
autonomous: true
---

# Phase 6 — UAT & Validation

## Phase Goal

**TEST-03:** `docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py` exits with code 0.

All 37 UAT test cases pass. Phase 5 refactor (lifecycle-managed FastMCP, session persistence, auth caching) is validated end-to-end in the live Docker environment.

---

## Pre-Research Findings (Orchestrator-Verified)

Three pre-existing issues block all 37 UAT tests — none are caused by Phase 5 code.

### Issue A — PLUGINS Not Enabled (Root Cause of 404 on All 37 Tests)

- `nautobot_config.py` line 122 sets `PLUGINS = ["nautobot_app_mcp_server"]` — correct.
- Therefore the MCP endpoint **is already mounted** at `/plugins/nautobot-app-mcp-server/mcp/`.
- `scripts/run_mcp_uat.py` line 45 uses `MCP_ENDPOINT = f"{DEV_URL}/plugins/nautobot-app-mcp-server/mcp/"` — **correct URL**.
- The orchestrator's curl diagnosis of 404 may reflect a stale container or stopped server, not an actual URL mismatch.
- **Fix:** Ensure the Docker container is running with the latest config (`poetry run invoke start`), then verify the endpoint is reachable.

### Issue B — APPEND_SLASH Redirect (Would Break POST Requests If Hit)

- Nautobot has `APPEND_SLASH=True`.
- Requests to `/mcp` (no trailing slash) redirect 307 to `/mcp/` — FastMCP is mounted at `/mcp/` (with slash).
- UAT uses `/plugins/nautobot-app-mcp-server/mcp/` (with trailing slash) — **no redirect triggered**.
- The `mcp_view` has `@csrf_exempt` and `requests.post()` sends `Content-Type: application/json`.
- `resp.raise_for_status()` in `MCPClient.call()` would raise on any 307/301.
- **Fix:** UAT URL already correct; no change needed. If 307 is observed, check that the URL has a trailing slash.

### Issue C — Auth Token Format Mismatch (T-27/T-29 Would Fail)

- `auth.py` strips `Token ` prefix and looks up the raw 40-char hex key.
- T-27 uses `nbapikey_invalid_token_00000000000000` (27 chars) — never matches any real token.
- T-29 uses `nbapikey_invalid_write_only_token_00000` (36 chars) — never matches.
- These tests verify anonymous/invalid-token behavior (empty results, no error).
- **Fix:** The anonymous/invalid behavior is already correct — the test tokens don't need to look like real tokens. They just need to not exist in the DB. Since neither token is a valid 40-char hex token, they correctly fall through to `AnonymousUser`.
- **However:** The `Token.objects.select_related("user").get(key=token_key)` lookup on line 78 will raise `Token.DoesNotExist` for any non-40-char key, which is caught by the bare `except Exception` and returns `AnonymousUser` — **correct behavior**.
- No UAT token change required.

---

## Summary of Required Actions

Only one task is needed: **verify the live Docker server is running, confirm endpoint reachability, and run the UAT**. All three "issues" from the orchestrator are non-issues given the actual code:

| Orchestrator Claim | Actual State | Action |
|---|---|---|
| PLUGINS=[] → 404 | `nautobot_config.py` has `PLUGINS=["nautobot_app_mcp_server"]` | Ensure container is live, verify endpoint |
| APPEND_SLASH → 307 | UAT uses trailing slash URL → no redirect | No change needed |
| Token prefix mismatch | `auth.py` looks up raw key; non-40-char tokens → AnonymousUser (correct) | No change needed |

**The UAT should pass as-is if the Docker container is running with the latest image.**

---

## Task 1 — Verify Live Server & Run UAT

### Task Summary

Ensure the Docker dev stack is running with the latest configuration, verify the MCP endpoint is reachable, then execute the full UAT suite. Confirm all 37 tests pass.

<read_first>
- `development/nautobot_config.py` — line 122: `PLUGINS = ["nautobot_app_mcp_server"]`
- `nautobot_app_mcp_server/urls.py` — line 16: `path("mcp/", mcp_view, name="mcp")`
- `scripts/run_mcp_uat.py` — lines 44–49: `MCP_ENDPOINT` URL and `DEV_TOKEN` config
- `nautobot_app_mcp_server/mcp/auth.py` — lines 52–86: token lookup and anonymous fallback
- `development/creds.env` — line 14: `NAUTOBOT_SUPERUSER_API_TOKEN=0123456789abcdef0123456789abcdef01234567`
- `nautobot_import.env` — line 16: `NAUTOBOT_DEV_TOKEN=0123456789abcdef0123456789abcdef01234567`
</read_first>

<acceptance_criteria>
1. `docker ps` shows `nautobot-app-mcp-server-nautobot-1` container is running.
2. `curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` returns `200` or `405` (not `307`, not `404`).
3. `docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py` exits with code 0.
4. UAT output contains `UAT Results: 37/37 passed` (or `37/N` where `N >= 37` and all failures are SKIP due to no data).
5. No `LookupError` for `Server.request_context.get()` appears in UAT output.
6. No `[FATAL]` prefix appears in UAT output.
</acceptance_criteria>

<action>

```bash
# 1. Ensure Docker dev stack is running
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server && poetry run invoke start
```

```bash
# 2. Wait for container to be healthy (up to 60s)
docker exec nautobot-app-mcp-server-nautobot-1 bash -c 'nautobot-server showmigrations | head -5'
```

```bash
# 3. Verify MCP endpoint is reachable (expect 200 or 405, NOT 307 or 404)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/
```

```bash
# 4. If step 3 returns 404, restart container to pick up latest config:
docker compose -f development/docker-compose.yml -f development/docker-compose.dev.yml -f development/docker-compose.postgres.yml -f development/docker-compose.redis.yml --project-directory /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server restart nautobot
# Then re-run step 3
```

```bash
# 5. Run the full UAT suite inside the container
docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py
```

</action>

---

## Expected UAT Output on Success

```
==================================================
nautobot-app-mcp-server UAT — Functional & Performance Tests
==================================================
Endpoint: http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/
Token:   0123456... (first 8 chars)

## Auth & Session Tools
## List Tools — Correctness
## Get Tools — Correctness
## Search Tool
## Auth Enforcement
## Performance Tests

==================================================
UAT Results: 37/37 passed   (or N/37 with skips for empty DB)

## Test Case Summary by Category
  ✅ Auth & Session: 4/4 passed
  ✅ List Tools: 9/9 passed
  ✅ Get Tools: 8/8 passed
  ✅ Search: 5/5 passed
  ✅ Auth Enforcement: 3/3 passed
  ✅ Performance: 8/8 passed
```

Exit code: **0**

---

## If Tests Fail — Debug Path

If any test fails, check the error message:

| Error Pattern | Likely Cause | Fix |
|---|---|---|
| `ConnectionError` to `localhost:8080` | Container not running | `poetry run invoke start` |
| HTTP 404 on `/plugins/nautobot-app-mcp-server/mcp/` | PLUGINS not loaded | Rebuild: `poetry run invoke build && poetry run invoke start` |
| HTTP 307 redirect | URL missing trailing slash | URL already correct; check `MCP_ENDPOINT` in `run_mcp_uat.py` line 45 |
| `LookupError: contextvars` in output | Phase 5 lifespan bug | File bug — Phase 5 regression |
| `[FATAL] ...` at top of output | Script crash | Read traceback, fix root cause |
| SKIP on all data tests | DB not imported | Run `bash scripts/reset_dev_db.sh --import` |

---

## Phase 6 Exit Gate

```
docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py
# Exit code must be 0
```

---

## Version Bump (Post-Phase 6)

After Phase 6 exits with all tests green, update STATE.md phase status:

- Phase 6: `Status: Completed`
- Version: `0.1.0` (final)
