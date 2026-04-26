"""GraphQL validation rules — depth limit, complexity limit, security helpers."""

from __future__ import annotations

from typing import Any

from graphql import (
    SKIP,
    DocumentNode,
    FieldNode,
    FragmentSpreadNode,
    GraphQLError,
    InlineFragmentNode,
    Node,
    validate,
)
from graphql.validation import ValidationContext, ValidationRule

MAX_DEPTH = 8
MAX_COMPLEXITY = 1000
# __typename is excluded from depth (adds no nesting) but included in complexity
# (it is a field and consumes execution resources) per design decision D-02.
_INTROSPECTION_FIELDS = frozenset({"__schema", "__type", "__typename"})

__all__ = ["MaxDepthRule", "QueryComplexityRule", "validate", "parse"]


def parse(query: str) -> DocumentNode:
    """Parse a GraphQL query string.

    Wraps graphql-core's parse() so tests can patch at the module level.
    """
    from graphql import parse as _parse

    return _parse(query)


class MaxDepthRule(ValidationRule):
    """ASTValidationRule that rejects queries with field nesting depth > MAX_DEPTH.

    Traverses the query AST and reports an error when any field's nesting depth
    exceeds MAX_DEPTH (default 8). Introspection fields (__schema, __type,
    __typename) are excluded from the depth count per D-02 from CONTEXT.md.

    Fragment cycles are handled via a _visited_fragments dict, following the
    same pattern as graphql-core's own MaxIntrospectionDepthRule.
    """

    def __init__(self, context: ValidationContext) -> None:  # noqa: D107
        super().__init__(context)
        self._visited_fragments: dict[str, None] = {}

    def _get_depth(self, node: Node, depth: int = 0) -> int:
        """Return maximum nesting depth below this node."""
        selection_set = getattr(node, "selection_set", None)
        if selection_set is None:
            return depth

        max_child_depth = depth + 1
        for selection in selection_set.selections:
            if isinstance(selection, FragmentSpreadNode):
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
                child_depth = self._get_depth(selection, depth + 1)
                max_child_depth = max(max_child_depth, child_depth)
        return max_child_depth

    def enter_field(self, node: FieldNode, *_args: Any) -> Any:
        """Called for each field; report error if depth exceeds MAX_DEPTH."""
        if node.name.value in _INTROSPECTION_FIELDS:
            return None  # introspection fields do not count toward depth

        depth = self._get_depth(node, depth=0)
        if depth > MAX_DEPTH:
            self.report_error(
                GraphQLError(
                    f"Query depth {depth} exceeds maximum allowed depth of {MAX_DEPTH}",
                    nodes=[node],
                )
            )
            return SKIP
        return None


def _count_complexity(node: Node) -> int:
    """Count total field selections across all paths (simple field-count heuristic).

    Each FieldNode contributes 1 to the complexity score. Fragments and inline
    fragments are traversed recursively. Introspection fields are included
    (they are still fields and consume execution resources).
    """
    selection_set = getattr(node, "selection_set", None)
    if selection_set is None:
        return 1  # scalar leaf = 1 field

    total = 0
    for selection in selection_set.selections:
        if isinstance(selection, FragmentSpreadNode):
            total += 1  # fragment spread itself counts as a selection
        elif isinstance(selection, InlineFragmentNode):
            total += _count_complexity(selection)
        else:
            total += _count_complexity(selection)
    return total


class QueryComplexityRule(ValidationRule):
    """ASTValidationRule that rejects queries with complexity > MAX_COMPLEXITY.

    Counts every FieldNode in the query AST (each contributes 1 to complexity)
    via _count_complexity(). Rejects at complexity > 1000 (MAX_COMPLEXITY).
    Uses enter_document so the count is computed once per query, not per-field.
    """

    def enter_document(self, node: DocumentNode, *_args: Any) -> Any:
        # DocumentNode.definitions[0] is the OperationDefinitionNode (query/mutation/subscription)
        # which has selection_set. DocumentNode itself has no selection_set, so we must
        # traverse to the operation definition.
        if not node.definitions:
            return None
        operation = node.definitions[0]
        complexity = _count_complexity(operation)
        if complexity > MAX_COMPLEXITY:
            self.report_error(
                GraphQLError(
                    f"Query complexity {complexity} exceeds maximum allowed complexity of {MAX_COMPLEXITY}",
                    nodes=[node],
                )
            )
            return SKIP
        return None
