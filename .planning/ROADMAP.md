# Project Roadmap — `nautobot-app-mcp-server`

**Project:** Nautobot App MCP Server
**Roadmap defined:** 2026-04-05
**Horizon:** v1.2.0
**Phases:** 7 (v1.2.0: Phases 7–13, continuing from v1.1.0 Phase 6)

---

## Milestones

- ✅ **v1.0 MVP** - Phases 0–4 (shipped 2026-04-02)
- ✅ **v1.1.0** - Phases 5–6 (shipped 2026-04-04)
- 🚧 **v1.2.0** - Phases 7–13 (in progress)
- 📋 **v2.0** - TBD (write tools, Redis sessions, horizontal scaling)

---

## v1.2.0 Milestone Goal

Migrate the MCP server from embedded (Option A — FastMCP inside Django process) to separate-process (Option B — standalone FastMCP via Django management commands). Eliminate the WSGI→ASGI bridge (`view.py`, `server.py`, daemon thread, `mcp._list_tools_mcp` override, `RequestContext` monkey-patches). Preserve all capabilities: 10 core read tools, auth, pagination, `MCPToolRegistry`, `register_mcp_tool()` API.

**Phase dependencies:**

```
Phase 7 ──► Phase 8 ──► Phase 9 ──► Phase 10 ──► Phase 11 ──► Phase 12 ──► Phase 13
```

---

## Phase Summary

| Phase | Name | Requirements | Key Output |
| ----- | ---- | ------------ | ---------- |
| **Phase 7** | Setup | P0-01, P0-02, P0-03 (3) | `pyproject.toml` uvicorn dep, updated docker-compose, upgrade docs |
| **Phase 8** | Infrastructure | P1-01–P1-04 (4) | `start_mcp_server.py` + `start_mcp_dev_server.py` management commands |
| **Phase 9** | Tool Registration | P2-01–P2-06 (6) | `@register_tool` decorator, `tool_registry.json`, all tools async |
| **Phase 10** | Session State | P3-01–P3-04 (4) | `ctx.request_context.session` native dict, `@scope_guard` decorator |
| **Phase 11** | Auth Refactor | P4-01–P4-04 (4) | Token from FastMCP headers, session-cached user, nginx docs |
| **Phase 12** | Bridge Cleanup | P5-01–P5-06 (6) | `view.py`/`server.py`/`urls.py` deleted, old endpoint returns 404 |
| **Phase 13** | UAT & Validation | P6-01–P6-05 (5) | All UAT tests pass on port 8005 |

---

## Phases

### 🚧 Phase 7: Setup

**Goal:** Prerequisite wiring — explicit uvicorn dependency, Docker env-var passthrough, `--workers 1` documentation.

**Depends on:** Nothing (first phase of v1.2.0)

**Requirements:** P0-01, P0-02, P0-03

**Success Criteria** (what must be TRUE):

1. `grep "uvicorn" pyproject.toml` finds `uvicorn >= 0.35.0` under `[tool.poetry.dependencies]`
2. `development/docker-compose.yml` passes all four `NAUTOBOT_DB_USER`, `NAUTOBOT_DB_PASSWORD`, `NAUTOBOT_DB_HOST`, `NAUTOBOT_DB_NAME` env vars to the MCP server service
3. `docs/admin/upgrade.md` contains a `--workers 1` warning section explaining in-memory session limitation

**Plans:** 3 plans

- [x] 07-01: Add `uvicorn >= 0.35.0` explicit dependency to `pyproject.toml`
- [x] 07-02: Update `development/docker-compose.yml` — pass `NAUTOBOT_DB_*` env vars to MCP server service
- [x] 07-03: Document `--workers 1` requirement in `docs/admin/upgrade.md`

**Known pitfalls:**

- P0-02: Docker compose service name must match the service defined in docker-compose — the MCP server runs as its own service, not inside the nautobot container
- All four `NAUTOBOT_DB_*` vars are required; omitting any one causes silent auth failures at `nautobot.setup()`

