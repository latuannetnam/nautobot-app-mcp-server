# Debug: fastmcp-output-schema-conflict

**Date:** 2026-04-07
**Status:** FIXED

---

## Summary

FastMCP 3.2.0 `FunctionTool.from_function()` auto-derives an `output_schema` from return
type annotations (e.g. `dict[str, Any]` → `{"type": "object"}`). When the
`StreamableHTTPSessionManager` path is used (HTTP transport), the MCP SDK's
low-level `handle_call_tool()` validates the output: if `tool.outputSchema is not None`
and `structuredContent is None`, it returns an error.

The conflict: our tool functions return `dict[str, Any]`. FastMCP sets
`outputSchema={"type": "object"}` on the Tool. When `convert_result()` runs, it
produces `content=[TextContent(...)]` with `structuredContent=None` (the SDK
path doesn't populate structuredContent for plain dict returns). The MCP SDK
sees `outputSchema is not None` and `structuredContent is None`, fires the
validation error, and all dict-returning tools fail.

---

## Root Cause Chain

```
register_all_tools_with_mcp()
  → mcp.tool(func, name=..., description=...)          # no output_schema passed
    → Tool.from_function(fn, ..., output_schema=NotSet)  # NotSet sentinel
      → FunctionTool.from_function()
        → metadata.output_schema is NotSet
          → final_output_schema = parsed_fn.output_schema   ← auto-derived
            → parsed_fn.output_schema = {"type": "object"}  ← from dict[str, Any]

tool.outputSchema = {"type": "object"}               # stored on the Tool

MCP HTTP request:
  StreamableHTTPSessionManager.handle_request()
    → FastMCP._call_tool_mcp()
      → FunctionTool.run() → convert_result() → ToolResult(content=[...], structuredContent=None)

MCP SDK lowlevel.handle_call_tool():
  if tool.outputSchema is not None:                 ← TRUE ({"type": "object"})
      if maybe_structured_content is None:           ← TRUE
          return error: "Output validation error: outputSchema defined but no structured output returned"
```

**Why the SSE transport was unaffected:** The original `mcp.sse_app()` path does not
go through the MCP SDK's `handle_call_tool()` — FastMCP handles it directly in its
SSE session handler, which has no outputSchema validation.

---

## Fix Applied

**Option A — Explicit `output_schema=None` in `register_all_tools_with_mcp()`**

File: `nautobot_app_mcp_server/mcp/__init__.py`

```python
# BEFORE:
mcp.tool(tool.func, name=tool.name, description=tool.description)

# AFTER:
mcp.tool(tool.func, name=tool.name, description=tool.description, output_schema=None)
```

**Mechanism:** `output_schema=None` is passed explicitly to `FunctionTool.from_function()`.
The sentinel check:

```python
if isinstance(metadata.output_schema, NotSetT):
    final_output_schema = parsed_fn.output_schema   # SKIPPED — None is not NotSet
else:
    final_output_schema = metadata.output_schema    # None wins
```

results in `final_output_schema = None`, so the Tool is created with
`outputSchema=None`. The MCP SDK's validation branch:

```python
if tool.outputSchema is not None:   # FALSE — None
    if maybe_structured_content is None:
        return error
```

is never entered. The `content=[TextContent(json.dumps(dict))]` is returned
normally.

**Option B (not used):** A startup monkey-patch to
`FunctionTool.from_function()` in `commands.py` would also work but requires
import-time patching before tools are registered. Option A is cleaner.

---

## Verification

```bash
# Smoke test (ran from MCP server container, /source is volume-mounted):
docker exec nautobot-app-mcp-server-mcp-server-1 bash -c "python /source/scripts/test_mcp_simple.py"
# ✅ All smoke tests PASSED

# Full UAT suite:
docker exec nautobot-app-mcp-server-mcp-server-1 bash -c "python /source/scripts/run_mcp_uat.py"
# ✅ UAT Results: 37/37 passed
```

---

## What Was Changed

| File | Change |
|---|---|
| `nautobot_app_mcp_server/mcp/__init__.py` | Added `output_schema=None` to `mcp.tool()` call in `register_all_tools_with_mcp()` + explanatory comment |

---

## Remaining Concerns

- **No remaining concerns.** The fix is clean, minimal, and survives `invoke build`
  because `COPY . /source` in `development/Dockerfile` includes our source.
- The `MCPToolRegistry` still has `output_schema: dict[str, Any] | None = None`
  on `ToolDefinition` — this is for cross-process discovery
  (`tool_registry.json`) and is NOT passed to FastMCP, so it does not
  interfere.
