"""Tests for the auth layer (AUTH-01, AUTH-02, AUTH-03, TEST-06)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase


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
        mock_ctx = MagicMock()
        mock_ctx.request_context.request = mock_request
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
        """AUTH-02: Token without nbapikey_ prefix → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Token abcdefghijklmnop")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_valid_nbapikey_token_returns_user(self):
        """AUTH-01: Valid nbapikey_ token → correct Nautobot User returned."""
        from django.contrib.auth import get_user_model
        from nautobot.users.models import Token

        User = get_user_model()
        # Ensure we have at least one superuser to test with
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",
            )
        user_obj = User.objects.filter(is_superuser=True).first()

        token = Token.objects.create(user=user_obj, key="nbapikey_testauthtoken123")

        try:
            ctx = self._make_mock_ctx(
                authorization=f"Token nbapikey_{token.key}",
            )
            result = get_user_from_request(ctx)
            self.assertEqual(result, user_obj)
        finally:
            token.delete()

    def test_valid_token_wrong_key_returns_anonymous(self):
        """AUTH-02: Valid format but unknown key → AnonymousUser + DEBUG log."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(
            authorization="Token nbapikey_nonexistentkey000000",
        )
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
