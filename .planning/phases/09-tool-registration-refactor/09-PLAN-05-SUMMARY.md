---
phase: 09-tool-registration-refactor
plan: 5
subsystem: core
tags: [lazy-import, TYPE_CHECKING, django-orm, nautobot]

dependency-graph:
  requires:
    - phase: 09-01
      provides: "@register_tool decorator and MCPToolRegistry plumbing"
  provides:
    - Nautobot model imports moved to TYPE_CHECKING block in query_utils.py
    - 22 lazy imports added inside functions (avoids module-level ORM coupling)
  affects:
    - Phase 09-06
    - Phase 10 (session state)
    - Phase 11 (auth refactor)

tech-stack:
  added: []
  patterns:
    - "Lazy import pattern: move module-level Nautobot model imports to TYPE_CHECKING, add inline imports in functions"
    - "Consistent lazy import comment: '# lazy import — avoids module-level Nautobot model import'"

key-files:
  created: []
  modified:
    - nautobot_app_mcp_server/mcp/tools/query_utils.py

key-decisions:
  - "All 6 Nautobot models (Device, Interface, Location, VLAN, IPAddress, Prefix) moved to TYPE_CHECKING block — only available for type annotations"
  - "22 functions received lazy imports — lazy import comment used consistently for grep-verification"
  - "serialize_device_with_interfaces uses serialize_device() — no new import needed (delegation)"
  - "build_interface_qs_with_ip_addresses uses build_interface_qs() — no new import needed"
  - "build_ipaddress_qs_with_interfaces uses build_ipaddress_qs() — no new import needed"
  - "_sync_search_by_name uses builder functions only — no new imports needed"

patterns-established:
  - "Pattern: Move module-level Nautobot model imports to TYPE_CHECKING + add lazy imports inside functions"
  - "Pattern: Comment format 'lazy import — avoids module-level Nautobot model import' for grep verifiability"

requirements-completed:
  - "grep -n 'from nautobot.dcim.models import\\|from nautobot.ipam.models import' query_utils.py at end of task returns zero matches outside TYPE_CHECKING block"
  - "grep -c 'lazy import' query_utils.py >= 20"
  - "All 10 core tools still work (90/91 MCP tests pass — 1 pre-existing failure in test_signal_integration.py)"

metrics:
  duration: ~10min
  completed: 2026-04-05
---

# Phase 09-05: Lazy Import Audit Summary

**Nautobot model imports refactored to TYPE_CHECKING + 22 lazy imports in query_utils.py functions**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-04-05
- **Completed:** 2026-04-05
- **Tasks:** 1
- **Files modified:** 1 (`query_utils.py`)

## Accomplishments
- Moved module-level `from nautobot.dcim.models import Device, Interface, Location` and `from nautobot.ipam.models import VLAN, IPAddress, Prefix` from lines 16-17 to `TYPE_CHECKING` block
- Added lazy import inside each of 22 functions that reference the models (via type annotations or direct use)
- All 90 MCP tests pass (1 pre-existing failure in `test_signal_integration.py` unrelated to this change)

## Task Commits

Each task was committed atomically:

1. **Task 1: Lazy Import Audit** - `571e7c0` (refactor)

**Plan metadata:** `571e7c0` (docs: plan complete)

## Files Created/Modified
- `nautobot_app_mcp_server/mcp/tools/query_utils.py` - Moved 6 Nautobot model imports to TYPE_CHECKING; added 22 lazy imports in function bodies

## Decisions Made

- **Consistent lazy import comment:** Used `"# lazy import — avoids module-level Nautobot model import"` on every lazy import line for grep verifiability
- **Delegation optimization:** Functions that call other functions (`serialize_device_with_interfaces`, `build_interface_qs_with_ip_addresses`, `build_ipaddress_qs_with_interfaces`, `_sync_search_by_name`) skip redundant lazy imports — the delegate function already has its own
- **All 6 models in TYPE_CHECKING:** Both dcim and ipam model imports go in the same `TYPE_CHECKING` block, with `User` from `nautobot.users.models`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - grep verification confirmed:
- `grep -c "lazy import" query_utils.py` → **22** (≥20 ✓)
- `grep -n "from nautobot.dcim.models import\|from nautobot.ipam.models import" query_utils.py | grep -v TYPE_CHECKING` → **zero matches** (only lines 18-19 inside `if TYPE_CHECKING:` block)

## Next Phase Readiness

- `query_utils.py` now fully lazy — no module-level coupling to Nautobot models
- Ready for Phase 09-06 or subsequent phases
- No blockers

---
*Phase: 09-tool-registration-refactor (plan 5)*
*Completed: 2026-04-05*
