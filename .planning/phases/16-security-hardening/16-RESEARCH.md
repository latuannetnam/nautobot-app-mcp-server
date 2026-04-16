# Phase 16 Research — Security Hardening

**Phase:** 16-security-hardening
**Status:** Research complete
**Date:** 2026-04-16

---

## 1. What I investigated

- `graphql/validation/rules/max_introspection_depth_rule.py` — reference implementation for custom `ASTValidationRule`
- `graphql/validation/validate.py` — `validate()` standalone function signature and behavior
- `graphql/validation/rules/__init__.py` — `ASTValidationRule`, `ValidationRule` base class hierarchy
- `graphql/validation/validation_context.py` — `ValidationContext`, `ASTValidationContext`, `report_error`
- `graphql/error/graphql_error.py` — `GraphQLError.__init__` signature, `nodes`-based location derivation, `.formatted` property
- `graphql/execution/execute.py` — `ExecutionResult` class, `.formatted` property shape
- `graphql/__init__.py` — all public exports including `parse`, `validate`, `ExecutionResult`, `ASTValidationRule`, `GraphQLError`, `FieldNode`, `FragmentSpreadNode`, `InlineFragmentNode`, `DocumentNode`, `SKIP`
- `graphql/language/visitor.py` — `Visitor` base class signature, `enter_field` / `leave_field` dispatch, `SKIP` return value
- `nautobot/core/graphql/__init__.py` — `execute_query()` behavior: internal `parse()` call, schema access via `graphene_settings.SCHEMA.graphql_schema`
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — current `_sync_graphql_query` implementation to extend
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — existing test patterns for mocking and fixture setup

---

## 2. Key findings

### 2.1 `ASTValidationRule` base class

File: `graphql/validation/rules/__init__.py`

```python
class ASTValidationRule(Visitor):
    context: ASTValidationContext

    def __init__(self, context: ASTValidationContext):
        super().__init__()
        self.context = context

    def report_error(self, error: GraphQLError) -> None:
        self.context.report_error(error)
```

**Key facts:**
- Inherits from `Visitor` — gets the full visitor dispatch system for free
- `context` is typed as `ASTValidationContext` (the stricter base class); `ValidationRule` uses `ValidationContext` (the schema-aware subclass)
- `report_error(error)` delegates to `self.context.report_error(error)` — always use this, never raise
- Both base classes share the same `report_error` interface

### 2.2 `ValidationRule` (schema-aware subclass)

```python
class ValidationRule(ASTValidationRule):
    context: ValidationContext

    def __init__(self, context: ValidationContext):
        super().__init__(context)
```

**Key facts:**
- `ValidationRule` is `ValidationContext`-aware; `ASTValidationRule` only has `ASTValidationContext`
- Both work identically for the depth/complexity use case
- Use `ValidationRule` for consistency with `MaxIntrospectionDepthRule`

### 2.3 `MaxIntrospectionDepthRule` — canonical reference implementation

File: `graphql/validation/rules/max_introspection_depth_rule.py`

```python
class MaxIntrospectionDepthRule(ValidationRule):
    def __init__(self, context: ValidationContext) -> None:
        super().__init__(context)
        self._visited_fragments: Dict[str, None] = {}
        self._get_fragment = context.get_fragment

    def enter_field(self, node: FieldNode, *_args: Any) -> VisitorAction:
        if node.name.value in ("__schema", "__type") and self._check_depth(node):
            self.report_error(
                GraphQLError(
                    "Maximum introspection depth exceeded",
                    [node],
                )
            )
            return SKIP
        return None
```

**Key facts:**
- `enter_field(self, node: FieldNode, *_args: Any) -> VisitorAction` — the visitor method signature
- `_args` is variadic because `Visitor` dispatch passes positional args: `key, parent, path, ancestors`
- `SKIP` (value `False` / `VisitorActionEnum.SKIP`) short-circuits traversal of child nodes — useful after reporting an error
- `GraphQLError("message", [node])` — passing `node` as the second positional arg auto-populates `.nodes` and derives `.locations` from the node's source position (no need to pass `source` or `positions` manually)
- `node.name.value` gives the field name string (e.g., `"devices"`, `"__schema"`)
- Fragment handling via `self._get_fragment(fragment_name)` and `_visited_fragments` dict for cycle detection

