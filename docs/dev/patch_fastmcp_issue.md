# FastMCP Output Schema Conflict — Resolution

**Issue:** "fastmcp-output-schema-conflict"
**Resolved:** 2026-04-07

---

## Problem

FastMCP 3.2.0 `FunctionTool.from_function()` auto-derives `output_schema` from
return type annotations (`dict[str, Any]` → `{"type": "object"}`). When the
HTTP transport (`StreamableHTTPSessionManager`) handles a `call_tool` request,
the MCP SDK validates the tool's `outputSchema` against the returned content:

```python
# mcp/server/lowlevel/server.py handle_call_tool():
if tool.outputSchema is not None:
    if maybe_structured_content is None:  # ← always None for plain dict returns
        return error: "Output validation error: outputSchema defined but no structured output returned"
```

Our tool functions return `dict[str, Any]`. FastMCP wraps this as
`{"type": "object"}`. The SDK sees `outputSchema is not None` but
`structuredContent is None`, and returns the error. All dict-returning tools
(`device_get`, `interface_list`, `ipaddress_list`, `prefix_list`, `vlan_list`,
`location_list`, `search_by_name`) fail.

**Note:** The SSE transport (`mcp.sse_app()`) was never affected because it
bypasses the MCP SDK's `handle_call_tool()` entirely.

---

## Solution

Pass `output_schema=None` explicitly in `register_all_tools_with_mcp()`.

**File:** `nautobot_app_mcp_server/mcp/__init__.py`

```python
mcp.tool(tool.func, name=tool.name, description=tool.description, output_schema=None)
```

This prevents FastMCP from auto-deriving an outputSchema. The MCP SDK then
skips validation and returns the plain text content (JSON dump of the dict).

---

## Why This Works

FastMCP's `FunctionTool.from_function()` uses a sentinel `NotSet` to decide
whether to auto-derive:

```python
if isinstance(metadata.output_schema, NotSetT):
    final_output_schema = parsed_fn.output_schema  # auto-derive
else:
    final_output_schema = metadata.output_schema    # use explicit value
```

With `output_schema=None`, `final_output_schema = None`, so
`tool.outputSchema = None`. The SDK's validation check
`if tool.outputSchema is not None` is never triggered.

---

## Previous Workaround (No Longer Needed)

The in-container patch to
`/usr/local/lib/python3.12/site-packages/fastmcp/tools/function_tool.py` line 234:

```python
# ❌ DO NOT USE — does not survive `invoke build`
output_schema=None,  # Force None to avoid MCP SDK output validation errors
```

This was a temporary fix applied inside the running container. It does NOT
survive `invoke build` because the Docker image is rebuilt from
`development/Dockerfile`. The source-controlled fix above replaces it entirely.

---

## Verification

```bash
# Inside the MCP server container:
docker exec nautobot-app-mcp-server-mcp-server-1 bash -c "python /source/scripts/test_mcp_simple.py"
# → All smoke tests PASSED

docker exec nautobot-app-mcp-server-mcp-server-1 bash -c "python /source/scripts/run_mcp_uat.py"
# → UAT Results: 37/37 passed
```

The fix is inside `nautobot_app_mcp_server/mcp/__init__.py`, which is copied
into the Docker image via `COPY . /source` in `development/Dockerfile`, so it
survives `invoke build`.
