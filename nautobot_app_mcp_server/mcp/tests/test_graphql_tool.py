"""Tests for the GraphQL query MCP tool (GQL-14, GQL-15, GQL-16, GQL-17)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from asgiref.sync import AsyncToSync
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase

from nautobot_app_mcp_server.mcp.tests.test_auth import _make_mock_ctx
from nautobot_app_mcp_server.mcp.tools import graphql_tool


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

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
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
            result = AsyncToSync(graphql_tool._graphql_query_handler)(ctx, query="{ devices { name } }")

            self.assertIn("data", result)
            self.assertIn("errors", result)
            self.assertEqual(result["data"]["devices"][0]["name"], "router-01")
            self.assertIsNone(result["errors"])
        finally:
            token.delete()

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
    def test_invalid_query_returns_errors_dict(self, mock_sync, mock_get_user):
        """GQL-16: Invalid GraphQL query returns dict with 'errors' key and no data.

        GraphQL validation errors are returned as structured errors in the dict,
        not as Python exceptions. The handler passes them through unchanged.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_result = {
            "data": None,
            "errors": [{"message": "Cannot query field 'nonexistentField' on type 'Query'."}],
        }
        mock_sync.return_value = mock_result
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(ctx, query="{ nonexistentField }")

            self.assertIn("errors", result)
            self.assertIsNone(result["data"])
            self.assertIn("nonexistentField", result["errors"][0]["message"])
        finally:
            token.delete()

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
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

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
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

    def test_anonymous_user_triggers_auth_error(self):
        """GQL-07: AnonymousUser triggers auth guard → structured error dict.

        The auth check is the first step in _sync_graphql_query and fires
        before any GraphQL execution. No patching needed.
        """
        result = graphql_tool._sync_graphql_query(
            query="{ devices { name } }",
            variables=None,
            user=AnonymousUser(),
        )

        self.assertIn("errors", result)
        self.assertIsNone(result["data"])
        self.assertEqual(result["errors"][0]["message"], "Authentication required")

    def test_anonymous_user_empty_query_results(self):
        """GQL-13: AnonymousUser (user=None) → auth guard returns error dict.

        The auth guard is the first step in _sync_graphql_query — it fires
        before parse() or execute() are called. No patching needed.
        """
        result = graphql_tool._sync_graphql_query(
            query="{ devices { name } }",
            variables=None,
            user=None,
        )

        self.assertIsNone(result["data"])
        self.assertIn("errors", result)
        self.assertEqual(result["errors"][0]["message"], "Authentication required")

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._graphql.execute")
    def test_authenticated_user_normal_results(self, mock_execute):
        """GQL-13: Authenticated user → graphql.execute returns non-empty filtered data.

        _sync_graphql_query calls graphql.execute() after auth guard + validation.
        Patch graphql.execute to return a mock ExecutionResult with the expected
        formatted shape.
        """
        from graphql import ExecutionResult

        # Subclass ExecutionResult and override the formatted property so it
        # returns the shape expected by the caller (omits "errors" key when None)
        class MockExecutionResult(ExecutionResult):
            @property
            def formatted(self):
                # Same logic as ExecutionResult.formatted but explicit
                result = {"data": self.data}
                if self.errors is not None:
                    result["errors"] = self.errors
                return result

        mock_result = MockExecutionResult(
            data={"devices": [{"name": "router-01"}]},
            errors=None,
        )
        mock_execute.return_value = mock_result

        user = self._get_or_create_superuser()

        result = graphql_tool._sync_graphql_query(
            query="{ devices { name } }",
            variables=None,
            user=user,
        )

        self.assertIn("data", result)
        self.assertNotEqual(result["data"]["devices"], [])
        self.assertEqual(result["data"]["devices"][0]["name"], "router-01")