**Phase exit gate:** `poetry lock && poetry install` succeeds; `grep uvicorn pyproject.toml` returns explicit entry

---

### Phase 8: Infrastructure — Management Commands

**Goal:** Two Django management commands that serve as the standalone MCP server entry points — production (`start_mcp_server.py`) and development (`start_mcp_dev_server.py`).

**Depends on:** Phase 7

**Requirements:** P1-01, P1-02, P1-03, P1-04

**Success Criteria** (what must be TRUE):

1. `python manage.py start_mcp_server --help` shows usage and starts `mcp.run(transport="http")` blocking indefinitely
2. `python manage.py start_mcp_dev_server --help` shows usage and starts `uvicorn.run(reload=True)` with auto-reload
3. `create_app()` is a callable that returns the FastMCP ASGI app; calling it before DB is reachable raises a descriptive `RuntimeError`
4. `create_app()` reads `NAUTOBOT_CONFIG` and `PLUGINS_CONFIG` from environment variables

**Plans:** 4 plans

- [ ] 08-01: `start_mcp_server.py` production management command — `nautobot.setup()` → register tools → `mcp.run(transport="http")`
- [ ] 08-02: `start_mcp_dev_server.py` dev management command — `create_app()` factory + `uvicorn.run(reload=True)`
- [ ] 08-03: `create_app()` validates DB connectivity before FastMCP starts
- [ ] 08-04: Read `NAUTOBOT_CONFIG` and `PLUGINS_CONFIG` from environment in `create_app()`

**Known pitfalls:**

- PITFALL #1: `nautobot.setup()` called after model imports — `RuntimeError: Django wasn't set up yet`. Guard: call `nautobot.setup()` at the **top** of the management command entry point, before any relative imports
- `uvicorn.run(reload=True)` requires the working directory to be the project root; file watchers must see changes to `nautobot_app_mcp_server/`

**Phase exit gate:** Both management commands are importable without error; `create_app()` raises `RuntimeError` if DB is unreachable

---

### Phase 9: Tool Registration Refactor

**Goal:** Redesign tool registration for cross-process use. `@register_tool` decorator writes to in-memory registry; `tool_registry.json` enables discovery across the process boundary. All 10 core tools converted to `async def` + `sync_to_async`.

**Depends on:** Phase 8

**Requirements:** P2-01, P2-02, P2-03, P2-04, P2-05, P2-06

**Success Criteria** (what must be TRUE):

1. `@register_tool` decorator registers a tool in both the in-memory `MCPToolRegistry` dict and wires it to FastMCP via `.tool()`
2. `register_all_tools_with_mcp()` called at server startup populates FastMCP from `MCPToolRegistry`
3. Nautobot plugin `ready()` generates `tool_registry.json` at plugin startup; MCP server reads it at startup
4. All 10 core read tools are `async def`; ORM calls wrapped in `sync_to_async(thread_sensitive=True)(get_sync_fn())`
5. No Django model imports at module level in `nautobot_app_mcp_server/mcp/tools/` — all imports lazy inside tool functions
6. Unit tests for `@register_tool` decorator and `register_all_tools_with_mcp()` pass

**Plans:** 6 plans

- [ ] 09-01: `@register_tool` decorator — dual registration (in-memory dict + FastMCP `.tool()` wiring)
- [ ] 09-02: `register_all_tools_with_mcp()` — populates FastMCP from `MCPToolRegistry` at startup
- [ ] 09-03: Plugin `ready()` generates `tool_registry.json` (replaces `post_migrate`)
- [ ] 09-04: All 10 core read tools refactored — `async def` + `sync_to_async(thread_sensitive=True)`
- [ ] 09-05: No Django model imports at module level — lazy import audit and conversion
- [ ] 09-06: Unit tests for `@register_tool` decorator and `register_all_tools_with_mcp()`

