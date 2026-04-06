# Phase 12: Bridge Cleanup — Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Delete the embedded-architecture code from Option A: `view.py`, `server.py`, `urls.py` entry. Remove `mcp._list_tools_mcp` override (already absent from `commands.py`, covered by `server.py` deletion). Old endpoint returns HTTP 404. `SKILL.md` updated to new standalone endpoint URL (`localhost:8005/mcp/`). `test_view.py` deleted.

Phase 12 delivers P5-01 through P5-06.

**Prerequisite:** Phase 11 (Auth Refactor) must be complete before this phase. PITFALL #12: this phase is deletion-only — nothing deleted until auth and sessions work in Option B architecture.

</domain>

<decisions>
## Implementation Decisions

### P5-01: Delete `mcp/view.py`

- **D-01:** `nautobot_app_mcp_server/mcp/view.py` is deleted. The file contains the ASGI bridge (`_bridge_django_to_asgi`) and Django view (`mcp_view`) — both are exclusive to the embedded (Option A) architecture.
- **D-02:** No replacement — the standalone FastMCP server (Option B) is already wired in `commands.py` → `create_app()` → `start_mcp_server.py` / `start_mcp_dev_server.py`.

### P5-02: Delete `mcp/server.py`

- **D-03:** `nautobot_app_mcp_server/mcp/server.py` is deleted. The file contains:
  - `_setup_mcp_app()` — FastMCP factory
  - `_mcp_instance` / `_mcp_app` / `_lifespan_started` globals
  - `_ensure_lifespan_started()` — daemon thread runner
  - `_make_mock_tool_context()` — mock ToolContext for `_list_tools_mcp` override
  - `get_mcp_app()` — lazy ASGI app factory
  - `progressive_list_tools_mcp` — `_list_tools_mcp` override (lines 78–110)
- **D-04:** The `progressive_list_tools_mcp` `_list_tools_mcp` override is **not separately removed** — it is removed as a consequence of deleting the file that contains it.

### P5-03: Remove MCP endpoint from `urls.py`

- **D-05:** In `__init__.py`, change `urls = ["nautobot_app_mcp_server.urls"]` → `urls = []`. This removes the URL configuration entirely.
- **D-06:** `nautobot_app_mcp_server/urls.py` is **not deleted** — it remains as an empty module (no `urlpatterns`). Deleting it would leave an import error in `__init__.py` unless that line is also removed.
- **D-07:** Result: `GET /plugins/nautobot-app-mcp-server/mcp/` returns HTTP 404 (no URL route registered).

### P5-04: Remove `mcp._list_tools_mcp` override

- **D-08:** Already addressed — the override is in `server.py` which is deleted by P5-02. No standalone removal step needed.

### P5-05: Verify old endpoint returns HTTP 404

- **D-09:** Command: `curl -I http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/`
- **D-10:** Expected: `HTTP/1.1 404 Not Found`
- **D-11:** This verifies `urls = []` is effective and no other URLconf is shadowing the route.

### P5-06: Update `SKILL.md` with new endpoint URL

- **D-12:** Replace all occurrences of `/plugins/nautobot-app-mcp-server/mcp/` with `http://localhost:8005/mcp/`
- **D-13:** Sections to update: Quick Start (endpoint reference), Session State Persistence, any direct endpoint mentions

### Test file cleanup: Delete `test_view.py`

- **D-14:** `nautobot_app_mcp_server/mcp/tests/test_view.py` is **deleted entirely**. All 7 tests (`MCPViewTestCase` + `MCPAppFactoryTestCase`) test the embedded Option A architecture — code being removed by P5-01 and P5-02. Tests for deleted code have no value.

### Test file cleanup: Update `test_session_persistence.py`

- **D-15:** `test_session_persistence.py` has the old endpoint URL hardcoded in the `@skip` comment and `cls.endpoint` class variable. The `@skip` comment URL should be updated to `http://localhost:8005/mcp/` for accurate documentation. The file remains skipped (intentionally — APPEND_SLASH issue with live server).
- **D-16:** `cls.endpoint` and `cls.base_url` in the skipped test are documentation/reference only; updating them keeps the file internally consistent even though it won't run.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 12 Scope (PRIMARY)
- `.planning/ROADMAP.md` §Phase 12 — phase goal, 6 requirements (P5-01–P5-06), success criteria, known pitfalls
- `.planning/REQUIREMENTS.md` — P5-01 through P5-06

