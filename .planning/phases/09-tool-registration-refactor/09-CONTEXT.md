# Phase 9: Tool Registration Refactor - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Redesign tool registration for the separate-process (Option B) MCP server architecture. P2-01–P2-03 handle the `@register_tool` decorator and `tool_registry.json` cross-process discovery. P2-04 refactors all 10 core read tools to the `async def + sync_to_async(thread_sensitive=True)` pattern. P2-05 eliminates module-level Django model imports from `mcp/tools/`. P2-06 adds unit tests.

Phase 8 delivered `start_mcp_server.py` and `start_mcp_dev_server.py` management commands. This phase wires tools into FastMCP and makes the standalone server actually useful.

</domain>

<decisions>
## Implementation Decisions

### P2-01: @register_tool Decorator
- **D-01:** `@register_tool` writes to `MCPToolRegistry` only — deferred wiring, NOT immediate FastMCP wiring at decoration time
- **D-02:** Auto-generate `input_schema` from function signature via `inspect.signature` — `input_schema` parameter becomes optional on `register_mcp_tool()` and `@register_tool`
- **D-03:** On call: extract function signature → convert each parameter to JSON Schema field (type inferred from default value or annotation) → build `input_schema` dict → register in `MCPToolRegistry`
- **D-04:** If caller explicitly passes `input_schema`, use it (explicit overrides auto-generated)
- **D-05:** `@register_tool` decorator signature: `@register_tool(description="...", tier="core", scope="core")` — wraps the async handler function, auto-wires name from `func.__name__`

### P2-02: register_all_tools_with_mcp()
- **D-06:** Called after `create_app()` in `start_mcp_server` and `start_mcp_dev_server` — reads `MCPToolRegistry.get_all()` and calls `mcp.tool()` for each entry
- **D-07:** Signature: `register_all_tools_with_mcp(mcp: FastMCP) -> None`
- **D-08:** For each `ToolDefinition` in the registry: extract `input_schema`, call `mcp.tool(name=tool.name, description=tool.description, input_schema=tool.input_schema)(tool.func)` — FastMCP 3.x `.tool()` is a decorator
- **D-09:** Must be called AFTER `nautobot.setup()` so lazy imports in tool functions succeed

