"""Cursor-based pagination layer for MCP tools."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async

if TYPE_CHECKING:
    from django.db.models import QuerySet

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

LIMIT_DEFAULT = 25
LIMIT_MAX = 1000
LIMIT_SUMMARIZE = 100


# -------------------------------------------------------------------
# Cursor helpers (PAGE-04)
# -------------------------------------------------------------------


def encode_cursor(pk: Any) -> str:
    """Encode a PK (UUID or string) as a base64 cursor string.

    Args:
        pk: The primary key value to encode.

    Returns:
        base64-encoded ASCII string safe for use as a cursor token.
    """
    return base64.b64encode(str(pk).encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    """Decode a base64 cursor string back to its PK value.

    Args:
        cursor: A cursor string produced by encode_cursor().

    Returns:
        The PK value as a string (UUID string or plain string).
    """
    return base64.b64decode(cursor.encode("ascii")).decode("utf-8")


# -------------------------------------------------------------------
# Result dataclass (PAGE-03)
# -------------------------------------------------------------------


@dataclass
class PaginatedResult:
    """Cursor-paginated result returned by all list tools.

    Attributes:
        items: List of serialized model dicts for the current page.
        cursor: base64 cursor for the next page, or None if no more results.
        total_count: Full queryset count, or None if below LIMIT_SUMMARIZE.
        summary: Summary dict when total_count > LIMIT_SUMMARIZE, else None.
    """

    items: list[dict[str, Any]]
    cursor: str | None = None
    total_count: int | None = None
    summary: dict[str, Any] | None = None

    def has_next_page(self) -> bool:
        """Return True if there is a next page of results."""
        return self.cursor is not None


# -------------------------------------------------------------------
# Paginate queryset (PAGE-01, PAGE-02)
# -------------------------------------------------------------------


def paginate_queryset(
    qs: QuerySet,
    limit: int = LIMIT_DEFAULT,
    cursor: str | None = None,
) -> PaginatedResult:
    """Paginate a Django queryset using base64(pk) cursor.

    Count is called on the original queryset (before cursor filter) only
    when the result set reaches LIMIT_SUMMARIZE, to avoid expensive COUNT
    on every request (PIT-07 prevention).

    Args:
        qs: The Django QuerySet to paginate.
        limit: Number of items per page (clamped to LIMIT_MAX).
        cursor: Optional base64-encoded PK cursor from a previous response.

    Returns:
        PaginatedResult with serialized items, next cursor, total count, and
        optional summary when result set exceeds LIMIT_SUMMARIZE.
    """
    # Step 1: Apply cursor filter (pk__gt) if present
    if cursor is not None:
        decoded_pk = decode_cursor(cursor)
        qs = qs.filter(pk__gt=decoded_pk)

    # Step 2: Clamp limit
    limit = max(1, min(limit, LIMIT_MAX))

    # Step 3: Slice to detect has_next
    # Evaluate queryset by converting to list — needed for has_next detection
    items_plus_one = list(qs[: limit + 1])  # type: ignore[misc]
    has_next = len(items_plus_one) > limit
    items = items_plus_one[:limit]

    # Step 4: Encode next cursor
    next_cursor: str | None = None
    if has_next and items:
        next_cursor = encode_cursor(items[-1].pk)

    # Step 5: Count only when summarize threshold is reachable
    # Count the FULL queryset (original, without cursor filter) for accurate total
    # Apply the count BEFORE any slicing to get the true total (PAGE-02, PIT-07)
    total_count: int | None = None
    summary: dict[str, Any] | None = None
    if len(items_plus_one) >= LIMIT_SUMMARIZE:
        total_count = qs.count()  # type: ignore[attr-defined]
        if total_count > LIMIT_SUMMARIZE:
            summary = {
                "total_count": total_count,
                "display_count": len(items),
                "message": (
                    f"Showing {len(items)} of {total_count} results. " "Refine your search to see specific records."
                ),
            }

    return PaginatedResult(
        items=items,
        cursor=next_cursor,
        total_count=total_count,
        summary=summary,
    )


# -------------------------------------------------------------------
# Async wrapper (PAGE-05)
# -------------------------------------------------------------------


async def paginate_queryset_async(
    qs: QuerySet,
    limit: int = LIMIT_DEFAULT,
    cursor: str | None = None,
) -> PaginatedResult:
    """Async wrapper around paginate_queryset using sync_to_async.

    Uses thread_sensitive=True to ensure ORM calls run on Django's request
    thread, reusing the database connection pool (PIT-06 / PAGE-05).

    Args:
        qs: The Django QuerySet to paginate.
        limit: Number of items per page.
        cursor: Optional base64-encoded cursor from a previous response.

    Returns:
        PaginatedResult (same as paginate_queryset).
    """
    return await sync_to_async(paginate_queryset, thread_sensitive=True)(qs=qs, limit=limit, cursor=cursor)