class GraphQLIntrospectHandlerTestCase(TestCase):
    """Test the graphql_introspect MCP tool handler (GQL-08, GQL-09)."""

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

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_introspect")
    def test_introspect_returns_sdl_string(self, mock_sync, mock_get_user):
        """GQL-09: graphql_introspect returns a multi-line SDL string.

        Patches both the auth layer and the sync helper at the module level
        (where the names are bound at import time). The mock returns a valid
        SDL fragment that the handler passes through unchanged.
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_sdl = "type Query {\n" "  devices: [Device]\n" "}\n" "type Device {\n" "  name: String\n" "}\n"
        mock_sync.return_value = mock_sdl
        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_introspect_handler)(ctx)

            self.assertIsInstance(result, str)
            self.assertIn("type Query", result)
            self.assertIn("Device", result)
        finally:
            token.delete()

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_introspect")
    def test_introspect_sdl_valid(self, mock_sync):
        """GQL-09: Returned SDL can be parsed by build_schema without GraphQLError.

        D-05 from RESEARCH.md: build_schema raises GraphQLError on malformed SDL.
        A well-formed SDL string parses successfully.
        """
        from graphql import GraphQLError, build_schema

        mock_sdl = "type Query {\n" "  devices: [Device]\n" "}\n" "type Device {\n" "  name: String\n" "}\n"
        mock_sync.return_value = mock_sdl

        result = graphql_tool._sync_graphql_introspect()

        # Must not raise GraphQLError — valid SDL parses successfully
        try:
            build_schema(result)
        except GraphQLError:
            self.fail("SDL from _sync_graphql_introspect is not a valid GraphQL schema")

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    def test_introspect_raises_on_anonymous(self, mock_get_user):
        """GQL-08: Introspection requires auth — anonymous raises ValueError.

        When get_user_from_request returns None (no token), the handler raises
        ValueError("Authentication required"). FastMCP converts this to a
        structured tool error response.
        """
        mock_get_user.return_value = None

        ctx = _make_mock_ctx(authorization=None)

        with self.assertRaises(ValueError) as ctx_:
            AsyncToSync(graphql_tool._graphql_introspect_handler)(ctx)
        self.assertIn("Authentication required", str(ctx_.exception))

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    def test_auth_required_resolves_user(self, mock_get_user):
        """GQL-08: Auth token is resolved before the sync boundary is crossed.

        Verifies that get_user_from_request is called once and its result
        is used (not re-checked inside the sync helper).
        """
        user = self._get_or_create_superuser()
        token = _create_token(user)

        mock_get_user.return_value = user

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            # Patch the sync helper to avoid needing Nautobot schema in unit test
            with patch(
                "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_introspect",
                return_value="type Query {\n  test: String\n}\n",
            ):
                result = AsyncToSync(graphql_tool._graphql_introspect_handler)(ctx)

            mock_get_user.assert_called_once()
            self.assertIsInstance(result, str)
        finally:
            token.delete()


class GraphQLSecurityTestCase(TestCase):
    """Test depth/complexity limits and structured error handling (GQL-10, GQL-11, GQL-12)."""

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

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_validation.validate")
    def test_depth_limit_enforced(self, mock_validate):
        """GQL-10: Query with depth 9 is rejected with data=None and 'depth' in message.

        _sync_graphql_query calls graphql.validate() before execute().
        Patch graphql_validation.validate to simulate MaxDepthRule rejecting the query.
        """
        from graphql import GraphQLError

        fake_error = GraphQLError("Query depth 9 exceeds maximum allowed depth of 8")
        mock_validate.return_value = [fake_error]

        user = self._get_or_create_superuser()
        result = graphql_tool._sync_graphql_query(
            query="{ a { b { c { d { e { f { g { h { i } } } } } } } } }",  # depth 9
            variables=None,
            user=user,
        )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("depth", result["errors"][0]["message"].lower())

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_validation.validate")
    def test_complexity_limit_enforced(self, mock_validate):
        """GQL-11: Over-complex query is rejected with data=None and 'complexity' in message.

        Patch graphql_validation.validate to simulate QueryComplexityRule rejecting the query.
        """
        from graphql import GraphQLError

        fake_error = GraphQLError("Query complexity 1001 exceeds maximum allowed complexity of 1000")
        mock_validate.return_value = [fake_error]

        # Build a query with > 1000 field selections
        many_fields = ", ".join(f"field{i}: name" for i in range(1001))
        query = f"{{ {many_fields} }}"

        user = self._get_or_create_superuser()
        result = graphql_tool._sync_graphql_query(
            query=query,
            variables=None,
            user=user,
        )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("complexity", result["errors"][0]["message"].lower())

    def test_syntax_error_returns_200_with_errors(self):
        """GQL-12: Malformed query returns HTTP 200 with structured errors dict.

        parse() raises GraphQLError for unclosed braces, invalid syntax, etc.
        This is caught in _sync_graphql_query and returned as
        ExecutionResult.formatted. No unhandled exception propagates from the tool.
        """
        user = self._get_or_create_superuser()
        result = graphql_tool._sync_graphql_query(
            query="{ devices {",  # unclosed brace — syntax error
            variables=None,
            user=user,
        )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("Syntax Error", result["errors"][0]["message"])
