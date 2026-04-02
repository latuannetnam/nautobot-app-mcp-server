# Phase 3: Core Read Tools — Research

**Phase:** 03-core-read-tools
**Research date:** 2026-04-02
**Status:** Ready for planning

---

## 1. Nautobot ORM Serialization

### `model_to_dict()` with Nautobot Models

Django's `django.forms.models.model_to_dict()` serializes a model instance to a Python dict. It handles:
- Scalar fields → Python primitives (str, int, bool, etc.)
- Foreign keys → the FK value (pk), not the related object
- Many-to-many → list of pk values
- Datetime fields → ISO 8601 strings

**Nautobot-specific behavior:**
- All Nautobot primary keys are **UUIDs** (not int) — `model_to_dict()` returns `pk` as a UUID string, JSON-serializable
- Nautobot adds extra fields beyond standard Django: `custom_field_data`, `computed_fields`, etc. Use `exclude` to drop these
- Standard exclusions for all tools: `["created", "last_updated", "custom_field_data", "computed_fields", "_正"]` (正 = concrete field marker)

### Field Lists Per Model

#### Device (`nautobot.dcim.models.Device`)
```
PK, name, serial, asset_tag, status, role, platform,
device_type (→ manufacturer), location, tenant,
primary_ip4, primary_ip6, vcs, secrets_group,
description, comments
```
**select_related chain:** `"device_type__manufacturer", "status", "role", "platform", "location", "tenant"`

#### Interface (`nautobot.dcim.models.Interface`)
```
PK, device (FK→name only), name, label, status, role, type,
speed, duplex, mtu, mac_address, wwn,
description, enabled, mgmt_only,
lag (parent LAG interface), parent, bridge, virtual_device_context,
mode, untagged_vlan, tagged_vlans
```
**select_related:** `"device", "status", "role", "lag"` (for LAG parent lookup)

#### IPAddress (`nautobot.ipam.models.IPAddress`)
```
PK, address, status, role, dns_name, description,
tenant, vrf, namespace, ip_version
```
**select_related:** `"status", "tenant", "vrf", "namespace"`

#### Prefix (`nautobot.ipam.models.Prefix`)
```
PK, prefix (network), prefix_length, status, role, description,
tenant, vrf, type, namespace, locations (M2M), date_allocated
```
**select_related:** `"status", "role", "tenant", "vrf", "namespace"`

#### VLAN (`nautobot.ipam.models.VLAN`)
```
PK, name, vid, status, role, description,
tenant, group (VLANGroup→name), locations (M2M)
```
**select_related:** `"status", "role", "tenant", "group"`

#### Location (`nautobot.dcim.models.Location`)
```
PK, name, status, location_type (→name), parent (→name),
tenant, description, _custom_field_data (excluded)
```
**select_related:** `"status", "location_type", "parent", "tenant"`

### Nested Object Serialization (D-05)

`model_to_dict()` only handles flat fields. For nested FK/M2M serialization:

```python
from django.forms.models import model_to_dict

def _serialize_device(device: Device) -> dict:
    data = model_to_dict(
        device,
        fields=[...],
        exclude=["created", "last_updated", "custom_field_data",
                 "computed_fields", "description", "comments"],
    )
    # Flatten FK objects inline
    data["device_type"] = device.device_type.display_name  # "DeviceType: Cisco 3850"
    data["manufacturer"] = device.device_type.manufacturer.name
    data["status"] = device.status.name
    data["role"] = device.role.name if device.role else None
    data["platform"] = device.platform.name if device.platform else None
    data["location"] = device.location.name if device.location else None
    data["tenant"] = device.tenant.name if device.tenant else None
    return data
```

For prefetched reverse relations (interfaces on device, ip_addresses on interface), serialize recursively:

```python
def _serialize_interface(interface: Interface) -> dict:
    data = model_to_dict(
        interface,
        fields=["pk", "name", "label", "status", "enabled",
                "type", "mtu", "mac_address", "description"],
        exclude=["created", "last_updated", "custom_field_data",
                 "computed_fields", "comments"],
    )
    # device_name is the natural identifier
    data["device"] = interface.device.name
    data["status"] = interface.status.name if interface.status else None
    # ip_addresses — already prefetched; serialize inline
    if hasattr(interface, "_prefetched_objects_cache") and \
       "ip_addresses" in interface._prefetched_objects_cache:
        data["ip_addresses"] = [
            {"pk": str(ip.pk), "address": ip.address}
            for ip in interface.ip_addresses.all()
        ]
    else:
        # Not prefetched — access carefully (causes N+1; acceptable for single-object tools)
        data["ip_addresses"] = [
            {"pk": str(ip.pk), "address": ip.address}
            for ip in interface.ip_addresses.all()
        ]
    return data
```

### Key Nautobot ORM Patterns (Context7 verified)

- Nautobot uses `RestrictedQuerySet` as the base manager for all permission-controlled models
- `.restrict(user, action="view")` is a method on the queryset that applies Nautobot's ABAC filter
- Prefixes and VLANs in v2.x have `locations` as M2M (was `location` FK in v1) — always use `locations` M2M field
- `device_type` → `.display_name` gives human-readable model name; `.manufacturer.name` gives manufacturer

---

## 2. Django ORM + FastMCP Async Bridging

### The Correct Pattern: `sync_to_async` with `thread_sensitive=True`

Django's ORM is synchronous. FastMCP tool handlers are `async`. The bridge is `asgiref.sync.sync_to_async`:

```python
from asgiref.sync import sync_to_async

# All ORM calls MUST use thread_sensitive=True (PIT-06)
async def device_list_impl(ctx: ToolContext, limit: int = 25) -> PaginatedResult:
    user = get_user_from_request(ctx)

    # Wrap the sync ORM call
    result = await sync_to_async(_sync_device_list, thread_sensitive=True)(
        user=user, limit=limit
    )
    return result
```

**Why `thread_sensitive=True` matters (PIT-06):**
- Django maintains a thread-local database connection pool
- Default `sync_to_async` may use any thread from the anyio pool → connection "already closed" errors
- `thread_sensitive=True` pins all ORM calls to the **same thread** as Django's request thread → connection pool is reused correctly
- The FastMCP → `WsgiToAsgi` → Django bridge ensures a Django request thread context exists

### How the Bridge Works

```
FastMCP async tool handler (anyio thread)
  → sync_to_async(fn, thread_sensitive=True)
  → fn runs on Django's request thread
  → Django ORM access → database connection from pool
```

**The WsgiToAsgi bridge** (from `view.py`): Django's request thread is established when `WsgiToAsgi(app)(request)` is called. `thread_sensitive=True` reuses that thread context.

### No `async_to_sync` in Tool Handlers

`async_to_sync` converts async→sync (useful inside sync Django views). Tool handlers are async, so we only need `sync_to_async`. The `get_mcp_app()` lazy factory in `server.py` is also sync (called from the Django view) — it only sets up the FastMCP server, not ORM calls.

### anyio Thread Pool

FastMCP uses `anyio` for async I/O. `sync_to_async` with default `thread_sensitive=False` dispatches to anyio's thread pool, which is separate from Django's request thread. With `thread_sensitive=True`, anyio picks (or creates) the "sensitive" thread — which is the Django request thread established by `WsgiToAsgi`.

---

## 3. Cursor-Based Pagination

### Cursor Format: `base64(str(pk))` (PAGE-04)

```python
import base64

def _encode_cursor(pk) -> str:
    """Encode a PK as a base64 cursor string. Works for UUID and string PKs."""
    return base64.b64encode(str(pk).encode("utf-8")).decode("ascii")

def _decode_cursor(cursor: str) -> str:
    """Decode a cursor string back to PK value for use in filter."""
    return base64.b64decode(cursor.encode("ascii")).decode("utf-8")
```

**UUID PK handling:** `str(uuid_obj)` → `"a3f8b2c0-..."` → encoded. Decoding returns the string. Django's `UUIDField` accepts string values in `.filter(pk__gt=decoded_str)`.

**PIT-17 confirmed:** Always call `str(pk)` before encoding. Always `.decode("utf-8")` after decoding. The PK value used in `filter(pk__gt=...)` is a string (from `str(pk)`), and Django UUIDField handles the conversion.

### Pagination Algorithm

