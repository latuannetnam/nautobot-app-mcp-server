# Phase 11: Auth Refactor — Research

**Research date:** 2026-04-05
**Status:** Ready for planning
**Requirements:** P4-01, P4-02, P4-03, P4-04

---

## 1. FastMCP `ctx.set_state` / `ctx.get_state` — Exact Signatures and Behavior

**Source:** `.venv/lib/python3.12/site-packages/fastmcp/server/context.py` lines 1195–1249.

### `set_state`

```python
async def set_state(
    self, key: str, value: Any, *, serializable: bool = True
) -> None:
```

- `key`: arbitrary string, auto-prefixed with `{session_id}:` internally via `_make_state_key()` (line 1191–1193). Key for auth will be `"mcp:cached_user"`.
- `value`: any JSON-serializable value by default. User IDs stored as `str(user.pk)` — always JSON-serializable.
- `serializable=True` (default): stored in FastMCP's `MemoryStore` (`_state_store`), persists across requests within the same MCP session, keyed by `{session_id}:{key}`. Default TTL: 1 day (`_STATE_TTL_SECONDS = 86400`).
- `serializable=False`: stored in `_request_state` dict, request-scoped only (cleared between requests). **Not used here** — we want per-session caching.

**Exception handling (lines 1218–1235):** If Pydantic serialization fails, raises `TypeError` with a clear message. This will only fire for non-serializable values — string user IDs are safe.

### `get_state`

```python
async def get_state(self, key: str) -> Any:  # lines 1237–1249
```

- Checks `_request_state` dict first (request-scoped, `serializable=False` values), then falls back to `_state_store`.
- **Returns `None` if key not found** — callers must handle None (Phase 10 pattern: `set(val) if val else set()`).
- No `await` needed beyond the call itself — already `async def`.

### `_make_state_key` (private, used internally)

```python
def _make_state_key(self, key: str) -> str:  # lines 1191–1193
    return f"{self.session_id}:{key}"
```

- Session ID comes from `mcp-session-id` HTTP header (StreamableHTTP) or generated UUID (STDIO/SSE). TTL: 1 day.
- The prefixed key `"mcp_session_id:mcp:cached_user"` is what actually gets stored in `MemoryStore`.

### Verified behavior from Phase 10 (`session_tools.py` lines 52–71)

```python
async def _get_enabled_scopes(ctx: ToolContext) -> set[str]:
    val = await ctx.get_state(_ENABLED_SCOPES_KEY)
    return set(val) if val else set()

async def _set_enabled_scopes(ctx: ToolContext, scopes: set[str]) -> None:
    await ctx.set_state(_ENABLED_SCOPES_KEY, list(scopes))
```

- State key constant: `_ENABLED_SCOPES_KEY = "mcp:enabled_scopes"`
- Stored value: `list[str]` (serializable). For user cache: `str(user.pk)`.
- The `ToolScopeState` dataclass wraps these helpers — same pattern applies to auth.

### Key implication for Phase 11

The auth cache stores **user ID string** (not the user object). On cache hit:
1. `cached_user_id = await ctx.get_state("mcp:cached_user")` → `"<uuid-str>"`
2. Fetch user from DB by ID: `User.objects.get(pk=cached_user_id)` — confirms user still exists and is active

This is a deliberate design choice: user objects are not JSON-serializable, so we can't cache them directly in `MemoryStore`.

---

## 2. `get_user_from_request()` — Current Implementation and Async Migration

**Current:** `nautobot_app_mcp_server/mcp/auth.py` (87 lines)

### Current sync implementation

```python
def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
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

    # Check request_context cache (D-13, D-14)
    cached_user = getattr(ctx.request_context, "_cached_user", None)
    if cached_user is not None:
        return cached_user

    # Cache miss — look up in DB (AUTH-02)
    try:
        from nautobot.users.models import Token
        token = Token.objects.select_related("user").get(key=token_key)
        user = token.user
    except Exception:  # noqa: BLE001
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache for subsequent calls
    ctx.request_context._cached_user = user
    return user
```

### What changes for async

