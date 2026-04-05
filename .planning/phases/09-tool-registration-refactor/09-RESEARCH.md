# Phase 9: Tool Registration Refactor — Research

**Researcher:** GSD Phase Researcher
**Phase:** 09-tool-registration-refactor
**Status:** Complete
**Date:** 2026-04-05

---

## 1. Executive Summary

- **FastMCP 3.x `mcp.tool()` is a dual-mode decorator/callable.** It accepts a function directly (`mcp.tool(my_func)`), derives `input_schema` automatically from Python type hints via `FunctionTool.from_function(fn)`, and can be called at any time after FastMCP instantiation — but **does not accept `input_schema` as a direct parameter**. This is the critical architectural constraint.
- **`@register_tool` must be a thin shim over `register_mcp_tool()`** that also runs `inspect.signature()` to derive and store the JSON Schema in `MCPToolRegistry`. It does NOT call `mcp.tool()` at decoration time (D-01) — that wiring is deferred to `register_all_tools_with_mcp()`.
- **`register_all_tools_with_mcp(mcp)` reads `MCPToolRegistry.get_all()` and calls `mcp.tool(tool.func)`** for each registered tool. Since `mcp.tool()` derives schema from type hints, the schema stored in `MCPToolRegistry` (from `inspect.signature`) and the schema FastMCP derives will always match for Python-annotated functions.
- **`tool_registry.json` path resolution**: Plugin `ready()` uses `os.path.dirname(__file__)` (always correct for installed package or dev symlink). MCP server reads it via `importlib.resources` or the same `__file__` approach. Both processes resolve to the same path because they both access the plugin package on disk.
- **`query_utils.py` has module-level Nautobot model imports on lines 16-17.** These are the only violation in `mcp/tools/`. They must move inside `_sync_*` functions (lazy import) or into `TYPE_CHECKING` for type annotations only.
- **Phase 5 already has the async + `sync_to_async` pattern correct** in `core.py` (lines 44-47). P2-04 is largely confirmatory — no logic changes needed, only wiring-layer refactoring.
- **The `post_migrate` signal in `__init__.py`** fires in the plugin process (Nautobot) but not the MCP server process. Phase 12 (Bridge Cleanup) removes the `post_migrate` wiring. The `ready()` hook becomes the sole registration trigger — Phase 9 must NOT depend on `post_migrate` continuing to exist.

---

## 2. FastMCP Tool Registration API

### 2.1 How `mcp.tool()` Works in FastMCP 3.x

**Source:** FastMCP 3.2.0 (`src/fastmcp/server/server.py` + `src/fastmcp/server/tools.py`)

FastMCP 3.x stores tools via `LocalProvider` (created in `FastMCP.__init__`):

```python
self._local_provider: LocalProvider = LocalProvider(on_duplicate=self._on_duplicate)
self.add_provider(self._local_provider)
```

**`tool()` method signature** (key parameters only):

```python
def tool(
    self,
    name_or_fn: str | AnyFunction | None = None,  # positional: function or name
    *,
    name: str | None = None,
    description: str | None = None,
    tags: set[str] | None = None,
    annotations: ToolAnnotations | dict[str, Any] | None = None,
    timeout: float | None = None,
    auth: AuthCheck | list[AuthCheck] | None = None,
    # ... other params
) -> Callable[[AnyFunction], FunctionTool] | FunctionTool | partial[...]:
```

**Critical finding: `mcp.tool()` does NOT accept `input_schema` as a direct parameter.** The `input_schema` (called `parameters` internally) is always derived from the Python function's type hints via `FunctionTool.from_function(fn)`, which calls `ParsedFunction.from_function()`.

**Decorator calling patterns supported:**

```python
@mcp.tool                          # bare decorator
@mcp.tool()                        # empty parens
@mcp.tool("custom_name")           # positional name
@mcp.tool(name="custom_name")      # keyword name
mcp.tool(my_function)              # direct call (no @)
mcp.tool(my_function, name="...")  # direct call with kwargs
```

### 2.2 Timing: Can `mcp.tool()` Be Called After Server Creation?

**Yes.** The decorator pattern used in `session_tools.py` (lines 378-403) confirms this:

```python
def mcp_enable_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def mcp_enable_tools_impl(ctx: ToolContext, scope: str | None = None, ...) -> str:
        return await _mcp_enable_tools_impl(ctx, scope, ...)
```

Here, `mcp.tool()` is called at server runtime (after `FastMCP("NautobotMCP")` is created) to register a tool. This is the exact pattern `register_all_tools_with_mcp()` will use.