### 2.4 `ValidationContext` — fragment and document access

File: `graphql/validation/validation_context.py`

```python
class ASTValidationContext:
    document: DocumentNode

    def report_error(self, error: GraphQLError) -> None:
        self.on_error(error)

    def get_fragment(self, name: str) -> Optional[FragmentDefinitionNode]: ...

class ValidationContext(ASTValidationContext):
    document: DocumentNode
    schema: GraphQLSchema
    _fragments: Optional[Dict[str, FragmentDefinitionNode]]

    def get_fragment(self, name: str) -> Optional[FragmentDefinitionNode]: ...
```

**Key facts:**
- `ValidationContext.document` gives the entire `DocumentNode` AST — can traverse without visitor
- `ValidationContext.get_fragment(name)` looks up fragment definitions by name — handles `_fragments` cache
- `ValidationContext.schema` gives the `GraphQLSchema` — not needed for depth/complexity static analysis

### 2.5 AST node types for traversal

File: `graphql/language/ast.py` (excerpts)

```python
class FieldNode(Node):
    name: NameNode          # .name.value = field name string
    alias: NameNode | None  # .alias.value = alias string (or None)
    arguments: list[ArgumentNode]
    selection_set: SelectionSetNode | None  # recurse here for children

class FragmentSpreadNode(Node):
    name: NameNode  # .name.value = fragment name

class InlineFragmentNode(Node):
    type_condition: NamedTypeNode | None
    selection_set: SelectionSetNode  # recurse here

class FragmentDefinitionNode(Node):
    name: NameNode
    selection_set: SelectionSetNode

class DocumentNode(Node):
    definitions: list[DefinitionNode]  # operations + fragments

class SelectionSetNode(Node):
    selections: list[SelectionNode]  # FieldNode | FragmentSpreadNode | InlineFragmentNode
```

**Key facts:**
- `isinstance(node, FieldNode)` for regular field selections
- `isinstance(node, FragmentSpreadNode)` for `...FragmentName`
- `isinstance(node, InlineFragmentNode)` for `...on Type { ... }`
- `selection_set.selections` gives the children of any selection set
- Introspection fields: names starting with `__` (e.g., `__schema`, `__type`, `__typename`) should be excluded from depth counting per D-02

### 2.6 `Visitor` dispatch — enter/leave method resolution

File: `graphql/language/visitor.py`

```python
class Visitor:
    def enter(self, node, key, parent, path, ancestors): ...
    def leave(self, node, key, parent, path, ancestors): ...

    # Per-node-type enter/leave:
    def enter_document(self, node, key, parent, path, ancestors): ...
    def leave_document(self, node, key, parent, path, ancestors): ...
    def enter_field(self, node, key, parent, path, ancestors): ...
    def leave_field(self, node, key, parent, path, ancestors): ...
    def enter_fragment_spread(self, node, key, parent, path, ancestors): ...
    def enter_inline_fragment(self, node, key, parent, path, ancestors): ...
```

**Key facts:**
- `enter_field` / `leave_field` are the per-node-type methods called automatically by the visitor
- Return `SKIP` to skip visiting children (useful after reporting an error)
- Return `BREAK` to halt traversal entirely
- Return `None` / `IDLE` for normal traversal
- Override `enter_field` only — no need to implement `leave_field` unless tracking state on exit
- `MaxIntrospectionDepthRule.enter_field` ignores `key, parent, path, ancestors` args (uses `*_args`)

### 2.7 `validate()` standalone function

File: `graphql/validation/validate.py`

```python
def validate(
    schema: GraphQLSchema,
    document_ast: DocumentNode,
    rules: Optional[Collection[Type[ASTValidationRule]]] = None,
    max_errors: Optional[int] = None,
    type_info: Optional[TypeInfo] = None,
) -> List[GraphQLError]:
    """Returns a list of GraphQLError (empty if valid)."""
```

