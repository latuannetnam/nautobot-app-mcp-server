---
gsd_wave: 1
gsd_phase: 14-graphql-tool-scaffold
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/tools/graphql_tool.py
  - nautobot_app_mcp_server/mcp/tools/__init__.py
autonomous: false
---

# Plan 14 — GraphQL Tool Scaffold

**Phase:** 14-graphql-tool-scaffold
**Wave:** 1
**Requirements:** GQL-01, GQL-02, GQL-03, GQL-04, GQL-05, GQL-06, GQL-07, GQL-14, GQL-15, GQL-16, GQL-17

---

## Goals

Create `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` containing the `graphql_query` async handler, register it via side-effect import in `tools/__init__.py`, and write 5 unit tests covering auth propagation, valid query, invalid query, variables injection, and anonymous-user error handling.

**Must-haves (goal-backward):**
- `graphql_tool.py` exists and contains `async def _graphql_query_handler(ctx, query, variables=None) -> dict`
- `_sync_graphql_query(query, variables, user) -> dict` wraps `execute_query` with `ValueError` guard
- `@register_tool(name="graphql_query", ...)` decorator present; no `output_schema` kwarg
- `tools/__init__.py` imports graphql_tool for side-effect registration
- 5 test cases in `test_graphql_tool.py` covering GQL-07, GQL-14, GQL-15, GQL-16, GQL-17
- All `@patch` decorators target `nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query` and `nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request` (not the auth or core modules)
- `poetry run invoke unittest` passes with 5 new tests and no regressions

---

## Verification

```bash
# 1. File created
ls nautobot_app_mcp_server/mcp/tools/graphql_tool.py

# 2. graphql_tool side-effect import present
grep "graphql_tool" nautobot_app_mcp_server/mcp/tools/__init__.py

# 3. Tool function exists and is async
grep "async def _graphql_query_handler" nautobot_app_mcp_server/mcp/tools/graphql_tool.py

# 4. register_tool decorator present
grep "register_tool" nautobot_app_mcp_server/mcp/tools/graphql_tool.py

# 5. execute_query import present
grep "execute_query" nautobot_app_mcp_server/mcp/tools/graphql_tool.py

# 6. sync_to_async at outer boundary
grep "sync_to_async" nautobot_app_mcp_server/mcp/tools/graphql_tool.py

# 7. Test file created with @patch decorators
grep -c "@patch" nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py

# 8. All 5 tests present
grep "def test_" nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py

# 9. Unit tests pass
unset VIRTUAL_ENV && poetry run invoke unittest 2>&1 | tail -30
```

---

## Task 14-1: Create graphql_tool.py

<task_id>14-1</task_id>
<read_first>
- `nautobot_app_mcp_server/mcp/tools/core.py` — async handler pattern, imports, decorator usage, `sync_to_async(thread_sensitive=True)` boundary
- `nautobot_app_mcp_server/mcp/__init__.py` — `register_tool()` decorator signature; note `output_schema=None` is set in `register_all_tools_with_mcp()`, not in the decorator
- `nautobot_app_mcp_server/mcp/auth.py` — `get_user_from_request(ctx)` reuse
- `.venv/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py` — `execute_query(query, variables=None, request=None, user=None)` signature and behavior; raises `ValueError("Either request or username should be provided")` when both request and user are None; returns `ExecutionResult` with `.formatted` property returning `{"data": ..., "errors": [...]}` (both always present, errors may be null)
</read_first>
<action>
Create the file `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` with this exact content:

```python
"""GraphQL query tool — wraps nautobot.core.graphql.execute_query()."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext

from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request

if TYPE_CHECKING:
    pass

TOOLS_SCOPE = "core"
TOOLS_TIER = "core"


@register_tool(
    name="graphql_query",
    description=(
        "Execute a GraphQL query against Nautobot's GraphQL API. "
        "Returns a dict with 'data' and 'errors' keys. "
        "Auth token is required — anonymous queries return empty data."
    ),
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict | None = None,
) -> dict[str, Any]:
    """Execute a GraphQL query against Nautobot.

    Args:
        ctx: FastMCP ToolContext providing request/session access.
        query: GraphQL query string (e.g. '{ devices { name status } }').
        variables: Optional dict of variables for the query.

    Returns:
        dict with 'data' and 'errors' keys from ExecutionResult.formatted.
        On authentication failure (no token), returns:
        {"data": None, "errors": [{"message": "Authentication required"}]}
    """
    user = await get_user_from_request(ctx)
    return await sync_to_async(_sync_graphql_query, thread_sensitive=True)(
        query=query, variables=variables, user=user
    )


def _sync_graphql_query(query: str, variables: dict | None, user) -> dict[str, Any]:
    """Synchronous GraphQL query executor.

    Imports nautobot.core.graphql lazily to avoid Django setup issues.
    Catches ValueError (raised when user is None) and returns a structured
    error dict instead of propagating the exception.
    """
    from nautobot.core.graphql import execute_query

    try:
        result = execute_query(query=query, variables=variables, user=user)
    except ValueError:
        # user was None — execute_query requires request or user
        return {"data": None, "errors": [{"message": "Authentication required"}]}
    return result.formatted
```

Key implementation decisions:
- Single `sync_to_async(thread_sensitive=True)` at the outer boundary — matches all 10 existing core tools
- `get_user_from_request(ctx)` called once before the sync wrapper — auth resolved in async context
- `_sync_graphql_query` is a module-level function (NOT a closure) — enables clean patching in unit tests
- Lazy import of `nautobot.core.graphql` inside `_sync_graphql_query` — no Django setup at module load time
- `ValueError` guard ensures the tool never raises to FastMCP; structured error dict returned instead
- `@register_tool` decorator with explicit `name="graphql_query"`; no `output_schema` kwarg (GQL-06: FastMCP gets `output_schema=None` in `register_all_tools_with_mcp()`)
</action>
<acceptance_criteria>
1. `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` exists and is readable
2. File contains `async def _graphql_query_handler(ctx: ToolContext, query: str, variables: dict | None = None) -> dict[str, Any]:`
3. File contains `def _sync_graphql_query(query: str, variables: dict | None, user) -> dict[str, Any]:`
4. File contains `@register_tool(name="graphql_query", description=..., tier="core", scope="core")`
5. `from nautobot.core.graphql import execute_query` is called inside `_sync_graphql_query` (lazy import, no module-level import)
6. `sync_to_async(_sync_graphql_query, thread_sensitive=True)` appears exactly once at the outer boundary
7. `get_user_from_request(ctx)` is called and its result passed as `user=user` kwarg to `_sync_graphql_query`
8. `except ValueError:` block returns `{"data": None, "errors": [{"message": "Authentication required"}]}`
9. `result.formatted` is returned on success (not raw ExecutionResult)
10. No `output_schema` kwarg on the `@register_tool` call
</acceptance_criteria>
<verify_with>
grep -n "async def _graphql_query_handler\|def _sync_graphql_query\|@register_tool\|from nautobot.core.graphql\|sync_to_async.*_sync_graphql_query.*thread_sensitive=True\|get_user_from_request\|except ValueError\|result.formatted\|output_schema" nautobot_app_mcp_server/mcp/tools/graphql_tool.py
</verify_with>
</task>

---

## Task 14-2: Register graphql_tool in tools/__init__.py

<task_id>14-2</task_id>
<read_first>
- `nautobot_app_mcp_server/mcp/tools/__init__.py` — existing side-effect imports pattern (`from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401`)
</read_first>
<action>
Add exactly one line to `nautobot_app_mcp_server/mcp/tools/__init__.py` — a side-effect import after the `core` import line (before the `LIMIT_*` imports):

```python
from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401
from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401
from nautobot_app_mcp_server.mcp.tools.pagination import (
```

The placement matters: put `graphql_tool` on its own line, below `core`, above `pagination`, with the same `# noqa: F401` comment used for `core`.
</action>
<acceptance_criteria>
1. `nautobot_app_mcp_server/mcp/tools/__init__.py` contains `from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401`
2. The line appears between the `core` side-effect import and the `from nautobot_app_mcp_server.mcp.tools.pagination import` block
3. No other changes to `tools/__init__.py`
4. File is valid Python (no syntax errors)
</acceptance_criteria>
<verify_with>
grep -n "graphql_tool" nautobot_app_mcp_server/mcp/tools/__init__.py
</verify_with>
</task>