### Prior Phase Context (MUST READ)
- `.planning/phases/10-session-state-simplification/10-CONTEXT.md` — D-39: Phase 12 removes `_list_tools_mcp` override; D-41: ScopeGuardMiddleware coexists with override during Phases 10–11
- `.planning/phases/11-auth-refactor/11-CONTEXT.md` — Phase 11 auth decisions; prerequisite for Phase 12
- `.planning/phases/09-tool-registration-refactor/09-CONTEXT.md` — `@register_tool`, `register_all_tools_with_mcp`, tool_registry.json

### Commands & Middleware (no changes needed)
- `nautobot_app_mcp_server/mcp/commands.py` — `create_app()` wires `register_all_tools_with_mcp(mcp)` + `mcp.add_middleware(ScopeGuardMiddleware())`. No changes.
- `nautobot_app_mcp_server/mcp/middleware.py` — `ScopeGuardMiddleware`. No changes.
- `nautobot_app_mcp_server/mcp/session_tools.py` — `_list_tools_handler`. No changes.

### Package Config
- `nautobot_app_mcp_server/__init__.py` — change `urls = ["nautobot_app_mcp_server.urls"]` → `urls = []`

### SKILL.md
- `nautobot_app_mcp_server/nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — update endpoint URL to `http://localhost:8005/mcp/`

### Tests to Delete/Update
- `nautobot_app_mcp_server/mcp/tests/test_view.py` — **DELETE** (all tests for removed code)
- `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — update `@skip` comment URL + `cls.endpoint` to new endpoint

### Tests Unaffected
- `test_auth.py` — unaffected
- `test_core_tools.py` — unaffected
- `test_register_tool.py` — unaffected
- `test_session_tools.py` — unaffected
- `test_signal_integration.py` — unaffected
- `test_commands.py` — unaffected

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Files to Delete
- `nautobot_app_mcp_server/mcp/view.py` — ASGI bridge + `mcp_view` Django view (Option A only)
- `nautobot_app_mcp_server/mcp/server.py` — FastMCP factory, `_list_tools_mcp` override, daemon thread (Option A only)
- `nautobot_app_mcp_server/mcp/tests/test_view.py` — 7 tests for Option A code being deleted

### Files to Modify
- `nautobot_app_mcp_server/__init__.py` — change `urls = [...]` to `urls = []`
- `nautobot_app_mcp_server/nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — update endpoint URL
- `nautobot_app_mcp_server/mcp/tests/test_session_persistence.py` — update `@skip` comment URL + `cls.endpoint`

### Files NOT to Modify
- `nautobot_app_mcp_server/mcp/commands.py` — Option B entry point; already complete
- `nautobot_app_mcp_server/mcp/middleware.py` — already in place
- `nautobot_app_mcp_server/mcp/session_tools.py` — already in place
- `nautobot_app_mcp_server/mcp/registry.py` — unchanged
- `nautobot_app_mcp_server/mcp/auth.py` — Phase 11 completed

### Verification Command
```bash
curl -I http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/
# Expected: HTTP/1.1 404 Not Found
```

### Integration Point
- After deletion, the only MCP server entry point is `start_mcp_server.py` / `start_mcp_dev_server.py` → `create_app()` → `FastMCP http_app()` on port 8005

</codebase_context>

<deferred>
## Deferred Ideas

- **`test_session_persistence.py` as UAT script** — this file (currently `@skip`) could become a Phase 13 UAT script that hits the new port 8005 endpoint. Deferred to Phase 13 planning.
- **`tool_registry.json` deletion** — the JSON file written by `ready()` is not deleted by Phase 12. It is harmless (used by standalone server for cross-process discovery). No action needed.

</deferred>

---
*Phase: 12-bridge-cleanup*
*Context gathered: 2026-04-06*
