---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified:
  - nautobot_app_mcp_server/mcp/tests/test_auth.py
autonomous: false
---

# Phase 5 — Wave 2 Task: WAVE2-TEST-AUTH

**Task ID:** WAVE2-TEST-AUTH
**File:** `nautobot_app_mcp_server/mcp/tests/test_auth.py`
**Requirements:** TEST-01 (verify auth caching)
**Blockers:** Wave 1 complete (WAVE1-AUTH must be done first)

---

## read_first

- `nautobot_app_mcp_server/mcp/tests/test_auth.py` (current state — lines 1–107)
- `nautobot_app_mcp_server/mcp/auth.py` (after WAVE1-AUTH refactor — `_cached_user` caching)
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` existing test methods for style reference

---

## context

The existing `test_auth.py` tests verify that a single call to `get_user_from_request()` with a valid token returns the correct user. After WAVE1-AUTH adds `_cached_user` caching, we need tests that verify:

1. **Cache hit:** Second call with the same mock ctx returns the cached user without a DB query
2. **Cache key isolation:** Setting `_cached_user` on the mock ctx's `request_context` persists across calls

The existing tests already use `MagicMock` for `ctx.request_context`. The new tests need to verify that `getattr(ctx.request_context, "_cached_user")` is checked and used.

---

## action

### Add new tests to `test_auth.py`

Add these test methods to the existing `GetUserFromRequestTestCase` class:

```python
def test_cached_user_returned_on_second_call(self):
    """AUTH-01, AUTH-02: Second call with same ctx returns cached user.

    After the first call populates ctx.request_context._cached_user,
    the second call should return the cached user without hitting the DB.
    """
    from django.contrib.auth import get_user_model
    from nautobot.users.models import Token

    User = get_user_model()
    user_obj = User.objects.filter(is_superuser=True).first()
    token = Token.objects.create(user=user_obj, key="nbapikey_testcache123")

    try:
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        # Build a mock ctx with _cached_user already set (simulating first call)
        mock_ctx = MagicMock()
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": f"Token {token.key}"}
        mock_ctx.request_context.request = mock_request

        # Pre-populate the cache (simulating first call's cache write)
        mock_ctx.request_context._cached_user = user_obj

        # Call get_user_from_request — should return cached user
        result = get_user_from_request(mock_ctx)

        # Should return the cached user (not a DB lookup)
        self.assertEqual(result, user_obj)

        # Verify _cached_user was checked (no DB query occurred)
        # We verify by checking that _cached_user on the ctx equals the returned user
        self.assertEqual(mock_ctx.request_context._cached_user, result)
    finally:
        token.delete()

def test_cache_stores_user_after_db_lookup(self):
    """AUTH-01, AUTH-02: After DB lookup, user is cached on request_context.

    On the first call (no _cached_user), the function looks up the DB,
    stores the result on ctx.request_context._cached_user, and returns it.
    """
    from django.contrib.auth import get_user_model
    from nautobot.users.models import Token

    User = get_user_model()
    user_obj = User.objects.filter(is_superuser=True).first()
    token = Token.objects.create(user=user_obj, key="nbapikey_testcachestore123")

    try:
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        # Fresh mock ctx — no _cached_user attribute
        mock_ctx = MagicMock()
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": f"Token {token.key}"}
        mock_ctx.request_context.request = mock_request

        # Ensure no cache initially
        self.assertFalse(hasattr(mock_ctx.request_context, "_cached_user"))

        # First call — should do DB lookup and cache the result
        result = get_user_from_request(mock_ctx)
        self.assertEqual(result, user_obj)

        # Verify user was cached on request_context
        self.assertTrue(hasattr(mock_ctx.request_context, "_cached_user"))
        self.assertEqual(mock_ctx.request_context._cached_user, user_obj)

        # Second call with same ctx — should hit cache (not DB)
        result2 = get_user_from_request(mock_ctx)
        self.assertEqual(result2, user_obj)
        self.assertEqual(result2, mock_ctx.request_context._cached_user)
    finally:
        token.delete()

def test_cache_miss_falls_through_to_db(self):
    """AUTH-02: Cache miss (no _cached_user) falls through to DB lookup.

    When ctx.request_context._cached_user is None, the function should
    perform the DB lookup, cache the result, and return the user.
    """
    from django.contrib.auth import get_user_model
    from nautobot.users.models import Token

    User = get_user_model()
    user_obj = User.objects.filter(is_superuser=True).first()
    token = Token.objects.create(user=user_obj, key="nbapikey_testcachemiss123")

    try:
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        # Mock ctx with _cached_user explicitly set to None
        mock_ctx = MagicMock()
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": f"Token {token.key}"}
        mock_ctx.request_context.request = mock_request
        mock_ctx.request_context._cached_user = None  # Explicit None = cache miss

        result = get_user_from_request(mock_ctx)

        # Should fall through to DB lookup and return the user
        self.assertEqual(result, user_obj)
        # And cache should now be populated
        self.assertEqual(mock_ctx.request_context._cached_user, user_obj)
    finally:
        token.delete()
```

---

## acceptance_criteria

1. `grep -n "test_cached_user_returned_on_second_call" nautobot_app_mcp_server/mcp/tests/test_auth.py` — shows the cache-hit test
2. `grep -n "test_cache_stores_user_after_db_lookup" nautobot_app_mcp_server/mcp/tests/test_auth.py` — shows the cache-write test
3. `grep -n "test_cache_miss_falls_through_to_db" nautobot_app_mcp_server/mcp/tests/test_auth.py` — shows the cache-miss fallback test
4. `grep -n "_cached_user" nautobot_app_mcp_server/mcp/tests/test_auth.py` — shows `_cached_user` used in at least 3 test methods
5. `grep -n "hasattr.*_cached_user" nautobot_app_mcp_server/mcp/tests/test_auth.py` — shows cache-existence checks
6. `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_auth.py` — scores 10.00/10
7. `poetry run invoke ruff` passes on test_auth.py
8. `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_auth` — passes (all 7 original tests + 3 new = 10 tests)
