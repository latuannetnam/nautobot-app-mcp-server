---
gsd_state_version: 1.0
milestone: v1.2.0
milestone_name: Milestone Goal
status: executing
last_updated: "2026-04-06"
last_activity: 2026-04-06 -- Phase 11 execution complete (2/2 plans)
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 2
  completed_plans: 0
  percent: 0
---

# Project State — `nautobot-app-mcp-server`

**Last updated:** 2026-04-05 (Phase 11 context gathered)

---

## Current Position

Phase: 11
Plan: Not started
Status: Ready to execute
Last activity: 2026-04-05 -- Phase 11 planning complete

Progress: [▓▓▓▓▓▓▓▓▓▓] Phases 7–10 complete (17/17 plans); Phase 11 context gathered

---

## Phase 11 Summary (Auth Refactor — Complete)

**Phase 11-01 and 11-02 completed** (2026-04-06):

**11-01 — `get_user_from_request()` async refactor:**
- `_cached_user` attribute → `_CACHED_USER_KEY = "mcp:cached_user"` constant
- `def get_user_from_request` → `async def get_user_from_request`
- Cache read: `await ctx.get_state(_CACHED_USER_KEY)` — cache-hit re-validates user via `User.objects.get(pk=id)` (T-11-04)
- Cache write: `await ctx.set_state(_CACHED_USER_KEY, str(user.pk))` — stores PK string, not object (T-11-03)
- Added `getattr(ctx, "token_objects", None)` fallback for testability — avoids Django `SynchronousOnlyOperation` when calling sync ORM from `async def` via `AsyncToSync`
- Test fixture: `AsyncToSync(func)(ctx)` + `_RequestContext` with `__slots__` (breaks MagicMock shadowing) + `token_key_to_user` mock
- 12/12 auth tests pass; 31/31 core tool tests pass; 98/98 MCP tests pass (2 skipped)

**11-02 — Call sites + nginx docs:**
- All 10 handlers in `core.py`: `user = get_user_from_request(ctx)` → `user = await get_user_from_request(ctx)`
- `.restrict(` count in `query_utils.py`: 19 (unchanged from baseline)
- `docs/admin/upgrade.md`: new "Production Deployment (nginx)" section documenting `proxy_set_header Authorization $http_authorization;`

**Key decisions:**
- Chose `ctx.set_state`/`ctx.get_state` (Phase 10 session state API) over `ctx.request_context.session["cached_user"]` — `ServerSession` has no dict interface
- Django 4.2 `SynchronousOnlyOperation` blocks sync ORM calls from ANY async context (including `AsyncToSync` thread pools); resolved by `token_key_to_user` fixture mock

---

## Phase 10 Summaries (Session State Simplification — Complete)

**Phase 10-01–04 completed** (commit `55e4694`):

- `session_tools.py`: replaced `RequestContext._mcp_tool_state` monkey-patch with `ctx.get_state()`/`ctx.set_state()` via FastMCP's `MemoryStore`. Deleted `MCPSessionState`; added `ToolScopeState` dataclass with async helpers. State keys: `"mcp:enabled_scopes"` and `"mcp:enabled_searches"`.
- `mcp/middleware.py` (new): `ScopeGuardMiddleware` — FastMCP `Middleware` subclass with `on_call_tool()` hook. Enforces scope at tool-call time as security backstop. Core tools always pass; app-tier tools require matching scope.
- `commands.py`: wired `mcp.add_middleware(ScopeGuardMiddleware())` after tool registration.
- `_list_tools_handler`: updated to read `enabled_scopes`/`enabled_searches` via `ctx.get_state()` directly.
- All session tool registrations migrated to `@register_tool(name="mcp_*")` with explicit names.
- All 96 MCP tests pass.

## Phase 09 Summaries (Tool Registration Refactor — Complete)

**Phase 09-01 completed** (`09-01-SUMMARY.md`):

- `schema.py`: `func_signature_to_input_schema()` auto-derives JSON Schema from Python type hints
- `@register_tool` decorator in `mcp/__init__.py`: ergonomic wrapper with auto-schema
- All 10 core tools in `core.py` converted to `@register_tool` (net: 54 insertions, 245 deletions)
- All tests pass

**Phase 09-02 completed** (`09-PLAN-02-SUMMARY.md`):

- `register_all_tools_with_mcp(mcp)` in `mcp/__init__.py`: iterates `MCPToolRegistry.get_all()` and calls `mcp.tool(func, name, description)` for each tool; added to `__all__`
- `mcp/commands.py` STEP 4: replaced placeholder with real wiring — import `core` (side-effect registration) then call `register_all_tools_with_mcp(mcp)`

**Phase 09-03 completed** (`09-03-SUMMARY.md`):

- `ready()` in `__init__.py`: removed `post_migrate` signal wiring, replaced with `tool_registry.json` generation
- JSON written to package dir via `os.path.dirname(__file__)` (works for editable install and installed package)
- `grep "post_migrate" __init__.py` → no matches (confirmed removed)

**Phase 09-04 completed** (`09-PLAN-04-SUMMARY.md`):

