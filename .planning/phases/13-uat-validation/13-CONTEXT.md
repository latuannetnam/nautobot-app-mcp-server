# Phase 13: UAT & Validation — Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the fully-clean Option B (separate-process) architecture end-to-end. UAT scripts updated to port 8005. Unit tests pass. `run_mcp_uat.py` smoke test exits 0. All 5 v1.2.0 requirements (P6-01–P6-05) verified.

Phase 13 delivers P6-01 through P6-05.

**Prerequisite:** Phase 12 (Bridge Cleanup) must be complete. `view.py`, `server.py`, `urls.py` deleted; MCP server now runs as separate FastMCP process on port 8005.

</domain>

<decisions>
## Implementation Decisions

### P6-01: UAT scripts updated to port 8005

- **D-01:** `scripts/run_mcp_uat.py` default `MCP_ENDPOINT` changed from `http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` to `http://localhost:8005/mcp/` — standalone FastMCP endpoint (Option B)
- **D-02:** `MCP_DEV_URL` env var (defaulting to `http://localhost:8080`) is removed. The MCP server is no longer at port 8080. Users who want a custom endpoint must set `MCP_DEV_URL` to the explicit MCP server URL (e.g., `http://localhost:8005`).
- **D-03:** Auth token format: `Authorization: Token <40-char-hex>` — unchanged. No `nbapikey_` prefix.
- **D-04:** `allow_redirects=False` — already set in `run_mcp_uat.py`. Phase 12's `test_session_persistence.py` also already uses this. No change needed.
- **D-05:** `requests.post()` timeout already 60s. No change needed.
- **D-06:** `MCP_DEV_TOKEN` env var name kept; `NAUTOBOT_SUPERUSER_API_TOKEN` from `creds.env` as fallback. Both already in the file.
- **D-07:** The `run_mcp_uat.py` script runs from the **host** via `poetry run python scripts/run_mcp_uat.py`. It must resolve `http://localhost:8005/mcp/` via Docker port mapping.

### P6-02: Token auth UAT passes

- **D-08:** `T-27` (anonymous): `MCPClient` with invalid token `"nbapikey_invalid_token_00000000000000"` → `device_list` returns `{"items": []}`. Code path: `get_user_from_request()` → invalid token → `AnonymousUser` → queryset restricted to empty. **Already implemented** (Phase 11).
- **D-09:** `T-28` (valid token): real superuser token → `device_list` returns real data (if DB imported). **Already implemented** (Phase 11).
- **D-10:** `T-29` (invalid token, second form): `"nbapikey_invalid_write_only_token_00000"` → empty results. Same `AnonymousUser` code path. **Already implemented**.
- **D-11:** Verification: `poetry run python scripts/run_mcp_uat.py` → T-27, T-28, T-29 pass.

### P6-03: Session UAT passes

- **D-12:** `T-01` through `T-04` test session tools: `mcp_enable_tools` → `mcp_list_tools` → scope reflects enabled tools. **Already implemented** (Phase 10 + Phase 11).
- **D-13:** `test_session_persistence.py` (currently `@skip`) tests MCP session persistence across sequential requests. Phase 12 context deferred this to Phase 13 as potential UAT.
- **D-14:** **Decision:** Do NOT convert `test_session_persistence.py` to an active Django test. The `@skip` reason (APPEND_SLASH causes 307 that strips POST body) still applies. The same behavior is validated by `T-01` through `T-04` in `run_mcp_uat.py` via the `mcp-session-id` header — this is the recommended path.
- **D-15:** Verification: `poetry run python scripts/run_mcp_uat.py` → T-01, T-02, T-03, T-04 pass.

### P6-04: All unit tests pass

- **D-16:** **Command (inside container):** `poetry run nautobot-server test nautobot_app_mcp_server`
- **D-17:** **Command (from host):** `unset VIRTUAL_ENV && poetry run invoke unittest`
- **D-18:** After Phase 12, only these test files exist (Phase 12 deleted `test_view.py`):
  - `test_auth.py` — Phase 11 async refactor; updated
  - `test_commands.py` — Phase 9/10; unchanged
  - `test_core_tools.py` — Phase 9; unchanged
  - `test_register_tool.py` — Phase 9; unchanged
  - `test_session_tools.py` — Phase 10; updated
  - `test_signal_integration.py` — Phase 9; unchanged
  - `test_session_persistence.py` — `@skip`; unchanged
