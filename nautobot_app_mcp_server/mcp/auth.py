"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token <hex_key>" format (Nautobot Token keys are 40-char hex)
    3. Check _cached_user on ctx.request_context (AUTH-01 cache)
    4. Cache miss → look up Nautobot Token object → return User (AUTH-02)
    5. Cache the user on ctx.request_context._cached_user
    6. Missing / invalid token → return AnonymousUser with log warning

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

# NOTE: Nautobot Token keys are 40-char hex strings (no "nbapikey_" prefix).


def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token <40-char-hex>`` header.
    Falls back to ``AnonymousUser`` (never raises) — empty querysets returned.

    Caches the authenticated user on ctx.request_context._cached_user (D-13).
    Subsequent calls within the same MCP request batch hit the cache and skip
    the DB lookup.

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

    # Look up the Nautobot API token directly by its 40-char hex key

    # AUTH-01 / AUTH-02: Check request_context cache first (D-13, D-14)
    # _cached_user is stored on the RequestContext dataclass (not ServerSession).
    # If already cached for this token key, return immediately.
    cached_user = getattr(ctx.request_context, "_cached_user", None)
    if cached_user is not None:
        return cached_user

    # Cache miss — look up in DB (AUTH-02)
    try:
        from nautobot.users.models import Token

        token = Token.objects.select_related("user").get(key=token_key)
        user = token.user
    except Exception:  # noqa: BLE001 — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache the user for subsequent calls within this MCP request (D-15)
    ctx.request_context._cached_user = user
    return user