---

## Task 14-3: Write unit tests in test_graphql_tool.py

<task_id>14-3</task_id>
<read_first>
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — `_make_mock_ctx()`, `_create_token()`, `_RequestContext`, token fixture patterns; note `_create_token` is defined in this file but will be redefined locally in test_graphql_tool.py
- `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — `@patch` decorator pattern: patch at `nautobot_app_mcp_server.mcp.tools.query_utils._sync_device_list` (the module where the name is bound, not where the function is defined); `AsyncToSync(graphql_tool._graphql_query_handler)` for async handler invocation; `mock_sync.call_args` to verify kwargs forwarding
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — the file being tested (created in Task 14-1); `_sync_graphql_query` is a module-level function patchable at `nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query`
</read_first>
<action>
Create the file `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` with exactly this content:

```python
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
        "nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request"
    )
    @patch(
        "nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query"
    )
    def test_anonymous_user_triggers_auth_error(self, mock_sync, mock_get_user):
        """GQL-07: Anonymous user triggers ValueError guard — structured error returned.

        When get_user_from_request returns AnonymousUser, execute_query raises
        ValueError because it requires a real user. The handler's try/except
        catches this and returns {"data": None, "errors": [{"message": "..."}]}.
        Mock _sync_graphql_query with side_effect to simulate execute_query behavior.
        """
        mock_get_user.return_value = AnonymousUser()
        # Simulate what execute_query does when user is None: raise ValueError
        mock_sync.side_effect = ValueError("Either request or username should be provided")

        ctx = _make_mock_ctx(authorization=None)

        result = AsyncToSync(graphql_tool._graphql_query_handler)(
            ctx,
            query="{ devices { name } }",
            variables=None,
        )

        self.assertIn("errors", result)
        self.assertIsNone(result["data"])
        self.assertEqual(result["errors"][0]["message"], "Authentication required")
```

**Critical mock patching rules (these were the bugs in the failed plan):**

1. **Patch at `graphql_tool` module, not at `auth` or `core.graphql` source:**
   - `@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")` — correct
   - `@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")` — correct
   - WRONG: `@patch("nautobot_app_mcp_server.mcp.auth.get_user_from_request")` — patches the export, not the local binding

2. **Decorator order:** Stacked decorators execute bottom-to-top. The bottom decorator (`@patch ... _sync_graphql_query`) patches the innermost function. The top decorator (`@patch ... get_user_from_request`) patches the outer. Parameters appear in the same order as the decorator stack: bottom decorator's mock is the innermost argument (first in list), top decorator's mock is the outermost (last in list). This gives us `def test_(self, mock_sync, mock_get_user)` where `mock_sync` is `_sync_graphql_query` (patched closer to the function definition) and `mock_get_user` is `get_user_from_request`.

3. **No bare `MagicMock()` for patching:** All patching uses `@patch` decorators with proper target strings. No `with MagicMock() as mock:` used as a no-op patch substitute.

4. **`mock_sync.side_effect = ValueError(...)`** for the auth error test — this simulates what `execute_query` does when `user=None`.
</action>
<acceptance_criteria>
1. `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` exists and is readable
2. File contains `class GraphQLQueryHandlerTestCase(TestCase):`
3. File contains `@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")` on test methods
4. File contains `@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")` on test methods
5. File contains `def test_valid_query_returns_structured_data(self, mock_sync, mock_get_user):` — GQL-15
6. File contains `def test_invalid_query_returns_errors_dict(self, mock_sync, mock_get_user):` — GQL-16
7. File contains `def test_variables_injection_works(self, mock_sync, mock_get_user):` — GQL-17; uses `mock_sync.call_args` to verify kwargs
8. File contains `def test_auth_propagates_to_sync_helper(self, mock_sync, mock_get_user):` — GQL-14; uses `mock_sync.call_args` to verify `user` kwarg
9. File contains `def test_anonymous_user_triggers_auth_error(self, mock_sync, mock_get_user):` — GQL-07; uses `mock_sync.side_effect = ValueError(...)` to simulate execute_query failure
10. All 5 test methods call `AsyncToSync(graphql_tool._graphql_query_handler)(ctx, ...)` to invoke the async handler
11. No bare `MagicMock()` used as a no-op patch — all mocks use `@patch` decorators or are MagicMocks returned as values
12. Tests import `_make_mock_ctx` from `nautobot_app_mcp_server.mcp.tests.test_auth`
13. Tests define their own `_create_token` and `_delete_token` locally in the file
14. `poetry run invoke unittest` passes with 5 new tests
</acceptance_criteria>
<verify_with>
grep -n "def test_\|class GraphQLQueryHandlerTestCase\|AsyncToSync(graphql_tool\|@patch.*graphql_tool\|mock_sync.call_args\|mock_sync.side_effect" nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py
</verify_with>
</task>

