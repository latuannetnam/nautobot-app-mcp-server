"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token nbapikey_xxx" format
    3. Look up Nautobot Token object → return User
    4. Missing / invalid token → return AnonymousUser with log warning

PIT-16: Always use ctx.request_context.request (MCP SDK request object),
NOT Django's HttpRequest. PIT-10: Log WARNING on missing token,
DEBUG on invalid token.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Context as ToolContext

logger = logging.getLogger(__name__)

# Token prefix used by Nautobot API tokens
TOKEN_PREFIX = "nbapikey_"  # noqa: S105


def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token nbapikey_xxx`` header.
    Falls back to ``AnonymousUser`` (never raises) — empty querysets returned.

    Args:
        ctx: FastMCP ToolContext, providing access to the MCP request object.

    Returns:
        nautobot.users.models.User if authenticated, otherwise
        django.contrib.auth.models.AnonymousUser.

    Logging (D-22, PIT-10):
        - Missing Authorization header → ``logger.warning``
        - Invalid / malformed token     → ``logger.debug``
    """
    from django.contrib.auth.models import AnonymousUser

    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")

    if not auth_header:
        logger.warning("MCP: No auth token, falling back to anonymous user")
        return AnonymousUser()

    if not auth_header.startswith("Token "):
        logger.debug("MCP: Invalid auth token format (not a Token prefix)")
        return AnonymousUser()

    token_key = auth_header[6:]  # Strip "Token "

    if not token_key.startswith(TOKEN_PREFIX):
        logger.debug("MCP: Invalid auth token (not a Nautobot nbapikey token)")
        return AnonymousUser()

    # Look up the Nautobot API token
    real_token_key = token_key[len(TOKEN_PREFIX):]

    try:
        from nautobot.users.models import Token

        token = Token.objects.select_related("user").get(key=real_token_key)
        return token.user
    except Exception:  # noqa: BLE001 — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()