```python
LIMIT_DEFAULT = 25
LIMIT_MAX = 1000
LIMIT_SUMMARIZE = 100

def paginate_queryset(qs, limit: int = 25, cursor: str | None = None):
    # 1. Decode cursor — apply pk__gt filter if present
    if cursor:
        decoded_pk = _decode_cursor(cursor)
        qs = qs.filter(pk__gt=decoded_pk)

    # 2. Enforce limits
    limit = min(max(1, limit), LIMIT_MAX)

    # 3. Slice: fetch limit+1 to detect has_next
    items = list(qs[: limit + 1])  # evaluate queryset
    has_next = len(items) > limit
    if has_next:
        items = items[:limit]

    # 4. Encode next cursor
    next_cursor = None
    if has_next and items:
        next_cursor = _encode_cursor(items[-1].pk)

    # 5. Build result
    return PaginatedResult(
        items=items,
        cursor=next_cursor,
        total_count=None,
        summary=None,
    )
```

### Count-Before-Slice (PAGE-02, PIT-07)

Auto-summarize fires when **raw queryset count** (before slicing) exceeds 100:

```python
# After slicing:
total_count = qs.count()  # Only when we need it (for summary)
summary = None
if total_count > LIMIT_SUMMARIZE:
    summary = {
        "total_count": total_count,
        "display_count": len(items),
        "message": f"Showing {len(items)} of {total_count} results. "
                   f"Refine your search to see specific records.",
    }
```

**Critical (PIT-07):** Call `qs.count()` on the **original queryset** (before `[:limit+1]` slice). If slicing happens first, the count is always ≤ limit, and auto-summarize never fires.

### Count + Slice Together

```python
def paginate_queryset(qs, limit: int = 25, cursor: str | None = None):
    if cursor:
        qs = qs.filter(pk__gt=_decode_cursor(cursor))
    limit = min(max(1, limit), LIMIT_MAX)

    # Fetch limit+1
    raw_items = list(qs[: limit + 1])
    has_next = len(raw_items) > limit
    items = raw_items[:limit]

    # Build result
    result = PaginatedResult(
        items=items,
        cursor=_encode_cursor(items[-1].pk) if has_next else None,
        total_count=None,
        summary=None,
    )

    # Only count if summarize threshold is relevant
    if len(raw_items) >= LIMIT_SUMMARIZE:
        # Count the full queryset (original, without cursor filter for accurate total)
        result.total_count = qs.count()
        result.summary = {
            "total_count": result.total_count,
            "display_count": len(items),
            "message": f"Showing {len(items)} of {result.total_count} results.",
        }

    return result
```

---

## 4. Nautobot Permissions

### `.restrict(user, action="view")` (AUTH-03)

Every queryset **must** call `.restrict()` before evaluation:

```python
from nautobot.dcim.models import Device

qs = Device.objects.select_related("device_type__manufacturer", ...)
qs = qs.restrict(user, action="view")  # AUTH-03
```

**How it works:** `RestrictedQuerySet` compiles Nautobot's ObjectPermission constraints into SQL `WHERE` clauses. AnonymousUser → `always=False` → empty queryset (no exception).

**Implementation pattern in tools:**

```python
def _sync_device_list(user, limit: int, cursor: str | None) -> PaginatedResult:
    qs = Device.objects.select_related(
        "device_type__manufacturer", "status", "role",
        "platform", "location", "tenant",
    ).restrict(user, action="view")  # Always restrict

    return paginate_queryset(qs, limit=limit, cursor=cursor)
```

**Phase 2 `get_user_from_request()`** returns `AnonymousUser` when no/invalid token. `.restrict(AnonymousUser, "view")` returns empty queryset — correct behavior per AUTH-02.

**Mock assertion pattern for tests:**

```python
with mock.patch.object(Device.objects, "restrict", return_value=empty_qs) as mock_restrict:
    result = await device_list_impl(ctx, limit=25)
    mock_restrict.assert_called_once()
    args, kwargs = mock_restrict.call_args
    assert kwargs.get("action") == "view" or args[1] == "view"  # user, action
```

### Getting User from Request Context

`ctx.request_context.session` → FastMCP session dict
`ctx.request_context.request` → MCP HTTP request (has `Authorization` header)

**Pattern (from `auth.py`):**

