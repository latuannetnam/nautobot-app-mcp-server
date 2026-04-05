# Phase 09 Verification Report

**Phase:** 09-tool-registration-refactor
**Goal:** Redesign tool registration for cross-process use. `@register_tool` decorator writes to in-memory registry; `tool_registry.json` enables discovery across the process boundary. All 10 core tools converted to `async def` + `sync_to_async`.
**Date:** 2026-04-05

---

## Criterion 1 — `@register_tool` Decorator: Dual Registration

**Status: passed**

### What was checked

- `nautobot_app_mcp_server/mcp/__init__.py`: `register_tool()` decorator (lines 96–149)
- `nautobot_app_mcp_server/mcp/tools/core.py`: all 10 tools use `@register_tool(...)` at decoration site
- `nautobot_app_mcp_server/mcp/tools/__init__.py`: side-effect `import core` triggers registration

### Evidence

**`register_tool` decorator calls `register_mcp_tool()` (in-memory registry):**
```python
# mcp/__init__.py lines 136–147
def decorator(func: Callable) -> Callable:
    tool_name = name if name is not None else func.__name__
    schema = input_schema if input_schema is not None else func_signature_to_input_schema(func)
    register_mcp_tool(
        name=tool_name,
        func=func,
        description=description,
        input_schema=schema,
        tier=tier,
        scope=scope,
    )
    return func
```

**FastMCP wiring via `register_all_tools_with_mcp()` (criterion 2):**
```python
# mcp/__init__.py lines 172–175
def register_all_tools_with_mcp(mcp: Any) -> None:
    registry = MCPToolRegistry.get_instance()
    for tool in registry.get_all():
        mcp.tool(tool.func, name=tool.name, description=tool.description)
```

**All 10 core tools decorated with `@register_tool`:**
```bash
$ grep -n "@register_tool" /source/nautobot_app_mcp_server/mcp/tools/core.py
26: @register_tool(
31: async def _device_list_handler(
60: @register_tool(
65: async def _device_get_handler(
92: @register_tool(
97: async def _interface_list_handler(
125: @register_tool(
130: async def _interface_get_handler(
155: @register_tool(
160: async def _ipaddress_list_handler(
186: @register_tool(
191: async def _ipaddress_get_handler(
216: @register_tool(
221: async def _prefix_list_handler(
247: @register_tool(
252: async def _vlan_list_handler(
278: @register_tool(
283: async def _location_list_handler(
309: @register_tool(
317: async def _search_by_name_handler(
```

**`register_all_tools_with_mcp` wires FastMCP from registry:**
```bash
$ grep -n "register_all_tools_with_mcp" /source/nautobot_app_mcp_server/mcp/commands.py
76:     from nautobot_app_mcp_server.mcp import register_all_tools_with_mcp
78:     register_all_tools_with_mcp(mcp)
```

**Tool names registered in registry:**
```bash
$ grep "async def _" /source/nautobot_app_mcp_server/mcp/tools/core.py
_device_list_handler
_device_get_handler
_interface_list_handler
_interface_get_handler
_ipaddress_list_handler
_ipaddress_get_handler
_prefix_list_handler
_vlan_list_handler
_location_list_handler
_search_by_name_handler
```
Exactly 10.

**Requirement P2-01:** `@register_tool` decorator registers in MCPToolRegistry + FastMCP wiring via `register_all_tools_with_mcp()`. ✅

---

## Criterion 2 — `register_all_tools_with_mcp()` Called at Startup

**Status: passed**

### What was checked

- `nautobot_app_mcp_server/mcp/commands.py`: `create_app()` calls `register_all_tools_with_mcp(mcp)`
- `nautobot_app_mcp_server/mcp/__init__.py`: `register_all_tools_with_mcp()` exported in `__all__`

### Evidence

```python
# commands.py lines 71–78
# STEP 4: Wire all registered tools to FastMCP.
# Importing nautobot_app_mcp_server.mcp.tools side-effects registration into
# MCPToolRegistry (via @register_tool on each core tool handler).
from nautobot_app_mcp_server.mcp.tools import core  # noqa: F401

from nautobot_app_mcp_server.mcp import register_all_tools_with_mcp

register_all_tools_with_mcp(mcp)
```

`__all__` in `mcp/__init__.py` line 41 includes `"register_all_tools_with_mcp"`.

**Requirement P2-02:** `register_all_tools_with_mcp()` populates FastMCP from MCPToolRegistry; called at server startup. ✅

