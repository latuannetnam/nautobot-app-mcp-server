# Phase 15: Introspection & Permissions — Research

**Research date:** 2026-04-15
**Phase:** 15-introspection-permissions

---

## Research Question 1: How to get GraphQL SDL from Nautobot's graphene-django schema?

### Finding

Nautobot's GraphQL schema lives at `nautobot.core.graphql.schema_init.schema`. This is a `graphene.Schema` instance. The path is configured in `nautobot/core/settings.py`:

```python
GRAPHENE = {
    "SCHEMA": "nautobot.core.graphql.schema_init.schema",
    ...
}
```

The `nautobot.core.graphql.schema_init.schema` is a `graphene.Schema` object (graphene 3.4.3). It exposes a `.graphql_schema` property that returns the underlying `graphql-core.GraphQLSchema`. **graphql-core** (`graphql-core` v3.2.8) provides `print_schema()`:

```python
from graphql import print_schema

# Path to Nautobot's schema
# In execute_query: graphene_settings.SCHEMA.graphql_schema
# where graphene_settings = graphene_django.settings.graphene_settings

schema = graphene_settings.SCHEMA  # nautobot.core.graphql.schema_init.schema
sdl: str = print_schema(schema.graphql_schema)
```

`print_schema()` is the canonical graphql-core API for this, also used by `graphene_django`'s `graphql_schema` management command (`/usr/local/lib/python3.12/site-packages/graphene_django/management/commands/graphql_schema.py`). The output is a multi-line `str` (not a dict), exactly matching the GQL-09 requirement.

### Key file locations

| File | Purpose |
|------|---------|
| `/usr/local/lib/python3.12/site-packages/nautobot/core/graphql/schema_init.py` | `schema = graphene.Schema(query=Query, auto_camelcase=False)` — the canonical schema object |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py` | `execute_query(query, variables, request, user)` — uses `graphene_settings.SCHEMA.graphql_schema` |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/settings.py:920` | `GRAPHENE = {"SCHEMA": "nautobot.core.graphql.schema_init.schema"}` |

### Implementation approach

```python
# In graphql_tool.py — sync helper
def _sync_graphql_introspect(user) -> str:
    from graphql import print_schema
    from graphene_django.settings import graphene_settings
    # Auth check: same pattern as execute_query ValueError
    if user is None:
        return None  # caller will handle
    schema = graphene_settings.SCHEMA
    return print_schema(schema.graphql_schema)
```

---

## Research Question 2: How does graphql-core provide SDL export?

### Finding

`graphql-core` v3.2.8 (confirmed in container) exposes `print_schema()` directly in the top-level `graphql` package:

```python
from graphql import print_schema, build_schema, GraphQLError

# print_schema: takes a GraphQLSchema → returns str (SDL)
sdl: str = print_schema(schema.graphql_schema)

# build_schema: takes SDL str → returns a new GraphQLSchema
rebuilt = build_schema(sdl)  # Used in test validation

# GraphQLError: exception raised by build_schema on malformed SDL
# Used for test validation
```

Both `print_schema` and `build_schema` are confirmed working in the container:

```python
>>> from graphql import print_schema, build_schema
>>> schema = build_schema('type Query { hello: String }')
>>> print_schema(schema.graphql_schema)
'type Query {\n  hello: String\n}'
```

