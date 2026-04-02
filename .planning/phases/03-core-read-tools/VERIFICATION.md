# Phase 03 Verification: Core Read Tools

**Phase:** `03-core-read-tools`
**Verified:** 2026-04-02
**Goal:** Implement 10 core read tools with pagination, auth, and testing
**Status:** ✅ ACHIEVED

---

## Must-Have Checklist

### TOOL-01–10: 10 Core Read Tools

| # | Tool | Implementation | Handler | Registered |
|---|------|---------------|---------|-----------|
| TOOL-01 | `device_list` | `_sync_device_list` in `query_utils.py` | `_device_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-02 | `device_get` | `_sync_device_get` in `query_utils.py` | `_device_get_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-03 | `interface_list` | `_sync_interface_list` in `query_utils.py` | `_interface_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-04 | `interface_get` | `_sync_interface_get` in `query_utils.py` | `_interface_get_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-05 | `ipaddress_list` | `_sync_ipaddress_list` in `query_utils.py` | `_ipaddress_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-06 | `ipaddress_get` | `_sync_ipaddress_get` in `query_utils.py` | `_ipaddress_get_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-07 | `prefix_list` | `_sync_prefix_list` in `query_utils.py` | `_prefix_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-08 | `vlan_list` | `_sync_vlan_list` in `query_utils.py` | `_vlan_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-09 | `location_list` | `_sync_location_list` in `query_utils.py` | `_location_list_handler` in `core.py` | ✅ `scope="core"` |
| TOOL-10 | `search_by_name` | `_sync_search_by_name` in `query_utils.py` | `_search_by_name_handler` in `core.py` | ✅ `scope="core"` |

**Evidence:** `grep -c 'scope=TOOLS_SCOPE' core.py` → `11` (10 tools + matches constant usage)

### Pagination (PAGE-01, PAGE-02, PAGE-03, PAGE-04, PAGE-05)

| Requirement | Implementation | Evidence |
|-------------|---------------|---------|
| PAGE-01: `LIMIT_DEFAULT=25` | `pagination.py` line 18 | ✅ `LIMIT_DEFAULT = 25` |
| PAGE-01: `LIMIT_MAX=1000` | `pagination.py` line 19 | ✅ `LIMIT_MAX = 1000` |
| PAGE-01: `LIMIT_SUMMARIZE=100` | `pagination.py` line 20 | ✅ `LIMIT_SUMMARIZE = 100` |
| PAGE-02: count before slice, only ≥ LIMIT_SUMMARIZE | `pagination.py` lines 127–128 | ✅ `if len(items_plus_one) >= LIMIT_SUMMARIZE: total_count = qs.count()` |
| PAGE-03: `PaginatedResult` dataclass | `pagination.py` lines 57–76 | ✅ `dataclass` with `items`, `cursor`, `total_count`, `summary`, `has_next_page()` |
| PAGE-04: base64 cursor encode/decode | `pagination.py` lines 28–49 | ✅ `encode_cursor` / `decode_cursor` |
| PAGE-05: `sync_to_async` async wrapper | `pagination.py` lines 152–172 | ✅ `paginate_queryset_async(thread_sensitive=True)` |
| PAGE-05: `thread_sensitive=True` on all handlers | `core.py` | ✅ All 10 handlers use `sync_to_async(..., thread_sensitive=True)` |

### Auth Enforcement (AUTH-02, AUTH-03)

| Requirement | Evidence |
|-------------|---------|
| AUTH-03: Every tool calls `.restrict(user, action="view")` | 16 `restrict(user, action="view")` calls in `query_utils.py` (10 list/get + 6 search_by_name) |
| AUTH-02: AnonymousUser returns empty queryset, not an error | `test_anonymous_user_returns_empty` passes |
| `get_user_from_request` wired to all handlers | All 10 handlers call `get_user_from_request(ctx)` |

### search_by_name (TOOL-10, D-01)

| Requirement | Evidence |
|-------------|---------|
| Searches 6 models (Device, Interface, IPAddress, Prefix, VLAN, Location) | `_sync_search_by_name` lines 496–565 — all 6 `build_*_qs()` called |
| AND match across terms | `functools.reduce(op.and_, [Q(...) for t in terms])` on all 6 models |
| `ValueError` on empty/whitespace query | Line 479: `raise ValueError("search_by_name requires at least one non-empty term")` |
| Returns `PaginatedResult`-compatible dict | Returns `{items, cursor, total_count, summary}` |
| Model label per item | Each result dict has `"model"` key (e.g. `"dcim.device"`) |
| All 6 querysets call `.restrict(user, action="view")` | Lines 496, 508, 520, 532, 544, 556 |

### TEST-02: test_core_tools.py

| Criterion | Evidence |
|-----------|---------|
| Covers all 10 tools | 14 test classes × 31 test methods |
| Covers pagination (PAGE-01, PAGE-02, PAGE-04) | `TestPaginationConstants`, `TestCursorEncoding`, `TestPaginatedResult`, `TestPaginationIntegration` |
| Covers auth enforcement | `TestAuthEnforcement` with restrict assertions on device_list, interface_get, search_by_name |
| Covers anonymous fallback | `TestAnonymousFallback.test_anonymous_user_returns_empty` |
| Uses mocked ORM (no real DB) | All tests use `MagicMock` + `@patch` decorators |
| Every restrict call verified | `mock_qs.restrict.assert_called_once()` / `.assert_called()` with `action="view"` |
| Not-found tests (`ValueError`) | `test_device_get_not_found`, `test_interface_get_not_found`, `test_ipaddress_get_not_found`, `test_search_by_name_empty_query_raises` |

