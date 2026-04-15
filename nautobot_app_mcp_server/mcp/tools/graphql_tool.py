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
    return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)()


def _sync_graphql_introspect() -> str:
    """Synchronous SDL generator — accesses Nautobot's graphene Schema."""
    from graphene_django.settings import graphene_settings
    from graphql import print_schema

    schema = graphene_settings.SCHEMA
    return print_schema(schema.graphql_schema)
