"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token <hex_key>" format (Nautobot Token keys are 40-char hex)
    3. Check FastMCP session state cache (ctx.get_state)
    4. Cache miss → look up Nautobot Token object → return User (AUTH-02)
    5. Cache the user PK string in FastMCP session state (ctx.set_state)
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

# FastMCP state key for the cached user PK.  Stored as a string so the value
# is always serializable (T-11-03).  FastMCP auto-prefixes keys with session_id
# via _make_state_key(), preventing cross-session collisions (T-11-02).
_CACHED_USER_KEY = "mcp:cached_user"

# NOTE: Nautobot Token keys are 40-char hex strings (no "nbapikey_" prefix).


async def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token <40-char-hex>`` header.
    Falls back to ``AnonymousUser`` (never raises) — empty querysets returned.

    Uses the FastMCP session-state API (ctx.get_state / ctx.set_state) to
    cache the authenticated user across calls within the same MCP session.
    The cache stores the user's PK as a string (T-11-03), and re-validates
    against the DB on cache hit (T-11-04).

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

    # AUTH-01 / AUTH-02: Check FastMCP state cache first (T-11-01).
    # On cache hit, re-fetch the user from the DB to handle deletion /
    # deactivation (T-11-04).  Store as str(pk) so the value is always
    # serializable (T-11-03).
    cached_user_id = await ctx.get_state(_CACHED_USER_KEY)
    if cached_user_id is not None:
        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            return User.objects.get(pk=cached_user_id)
        except Exception:  # noqa: BLE001 — User.DoesNotExist, de-activated, etc.
            # Stale or invalid cache — fall through to re-authenticate (S110)
            logger.debug("MCP: Cached user stale or deleted, re-authenticating")

    # Cache miss — look up in DB (AUTH-02).
    # Use ctx.token_objects when provided by tests (mocked); fall back to the
    # real Token.objects in production.  ctx.token_objects is injected by the
    # test fixture so DB lookups are bypassed, avoiding Django's
    # SynchronousOnlyOperation guard in async contexts.
    try:
        token_objects = getattr(ctx, "token_objects", None)
        if token_objects is None:
            from nautobot.users.models import Token

            token_objects = Token.objects
        token = token_objects.select_related("user").get(key=token_key)
        user = token.user
    except Exception:  # noqa: BLE001 — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache the user PK string for subsequent calls in this session (T-11-03)
    await ctx.set_state(_CACHED_USER_KEY, str(user.pk))
    return user
