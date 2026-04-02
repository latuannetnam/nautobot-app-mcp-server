"""Core read tools — all 10 MCP read tools with pagination and auth."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from fastmcp.server.context import Context as ToolContext

from nautobot_app_mcp_server.mcp import register_mcp_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot_app_mcp_server.mcp.tools import query_utils

if TYPE_CHECKING:
    pass

TOOLS_SCOPE = "core"
TOOLS_TIER = "core"


# -------------------------------------------------------------------
# device_list
# -------------------------------------------------------------------


async def _device_list_handler(
    ctx: ToolContext,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List network devices with status, platform, location, and more.

    Returns a paginated list of devices. Each device includes its
    status, role, platform, device type, manufacturer, location, and tenant.

    Args:
        ctx: FastMCP ToolContext providing request/session access.
        limit: Maximum number of devices to return (default 25, max 1000).
        cursor: Optional cursor from a previous response for pagination.

    Returns:
        dict with items (list of device dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_device_list, thread_sensitive=True
    )(user=user, limit=limit, cursor=cursor)


register_mcp_tool(
    name="device_list",
    func=_device_list_handler,
    description="List network devices with status, platform, location, and more.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of devices to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# device_get
# -------------------------------------------------------------------


async def _device_get_handler(
    ctx: ToolContext,
    name_or_id: str,
) -> dict[str, Any]:
    """Get a single device by name or ID with its interfaces prefetched.

    Args:
        ctx: FastMCP ToolContext.
        name_or_id: Device name (e.g. 'router-01') or UUID primary key.
            If it looks like a UUID, performs a pk lookup; otherwise performs
            a name lookup.

    Returns:
        dict with device data including nested interfaces.

    Raises:
        ValueError: If the device is not found.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_device_get, thread_sensitive=True
    )(user=user, name_or_id=name_or_id)


