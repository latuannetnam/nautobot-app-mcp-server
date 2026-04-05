# Phase 11: Auth Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 11-auth-refactor
**Areas discussed:** Cache location, Token source, Restrict behavior, nginx docs

---

## P4-01: Token from FastMCP request headers

| Option | Description | Selected |
|--------|-------------|----------|
| Keep current code: `ctx.request_context.request.headers.get("Authorization")` | Works in Option B — `request` is a Starlette ASGI Request | ✓ |
| Change to new API | No other API available; Starlette Request is the correct interface | |

**User's choice:** Keep current code — confirmed that `ctx.request_context.request` is a Starlette ASGI Request with `.headers` support. No changes needed for P4-01.

**Notes:** Token format (40-char hex, no `nbapikey_` prefix) already correctly documented in `auth.py` line 27 comment. Logging levels (warning on missing, debug on invalid) already correctly implemented.

---

## P4-02: Token cached location

| Option | Description | Selected |
|--------|-------------|----------|
| Keep `. _cached_user` attribute on `ctx.request_context` | Phase 5 pattern; works but technically not "session dict" | |
| Use `ctx.request_context.session["cached_user"]` | ROADMAP wording; BUT `ServerSession` has no dict interface — doesn't work | |
| Use `ctx.set_state("mcp:cached_user")` / `ctx.get_state("mcp:cached_user")` | Phase 10 session state API; consistent, session-scoped | ✓ |

**User's choice:** Option B — use `ctx.set_state`/`ctx.get_state` from FastMCP's MemoryStore. Consistent with Phase 10's `session_tools.py` pattern.

**Notes:** Cache value must be serializable (user ID string, not user object). Cache scope is per-FastMCP-session (keyed by `session_id`), meaning one DB lookup per MCP session vs per request batch. `get_user_from_request` must become `async def`.

---

## P4-03: `.restrict(user, "view")` on all querysets

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve unchanged | All 10 core tools already call `.restrict()`; no refactoring needed | ✓ |

**User's choice:** Preserved unchanged — no work needed.

**Notes:** Flagged question about `is_active` user check — user deferred to future phase. Not in scope.

---

## P4-04: nginx documentation

| Option | Description | Selected |
|--------|-------------|----------|
| Add nginx section to `docs/admin/upgrade.md` | Document `proxy_set_header Authorization $http_authorization;` | ✓ |

**User's choice:** Proceed with docs addition.

**Notes:** PITFALL #7: nginx strips `Authorization` header by default. Must be explicitly forwarded.

---

## Claude's Discretion

- Exact nginx configuration snippet format (which block to add it in, whether to show full location block)
- Whether to add nginx config as a code block or describe the directive inline
- Whether the nginx section goes under existing "Production Deployment" heading or new standalone section