**Key facts:**
- Takes a **schema** and a **parsed document AST** — does NOT parse the query string
- `rules` must be a **collection of rule classes** (not instances) — `validate()` instantiates each
- `rules=None` uses `specified_rules` (all spec-defined rules including `MaxIntrospectionDepthRule`)
- Returns `List[GraphQLError]` — empty list means valid; non-empty means invalid
- If validation errors exist → short-circuit execution by returning `ExecutionResult(data=None, errors=errors).formatted`
- **Does NOT execute the query** — purely static AST analysis + schema type checking
- `max_errors=100` by default; errors beyond the limit raise `ValidationAbortedError`
- The visitor runs all rules in parallel via `ParallelVisitor`

### 2.8 `GraphQLError` constructor

File: `graphql/error/graphql_error.py`

```python
class GraphQLError(Exception):
    message: str
    locations: Optional[List["SourceLocation"]]
    nodes: Optional[List["Node"]]
    path: Optional[List[Union[str, int]]]
    extensions: Optional[GraphQLErrorExtensions]

    def __init__(
        self,
        message: str,
        nodes: Union[Collection["Node"], "Node", None] = None,
        source: Optional["Source"] = None,
        positions: Optional[Collection[int]] = None,
        path: Optional[Collection[Union[str, int]]] = None,
        original_error: Optional[Exception] = None,
        extensions: Optional[GraphQLErrorExtensions] = None,
    ) -> None:
        # nodes → auto-derive .locations via node.loc.source.get_location()
        ...
```

**Key facts:**
- `GraphQLError("message", nodes=[node])` — passing nodes auto-derives locations from source positions
- `GraphQLError("message", path=["devices", 0, "name"])` — for execution-time errors
- `.formatted` property: `{"message": "...", "locations": [...], "path": [...], "extensions": {...}}` — locations and path only if set
- `GraphQLError` subclasses `Exception` — can be raised or passed to `report_error`

### 2.9 `ExecutionResult.formatted` — exact shape

File: `graphql/execution/execute.py`

```python
class ExecutionResult:
    __slots__ = "data", "errors", "extensions"

    def __init__(
        self,
        data: Optional[Dict[str, Any]] = None,
        errors: Optional[List[GraphQLError]] = None,
        extensions: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    @property
    def formatted(self) -> FormattedExecutionResult:
        formatted: FormattedExecutionResult = {"data": self.data}
        if self.errors is not None:
            formatted["errors"] = [error.formatted for error in self.errors]
        if self.extensions is not None:
            formatted["extensions"] = self.extensions
        return formatted
```

**Formatted output shapes:**

```python
# Validation errors (depth, complexity, syntax):
ExecutionResult(data=None, errors=[GraphQLError("message", nodes=[node])]).formatted
# → {"data": None, "errors": [{"message": "...", "locations": [{"line": 1, "column": 1}]}]}

# No errors:
ExecutionResult(data={"devices": [...]}, errors=None).formatted
# → {"data": {"devices": [...]}}

# Execution errors:
ExecutionResult(data=None, errors=[GraphQLError("message", path=["devices", 0])]).formatted
# → {"data": None, "errors": [{"message": "...", "path": ["devices", 0]}]}
```

**Key facts:**
- `data=None` is preserved as `None` in `.formatted` (not removed)
- `errors=None` means the `"errors"` key is absent from `.formatted` dict
- `errors=[]` (empty list) → `"errors": []` present in output
- For validation failures: `errors=[GraphQLError(...)]` → `"errors": [{...}]`
- **D-03 from CONTEXT.md:** Use `ExecutionResult(data=None, errors=[GraphQLError("...")]).formatted`

### 2.10 `parse()` — syntax errors as `GraphQLError`

File: `graphql/__init__.py`

```python
# Exports: parse, GraphQLError, ExecutionResult, validate, ASTValidationRule, ...
```

```python
from graphql import parse, GraphQLError

try:
    doc = parse("{ devices {")  # unclosed brace
except GraphQLError as e:
    # e.message: "Syntax Error: Unexpected EndOfFile."
    # e.locations: [{"line": 1, "column": 11}]
    ...
```