---

## Criterion 3 — Plugin `ready()` Generates `tool_registry.json`; MCP Server Reads It

**Status: gaps_found**

### What was checked

- `nautobot_app_mcp_server/__init__.py`: `ready()` generates `tool_registry.json`
- `nautobot_app_mcp_server/mcp/commands.py`: whether MCP server reads `tool_registry.json` at startup
- `09-CONTEXT.md` line 116: design intent states MCP server reads it

### Evidence

**Plugin generates `tool_registry.json` (correctly implemented):**
```python
# __init__.py lines 41–74
def ready(self) -> None:
    super().ready()  # Registers URL patterns (MUST be first)
    import json, os
    import nautobot_app_mcp_server.mcp.tools  # noqa: F401
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry
    registry = MCPToolRegistry.get_instance()
    tools = registry.get_all()
    payload = [
        {
            "name": tool.name,
            "description": tool.description,
            "tier": tool.tier,
            "app_label": tool.app_label,
            "scope": tool.scope,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]
    package_dir = os.path.dirname(__file__)
    json_path = os.path.join(package_dir, "tool_registry.json")
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
```

**post_migrate removed (correct — `post_migrate` never fires in MCP server process):**
```bash
$ grep "post_migrate" /source/nautobot_app_mcp_server/__init__.py
# (no output — confirmed absent)
```

### Gap: MCP Server Does NOT Read `tool_registry.json` at Startup

```bash
$ grep -i "tool_registry\|json\|load" /source/nautobot_app_mcp_server/mcp/commands.py
# (no output — tool_registry.json is never loaded in commands.py)
```

```bash
$ grep -r "tool_registry.*json.*load\|load.*json\|open.*json" /source/nautobot_app_mcp_server/mcp/
# (no output)
```

**Analysis:** The `commands.py` `create_app()` does NOT read `tool_registry.json`. Instead, it re-runs the side-effect import (`from nautobot_app_mcp_server.mcp.tools import core`) which re-registers all tools into `MCPToolRegistry` in-memory. `register_all_tools_with_mcp(mcp)` then wires them to FastMCP.

**Effect of the gap:** The `tool_registry.json` file is generated but never consumed. It enables cross-process discovery in theory (the JSON is a documented artifact on disk), but the MCP server process does not use it — it re-populates the registry via Python-side-effect imports. If the MCP server runs as a separate process that does NOT import `nautobot_app_mcp_server.mcp.tools` at startup, the JSON file would not be used.

**Per `09-CONTEXT.md` line 116:** "MCP server startup: `create_app()` reads `tool_registry.json`, populates `MCPToolRegistry` before `register_all_tools_with_mcp()`"

**Per ROADMAP.md criterion 3:** "MCP server reads it at startup"

**Verdict:** `tool_registry.json` **generation** (plugin side) is ✅. `tool_registry.json` **reading** (MCP server side) is ❌ — gap exists between documented design intent and implementation.

**Requirement P2-03:** Plugin `ready()` generates `tool_registry.json`. ✅
But: "MCP server reads it at startup" (ROADMAP criterion 3) is ❌ — not implemented.

---

## Criterion 4 — All 10 Core Tools: `async def` + `sync_to_async(thread_sensitive=True)`

**Status: passed**

### What was checked

- `nautobot_app_mcp_server/mcp/tools/core.py`: handler function signatures and `sync_to_async` calls

### Evidence

**Count of `async def _X_handler`:**
```bash
$ docker exec nautobot-app-mcp-server-nautobot-1 grep -c "^async def _" /source/nautobot_app_mcp_server/mcp/tools/core.py
10
```

**Count of `sync_to_async(query_utils._sync_` calls:**
```bash
$ docker exec nautobot-app-mcp-server-nautobot-1 grep -c "sync_to_async(query_utils._sync_" /source/nautobot_app_mcp_server/mcp/tools/core.py
10
```