- **D-19:** No new unit tests needed for Phase 13 — the 5 requirements are validated by UAT (`run_mcp_uat.py`) and `invoke unittest`.

### P6-05: UAT smoke test exits code 0

- **D-20:** **Command:** `docker exec nautobot-app-mcp-server-mcp-1 python /source/scripts/run_mcp_uat.py` — runs from the `mcp` container
- **D-21:** **Alternative (from host):** `poetry run python scripts/run_mcp_uat.py` — equivalent; uses Docker port mapping `8005:8005`
- **D-22:** **Expected exit code:** 0 (all tests pass); exit code 1 (some tests fail); exit code 2 (fatal error)
- **D-23:** `run_mcp_uat.py` already implements `sys.exit(0)` / `sys.exit(1)` / `sys.exit(2)` correctly. No code changes needed.

### Docker Compose — Separate MCP Server Service (Option C)

- **D-24:** `development/docker-compose.mcp.yml` — **NEW file** (Compose override). Adds a dedicated `mcp-server` service that runs `nautobot-server start_mcp_dev_server`.
- **D-25:** The `mcp` service in `docker-compose.dev.yml` (`entrypoint: tail -f /dev/null`) is **replaced** by `docker-compose.mcp.yml`. The old `mcp` placeholder is removed from `docker-compose.dev.yml` and superseded by the new separate service.
- **D-26:** `mcp-server` service config:
  - `image`: same Nautobot image as `nautobot` service
  - `command`: `nautobot-server start_mcp_dev_server` (blocks; not `tail -f /dev/null`)
  - `ports`: `8005:8005` (host→container port mapping)
  - `depends_on`: `db` (service_healthy)
  - `environment`: all four `NAUTOBOT_DB_*` vars (Phase 7 already wired)
  - `env_file`: `development.env`, `creds.env`
  - `volumes`: `../:/source` (source code bind mount), `./nautobot_config.py:/opt/nautobot/nautobot_config.py`
- **D-27:** `invoke start` automatically includes the new compose file (added to `compose_files` in `tasks.py`).
- **D-28:** Container name: `nautobot-app-mcp-server-mcp-server-1` (Docker Compose naming: `{project}-{service}-{index}`).

### test_session_persistence.py Status

- **D-29:** File remains **@skip** and unchanged. `APPEND_SLASH=True` on live server still causes 307 redirect that strips POST body. This is a fundamental Django limitation when testing from the Django test runner.
- **D-30:** Session persistence IS validated by T-01 through T-04 in `run_mcp_uat.py` using `mcp-session-id` header on the live FastMCP server. That's the production-accurate path.

### SKILL.md Endpoint Update (Phase 12 Done)

- **D-31:** Phase 12's D-12/D-13 updated `SKILL.md` to `http://localhost:8005/mcp/`. No Phase 13 action needed here — this was P5-06, completed in Phase 12.

</decisions>

<gray_areas>
## Remaining Gray Areas (Not Blocking — Can Be Deferred)

### GA-01: Performance thresholds in run_mcp_uat.py

The P-01 through P-08 performance tests have hardcoded thresholds (e.g., `device_list(1000) < 5s`, `device_list(50) < 2s`). These are reasonable for local development but may be too tight for CI environments on shared hardware.

**Decision for Phase 13:** No change. Thresholds are per-machine and documented. If CI needs looser thresholds, env-var overrides can be added later (deferred).

### GA-02: How to run UAT if MCP server is not yet up

`run_mcp_uat.py` currently calls `requests.post()` with no retry logic. If the MCP server is slow to start (first `nautobot.setup()` call), the UAT fails immediately.

**Decision for Phase 13:** No change. The docker-compose health check on `db` + the MCP server's own DB connectivity check in `create_app()` ensure the server is ready before accepting connections. Users running UAT manually are responsible for waiting for startup.

</gray_areas>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 13 Scope (PRIMARY)
- `.planning/ROADMAP.md` §Phase 13 — phase goal, 5 requirements (P6-01–P6-05), success criteria, known pitfalls
- `.planning/REQUIREMENTS.md` — P6-01 through P6-05

### Phase 12 Context (MUST READ)
- `.planning/phases/12-bridge-cleanup/12-CONTEXT.md` — Phase 12 decisions (D-01 through D-16). `test_view.py` deleted, `SKILL.md` updated. Prerequisite for Phase 13.