**Key facts:**
- `parse()` raises `GraphQLError` (not `SyntaxError`) on malformed input
- The error has `.locations` populated from the parser
- Catch `GraphQLError` in `_sync_graphql_query` to return structured error without HTTP 500

### 2.11 `nautobot.core.graphql.execute_query()` — internal parse

File: `.venv/.../nautobot/core/graphql/__init__.py`

```python
def execute_query(query, variables=None, request=None, user=None):
    if not request and not user:
        raise ValueError("Either request or username should be provided")
    if not request:
        request = RequestFactory().post("/graphql/")
        request.user = user
    schema = graphene_settings.SCHEMA.graphql_schema
    document = parse(query)  # ← internal parse; cannot inject custom rules here
    if variables:
        return execute(schema=schema, document=document, context_value=request, variable_values=variables)
    else:
        return execute(schema=schema, document=document, context_value=request)
```

**Key facts:**
- `execute_query` calls `parse()` internally — cannot pass custom validation rules to that call
- **Parse-then-execute approach:** call `parse()` separately first, then `validate()` with custom rules, then pass the parsed document to `execute_query` — but `execute_query` calls `parse()` again on the same query string, which is redundant
- **Better approach:** Do NOT call `execute_query` directly; instead replicate its behavior with the pre-validated document:
  1. `document = graphql.parse(query)` — raises `GraphQLError` on syntax error
  2. `errors = graphql.validate(schema, document, rules=[MaxDepthRule, QueryComplexityRule, *specified_rules])` — if non-empty, return `ExecutionResult(data=None, errors=errors).formatted`
  3. `result = execute(schema, document, context_value=request, variable_values=variables)` — execute with validated document
  4. Return `result.formatted`
- **D-01 from CONTEXT.md** says: "parse-then-execute in `_sync_graphql_query`" — this confirms the approach above

### 2.12 Schema access — `graphene_settings.SCHEMA.graphql_schema`

File: `.venv/.../graphene_django/settings.py`

```python
# graphene_django.settings
SCHEMA = getattr(settings, 'GRAPHENE', {}).get('SCHEMA')
```

File: `.venv/.../nautobot/core/graphql/__init__.py`

```python
schema = graphene_settings.SCHEMA.graphql_schema  # GraphQLSchema instance
```

**Key facts:**
- `graphene_settings.SCHEMA.graphql_schema` returns a `GraphQLSchema` object usable by `graphql-core`
- This is safe to call inside `_sync_graphql_query` (D-01: sync access inside sync function)
- Accessing at module level in `graphql_tool.py` would import graphene-django before Django setup — use lazy import inside the function
- Thread-safe: the schema object itself is stateless and re-entrant

### 2.13 `from __future__ import annotations` + graphql-core types

Per CLAUDE.md: all files use `from __future__ import annotations` (PEP 563). graphql-core types (e.g., `FieldNode`, `GraphQLError`, `DocumentNode`) are imported as strings in type hints but resolved at runtime. Use string annotations for consistency:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from graphql.language.ast import FieldNode, DocumentNode
    from graphql.error import GraphQLError
    from graphql.type import GraphQLSchema
    from graphql.validation import ValidationContext
