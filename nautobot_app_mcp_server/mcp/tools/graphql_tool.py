"""GraphQL query tool — parse-then-execute with security validation rules."""

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
    return await sync_to_async(_sync_graphql_query, thread_sensitive=True)(query=query, variables=variables, user=user)


def _sync_graphql_query(query: str, variables: dict | None, user) -> dict[str, Any]:
    """Synchronous GraphQL query executor — parse → validate → execute pattern.

    Replaces `nautobot.core.graphql.execute_query()` with three distinct phases:
      1. Auth guard (user=None check — preserved from Phase 14)
      2. parse() — raises GraphQLError on syntax error → HTTP 200 with errors dict
      3. validate() — runs custom security rules before execution
      4. execute() — runs the validated document against the schema

    All imports are lazy (inside the function body) to avoid Django setup issues.
    """
    # Lazy imports — must be inside function to avoid Django setup conflicts
    from django.test.client import RequestFactory
    from graphene_django.settings import graphene_settings
    from graphql import ExecutionResult
    from graphql.validation import specified_rules

    from nautobot_app_mcp_server.mcp.tools import graphql_validation

    # Initialise _graphql lazily once (module-level so tests can patch the attribute)
    import nautobot_app_mcp_server.mcp.tools.graphql_tool as _self
    if not hasattr(_self, "_graphql") or _self._graphql is None:  # pragma: no cover
        import graphql as _graphql_module
        _self._graphql = _graphql_module

    # Step 1: Auth guard (existing — preserved from Phase 14)
    # Covers both user=None and AnonymousUser instances
    if user is None or (hasattr(user, "is_anonymous") and user.is_anonymous):
        return {"data": None, "errors": [{"message": "Authentication required"}]}

    # Step 2: Syntax validation — parse() raises GraphQLError on bad syntax
    try:
        document = graphql_validation.parse(query)
    except graphql_validation.GraphQLError as e:
        return ExecutionResult(data=None, errors=[e]).formatted

    # Step 3: Security validation — depth + complexity limits (stubs in Wave 1)
    schema = graphene_settings.SCHEMA.graphql_schema
    validation_errors = graphql_validation.validate(
        schema=schema,
        document_ast=document,
        rules=[graphql_validation.MaxDepthRule, graphql_validation.QueryComplexityRule, *specified_rules],
    )
    if validation_errors:
        return ExecutionResult(data=None, errors=validation_errors).formatted

    # Step 4: Execute — build Django request as context value
    request = RequestFactory().post("/graphql/")
    request.user = user
    if variables:
        result = _self._graphql.execute(
            schema=schema,
            document=document,
            context_value=request,
            variable_values=variables,
        )
    else:
        result = _self._graphql.execute(schema=schema, document=document, context_value=request)

    return result.formatted


@register_tool(
    name="graphql_introspect",
    description=(
        "Return the GraphQL schema as an SDL string. " "Auth token required — anonymous callers receive a tool error."
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
    return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)()


def _sync_graphql_introspect() -> str:
    """Synchronous SDL generator — accesses Nautobot's graphene Schema."""
    from graphene_django.settings import graphene_settings
    from graphql import print_schema

    schema = graphene_settings.SCHEMA
    return print_schema(schema.graphql_schema)