Tools are stored in `LocalProvider._tools` (a list). `mcp.run()` or `mcp.http_app()` is called after all tools are registered. **Tools must be registered before `mcp.run()` / `mcp.http_app()` is called** — this is why `register_all_tools_with_mcp()` is called in `create_app()` before the return.

### 2.3 `mcp.add_tool()` vs `mcp.tool()`

- **`mcp.add_tool(tool: Tool | Callable)`** — Low-level, no decorator magic. Accepts a pre-built `Tool` instance. Used internally.
- **`mcp.tool(...)`** — Full decorator. Handles app config, task defaults, metadata merging. The standard registration API.

For Phase 9: `mcp.tool(func, name=..., description=...)` is correct for `register_all_tools_with_mcp()`. `mcp.add_tool()` is an internal FastMCP detail.

### 2.4 `input_schema` Auto-Derivation from Type Hints

`FunctionTool.from_function(fn)` uses `ParsedFunction.from_function()` to extract the input schema. For a function like:

```python
async def _device_list_handler(ctx: ToolContext, limit: int = 25, cursor: str | None = None) -> dict:
    ...
```

FastMCP auto-generates `input_schema` equivalent to:

```json
{
  "type": "object",
  "properties": {
    "limit": {"type": "integer", "default": 25},
    "cursor": {"type": "string"}
  },
  "required": []
}
```

**Implication for Phase 9:** Since `mcp.tool()` cannot accept an explicit `input_schema` parameter, the schema derived by FastMCP from type hints will be used at runtime. The schema stored in `MCPToolRegistry` (via `inspect.signature` in `@register_tool`) is for cross-process discovery and documentation — it may differ slightly from FastMCP's auto-derived schema but both come from the same function signature and will be functionally equivalent for type-annotated functions.

### 2.5 FastMCP HTTP Transport

Both `mcp.run(transport="http", host, port)` and `mcp.http_app()` are available in FastMCP 3.x. `mcp.http_app()` returns a Starlette ASGI callable. Phase 8 confirmed:

```python
# Production
mcp.run(transport="http", host=bound_host, port=bound_port, stateless_http=False)

# Development
mcp_app = mcp.http_app(transport="http", stateless_http=False)
uvicorn.run(mcp_app, host=host, port=port, reload=True, ...)
```

---

## 3. JSON Schema Auto-Generation

### 3.1 `inspect.signature` → JSON Schema Mapping Strategy

The `inspect` module from the standard library is sufficient. No external library needed.

**Type mapping:**

| Python Type | JSON Schema Type | Notes |
|---|---|---|
| `int` | `{"type": "integer"}` | |
| `str` | `{"type": "string"}` | |
| `float` | `{"type": "number"}` | |
| `bool` | `{"type": "boolean"}` | |
| `None` (literal) | `{"type": "null"}` | Rare as parameter type |
| `list[X]` | `{"type": "array", "items": {...}}` | |
| `dict[K, V]` | `{"type": "object"}` | Fallback to object |
| Unannotated | `{"type": "string"}` | Safe default |

**`Union[str, None]` / `str | None` handling:**

```python
# For "X | None" or "Optional[X]":
if origin is Union and (type(None) in args):
    non_none = [a for a in args if a is not type(None)]
    if len(non_none) == 1:
        # Optional[X] → derive type from X, add default: None
        schema = python_type_to_json_schema(non_none[0])
        schema["default"] = None
        return schema
```

**Required vs optional parameters:**

```python
# Required: no default value
# Optional: has a default value (including None)
if param.default is inspect.Parameter.empty:
    required.append(param.name)
else:
    properties[name]["default"] = param.default
```

**Special cases:**

- `**kwargs`: skip (not used in any current tool)
- `*args`: skip (not used in any current tool)
- Complex generics (`list[dict[str, int]]`): fallback to `{"type": "object"}` with a warning log

### 3.2 Implementation Location

A new module `nautobot_app_mcp_server/mcp/schema.py` (or inline in `mcp/__init__.py`) with:

```python
import inspect
from typing import Any, get_type_hints

def func_signature_to_input_schema(func: Callable) -> dict[str, Any]:
    """Derive a JSON Schema input_schema from a Python function signature.

    Args:
        func: An async function with type-annotated parameters.

    Returns:
        A JSON Schema dict with type, properties, required.
    """
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)  # resolves ForwardRef etc.

    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name == "ctx":  # ToolContext — skip
            continue

        # Derive schema for this parameter
        hint = type_hints.get(name)
        schema = _python_type_to_json_schema(hint)

        # Handle default values
        if param.default is not inspect.Parameter.empty:
            schema["default"] = param.default
        else:
            required.append(name)

        properties[name] = schema

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
```