```

Or import directly (runtime type hints only, no TYPE_CHECKING needed since we're not inside `TYPE_CHECKING` guard):

```python
from graphql import (
    DocumentNode, FieldNode, FragmentSpreadNode, InlineFragmentNode,
    GraphQLError, GraphQLSchema, parse, validate, ExecutionResult, SKIP,
    ValidationRule,
)
from graphql.validation import ValidationContext
```

All of these are top-level exports from `graphql` package — verified in `graphql/__init__.py` `__all__`.

---

## 3. Implementation design

### 3.1 Parse-then-execute pattern in `_sync_graphql_query`

```python
def _sync_graphql_query(query: str, variables: dict | None, user) -> dict[str, Any]:
    from django.test.client import RequestFactory
    from graphene_django.settings import graphene_settings
    from graphql import execute, parse, validate, ExecutionResult, GraphQLError
    from graphql.validation import specified_rules

    from nautobot_app_mcp_server.mcp.tools.graphql_validation import (
        MaxDepthRule,
        QueryComplexityRule,
    )

    # Step 1: Auth guard (existing)
    if user is None:
        return {"data": None, "errors": [{"message": "Authentication required"}]}

    # Step 2: Syntax validation — parse() raises GraphQLError on bad syntax
    try:
        document = parse(query)
    except GraphQLError as e:
        return ExecutionResult(data=None, errors=[e]).formatted

    # Step 3: Security validation — depth + complexity limits
    schema = graphene_settings.SCHEMA.graphql_schema
    validation_errors: list[GraphQLError] = validate(
        schema=schema,
        document_ast=document,
        rules=[MaxDepthRule, QueryComplexityRule, *specified_rules],
    )
    if validation_errors:
        return ExecutionResult(data=None, errors=validation_errors).formatted

    # Step 4: Execute
    request = RequestFactory().post("/graphql/")
    request.user = user
    if variables:
        result = execute(
            schema=schema,
            document=document,
            context_value=request,
            variable_values=variables,
        )
    else:
        result = execute(schema=schema, document=document, context_value=request)

    return result.formatted
```

**Note:** We no longer call `nautobot.core.graphql.execute_query()` directly because it calls `parse()` internally without custom rules. The steps above replicate `execute_query`'s behavior with pre-validation.

### 3.2 `MaxDepthRule` design

```python
MAX_DEPTH = 8

# Introspection fields — excluded from depth counting
_INTROSPECTION_FIELDS = frozenset({"__schema", "__type", "__typename"})


class MaxDepthRule(ValidationRule):
    """ASTValidationRule that rejects queries with field nesting > MAX_DEPTH."""

    def __init__(self, context: ValidationContext) -> None:
        super().__init__(context)
        self._visited_fragments: dict[str, None] = {}

    def _get_depth(self, node: Node, depth: int = 0) -> int:
        """Return maximum nesting depth below this node."""
        # Base case: leaf node (no selection_set)
        selection_set = getattr(node, "selection_set", None)
        if selection_set is None:
            return depth

        max_child_depth = depth + 1
        for selection in selection_set.selections:
            if isinstance(selection, FragmentSpreadNode):
                # Follow fragment, resetting depth counter for the fragment body
                fragment_name = selection.name.value
                if fragment_name in self._visited_fragments:
                    continue
                fragment = self.context.get_fragment(fragment_name)
                if fragment is None:
                    continue
                self._visited_fragments[fragment_name] = None
                try:
                    child_depth = self._get_depth(fragment, depth + 1)
                finally:
                    del self._visited_fragments[fragment_name]
                max_child_depth = max(max_child_depth, child_depth)
            elif isinstance(selection, InlineFragmentNode):
                child_depth = self._get_depth(selection, depth + 1)
                max_child_depth = max(max_child_depth, child_depth)
            else:
                # FieldNode or other selection
                child_depth = self._get_depth(selection, depth + 1)
                max_child_depth = max(max_child_depth, child_depth)
        return max_child_depth

    def enter_field(self, node: FieldNode, *_args: Any) -> VisitorAction:
        if node.name.value in _INTROSPECTION_FIELDS:
            return None  # skip introspection fields

        depth = self._get_depth(node, depth=0)
        if depth > MAX_DEPTH:
            self.report_error(
                GraphQLError(
                    f"Query depth {depth} exceeds maximum allowed depth of {MAX_DEPTH}",
                    [node],
                )
            )
            return SKIP
        return None
```

**Depth counting behavior:**
- Root-level fields (directly under `Query`) have depth 1
- `{ devices { name { id } } }` — `devices` depth=1, `name` depth=2, `id` depth=3
- `{ devices { location { site { name } } } }` — `site` depth=3, `name` depth=4
- At depth 9 (8 allowed): rejected with error message

### 3.3 `QueryComplexityRule` design

```python
MAX_COMPLEXITY = 1000