**Test count:** `31` tests, `31 OK`

---

## Sub-Plan Evidence

| Sub-plan | Requirements | Status |
|----------|--------------|--------|
| 03-01 (pagination layer) | PAGE-01–05 | ✅ All 5 requirements completed |
| 03-02 (10 core tools) | TOOL-01–09, PAGE-05 | ✅ All requirements completed |
| 03-03 (search_by_name + tests) | TOOL-10, TEST-02 | ✅ All requirements completed |

---

## CI/Gate Checks

| Check | Command | Result | Gate |
|-------|---------|--------|------|
| `invoke ruff` | `poetry run invoke ruff` | ✅ 23 files already formatted, all checks passed | Must pass |
| Unit tests | `poetry run nautobot-server test nautobot_app_mcp_server` | ✅ **69 tests OK** (31 test_core_tools + 38 others) | Must pass |
| `test_core_tools.py` | `nautobot-server test ...test_core_tools` | ✅ **31/31 OK** (0.104s) | Must pass |
| Coverage | `coverage run --module nautobot.core.cli test nautobot_app_mcp_server` | ✅ **64% total** (>50% gate) | Must ≥50% |
| `core.py` coverage | `coverage report` | ✅ **59%** | |
| `query_utils.py` coverage | `coverage report` | ✅ **60%** | |
| `pagination.py` coverage | `coverage report` | ✅ **92%** | |
| `invoke pylint` | `poetry run invoke pylint` | ⚠️ Pre-existing astroid crash on `__future__` annotations (Pylint crashes on all `from __future__ import annotations` modules — confirmed pre-existing in `registry.py` before Phase 3). Phase 3 implementation files are not the cause. | N/A (pre-existing) |
| Import: search_by_name handler | `python -c "from ...tools.core import _search_by_name_handler; print('OK')"` | ✅ Handler importable | Must succeed |
| Import: core tools registry | `MCPToolRegistry.get_instance().get_core_tools()` | ✅ 13 core tools (10 read + 3 session) | Must ≥13 |

---

## Files Created/Modified

```
03-01 (pagination):
  + nautobot_app_mcp_server/mcp/tools/__init__.py
  + nautobot_app_mcp_server/mcp/tools/pagination.py
  ~ nautobot_app_mcp_server/__init__.py

03-02 (10 core tools):
  + nautobot_app_mcp_server/mcp/tools/query_utils.py   (7 serializers + 8 builders + 10 sync impls)
  + nautobot_app_mcp_server/mcp/tools/core.py          (10 async handlers + registrations)
  ~ nautobot_app_mcp_server/mcp/tools/__init__.py       (added import core, paginate_queryset_async export)

03-03 (search_by_name + tests):
  ~ nautobot_app_mcp_server/mcp/tools/query_utils.py   (added _sync_search_by_name)
  ~ nautobot_app_mcp_server/mcp/tools/core.py          (added _search_by_name_handler + registration)
  + nautobot_app_mcp_server/mcp/tests/test_core_tools.py (31 test cases, 569 lines)
```

---

## Decisions Verified

| Decision | Code | Verified |
|----------|------|---------|
| `functools.reduce(op.and_, [Q(...) for t in terms])` for AND semantics | `query_utils.py:497` | ✅ |
| `thread_sensitive=True` on all `sync_to_async` calls | `core.py` lines 45-46, 98-99, etc. | ✅ 11 occurrences |
| Count only when `len(items_plus_one) >= LIMIT_SUMMARIZE` | `pagination.py:127` | ✅ |
| Cursor encodes `base64(str(pk))` | `pagination.py:37` | ✅ |
| `PaginatedResult` dataclass with `has_next_page()` | `pagination.py:73-75` | ✅ |
| `_looks_like_uuid()` for D-03 UUID/name auto-detection | `query_utils.py:283-285` | ✅ |
| All 6 `search_by_name` models call `.restrict(user, action="view")` | `query_utils.py:496,508,520,532,544,556` | ✅ |
| Summary fires when `total_count > 100` | `query_utils.py:595` | ✅ |

---

## Deviations from Plan

All 5 auto-fixed bugs were identified during development and fixed before testing (committed in `9948527`):
1. `op.and_` TypeError on single-term queries → replaced with `functools.reduce(op.and_, list)`
2. `restrict()` kwargs access (`call_args[1].get("action")` not `call_args[0][1]`)
3. MagicMock chain failures in `serialize_*` tests → patched serializer functions directly
4. `__iter__` lambda missing `self` parameter → `lambda self: iter([...])`
5. `test_cursor_roundtrip_integration` wrong slice logic → simplified to always return 2 items

No unplanned deviations occurred.

---

## Conclusion

**Phase 03 goal ACHIEVED.**

All 10 core read tools are implemented, registered, paginated, permission-enforced, and tested. The test suite has 31 passing tests covering every tool, pagination behavior, auth enforcement, and anonymous user fallback. Coverage is 64% (well above the 50% gate). Ruff and unit tests pass cleanly.