- Confirmed all 10 core read tools use `async def` + `sync_to_async(thread_sensitive=True)` pattern
- `grep -c "^async def _"` returns 10
- `grep -c "sync_to_async(query_utils._sync_"` returns 10
- No module-level Django model imports in `core.py`

**Phase 09-05 completed** (`09-PLAN-05-SUMMARY.md`):

- `query_utils.py`: moved all Nautobot model imports from module level to `TYPE_CHECKING` block
- Added 22 lazy imports inside functions (≥20 required); zero module-level violations

**Phase 09-06 completed** (`09-PLAN-06-SUMMARY.md`):

- 11 unit tests in `test_register_tool.py` covering `func_signature_to_input_schema()` (3), `@register_tool` decorator (5), and `register_all_tools_with_mcp()` (3)
- All 89 MCP tests pass (PostMigrateSignalTestCase removed as stale)

**Gap fixes after verification:**

- `commands.py` STEP 4a: reads `tool_registry.json` at startup, logs discovery count, graceful no-op when absent (commit `24635c1`)
- `PostMigrateSignalTestCase` deleted from `test_signal_integration.py` — `post_migrate` replaced by `ready()` writing JSON (commit `24635c1`)

---

## Accumulated Context

**v1.0.0 completed (Phases 0–4):** Core MCP server, auth, 10 read tools, SKILL.md package.

**v1.1.0 completed (Phases 5–6):** Embedded FastMCP bridge refactor — `async_to_sync` + `session_manager.run()` replaces `asyncio.run()`; session state on `RequestContext._mcp_tool_state`; auth caching on `_cached_user`; progressive disclosure via `mcp._list_tools_mcp` override.

**v1.2.0 active (Phases 7–13):** Separate-process migration (Option A → Option B).

**Phase 08 decisions to carry forward:**

- FastMCP 3.x: `stateless_http` passed at `mcp.run()` / `mcp.http_app()` — NOT constructor
- Two-phase import pattern: `nautobot.setup()` before relative imports
- `create_app()` returns `(FastMCP, host, port)` tuple
- `reload_dirs` scoped to `nautobot_app_mcp_server/` package root (computed via `Path(__file__).resolve().parents[3]`)
- `connection.ensure_connection()` before `nautobot.setup()` for fast DB failure detection

**Phase 09 decisions to carry forward:**

- `@register_tool` decorator: dual registration (in-memory `MCPToolRegistry` + FastMCP via `register_all_tools_with_mcp()`)
- `tool_registry.json`: written by plugin `ready()`, read by `commands.py` `create_app()` at startup
- All 10 core tools: `async def` + `sync_to_async(thread_sensitive=True)` (ORM lazy imports inside functions)
- `post_migrate` signal removed — Phase 8 MCP server process doesn't fire it; `ready()` writing JSON is the replacement
- `func_signature_to_input_schema()`: auto-derives JSON Schema from Python type hints; FastMCP 3.x ignores `input_schema` (auto-derives from type hints at runtime)

**Reference project (`nautobot-app-mcp`):**

- Separate process via `nautobot-server start_mcp_server`
- `FastMCP("Nautobot MCP Server", host, port).run(transport="http")`
- `nautobot.setup()` called once at worker startup
- `@register_tool` decorator: dual registration (in-memory dict + FastMCP `.tool()` wiring)
- Tools: async wrapper → `sync_to_async(get_sync_fn())` → Django ORM
- Session state: normal `dict` keyed by `session_id`
- `tool_registry.json` for cross-process plugin discovery
- No auth (assumed trusted network)

---

## Phase Status

| Phase | Name | Status | Start Date | End Date | Blockers |
|---|---|---|---|---|---|
| Phase 7 | Setup | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 8 | Infrastructure | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 9 | Tool Registration | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 10 | Session State | Complete | 2026-04-05 | 2026-04-05 | None |
| Phase 11 | Auth Refactor | Complete | 2026-04-06 | 2026-04-06 | None |
| Phase 12 | Bridge Cleanup | Not Started | — | — | Phase 11 |
| Phase 13 | UAT & Validation | Not Started | — | — | Phase 12 |

---

## Version History

| Version | Date | Phases | Notes |
|---|---|---|---|
| 0.1.0 | 2026-04-01 | Phases 0–4 | v1.0 shipped |
| 0.1.0 | 2026-04-04 | Phases 5–6 | v1.1.0 shipped |
| 0.1.0 | 2026-04-05 | Phase 7 | v1.2.0 Phase 7 setup complete |
| 0.1.0 | 2026-04-05 | Phase 8 | v1.2.0 Phase 8 infrastructure complete |
| 0.1.0 | 2026-04-05 | Phase 9 | v1.2.0 Phase 9 tool registration refactor complete (`8da04f1`) |
| 0.1.0 | 2026-04-05 | Phase 10 | v1.2.0 Phase 10 session state simplification complete (`55e4694`) |
| 0.1.0 | 2026-04-06 | Phase 11 | v1.2.0 Phase 11 auth refactor complete (2/2 plans, 98/98 tests pass) |

---

*State last updated: 2026-04-06*
