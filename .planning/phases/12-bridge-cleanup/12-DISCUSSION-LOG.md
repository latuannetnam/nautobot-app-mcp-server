# Phase 12 Discussion Log

**Date:** 2026-04-06
**Phase:** Bridge Cleanup (P5-01 through P5-06)

## Topics Discussed

### 1. Phase 12 Scope Analysis

Confirmed: Phase 12 is purely mechanical deletion. All decisions flow from prior phases.

**Files to delete:**
- `mcp/view.py` — ASGI bridge, Option A only
- `mcp/server.py` — FastMCP factory + `_list_tools_mcp` override, Option A only

**Files to modify:**
- `__init__.py` — set `urls = []`
- `SKILL.md` — update endpoint URL

### 2. Gray Area: `test_view.py` Disposition

**Question:** What to do with `test_view.py`? All 7 tests cover code being deleted.

**Options considered:**
1. Delete `test_view.py` entirely — simpler, cleaner
2. Rewrite with a single `test_old_endpoint_returns_404` test

**Decision: Delete `test_view.py`.**
- Rationale: All 7 tests (`MCPViewTestCase` 4 tests + `MCPAppFactoryTestCase` 3 tests) test Option A code being removed
- Keeping tests for deleted code provides no value
- If a 404 test is needed, it can be added later in Phase 13 UAT

### 3. Gray Area: `test_session_persistence.py` URL

Not discussed — discovered during analysis. Action taken:
- Update `@skip` comment URL from `localhost:8080/...` to `localhost:8005/mcp/`
- Update `cls.endpoint` and `cls.base_url` for internal consistency
- File remains skipped (APPEND_SLASH issue with live server, correct behavior)

### 4. `_list_tools_mcp` Override Removal

Confirmed: The override is in `server.py` (lines 78–110). Deleting `server.py` (P5-02) automatically removes the override. No standalone removal step needed.

### 5. `urls.py` Deletion vs. Empty

Confirmed: `urls.py` is NOT deleted — set to empty module. `__init__.py` changes `urls = ["nautobot_app_mcp_server.urls"]` → `urls = []`. Deleting `urls.py` would cause an import error in `__init__.py` unless the import line is also removed, which is more error-prone.

### 6. Deferred Ideas

- `test_session_persistence.py` → UAT script for Phase 13: deferred to Phase 13 planning
- `tool_registry.json` cleanup: no action (harmless, used by standalone server)

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| D-01 | Delete `view.py` | Option A only |
| D-02 | Delete `server.py` | Option A only |
| D-03 | Set `urls = []` in `__init__.py` | Removes route; `urls.py` stays as empty module |
| D-04 | No separate `_list_tools_mcp` removal step | Covered by `server.py` deletion |
| D-05 | Delete `test_view.py` entirely | All 7 tests cover removed code |
| D-06 | Update `test_session_persistence.py` URL in skip comment | Internal consistency |
| D-07 | Update `SKILL.md` endpoint URL to `localhost:8005/mcp/` | New Option B endpoint |

## Verification Plan

```bash
# After all deletions:
curl -I http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/
# Expected: HTTP/1.1 404 Not Found
```

## Next Steps

1. Plan phase → create 12-01 through 12-06 plans + test cleanup plan
2. Execute plans in order
3. Run tests: `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests`
4. Phase exit gate: `curl` returns 404 + all tests pass