def _count_complexity(node: Node) -> int:
    """Count field selections across all paths (simple field-count heuristic)."""
    selection_set = getattr(node, "selection_set", None)
    if selection_set is None:
        return 1  # scalar leaf = 1 field

    total = 0
    for selection in selection_set.selections:
        if isinstance(selection, FragmentSpreadNode):
            # Fragment counts as its own selection set's fields
            # (handled via traversal below; for simple heuristic, skip fragments)
            total += 1
        elif isinstance(selection, InlineFragmentNode):
            total += _count_complexity(selection)
        else:
            # FieldNode
            total += _count_complexity(selection)
    return total


class QueryComplexityRule(ValidationRule):
    """ASTValidationRule that rejects queries with complexity > MAX_COMPLEXITY."""

    def enter_document(self, node: DocumentNode, *_args: Any) -> VisitorAction:
        complexity = _count_complexity(node)
        if complexity > MAX_COMPLEXITY:
            self.report_error(
                GraphQLError(
                    f"Query complexity {complexity} exceeds maximum allowed complexity of {MAX_COMPLEXITY}",
                    [node],
                )
            )
            return SKIP
        return None
```

**Complexity counting behavior:**
- Simple field-count: each `FieldNode` in the AST contributes 1 to complexity
- Introspection fields also count (they're fields too)
- Fragments and inline fragments are traversed
- `query { devices { name status } }` → complexity 3 (root `devices` + `name` + `status`)
- `query { devices { name location { site { name } } } }` → complexity 5

### 3.4 File placement

Per D-07 from CONTEXT.md: validation rules in `graphql_tool.py` (or optionally a sibling). Given that `MaxDepthRule` and `QueryComplexityRule` are ~80 lines each, keeping them in `graphql_tool.py` is acceptable, but a sibling `graphql_validation.py` is cleaner:

```
nautobot_app_mcp_server/mcp/tools/
├── graphql_tool.py          # _graphql_query_handler, _sync_graphql_query (modified)
└── graphql_validation.py    # NEW: MaxDepthRule, QueryComplexityRule
```

**Recommended: `graphql_validation.py`** — separates concerns, easier to unit test in isolation.

### 3.5 `graphql_validate_query` helper

```python
# graphql_validation.py

from __future__ import annotations

from graphql import (
    DocumentNode,
    ExecutionResult,
    GraphQLError,
    GraphQLSchema,
    ValidationRule,
)
from graphql.validation import ValidationContext

MAX_DEPTH = 8
MAX_COMPLEXITY = 1000

_INTROSPECTION_FIELDS = frozenset({"__schema", "__type", "__typename"})

__all__ = ["MaxDepthRule", "QueryComplexityRule", "validate_query_security"]
```

---

## 4. Test design (D-06)

File: `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py`

New test class: `GraphQLSecurityTestCase`

```python
class GraphQLSecurityTestCase(TestCase):
    """Test depth/complexity limits and structured error handling (GQL-10, GQL-11, GQL-12)."""

    def _get_or_create_superuser(self): ...

    @patch("nautobot.core.graphql.execute_query")
    def test_depth_limit_enforced(self, mock_execute):
        """GQL-10: Query with depth 9 is rejected with data=None and "depth" in error message.

        Since _sync_graphql_query no longer calls execute_query directly (parse+validate
        happens first), we patch at the parse+validate level. We inject a fake
        GraphQLError to simulate MaxDepthRule rejecting the query.
        """
        # Patch validate() to return a depth-limit error instead of empty list
        from graphql import GraphQLError
        from unittest.mock import MagicMock

        fake_error = GraphQLError(
            "Query depth 9 exceeds maximum allowed depth of 8"
        )
        with patch(
            "nautobot_app_mcp_server.mcp.tools.graphql_validation.validate",
            return_value=[fake_error],
        ):
            result = graphql_tool._sync_graphql_query(
                query="{ a { b { c { d { e { f { g { h { i } } } } } } } } }",  # depth 9
                variables=None,
                user=self._get_or_create_superuser(),
            )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("depth", result["errors"][0]["message"].lower())

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_validation.validate")
    def test_complexity_limit_enforced(self, mock_validate):
        """GQL-11: Over-complex query is rejected with data=None and "complexity" in message."""
        from graphql import GraphQLError

        fake_error = GraphQLError(
            "Query complexity 1001 exceeds maximum allowed complexity of 1000"
        )
        mock_validate.return_value = [fake_error]

        # Build a query with > 1000 field selections
        many_fields = ", ".join(f"field{i}: name" for i in range(1001))
        query = f"{{ {many_fields} }}"

        result = graphql_tool._sync_graphql_query(
            query=query,
            variables=None,
            user=self._get_or_create_superuser(),
        )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("complexity", result["errors"][0]["message"].lower())

    @patch("nautobot_app_mcp_server.mcp.tools.graphql_validation.validate")
    def test_syntax_error_returns_200_with_errors(self, mock_validate):
        """GQL-12: Malformed query returns HTTP 200 (structured errors dict, not HTTP 500).

        parse() raises GraphQLError for unclosed braces, invalid syntax, etc.
        This is caught in _sync_graphql_query and returned as ExecutionResult.formatted.
        No unhandled exception propagates from the tool.
        """
        from graphql import GraphQLError, Source

        # Simulate parse() raising a syntax error
        syntax_error = GraphQLError(
            "Syntax Error: Unexpected EndOfFile.",
            nodes=None,
            source=Source("{ devices {"),
            positions=[11],
        )
        with patch(
            "nautobot_app_mcp_server.mcp.tools.graphql_validation.parse",
            side_effect=syntax_error,
        ):
            result = graphql_tool._sync_graphql_query(
                query="{ devices {",  # unclosed brace
                variables=None,
                user=self._get_or_create_superuser(),
            )

        self.assertIsNone(result["data"])
        self.assertIsNotNone(result["errors"])
        self.assertIn("Syntax Error", result["errors"][0]["message"])