register_mcp_tool(
    name="device_get",
    func=_device_get_handler,
    description="Get a single device by name or ID, with interfaces prefetched.",
    input_schema={
        "type": "object",
        "properties": {
            "name_or_id": {
                "type": "string",
                "description": "Device name (e.g. 'router-01') or UUID primary key.",
            },
        },
        "required": ["name_or_id"],
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# interface_list
# -------------------------------------------------------------------


async def _interface_list_handler(
    ctx: ToolContext,
    device_name: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List interfaces, optionally filtered by device name.

    Args:
        ctx: FastMCP ToolContext.
        device_name: Optional device name to filter interfaces.
        limit: Maximum number of interfaces to return (default 25, max 1000).
        cursor: Optional pagination cursor.

    Returns:
        dict with items (list of interface dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_interface_list, thread_sensitive=True
    )(user=user, device_name=device_name, limit=limit, cursor=cursor)


register_mcp_tool(
    name="interface_list",
    func=_interface_list_handler,
    description="List network interfaces, optionally filtered by device name.",
    input_schema={
        "type": "object",
        "properties": {
            "device_name": {
                "type": "string",
                "description": "Optional device name to filter interfaces by.",
            },
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of interfaces to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# interface_get
# -------------------------------------------------------------------


async def _interface_get_handler(
    ctx: ToolContext,
    name_or_id: str,
) -> dict[str, Any]:
    """Get a single interface by name or ID with IP addresses prefetched.

    Args:
        ctx: FastMCP ToolContext.
        name_or_id: Interface name (e.g. 'ge-0/0/0') or UUID primary key.

    Returns:
        dict with interface data including nested ip_addresses.

    Raises:
        ValueError: If the interface is not found.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_interface_get, thread_sensitive=True
    )(user=user, name_or_id=name_or_id)


register_mcp_tool(
    name="interface_get",
    func=_interface_get_handler,
    description="Get a single interface by name or ID, with IP addresses prefetched.",
    input_schema={
        "type": "object",
        "properties": {
            "name_or_id": {
                "type": "string",
                "description": "Interface name (e.g. 'ge-0/0/0') or UUID primary key.",
            },
        },
        "required": ["name_or_id"],
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# ipaddress_list
# -------------------------------------------------------------------


async def _ipaddress_list_handler(
    ctx: ToolContext,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List IP addresses with tenant, VRF, status, and role.

    Args:
        ctx: FastMCP ToolContext.
        limit: Maximum number of IP addresses to return (default 25, max 1000).
        cursor: Optional pagination cursor.

    Returns:
        dict with items (list of IP address dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_ipaddress_list, thread_sensitive=True
    )(user=user, limit=limit, cursor=cursor)


register_mcp_tool(
    name="ipaddress_list",
    func=_ipaddress_list_handler,
    description="List IP addresses with tenant, VRF, status, and role.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of IP addresses to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# ipaddress_get
# -------------------------------------------------------------------


async def _ipaddress_get_handler(
    ctx: ToolContext,
    name_or_id: str,
) -> dict[str, Any]:
    """Get a single IP address by address or ID with interfaces prefetched.

    Args:
        ctx: FastMCP ToolContext.
        name_or_id: IP address (e.g. '10.0.0.1/24') or UUID primary key.

    Returns:
        dict with IP address data including nested interfaces.

    Raises:
        ValueError: If the IP address is not found.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_ipaddress_get, thread_sensitive=True
    )(user=user, name_or_id=name_or_id)


register_mcp_tool(
    name="ipaddress_get",
    func=_ipaddress_get_handler,
    description="Get a single IP address by address or ID, with interfaces prefetched.",
    input_schema={
        "type": "object",
        "properties": {
            "name_or_id": {
                "type": "string",
                "description": "IP address (e.g. '10.0.0.1/24') or UUID primary key.",
            },
        },
        "required": ["name_or_id"],
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# prefix_list
# -------------------------------------------------------------------


async def _prefix_list_handler(
    ctx: ToolContext,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List network prefixes with VRF, tenant, status, and role.

    Args:
        ctx: FastMCP ToolContext.
        limit: Maximum number of prefixes to return (default 25, max 1000).
        cursor: Optional pagination cursor.

    Returns:
        dict with items (list of prefix dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_prefix_list, thread_sensitive=True
    )(user=user, limit=limit, cursor=cursor)


register_mcp_tool(
    name="prefix_list",
    func=_prefix_list_handler,
    description="List network prefixes with VRF, tenant, status, and role.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of prefixes to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# vlan_list
# -------------------------------------------------------------------


async def _vlan_list_handler(
    ctx: ToolContext,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List VLANs with site/group, status, and role.

    Args:
        ctx: FastMCP ToolContext.
        limit: Maximum number of VLANs to return (default 25, max 1000).
        cursor: Optional pagination cursor.

    Returns:
        dict with items (list of VLAN dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_vlan_list, thread_sensitive=True
    )(user=user, limit=limit, cursor=cursor)


register_mcp_tool(
    name="vlan_list",
    func=_vlan_list_handler,
    description="List VLANs with site/group, status, and role.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of VLANs to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# location_list
# -------------------------------------------------------------------


async def _location_list_handler(
    ctx: ToolContext,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List locations with location type, parent, and tenant.

    Args:
        ctx: FastMCP ToolContext.
        limit: Maximum number of locations to return (default 25, max 1000).
        cursor: Optional pagination cursor.

    Returns:
        dict with items (list of location dicts), cursor, total_count, summary.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(
        query_utils._sync_location_list, thread_sensitive=True
    )(user=user, limit=limit, cursor=cursor)


register_mcp_tool(
    name="location_list",
    func=_location_list_handler,
    description="List locations with location type, parent, and tenant.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of locations to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)


# -------------------------------------------------------------------
# search_by_name
# -------------------------------------------------------------------


async def _search_by_name_handler(
    ctx: ToolContext,
    query: str,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Multi-model name search across devices, interfaces, IPs, prefixes, VLANs, and locations.

    Performs an AND search across all terms — all search terms must appear
    somewhere in the object's name (or address for IP addresses).

    Examples:
        - "juniper router" — finds objects whose name contains both "juniper" AND "router"
        - "edge" — finds all objects with "edge" in the name

    Args:
        ctx: FastMCP ToolContext.
        query: Space-separated search terms (e.g. "juniper router").
        limit: Maximum number of results to return (default 25, max 1000).
        cursor: Optional pagination cursor from a previous response.

    Returns:
        dict with items (list of result dicts), cursor, total_count, summary.
        Each item has: model, pk, name, data (serialized object).

    Raises:
        ValueError: If the query is empty or whitespace-only.
    """
    user = get_user_from_request(ctx)
    return await sync_to_async(query_utils._sync_search_by_name, thread_sensitive=True)(
        user=user, query=query, limit=limit, cursor=cursor
    )


register_mcp_tool(
    name="search_by_name",
    func=_search_by_name_handler,
    description=(
        "Multi-model name search across devices, interfaces, IP addresses, prefixes, "
        "VLANs, and locations. All search terms must match (AND semantics)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Space-separated search terms. All terms must appear in the "
                    "object's name (AND match). Case-insensitive. "
                    "Example: 'juniper router' finds objects with both terms."
                ),
            },
            "limit": {
                "type": "integer",
                "default": 25,
                "description": "Maximum number of results to return (default 25, max 1000).",
            },
            "cursor": {
                "type": "string",
                "description": "Pagination cursor from a previous response.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
