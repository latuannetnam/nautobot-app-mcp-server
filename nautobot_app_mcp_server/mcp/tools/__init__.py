"""MCP tools package — all core read tools and pagination utilities."""

from __future__ import annotations

# Side-effect import to trigger core tools registration via register_mcp_tool().
# Must come after pagination import since core tools depend on query_utils
# which imports from pagination.
from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401
from nautobot_app_mcp_server.mcp.tools import graphql_tool  # noqa: F401
from nautobot_app_mcp_server.mcp.tools.pagination import (
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_SUMMARIZE,
    PaginatedResult,
    decode_cursor,
    encode_cursor,
    paginate_queryset,
    paginate_queryset_async,
)

__all__ = [
    "LIMIT_DEFAULT",
    "LIMIT_MAX",
    "LIMIT_SUMMARIZE",
    "PaginatedResult",
    "decode_cursor",
    "encode_cursor",
    "paginate_queryset",
    "paginate_queryset_async",
]