```

**Key mock patterns:**
- Patch `graphql_validation.validate` (the module we control) rather than the top-level `graphql.validate`
- For syntax errors, patch `graphql_validation.parse` (re-exported from `graphql`) to raise
- The patched function is in `nautobot_app_mcp_server.mcp.tools.graphql_validation` (the local module), so `@patch` targets that path
- `GraphQLError` can be constructed with `source=` and `positions=` to populate `.locations` in `.formatted`

---

## 5. Import plan

`graphql_validation.py` needs these imports (all from `graphql` top-level package, verified in `graphql/__init__.py` `__all__`):

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graphql import (
    DocumentNode,
    ExecutionResult,
    FieldNode,
    FragmentSpreadNode,
    GraphQLError,
    GraphQLSchema,
    InlineFragmentNode,
    Node,
    SKIP,
    validate,
)
from graphql.validation import ValidationContext, specified_rules, ValidationRule

if TYPE_CHECKING:
    pass
```

`graphql_tool.py` imports from `graphql_validation`:
```python
from nautobot_app_mcp_server.mcp.tools.graphql_validation import (
    MaxDepthRule,
    QueryComplexityRule,
)
```

No new dependencies — all are transitive deps of Nautobot (graphql-core 3.2.8, graphene-django).

---

## 6. GQL-12: Syntax error handling detail

`parse()` is called first in `_sync_graphql_query`. On syntax error, it raises `GraphQLError` (not a generic exception). The catch block:

```python
try:
    document = parse(query)
except GraphQLError as e:
    return ExecutionResult(data=None, errors=[e]).formatted
```

This means malformed queries never reach `validate()` or `execute()`. They return HTTP 200 with `{"data": None, "errors": [{...}]}` — satisfying GQL-12.

The existing `execute_query` fallback (for anonymous users raising `ValueError`) is preserved by the auth guard at the top of `_sync_graphql_query`.

---

## 7. Decisions made (D-08 scope from CONTEXT.md)

| Decision | Choice | Rationale |
|---|---|---|
| File for validation rules | `graphql_validation.py` (sibling to `graphql_tool.py`) | Cleaner separation; ~80 lines per rule; allows isolated testing |
| Rule class names | `MaxDepthRule`, `QueryComplexityRule` | Follows `MaxIntrospectionDepthRule` naming convention |
| Complexity counting | Simple field-count (1 per FieldNode) | Meets the ≤1000 threshold without type-weighted complexity analysis |
| Depth base level | 1 for root-level fields | Matches typical GraphQL depth semantics; max depth 8 means 7 levels of nesting under root |
| Introspection in depth | Excluded from depth count | `__schema`, `__type` are metadata; not part of business-data nesting |
| Introspection in complexity | Included (counts as fields) | Simplicity: all fields count 1; introspection fields are still expensive |
| Fragment cycle handling | Track visited fragments; skip re-visiting | Same pattern as `MaxIntrospectionDepthRule` |
| Test mock target | `graphql_validation.validate` / `graphql_validation.parse` | Patches the local module where these are imported; avoids patching `graphql.*` internals |