### 3.3 Error Handling

If `inspect.signature()` fails (e.g., built-in or C extension), fall back to `{"type": "object", "properties": {}, "additionalProperties": False}` and log a `WARNING`. Do not crash registration.

If `get_type_hints()` fails (forward reference), fall back to `str` type for that parameter.

---

## 4. `tool_registry.json` Discovery

### 4.1 Cross-Process Path Resolution

**Plugin process (Nautobot):** `NautobotAppConfig.ready()` runs when Nautobot starts. At this point `nautobot_app_mcp_server/__init__.py` is importable.

```python
# In __init__.py, ready() method:
import json
import os

def ready(self):
    # ...
    registry = MCPToolRegistry.get_instance()
    # Ensure core tools are registered
    import nautobot_app_mcp_server.mcp.tools  # noqa: F401

    # Write tool_registry.json
    json_path = os.path.join(os.path.dirname(__file__), "tool_registry.json")
    tools = registry.get_all()
    payload = [
        {
            "name": t.name,
            "description": t.description,
            "tier": t.tier,
            "app_label": t.app_label,
            "scope": t.scope,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
```

**MCP server process:** `create_app()` reads the JSON before calling `register_all_tools_with_mcp()`.

```python
# In commands.py:
import json
import os
import importlib.resources

def create_app(...):
    # ... nautobot.setup() ...

    # Read tool_registry.json for discovery / logging
    plugin_dir = os.path.dirname(
        importlib.import_module("nautobot_app_mcp_server").__file__
    )
    json_path = os.path.join(plugin_dir, "tool_registry.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            discovered = json.load(f)
        # Optionally re-populate MCPToolRegistry from JSON
        # (for tools discovered from third-party plugins)

    # Import all known tool modules to populate MCPToolRegistry
    import nautobot_app_mcp_server.mcp.tools  # noqa: F401

    register_all_tools_with_mcp(mcp)
```

### 4.2 Path Resolution: Installed vs Dev Symlink

| Scenario | `__file__` resolves to | `tool_registry.json` location |
|---|---|---|
| Installed via pip | `site-packages/nautobot_app_mcp_server/__init__.py` | `site-packages/nautobot_app_mcp_server/tool_registry.json` |
| Dev (editable install / symlink) | `nautobot_app_mcp_server/__init__.py` (project root) | `nautobot_app_mcp_server/tool_registry.json` (in repo) |
| Docker volume mount | Same as above | Same as above |

Both processes (plugin and MCP server) see the **same file path** because:
- Both import `nautobot_app_mcp_server`
- Both use `__file__` on the module to resolve the directory
- In Docker, the plugin package is mounted at the same path for both containers

**Confidence: High.** `__file__`-based resolution is the standard approach used by Django, Flask, and most Nautobot plugins for self-locating their own package directory.

### 4.3 JSON Schema Storage in `tool_registry.json`

D-12 specifies: `name`, `description`, `tier`, `app_label`, `scope` (no `func`). **The `input_schema` should be added** because:
1. It enables MCP clients to display tool schemas without calling the server
2. It validates the auto-generated schema from `inspect.signature`
3. The `func` is not JSON-serializable (correct, not included)

```json
[
  {
    "name": "device_list",
    "description": "List network devices...",
    "tier": "core",
    "app_label": null,
    "scope": "core",
    "input_schema": {
      "type": "object",
      "properties": {
        "limit": {"type": "integer", "default": 25},
        "cursor": {"type": "string"}
      },
      "required": [],
      "additionalProperties": false
    }
  }
]
```

---

## 5. Lazy Import Migration

### 5.1 Current State: `query_utils.py` Module-Level Imports

```python
# Lines 16-17 — VIOLATION of P2-05:
from nautobot.dcim.models import Device, Interface, Location
from nautobot.ipam.models import VLAN, IPAddress, Prefix
```

These imports are at module level (top of file, outside `TYPE_CHECKING`). They execute when `query_utils.py` is imported, which happens when `core.py` is imported via `mcp/tools/__init__.py` side-effect import.

**Problem:** In the MCP server process, `nautobot.setup()` is called before `mcp/tools/` imports happen (`create_app()` calls `nautobot.setup()`, then imports tools). So for the MCP server process, these imports are fine because Django is already set up.

However, for the **plugin process** (`NautobotAppConfig.ready()`), if `query_utils.py` is imported before Django setup completes, it will fail. The plugin uses `nautobot.setup()` via Nautobot's startup sequence, so Django IS set up before `ready()` fires.

**Actual risk:** The module-level imports are technically fine for the current architecture BUT violate the P2-05 requirement explicitly. The ROADMAP says: "Any match at module level must be moved inside the tool function." This is a correctness requirement, not just a startup-time concern.