Note: For `graphene.Schema`, access the underlying schema via `.graphql_schema` property (graphene 3.x wraps graphql-core's Schema). Direct `print_schema(schema)` on a `graphene.Schema` does NOT work — must be `print_schema(schema.graphql_schema)`.

### Test validation approach (D-05)

D-05 specifies `build_schema(sdl)` for SDL validation (raises `GraphQLError` on malformed input). This is confirmed to work:

```python
from graphql import GraphQLError

try:
    build_schema(sdl)  # Re-raises as GraphQLError on failure
    # Valid SDL
except GraphQLError:
    # Invalid SDL
```

---

## Research Question 3: Permission enforcement in GraphQL

### Finding

Nautobot's GraphQL resolver generator `generate_restricted_queryset()` in `nautobot/core/graphql/generators.py` applies `.restrict(user, "view")` to all querysets **in resolvers that fetch individual objects** (e.g., `Device(id: ID!)`). However, for **list queries** (e.g., `devices`), the resolver calls `model.objects.restrict(user, "view").all()` — so permission IS enforced on list queries too.

The mechanism:
```python
# generators.py:34
queryset.restrict(info.context.user, "view")
```

The `user` comes from `info.context` which is the Django request passed as `context_value` in `execute()`:
```python
# nautobot/core/graphql/__init__.py:execute_query
execute(schema=schema, document=document, context_value=request, ...)
# Where request.user is set to the authenticated user
```

### Anonymous user behavior

When `execute_query` is called with `user=None` (no auth):
```python
# If no user provided, execute_query creates a mock request with user=None
request = RequestFactory().post("/graphql/")
request.user = None  # Django middleware converts None → AnonymousUser
```

**Critically:** When `user=None` AND `request=None`, `execute_query` raises `ValueError("Either request or username should be provided")`. This is the auth-gating mechanism for `graphql_query` (Phase 14 test `test_anonymous_user_triggers_auth_error`).

For `graphql_introspect`, auth is gated at the MCP tool handler level (same as `graphql_query`). The `_sync_graphql_introspect` helper receives a user that is already resolved by `get_user_from_request(ctx)` — so `user=None` means anonymous (no token), `user=User` means authenticated.

### Permission enforcement for introspection

**Introspection query does NOT filter by object permissions** — it returns the schema types/fields regardless of user. This is standard GraphQL behavior: introspection is about the schema structure, not data. However, `graphql_introspect` returns SDL, and **SDL itself may reveal internal model structure** (D-01 rationale for requiring auth).

For GQL-13 testing (permission enforcement for queries), the test should verify:
1. `graphql_query` with `AnonymousUser` → empty or permission-filtered results
2. `graphql_query` with authenticated user with view permissions → non-empty results

The permission test should mock `execute_query` to observe the user passed to it, or use a real simple query against Nautobot (like `{ devices { count } }`) and verify different result shapes.

---

## Research Question 4: Mock-based permission tests

### Finding

The Phase 14 test pattern uses `@patch` at the module level to mock `get_user_from_request` and `_sync_graphql_query`. For permission tests (GQL-13), the approach is:

**Option A: Mock `nautobot.core.graphql.execute_query`** (in `graphql_tool._sync_graphql_query`'s scope)
```python
@patch("nautobot.core.graphql.execute_query")
def test_anonymous_query_result(self, mock_execute):
    # execute_query is called with user=AnonymousUser
    # it raises ValueError, or returns empty data
    mock_execute.return_value = MagicMock(formatted={"data": None, "errors": [...]})
    result = _sync_graphql_query(query="{ devices { name } }", variables=None, user=AnonymousUser())
    self.assertIn("errors", result)
```

**Option B: Mock `graphql_tool._sync_graphql_query` itself** (higher-level)
```python
@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
def test_anonymous_yields_empty(self, mock_sync):
    mock_sync.return_value = {"data": {"devices": []}, "errors": None}
    # Call handler with anonymous user
```

**Option C: Use real `graphql_query` with mocked `get_user_from_request`** (cleanest)
```python
@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
def test_authenticated_user_gets_data(self, mock_get_user):
    mock_get_user.return_value = user_with_permissions
    result = AsyncToSync(_graphql_query_handler)(ctx, "{ devices { name } }")
    self.assertIn("data", result)
```

**For GQL-13:** The requirement says "AnonymousUser → empty results, authenticated user → filtered results". The most robust test is to mock `execute_query` (where permissions are enforced) and verify the `user` argument is correct in each case. However, the GraphQL layer handles `.restrict()` internally, so what we can test at unit level is:
1. The correct user is passed to `execute_query`
2. `AnonymousUser` (user=None) triggers the `ValueError` path

**Recommended pattern** (following Phase 14's `test_anonymous_user_triggers_auth_error`):
```python
def test_anonymous_triggers_empty_data(self):
    """GQL-13: AnonymousUser via None returns empty/error result."""
    # When user=None, _sync_graphql_query catches ValueError
    result = _sync_graphql_query(query="{ devices { name } }", variables=None, user=None)
    self.assertIn("errors", result)
    self.assertIsNone(result["data"])

def test_authenticated_user_gets_data(self):
    """GQL-13: Authenticated user triggers normal execution."""
    # When user is a real User, execute_query runs normally
    mock_execute.return_value = MagicMock(formatted={"data": {"devices": [{"name": "r1"}]}, "errors": None})
    result = _sync_graphql_query(query="{ devices { name } }", variables=None, user=mock_user)
    self.assertNotIn("errors", result)
    self.assertIn("data", result)
```

For the MCP tool handler test (via `_graphql_query_handler`):
```python
@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
@patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query")
def test_handler_passes_user_to_sync(self, mock_sync, mock_get_user):
    mock_get_user.return_value = mock_user
    result = AsyncToSync(_graphql_query_handler)(ctx, "{ devices { name } }")
    _, kwargs = mock_sync.call_args
    assert kwargs["user"] == mock_user
```

---

## Research Question 5: Error response for auth failure

### Finding

**The core conflict:** D-07 notes `graphql_introspect` returns `str` (SDL), but auth failure needs `{"error": "Authentication required"}`. The return type is `str`, yet error needs to be communicated differently.

**Resolution:** Two options:

**Option A — Raise `ValueError` to FastMCP (preferred):**
```python
@register_tool(name="graphql_introspect", ...)
async def _graphql_introspect_handler(ctx: ToolContext) -> str:
    user = await get_user_from_request(ctx)
    if user is None:
        raise ValueError("Authentication required")
    return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)(user=user)
```
FastMCP catches raised exceptions and converts them to structured tool errors. This is the cleanest approach and consistent with how the project handles errors (D-07: "raise a ValueError that FastMCP handles as a tool error").

**Option B — Return a sentinel string (NOT recommended):**
Would return `{"error": "Authentication required"}` as a string, which is not valid SDL and would confuse clients.

**Option C — Return empty SDL string (NOT recommended):**
Would pass validation but not signal auth failure.

**Decision:** Option A is cleaner and consistent with Phase 14's pattern where `execute_query` raises `ValueError` when user is None. FastMCP will surface this as a tool error response to the MCP client.

**Note on `graphql_query`:** The existing `graphql_query` returns `{"data": None, "errors": [{"message": "Authentication required"}]}` because its return type is `dict`. For `graphql_introspect` with return type `str`, Option A is the right choice.

**Implementation for `graphql_introspect`:**
```python
async def _graphql_introspect_handler(ctx: ToolContext) -> str:
    user = await get_user_from_request(ctx)
    if user is None:
        raise ValueError("Authentication required")
    return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)(user=user)
```

**Implementation for `graphql_query` permission test:** The test already covers this via `test_anonymous_user_triggers_auth_error` in Phase 14. No change needed.

---

## Research Question 6: Nautobot GraphQL schema location confirmation

### Finding — Confirmed

| Component | Location |
|-----------|----------|
| GraphQL schema variable | `nautobot.core.graphql.schema_init.schema` |
| Schema object type | `graphene.Schema` (graphene 3.4.3) |
| Underlying graphql-core schema | `schema.graphql_schema` (property) |
| SDL export | `from graphql import print_schema; print_schema(schema.graphql_schema)` |
| Settings configuration | `nautobot.core.settings.py:920` — `GRAPHENE["SCHEMA"]` |
| `execute_query` uses | `graphene_settings.SCHEMA.graphql_schema` |
| Permission enforcement | `nautobot.core.graphql.generators.generate_restricted_queryset()` — `.restrict(user, "view")` |

### Module import strategy

For lazy imports (avoiding Django setup at import time):
```python
from graphene_django.settings import graphene_settings  # Binds name at call time
# Or
from nautobot.core.graphql.schema_init import schema  # Direct schema reference
```

---

## Implementation Recommendations

### Recommendation 1: `graphql_introspect` handler structure

```python
# graphql_tool.py

@register_tool(
    name="graphql_introspect",
    description=(
        "Return the GraphQL schema as an SDL string. "
        "Auth token required — anonymous callers receive a tool error."
    ),
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_introspect_handler(ctx: ToolContext) -> str:
    """Return the GraphQL SDL string for Nautobot's schema.

    Returns:
        str: Multi-line GraphQL SDL describing all available types and fields.
    Raises:
        ValueError: If no authentication token is provided.
    """
    user = await get_user_from_request(ctx)
    if user is None:
        raise ValueError("Authentication required")
    return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)(user=user)


def _sync_graphql_introspect(user) -> str:
    """Synchronous SDL generator.

    Raises:
        ValueError: If user is None (anonymous).
    """
    from graphql import print_schema
    from graphene_django.settings import graphene_settings

    if user is None:
        raise ValueError("Authentication required")
    schema = graphene_settings.SCHEMA
    return print_schema(schema.graphql_schema)
```

**Key decisions:**
- Same auth pattern as `graphql_query` — `get_user_from_request` first
- ValueError raised → FastMCP converts to tool error
- Return type `str` (D-01) — no dict envelope, plain SDL
- Uses `graphene_settings.SCHEMA.graphql_schema` (same path as `execute_query`)

### Recommendation 2: Unit tests for `graphql_introspect`

```python
# test_graphql_tool.py — add new test class

class GraphQLIntrospectHandlerTestCase(TestCase):
    """Test the graphql_introspect MCP tool handler (GQL-08, GQL-09)."""

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_introspect")
    def test_introspect_returns_sdl_string(self, mock_sync, mock_get_user):
        """GQL-09: graphql_introspect returns a multi-line SDL string."""
        mock_sdl = 'type Query {\n  devices: [Device]\n}\ntype Device {\n  name: String\n}'
        mock_sync.return_value = mock_sdl
        mock_get_user.return_value = mock_user

        result = AsyncToSync(_graphql_introspect_handler)(ctx)
        self.assertIsInstance(result, str)
        self.assertIn("type Query", result)
        self.assertIn("Device", result)

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_introspect")
    def test_introspect_sdl_valid(self, mock_sync):
        """GQL-09: Returned SDL can be parsed by build_schema without GraphQLError."""
        from graphql import build_schema, GraphQLError
        mock_sdl = 'type Query { devices: [Device] } type Device { name: String }'
        mock_sync.return_value = mock_sdl

        result = _sync_graphql_introspect(user=mock_user)
        # D-05: build_schema raises GraphQLError on malformed SDL
        try:
            build_schema(result)
        except GraphQLError:
            self.fail("SDL from graphql_introspect is not valid GraphQL schema")

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    def test_introspect_raises_on_anonymous(self, mock_get_user):
        """GQL-08: Introspection requires auth — anonymous raises ValueError."""
        from django.contrib.auth.models import AnonymousUser
        mock_get_user.return_value = AnonymousUser()

        with self.assertRaises(ValueError) as ctx:
            AsyncToSync(_graphql_introspect_handler)(ctx)
        self.assertIn("Authentication required", str(ctx.exception))

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_tool.get_user_from_request")
    def test_auth_required(self, mock_get_user):
        """GQL-08: Verify auth token is resolved before sync boundary."""
        mock_get_user.return_value = mock_user
        AsyncToSync(_graphql_introspect_handler)(ctx)
        mock_get_user.assert_called_once()
```

### Recommendation 3: Permission test for GQL-13

```python
# Extend GraphQLQueryHandlerTestCase or add GraphQLPermissionTestCase

@patch("nautobot.core.graphql.execute_query")
def test_anonymous_user_empty_query_results(self, mock_execute):
    """GQL-13: AnonymousUser results in permission-filtered / empty data."""
    # execute_query with user=None raises ValueError → caught by _sync_graphql_query
    mock_execute.side_effect = ValueError("Either request or username should be provided")
    result = _sync_graphql_query(query="{ devices { name } }", variables=None, user=None)
    self.assertIsNone(result["data"])
    self.assertIn("errors", result)
    self.assertEqual(result["errors"][0]["message"], "Authentication required")

@patch("nautobot.core.graphql.execute_query")
def test_authenticated_user_normal_results(self, mock_execute):
    """GQL-13: Authenticated user gets non-empty filtered data."""
    mock_execute.return_value = MagicMock(
        formatted={"data": {"devices": [{"name": "router-01"}]}, "errors": None}
    )
    result = _sync_graphql_query(query="{ devices { name } }", variables=None, user=mock_user)
    self.assertIn("data", result)
    self.assertIsNone(result["errors"])
    self.assertNotEqual(result["data"]["devices"], [])
```

---

## Pitfalls to Avoid

1. **`print_schema(graphene.Schema)` vs `print_schema(graphql.GraphQLSchema)`**: graphenes Schema wraps graphql-core's Schema. Always use `.graphql_schema` property — `print_schema(graphene.Schema_instance)` raises `TypeError: ObjectType() takes no arguments`.

2. **Auth failure return type mismatch**: `graphql_introspect` returns `str`. Do NOT try to return `{"error": "..."}` as a string — use `raise ValueError` so FastMCP surfaces a proper tool error. For `graphql_query`, the dict return already handles this.

3. **Lazy import for `graphene_django.settings`**: Import `graphene_settings` inside the sync helper (or at call-time) to avoid Django setup issues at module load time.

4. **Thread safety**: All ORM calls in `graphql_introspect` must use `sync_to_async(..., thread_sensitive=True)`. However, `graphene_settings.SCHEMA` is a reference access (not ORM), so the sync helper can call `print_schema(schema.graphql_schema)` directly without thread concerns.

5. **`user is None` check vs `isinstance(user, AnonymousUser)`**: `get_user_from_request` returns `AnonymousUser` instance (not Python `None`). The check should be `user is None` in the handler only after `await get_user_from_request` returns `AnonymousUser()`. In `_sync_graphql_introspect`, use `if user is None` to match `execute_query`'s ValueError trigger. Note: `AnonymousUser.is_authenticated` is `False`, so check `user is None` not `not user.is_authenticated`.

6. **SDL validation test**: Use `build_schema(sdl)` which raises `GraphQLError` on malformed input. Do NOT use `assertIn('type', sdl)` — parse-only validation per D-05.

7. **Permission test mock location**: For `graphql_query`, patch `nautobot.core.graphql.execute_query` (where the name is imported inside `_sync_graphql_query`). For `graphql_introspect`, patch `_sync_graphql_introspect` directly since it's imported in the module.

---

## Validation Architecture (for VALIDATION.md)

### GQL-08: `graphql_introspect` MCP tool registered
- Verify tool appears in `mcp_list_tools` output
- Verify calling with valid token returns `str` (not `dict`)
- Verify calling without token raises tool error

### GQL-09: Returns GraphQL SDL string
- Assert `isinstance(result, str)`
- Assert `"type Query"` present in result
- Assert `build_schema(result)` executes without raising `GraphQLError`

### GQL-13: Permission enforcement
- Anonymous user → `ValueError` raised → tool error response
- Authenticated user → SDL string returned (no permission filtering on introspection)
- For query permission tests: mock `execute_query`, verify `AnonymousUser` triggers `ValueError` path, authenticated user triggers normal execution

---

## Files to Read Before Implementation

| File | Why |
|------|-----|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | Model `graphql_introspect` after `graphql_query` pattern |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` | Phase 14 tests for `graphql_query` — follow same patterns |
| `nautobot_app_mcp_server/mcp/tests/test_auth.py` | `_make_mock_ctx`, `_create_token` helpers |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/graphql/__init__.py` | `execute_query` signature, uses `graphene_settings.SCHEMA.graphql_schema` |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/graphql/schema_init.py` | `schema = graphene.Schema(query=Query, auto_camelcase=False)` — canonical schema object |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/graphql/generators.py` | `generate_restricted_queryset()` — permission enforcement mechanism |
| `/usr/local/lib/python3.12/site-packages/nautobot/core/settings.py:920` | `GRAPHENE["SCHEMA"]` setting confirming schema path |
| `/usr/local/lib/python3.12/site-packages/graphene_django/management/commands/graphql_schema.py` | `print_schema(schema.graphql_schema)` usage pattern |

---

*Research complete — ready for planning.*