### Docker Compose
- `development/docker-compose.dev.yml` — `mcp` service placeholder (lines 52–57) to be **replaced** by new `docker-compose.mcp.yml`
- `development/docker-compose.base.yml` — shared `x-nautobot-base` anchor for service config
- `development/development.env` — `NAUTOBOT_DB_*` vars already present

### Management Commands (Option B — already complete)
- `nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` — dev entry point (`nautobot-server start_mcp_dev_server`)
- `nautobot_app_mcp_server/management/commands/start_mcp_server.py` — prod entry point (`nautobot-server start_mcp_server`)

### UAT Script
- `scripts/run_mcp_uat.py` — UAT client; only `MCP_ENDPOINT` default needs updating (D-01)

### Tasks
- `tasks.py` — `invoke start` uses `compose_files` list; add `docker-compose.mcp.yml` to the list

### Unit Tests
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — Phase 11 async refactor
- `nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — Phase 10 state API
- `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — Phase 9 async tools
- `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — @skip; remains unchanged (D-29)

### Auth Architecture
- `nautobot_app_mcp_server/mcp/auth.py` — Phase 11 async `get_user_from_request()` using `ctx.get_state()`/`ctx.set_state()`
- `nautobot_app_mcp_server/mcp/session_tools.py` — Phase 10 `_list_tools_handler`

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Files to Create
- `development/docker-compose.mcp.yml` — **NEW** Compose override; defines `mcp-server` service with `command: nautobot-server start_mcp_dev_server`

### Files to Modify
- `tasks.py` — add `"docker-compose.mcp.yml"` to `compose_files` list in `namespace.configure()`
- `scripts/run_mcp_uat.py` — change `MCP_ENDPOINT` default from `http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` to `http://localhost:8005/mcp/` (D-01)
- `development/docker-compose.dev.yml` — **remove** the `mcp` service placeholder (lines 52–57, the `entrypoint: tail -f /dev/null` stub). Replaced by `docker-compose.mcp.yml`.

### Files NOT to Modify (already correct)
- `run_mcp_uat.py` auth token format — unchanged (40-char hex, no prefix)
- `run_mcp_uat.py` `allow_redirects=False` — already present
- `run_mcp_uat.py` timeout — already 60s
- `run_mcp_uat.py` `sys.exit` codes — already correct
- `run_mcp_uat.py` `MCP_DEV_TOKEN` / `NAUTOBOT_SUPERUSER_API_TOKEN` fallback — already present
- Unit test files — all already updated by prior phases
- `SKILL.md` — Phase 12 already updated (P5-06)

### Verification Commands
```bash
# Start stack (includes new mcp-server service)
unset VIRTUAL_ENV && poetry run invoke start

# Verify MCP server is up
curl http://localhost:8005/mcp/  # or check container logs

# Run UAT from host
poetry run python scripts/run_mcp_uat.py

# Run unit tests from host
poetry run invoke unittest

# Run unit tests from inside container
poetry run nautobot-server test nautobot_app_mcp_server

# Run UAT from mcp container
docker exec nautobot-app-mcp-server-mcp-server-1 python /source/scripts/run_mcp_uat.py
```

### Container Naming
- Old: `nautobot-app-mcp-server-nautobot-1` (nautobot container)
- New MCP: `nautobot-app-mcp-server-mcp-server-1` (mcp-server service)
- The old `mcp` service (`entrypoint: tail -f /dev/null`) is removed.

### Integration Point
- `invoke start` now starts two server processes: Nautobot (port 8080) + MCP server (port 8005)
- UAT hits port 8005 only; port 8080 has no MCP endpoint (Phase 12 deleted `urls.py` entry)

</codebase_context>

<deferred>
## Deferred Ideas

- **Performance threshold env-var overrides** — GA-01: loosen P-01–P-08 thresholds via environment variables. Not needed for Phase 13.
- **UAT startup retry logic** — GA-02: add a 3-retry-with-backoff to `run_mcp_uat.py`. Not needed for Phase 13; docker-compose health checks are sufficient.
- **`test_session_persistence.py` as active UAT** — Phase 12 deferred; Phase 13 confirms it's not needed (T-01–T-04 cover same behavior).
- **Redis session backend** — v2 scope. In-memory `MemoryStore` sufficient for v1.2.0 with `--workers 1`.

</deferred>

---
*Phase: 13-uat-validation*
*Context gathered: 2026-04-06*