### P2-03: tool_registry.json
- **D-10:** Written by Nautobot plugin `ready()` in `__init__.py` — runs when Nautobot starts (plugin process), NOT `post_migrate` (which never fires in MCP server process — PITFALL #3 from ROADMAP)
- **D-11:** Location: same directory as `nautobot_app_mcp_server/__init__.py` — resolved via `os.path.dirname(__file__)` in plugin `__init__.py` at write time
- **D-12:** JSON structure: list of tool metadata dicts — `name`, `description`, `tier`, `app_label`, `scope` (no `func` — not JSON-serializable; MCP server re-imports tool modules to get callable)
- **D-13:** At MCP server startup, `create_app()` reads `tool_registry.json` from the plugin package directory (via `importlib.resources` or `__file__` resolution) — populates `MCPToolRegistry` before `register_all_tools_with_mcp()` runs

### P2-04: All 10 Core Tools — async + sync_to_async
- **D-14:** All tools in `mcp/tools/core.py` are `async def` with `ToolContext` as first param — already the case (Phase 5 pattern)
- **D-15:** ORM calls wrapped: `sync_to_async(thread_sensitive=True)(get_sync_fn())` — already the case (Phase 5 D-09, implemented in `core.py` lines 44-47)
- **D-16:** No changes to tool logic — only refactoring the wiring layer (registration + FastMCP attachment)

### P2-05: No Django Model Imports at Module Level
- **D-17:** Strategy: manual grep + convert — `grep -n "from nautobot" query_utils.py` to find all module-level Nautobot model imports
- **D-18:** Convert each: move import from module level to inside the function that uses it (lazy import)
- **D-19:** Keep `TYPE_CHECKING` block for type annotations — `from nautobot.users.models import User` stays in `TYPE_CHECKING` block
- **D-20:** Primary target: `nautobot_app_mcp_server/mcp/tools/query_utils.py` lines 16-17 (module-level `from nautobot.dcim.models import ...` and `from nautobot.ipam.models import ...`)
- **D-21:** Post-conversion audit: `grep -r "from nautobot" mcp/tools/ --include="*.py"` at module level (outside `TYPE_CHECKING`) must return zero matches

### P2-06: Unit Tests
- **D-22:** Tests for `@register_tool` decorator: registers in registry, auto-generates schema, explicit schema overrides auto-generated
- **D-23:** Tests for `register_all_tools_with_mcp()`: wires all registered tools to FastMCP, handles empty registry

### Claude's Discretion
- Exact `inspect.signature` → JSON Schema type mapping (int/float/bool/str/None → JSON types; complex annotations → `{"type": "object"}` fallback)
- Error message wording when input_schema generation fails
- Exact `tool_registry.json` filename
- How to handle third-party tool modules (not in `nautobot_app_mcp_server/mcp/tools/`) — where they are discovered and how MCP server imports them
- Whether `MCPToolRegistry.get_all()` returns tools in registration order (preserves predictability)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 9 Scope (PRIMARY)
- `.planning/ROADMAP.md` §Phase 9 — phase goal, 6 requirements (P2-01–P2-06), success criteria, known pitfalls (PITFALL #3: `post_migrate` never fires in MCP server process)
- `.planning/REQUIREMENTS.md` §v1.2.0 Requirements — P2-01 through P2-06

### Phase 8 Context
- `.planning/phases/08-infrastructure-management-commands/08-CONTEXT.md` — Phase 8 decisions (create_app() factory, management commands, DB validation, env var config)

### Prior Phase Context
- `.planning/phases/07-setup/07-CONTEXT.md` — Phase 7 decisions (uvicorn dep, docker-compose, upgrade docs)
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — Phase 5 D-09: `async_to_sync` pattern, D-24: MCPToolSession dict usage
- `.planning/phases/03-core-read-tools/03-CONTEXT.md` — Phase 3 D-04: scope="core" for all 10 tools, D-05: model_to_dict serialization

### Stack & Conventions
- `.planning/codebase/CONVENTIONS.md` — Python naming, docstrings, error handling
- `.planning/codebase/STACK.md` — Python 3.12, Poetry, asgiref, Django config from env

### Implementation Reference
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry`, `ToolDefinition` — existing registry to extend
- `nautobot_app_mcp_server/mcp/__init__.py` — `register_mcp_tool()` — public API to extend
- `nautobot_app_mcp_server/mcp/tools/core.py` — existing tool registration pattern (lines 50-71: register_mcp_tool call)
- `nautobot_app_mcp_server/mcp/tools/query_utils.py` — module-level Nautobot imports to convert (lines 16-17)
- `nautobot_app_mcp_server/mcp/tools/pagination.py` — existing pagination utilities
- `nautobot_app_mcp_server/__init__.py` — `NautobotAppConfig` — where plugin `ready()` will write `tool_registry.json`

### Reference Project (nautobot-app-mcp)
- Reference project decisions from STATE.md: `@register_tool` decorator does dual registration (in-memory dict + FastMCP `.tool()`); `tool_registry.json` for cross-process plugin discovery

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- `MCPToolRegistry` (`registry.py`): existing thread-safe singleton, `register()` method, `get_all()` / `get_core_tools()` / `get_by_scope()` methods — extend, don't replace
- `register_mcp_tool()` (`mcp/__init__.py`): existing public API — add `@register_tool` decorator wrapper and auto-schema generation
- `core.py`: existing `async def` handlers with `sync_to_async` — already in Phase 5 pattern, no logic changes needed
- `query_utils.py`: `_sync_*` functions — sync ORM wrappers called via `sync_to_async` in `core.py`
- `pagination.py`: `PaginatedResult`, `paginate_queryset` — already exist, not changing

### Established Patterns
- `sync_to_async(thread_sensitive=True)` — ORM calls wrapped this way (Phase 5, D-09)
- `ToolContext` from `fastmcp.server.context` — first param of every async tool handler
- Module-level `register_mcp_tool()` calls at import time — registration happens when `mcp/tools/__init__.py` side-effect imports `core`
- `model_to_dict()` + explicit field lists per model — serialization pattern in `query_utils.py`

### Integration Points
- Plugin `__init__.py` → `ready()` hook: write `tool_registry.json` here
- `create_app()` in `management/commands/start_mcp_server.py` / `start_mcp_dev_server.py`: call `register_all_tools_with_mcp(mcp)` after FastMCP instantiation
- `nautobot_app_mcp_server/mcp/tools/__init__.py`: side-effect import of `core` triggers `register_mcp_tool()` calls — MCPToolRegistry populated
- MCP server startup: `create_app()` reads `tool_registry.json`, populates `MCPToolRegistry` before `register_all_tools_with_mcp()`

### Critical Code (to review before planning)
- `nautobot_app_mcp_server/mcp/tools/query_utils.py` lines 16-17: module-level Nautobot model imports (P2-05 target)
- `nautobot_app_mcp_server/mcp/tools/core.py` lines 44-47: existing `sync_to_async` pattern (P2-04 reference)
- `nautobot_app_mcp_server/mcp/__init__.py` lines 44-90: `register_mcp_tool()` signature (P2-01 extend point)
- `nautobot_app_mcp_server/mcp/registry.py` lines 54-59: `MCPToolRegistry.register()` (P2-01 extend point)

</codebase_context>

<specifics>
## Specific Ideas

- PITFALL #3 is explicit in the ROADMAP: `post_migrate` never fires in the MCP server process because it runs `django.setup()` directly, not via `nautobot-server`. `tool_registry.json` replaces `post_migrate` — this is a hard architectural constraint, not a choice.
- The 10 core tools are already in the correct async pattern (Phase 5) — P2-04 is confirming the pattern is right and adding the FastMCP wiring
- "Manual grep + convert" for P2-05 means the git diff will be auditable: each moved import shows clearly

</specifics>

<deferred>
## Deferred Ideas

**None — all Phase 9 decisions captured above.**

</deferred>

---

*Phase: 09-tool-registration-refactor*
*Context gathered: 2026-04-05*