```python
from nautobot_app_mcp_server.mcp.auth import get_user_from_request

async def device_list_impl(ctx: ToolContext, limit: int = 25) -> PaginatedResult:
    user = get_user_from_request(ctx)
    return await sync_to_async(_sync_device_list, thread_sensitive=True)(
        user=user, limit=limit, cursor=cursor
    )
```

---

## 5. Tool Registration Pattern

### Module-Level `register_mcp_tool()` (established pattern from `session_tools.py`)

Each tool is defined as a module-level async function, then registered with `register_mcp_tool()` at module import time. This makes tools visible in `MCPToolRegistry` without needing a live FastMCP server.

**D-04: All 10 tools → `scope="core"`, `tier="core"`** (always visible, SESS-06)

**Structure:**

```python
# mcp/tools/core.py
from __future__ import annotations
from typing import TYPE_CHECKING

from fastmcp.server.context import Context as ToolContext
from mcp.types import Tool as ToolInstance

from nautobot_app_mcp_server.mcp import register_mcp_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot_app_mcp_server.mcp.tools.pagination import paginate_queryset
from nautobot_app_mcp_server.mcp.tools.query_utils import (
    _serialize_device,
    _sync_device_list,
    # ...
)

# Tool implementations (sync helpers) — called via sync_to_async
# Tool handlers (async) — called by FastMCP
# register_mcp_tool() — module level, runs on import
```

### Scope Assignment (D-04)

All 10 core tools: `scope="core"`, `tier="core"`.

The progressive disclosure filter (REGI-05) in `_list_tools_handler` always includes `registry.get_core_tools()` — meaning core tools bypass all filtering. Their `scope="core"` means `get_by_scope("core")` would include them, but the `_list_tools_handler` includes core tools unconditionally.

### Registration Constants

```python
TOOLS_SCOPE = "core"
TOOLS_TIER = "core"

register_mcp_tool(
    name="device_list",
    func=_device_list_handler,
    description="List network devices with status, platform, and location.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 25, "description": "..."},
            "cursor": {"type": "string", "description": "..."},
        },
        "additionalProperties": False,
    },
    tier=TOOLS_TIER,
    scope=TOOLS_SCOPE,
)
```

---

## 6. File Structure (from STRUCTURE.md + Phase 2 execution)

### New files for Phase 3

```
mcp/tools/
├── __init__.py                  # exports all tools, registry functions
├── pagination.py                # PaginatedResult, paginate_queryset, cursor encode/decode
├── query_utils.py               # Shared serialization + queryset helpers
└── core.py                      # All 10 tools + meta tool registrations
```

### Imports to wire from `__init__.py`

```python
# mcp/tools/__init__.py
from nautobot_app_mcp_server.mcp.tools.pagination import (
    PaginatedResult,
    paginate_queryset,
)
from nautobot_app_mcp_server.mcp.tools.query_utils import (
    _serialize_device,
    _serialize_interface,
    _serialize_ipaddress,
    _serialize_prefix,
    _serialize_vlan,
    _serialize_location,
)
```

### Module-level registration in `core.py`

All 10 tools + `register_mcp_tool()` calls at module level. The `__init__.py` of the app (`nautobot_app_mcp_server/__init__.py`) already wires `post_migrate` to call core tool registration. Phase 3 tools import `register_mcp_tool` and call it at module level.

---

## 7. Implementation Order Recommendation

Based on dependency analysis:

1. **`pagination.py`** — no dependencies on anything; implement first
2. **`query_utils.py`** — `_serialize_*` helpers; depends on pagination for constants
3. **`core.py` base** — single-object tools (`device_get`, `interface_get`, `ipaddress_get`)
4. **`core.py` list tools** — paginated list tools
5. **`search_by_name`** — multi-model cross-query (PIT-14: highest complexity, do last)
6. **`__init__.py` wiring** — ensure `post_migrate` imports `mcp/tools/__init__`
7. **`test_core_tools.py`** — mock ORM, verify all patterns

---

## 8. Key Sources

