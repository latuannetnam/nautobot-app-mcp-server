# Phase 14 Research — GraphQL Tool Scaffold

**Phase:** 14-graphql-tool-scaffold
**Status:** Research complete
**Date:** 2026-04-15

---

## 1. What I investigated

- `nautobot.core.graphql.execute_query()` — function signature, auth semantics, return type
- `nautobot_app_mcp_server/mcp/auth.py` — `get_user_from_request()` reuse pattern
- `nautobot_app_mcp_server/mcp/tools/core.py` — all 10 existing async tool handlers
- `nautobot_app_mcp_server/mcp/tools/__init__.py` — side-effect import registration pattern
- `nautobot_app_mcp_server/mcp/__init__.py` — `register_tool()` decorator, `register_all_tools_with_mcp()`
- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — test patterns, mock setup, `_create_token()`, `_make_mock_ctx()`
- `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — test structure for tool handlers

---

## 2. What I found

### 2.1 `execute_query` semantics (GQL-03, GQL-04, GQL-05)

File: `.venv/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py`

```python
def execute_query(query, variables=None, request=None, user=None):
    if not request and not user:
        raise ValueError("Either request or username should be provided")
    if not request:
        request = RequestFactory().post("/graphql/")
        request.user = user
    schema = graphene_settings.SCHEMA.graphql_schema
    document = parse(query)
    if variables:
        return execute(schema=schema, document=document,
                       context_value=request, variable_values=variables)
    else:
        return execute(schema=schema, document=document, context_value=request)
```

Key behaviors:
- `ValueError` is raised when both `request` and `user` are `None` — this is the "no-throw" boundary requirement (D-07)
- The returned value is an `ExecutionResult` from `graphql-core`; its `.formatted` property returns `{"data": ..., "errors": [...]}`
- Both `data` and `errors` keys are always present in `.formatted`; `errors` may be `None`
- Nautobot's GraphQL schema is pre-built via `graphene_settings.SCHEMA.graphql_schema` (uses `OptimizedNautobotObjectType` wrappers)
- Permission enforcement via `.restrict(user, "view")` happens inside resolvers — `user` passed via `context_value`

### 2.2 Auth propagation (GQL-07, GQL-02)

- `get_user_from_request(ctx)` is reused directly — no changes to `auth.py`
- User is resolved once, before the `sync_to_async` call
- Passed as the named `user` keyword argument to `execute_query(query, variables, user=user)` — no manual `RequestFactory` construction needed
- `execute_query` internally calls `RequestFactory().post("/graphql/")` and sets `request.user = user` — this is fine; the Django `Request` object is only needed for the GraphQL resolver context

### 2.3 Async/sync boundary (GQL-02)

- Pattern identical to all 10 existing tools: `async def handler` + single `sync_to_async(thread_sensitive=True)` at outer boundary
- The entire `execute_query()` call is wrapped — no per-resolver guards
- Auth resolution is `await` (async), then the sync block is `await sync_to_async(...)` (async wrapper of sync function)
- This matches P1 from the research pitfall catalog: single wrapper at tool boundary prevents `SynchronousOnlyOperation`

### 2.4 Tool registration pattern

- `graphql_tool.py` uses `@register_tool(name="graphql_query", description=..., tier="core", scope="core")` — same as all existing core tools
- `mcp/tools/__init__.py` gets a side-effect import: `from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401`
- `output_schema=None` on the decorator — same as all existing tools
- `register_all_tools_with_mcp()` already wires every registered tool — no changes needed

### 2.5 Error handling (D-07, GQL-12)

- `execute_query` raises `ValueError` only when both `user` and `request` are `None` — this is the only case where the tool boundary needs to catch and return a structured error
- All GraphQL runtime errors (syntax, validation, field resolution) are returned in the `errors` array via `ExecutionResult.formatted` — no HTTP 500s, no exception to catch
- The tool function itself must not raise — `ExecutionResult.formatted` is always returned; on `ValueError` the tool returns `{"data": None, "errors": [{"message": "Authentication required"}]}`

### 2.6 Unit test strategy (GQL-14, GQL-15, GQL-16, GQL-17)

File: `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py`

Test patterns to follow from `test_auth.py`:
- `AsyncToSync` to call async handlers from sync test methods
- `_make_mock_ctx()` and `_create_token()` for auth fixture setup
- Same `TestCase` base class
- Mock `execute_query` to isolate unit tests from DB/schema

Four test cases mapping to four requirements:
1. **GQL-14** — auth propagates: verify `execute_query` is called with the correct `user` argument (not `None`)
2. **GQL-15** — valid query returns structured `{data, errors}` dict: mock `execute_query` returning an `ExecutionResult` with `.formatted = {"data": {...}, "errors": None}`
3. **GQL-16** — invalid query returns errors dict: mock `execute_query` returning an `ExecutionResult` with syntax errors in `.formatted`
4. **GQL-17** — variables injection works: mock `execute_query` called with `variables={"id": "..."}` kwarg

Mock strategy: patch `nautobot.core.graphql.execute_query` at the module level inside each test, rather than patching at the call site. This isolates the tool function from Nautobot's GraphQL infrastructure entirely, keeping tests fast and deterministic.

---

## 3. Implementation plan

### Files to create

| File | Purpose |
|---|---|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | `graphql_query` async handler — 60–80 lines |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` | 4 unit tests — 120–150 lines |