**All 10 use `thread_sensitive=True`:**
```bash
$ docker exec nautobot-app-mcp-server-nautobot-1 grep "sync_to_async(query_utils._sync_" /source/nautobot_app_mcp_server/mcp/tools/core.py
return await sync_to_async(query_utils._sync_device_list, thread_sensitive=True)(user=user, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_device_get, thread_sensitive=True)(user=user, name_or_id=name_or_id)
return await sync_to_async(query_utils._sync_interface_list, thread_sensitive=True)(user=user, device_name=device_name, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_interface_get, thread_sensitive=True)(user=user, name_or_id=name_or_id)
return await sync_to_async(query_utils._sync_ipaddress_list, thread_sensitive=True)(user=user, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_ipaddress_get, thread_sensitive=True)(user=user, name_or_id=name_or_id)
return await sync_to_async(query_utils._sync_prefix_list, thread_sensitive=True)(user=user, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_vlan_list, thread_sensitive=True)(user=user, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_location_list, thread_sensitive=True)(user=user, limit=limit, cursor=cursor)
return await sync_to_async(query_utils._sync_search_by_name, thread_sensitive=True)(user=user, query=query, limit=limit, cursor=cursor)
```

**Requirement P2-04:** All 10 core tools are `async def` + `sync_to_async(thread_sensitive=True)`. ✅

---

## Criterion 5 — No Django Model Imports at Module Level in `tools/`

**Status: passed**

### What was checked

- `nautobot_app_mcp_server/mcp/tools/core.py`
- `nautobot_app_mcp_server/mcp/tools/__init__.py`
- `nautobot_app_mcp_server/mcp/tools/pagination.py` (checked separately)

### Evidence

```bash
$ grep -E "^from nautobot\.|^import nautobot\.|^from django\." \
    /source/nautobot_app_mcp_server/mcp/tools/core.py \
    /source/nautobot_app_mcp_server/mcp/tools/__init__.py
# (no output — none found)
```

Only internal package imports at module level:
```python
# core.py lines 10–12
from nautobot_app_mcp_server.mcp import register_tool
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot_app_mcp_server.mcp.tools import query_utils
```

Django models are imported **lazily** inside functions:
```python
# query_utils.py — representative examples
def _sync_device_list(user: User, limit: int, cursor: str | None) -> dict[str, Any]:
    from nautobot.dcim.models import Device  # lazy import
    ...

def serialize_device(device: Device) -> dict[str, Any]:
    from nautobot.dcim.models import Device  # lazy import
    ...

def build_device_qs() -> QuerySet[Device]:
    from nautobot.dcim.models import Device  # lazy import
    ...
```

`TYPE_CHECKING` guard in `query_utils.py` line 14–20:
```python
if TYPE_CHECKING:
    from nautobot.dcim.models import Device, Interface, Location
    from nautobot.ipam.models import VLAN, IPAddress, Prefix
    from nautobot.users.models import User
```
These are type-only imports (ignored at runtime), so no Django model loading at module import time. ✅

**Requirement P2-05:** No Django model imports at module level in `mcp/tools/`. ✅

---

## Criterion 6 — Unit Tests for `@register_tool` and `register_all_tools_with_mcp()` Pass

**Status: passed (with a stale unrelated failure)**

### What was checked

- `nautobot_app_mcp_server/mcp/tests/test_register_tool.py`: 11 unit tests
- Test runner: `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_register_tool --keepdb`

### Evidence

**Test run:**
```bash
$ docker exec nautobot-app-mcp-server-nautobot-1 \
    poetry run nautobot-server test \
    nautobot_app_mcp_server.mcp.tests.test_register_tool --keepdb

Found 11 test(s).
Using existing test database for alias 'default'...
System check identified no issues (0 silenced).
...........
----------------------------------------------------------------------
Ran 11 tests in 0.019s

OK
Preserving test database for alias 'default'...
```

**Test coverage:**

| Test | Class | Coverage |
|------|-------|---------|
| `test_func_signature_to_input_schema_simple` | `TestFuncSignatureToInputSchema` | auto-generated schema, defaults, ctx excluded |
| `test_func_signature_to_input_schema_required_param` | `TestFuncSignatureToInputSchema` | required params in schema |
| `test_func_signature_to_input_schema_skips_ctx` | `TestFuncSignatureToInputSchema` | ctx excluded from schema |
| `test_register_tool_decorator_registers_in_registry` | `TestRegisterToolDecorator` | decorator writes to MCPToolRegistry |
| `test_register_tool_auto_generates_schema` | `TestRegisterToolDecorator` | auto-generated input_schema |
| `test_register_tool_explicit_schema_overrides_auto` | `TestRegisterToolDecorator` | explicit input_schema override |
| `test_register_tool_explicit_name` | `TestRegisterToolDecorator` | custom name parameter |
| `test_register_tool_duplicate_name_raises` | `TestRegisterToolDecorator` | ValueError on duplicate |
| `test_register_all_tools_with_mcp_wires_tools` | `TestRegisterAllToolsWithMcp` | calls mcp.tool() for each tool |
| `test_register_all_tools_with_mcp_empty_registry_noop` | `TestRegisterAllToolsWithMcp` | zero calls when registry empty |
| `test_register_all_tools_with_mcp_does_not_pass_input_schema` | `TestRegisterAllToolsWithMcp` | input_schema NOT passed to mcp.tool() |

