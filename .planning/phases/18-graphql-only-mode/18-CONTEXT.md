# Phase 18: GraphQL-Only Mode - Context

**Gathered:** 2026-05-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Add `NAUTOBOT_MCP_GRAPHQL_ONLY` env var support. When set to `true` at server startup, the MCP server exposes exactly `graphql_query` and `graphql_introspect` — all other tools (core read tools + session tools) are hidden from the manifest and blocked at call time. Without the env var, all 15 tools behave identically to v2.0.

</domain>

<decisions>
## Implementation Decisions

### Enforcement Architecture
- **D-01:** The flag is read in `create_app()` (`commands.py`) from `os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"` at server startup — same pattern as `NAUTOBOT_CONFIG`
- **D-02:** Enforcement is **both layers** — `_list_tools_handler` filters the manifest (GQLONLY-02) AND `ScopeGuardMiddleware` blocks calls (GQLONLY-03). Belt-and-suspenders.
- **D-03:** The flag is stored as a **module-level constant** (e.g. `GRAPHQL_ONLY_MODE: bool` in `commands.py` or a dedicated config module). Both `_list_tools_handler` and `ScopeGuardMiddleware` import it. No re-reading env at call time.
- **D-04:** Blocked tool calls raise `ToolNotFoundError` (reuse existing exception from `middleware.py`) with a GQL-only-specific message. Consistent with existing blocked-call behavior.

### Session Tools Visibility
- **D-05:** In GQL-only mode, `mcp_enable_tools`, `mcp_disable_tools`, and `mcp_list_tools` are **hidden** from the manifest. The scope management system is irrelevant when only 2 tools exist. The manifest shows exactly 2 tools.
- **D-06:** If session tools are called despite being hidden, they raise `ToolNotFoundError` — same as any other blocked non-GraphQL tool. Uniform behavior, no special-case handling.

### UAT Coverage
- **D-07:** Test IDs: T-45, T-46, T-47 (continuing from T-44 in v2.0 UAT suite)
  - T-45: Tool list returns exactly 2 tools when GQL-only active (GQLONLY-02)
  - T-46: Calling a non-GraphQL tool (e.g. `device_list`) returns `ToolNotFoundError` (GQLONLY-03)
  - T-47: Default-off — tool list shows all 15 tools when env var not set (GQLONLY-04)
- **D-08:** Tests live in `scripts/run_mcp_uat.py` in a new `### 5. GraphQL-Only Mode` section
- **D-09:** UAT script **auto-detects** server mode at startup by calling `tools/list`. If only 2 tools appear → GQL-only mode → run T-45/T-46, skip T-01–T-44. If 15 tools → normal mode → run T-01–T-44, skip GQL-only tests. T-47 (default-off) only runs in normal mode.

### Documentation (GQLONLY-06)
- **D-10:** `CLAUDE.md` — add one row to the existing **Gotchas table**: `| GraphQL-only mode hides non-GraphQL tools | Set/unset NAUTOBOT_MCP_GRAPHQL_ONLY env var and restart |`
- **D-11:** `SKILL.md` — add a short **GraphQL-Only Mode** section: env var name, what it does (only `graphql_query` + `graphql_introspect` visible and callable), how to enable (restart with `NAUTOBOT_MCP_GRAPHQL_ONLY=true`). No workflow examples needed.

### Claude's Discretion
- Exact module/location for the `GRAPHQL_ONLY_MODE` constant (could be `commands.py` module-level or a new `config.py`)
- Name of the constant (`GRAPHQL_ONLY_MODE`, `GQL_ONLY`, `_GRAPHQL_ONLY_MODE`, etc.)
- Exact error message string in `ToolNotFoundError` for GQL-only blocked calls
- Unit test naming conventions (follow existing `test_graphql_tool.py` patterns)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Enforcement layers (where changes happen)
- `nautobot_app_mcp_server/mcp/commands.py` — `create_app()` factory: reads env vars, wires FastMCP, adds middleware; GQL-only flag read here
- `nautobot_app_mcp_server/mcp/session_tools.py` — `_list_tools_handler()`: manifest filtering logic; must filter to 2 tools in GQL-only mode
- `nautobot_app_mcp_server/mcp/middleware.py` — `ScopeGuardMiddleware.on_call_tool()`: call-time blocking; must block all non-GraphQL tools in GQL-only mode; `ToolNotFoundError` defined here
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry`: used by both layers to identify tools by name/tier

### Test patterns
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — unit test patterns for GraphQL tools (patch strategy, async test structure)
- `nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — unit test patterns for `_list_tools_handler` and `ScopeGuardMiddleware`
- `scripts/run_mcp_uat.py` — UAT script structure; T-37–T-44 GraphQL section; `MCPClient`, `TestRunner`, `TestResult` classes; auto-detection pattern to add at startup

### Requirements
- `.planning/REQUIREMENTS.md` §Active Requirements — GQLONLY-01 through GQLONLY-06
- `.planning/ROADMAP.md` §Phase 18 — success criteria (6 items)

### Documentation targets
- `CLAUDE.md` — Gotchas table: add `NAUTOBOT_MCP_GRAPHQL_ONLY` row
- `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — add GraphQL-Only Mode section

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ToolNotFoundError` in `middleware.py` — already defined; reuse for GQL-only blocked calls (no new exception class needed)
- `ScopeGuardMiddleware.on_call_tool()` — extend with a GQL-only early-exit check before the existing scope logic
- `_list_tools_handler()` in `session_tools.py` — extend with a GQL-only early-return branch before the existing scope filtering
- `MCPToolRegistry.get_all()` — returns all tools; filter by name (`graphql_query`, `graphql_introspect`) for GQL-only manifest
- `TestRunner` / `MCPClient` in `scripts/run_mcp_uat.py` — reuse unchanged for T-45/T-46/T-47

### Established Patterns
- Env var reads in `create_app()`: `os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")` — follow exact same pattern for `NAUTOBOT_MCP_GRAPHQL_ONLY`
- `tier="core"` means "always callable" in current `ScopeGuardMiddleware` — GQL-only mode overrides this by name, not tier
- Unit tests patch `nautobot.core.graphql.execute_query` at **source** (not consumer) due to lazy imports — follow same lazy-import patch pattern

### Integration Points
- `create_app()` returns `(mcp, host, port)` — the GQL-only constant must be set before `_list_tools_handler` and `ScopeGuardMiddleware` are instantiated (both happen inside `create_app()`)
- `mcp.add_middleware(ScopeGuardMiddleware())` in `create_app()` — if passing flag via constructor, change to `ScopeGuardMiddleware(graphql_only=GRAPHQL_ONLY_MODE)`. If using module-level constant, no change needed at the call site.
- UAT auto-detection: call `tools/list` before any test, count returned tools; branch test suite accordingly

</code_context>

<specifics>
## Specific Ideas

- Auto-detection in `run_mcp_uat.py`: one `mcp_client.list_tools()` call at the top of `main()`, check `len(tools) == 2` → GQL-only mode. Print mode banner so test output is self-explanatory.
- The 2 tools to show in GQL-only mode are named `graphql_query` and `graphql_introspect` — these are the exact registered names from `graphql_tool.py`
- T-46 should call `device_list` (the most familiar non-GraphQL tool) to keep the test readable

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 18-graphql-only-mode*
*Context gathered: 2026-05-04*
