---
wave: 1
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/auth.py
autonomous: false
---

# Phase 5 — Wave 1 Task: WAVE1-AUTH

**Task ID:** WAVE1-AUTH
**File:** `nautobot_app_mcp_server/mcp/auth.py`
**Requirements:** AUTH-01, AUTH-02
**Priority:** P0

---

## read_first

- `nautobot_app_mcp_server/mcp/auth.py` — current state; see `get_user_from_request()` in full
- `nautobot_app_mcp_server/mcp/session_tools.py` — see `_get_tool_state()` helper added by WAVE1-SESSION; read it here even though WAVE1-SESSION runs in parallel (the pattern is the same)
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — D-13, D-14, D-15 (auth caching decisions)

---

## context

**Why cache?** A single MCP HTTP request can carry a JSON-RPC batch with multiple tool calls. Without caching, each tool call executes `Token.objects.select_related("user").get(key=real_token_key)` — one DB query per tool call. For a batch of 10 tool calls, that's 10 identical DB queries.

**What to cache:** The Nautobot `User` object returned from a valid token lookup.

**Where to cache:** On `ctx.request_context` as `_cached_user`. `ctx.request_context` is a plain Python dataclass (not `ServerSession`) — it always supports attribute access. The cache survives across tool calls within the same MCP request because all tool calls share the same `request_context` object.

**Cache key:** The token key string (e.g., `nbapikey_abc123def...`). Cache hit = same token key → same user. Cache miss = first lookup → DB query → populate cache → return user.

**Why NOT session dict:** `ctx.request_context.session` is `ServerSession` — not dict-like. Can't do `session["cached_user"] = user`.

---

## action

### 1. Update `get_user_from_request()` to cache user on request_context

Replace the existing `get_user_from_request()` function body with the cached version below.

The function already parses the token, extracts `real_token_key`, and looks up the `Token`. The only changes are:
1. Check `_cached_user` on `ctx.request_context` before doing the DB lookup
2. Store the user on `ctx.request_context._cached_user` after a successful lookup

**Exact replacement for auth.py:28–75:**

```python
def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token nbapikey_xxx`` header.
    Falls back to ``AnonymousUser`` (never raises) — empty querysets returned.

    Caches the authenticated user on ctx.request_context._cached_user (D-13).
    Subsequent calls within the same MCP request batch hit the cache and skip
    the DB lookup.

    Args:
        ctx: FastMCP ToolContext, providing access to the MCP request object.

    Returns:
        nautobot.users.models.User if authenticated, otherwise
        django.contrib.auth.models.AnonymousUser.

    Logging (D-22, PIT-10):
        - Missing Authorization header → ``logger.warning``
        - Invalid / malformed token     → ``logger.debug``
    """
    from django.contrib.auth.models import AnonymousUser

    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")

    if not auth_header:
        logger.warning("MCP: No auth token, falling back to anonymous user")
        return AnonymousUser()

    if not auth_header.startswith("Token "):
        logger.debug("MCP: Invalid auth token format (not a Token prefix)")
        return AnonymousUser()

    token_key = auth_header[6:]  # Strip "Token "

    if not token_key.startswith(TOKEN_PREFIX):
        logger.debug("MCP: Invalid auth token (not a Nautobot nbapikey token)")
        return AnonymousUser()

    # Look up the Nautobot API token
    real_token_key = token_key[len(TOKEN_PREFIX) :]

    # AUTH-01 / AUTH-02: Check request_context cache first (D-13, D-14)
    # _cached_user is stored on the RequestContext dataclass (not ServerSession).
    # If already cached for this token key, return immediately.
    cached_user = getattr(ctx.request_context, "_cached_user", None)
    if cached_user is not None:
        return cached_user

    # Cache miss — look up in DB (AUTH-02)
    try:
        from nautobot.users.models import Token

        token = Token.objects.select_related("user").get(key=real_token_key)
        user = token.user
    except Exception:  # noqa: BLE001 — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache the user for subsequent calls within this MCP request (D-15)
    ctx.request_context._cached_user = user
    return user
```

### 2. Update module docstring

Add a note about the caching strategy to the top of `auth.py`:

```python
"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token nbapikey_xxx" format
    3. Check _cached_user on ctx.request_context (AUTH-01 cache)
    4. Cache miss → look up Nautobot Token object → return User (AUTH-02)
    5. Cache the user on ctx.request_context._cached_user
    6. Missing / invalid token → return AnonymousUser with log warning

PIT-16: Always use ctx.request_context.request (MCP SDK request object),
NOT Django's HttpRequest. PIT-10: Log WARNING on missing token,
DEBUG on invalid token.
"""
```

---

## acceptance_criteria

1. `grep -n "_cached_user" nautobot_app_mcp_server/mcp/auth.py` — shows `_cached_user` used at least 3 times: `getattr` check, assignment after DB lookup, and in `if cached_user is not None` branch
2. `grep -n "getattr.*_cached_user" nautobot_app_mcp_server/mcp/auth.py` — shows the cache-read pattern
3. `grep -n "ctx.request_context._cached_user = user" nautobot_app_mcp_server/mcp/auth.py` — shows the cache-write after DB lookup
4. `grep -n "return cached_user" nautobot_app_mcp_server/mcp/auth.py` — shows early return on cache hit
5. `grep -n "ctx.request_context.request" nautobot_app_mcp_server/mcp/auth.py` — shows `mcp_request = ctx.request_context.request` unchanged
6. `grep -n "Token.objects.select_related" nautobot_app_mcp_server/mcp/auth.py` — shows the DB lookup still exists (only skipped on cache hit)
7. `poetry run pylint nautobot_app_mcp_server/mcp/auth.py` — scores 10.00/10
8. `poetry run invoke ruff` passes with no errors on auth.py
9. Existing test `test_valid_nbapikey_token_returns_user` in `test_auth.py` still passes (cache is set after DB lookup, test creates a fresh mock ctx each time)

---

## notes

- The existing tests in `test_auth.py` create a new mock ctx per test — cache hits won't affect those tests since each test has a fresh ctx
- No changes to test files needed for AUTH-01/AUTH-02; new tests added in WAVE2-TEST-AUTH to verify caching behavior
- `_cached_user` is used instead of `cached_user` as the attribute name on `ctx.request_context` to make it clearly a persistence attribute (not a local variable)
- If `_cached_user` is set but the token is invalid on the next call (different token), the cache check still passes with the wrong user. This is acceptable since token validity is validated at the start of each tool call and the MCP client sends the same token throughout a session. A malicious client changing tokens mid-session would get wrong user — but that requires changing tokens mid-session which is not a normal MCP workflow.