**Known pitfalls:**

- PITFALL #3: `post_migrate` never fires in the MCP server process (it runs `django.setup()` directly, not via `nautobot-server`). `tool_registry.json` replaces it — must be generated by the Nautobot plugin at startup
- P2-05 lazy import audit: grep for `from nautobot` or `from dcim` or `from ipam` in `mcp/tools/`. Any match at module level must be moved inside the tool function

**Phase exit gate:** `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` passes; lazy import audit returns zero matches

---

### Phase 10: Session State Simplification

**Goal:** Replace `RequestContext._mcp_tool_state` monkey-patch with FastMCP's native `ctx.request_context.session` dict. Replace `mcp._list_tools_mcp` override with `@scope_guard` decorator.

**Depends on:** Phase 9

**Requirements:** P3-01, P3-02, P3-03, P3-04

**Success Criteria** (what must be TRUE):

1. Session state is stored in `ctx.request_context.session` (plain dict, no monkey-patching)
2. `MCPSessionState` is keyed by FastMCP `session_id` in `StreamableHTTPSessionManager.sessions`
3. `@scope_guard("dcim")` decorator replaces `mcp._list_tools_mcp` override — scope checked before tool executes
4. `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` implemented in Option B pattern using `ctx.request_context.session`

**Plans:** 4 plans

- [ ] 10-01: Session state in `ctx.request_context.session` — rewrite `session_tools.py`
- [ ] 10-02: `MCPSessionState` keyed by FastMCP `session_id` in `StreamableHTTPSessionManager.sessions`
- [ ] 10-03: `@scope_guard` decorator replaces `mcp._list_tools_mcp` override
- [ ] 10-04: `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` in Option B pattern

**Known pitfalls:**

- PITFALL #4: `RequestContext` monkey-patching is broken in standalone FastMCP. `ctx.request_context.session` is always a plain dict — always dict-like, always available
- `StreamableHTTPSessionManager.sessions` is a `dict[str, ServerSession]` — `MCPSessionState` can be stored as `sessions[session_id]._mcp_tool_state` or directly on `session` if exposed

**Phase exit gate:** `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` passes; session tools respond correctly with native session dict

---

### Phase 11: Auth Refactor

**Goal:** `get_user_from_request()` reads token from FastMCP request headers. Token cached in `ctx.request_context.session["cached_user"]`. `.restrict()` preserved. nginx `proxy_set_header Authorization` documented.

**Depends on:** Phase 10

**Requirements:** P4-01, P4-02, P4-03, P4-04

**Success Criteria** (what must be TRUE):

1. `get_user_from_request()` reads token from FastMCP request headers (`Authorization: Token <hex>`)
2. Token cached in `ctx.request_context.session["cached_user"]` — no monkey-patch; survives batched requests
3. All querysets call `.restrict(user, action="view")` (preserved from v1.1.0)
4. `docs/admin/upgrade.md` documents `proxy_set_header Authorization` for nginx production deployments

**Plans:** 4 plans

- [ ] 11-01: `get_user_from_request()` reads token from FastMCP request headers
- [ ] 11-02: Token cached in `ctx.request_context.session["cached_user"]` (no monkey-patch)
- [ ] 11-03: `.restrict(user, "view")` on all querysets — preserved unchanged
- [ ] 11-04: Document `proxy_set_header Authorization` for nginx in `docs/admin/upgrade.md`

**Known pitfalls:**

