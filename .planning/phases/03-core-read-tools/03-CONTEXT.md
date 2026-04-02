# Phase 3: Core Read Tools - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement all 10 core read tools (device_list, device_get, interface_list, interface_get, ipaddress_list, ipaddress_get, prefix_list, vlan_list, location_list, search_by_name) and 3 meta tools, with a cursor-based pagination layer, Nautobot ORM serialization, and permission enforcement. Write `test_core_tools.py` with ORM mocking. Write tools are out of scope (Phase 4 is SKILL.md package).

</domain>

<decisions>
## Implementation Decisions

### Search query format
- **D-01:** `search_by_name` uses AND match across terms — all terms must appear somewhere in the name (case-insensitive). `"juniper router"` matches names containing both "juniper" AND "router". Single-term queries match that term normally.

### Not-found behavior
- **D-02:** Single-object tools (`device_get`, `interface_get`, `ipaddress_get`) raise a clear error message when the object is not found. Example: `Device "router-01" not found`. Do NOT return null or empty.

### Identifier lookup
- **D-03:** Single-object tools accept a single `name_or_id` parameter that auto-detects type — if it looks like a UUID, do a pk lookup; otherwise do a name lookup. Simpler for callers.

### Scope assignment
- **D-04:** All 10 core tools are assigned scope `"core"` and are always visible regardless of session state (SESS-06 already decided). Core tools bypass progressive disclosure filtering entirely.

### ORM serialization
- **D-05:** Each tool uses `model_to_dict()` with `fields` and `exclude` to produce clean JSON-serializable dicts. Nested objects (interfaces on device, ip_addresses on interface) are serialized recursively.

### Claude's Discretion
- Exact serializer field lists per tool (which fields to include/exclude per object type)
- `select_related` and `prefetch_related` chain configuration per tool
- `search_by_name` result limit behavior (default 25, max 1000)
- Error message format for not-found (just the object name vs full path)
- Test structure and mock strategy for `test_core_tools.py`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pagination & Session
- `.planning/ROADMAP.md` — Phase 3 requirements, PAGE-01 through PAGE-05, TOOL-01 through TOOL-10
- `.planning/STATE.md` — Auth decisions (AUTH-01 through AUTH-03), session decisions (SESS-01 through SESS-06)
- `.planning/phases/02-authentication-sessions/` — session tools pattern, `_list_tools_handler`, `MCPSessionState`

### Codebase Patterns
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry`, `ToolDefinition`, `register_mcp_tool()` API
- `nautobot_app_mcp_server/mcp/session_tools.py` — async tool pattern with `ToolContext`, session access via `ctx.request_context.session`
- `nautobot_app_mcp_server/mcp/__init__.py` — public API, `register_mcp_tool()` signature
- `nautobot_app_mcp_server/mcp/server.py` — FastMCP setup, lazy factory, progressive disclosure override
- `.planning/codebase/STACK.md` — Nautobot ORM patterns, `model_to_dict`, ORM access
- `.planning/codebase/STRUCTURE.md` — planned `mcp/tools/` structure (`core.py`, `pagination.py`, `query_utils.py`)

### Requirements
- `.planning/REQUIREMENTS.md` — TOOL-01 through TOOL-10, PAGE-01 through PAGE-05, TEST-02

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- `MCPToolRegistry.get_instance()` — tool registration, already wired in Phase 1
- `MCPSessionState` — session state via FastMCP dict, used by session tools in Phase 2
- `register_mcp_tool()` at module level — pattern established in `session_tools.py`
- `_list_tools_handler` in `session_tools.py` — template for progressive disclosure filtering

### Established Patterns
- Tools: `async def` with `ToolContext`, first param; session via `ctx.request_context.session`; return structured data
- Auth: `.restrict(user, action="view")` on every queryset (AUTH-03 decision from Phase 2)
- Pagination: `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`, `LIMIT_SUMMARIZE=100`, cursor as `base64(str(pk))` (from ROADMAP)
- Tool registration: module-level `register_mcp_tool()` calls (not inside functions)

### Integration Points
- `mcp/tools/core.py` — new file; where all 10 tools will live; registered via `register_mcp_tool()` calls at module level
- `mcp/tools/pagination.py` — new file planned for `paginate_queryset()`, `PaginatedResult`, cursor encoding
- `mcp/tools/query_utils.py` — new file planned for shared queryset builders (`select_related`/`prefetch_related` chains)
- `MCPToolRegistry` — tools register here; `_list_tools_handler` reads from it
- `nautobot_app_mcp_server/__init__.py` — `post_migrate` signal wires core tools registration

</codebase_context>

<specifics>
## Specific Ideas

- `search_by_name` should handle leading/trailing whitespace (strip before querying)
- State from Phase 2 flags `search_by_name` as "high priority open question" — the multi-model cross-query complexity is real; estimate it as 2–3× the effort of a single-model tool

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within Phase 3 scope.

</deferred>

---

*Phase: 03-core-read-tools*
*Context gathered: 2026-04-02*
