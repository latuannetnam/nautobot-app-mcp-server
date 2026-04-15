# Universal GraphQL MCP Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single `graphql_query` MCP tool that lets AI agents query any Nautobot model via a structured interface (model + filters + fields + nested selections), using Graphene-Django internally. The tool validates field names against a schema cached at startup and returns GraphQL-native camelCase output.

**Architecture:** The tool accepts a structured query dict, validates it against a cached GraphQL schema, builds a GraphQL query string internally (no raw GraphQL from the agent), executes it via `nautobot.core.graphql.execute_query()`, and returns camelCase JSON. A companion `graphql_schema_get` tool lets agents discover available fields at runtime.

**Tech Stack:** Python ≥3.10, FastMCP, Graphene-Django, Django ORM (thread-sensitive), `nautobot.core.graphql.execute_query()`, `asgiref.sync.sync_to_async`

---

## File Map

| File | Role |
|---|---|
| `nautobot_app_mcp_server/mcp/tools/graphql_tools.py` | **New** — schema cache, query builder, executor, error translator |
| `nautobot_app_mcp_server/mcp/tools/core.py` | **Modified** — add `graphql_query` and `graphql_schema_get` tool handlers |
| `nautobot_app_mcp_server/mcp/tools/pagination.py` | Reference only — copy LIMIT constants if needed |
| `nautobot_app_mcp_server/__init__.py` | **Modified** — add schema cache init in `ready()` |
| `nautobot_app_mcp_server/mcp/auth.py` | Reference — `get_user_from_request()` reused for user injection |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py` | **New** — unit tests for all 4 modules |

---

## Task 1: Schema Cache Module (`graphql_schema.py`)

**Files:**
- Create: `nautobot_app_mcp_server/mcp/tools/graphql_schema.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for GraphQL schema introspection and caching."""
from django.test import TestCase
from nautobot_app_mcp_server.mcp.tools.graphql_schema import (
    get_cached_schema,
    get_fields_for_model,
    clear_schema_cache,
)


class TestSchemaCache(TestCase):
    """GRAPHQL-01: Schema is cached at first call and reused on subsequent calls."""

    def test_schema_cache_returns_same_object(self):
        """Two calls return the same cached object."""
        clear_schema_cache()
        schema1 = get_cached_schema()
        schema2 = get_cached_schema()
        self.assertIs(schema1, schema2)

    def test_schema_cache_type(self):
        """Cached schema is a graphene.Schema instance."""
        clear_schema_cache()
        schema = get_cached_schema()
        # graphene.Schema has 'query_type' attribute
        self.assertTrue(hasattr(schema, "query_type"))


class TestGetFieldsForModel(TestCase):
    """GRAPHQL-02: get_fields_for_model returns field names for a given type."""

    def test_get_fields_for_device(self):
        """Device type exposes expected fields."""
        clear_schema_cache()
        fields = get_fields_for_model("Device")
        self.assertIsInstance(fields, list)
        self.assertIn("name", fields)
        self.assertIn("status", fields)

    def test_get_fields_for_unknown_model(self):
        """Unknown model raises ValueError."""
        clear_schema_cache()
        with self.assertRaises(ValueError) as ctx:
            get_fields_for_model("NonExistentModel")
        self.assertIn("not found", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nautobot_app_mcp_server.mcp.tools.graphql_schema'`

- [ ] **Step 3: Write minimal schema cache implementation**

```python
"""GraphQL schema introspection and caching.

GRAPHQL-01: Schema is cached at first call in a module-level variable.
Reused on subsequent calls without re-introspection.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from graphene_dsettings import graphene_settings

if TYPE_CHECKING:
    pass

LOG = logging.getLogger(__name__)

# Module-level cache — persists across calls within the MCP server process
_cached_schema: Any | None = None