| Aspect | Current | After refactor |
|--------|---------|----------------|
| Function signature | `def get_user_from_request(ctx)` | `async def get_user_from_request(ctx)` |
| Header access | `mcp_request.headers.get("Authorization", "")` | **unchanged** — `ctx.request_context.request` is Starlette `Request`; `.headers` is `Headers` object, same interface |
| Cache check | `getattr(ctx.request_context, "_cached_user", None)` | `await ctx.get_state("mcp:cached_user")` |
| Cache write | `ctx.request_context._cached_user = user` | `await ctx.set_state("mcp:cached_user", str(user.pk))` |
| Cache hit behavior | Return cached user object directly | Fetch user from DB by ID (`User.objects.get(pk=cached_user_id)`) |
| Return type | `nautobot.users.models.User` | **unchanged** — same user object returned |
| Exception handling | `except Exception` (broad) | **unchanged** — still catches `Token.DoesNotExist`, DB errors |

### New async implementation (draft)

```python
_CACHED_USER_KEY = "mcp:cached_user"

async def get_user_from_request(ctx: ToolContext):
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token <40-char-hex>`` header.
    Falls back to ``AnonymousUser`` (never raises).

    Caches the user ID in FastMCP session state via ctx.set_state("mcp:cached_user").
    Subsequent calls within the same MCP session hit the cache and re-fetch
    the user by ID (validates user still exists).

    Args:
        ctx: FastMCP ToolContext.

    Returns:
        nautobot.users.models.User if authenticated, otherwise
        django.contrib.auth.models.AnonymousUser.
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

    # P4-02: Check FastMCP session state cache
    cached_user_id = await ctx.get_state(_CACHED_USER_KEY)
    if cached_user_id is not None:
        # Re-fetch user by ID to ensure still valid/active
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            return User.objects.get(pk=cached_user_id)
        except Exception:  # noqa: BLE001 — user deleted/deactivated
            # Cache is stale; fall through to re-authenticate
            pass

    # Cache miss — look up token in DB
    try:
        from nautobot.users.models import Token
        token = Token.objects.select_related("user").get(key=token_key)
        user = token.user
    except Exception:  # noqa: BLE001
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache user ID for subsequent calls within this session
    await ctx.set_state(_CACHED_USER_KEY, str(user.pk))
    return user
```

### `_cached_user` removal

- `_cached_user` attribute on `ctx.request_context` — **deleted**. It is no longer set or read.
- `auth.py` no longer needs `getattr` or `hasattr` checks against `ctx.request_context`.
- Phase 10 D-17/D-18 finding: `ServerSession` is NOT dict-like; Phase 5's attribute cache on `RequestContext` was a workaround for the non-dict session. FastMCP's `MemoryStore` via `ctx.set_state`/`ctx.get_state` is the correct session-scoped API.

### Starlette `Request.headers` interface

`ctx.request_context.request` is a **Starlette `Request`** object (not Django `HttpRequest`). From `starlette.requests.Request`:

```python
@property
def headers(self) -> Headers:
    """Returns the request headers as a mapping of lowercase names to values."""
```

Starlette `Headers` class (from `starlette.datastructures.Headers`):
- Inherits from `Mapping[str, str]`
- Subscriptable: `headers["Authorization"]` returns the string value
- Case-insensitive key lookup (RFC 7230 compliant)
- `Headers.get(name: str, default: str = "") -> str` — exactly what the current code uses

**No change needed** to header access code. `mcp_request.headers.get("Authorization", "")` works identically.

---

## 3. All 10 Call Sites in `core.py` — Changes Required

**File:** `nautobot_app_mcp_server/mcp/tools/core.py`

Each of the 10 handlers currently calls:
```python
user = get_user_from_request(ctx)  # sync
```

Each becomes:
```python
user = await get_user_from_request(ctx)  # async
```

The import line (`from nautobot_app_mcp_server.mcp.auth import get_user_from_request`) is unchanged — the function name stays the same, only the call site adds `await`.

### All 10 affected handlers

