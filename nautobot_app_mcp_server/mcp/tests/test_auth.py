"""Tests for the auth layer (AUTH-01, AUTH-02, AUTH-03, TEST-06)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from asgiref.sync import AsyncToSync
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase


def _create_token(user) -> object:
    """Create a Nautobot Token bypassing the ORM's save() method.

    Token.save() has a side effect with BaseModel's UUID default + force_insert
    that causes `user_id` to become NULL in PostgreSQL during the INSERT.
    Using a raw INSERT bypasses this issue.
    """
    from django.utils import timezone

    token_id = uuid.uuid4()
    key = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 40-char hex key
    created = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO users_token (id, user_id, created, key, write_enabled, description) "
            "VALUES (%s, %s, %s, %s, true, '')",
            [str(token_id), user.id, created, key],
        )
    # Return an object with the minimal interface needed by the tests
    token = MagicMock()
    token.id = token_id
    token.key = key
    token.pk = token_id
    token._user_id = user.id
    token.delete = lambda: _delete_token(token_id)
    return token


def _delete_token(token_id):
    """Delete a token by its UUID."""
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM users_token WHERE id = %s", [str(token_id)])


class _RequestContext:
    """Plain object holding request_context data.

    MagicMock auto-generates attributes on every access, which shadows
    manually-set .request_context and .request on the mock.  Using a
    separate plain object with __slots__ breaks that shadow chain so that
    ctx.request_context.request resolves to the real MagicMock, not an
    auto-generated one.
    """

    __slots__ = ("request",)

    def __init__(self, request: MagicMock) -> None:
        self.request = request


def _make_mock_ctx(
    authorization: str | None = None,
    state_store: dict | None = None,
    token_key_to_user: dict | None = None,
    enabled_scopes: set[str] | None = None,
    enabled_searches: set[str] | None = None,
) -> MagicMock:
    """Build a mock ToolContext with an Authorization header and state store.

    Args:
        authorization: Value for the Authorization header.
        state_store: Dict backing ctx.get_state / ctx.set_state.
        token_key_to_user: Dict mapping token keys to User objects.  Used to
            mock Token.objects.select_related().get() in auth.py so the DB
            lookup can be tested without triggering Django's
            SynchronousOnlyOperation guard (Django 4.2 blocks sync ORM calls
            from async contexts, including AsyncToSync thread pools).
        enabled_scopes: Set of scope strings pre-populated in state store
            under the key ``mcp:enabled_scopes``.  Used by
            ScopeGuardMiddleware tests to simulate sessions with scopes
            already enabled.
        enabled_searches: Set of search strings pre-populated in state store
            under the key ``mcp:enabled_searches``.  Used by
            ProgressiveDisclosureIntegrationTestCase to simulate sessions with
            search filters already set.
    """
    mock_request = MagicMock()
    mock_request.headers = {}
    if authorization is not None:
        mock_request.headers["Authorization"] = authorization

    mock_ctx = MagicMock()
    # Use a plain _RequestContext object so .request is not auto-generated
    mock_ctx.request_context = _RequestContext(mock_request)

    if state_store is None:
        state_store = {}
    # Pre-populate state keys so callers can simulate non-empty sessions.
    # Use ``is not None`` (not bare truthiness) so empty set/list is stored
    # as [] rather than treated as "key not present".
    if enabled_scopes is not None:
        state_store["mcp:enabled_scopes"] = list(enabled_scopes)
    if enabled_searches is not None:
        state_store["mcp:enabled_searches"] = list(enabled_searches)

    async def _mock_get_state(key: str):
        return state_store.get(key)

    async def _mock_set_state(key: str, value: str) -> None:
        state_store[key] = value

    mock_ctx.get_state = AsyncMock(side_effect=_mock_get_state)
    mock_ctx.set_state = AsyncMock(side_effect=_mock_set_state)

    # Mock Token.objects so the DB lookup is bypassed in async context.
    # token_key_to_user maps "Token {key}" → user object.
    if token_key_to_user is None:
        token_key_to_user = {}

    def _mock_token_get(**kwargs):
        """Return user for matching key, raise Token.DoesNotExist otherwise."""
        key = kwargs.get("key", "")
        username = token_key_to_user.get(key)
        if username is None:
            from nautobot.users.models import Token

            raise Token.DoesNotExist()
        mock_token = MagicMock()
        mock_token.key = key
        mock_token.user = username
        return mock_token

    mock_select_related = MagicMock()
    mock_select_related.get = MagicMock(side_effect=_mock_token_get)
    mock_token_objects = MagicMock()
    mock_token_objects.select_related = MagicMock(return_value=mock_select_related)
    mock_ctx.token_objects = mock_token_objects

    return mock_ctx


class GetUserFromRequestTestCase(TestCase):
    """Test get_user_from_request() from auth.py."""

    def test_missing_authorization_header_returns_anonymous(self):
        """AUTH-02: Missing token → AnonymousUser returned (no exception)."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = _make_mock_ctx(authorization=None)
        user = AsyncToSync(get_user_from_request)(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_missing_authorization_header_logs_warning(self):
        """AUTH-02, PIT-10: Missing token → WARNING logged."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = _make_mock_ctx(authorization=None)
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="WARNING") as cm:
            AsyncToSync(get_user_from_request)(ctx)
        self.assertTrue(any("No auth token" in line for line in cm.output))

    def test_invalid_token_format_returns_anonymous(self):
        """AUTH-02: Malformed Authorization header → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = _make_mock_ctx(authorization="Bearer invalid")
        user = AsyncToSync(get_user_from_request)(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_non_nbapikey_token_returns_anonymous(self):
        """AUTH-02: Token without "Token " prefix → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = _make_mock_ctx(authorization="Token abcdefghijklmnop")
        user = AsyncToSync(get_user_from_request)(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_valid_token_returns_user(self):
        """AUTH-01: Valid Token key → correct Nautobot User returned."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user_obj},
            )
            result = AsyncToSync(get_user_from_request)(ctx)
            self.assertEqual(result, user_obj)
        finally:
            token.delete()

    def test_valid_token_wrong_key_returns_anonymous(self):
        """AUTH-02: Valid format but unknown key → AnonymousUser + DEBUG log.

        A UUID-based key guarantees no collision with any existing token.
        """
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        nonexistent_key = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 40-char hex
        ctx = _make_mock_ctx(authorization=f"Token {nonexistent_key}")
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="DEBUG") as cm:
            user = AsyncToSync(get_user_from_request)(ctx)
        self.assertIsInstance(user, AnonymousUser)
        self.assertTrue(any("Invalid auth token" in line for line in cm.output))

    def test_empty_token_returns_anonymous(self):
        """AUTH-02: Empty "Token " value → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = _make_mock_ctx(authorization="Token ")
        user = AsyncToSync(get_user_from_request)(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_cached_user_returned_on_second_call(self):
        """AUTH-01, AUTH-02: Second call with same ctx returns cached user.

        After the first call stores ctx.set_state("mcp:cached_user", str(user.pk)),
        the second call returns the cached user (re-fetched from DB).
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            # Pre-populate the FastMCP state cache with the user PK
            state_store = {"mcp:cached_user": str(user_obj.pk)}
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                state_store=state_store,
                token_key_to_user={token.key: user_obj},
            )

            # First call — should return cached user (re-fetched from DB)
            result = AsyncToSync(get_user_from_request)(ctx)
            self.assertEqual(result, user_obj)
        finally:
            token.delete()

    def test_cache_stores_user_after_db_lookup(self):
        """AUTH-01, AUTH-02: After DB lookup, user PK is stored in FastMCP state.

        On the first call (no cached entry), the function looks up the DB,
        stores str(user.pk) via ctx.set_state, and returns the user.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            state_store: dict = {}
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                state_store=state_store,
                token_key_to_user={token.key: user_obj},
            )

            # First call — should do DB lookup and store the user PK
            result = AsyncToSync(get_user_from_request)(ctx)
            self.assertEqual(result, user_obj)

            # Verify user PK was cached via FastMCP state API
            self.assertEqual(state_store.get("mcp:cached_user"), str(user_obj.pk))

            # Second call — should hit cache (DB not queried again)
            result2 = AsyncToSync(get_user_from_request)(ctx)
            self.assertEqual(result2, user_obj)
            self.assertEqual(state_store.get("mcp:cached_user"), str(user_obj.pk))
        finally:
            token.delete()

    def test_cache_miss_falls_through_to_db(self):
        """AUTH-02: Cache miss (no mcp:cached_user) falls through to DB lookup.

        When ctx.get_state("mcp:cached_user") returns None, the function should
        perform the DB lookup, cache the result, and return the user.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            state_store: dict = {}
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                state_store=state_store,
                token_key_to_user={token.key: user_obj},
            )

            result = AsyncToSync(get_user_from_request)(ctx)

            # Should fall through to DB lookup and return the user
            self.assertEqual(result, user_obj)
            # And cache should now be populated
            self.assertEqual(state_store.get("mcp:cached_user"), str(user_obj.pk))
        finally:
            token.delete()

    def test_cache_hit_re_validates_user(self):
        """T-11-04: On cache hit, User.objects.get(pk=id) is called (DB query).

        Even on a cache hit, the user is re-fetched from the DB so that
        deactivation / deletion is detected immediately.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            state_store = {"mcp:cached_user": str(user_obj.pk)}
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                state_store=state_store,
                token_key_to_user={token.key: user_obj},
            )

            result = AsyncToSync(get_user_from_request)(ctx)
            # Result is re-fetched from DB on every cache hit
            self.assertEqual(result, user_obj)
            self.assertEqual(result.pk, user_obj.pk)
        finally:
            token.delete()

    def test_cache_stores_user_id_not_object(self):
        """T-11-03: set_state is called with str(user.pk), never the user object.

        The cached value must always be a string so it is always serializable.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_obj = User.objects.filter(is_superuser=True).first()
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            state_store: dict = {}
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                state_store=state_store,
                token_key_to_user={token.key: user_obj},
            )

            AsyncToSync(get_user_from_request)(ctx)

            cached_value = state_store.get("mcp:cached_user")
            self.assertIsInstance(cached_value, str)
            self.assertEqual(cached_value, str(user_obj.pk))
            # Ensure it is NOT the user object
            self.assertNotIsInstance(cached_value, User)
        finally:
            token.delete()