- PITFALL #7: Auth header stripped by nginx reverse proxy. Must explicitly set `proxy_set_header Authorization $http_authorization;` in nginx config
- Token key is 40-char hex, no `nbapikey_` prefix (Nautobot's native token format)

**Phase exit gate:** Auth unit tests pass; token cached in `session["cached_user"]` verified by mock assertion

---

### Phase 12: Bridge Cleanup

**Goal:** Delete all embedded-architecture code (`view.py`, `server.py`, `urls.py`, `mcp._list_tools_mcp` override). Old endpoint returns 404. `SKILL.md` updated with new standalone URL.

**Depends on:** Phase 11

**Requirements:** P5-01, P5-02, P5-03, P5-04, P5-05, P5-06

**Success Criteria** (what must be TRUE):

1. `nautobot_app_mcp_server/mcp/view.py` does not exist
2. `nautobot_app_mcp_server/mcp/server.py` does not exist
3. `nautobot_app_mcp_server/urls.py` has no MCP endpoint entry
4. No `mcp._list_tools_mcp` override in the codebase
5. `GET /plugins/nautobot-app-mcp-server/mcp/` returns HTTP 404 (old endpoint removed)
6. `SKILL.md` documents the new standalone endpoint URL (`localhost:8005/mcp/`)

**Plans:** 6 plans

- [ ] 12-01: Delete `nautobot_app_mcp_server/mcp/view.py` — entire WSGI→ASGI bridge removed
- [ ] 12-02: Delete `nautobot_app_mcp_server/mcp/server.py` — daemon thread, lazy factory, `_mcp_app` singleton gone
- [ ] 12-03: Remove MCP endpoint entry from `nautobot_app_mcp_server/urls.py`
- [ ] 12-04: Remove `mcp._list_tools_mcp` override from `MCPToolRegistry` initialization
- [ ] 12-05: Verify old endpoint (`/plugins/nautobot-app-mcp-server/mcp/`) returns HTTP 404
- [ ] 12-06: Update `SKILL.md` with new standalone endpoint URL (`localhost:8005/mcp/`)

**Known pitfalls:**

- PITFALL #5: Old endpoint still accessible after migration — leaves a live conflict (two endpoints serving MCP). Phase 12 must include explicit deletion checklist and 404 verification
- PITFALL #12: Phase 12 is deletion-only — nothing should be deleted until auth and sessions work in the new architecture (Phase 11)

**Phase exit gate:** All 6 files/entries deleted; `curl http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` returns 404; `SKILL.md` updated

---

### Phase 13: UAT & Validation

**Goal:** Full end-to-end validation of the production architecture. UAT scripts updated to port 8005. All unit tests pass.

**Depends on:** Phase 12

**Requirements:** P6-01, P6-02, P6-03, P6-04, P6-05

**Success Criteria** (what must be TRUE):

1. UAT scripts hit the new port (default 8005) — endpoint URL, auth tokens (40-char hex, no prefix), `allow_redirects=False`
2. Token auth UAT passes: valid token → data returned; invalid token → empty result + warning logged
3. Session UAT passes: `mcp_enable_tools` → `mcp_list_tools` → tool list reflects enabled scope
4. All unit tests pass: `poetry run nautobot-server test nautobot_app_mcp_server`
5. `docker exec ... python /source/scripts/run_mcp_uat.py` exits with code 0

**Plans:** 5 plans

- [ ] 13-01: UAT scripts updated to hit port 8005 — fix endpoint URL, fix auth tokens, use `allow_redirects=False`
- [ ] 13-02: Token auth UAT passes — valid token returns data, invalid token returns empty + warning
- [ ] 13-03: Session UAT passes — `mcp_enable_tools` → `mcp_list_tools` reflects enabled scope
- [ ] 13-04: All unit tests pass — `poetry run nautobot-server test nautobot_app_mcp_server`
- [ ] 13-05: UAT smoke test `docker exec ... python /source/scripts/run_mcp_uat.py` exits 0

**Known pitfalls:**

- PITFALL #9: Old endpoint breaks clients — UAT scripts must be updated to port 8005 before Phase 13 tests run
- UAT tokens must be real 40-char hex Nautobot tokens (no `nbapikey_` prefix)

**Phase exit gate:** `docker exec ... python /source/scripts/run_mcp_uat.py` exits 0; all 27 v1.2.0 requirements verified

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
| ----- | --------- | -------------- | ------ | --------- |
| 0. Project Setup | v1.0 | 4/4 | Complete | 2026-04-01 |
| 1. MCP Server Infrastructure | v1.0 | 11/11 | Complete | 2026-04-01 |
| 2. Auth & Sessions | v1.0 | 7/7 | Complete | 2026-04-01 |
| 3. Core Read Tools | v1.0 | 3/3 | Complete | 2026-04-02 |
| 4. SKILL.md Package | v1.0 | 3/3 | Complete | 2026-04-02 |
| 5. MCP Server Refactor | v1.1.0 | 7/7 | Complete | 2026-04-04 |
| 6. UAT & Smoke Tests | v1.1.0 | 1/1 | Complete | 2026-04-04 |
| 7. Setup | v1.2.0 | 1/3 | In Progress | 2026-04-05 |
| 8. Infrastructure | v1.2.0 | 0/4 | Not started | — |
| 9. Tool Registration | v1.2.0 | 0/6 | Not started | — |
| 10. Session State | v1.2.0 | 0/4 | Not started | — |
| 11. Auth Refactor | v1.2.0 | 0/4 | Not started | — |
| 12. Bridge Cleanup | v1.2.0 | 0/6 | Not started | — |
| 13. UAT & Validation | v1.2.0 | 0/5 | Not started | — |

---

## Phase Exit Gates

| Phase | Gate | Verification Command |
| ----- | ---- | -------------------- |
| Phase 7 | uvicorn explicit in pyproject.toml; docker-compose passes DB vars; upgrade.md has `--workers 1` | `poetry lock && grep uvicorn pyproject.toml` |
| Phase 8 | Both management commands importable; `create_app()` raises `RuntimeError` on unreachable DB | `python manage.py start_mcp_server --help` |
| Phase 9 | All 10 core tools async; lazy import audit returns 0; decorator tests pass | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` |
| Phase 10 | Session tools use native `session` dict; no monkey-patch; scope_guard decorator active | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` |
| Phase 11 | Token auth UAT passes; `session["cached_user"]` caching verified by mock | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests` |
| Phase 12 | `view.py`, `server.py`, `urls.py` deleted; old endpoint returns 404; SKILL.md updated | `curl http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` → 404 |
| Phase 13 | UAT smoke test exits 0; all 27 v1.2.0 requirements verified | `docker exec ... python /source/scripts/run_mcp_uat.py` |

---

## Quick Reference

**MCP Endpoint (v1.2.0):** `http://localhost:8005/mcp/` (standalone FastMCP process)

**MCP Endpoint (v1.1.0 — to be removed in Phase 12):** `http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/`

**Stack (v1.2.0):**

- `fastmcp ^3.2.0` — standalone event loop, `mcp.run(transport="http")` (HTTP transport, not legacy SSE)
- `uvicorn >= 0.35.0` — dev server with `reload=True`
- `nautobot.setup()` — bootstraps Django ORM once per worker
- `asgiref` — `sync_to_async(thread_sensitive=True)` for ORM calls
- `tool_registry.json` — cross-process plugin tool discovery

**Phase ordering rationale:**

- Phase 7 before 8: Docker env-var wiring and `--workers 1` are prerequisites for any meaningful testing of the new process
- Phase 8 before 9: Management commands are the sole entry point; tool registration cannot be tested until the server can start
- Phase 9 before 10: Session simplification replaces monkey-patches; the registry must be stable first
- Phase 10 before 11: Auth refactor depends on session dict being the canonical store
- Phase 11 before 12: Bridge cleanup is deletion-only; nothing deleted until auth and sessions work
- Phase 12 before 13: UAT validates the fully clean state

---

*Roadmap defined: 2026-04-05*
*v1.2.0 Separate Process Refactor milestone — Phases 7–13*
*Derived from: REQUIREMENTS.md (27 v1.2.0 requirements), research/SUMMARY.md, config.json*