| Handler | Line | Change |
|---------|------|--------|
| `_device_list_handler` | 49 | `user = get_user_from_request(ctx)` → `user = await get_user_from_request(ctx)` |
| `_device_get_handler` | 83 | same |
| `_interface_list_handler` | 114 | same |
| `_interface_get_handler` | 146 | same |
| `_ipaddress_list_handler` | 175 | same |
| `_ipaddress_get_handler` | 207 | same |
| `_prefix_list_handler` | 236 | same |
| `_vlan_list_handler` | 267 | same |
| `_location_list_handler` | 298 | same |
| `_search_by_name_handler` | 345 | same |

**Total diff:** 10 lines changed, each adding `await` before `get_user_from_request(ctx)`.

The downstream `.restrict(user, "view")` calls in `query_utils._sync_*` functions are **unchanged** — the user object returned is identical in shape. No changes to `query_utils.py` are required.

### `_sync_*` wrapper functions unaffected

Each handler uses `sync_to_async`:
```python
return await sync_to_async(query_utils._sync_device_list, thread_sensitive=True)(
    user=user, limit=limit, cursor=cursor
)
```

`get_user_from_request(ctx)` runs in the `async def` handler (before the `sync_to_async` call), so it uses the async event loop thread. The `sync_to_async` call then switches to Django's database thread for the ORM query. This is the correct pattern already established by Phase 9.

---

## 4. Auth Tests — What Changes

**File:** `nautobot_app_mcp_server/mcp/tests/test_auth.py` (249 lines)

### Key challenge: `get_state`/`set_state` are async on `MagicMock`

The current `_make_mock_ctx()` creates a `MagicMock` with `request_context` set to a plain `_BareRequestContext` object. It tests the `_cached_user` attribute directly.

After refactoring:
- `get_state("mcp:cached_user")` → async call returning cached user ID or `None`
- `set_state("mcp:cached_user", str(user.pk))` → async call with no return

**`MagicMock` async behavior:** `MagicMock()` returns another `MagicMock` for any attribute/method call, including awaited calls. So `await mock_ctx.get_state("mcp:cached_user")` returns a `MagicMock`, not `None`. Tests must explicitly configure async mock behavior.

### Required test changes

#### `test_cached_user_returned_on_second_call`

**Current:** Checks `_cached_user` attribute on `ctx.request_context`.

**After:** Must test that on second call, `ctx.get_state("mcp:cached_user")` returns the cached user ID and the user is re-fetched from DB.

Test fixture needs:
```python
# Shared state dict for the mock
_store: dict[str, str | None] = {}

class _BareRequestContext:
    def __init__(self):
        self.request = mock_request

async def _mock_get_state(key: str):
    return _store.get(key)

async def _mock_set_state(key: str, value: str):
    _store[key] = value

mock_ctx.get_state = _mock_get_state       # type: ignore[method-assign]
mock_ctx.set_state = _mock_set_state       # type: ignore[method-assign]
```

This is the **same pattern** used in `test_session_tools.py` for `_get_enabled_scopes`/`_set_enabled_scopes` — verified working in Phase 10.

#### `test_cache_stores_user_after_db_lookup`

**Current:** Checks `ctx.request_context._cached_user = user_obj` after first call.

**After:** Verify that `await ctx.set_state("mcp:cached_user", str(user_obj.pk))` was called. Can use `AsyncMock` with `assert_awaited_once_with`.

#### `test_cache_miss_falls_through_to_db`

**Current:** Checks `ctx.request_context._cached_user` is set after cache miss.

**After:** Verify `await ctx.get_state("mcp:cached_user")` returns `None` on first call (cache miss → DB lookup → `set_state` called).

#### `test_valid_token_returns_user`

**Current:** Sync call `get_user_from_request(mock_ctx)`.

**After:** `await get_user_from_request(mock_ctx)` — must be `async def` test or use `AsyncTestCase`.

**Django's `TestCase` runs test methods synchronously.** The `async def` tests can use `@async_to_sync` wrapper (from `asgiref.sync`) to run the async `get_user_from_request` call inside a sync test method. This avoids converting the entire test class to `AsyncTestCase`.