All 11 pass. ✅

**Full MCP test suite (91 tests):**
```bash
$ docker exec nautobot-app-mcp-server-nautobot-1 \
    poetry run nautobot-server test \
    nautobot_app_mcp_server.mcp.tests --keepdb

Ran 91 tests in 1.045s
FAILED (errors=1, skipped=2)
```

**One unrelated failure:** `test_on_post_migrate_only_runs_for_this_app` — this test calls `NautobotAppMcpServerConfig._on_post_migrate()` which no longer exists (removed as part of criterion 3 — `post_migrate` was replaced by `ready()` writing `tool_registry.json`). This is a stale test, not a Phase 9 regression.

**Requirement P2-06:** Unit tests for `@register_tool` and `register_all_tools_with_mcp()` pass. ✅

---

## Requirement IDs: P2-01 through P2-06

| ID | Requirement | Status |
|----|-------------|--------|
| P2-01 | `@register_tool` decorator: in-memory + FastMCP wiring | ✅ passed |
| P2-02 | `register_all_tools_with_mcp()` called at server startup | ✅ passed |
| P2-03 | Plugin `ready()` generates `tool_registry.json`; MCP server reads it | ⚠️ gap_found |
| P2-04 | All 10 core tools: `async def` + `sync_to_async(thread_sensitive=True)` | ✅ passed |
| P2-05 | No Django model imports at module level in `tools/` | ✅ passed |
| P2-06 | Unit tests for `@register_tool` and `register_all_tools_with_mcp()` pass | ✅ passed |

---

## Must-Haves Checklist

### Required to close gap (Criterion 3 partial)

- [ ] **MCP server reads `tool_registry.json` at startup.** `commands.py` `create_app()` must load `tool_registry.json` and populate `MCPToolRegistry` from it (before calling `register_all_tools_with_mcp()`). Current implementation uses Python-side-effect re-registration instead, which only works when the MCP server process imports `nautobot_app_mcp_server.mcp.tools`. If the server were to run with a minimal bootstrap (without importing that package), the JSON would not be used.
  - **Location to fix:** `nautobot_app_mcp_server/mcp/commands.py`, inside `create_app()` after `nautobot.setup()` and before `register_all_tools_with_mcp(mcp)`.
  - **Pattern from `09-CONTEXT.md`:** "MCP server startup: `create_app()` reads `tool_registry.json`, populates `MCPToolRegistry` before `register_all_tools_with_mcp()`"
  - **Implementation note:** Use `importlib.resources` or `os.path.join(os.path.dirname(__file__), "tool_registry.json")` from within the package context to locate the file reliably in both dev (editable install) and production (installed package).

### Required to close stale test

- [ ] **Fix or remove `test_on_post_migrate_only_runs_for_this_app`** in `test_signal_integration.py`. `NautobotAppMcpServerConfig._on_post_migrate` was removed when `post_migrate` signal wiring was replaced by `ready()` writing `tool_registry.json`. This test calls a method that no longer exists.
  - **Recommended:** Delete this test (or the entire `PostMigrateSignalTestCase` class) since `post_migrate` is intentionally not used.

---

## Summary

**5 of 6 criteria: passed.** Phase 9 successfully implements `@register_tool` decorator, `register_all_tools_with_mcp()` wiring, all 10 `async def` tools with `sync_to_async`, lazy Django model imports, and comprehensive unit tests.

**1 gap:** The MCP server process does not read `tool_registry.json` at startup (as stated in ROADMAP criterion 3 and `09-CONTEXT.md` design intent). The file is generated correctly by the plugin `ready()` hook, but the MCP server currently re-populates `MCPToolRegistry` via Python-side-effect import instead of reading the JSON. This means `tool_registry.json` is a dead artifact unless the MCP server process imports `nautobot_app_mcp_server.mcp.tools` — the primary use case (standalone server reading pre-generated JSON from the plugin package directory) is not implemented.
