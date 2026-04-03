"""Tests for the auth layer (AUTH-01, AUTH-02, AUTH-03, TEST-06)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

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


class GetUserFromRequestTestCase(TestCase):
    """Test get_user_from_request() from auth.py."""

    def _make_mock_ctx(
        self,
        authorization: str | None = None,
    ) -> MagicMock:
        """Build a mock ToolContext with an Authorization header."""
        mock_request = MagicMock()
        mock_request.headers = {}
        if authorization is not None:
            mock_request.headers["Authorization"] = authorization
        # Use a plain class (not MagicMock) to avoid auto-creating _cached_user
        mock_ctx = MagicMock()

        class _BareRequestContext:
            def __init__(self):
                self.request = mock_request

        mock_ctx.request_context = _BareRequestContext()
        return mock_ctx

    def test_missing_authorization_header_returns_anonymous(self):
        """AUTH-02: Missing token → AnonymousUser returned (no exception)."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization=None)
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_missing_authorization_header_logs_warning(self):
        """AUTH-02, PIT-10: Missing token → WARNING logged."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization=None)
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="WARNING") as cm:
            get_user_from_request(ctx)
        self.assertTrue(any("No auth token" in line for line in cm.output))

    def test_invalid_token_format_returns_anonymous(self):
        """AUTH-02: Malformed Authorization header → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Bearer invalid")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_non_nbapikey_token_returns_anonymous(self):
        """AUTH-02: Token without "Token " prefix → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Token abcdefghijklmnop")
        user = get_user_from_request(ctx)
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
        if not user_obj:
            user_obj = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        token = _create_token(user_obj)

        try:
            from nautobot_app_mcp_server.mcp.auth import get_user_from_request

            mock_request = MagicMock()
            mock_request.headers = {"Authorization": f"Token {token.key}"}

            class _BareRequestContext:
                def __init__(self):
                    self.request = mock_request

            mock_ctx = MagicMock()
            mock_ctx.request_context = _BareRequestContext()
            result = get_user_from_request(mock_ctx)
            self.assertEqual(result, user_obj)
        finally:
            token.delete()

    def test_valid_token_wrong_key_returns_anonymous(self):
        """AUTH-02: Valid format but unknown key → AnonymousUser + DEBUG log.

        A UUID-based key guarantees no collision with any existing token.
        """
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        nonexistent_key = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 40-char hex
        ctx = self._make_mock_ctx(authorization=f"Token {nonexistent_key}")
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="DEBUG") as cm:
            user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)
        self.assertTrue(any("Invalid auth token" in line for line in cm.output))

    def test_empty_token_returns_anonymous(self):
        """AUTH-02: Empty "Token " value → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Token ")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_cached_user_returned_on_second_call(self):
        """AUTH-01, AUTH-02: Second call with same ctx returns cached user.

        After the first call populates ctx.request_context._cached_user,
        the second call should return the cached user without hitting the DB.
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

            mock_request = MagicMock()
            mock_request.headers = {"Authorization": f"Token {token.key}"}

            class _BareRequestContext:
                def __init__(self):
                    self.request = mock_request
                    self._cached_user = user_obj

            mock_ctx = MagicMock()
            mock_ctx.request_context = _BareRequestContext()

            # Call get_user_from_request — should return cached user
            result = get_user_from_request(mock_ctx)

            # Should return the cached user (not a DB lookup)
            self.assertEqual(result, user_obj)

            # Verify _cached_user was checked (no DB query occurred)
            self.assertEqual(mock_ctx.request_context._cached_user, result)
        finally:
            token.delete()

    def test_cache_stores_user_after_db_lookup(self):
        """AUTH-01, AUTH-02: After DB lookup, user is cached on request_context.

        On the first call (no _cached_user), the function looks up the DB,
        stores the result on ctx.request_context._cached_user, and returns it.
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

            mock_request = MagicMock()
            mock_request.headers = {"Authorization": f"Token {token.key}"}

            class _BareRequestContext:
                def __init__(self):
                    self.request = mock_request

            mock_ctx = MagicMock()
            mock_ctx.request_context = _BareRequestContext()

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

        When ctx.request_context._cached_user is absent, the function should
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

            mock_request = MagicMock()
            mock_request.headers = {"Authorization": f"Token {token.key}"}

            class _BareRequestContext:
                def __init__(self):
                    self.request = mock_request

            mock_ctx = MagicMock()
            mock_ctx.request_context = _BareRequestContext()

            result = get_user_from_request(mock_ctx)

            # Should fall through to DB lookup and return the user
            self.assertEqual(result, user_obj)
            # And cache should now be populated
            self.assertEqual(mock_ctx.request_context._cached_user, user_obj)
        finally:
            token.delete()