```python
from asgiref.sync import async_to_sync

def test_valid_token_returns_user(self):
    async def _run():
        return await get_user_from_request(mock_ctx)
    result = async_to_sync(_run)()
    self.assertEqual(result, user_obj)
```

Alternatively, Django 4.2+ `AsyncTestCase` supports `async def test_*` directly — but `async_to_sync` wrapper is simpler and consistent with the existing sync test infrastructure.

#### New tests to add

- **Token ID cached (not full user):** After valid token lookup, verify `ctx.set_state` was called with `str(user.pk)` (a string), not the user object.
- **Cache hit re-fetches user:** On second call with valid cached ID, verify `User.objects.get(pk=<id>)` is called (DB query), not `Token.objects.get()`. This validates the cache-hit path re-validates the user.

---

## 5. nginx Configuration Snippet

**File:** `docs/admin/upgrade.md` — add after "Worker Process Requirement" section.

### Where to add

Section 4 "Production Deployment (nginx)" — new subsection, or appended to the existing "Production Deployment" block.

### Required directive

```nginx
proxy_set_header Authorization $http_authorization;
```

### Why this is needed

By default, nginx **strips the `Authorization` header** on upstream proxy requests (RFC 7230 §2.7; nginx default behavior for security). Without this directive, the MCP server receives requests with no `Authorization` header, causing all requests to fall back to `AnonymousUser` even when clients send valid tokens.

### Complete minimal nginx config for MCP server

```nginx
# Upstream MCP server (running on port 8005)
upstream nautobot_mcp {
    server 127.0.0.1:8005;
}

server {
    # ... existing Nautobot server block ...

    location /mcp/ {
        proxy_pass http://nautobot_mcp/;

        # Required: forward the Authorization header to the MCP server
        proxy_set_header Authorization $http_authorization;

        # Recommended for HTTP/1.1 keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Documentation location decision

The current `upgrade.md` has:
- Section 1: "Upgrade Guide" (boilerplate)
- Section 2: "Worker Process Requirement" (single worker, systemd, uvicorn)

**Decision:** Add "Production Deployment (nginx)" as Section 3, before "Development" (Section 4) and "Future: Horizontal Scaling" (Section 5). This keeps deployment docs grouped together.

---

## Validation Architecture

### What to verify for each requirement

#### P4-01: Token from FastMCP request headers (`ctx.request_context.request.headers`)

**Test command:**
```bash
docker exec nautobot-app-mcp-server-nautobot-1 \
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_auth
```

**Verification checklist:**
- `grep -n "Authorization" nautobot_app_mcp_server/mcp/auth.py` → finds header access
- `grep -n "mcp_request.headers.get" nautobot_app_mcp_server/mcp/auth.py` → confirms `mcp_request.headers.get("Authorization")` is unchanged
- `grep -c "^async def get_user_from_request" nautobot_app_mcp_server/mcp/auth.py` → `1`
- `grep -n "ctx.request_context.request" nautobot_app_mcp_server/mcp/auth.py` → confirms `mcp_request = ctx.request_context.request` is still used for header access

**Integration test:**
```bash
# Valid token → returns user; invalid token → returns AnonymousUser + log
docker exec nautobot-app-mcp-server-nautobot-1 \
  python /source/nautobot_app_mcp_server/mcp/tests/test_session_persistence.py
```

#### P4-02: Token cached in `ctx.set_state("mcp:cached_user")`

**Test command:**
```bash
docker exec nautobot-app-mcp-server-nautobot-1 \
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_auth \
  --verbosity=2 2>&1 | grep -E "(test_cached_user|test_cache_stores|test_cache_miss)"