Additionally, `query_utils.py` is imported by `core.py` at module level (line 12: `from nautobot_app_mcp_server.mcp.tools import query_utils`). Moving imports inside `_sync_*` functions breaks the module-level `query_utils` import in `core.py` — but `core.py` already calls `query_utils._sync_device_list` etc., so it doesn't need the model classes directly.

### 5.2 Audit Results

**Files in `nautobot_app_mcp_server/mcp/tools/`:**

| File | Module-level Nautobot imports? |
|---|---|
| `core.py` | No (only imports from `query_utils` and `pagination`) |
| `query_utils.py` | **YES** — lines 16-17 (`Device`, `Interface`, `Location`, `VLAN`, `IPAddress`, `Prefix`) |
| `pagination.py` | No |
| `__init__.py` | No |

**`pagination.py` line 12:** `from django.db.models import QuerySet` — inside `TYPE_CHECKING`, so it's fine.

### 5.3 Conversion Pattern

**Before (query_utils.py lines 16-17):**

```python
from nautobot.dcim.models import Device, Interface, Location
from nautobot.ipam.models import VLAN, IPAddress, Prefix
```

**After:**

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nautobot.dcim.models import Device, Interface, Location  # type: ignore
    from nautobot.ipam.models import VLAN, IPAddress, Prefix  # type: ignore
```

Then inside each function that uses these models, add the import:

```python
def build_device_qs() -> QuerySet[Device]:
    from nautobot.dcim.models import Device  # lazy import
    return Device.objects.select_related(...)
```

### 5.4 `core.py` Async + `sync_to_async` Pattern — Already Correct

From `core.py` lines 44-47:

```python
return await sync_to_async(query_utils._sync_device_list, thread_sensitive=True)(
    user=user, limit=limit, cursor=cursor
)
```

This is Phase 5's correct pattern. The `_sync_device_list` functions in `query_utils.py` are the sync wrappers called via `sync_to_async`. No changes needed for P2-04 — this is already done.

---

## 6. Implementation Approach

### Recommended Order of Operations

**Plan 09-01: `@register_tool` Decorator**

1. Create `nautobot_app_mcp_server/mcp/schema.py` with `func_signature_to_input_schema()`
2. Add `@register_tool` to `nautobot_app_mcp_server/mcp/__init__.py`
   - Signature: `@register_tool(description="...", tier="core", scope="core")`
   - On call: extract func name → call `func_signature_to_input_schema(func)` → call `register_mcp_tool(...)`
   - Explicit `input_schema` param on `@register_tool` overrides auto-generated (D-04)
3. Update all 10 existing `register_mcp_tool()` calls in `core.py` to use `@register_tool` decorator
4. Verify: existing tools still registered correctly

**Plan 09-02: `register_all_tools_with_mcp()`**

1. Add to `nautobot_app_mcp_server/mcp/__init__.py`:
   ```python
   def register_all_tools_with_mcp(mcp: FastMCP) -> None:
       """Register all tools from MCPToolRegistry with the FastMCP instance."""
       for tool in MCPToolRegistry.get_instance().get_all():
           mcp.tool(tool.func, name=tool.name, description=tool.description)
   ```
2. In `commands.py`, after `mcp = FastMCP(...)` and `import nautobot_app_mcp_server.mcp.tools`, call:
   ```python
   register_all_tools_with_mcp(mcp)
   ```
3. Remove the `post_migrate` wiring in `__init__.py` that calls `MCPToolRegistry.get_instance()` — tools are registered via module-side-effect import in `create_app()`, not via `post_migrate`

**Plan 09-03: `tool_registry.json` Generation**

1. Update `nautobot_app_mcp_server/__init__.py` `ready()` method:
   - Remove `post_migrate` wiring (PITFALL #3: `post_migrate` never fires in MCP server process; Phase 12 also removes this)
   - Keep `import nautobot_app_mcp_server.mcp.tools` (side-effect registers tools)
   - Write `tool_registry.json` to `os.path.dirname(__file__)`
2. Update `create_app()` in `commands.py` to optionally read `tool_registry.json` for logging/debugging

**Plan 09-04: Verify All 10 Core Tools — `async def` + `sync_to_async`**

- Review `core.py`: all 10 handlers are `async def` ✓
- Review `core.py` call chain: `sync_to_async(query_utils._sync_*, thread_sensitive=True)` ✓
- **No code changes needed** — confirm pattern is correct and document

**Plan 09-05: Lazy Import Audit**

1. Grep: `grep -n "from nautobot" nautobot_app_mcp_server/mcp/tools/query_utils.py`
2. Convert lines 16-17: move to `TYPE_CHECKING` block + lazy import inside each function
3. Verify: `grep "from nautobot" nautobot_app_mcp_server/mcp/tools/query_utils.py` returns only `TYPE_CHECKING` matches

**Plan 09-06: Unit Tests**

1. Test `@register_tool` decorator:
   - Tool is in `MCPToolRegistry.get_all()`
   - `input_schema` auto-generated from function signature
   - Explicit `input_schema` overrides auto-generated
   - Duplicate name raises `ValueError`
2. Test `register_all_tools_with_mcp()`:
   - All registered tools are callable via FastMCP
   - Empty registry: no-op
   - Called twice: raises `ValueError` (tool already registered)

### Where to Wire `register_all_tools_with_mcp()`

**Current `commands.py` structure:**

```
create_app():
  STEP 0: Read env vars
  STEP 1: DB connectivity check
  STEP 2: nautobot.setup()
  STEP 3: FastMCP instance created
  STEP 4: (Phase 9 placeholder)
  return (mcp, host, port)