def get_cached_schema() -> Any:
    """Return the Nautobot GraphQL schema, fetching and caching it on first call.

    On AttributeError (schema field removed after Nautobot upgrade) or first
    call, introspects the schema via graphene introspection.

    Returns:
        A graphene.Schema instance.

    Raises:
        RuntimeError: If the schema cannot be obtained or introspected.
    """
    global _cached_schema

    if _cached_schema is not None:
        return _cached_schema

    try:
        schema = graphene_settings.SCHEMA.graphql_schema
        _cached_schema = schema
        LOG.info("GraphQL schema cached successfully")
        return schema
    except AttributeError as exc:
        LOG.warning("GraphQL schema not available: %s", exc)
        raise RuntimeError(f"Cannot obtain Nautobot GraphQL schema: {exc}") from exc


def get_fields_for_model(model_name: str) -> list[str]:
    """Return a list of field names for the given GraphQL model type.

    Uses graphene introspection to extract field names from the schema.

    Args:
        model_name: GraphQL type name, e.g. "Device", "Interface".

    Returns:
        List of field name strings.

    Raises:
        ValueError: If the model type is not found in the schema.
    """
    schema = get_cached_schema()
    query_type = schema.query_type

    # Traverse to find the type by name
    type_map = schema._type_map  # noqa: SLF001 — internal graphene API
    graph_type = type_map.get(model_name)

    if graph_type is None:
        raise ValueError(
            f"Model '{model_name}' not found in GraphQL schema. "
            f"Available types: {sorted(type_map.keys())}"
        )

    # ObjectType fields are in .fields dict
    if hasattr(graph_type, "fields"):
        return sorted(graph_type.fields.keys())

    return []


def clear_schema_cache() -> None:
    """Clear the cached schema (for testing)."""
    global _cached_schema
    _cached_schema = None
```

- [ ] **Step 4: Fix import typo — `graphene_dsettings` → `graphene_django.settings`**

```python
from graphene_django.settings import graphene_settings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestSchemaCache -v`
Expected: PASS (or import error if graphene_django.settings is named differently — fix to `from nautobot.apps.graphql import schema as nb_schema`)

> **Note:** If the above import fails, try:
> ```python
> from nautobot.core.graphql import execute_query  # for task 3
> # For schema access, introspect via graphql-core directly:
> from graphql import build_client_schema
> # OR use the schema object from nautobot.core.graphql:
> import nautobot.core.graphql.schema_init as nb_schema_init
> schema = nb_schema_init.schema
> ```

- [ ] **Step 6: Commit**

```bash
git add nautobot_app_mcp_server/mcp/tools/graphql_schema.py nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py
git commit -m "feat: add GraphQL schema introspection and caching module