```

**Verification checklist:**
- `grep -n "mcp:cached_user" nautobot_app_mcp_server/mcp/auth.py` → 2 occurrences (get + set)
- `grep -n "_cached_user" nautobot_app_mcp_server/mcp/auth.py` → **no matches** (removed)
- `grep -n "await ctx.get_state" nautobot_app_mcp_server/mcp/auth.py` → confirms `get_state` is `await`ed
- `grep -n "await ctx.set_state" nautobot_app_mcp_server/mcp/auth.py` → confirms `set_state` is `await`ed
- `grep -n "str(user.pk)" nautobot_app_mcp_server/mcp/auth.py` → confirms user ID stored as string, not object

**Test behavior verification (file reads):**
```bash
# Verify test_auth.py tests the new cache mechanism
grep -n "get_state\|set_state\|_CACHED_USER_KEY\|_store" \
  nautobot_app_mcp_server/mcp/tests/test_auth.py
```

**Expected:** Tests use `AsyncMock` or shared `_store` dict pattern matching `test_session_tools.py`.

#### P4-03: `.restrict(user, "view")` on all querysets

**Test command:**
```bash
docker exec nautobot-app-mcp-server-nautobot-1 \
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_core_tools \
  --verbosity=2
```

**Verification checklist:**
- `grep -n "\.restrict(" nautobot_app_mcp_server/mcp/tools/query_utils.py` → 10 occurrences (one per `_sync_*` function)
- `grep -n "get_user_from_request" nautobot_app_mcp_server/mcp/tools/core.py` → 10 call sites, all with `await`
- `grep -n "await get_user_from_request" nautobot_app_mcp_server/mcp/tools/core.py` → 10 occurrences

**Unit test isolation:**
- Each `test_core_tools.py` test should create a scoped user and verify `.restrict()` returns only permitted objects. Anonymous user tests already exist and should return empty querysets.

#### P4-04: nginx `proxy_set_header Authorization` documentation

**Test command:**
```bash
grep -n "proxy_set_header Authorization" docs/admin/upgrade.md
```

**Expected output:** At least 1 match, inside a `location /mcp/` or `location /` block.

**Verification checklist:**
```bash
# File content check
grep -A5 "proxy_set_header Authorization" docs/admin/upgrade.md
```

**Expected:** Confirms the directive appears with explanatory comment about header forwarding.

**Build check:**
```bash
poetry run invoke mkdocs
```

Expected: `Generated` output with no errors (validates Markdown syntax).

### Full integration test pipeline

```bash
# 1. Lint
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server
unset VIRTUAL_ENV && poetry run invoke ruff [--fix]

# 2. Pylint
unset VIRTUAL_ENV && poetry run invoke pylint

# 3. All MCP tests (inside container)
docker exec nautobot-app-mcp-server-nautobot-1 \
  poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests

# 4. All app tests
docker exec nautobot-app-mcp-server-nautobot-1 \
  poetry run nautobot-server test nautobot_app_mcp_server

# 5. Docs build
unset VIRTUAL_ENV && poetry run invoke mkdocs
```

**Expected:** All pass with score 10.00/10 on pylint.

### Files modified summary

| File | Changes |
|------|---------|
| `nautobot_app_mcp_server/mcp/auth.py` | `def` → `async def`; `_cached_user` attr → `ctx.get_state/set_state`; cache stores `str(user.pk)` |
| `nautobot_app_mcp_server/mcp/tools/core.py` | 10 call sites: `get_user_from_request(ctx)` → `await get_user_from_request(ctx)` |
| `nautobot_app_mcp_server/mcp/tests/test_auth.py` | Update `_make_mock_ctx()` for async state API; rewrite 3 cache tests; add token-ID-cache test |
| `docs/admin/upgrade.md` | Add nginx `proxy_set_header Authorization` section |

### Files NOT modified (scope boundary)

- `nautobot_app_mcp_server/mcp/tools/query_utils.py` — `.restrict()` call sites untouched
- `nautobot_app_mcp_server/mcp/session_tools.py` — session tools already use `ctx.get_state/set_state`
- `nautobot_app_mcp_server/mcp/commands.py` — no changes needed
- `nautobot_app_mcp_server/mcp/middleware.py` — scope guard middleware untouched

---

*Research synthesized from: auth.py (87 lines), test_auth.py (249 lines), core.py (10 handlers), session_tools.py (ToolScopeState pattern), FastMCP context.py (set_state/get_state at lines 1195–1249), upgrade.md.*