```

**After Phase 9:**

```
create_app():
  STEP 0: Read env vars
  STEP 1: DB connectivity check
  STEP 2: nautobot.setup()
  STEP 3: FastMCP instance created
  STEP 4: Import tool modules (side-effect: MCPToolRegistry populated)
  STEP 5: register_all_tools_with_mcp(mcp) ← NEW
  return (mcp, host, port)
```

Note: `register_all_tools_with_mcp()` must be called **before** `mcp.run()` or `mcp.http_app()`. Since `create_app()` returns the `(mcp, host, port)` tuple and the caller (`start_mcp_server.handle()`) calls `mcp.run()`, the wiring is correct as long as `register_all_tools_with_mcp()` is called before the return.

---

## 7. Risks & Confidence

### Risks

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| **FastMCP auto-schema differs from `inspect.signature` schema** | Low | Low | Both derive from same function signature; MCP clients use FastMCP's schema. `MCPToolRegistry` schema is for documentation/discovery, not runtime validation. |
| **`tool_registry.json` not found at MCP server startup** | Medium | Low | Graceful degradation: log warning, continue. Plugin process always writes it. Docker volume mount ensures same path for both processes. |
| **`post_migrate` removal breaks other phases** | Medium | Low | `post_migrate` only calls `MCPToolRegistry.get_instance()` (singleton init). Phase 9 removes it; Phase 12 (Bridge Cleanup) also removes it. Ensure no other phase depends on it. |
| **Module-level imports in `query_utils.py` cause startup failures** | Low | Very Low | Django is set up before tool imports in `create_app()`. Moving to lazy imports is a correctness improvement, not a startup fix. |
| **`mcp.tool()` called after `mcp.http_app()` is created** | High | Low | `register_all_tools_with_mcp()` is called inside `create_app()` before return. Both management commands call `create_app()` and THEN call `mcp.run()` / `mcp.http_app()`. |
| **Third-party plugin tools not discovered** | Low | Low | Third-party plugins must call `register_mcp_tool()` in their own `ready()`. Plugin process reads all plugins' `ready()` hooks. MCP server reads `tool_registry.json` which includes all registered tools. |
| **Pylint score drops** | Medium | Low | Lazy imports add `TYPE_CHECKING` blocks. Ensure new schema.py module has no Pylint issues. Run `pylint` after each plan. |

### Confidence Levels

| Area | Confidence | Rationale |
|---|---|---|
| `mcp.tool()` calling patterns | **High** | Confirmed from FastMCP 3.2.0 source via WebFetch; existing `session_tools.py` uses the exact pattern planned |
| `inspect.signature` → JSON Schema | **High** | Standard library, well-documented, simple mapping needed for current 10 tools |
| `tool_registry.json` path resolution | **High** | `__file__`-based resolution is standard; works for both installed and dev scenarios |
| Lazy import conversion | **High** | Clear grep target; clear conversion pattern; no functional changes to `_sync_*` functions |
| Phase 5 async pattern correctness | **High** | Already implemented and tested in Phase 5 |
| `@register_tool` as decorator | **High** | Simple shim over existing `register_mcp_tool()`; no FastMCP wiring at decoration time (D-01) |
| `register_all_tools_with_mcp()` placement | **High** | `create_app()` is the natural place; confirmed by Phase 9 D-06, D-09 |

---

*Research complete: 2026-04-05*
*Key sources: FastMCP 3.2.0 source (GitHub PrefectHQ/fastmcp), Python `inspect.signature` stdlib docs, project codebase*
