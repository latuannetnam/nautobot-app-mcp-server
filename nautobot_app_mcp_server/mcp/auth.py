"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token <hex_key>" format (Nautobot Token keys are 40-char hex)
    3. Check FastMCP session state cache (ctx.get_state)
    4. Cache miss → look up Nautobot Token object → return User (AUTH-02)
    5. Cache the user PK string in FastMCP session state (ctx.set_state)
    6. Missing / invalid token → return AnonymousUser with log warning

PIT-16 / PIT-20: Use get_http_request() from fastmcp.server.dependencies
to access the Starlette Request.  This function reads both ctx.request_context
(when available) and FastMCP's _current_http_request ContextVar directly,
so it works regardless of whether FastMCP has set request_context on the
ServerContext — fixing an issue where ctx.request_context was None during
StreamableHTTPSessionManager tool calls.  PIT-10: Log WARNING on missing
token, DEBUG on invalid token.

PIT-AUTHFIX: Token.objects and User.objects lookups MUST be wrapped in
sync_to_async(..., thread_sensitive=True) because FastMCP runs async tools
in a thread pool where Django's default DB connection (bound to the main thread)
is not available.  Calling ORM methods directly in the async tool context raises
"Connection not available" errors.  Using thread_sensitive=True ensures the ORM
calls run on Django's dedicated request thread where the connection is valid.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext
from fastmcp.server.dependencies import get_http_request

logger = logging.getLogger(__name__)

# FastMCP state key for the cached user PK.  Stored as a string so the value
# is always serializable (T-11-03).  FastMCP auto-prefixes keys with session_id
# via _make_state_key(), preventing cross-session collisions (T-11-02).
_CACHED_USER_KEY = "mcp:cached_user"

# NOTE: Nautobot Token keys are 40-char hex strings (no "nbapikey_" prefix).


# -------------------------------------------------------------------
# Sync helpers — called via sync_to_async below
# -------------------------------------------------------------------


def _lookup_user_by_token_sync(token_key: str):  # noqa: ANN202
    """Sync helper: look up a Nautobot Token by key and return its user.

    Raises Token.DoesNotExist if the token is not found.
    """
    from nautobot.users.models import Token

    token = Token.objects.select_related("user").get(key=token_key)
    return token.user


def _lookup_user_by_pk_sync(user_pk: str):  # noqa: ANN202
    """Sync helper: look up a Nautobot user by primary key.

    Raises User.DoesNotExist if the user is not found.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.get(pk=user_pk)


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


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

    # PIT-20: Use get_http_request() which reads FastMCP's _current_http_request
    # ContextVar directly — works even when ctx.request_context is None (the
    # case during StreamableHTTPSessionManager tool calls).
    # Fall back to ctx.request_context.request for non-HTTP contexts (tests, STDIO).
    try:
        mcp_request = get_http_request()
    except RuntimeError:
        # Non-HTTP transport (unit tests, STDIO) — try ctx.request_context
        ctx_req = ctx.request_context
        if ctx_req is not None:
            mcp_request = ctx_req.request
        else:
            # Cannot determine auth — return AnonymousUser
            logger.warning("MCP: No HTTP request context available, anonymous access")
            return AnonymousUser()
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
            # PIT-AUTHFIX: Wrap ORM call in sync_to_async with thread_sensitive=True
            # to run on Django's request thread where the DB connection is available.
            user = await sync_to_async(_lookup_user_by_pk_sync, thread_sensitive=True)(
                cached_user_id
            )
            return user
        except Exception:  # noqa: BLE001 — User.DoesNotExist, de-activated, etc.
            # Stale or invalid cache — fall through to re-authenticate (S110)
            logger.debug("MCP: Cached user stale or deleted, re-authenticating")

    # Cache miss — look up in DB (AUTH-02).
    # PIT-AUTHFIX: Wrap ORM call in sync_to_async with thread_sensitive=True.
    # FastMCP runs async tool handlers in a thread pool, but Django's default
    # DB connection is bound to the main thread.  Calling ORM methods directly
    # in that context raises "Connection not available".  Using
    # thread_sensitive=True routes the call to Django's dedicated request thread.
    try:
        user = await sync_to_async(_lookup_user_by_token_sync, thread_sensitive=True)(token_key)
    except Exception:  # noqa: BLE001 — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()

    # Cache the user PK string for subsequent calls in this session (T-11-03)
    await ctx.set_state(_CACHED_USER_KEY, str(user.pk))
    return user