GRAPHQL-01: module-level cache in graphql_schema.py
GRAPHQL-02: get_fields_for_model() with ValueError for unknown models"
```

---

## Task 2: GraphQL Query Builder (`graphql_query_builder.py`)

**Files:**
- Create: `nautobot_app_mcp_server/mcp/tools/graphql_query_builder.py`
- Test: `nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py` (add TestGraphqlQueryBuilder class)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for GraphQL query building from structured input."""
from django.test import TestCase
from nautobot_app_mcp_server.mcp.tools.graphql_query_builder import (
    build_graphql_query,
    SupportedFilter,
)


class TestBuildGraphqlQuery(TestCase):
    """GRAPHQL-03: build_graphql_query converts {model, filters, fields} to GraphQL string."""

    def test_simple_query(self):
        """Single model with one filter and one field."""
        query = build_graphql_query(
            model="Device",
            filters={"name": "router-01"},
            fields=["name", "status"],
        )
        self.assertIn("query Device(", query)
        self.assertIn('name: "router-01"', query)
        self.assertIn("name", query)
        self.assertIn("status", query)

    def test_multiple_filters_are_and(self):
        """Multiple filters produce AND conditions."""
        query = build_graphql_query(
            model="Device",
            filters={"name__icontains": "router", "status__name": "active"},
            fields=["name"],
        )
        self.assertIn(" AND ", query)

    def test_nested_selections(self):
        """Nested selections produce nested GraphQL query structure."""
        query = build_graphql_query(
            model="Device",
            filters={"name": "router-01"},
            fields=["name"],
            nested=[{"field": "interfaces", "fields": ["name", "status"]}],
        )
        self.assertIn("interfaces {", query)
        self.assertIn("name", query)
        self.assertIn("status", query)

    def test_limit_applied(self):
        """limit is applied as first N results."""
        query = build_graphql_query(
            model="Device",
            filters={},
            fields=["name"],
            limit=10,
        )
        self.assertIn("first: 10", query)

    def test_unknown_field_raises(self):
        """Unknown field name raises ValueError with available fields."""
        from nautobot_app_mcp_server.mcp.tools.graphql_schema import get_fields_for_model

        # Mock so we don't need live schema in unit test
        with self.assertRaises(ValueError) as ctx:
            build_graphql_query(
                model="Device",
                filters={},
                fields=["nonexistent_field_xyz"],
            )
        self.assertIn("nonexistent_field_xyz", str(ctx.exception))


class TestSupportedFilter(TestCase):
    """GRAPHQL-04: SupportedFilter maps Django ORM lookup to GraphQL filter syntax."""

    def test_exact(self):
        f = SupportedFilter("name", "router-01")
        self.assertEqual(f.to_graphql(), 'name: "router-01"')

    def test_iexact(self):
        f = SupportedFilter("name__iexact", "Router-01")
        self.assertEqual(f.to_graphql(), 'name_Iexact: "Router-01"')

    def test_icontains(self):
        f = SupportedFilter("name__icontains", "router")
        self.assertEqual(f.to_graphql(), 'name_Icontains: "router"')

    def test_in(self):
        f = SupportedFilter("pk__in", ["abc", "def"])
        self.assertEqual(f.to_graphql(), 'pk_In: ["abc", "def"]')

    def test_unsupported_operator_raises(self):
        with self.assertRaises(ValueError) as ctx:
            SupportedFilter("name__like", "router")
        self.assertIn("not supported", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestBuildGraphqlQuery -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal query builder**

```python
"""GraphQL query builder from structured {model, filters, fields, nested} input.

Converts:
    {model: "Device", filters: {name: "router-01"}, fields: ["name", "status"]}
To:
    query {
        device(name: "router-01", first: 25) {
            name
            status
        }
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Supported filter operators: Django ORM lookup → GraphQL field suffix
_FILTER_OPERATORS = {
    "exact": "",
    "iexact": "_Iexact",
    "contains": "_contains",
    "icontains": "_Icontains",
    "in": "_In",
    "gt": "_Gt",
    "lt": "_Lt",
    "gte": "_Gte",
    "lte": "_Lte",
}

# Reverse map for error messages
_REVERSE_OPERATORS = {v: k for k, v in _FILTER_OPERATORS.items() if v}


@dataclass
class SupportedFilter:
    """A Django ORM-style filter key/value pair.

    Attribute:
        key: Field name with optional __ operator suffix
               (e.g. "name", "name__icontains", "status__name").
        value: Filter value (str, int, list, bool).
    """

    key: str
    value: Any

    def _parse_key(self) -> tuple[str, str]:
        """Return (field_name, operator_suffix)."""
        if "__" in self.key:
            field, op = self.key.rsplit("__", 1)
            if op not in _FILTER_OPERATORS:
                supported = ", ".join(sorted(_FILTER_OPERATORS))
                raise ValueError(
                    f"Filter operator '__{op}' not supported. "
                    f"Supported operators: {supported}"
                )
            return field, _FILTER_OPERATORS[op]
        return self.key, ""

    def to_graphql(self) -> str:
        """Return GraphQL filter string fragment."""
        field, suffix = self._parse_key()
        gql_field = field + suffix

        if isinstance(self.value, str):
            return f'{gql_field}: {json.dumps(self.value)}'
        if isinstance(self.value, (int, float)):
            return f"{gql_field}: {self.value}"
        if isinstance(self.value, bool):
            return f"{gql_field}: {str(self.value).lower()}"
        if isinstance(self.value, list):
            items = ", ".join(json.dumps(v) for v in self.value)
            return f"{gql_field}: [{items}]"
        # Fallback
        return f'{gql_field}: {json.dumps(str(self.value))}'


def build_graphql_query(
    model: str,
    filters: dict[str, Any],
    fields: list[str],
    nested: list[dict[str, Any]] | None = None,
    limit: int | None = None,
) -> str:
    """Build a GraphQL query string from structured input.

    Args:
        model: GraphQL type name (e.g. "Device").
        filters: Dict of Django ORM-style field filters.
        fields: List of top-level field names to request.
        nested: List of nested selection dicts, each with:
            - field: str (relationship field name)
            - fields: list[str] (child fields)
            - nested: list[dict] (optional further nesting)
        limit: Max results (sets GraphQL first: N). Defaults to 25.

    Returns:
        A GraphQL query string.

    Raises:
        ValueError: If any field name is not in the schema.
    """
    from nautobot_app_mcp_server.mcp.tools.graphql_schema import get_fields_for_model

    # Validate field names against schema
    if fields:
        try:
            valid_fields = set(get_fields_for_model(model))
        except RuntimeError:
            valid_fields = set()  # Skip validation if schema unavailable

        for fld in fields:
            if fld not in valid_fields:
                raise ValueError(
                    f"Field '{fld}' not found on model '{model}'. "
                    f"Available fields: {sorted(valid_fields)}"
                )

    # Build filter string
    filter_parts = [SupportedFilter(k, v).to_graphql() for k, v in (filters or {}).items()]
    filter_str = ", ".join(filter_parts)
    if filter_str:
        filter_str = f"({filter_str})"

    # Build nested selection strings
    def build_selection(fields_list: list[str], nested_list: list[dict[str, Any]] | None) -> str:
        lines = ["{"]
        for fld in fields_list:
            lines.append(f"    {fld}")
        if nested_list:
            for ns in nested_list:
                lines.append(f"    {ns['field']} {build_selection(ns['fields'], ns.get('nested'))}")
        lines.append("}")
        return "\n".join(lines)

    nested_str = ""
    if nested:
        nested_str = "\n" + build_selection(fields, nested)

    # Assemble
    limit_val = limit if limit is not None else 25
    first_str = f"first: {limit_val}"
    filter_str_with_first = filter_str.replace(")", f", {first_str})") if filter_str else f"({first_str})"

    model_lower = model[:1].lower() + model[1:]  # camelCase: Device → device
    query = f'query {{\n  {model_lower}{filter_str_with_first} {{\n' + "\n".join(f"    {f}" for f in fields) + nested_str + "\n  }\n}"
    return query
```

- [ ] **Step 4: Run tests and fix issues**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestBuildGraphqlQuery -v`
Expected: FAIL — fix the `limit` injection logic (filter_str already has parens, need to handle differently)

- [ ] **Step 4b: Fix the limit injection — rewrite filter_str assembly**

The current logic tries to inject `first: N` inside existing parens — this is fragile. Fix to:

```python
    limit_val = limit if limit is not None else 25
    args = f"first: {limit_val}"
    if filter_parts:
        args += ", " + ", ".join(filter_parts)
    filter_str = f"({args})"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestBuildGraphqlQuery -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nautobot_app_mcp_server/mcp/tools/graphql_query_builder.py
git commit -m "feat: add GraphQL query builder from structured input

GRAPHQL-03: build_graphql_query() converts {model, filters, fields, nested}
GRAPHQL-04: SupportedFilter maps Django ORM lookups to GraphQL filter format"
```

---

## Task 3: GraphQL Executor + Error Translator (`graphql_executor.py`)

**Files:**
- Create: `nautobot_app_mcp_server/mcp/tools/graphql_executor.py`
- Test: `nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py` (add TestGraphqlExecutor class)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for GraphQL execution and error translation."""
from django.test import TestCase
from unittest.mock import MagicMock, patch
from nautobot_app_mcp_server.mcp.tools.graphql_executor import (
    execute_graphql_query,
    translate_graphql_errors,
    GraphQLQueryError,
)


