"""Shared ORM query utilities for core read tools.

Provides:
    - Serialization helpers (model_to_dict wrappers per model)
    - QuerySet builder functions (select_related / prefetch_related chains)
    - Sync implementation helpers called via sync_to_async
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from django.db.models import QuerySet
from django.forms.models import model_to_dict

if TYPE_CHECKING:
    from nautobot.dcim.models import Device, Interface, Location  # type: ignore
    from nautobot.ipam.models import VLAN, IPAddress, Prefix  # type: ignore
    from nautobot.users.models import User

# Standard fields excluded from all model_to_dict calls
_STANDARD_EXCLUDE = [
    "created",
    "last_updated",
    "custom_field_data",
    "computed_fields",
    "comments",
]


# -------------------------------------------------------------------
# Serialization helpers
# -------------------------------------------------------------------


def serialize_device(device: Device) -> dict[str, Any]:
    """Serialize a Device to a JSON-serializable dict."""
    from nautobot.dcim.models import Device  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        device,
        fields=[
            "pk",
            "name",
            "serial",
            "asset_tag",
            "description",
            "primary_ip4",
            "primary_ip6",
        ],
        exclude=_STANDARD_EXCLUDE,
    )
    data["pk"] = str(device.pk)
    data["status"] = device.status.name if device.status else None
    data["role"] = device.role.name if device.role else None
    data["platform"] = device.platform.name if device.platform else None
    data["device_type"] = device.device_type.model if device.device_type else None
    data["manufacturer"] = (
        device.device_type.manufacturer.name if device.device_type and device.device_type.manufacturer else None
    )
    data["location"] = device.location.name if device.location else None
    data["tenant"] = device.tenant.name if device.tenant else None
    return data


def serialize_device_with_interfaces(device: Device) -> dict[str, Any]:
    """Serialize a Device with its interfaces prefetched."""
    # Uses serialize_device() — no new lazy import needed
    data = serialize_device(device)
    # Interfaces are prefetched in the queryset; serialize inline
    if hasattr(device, "_prefetched_objects_cache") and "interfaces" in device._prefetched_objects_cache:  # noqa: E501
        data["interfaces"] = [serialize_interface(iface) for iface in device.interfaces.all()]
    else:
        data["interfaces"] = [serialize_interface(iface) for iface in device.interfaces.all()]
    return data


def serialize_interface(interface: Interface) -> dict[str, Any]:
    """Serialize an Interface to a JSON-serializable dict."""
    from nautobot.dcim.models import Interface  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        interface,
        fields=[
            "pk",
            "name",
            "label",
            "enabled",
            "type",
            "mtu",
            "mac_address",
            "mode",
            "description",
            "mgmt_only",
            "speed",
            "duplex",
            "wwn",
        ],
        exclude=_STANDARD_EXCLUDE,
    )
    data["pk"] = str(interface.pk)
    data["status"] = interface.status.name if interface.status else None
    data["device"] = interface.device.name if interface.device else None
    data["role"] = interface.role.name if interface.role else None
    data["lag"] = interface.lag.name if interface.lag else None
    data["parent"] = interface.parent_interface.name if interface.parent_interface else None
    data["bridge"] = interface.bridge.name if interface.bridge else None
    # virtual_device_contexts is a M2M relation in Nautobot 3.x
    vdc_list = list(interface.virtual_device_contexts.all())
    data["virtual_device_context"] = vdc_list[0].name if vdc_list else None
    data["untagged_vlan"] = interface.untagged_vlan.name if interface.untagged_vlan else None
    # Serialize IP addresses inline (prefetched on interface_get)
    if hasattr(interface, "_prefetched_objects_cache") and "ip_addresses" in interface._prefetched_objects_cache:  # noqa: E501
        data["ip_addresses"] = [{"pk": str(ip.pk), "address": ip.host} for ip in interface.ip_addresses.all()]
    else:
        data["ip_addresses"] = [{"pk": str(ip.pk), "address": ip.host} for ip in interface.ip_addresses.all()]
    return data


def serialize_ipaddress(ip: IPAddress) -> dict[str, Any]:
    """Serialize an IPAddress to a JSON-serializable dict."""
    from nautobot.ipam.models import IPAddress  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        ip,
        fields=["pk", "dns_name", "description", "ip_version"],
        exclude=_STANDARD_EXCLUDE,
    )
    # "host" is the actual DB field name in Nautobot 3.0.0; expose as "address" for API compat
    data["address"] = ip.host
    data["pk"] = str(ip.pk)
    data["status"] = ip.status.name if ip.status else None
    data["role"] = ip.role.name if ip.role else None
    data["tenant"] = ip.tenant.name if ip.tenant else None
    # vrf/namespace do not exist on Nautobot 3.0.0 IPAddress model
    # Serialize interfaces inline (prefetched on ipaddress_get)
    if hasattr(ip, "_prefetched_objects_cache") and "interfaces" in ip._prefetched_objects_cache:
        data["interfaces"] = [
            {
                "pk": str(iface.pk),
                "name": iface.name,
                "device": iface.device.name if iface.device else None,
            }
            for iface in ip.interfaces.all()
        ]
    else:
        data["interfaces"] = [
            {
                "pk": str(iface.pk),
                "name": iface.name,
                "device": iface.device.name if iface.device else None,
            }
            for iface in ip.interfaces.all()
        ]
    return data


def serialize_prefix(prefix: Prefix) -> dict[str, Any]:
    """Serialize a Prefix to a JSON-serializable dict."""
    from nautobot.ipam.models import Prefix  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        prefix,
        fields=["pk", "description", "type", "date_allocated"],
        exclude=_STANDARD_EXCLUDE,
    )
    # "network" is the actual DB field name in Nautobot 3.0.0; expose as "prefix" for API compat
    data["prefix"] = str(prefix.network)
    data["pk"] = str(prefix.pk)
    data["status"] = prefix.status.name if prefix.status else None
    data["role"] = prefix.role.name if prefix.role else None
    data["tenant"] = prefix.tenant.name if prefix.tenant else None
    # vrfs is M2M in Nautobot 3.x IPAM (no direct FK vrf field)
    data["vrfs"] = [vrf.name for vrf in prefix.vrfs.all()]
    # Also expose singular "vrf" for API compat (first VRF name, or None)
    vrfs_list = list(prefix.vrfs.all())
    data["vrf"] = vrfs_list[0].name if vrfs_list else None
    # namespace is a direct CharField in Nautobot 3.x IPAM (not a relation)
    data["namespace"] = str(prefix.namespace) if prefix.namespace else None
    # locations is M2M in Nautobot v2.x
    data["locations"] = [loc.name for loc in prefix.locations.all()]
    return data


def serialize_vlan(vlan: VLAN) -> dict[str, Any]:
    """Serialize a VLAN to a JSON-serializable dict."""
    from nautobot.ipam.models import VLAN  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        vlan,
        fields=["pk", "name", "vid", "description"],
        exclude=_STANDARD_EXCLUDE,
    )
    data["pk"] = str(vlan.pk)
    data["status"] = vlan.status.name if vlan.status else None
    data["role"] = vlan.role.name if vlan.role else None
    data["tenant"] = vlan.tenant.name if vlan.tenant else None
    # vlan_group is the FK field name in Nautobot 3.x (not "group")
    data["group"] = vlan.vlan_group.name if vlan.vlan_group else None
    # locations is M2M in Nautobot v2.x
    data["locations"] = [loc.name for loc in vlan.locations.all()]
    return data


def serialize_location(location: Location) -> dict[str, Any]:
    """Serialize a Location to a JSON-serializable dict."""
    from nautobot.dcim.models import Location  # lazy import — avoids module-level Nautobot model import

    data = model_to_dict(
        location,
        fields=["pk", "name", "description"],
        exclude=_STANDARD_EXCLUDE,
    )
    data["pk"] = str(location.pk)
    data["status"] = location.status.name if location.status else None
    data["location_type"] = location.location_type.name if location.location_type else None
    data["parent"] = location.parent.name if location.parent else None
    data["tenant"] = location.tenant.name if location.tenant else None
    return data


# -------------------------------------------------------------------
# QuerySet builders
# -------------------------------------------------------------------


def build_device_qs() -> QuerySet[Device]:
    """Build a Device queryset with select_related for all FK fields."""
    from nautobot.dcim.models import Device  # lazy import — avoids module-level Nautobot model import

    return Device.objects.select_related(
        "device_type__manufacturer",
        "status",
        "role",
        "platform",
        "location",
        "tenant",
    )


def build_interface_qs() -> QuerySet[Interface]:
    """Build an Interface queryset with select_related for FK fields."""
    from nautobot.dcim.models import Interface  # lazy import — avoids module-level Nautobot model import

    return Interface.objects.select_related(
        "device",
        "status",
        "role",
        "lag",
        "parent_interface",
        "bridge",
        "untagged_vlan",
    )


def build_interface_qs_with_ip_addresses() -> QuerySet[Interface]:
    """Build an Interface queryset with ip_addresses prefetched."""
    return build_interface_qs().prefetch_related("ip_addresses")


def build_ipaddress_qs() -> QuerySet[IPAddress]:
    """Build an IPAddress queryset with select_related for FK fields."""
    from nautobot.ipam.models import IPAddress  # lazy import — avoids module-level Nautobot model import

    # namespace and vrf are NOT FK fields in Nautobot 3.x IPAM
    # namespace is a CharField; vrfs is M2M — accessed directly in serialize
    return IPAddress.objects.select_related(
        "status",
        "tenant",
    )


def build_ipaddress_qs_with_interfaces() -> QuerySet[IPAddress]:
    """Build an IPAddress queryset with interfaces prefetched."""
    return build_ipaddress_qs().prefetch_related("interfaces")


def build_prefix_qs() -> QuerySet[Prefix]:
    """Build a Prefix queryset with select_related for FK fields."""
    from nautobot.ipam.models import Prefix  # lazy import — avoids module-level Nautobot model import

    # vrf and namespace are NOT FK fields in Nautobot 3.x IPAM
    # namespace is a CharField; vrfs is M2M — accessed directly in serialize
    return Prefix.objects.select_related(
        "status",
        "role",
        "tenant",
    ).prefetch_related("locations", "vrfs")


def build_vlan_qs() -> QuerySet[VLAN]:
    """Build a VLAN queryset with select_related for FK fields."""
    from nautobot.ipam.models import VLAN  # lazy import — avoids module-level Nautobot model import

    return VLAN.objects.select_related(
        "status",
        "role",
        "tenant",
        "vlan_group",
    ).prefetch_related("locations")


def build_location_qs() -> QuerySet[Location]:
    """Build a Location queryset with select_related for FK fields."""
    from nautobot.dcim.models import Location  # lazy import — avoids module-level Nautobot model import

    return Location.objects.select_related(
        "status",
        "location_type",
        "parent",
        "tenant",
    )


# -------------------------------------------------------------------
# Sync implementation helpers (called via sync_to_async)
# -------------------------------------------------------------------


def _looks_like_uuid(value: str) -> bool:
    """Return True if value looks like a UUID (D-03 identifier auto-detection)."""
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", value.lower()))  # noqa: E501


def _sync_device_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    """Sync implementation of device_list."""
    from nautobot.dcim.models import Device  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_device_qs().restrict(user, action="view")
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_device(d) for d in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


def _sync_device_get(user: User, name_or_id: str) -> dict[str, Any]:
    """Sync implementation of device_get (D-02 not-found + D-03 name-or-id)."""
    from nautobot.dcim.models import Device  # lazy import — avoids module-level Nautobot model import

    if _looks_like_uuid(name_or_id):
        qs = (
            build_device_qs()
            .filter(pk=name_or_id)
            .restrict(user, action="view")
            .prefetch_related("interfaces__ip_addresses", "interfaces__status")
        )
    else:
        qs = (
            build_device_qs()
            .filter(name=name_or_id)
            .restrict(user, action="view")
            .prefetch_related("interfaces__ip_addresses", "interfaces__status")
        )
    devices = list(qs)
    if not devices:
        raise ValueError(f"Device '{name_or_id}' not found")
    return serialize_device_with_interfaces(devices[0])


def _sync_interface_list(user: User, device_name: str | None, limit: int, cursor: str | None) -> dict[str, Any]:  # noqa: E501
    """Sync implementation of interface_list."""
    from nautobot.dcim.models import Interface  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_interface_qs().restrict(user, action="view")
    if device_name:
        qs = qs.filter(device__name=device_name)
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_interface(i) for i in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


def _sync_interface_get(user: User, name_or_id: str) -> dict[str, Any]:
    """Sync implementation of interface_get (D-02 + D-03)."""
    from nautobot.dcim.models import Interface  # lazy import — avoids module-level Nautobot model import

    if _looks_like_uuid(name_or_id):
        qs = build_interface_qs_with_ip_addresses().filter(pk=name_or_id).restrict(user, action="view")
    else:
        qs = build_interface_qs_with_ip_addresses().filter(name=name_or_id).restrict(user, action="view")
    interfaces = list(qs)
    if not interfaces:
        raise ValueError(f"Interface '{name_or_id}' not found")
    return serialize_interface(interfaces[0])


def _sync_ipaddress_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    """Sync implementation of ipaddress_list."""
    from nautobot.ipam.models import IPAddress  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_ipaddress_qs().restrict(user, action="view")
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_ipaddress(ip) for ip in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


def _sync_ipaddress_get(user: User, name_or_id: str) -> dict[str, Any]:
    """Sync implementation of ipaddress_get (D-02 + D-03)."""
    from nautobot.ipam.models import IPAddress  # lazy import — avoids module-level Nautobot model import

    if _looks_like_uuid(name_or_id):
        qs = build_ipaddress_qs_with_interfaces().filter(pk=name_or_id).restrict(user, action="view")
    else:
        qs = build_ipaddress_qs_with_interfaces().filter(host=name_or_id).restrict(user, action="view")
    ips = list(qs)
    if not ips:
        raise ValueError(f"IP address '{name_or_id}' not found")
    return serialize_ipaddress(ips[0])


def _sync_prefix_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    """Sync implementation of prefix_list."""
    from nautobot.ipam.models import Prefix  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_prefix_qs().restrict(user, action="view")
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_prefix(p) for p in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


def _sync_vlan_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    """Sync implementation of vlan_list."""
    from nautobot.ipam.models import VLAN  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_vlan_qs().restrict(user, action="view")
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_vlan(v) for v in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


def _sync_location_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    """Sync implementation of location_list."""
    from nautobot.dcim.models import Location  # lazy import — avoids module-level Nautobot model import

    from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset

    qs = build_location_qs().restrict(user, action="view")
    result = paginate_queryset(qs, limit=limit, cursor=cursor)
    return {
        "items": [serialize_location(loc) for loc in result.items],
        "cursor": result.cursor,
        "total_count": result.total_count,
        "summary": result.summary,
    }


# -------------------------------------------------------------------
# search_by_name — multi-model search (TOOL-10, D-01)
# -------------------------------------------------------------------


def _sync_search_by_name(
    user: User,
    query: str,
    limit: int = 25,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Multi-model name search with AND match across terms (TOOL-10, D-01).

    Searches: Device.name, Interface.name, IPAddress.address, Prefix.prefix,
    VLAN.name, Location.name

    All terms must appear in the searched field (AND semantics, case-insensitive).

    Args:
        user: Nautobot user for .restrict().
        query: Space-separated search terms (e.g. "juniper router").
        limit: Max results to return (default 25, max 1000).
        cursor: Optional base64 cursor for pagination.

    Returns:
        dict with items (list of result dicts), cursor, total_count, summary.

    Raises:
        ValueError: If query is empty or whitespace-only.
    """
    import functools
    import operator as op

    from django.db.models import Q

    from nautobot_app_mcp_server.mcp.tools.pagination import (
        decode_cursor,
        encode_cursor,
    )

    # Strip and split query (D-01: handle leading/trailing whitespace)
    terms = query.strip().split()
    if not terms:
        raise ValueError("search_by_name requires at least one non-empty term")

    # Build AND Q object per term across all terms
    def _name_contains(model_field: str, term: str) -> Q:
        return Q(**{f"{model_field}__icontains": term})

    def _address_contains(term: str) -> Q:
        return Q(host__icontains=term)

    def _prefix_contains(term: str) -> Q:
        return Q(network__icontains=term)

    # Search across 6 models sequentially and combine results.
    # Each model gets its own queryset filtered by all terms (AND across terms).
    all_results: list[dict[str, Any]] = []

    # Search Device
    qs_device = (
        build_device_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_name_contains("name", t) for t in terms]))
    )
    for device in qs_device[: limit * 2]:
        all_results.append(
            {
                "model": "dcim.device",
                "pk": str(device.pk),
                "name": device.name,
                "data": serialize_device(device),
            }
        )

    # Search Interface
    qs_interface = (
        build_interface_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_name_contains("name", t) for t in terms]))
    )
    for interface in qs_interface[: limit * 2]:
        all_results.append(
            {
                "model": "dcim.interface",
                "pk": str(interface.pk),
                "name": interface.name,
                "data": serialize_interface(interface),
            }
        )

    # Search IPAddress (search address field)
    qs_ip = (
        build_ipaddress_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_address_contains(t) for t in terms]))
    )
    for ip in qs_ip[: limit * 2]:
        all_results.append(
            {
                "model": "ipam.ipaddress",
                "pk": str(ip.pk),
                "name": ip.host,
                "data": serialize_ipaddress(ip),
            }
        )

    # Search Prefix (search prefix field — network portion)
    qs_prefix = (
        build_prefix_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_prefix_contains(t) for t in terms]))
    )
    for prefix in qs_prefix[: limit * 2]:
        all_results.append(
            {
                "model": "ipam.prefix",
                "pk": str(prefix.pk),
                "name": str(prefix.network),
                "data": serialize_prefix(prefix),
            }
        )

    # Search VLAN
    qs_vlan = (
        build_vlan_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_name_contains("name", t) for t in terms]))
    )
    for vlan in qs_vlan[: limit * 2]:
        all_results.append(
            {
                "model": "ipam.vlan",
                "pk": str(vlan.pk),
                "name": vlan.name,
                "data": serialize_vlan(vlan),
            }
        )

    # Search Location
    qs_location = (
        build_location_qs()
        .restrict(user, action="view")
        .filter(functools.reduce(op.and_, [_name_contains("name", t) for t in terms]))
    )
    for location in qs_location[: limit * 2]:
        all_results.append(
            {
                "model": "dcim.location",
                "pk": str(location.pk),
                "name": location.name,
                "data": serialize_location(location),
            }
        )

    # Sort by model then name for consistent ordering
    all_results.sort(key=lambda r: (r["model"], r["name"]))

    # Manual pagination over the combined list (no DB cursor across models)
    # Apply cursor filter (cursor encodes last seen model's pk+name for ordering)
    start_idx = 0
    if cursor:
        decoded = decode_cursor(cursor)
        # Cursor format: base64(f"{model}@{pk}") — "@" is safe since neither
        # model names nor UUID strings contain it.
        try:
            last_model, last_pk = decoded.split("@", 1)
            for i, r in enumerate(all_results):
                if r["model"] == last_model and r["pk"] == last_pk:
                    start_idx = i + 1
                    break
        except ValueError:
            start_idx = 0  # Invalid cursor — start from beginning

    total_count = len(all_results)
    limit = max(1, min(limit, 1000))
    page = all_results[start_idx : start_idx + limit]
    has_next = start_idx + limit < total_count
    next_cursor = None
    if has_next and page:
        last_item = page[-1]
        next_cursor = encode_cursor(f"{last_item['model']}@{last_item['pk']}")

    summary = None
    if total_count > 100:
        summary = {
            "total_count": total_count,
            "display_count": len(page),
            "message": (
                f"Showing {len(page)} of {total_count} results across 6 models. "
                "Refine your search to narrow results."
            ),
        }

    return {
        "items": page,
        "cursor": next_cursor,
        "total_count": total_count if total_count > 100 else None,
        "summary": summary,
    }