### Files to modify

| File | Change |
|---|---|
| `nautobot_app_mcp_server/mcp/tools/__init__.py` | Add `graphql_tool` side-effect import |

### No changes needed

- `auth.py` — reused as-is (no modification)
- `registry.py`, `commands.py`, `session_tools.py`, `core.py` — untouched
- `__init__.py` (top-level plugin) — untouched
- `pyproject.toml` — no new dependencies

### Implementation sketch

```python
# nautobot_app_mcp_server/mcp/tools/graphql_tool.py
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
    description="Execute a GraphQL query against Nautobot's GraphQL API.",
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict | None = None,
) -> dict[str, Any]:
    user = await get_user_from_request(ctx)
    return await sync_to_async(_sync_graphql_query, thread_sensitive=True)(
        query=query, variables=variables, user=user
    )


def _sync_graphql_query(query: str, variables: dict | None, user) -> dict[str, Any]:
    from nautobot.core.graphql import execute_query

    try:
        result = execute_query(query=query, variables=variables, user=user)
    except ValueError:
        # user was None — auth failure at the boundary
        return {"data": None, "errors": [{"message": "Authentication required"}]}
    return result.formatted
```

### Test sketch

```python
# nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py
from __future__ import annotations

from unittest.mock import MagicMock, patch

from asgiref.sync import AsyncToSync
from django.test import TestCase

from nautobot_app_mcp_server.mcp.tools import graphql_tool


class GraphQLQueryTestCase(TestCase):
    """Test the graphql_query MCP tool handler."""

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.execute_query")
    def test_valid_query_returns_structured_data(self, mock_execute):
        mock_result = MagicMock()
        mock_result.formatted = {"data": {"device": {"name": "router-01"}}, "errors": None}
        mock_execute.return_value = mock_result

        from nautobot_app_mcp_server.mcp.auth import get_user_from_request
        from nautobot_app_mcp_server.mcp.tests.test_auth import _make_mock_ctx, _create_token
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.create_superuser("testadmin", "admin@test", "testpass")
        token = _create_token(user)

        try:
            ctx = _make_mock_ctx(
                authorization=f"Token {token.key}",
                token_key_to_user={token.key: user},
            )
            result = AsyncToSync(graphql_tool._graphql_query_handler)(ctx, query="{ devices { name } }")
            self.assertEqual(result["data"]["device"]["name"], "router-01")
            self.assertIsNone(result["errors"])
        finally:
            token.delete()

    # ... (3 more test cases)
```

---

## 4. Decisions I can make during implementation (D-08 scope)

| Decision | Options | Recommended | Rationale |
|---|---|---|---|
| Variable naming in sync helper | `variables: dict \| None` vs `variables: dict` | `dict \| None` | Matches `execute_query` signature |
| Type annotation on return dict | `dict[str, Any]` vs `dict` | `dict[str, Any]` | Consistent with all core tools |
| Error message text | "Authentication required" vs "User required" | "Authentication required" | Matches HTTP 401 semantics |
| Test mock patching level | Patch `execute_query` at module level | Module-level patch | Isolates tests from Nautobot internals |
| Test fixture approach | Real user from DB (like `test_auth.py`) | Real user + token mock | Same pattern as existing auth tests |

---

## 5. Coverage of requirements

| Req | What it means | Covered by |
|---|---|---|
| GQL-01 | `graphql_query` tool exists | `graphql_tool.py` + `__init__.py` side-effect import |
| GQL-02 | `sync_to_async(thread_sensitive=True)` at outer boundary | `graphql_tool.py` — single wrapper around `_sync_graphql_query` |
| GQL-03 | Reuse `nautobot.core.graphql.execute_query()` | `_sync_graphql_query` calls it directly |
| GQL-04 | Accept `query: str` + `variables: dict \| None` | Function signature |
| GQL-05 | Return `{data, errors}` dict | `_sync_graphql_query` returns `result.formatted` |
| GQL-06 | `output_schema=None` on decorator | `@register_tool` has no `output_schema` kwarg → FastMCP default |
| GQL-07 | Auth via `get_user_from_request()` | `await get_user_from_request(ctx)` → pass as `user=user` |
| GQL-14 | Auth propagation unit test | `test_auth_propagates_to_execute_query` — mock verifies user is passed |
| GQL-15 | Valid query returns `{data, errors}` unit test | `test_valid_query_returns_structured_data` |
| GQL-16 | Invalid query returns errors dict unit test | `test_invalid_query_returns_errors_dict` |
| GQL-17 | Variables injection unit test | `test_variables_injection_works` |

**All 11 requirements addressed.**

---

## 6. Remaining unknowns (not blocking)

- **None identified.** All canonical references were read and all decision points have clear guidance from `14-CONTEXT.md`.

---

*Research: 2026-04-15*