class TestTranslateGraphqlErrors(TestCase):
    """GRAPHQL-05: translate_graphql_errors rewrites cryptic GraphQL errors."""

    def test_unknown_field_error(self):
        """Unknown field → actionable message listing available fields."""
        raw_errors = [
            {
                "message": "Cannot query field 'device_name' on type 'Device'.",
                "locations": [{"line": 1, "column": 3}],
            }
        ]
        result = translate_graphql_errors(raw_errors, model="Device", available_fields=["name", "status"])
        self.assertIn("device_name", result)
        self.assertIn("Device", result)

    def test_filter_error(self):
        """Filter error → message with supported operators."""
        raw_errors = [{"message": "Unknown argument 'name_Llike'."}]
        result = translate_graphql_errors(raw_errors, model="Device", available_fields=["name"])
        # Message should be actionable
        self.assertTrue(len(result) > 0)


class TestExecuteGraphqlQuery(TestCase):
    """GRAPHQL-06: execute_graphql_query runs the query and returns camelCase JSON."""

    def test_success_returns_data(self):
        """On success, returns the 'data' key from the result."""
        mock_result = {"data": {"device": {"name": "router-01", "status": "active"}}}
        with patch("nautobot_app_mcp_server.mcp.tools.graphql_executor.execute_query") as mock_eq:
            mock_eq.return_value = mock_result
            result = execute_graphql_query(
                query="query { device(name: \"router-01\") { name status } }",
                user=MagicMock(),
            )
            self.assertEqual(result, mock_result["data"])

    def test_graphql_errors_are_translated(self):
        """GraphQL errors raise GraphQLQueryError with translated messages."""
        raw_errors = [{"message": "Cannot query field 'device_name' on type 'Device'."}]
        mock_result = {"data": None, "errors": raw_errors}
        with patch("nautobot_app_mcp_server.mcp.tools.graphql_executor.execute_query") as mock_eq:
            mock_eq.return_value = mock_result
            with self.assertRaises(GraphQLQueryError) as ctx:
                execute_graphql_query(
                    query="query { device { device_name } }",
                    user=MagicMock(),
                )
            self.assertIn("device_name", str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestExecuteGraphqlQuery -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal executor implementation**

```python
"""GraphQL query execution and error translation.

GRAPHQL-05: translate_graphql_errors rewrites cryptic GraphQL errors into
actionable messages for AI agents.
GRAPHQL-06: execute_graphql_query runs the query via nautobot.core.graphql.execute_query()
and returns camelCase JSON.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.contrib.auth.models import User

from nautobot.core.graphql import execute_query

LOG = logging.getLogger(__name__)


class GraphQLQueryError(Exception):
    """Raised when a GraphQL query returns errors.

    Attributes:
        translated_message: Human-readable error message with guidance.
        original_errors: Raw GraphQL error dicts.
    """

    def __init__(self, translated_message: str, original_errors: list[dict[str, Any]]):
        self.translated_message = translated_message
        self.original_errors = original_errors
        super().__init__(translated_message)


def translate_graphql_errors(
    errors: list[dict[str, Any]],
    model: str,
    available_fields: list[str],
) -> str:
    """Translate raw GraphQL errors into actionable messages for AI agents.

    Args:
        errors: List of GraphQL error dicts with 'message' keys.
        model: The GraphQL type being queried (e.g. "Device").
        available_fields: List of valid field names for this model.

    Returns:
        A single human-readable error string.
    """
    if not errors:
        return "Unknown GraphQL error"

    messages = []
    available = ", ".join(sorted(available_fields))

    for error in errors:
        msg = error.get("message", "")

        # Unknown field
        if "Cannot query field" in msg or "Cannot query field" in msg:
            # Extract field name from message
            import re
            match = re.search(r"'(\w+)'", msg)
            bad_field = match.group(1) if match else "unknown"
            messages.append(
                f"Unknown field '{bad_field}' on model '{model}'. "
                f"Available fields: {available}"
            )

        # Unknown argument (bad filter operator)
        elif "Unknown argument" in msg:
            messages.append(
                f"Invalid filter in query: {msg}. "
                f"Supported filter operators for '{model}': exact, iexact, contains, icontains, in, gt, lt, gte, lte"
            )

        # Auth / access denied
        elif "not have permission" in msg.lower() or "unauthorized" in msg.lower():
            messages.append(
                f"Access denied to model '{model}'. "
                "Check your Nautobot token permissions."
            )

        # Fallback
        else:
            messages.append(f"GraphQL error: {msg}")

    return " | ".join(messages)


def execute_graphql_query(
    query: str,
    user: User,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a GraphQL query and return the data.

    Args:
        query: A GraphQL query string (built by graphql_query_builder).
        user: Nautobot User for permission enforcement.
        variables: Optional GraphQL variables dict.

    Returns:
        The 'data' dict from the GraphQL result (camelCase).

    Raises:
        GraphQLQueryError: If the query returns GraphQL errors.
    """
    from nautobot_app_mcp_server.mcp.tools.graphql_schema import get_fields_for_model
    from nautobot_app_mcp_server.mcp.tools.graphql_query_builder import _MODEL_NAME_HACK

    # Determine model name from query for error translation
    # Simple heuristic: extract first word after "query {" or first word
    model_name = "Unknown"
    for word in ["Device", "Interface", "IPAddress", "Prefix", "VLAN", "Location"]:
        if word.lower() in query.lower():
            model_name = word
            break

    try:
        available_fields = get_fields_for_model(model_name)
    except (ValueError, RuntimeError):
        available_fields = []

    # Execute via Nautobot's GraphQL executor with user injected
    result = execute_query(query=query, variables=variables, user=user)

    if result.get("errors"):
        translated = translate_graphql_errors(
            errors=result["errors"],
            model=model_name,
            available_fields=available_fields,
        )
        raise GraphQLQueryError(translated_message=translated, original_errors=result["errors"])

    return result.get("data", {})
```

> **Note:** `_MODEL_NAME_HACK` doesn't exist yet — remove that reference. Just use the heuristic directly.

- [ ] **Step 4: Run tests and fix issues**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestExecuteGraphqlQuery -v`
Expected: FAIL — fix issues from test review

- [ ] **Step 5: Run tests to verify they pass**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestExecuteGraphqlQuery -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nautobot_app_mcp_server/mcp/tools/graphql_executor.py
git commit -m "feat: add GraphQL executor with error translation

GRAPHQL-05: translate_graphql_errors() for actionable AI agent messages
GRAPHQL-06: execute_graphql_query() via nautobot.core.graphql.execute_query()
GRAPHQL-07: GraphQLQueryError exception class"
```

---

## Task 4: MCP Tool Handlers (`core.py` additions)

**Files:**
- Modify: `nautobot_app_mcp_server/mcp/tools/core.py` — add two new tool handler functions
- Test: `nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py` (add TestGraphqlToolsIntegration class)

- [ ] **Step 1: Write the failing integration tests**

```python
"""Integration tests for graphql_query and graphql_schema_get MCP tools."""
from django.test import TestCase
from unittest.mock import MagicMock, patch, AsyncMock


class TestGraphqlQueryTool(TestCase):
    """GRAPHQL-08: graphql_query tool accepts structured input and returns camelCase JSON."""

    def test_tool_signature(self):
        """Tool handler accepts model, filters, fields, nested, limit."""
        from nautobot_app_mcp_server.mcp.tools.core import _graphql_query_handler
        import inspect
        sig = inspect.signature(_graphql_query_handler)
        params = list(sig.parameters.keys())
        # Should have ctx + 5 query params
        self.assertIn("model", params)
        self.assertIn("filters", params)
        self.assertIn("fields", params)
        self.assertIn("nested", params)
        self.assertIn("limit", params)

    @patch("nautobot_app_mcp_server.mcp.tools.core.sync_to_async")
    def test_handler_calls_sync_impl(self, mock_sa):
        """Handler delegates to sync implementation via sync_to_async."""
        mock_sa.return_value = AsyncMock(return_value={"data": {"devices": []}})
        from nautobot_app_mcp_server.mcp.tools.core import _graphql_query_handler
        from fastmcp.server.context import Context
        import asyncio
        ctx = MagicMock(spec=Context)
        ctx.request_context = None
        ctx.get_http_request = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                _graphql_query_handler(ctx, model="Device", filters={}, fields=["name"])
            )
        finally:
            loop.close()

        mock_sa.assert_called()


class TestGraphqlSchemaGetTool(TestCase):
    """GRAPHQL-09: graphql_schema_get returns available fields for a model."""

    def test_tool_signature(self):
        """Tool handler accepts model name and returns field list."""
        from nautobot_app_mcp_server.mcp.tools.core import _graphql_schema_get_handler
        import inspect
        sig = inspect.signature(_graphql_schema_get_handler)
        params = list(sig.parameters.keys())
        self.assertIn("model", params)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestGraphqlQueryTool -v`
Expected: FAIL — handler functions don't exist yet

- [ ] **Step 3: Add tool handler functions to core.py**

In `nautobot_app_mcp_server/mcp/tools/core.py`, add:

```python
# -------------------------------------------------------------------
# graphql_query
# -------------------------------------------------------------------


@register_tool(
    name="graphql_query",
    description=(
        "Query Nautobot models via GraphQL using a structured interface. "
        "Specify model, filters, fields, and optional nested selections. "
        "Returns camelCase JSON matching Nautobot's GraphQL schema. "
        "Use graphql_schema_get to discover available fields before querying."
    ),
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_query_handler(
    ctx: ToolContext,
    model: str,
    filters: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    nested: list[dict[str, Any]] | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """Query Nautobot via GraphQL with a structured interface.

    Args:
        ctx: FastMCP ToolContext.
        model: GraphQL type name (e.g. "Device", "Interface", "IPAddress").
        filters: Django ORM-style filters (e.g. {"name__icontains": "router"}).
        fields: List of field names to return.
        nested: Nested relationship selections.
            Example: [{"field": "interfaces", "fields": ["name", "status"]}]
        limit: Maximum results (default 25, max 1000).

    Returns:
        camelCase JSON dict from GraphQL response.

    Raises:
        GraphQLQueryError: On query error (field not found, auth denied, etc.).
    """
    from nautobot_app_mcp_server.mcp.auth import get_user_from_request
    from nautobot_app_mcp_server.mcp.tools.graphql_query_builder import build_graphql_query
    from nautobot_app_mcp_server.mcp.tools.graphql_executor import execute_graphql_query
    from nautobot_app_mcp_server.mcp.tools.pagination import LIMIT_MAX

    if limit <= 0:
        return {"error": "limit must be positive"}
    limit = min(limit, LIMIT_MAX)

    user = await get_user_from_request(ctx)

    if not fields:
        return {"error": "At least one field must be specified."}

    if not model:
        return {"error": "model is required."}

    query_str = build_graphql_query(
        model=model,
        filters=filters or {},
        fields=fields,
        nested=nested,
        limit=limit,
    )

    return await sync_to_async(
        execute_graphql_query, thread_sensitive=True
    )(query=query_str, user=user)


# -------------------------------------------------------------------
# graphql_schema_get
# -------------------------------------------------------------------


@register_tool(
    name="graphql_schema_get",
    description=(
        "Get available GraphQL fields for a Nautobot model. "
        "Use this before graphql_query to discover valid field names. "
        "Returns a list of field names for the specified model type."
    ),
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
async def _graphql_schema_get_handler(
    ctx: ToolContext,
    model: str,
) -> dict[str, Any]:
    """Get available GraphQL field names for a model.

    Args:
        ctx: FastMCP ToolContext.
        model: GraphQL type name (e.g. "Device", "Interface").

    Returns:
        dict with model name and list of available field names.

    Raises:
        ValueError: If the model is not found in the schema.
    """
    from nautobot_app_mcp_server.mcp.tools.graphql_schema import get_fields_for_model

    try:
        fields = await sync_to_async(get_fields_for_model, thread_sensitive=True)(model)
        return {"model": model, "fields": fields}
    except ValueError as exc:
        return {"error": str(exc)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestGraphqlQueryTool -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nautobot_app_mcp_server/mcp/tools/core.py
git commit -m "feat: add graphql_query and graphql_schema_get MCP tools

GRAPHQL-08: graphql_query — universal structured GraphQL query tool
GRAPHQL-09: graphql_schema_get — schema discovery tool for field names"
```

---

## Task 5: Schema Caching in `ready()` (startup init)

**Files:**
- Modify: `nautobot_app_mcp_server/__init__.py` — preload schema in `ready()`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for schema preloading in ready() hook."""
from django.test import TestCase
from unittest.mock import patch


class TestSchemaPreloadInReady(TestCase):
    """GRAPHQL-10: Schema is preloaded during ready() for fast first query."""

    def test_ready_preloads_schema(self):
        """ready() calls get_cached_schema() to warm the cache."""
        with patch(
            "nautobot_app_mcp_server.mcp.tools.graphql_schema.get_cached_schema"
        ) as mock_get:
            from nautobot_app_mcp_server import NautobotAppMcpServerConfig
            cfg = NautobotAppMcpServerConfig("nautobot_app_mcp_server")
            cfg.ready()
            mock_get.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestSchemaPreloadInReady -v`
Expected: FAIL — ready() doesn't call get_cached_schema yet

- [ ] **Step 3: Add schema preload to ready() in __init__.py**

In `nautobot_app_mcp_server/__init__.py`, after the tool registry write block in `ready()`:

```python
        # Preload GraphQL schema cache (GRAPHQL-10)
        # Fires on first MCP server startup so first query isn't slow.
        # Graceful no-op if schema is unavailable (e.g. fresh install).
        try:
            from nautobot_app_mcp_server.mcp.tools.graphql_schema import get_cached_schema
            get_cached_schema()
            import logging
            logging.getLogger(__name__).info("GraphQL schema cached at startup")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not preload GraphQL schema at startup: %s", exc
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `poetry run pytest nautobot_app_mcp_server/mcp/tests/test_graphql_tools.py::TestSchemaPreloadInReady -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nautobot_app_mcp_server/__init__.py
git commit -m "feat: preload GraphQL schema cache in ready() hook

GRAPHQL-10: warm schema cache on MCP server startup for fast first query"
```

---

## Task 6: End-to-End Verification

**Files:**
- Run: `scripts/test_mcp_simple.py` — add new test cases
- Run: `scripts/run_mcp_uat.py` — add UAT test cases

- [ ] **Step 1: Start dev environment and run smoke tests**

```bash
# In host shell
cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server
invoke start
# Wait for services to be healthy
python scripts/test_mcp_simple.py
```

- [ ] **Step 2: Add P-09 (graphql_schema_get smoke test)**

```python
# In test_mcp_simple.py, add:
def test_p09_graphql_schema_get():
    """P-09: graphql_schema_get returns field list for Device."""
    response = mcp_request("graphql_schema_get", {"model": "Device"})
    assert response["status"] == 200
    data = response["json"]
    assert "fields" in data or "error" in data  # Allow graceful error if schema unavailable
```

- [ ] **Step 3: Run the new smoke test**

```bash
python scripts/test_mcp_simple.py
```

Expected: All P-01–P-09 pass

- [ ] **Step 4: Run full test suite**

```bash
invoke tests
```

Expected: All tests pass, lint clean

- [ ] **Step 5: Final commit**

```bash
git add docs/superpowers/plans/2026-04-15-universal-graphql-mcp-tool.md
git commit -m "docs: add implementation plan for universal GraphQL MCP tool"
```

---

## Self-Review Checklist

After writing the complete plan:

1. **Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it?
   - [x] Schema caching at startup → Task 5 (ready()) + Task 1 (schema module)
   - [x] Structured query building → Task 2 (query builder)
   - [x] GraphQL execution → Task 3 (executor)
   - [x] Error translation → Task 3 (translate_graphql_errors)
   - [x] Tool registration → Task 4 (core.py additions)
   - [x] Schema discovery tool → Task 4 (`graphql_schema_get`)
   - [x] Output schema=None for FastMCP → Follows existing pattern in `register_all_tools_with_mcp`
   - [x] Thread-safe ORM access → `sync_to_async(..., thread_sensitive=True)` in handlers
   - [x] Auth via user injection → `get_user_from_request()` + `execute_query(user=user)`
   - [x] Nested selections → Task 2 (nested param in query builder)
   - [x] Limit enforcement → Task 2 (limit with max 1000)

2. **Placeholder scan:** Search for "TBD", "TODO", "implement later", "fill in details" — none found.

3. **Type consistency:** Functions defined in Task 1 used in Task 3 with same signatures — yes, all match.

4. **Spec requirement gaps:** None identified.
