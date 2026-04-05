# Phase 11: Auth Refactor — Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor `get_user_from_request()` to read token from FastMCP request headers (separate-process Option B architecture), and migrate user caching to FastMCP's `ctx.set_state()`/`ctx.get_state()` API (Phase 10 session state pattern). All 10 core tools preserve `.restrict(user, "view")`. Document nginx `proxy_set_header Authorization` requirement.

Phase 11 delivers P4-01 through P4-04.

</domain>

<decisions>
## Implementation Decisions

### P4-01: Token from FastMCP request headers

- **D-01:** Token source: `ctx.request_context.request.headers.get("Authorization", "")` — unchanged from v1.1.0
- **D-02:** In Option B (separate FastMCP process), `ctx.request_context.request` is a **Starlette ASGI Request object** (not Django's `HttpRequest`). Starlette `Request.headers` is a `Headers` object, subscriptable like a dict.
- **D-03:** Token format: `Authorization: Token <40-char-hex>` (no `nbapikey_` prefix — Nautobot's native token format)
- **D-04:** Missing header → `logger.warning("MCP: No auth token, falling back to anonymous user")`. Invalid/malformed → `logger.debug("MCP: Invalid auth token format")`. Both return `AnonymousUser` — no exceptions.

### P4-02: Token cached in FastMCP session state (`ctx.set_state`/`ctx.get_state`)

- **D-05:** Cache storage: `ctx.set_state("mcp:cached_user")` / `ctx.get_state("mcp:cached_user")` — Phase 10's session state API, NOT `ctx.request_context.session["cached_user"]` (ServerSession has no dict interface — Phase 10 finding)
- **D-06:** Cached value: **user ID as string** (not the full user object — user objects are not JSON-serializable). Format: `str(user.pk)` (UUID as string).
- **D-07:** Cache scope: **Per-FastMCP-session** — keyed by FastMCP `session_id` in `MemoryStore`. One DB lookup per MCP session, not per request batch. This is an improvement over Phase 5's per-request-context caching.
- **D-08:** Cache flow (first call, cache miss):
  1. Parse `Authorization: Token <key>` from headers
  2. `await ctx.get_state("mcp:cached_user")` → cache miss
  3. DB: `Token.objects.select_related("user").get(key=<key>)`
  4. `await ctx.set_state("mcp:cached_user", str(user.pk))`
  5. Return user
- **D-09:** Cache flow (subsequent calls, cache hit):
  1. `await ctx.get_state("mcp:cached_user")` → returns user ID string
  2. Fetch user by ID from DB (`User.objects.get(pk=<user_id>)`) — avoids Token lookup but still checks user is valid/active
  3. Return user
- **D-10:** `_cached_user` attribute on `ctx.request_context` (Phase 5 pattern) — **removed**. Replaced by FastMCP session state.
- **D-11:** `get_user_from_request()` must become `async def` — `ctx.set_state`/`ctx.get_state` are async.

### P4-03: `.restrict(user, "view")` on all querysets

- **D-12:** All 10 core read tools in `core.py` call `.restrict(user, action="view")` — **preserved unchanged**. No refactoring needed.
- **D-13:** `restrict()` is Nautobot's object-level permission enforcement — returns empty queryset for unauthenticated users naturally.

### P4-04: nginx `proxy_set_header Authorization` documentation

- **D-14:** `docs/admin/upgrade.md` — add nginx configuration section
- **D-15:** Required nginx directive: `proxy_set_header Authorization $http_authorization;` — nginx strips `Authorization` header by default (PITFALL #7 from ROADMAP)
- **D-16:** Document the config in the existing "Worker Process Requirement" section or a new "Production Deployment (nginx)" subsection

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 11 Scope (PRIMARY)
- `.planning/ROADMAP.md` §Phase 11 — phase goal, 4 requirements (P4-01–P4-04), success criteria, known pitfalls
- `.planning/REQUIREMENTS.md` — P4-01 through P4-04

### Phase 10 Context (MUST READ)
- `.planning/phases/10-session-state-simplification/10-CONTEXT.md` — Phase 10 decisions (D-01 through D-18). Key finding: `ServerSession` is NOT dict-like; Phase 10 established `ctx.set_state()`/`ctx.get_state()` as the session state API
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — Phase 5 decisions (D-13 through D-16): `_cached_user` on `ctx.request_context` attribute, auth logging levels

### Auth Architecture
- `nautobot_app_mcp_server/mcp/auth.py` — CURRENT `get_user_from_request()` — must be refactored to async + FastMCP state API
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — auth tests to update after refactor

### Prior Phase Context
- `.planning/phases/02-authentication-sessions/02-CONTEXT.md` — Original auth decisions (D-22 through D-25): token extraction, logging levels, AnonymousUser behavior

### FastMCP State API (Phase 10 verified)
- `.planning/phases/10-session-state-simplification/10-CONTEXT.md` §FastMCP 3.2.0 Internals — `ctx.set_state()`/`ctx.get_state()` implementation notes

### Documentation
- `docs/admin/upgrade.md` — add nginx `proxy_set_header Authorization` section

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Files to Modify
- `nautobot_app_mcp_server/mcp/auth.py` — **refactor to async**; `get_user_from_request` becomes `async def`; replace `_cached_user` attribute with `await ctx.set_state("mcp:cached_user", str(user.pk))`; replace cache check with `await ctx.get_state("mcp:cached_user")`
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — update tests for async `get_user_from_request` and new cache mechanism (session-state based, not attribute-based)
- `nautobot_app_mcp_server/mcp/tools/core.py` — update `get_user_from_request` call sites to `await get_user_from_request(ctx)` (now async)
- `docs/admin/upgrade.md` — add nginx configuration section

### Reusable Assets
- `ctx.set_state()` / `ctx.get_state()` — Phase 10's async session state API; `session_tools.py` already uses this pattern
- `_get_enabled_scopes` / `_set_enabled_scopes` — Phase 10 async helpers in `session_tools.py`; same pattern applies here

### Key Implementation Detail
- `get_user_from_request()` is called from all 10 core tools in `core.py`. After refactor, it becomes `async def`. All 10 call sites must change to `await get_user_from_request(ctx)`.
- The cache stores user ID (string), not the user object. On cache hit, the user is re-fetched by ID from DB. This avoids Token table lookup on every call but still ensures the user is valid.

### Test Patterns
- `_make_mock_ctx()` in `test_auth.py` will need `AsyncMock` or `async` fixtures for `get_state`/`set_state`
- Current cache test (`test_cached_user_returned_on_second_call`) checks `_cached_user` attribute — must be rewritten to check `ctx.get_state()` behavior

### Integration Points
- `auth.py` → `core.py`: `get_user_from_request` is imported and called in all 10 core tools
- `auth.py` → `core.py`: `restrict(user, "view")` call is unaffected — user object is still returned

</codebase_context>

<deferred>
## Deferred Ideas

- **Active user check** — whether to validate user `.is_active` before returning. Not in Phase 11 scope. Can be added if needed.
- **Redis session backend** — v2 scope. In-memory `MemoryStore` sufficient for v1.2.0 with `--workers 1`.

</deferred>

---

*Phase: 11-auth-refactor*
*Context gathered: 2026-04-05*