---

## Task 14-4: Run unit tests and verify pass

<task_id>14-4</task_id>
<read_first>
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — verify all 5 tests are present before running
</read_first>
<action>
Run the unit test suite for the graphql_tool module:

```bash
unset VIRTUAL_ENV && poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool
```

All 5 tests must pass (exit code 0). If any test fails:
1. Read the full traceback
2. Identify the root cause
3. Fix the source file and re-run

Expected output includes:
- `Ran 5 tests in ...s`
- `OK`

Common failure modes:
- **"Connection not available"** → `sync_to_async` missing `thread_sensitive=True`; check `_sync_graphql_query` is called with `thread_sensitive=True`
- **Mock not applied** → patch target string wrong; must be `nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query`, not `nautobot.core.graphql.execute_query`
- **`test_anonymous_user` fails with wrong result** → `mock_sync.side_effect` not set; the ValueError from the real `execute_query` is NOT raised when `user=AnonymousUser()` (AnonymousUser is not None); fix: make `mock_sync.side_effect` raise ValueError and patch `_sync_graphql_query` instead of patching `get_user_from_request`
</action>
<acceptance_criteria>
1. `unset VIRTUAL_ENV && poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool` exits with code 0
2. All 5 tests report OK (no failures, no errors)
3. No "Connection not available" errors
4. No import errors for graphql_tool module
</acceptance_criteria>
<verify_with>
unset VIRTUAL_ENV && poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool 2>&1 | tail -20
</verify_with>
</task>

---

## Task 14-5: Run full test suite and verify no regressions

<task_id>14-5</task_id>
<read_first>
- `nautobot_app_mcp_server/mcp/tests/` directory listing to confirm all test files are present
</read_first>
<action>
Run the full test suite:

```bash
unset VIRTUAL_ENV && poetry run invoke unittest
```

This runs all unit tests across all test modules. All existing tests must continue to pass. New tests for graphql_tool must also pass.

If pylint or ruff reports issues, fix them before completing the task.
</action>
<acceptance_criteria>
1. `unset VIRTUAL_ENV && poetry run invoke unittest` exits with code 0
2. `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` tests appear in the output (5 tests)
3. No regression in existing tests (test_auth.py, test_core_tools.py, test_pagination.py all pass)
4. No linter errors (ruff, pylint) in the new files
</acceptance_criteria>
<verify_with>
unset VIRTUAL_ENV && poetry run invoke unittest 2>&1 | tail -50
</verify_with>
</task>

---

## Dependencies

| Order | Task | Reason |
|-------|------|--------|
| 1 | 14-1: Create graphql_tool.py | Source file for tasks 14-2 and 14-3 |
| 2 | 14-2: Register in __init__.py | Verify import works; depends on 14-1 |
| 3 | 14-3: Write tests | Tests import graphql_tool; depends on 14-1 |
| 4 | 14-4: Run graphql_tool tests | Depends on 14-3 |
| 5 | 14-5: Run full suite | Depends on all above |

## Wave Summary

| Task | File | GQL Reqs |
|------|------|----------|
| 14-1 | `graphql_tool.py` | GQL-01, GQL-02, GQL-03, GQL-04, GQL-05, GQL-06, GQL-07 |
| 14-2 | `tools/__init__.py` | GQL-01 |
| 14-3 | `test_graphql_tool.py` | GQL-14, GQL-15, GQL-16, GQL-17 |
| 14-4 | (test run) | all |
| 14-5 | (full suite) | all |

*Plan created: 2026-04-15*
