"""Tests for the GraphQL query MCP tool (GQL-14, GQL-15, GQL-16, GQL-17)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from asgiref.sync import AsyncToSync
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase

from nautobot_app_mcp_server.mcp.tools import graphql_tool
from nautobot_app_mcp_server.mcp.tests.test_auth import _make_mock_ctx


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


class GraphQLQueryHandlerTestCase(TestCase):
    """Test the graphql_query MCP tool handler (GQL-14, GQL-15, GQL-16, GQL-17)."""

    def _get_or_create_superuser(self):
        """Return an existing superuser or create one for test fixtures."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",  # noqa: S106
            )
        return user

    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request"
    )
    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query"
    )
    def test_valid_query_returns_structured_data(self, mock_sync, mock_get_user):
        """GQL-15: Valid GraphQL query returns dict with 'data' and 'errors' keys.

        Both _sync_graphql_query and get_user_from_request are patched at the
        graphql_tool module level (where the names are bound, not where they are
        defined). The mock returns a valid ExecutionResult.formatted structure.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_result = {"data": {"devices": [{"name": "router-01"}]}, "errors": None}
        mock_sync.return_value = mock_result
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(
                ctx, query="{ devices { name } }"
            )

            self.assertIn("data", result)
            self.assertIn("errors", result)
            self.assertEqual(result["data"]["devices"][0]["name"], "router-01")
            self.assertIsNone(result["errors"])
        finally:
            token.delete()

    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request"
    )
    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query"
    )
    def test_invalid_query_returns_errors_dict(self, mock_sync, mock_get_user):
        """GQL-16: Invalid GraphQL query returns dict with 'errors' key and no data.

        GraphQL validation errors are returned as structured errors in the dict,
        not as Python exceptions. The handler passes them through unchanged.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_result = {
            "data": None,
            "errors": [
                {"message": "Cannot query field 'nonexistentField' on type 'Query'."}
            ],
        }
        mock_sync.return_value = mock_result
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(
                ctx, query="{ nonexistentField }"
            )

            self.assertIn("errors", result)
            self.assertIsNone(result["data"])
            self.assertIn("nonexistentField", result["errors"][0]["message"])
        finally:
            token.delete()

    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request"
    )
    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query"
    )
    def test_variables_injection_works(self, mock_sync, mock_get_user):
        """GQL-17: variables dict is forwarded to _sync_graphql_query as the `variables` kwarg.

        The handler calls sync_to_async(_sync_graphql_query)(query=..., variables=..., user=...).
        Verify that variables {"id": "1234-uuid"} is received by the mock via call_args.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_sync.return_value = {"data": {"device": {"name": "test"}}, "errors": None}
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(
                ctx,
                query="query GetDevice($id: ID!) { device(id: $id) { name } }",
                variables={"id": "1234-uuid"},
            )

            self.assertEqual(result["data"]["device"]["name"], "test")
            # Verify variables was forwarded as a kwarg to _sync_graphql_query
            mock_sync.assert_called_once()
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs["variables"], {"id": "1234-uuid"})
            self.assertEqual(kwargs["user"], user)
            self.assertIn("query", kwargs)
        finally:
            token.delete()

    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request"
    )
    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query"
    )
    def test_auth_propagates_to_sync_helper(self, mock_sync, mock_get_user):
        """GQL-14: Auth token resolves to user and user is passed to _sync_graphql_query.

        When a valid token is provided, get_user_from_request returns the User
        object, which is then passed to _sync_graphql_query as the `user` kwarg.
        Uses call_args to verify the exact kwarg passed.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_sync.return_value = {"data": {}, "errors": None}
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(
                ctx,
                query="{ devices { name } }",
                variables=None,
            )

            # Verify user was passed to _sync_graphql_query
            mock_sync.assert_called_once()
            _, kwargs = mock_sync.call_args
            self.assertEqual(kwargs["user"], user)
            # Verify result returned without error
            self.assertIn("data", result)
        finally:
            token.delete()

    @patch(
        "nautobot.core.graphql.execute_query"
    )
    def test_anonymous_user_triggers_auth_error(self, mock_execute):
        """GQL-07: execute_query ValueError is caught and returns structured error dict.

        When user is None (AnonymousUser), execute_query raises ValueError.
        The handler's try/except catches this and returns
        {"data": None, "errors": [{"message": "Authentication required"}]}.

        Patches nautobot.core.graphql.execute_query because _sync_graphql_query
        uses a lazy import (imported inside the function body), so the name
        is not in graphql_tool's module namespace at decoration time.
        """
        mock_execute.side_effect = ValueError("Either request or username should be provided")

        result = graphql_tool._sync_graphql_query(
            query="{ devices { name } }",
            variables=None,
            user=AnonymousUser(),
        )

        self.assertIn("errors", result)
        self.assertIsNone(result["data"])
        self.assertEqual(result["errors"][0]["message"], "Authentication required")