| Pattern | Source |
|---|---|
| `model_to_dict()` usage | Django forms/models docs (Context7) |
| `sync_to_async(thread_sensitive=True)` | Django async docs (Context7) |
| Nautobot RestrictedQuerySet + `.restrict()` | Nautobot apps/queryset.md (Context7) |
| Cursor encoding `base64(str(pk))` | PIT-17 (PITFALLS.md) |
| `PaginatedResult` + count-before-slice | PIT-07 (PITFALLS.md) |
| Tool registration pattern | `session_tools.py` module-level registration |
| `get_user_from_request` + `.restrict()` | Phase 2 `auth.py` |
| Device model relationships | Nautobot ERD diagrams (Context7) |
| Prefixes/VLANs locations M2M | Nautobot v2.2 release notes (Context7) |
| Async view + ORM bridge | Django async docs (Context7) |

---

## Validation Architecture

### Requirement → Test File Mapping

| ID | Requirement | Test File | Test Command |
|---|---|---|---|
| TOOL-01 | `device_list` | `test_core_tools.py` | `DeviceListTestCase` |
| TOOL-02 | `device_get` | `test_core_tools.py` | `DeviceGetTestCase` |
| TOOL-03 | `interface_list` | `test_core_tools.py` | `InterfaceListTestCase` |
| TOOL-04 | `interface_get` | `test_core_tools.py` | `InterfaceGetTestCase` |
| TOOL-05 | `ipaddress_list` | `test_core_tools.py` | `IPAddressListTestCase` |
| TOOL-06 | `ipaddress_get` | `test_core_tools.py` | `IPAddressGetTestCase` |
| TOOL-07 | `prefix_list` | `test_core_tools.py` | `PrefixListTestCase` |
| TOOL-08 | `vlan_list` | `test_core_tools.py` | `VLANListTestCase` |
| TOOL-09 | `location_list` | `test_core_tools.py` | `LocationListTestCase` |
| TOOL-10 | `search_by_name` | `test_core_tools.py` | `SearchByNameTestCase` |
| PAGE-01 | `paginate_queryset` defaults | `test_core_tools.py` | `PaginationTestCase` |
| PAGE-02 | Auto-summarize at 100 | `test_core_tools.py` | `PaginationTestCase.test_summarize_at_100` |
| PAGE-03 | `PaginatedResult` dataclass | `test_core_tools.py` | `PaginatedResultTestCase` |
| PAGE-04 | Cursor encode/decode roundtrip | `test_core_tools.py` | `PaginationTestCase.test_cursor_encoding` |
| PAGE-05 | `sync_to_async` thread_sensitive | `test_core_tools.py` | `AsyncBridgeTestCase` |
| TEST-02 | Full `test_core_tools.py` | `test_core_tools.py` | Full file |
| REGI-05 | Progressive disclosure | (Phase 2) | `test_session_tools.py` |
| AUTH-03 | `.restrict()` enforced | `test_core_tools.py` | Mock assertion in each tool test |

### Test Execution

```bash
# Inside Docker container
poetry run nautobot-server test nautobot_app_mcp_server.tests.test_core_tools

# From host
unset VIRTUAL_ENV && poetry run invoke unittest -- -k test_core_tools
```

### Mock Strategy (TEST-02)

All tests use mocked ORM — no real Nautobot database needed:

```python
from unittest.mock import MagicMock, patch
from django.test import TestCase

class DeviceListTestCase(TestCase):
    def setUp(self):
        self.mock_device = MagicMock()
        self.mock_device.pk = "uuid-123"
        self.mock_device.name = "router-01"
        self.mock_device.serial = "SN123"

    @patch("nautobot_app_mcp_server.mcp.tools.query_utils.Device")
    async def test_device_list_returns_paginated_result(self, mock_device_model):
        mock_qs = MagicMock()
        mock_device_model.objects.select_related.return_value = mock_qs
        mock_qs.restrict.return_value = mock_qs
        mock_qs.__getitem__ = lambda self, k: [self.mock_device] if k == slice(0, 26) else [self.mock_device]

        # Verify restrict called with user + "view"
        result = await device_list_impl(self.mock_ctx, limit=25)
        self.assertIn("items", result)
        mock_qs.restrict.assert_called_once()
```

### Exit Gate Verification

After Phase 3 execution:
1. `poetry run invoke pylint` → 10.00/10
2. `poetry run invoke ruff` → clean
3. `poetry run invoke unittest` → all green
4. Coverage ≥ 50% (`coverage report`)

---

*Research completed: 2026-04-02*
*Phase: 03-core-read-tools*
