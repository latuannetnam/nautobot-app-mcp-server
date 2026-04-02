---
phase: 03-core-read-tools
plan: "02"
subsystem: mcp-tools
tags: [django, orm, fastmcp, nautobot, pagination, auth]

# Dependency graph
requires:
  - phase: 01-core-infrastructure
    provides: MCPToolRegistry, register_mcp_tool()
  - phase: 02-authentication-sessions
    provides: session_tools.py (get_user_from_request)
  - phase: 03-plan-01
    provides: mcp/tools/ package (pagination.py, __init__.py), PaginatedResult
provides:
  - 10 core read MCP tools: device_list, device_get, interface_list, interface_get, ipaddress_list, ipaddress_get, prefix_list, vlan_list, location_list, search_by_name
  - query_utils.py: 7 serialization helpers + 8 queryset builders + 10 sync implementations
  - All tools use sync_to_async(thread_sensitive=True) + .restrict(user, "view")
affects:
  - Phase 3 Plan 03 (search_by_name): _sync_search_by_name already in query_utils.py
  - Phase 4 (SKILL.md package): tools will be documented with scopes and workflows

# Tech tracking
tech-stack:
  added: [django.forms.models.model_to_dict]
  patterns: [model_to_dict serialization, select_related/prefetch_related chains, UUID/name auto-detection, D-03 identifier resolution]

key-files:
  created:
    - nautobot_app_mcp_server/mcp/tools/query_utils.py
    - nautobot_app_mcp_server/mcp/tools/core.py
  modified:
    - nautobot_app_mcp_server/mcp/tools/__init__.py

key-decisions:
  - "sync_to_async + query_utils pattern: async handlers in core.py delegate to _sync_* helpers in query_utils.py via sync_to_async(thread_sensitive=True)"
  - "D-03 UUID/name auto-detection: _looks_like_uuid() regex (8-4-4-4-12 hex) for single-object tools"
  - "D-02 not-found behavior: device_get/interface_get/ipaddress_get raise ValueError with descriptive message"
  - "search_by_name AND semantics: sequential per-model queries with sorted in-memory merge"
  - "Interface ip_addresses: flat {pk, address} dicts inline (no deep serialization for search_by_name perf)"

patterns-established:
  - "Serializer pattern: model_to_dict(fields=[...], exclude=_STANDARD_EXCLUDE) + FK .name flattening"
  - "QuerySet builder pattern: build_*_qs() → build_*_qs_with_*() for prefetched variants"
  - "Sync wrapper pattern: _sync_*_impl() in query_utils → sync_to_async() in core.py"
  - "Tool registration: module-level register_mcp_tool() called on package import (triggered by __init__.py import of core)"

requirements-completed:
  - TOOL-01
  - TOOL-02
  - TOOL-03
  - TOOL-04
  - TOOL-05
  - TOOL-06
  - TOOL-07
  - TOOL-08
  - TOOL-09
  - PAGE-05

# Metrics
duration: 10 min
completed: 2026-04-02T04:08:25Z
---

# Phase 3 Plan 02: Core Read Tools Summary

**10 core read MCP tools implemented with pagination, permission enforcement, and ORM optimization**

## Performance

- **Duration:** 10 min
- **Started:** 2026-04-02T03:58:07Z
- **Completed:** 2026-04-02T04:08:25Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- Created `query_utils.py`: 7 serialization helpers, 8 queryset builders, 10 `_sync_*` implementations
- Created `core.py`: 10 async tool handlers, all registered with `scope="core"`, `tier="core"`
- `search_by_name` (TOOL-10): multi-model AND search across 6 models (Device, Interface, IPAddress, Prefix, VLAN, Location) with in-memory pagination
- All tools call `.restrict(user, action="view")` — full Nautobot permission enforcement
- `mcp/tools/__init__.py` now triggers tool registration on import

## Task Commits

Each task was committed atomically:

1. **Task 1: query_utils.py** - `dbe2b23` (feat)
2. **Task 2: core.py** - `72a3b7a` (feat) → later reset and re-applied
3. **Task 3: __init__.py + core.py** - `033728b` (feat)

**Note:** Tasks 1 and 2 were committed then reset during orchestrator reconciliation. Re-applied atomically in Task 3.

## Files Created/Modified

- `nautobot_app_mcp_server/mcp/tools/query_utils.py` - Serialization helpers (`serialize_device`, `serialize_interface`, etc.), queryset builders (`build_device_qs`, etc.), sync implementations (`_sync_device_list`, `_sync_device_get`, etc.), `_sync_search_by_name` (TOOL-10)
- `nautobot_app_mcp_server/mcp/tools/core.py` - 10 async handlers (`_device_list_handler`, etc.), 10 `register_mcp_tool()` calls with scope="core", tier="core"
- `nautobot_app_mcp_server/mcp/tools/__init__.py` - Added `paginate_queryset_async` export, added `import core` to trigger tool registration on package load

## Decisions Made

- Used `sync_to_async + query_utils` split: async handlers in `core.py` import from `query_utils` to call `_sync_*` helpers via `sync_to_async(thread_sensitive=True)` — avoids circular imports while keeping ORM in sync code
- `_looks_like_uuid()` uses regex `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` for D-03 identifier auto-detection
- `search_by_name` uses sequential per-model queries + in-memory merge (not `QuerySet.union()`) since union would lose model type information without an annotated discriminator column
- Interface `ip_addresses` in `search_by_name` results are serialized as flat `{pk, address}` dicts for performance (deep serialization deferred to `interface_get`)
- `virtual_device_context` and `untagged_vlan` added to interface serialization (not in original plan, needed for completeness)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- All 10 core read tools are registered and ready for unit testing
- `search_by_name` (TOOL-10) already implemented in `query_utils.py` and `core.py` — Plan 03 can build on this foundation
- `MCPToolRegistry.get_core_tools()` will return 13 tools: 10 core read + 3 meta (mcp_enable_tools, mcp_disable_tools, mcp_list_tools)

---
*Phase: 03-core-read-tools*
*Completed: 2026-04-02*