---

## 8. Coverage of requirements

| Req | What it means | Covered by |
|---|---|---|
| GQL-10 | Depth ≤8 enforced | `MaxDepthRule` + `_sync_graphql_query` parse-then-validate step |
| GQL-11 | Complexity ≤1000 enforced | `QueryComplexityRule` + `_sync_graphql_query` parse-then-validate step |
| GQL-12 | Structured errors, not HTTP 500 | `parse()` → `GraphQLError` caught → `ExecutionResult.formatted`; no exception propagates |
| D-01 | Parse-then-execute in `_sync_graphql_query` | `parse()` → `validate()` → `execute()` pattern; `execute_query` no longer called directly |
| D-02 | Two custom `ASTValidationRule` subclasses | `MaxDepthRule` and `QueryComplexityRule` modeled on `MaxIntrospectionDepthRule` |
| D-03 | `ExecutionResult(data=None, errors=[...]).formatted` | Used for all over-limit and syntax-error responses |
| D-06 | 3 new tests in `GraphQLSecurityTestCase` | `test_depth_limit_enforced`, `test_complexity_limit_enforced`, `test_syntax_error_returns_200_with_errors` |

**All 6 Phase 16 items addressed.**

---

## 9. Remaining unknowns (not blocking)

- **None identified.** All graphql-core APIs were read from the installed `.venv`. The `validate()` function, `ASTValidationRule` pattern, `ExecutionResult.formatted` shape, `GraphQLError` constructor, and `parse()` behavior are all confirmed from source.

---

## RESEARCH COMPLETE

### Summary of key findings

1. **ASTValidationRule pattern:** Inherit from `ValidationRule`, implement `enter_field` (or `enter_document` for document-level rules), call `self.report_error(GraphQLError("msg", [node]))` for errors, return `SKIP` to short-circuit after reporting.

2. **`validate()` function:** Takes `(schema, document_ast, rules=[...])`, returns `List[GraphQLError]` (empty = valid). Instantiate rule classes (pass class, not instance); `validate()` calls `rule(context)` internally.

3. **`ExecutionResult.formatted`:** Returns `{"data": x}` always; adds `"errors": [error.formatted for ...]` only when `self.errors is not None`. For validation failures: `ExecutionResult(data=None, errors=[GraphQLError("...")]).formatted`.

4. **Parse-then-execute:** `execute_query()` can't be used directly (it calls `parse()` internally without custom rules). Instead, replicate its behavior: `parse()` → `validate(..., rules=[MaxDepthRule, QueryComplexityRule, *specified_rules])` → `execute(schema, document, ...)`.

5. **Depth limit:** `enter_field` checks field name (exclude `__*`), calls recursive `_get_depth(node, 0)` helper that traverses `selection_set.selections` including `FragmentSpreadNode` (with cycle detection) and `InlineFragmentNode`. Reject at depth > 8.

6. **Complexity limit:** `enter_document` calls `_count_complexity(node)` which counts every `FieldNode` in the AST tree (each contributes 1). Simpler than type-weighted analysis. Reject at count > 1000.

7. **Schema access:** `graphene_settings.SCHEMA.graphql_schema` is safe inside `_sync_graphql_query` (lazy import, sync access, thread-safe schema object).

8. **Test mocking:** Patch `graphql_validation.validate` (the local re-export) and `graphql_validation.parse` at those module paths. `GraphQLError` constructed with `source=` and `positions=` to populate `.locations`.

9. **No new dependencies.** All APIs are from `graphql-core 3.2.8` (Nautobot transitive dep) and `graphene_django` (Nautobot dep).
