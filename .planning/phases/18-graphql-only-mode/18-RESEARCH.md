# Phase 18: GraphQL-Only Mode - Research

**Researched:** 2026-05-04
**Domain:** FastMCP middleware enforcement, environment-variable-gated feature flags, MCP manifest filtering
**Confidence:** HIGH

## Summary

Phase 18 adds `NAUTOBOT_MCP_GRAPHQL_ONLY=true` env var support to the standalone FastMCP MCP server. When set at server startup, exactly two tools (`graphql_query`, `graphql_introspect`) are exposed in the tool manifest and callable. All other tools (10 core read tools + 3 session tools) are hidden and blocked. The implementation uses a module-level `GRAPHQL_ONLY_MODE` boolean constant set in `create_app()` before middleware/tool registration.

The enforcement is two-layered: `_list_tools_handler` in `session_tools.py` filters the manifest at `tools/list` time, and `ScopeGuardMiddleware.on_call_tool()` in `middleware.py` blocks calls to non-GraphQL tools at call time. This belt-and-suspenders approach ensures clients cannot bypass the manifest to call hidden tools.

**Primary recommendation:** Store `GRAPHQL_ONLY_MODE` as a module-level boolean in `commands.py` (matching the D-03 decision). Read it via `os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"` before `nautobot.setup()`. Both `_list_tools_handler` and `ScopeGuardMiddleware` import the constant directly.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Env var read + flag set | API/Backend (`commands.py`) | — | `create_app()` is the startup entry point; env reads belong here |
| Manifest filtering | API/Backend (`_list_tools_handler`) | — | `session_tools.py` owns progressive disclosure |
| Call-time blocking | API/Backend (`ScopeGuardMiddleware`) | — | `middleware.py` owns security backstop |
| Tool registry (lookup) | API/Backend (`MCPToolRegistry`) | — | Registry identifies tools by name/tier |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Flag read in `create_app()` via `os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"`
- **D-02:** Both layers enforced: `_list_tools_handler` filters manifest AND `ScopeGuardMiddleware` blocks calls
- **D-03:** Module-level constant (`GRAPHQL_ONLY_MODE` in `commands.py`)
- **D-04:** Blocked calls raise `ToolNotFoundError` (reuse existing exception from `middleware.py`)
- **D-05:** Session tools (`mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools`) hidden in GQL-only mode manifest
- **D-06:** Hidden session tools raise `ToolNotFoundError` if called despite being hidden
- **D-07:** UAT test IDs: T-45, T-46, T-47
- **D-08:** UAT tests live in `scripts/run_mcp_uat.py` new section
- **D-09:** UAT auto-detects mode: call `tools/list`, count tools, branch accordingly
- **D-10/D-11:** Documentation in CLAUDE.md (Gotchas table) and SKILL.md

### Claude's Discretion
- Exact module/location for the constant (`commands.py` module-level vs new `config.py`)
- Name of constant (`GRAPHQL_ONLY_MODE`, `GQL_ONLY`, etc.)
- Exact error message string in `ToolNotFoundError`
- Unit test naming conventions

### Deferred Ideas (OUT OF SCOPE)
None.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GQLONLY-01 | `NAUTOBOT_MCP_GRAPHQL_ONLY=true` starts server in GQL-only mode | `create_app()` reads env vars; pattern from `NAUTOBOT_CONFIG` read |
| GQLONLY-02 | GQL-only: manifest returns exactly `graphql_query` + `graphql_introspect` | `_list_tools_handler` filters by name when `GRAPHQL_ONLY_MODE=True` |
| GQLONLY-03 | GQL-only: non-GraphQL tool calls blocked with clear error | `ScopeGuardMiddleware.on_call_tool()` raises `ToolNotFoundError` for non-GraphQL tools |
| GQLONLY-04 | Default (no env var): all 15 tools visible | Normal mode passes through existing `_list_tools_handler` unchanged |
| GQLONLY-05 | Unit tests cover: manifest filtering, call-time blocking, default-off | `test_session_tools.py` patterns for `_list_tools_handler`; `test_graphql_tool.py` patterns for GQL tools |
| GQLONLY-06 | Documented in CLAUDE.md + SKILL.md | Gotchas table row + SKILL.md new section |

## Standard Stack

### Core (Already Present — No New Dependencies)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastMCP | 3.2.0 | MCP HTTP transport + middleware | Already in use |
| `os.environ.get` | stdlib | Env var reading | Established pattern in `commands.py` (`NAUTOBOT_CONFIG`) |
| `MCPToolRegistry` | existing | Tool registry lookup by name | Existing Phase 7 infrastructure |
| `ToolNotFoundError` | existing | Blocked tool exception | Already defined in `middleware.py` |

**No new packages needed.**

### Existing Pattern for Env Vars
```python
# commands.py — established pattern (D-01 reference)
_NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
_PLUGINS_CONFIG = os.environ.get("PLUGINS_CONFIG")
```
Same pattern for `NAUTOBOT_MCP_GRAPHQL_ONLY`.

## Architecture Patterns

### System Architecture Diagram

```
[env: NAUTOBOT_MCP_GRAPHQL_ONLY=true]
         │
         ▼
commands.py: create_app()
    │
    ├─► reads os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"
    │   sets GRAPHQL_ONLY_MODE = True  (module-level constant)
    │
    ├─► nautobot.setup()
    │
    ├─► FastMCP() instance created
    │
    ├─► Side-effect imports → tools registered in MCPToolRegistry
    │
    ├─► ScopeGuardMiddleware() added to FastMCP
    │       │
    │       └─► on_call_tool(params):
    │               if GRAPHQL_ONLY_MODE and params.name not in ("graphql_query", "graphql_introspect"):
    │                   raise ToolNotFoundError("GraphQL-only mode is active...")
    │
    └─► return (mcp, host, port)
              │
              ▼
    MCP HTTP Endpoint (port 8005)
         │
         ├─► tools/list → _list_tools_handler()
         │                   │
         │                   └─► if GRAPHQL_ONLY_MODE:
         │                           return only [graphql_query, graphql_introspect]
         │
         └─► tools/call → ScopeGuardMiddleware.on_call_tool()
                             │
                             └─► if GRAPHQL_ONLY_MODE and tool not GraphQL:
                                     raise ToolNotFoundError
```

### Recommended Project Structure
No structural changes — all changes are in-place edits to existing files:
```
nautobot_app_mcp_server/mcp/
├── commands.py         # Add: GRAPHQL_ONLY_MODE read + constant
├── middleware.py       # Add: GQL-only early-exit in on_call_tool()
├── session_tools.py   # Add: GQL-only branch in _list_tools_handler()
└── tests/
    └── test_graphql_only_mode.py  # New file (GQLONLY-05)
```

### Pattern 1: Module-Level Feature Flag

**What:** A boolean constant (`GRAPHQL_ONLY_MODE`) set at module load time in `commands.py`, read by both `_list_tools_handler` and `ScopeGuardMiddleware`.

**When to use:** When multiple distant components need to check the same startup-determined flag without passing it through function arguments.

**Example:**
```python
# commands.py (after STEP 0 env reads)
GRAPHQL_ONLY_MODE: bool = os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"

# middleware.py (import at top)
from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE

# session_tools.py (import at top)
from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE
```

### Pattern 2: Two-Layer Enforcement (Manifest + Call-Time)

**What:** Both the tool manifest (`tools/list`) and the call gate (`tools/call`) enforce the same policy. Manifest filtering provides UX (only 2 tools visible). Call-time blocking provides security (client cannot bypass manifest).

**When to use:** When hiding tools from the manifest is insufficient security and a security backstop is needed.

**Example (call-time):**
```python
# middleware.py — in on_call_tool()
if GRAPHQL_ONLY_MODE:
    if params.name not in ("graphql_query", "graphql_introspect"):
        raise ToolNotFoundError(
            f"Tool '{params.name}' is not available in GraphQL-only mode. "
            f"Only graphql_query and graphql_introspect are available."
        )
```

**Example (manifest):**
```python
# session_tools.py — in _list_tools_handler()
if GRAPHQL_ONLY_MODE:
    registry = MCPToolRegistry.get_instance()
    return [
        ToolInstance(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
        )
        for t in registry.get_all()
        if t.name in ("graphql_query", "graphql_introspect")
    ]
```

### Pattern 3: GQL-Only Tool Name Allowlist

**What:** Hardcoded tuple of tool names that are the only ones permitted in GQL-only mode.

**Why not dynamic:** Exactly 2 tools, both known at design time. No need for configuration flexibility.

```python
# Shared constant
_ALLOWED_GQL_ONLY_TOOLS = ("graphql_query", "graphql_introspect")
```

### Anti-Patterns to Avoid
- **Env var read at call time:** The flag must be read once at startup and stored as a module-level constant. Re-reading `os.environ` at each tool call is incorrect (D-03).
- **New exception class:** Reuse `ToolNotFoundError` from `middleware.py`. Creating a `GraphQLOnlyModeError` adds a new exception type for no reason (D-04).
- **Tier-based filtering:** GraphQL tools are `tier="core"` but GQL-only mode overrides this by name. Filtering by `tier == "core"` would incorrectly include session tools which are also `tier="core"`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Feature flag constant | Re-implement the pattern | Module-level boolean in `commands.py` | Consistent with D-03; same pattern used for env-based config |
| Blocked tool exception | Create new exception class | Reuse `ToolNotFoundError` from `middleware.py` | Already defined; adding a new type is unnecessary complexity |
| Manifest filtering | Build a new list handler from scratch | Extend existing `_list_tools_handler` with GQL-only branch | Maintains existing progressive disclosure logic; minimal diff |

## Common Pitfalls

### Pitfall 1: Session Tools Visibility (D-05)
**What goes wrong:** `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` are `tier="core"` and would normally appear in `get_core_tools()`. In GQL-only mode, they must be hidden from the manifest entirely.
**Why it happens:** `get_core_tools()` returns all `tier="core"` tools. Session tools are registered as `tier="core"`. A naive `get_core_tools()` filter would include them.
**How to avoid:** Filter by exact tool name (`"graphql_query"`, `"graphql_introspect"`) rather than by tier. Session tools are hidden by name, not by tier logic.

### Pitfall 2: Tool Name Exact Match
**What goes wrong:** Using `in ["graphql_query", "graphql_introspect"]` without verifying exact spelling.
**Why it happens:** The tool names are registered as `"graphql_query"` and `"graphql_introspect"` in `graphql_tool.py`. Any typo or case variation causes the tool to be blocked.
**How to avoid:** Use a shared constant `ALLOWED_GQL_ONLY_TOOLS = ("graphql_query", "graphql_introspect")` referenced in both enforcement layers. Single source of truth.

### Pitfall 3: ScopeGuardMiddleware Import Before Constant Set
**What goes wrong:** If `ScopeGuardMiddleware` is imported (at `add_middleware()` call time) before `GRAPHQL_ONLY_MODE` is assigned, the middleware gets the wrong value.
**Why it happens:** Python module-level constants are evaluated at import time. If `middleware.py` imports `GRAPHQL_ONLY_MODE` from `commands.py` before the assignment happens, it gets `NameError` or the wrong value.
**How to avoid:** `GRAPHQL_ONLY_MODE` is assigned at module level in `commands.py` before any other module imports it. The import chain is: `commands.py` is imported first (by management commands) → sets constant → later imports of `middleware.py` and `session_tools.py` see the constant. This works because `commands.py` is imported before those modules are loaded.

### Pitfall 4: Lazy Import Mismatch
**What goes wrong:** Patching `nautobot_app_mcp_server.mcp.commands.GRAPHQL_ONLY_MODE` in tests doesn't work because the test imports `commands` via `from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE`, creating a local binding.
**How to avoid:** Patch at the module level in tests: `patch("nautobot_app_mcp_server.mcp.commands.GRAPHQL_ONLY_MODE", True)`. Or use an environment variable patch: `patch.dict(os.environ, {"NAUTOBOT_MCP_GRAPHQL_ONLY": "true"})`.

## Code Examples

### commands.py — Add GRAPHQL_ONLY_MODE Constant

```python
# Somewhere near STEP 0 (before nautobot.setup() is called)
GRAPHQL_ONLY_MODE: bool = os.environ.get("NAUTOBOT_MCP_GRAPHQL_ONLY", "false").lower() == "true"
```

Verified: Pattern matches existing `NAUTOBOT_CONFIG` and `PLUGINS_CONFIG` reads in same function. No new library needed.

### middleware.py — GQL-Only Call Blocking

```python
# At top of middleware.py, add import
from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE

# In on_call_tool(), after tool lookup but before scope check:
_ALLOWED_GQL_ONLY_TOOLS = ("graphql_query", "graphql_introspect")

async def on_call_tool(self, context, call_next):
    params = context.message
    registry = MCPToolRegistry.get_instance()
    tool = registry._tools.get(params.name)

    # GQL-only mode: block all non-GraphQL tools
    if GRAPHQL_ONLY_MODE:
        if params.name not in _ALLOWED_GQL_ONLY_TOOLS:
            raise ToolNotFoundError(
                f"Tool '{params.name}' is not available in GraphQL-only mode. "
                f"Only graphql_query and graphql_introspect are available."
            )
        # Fall through to normal GraphQL handling (auth, execution)

    # Core tools: always pass through
    if tool is None or tool.tier == "core":
        return await call_next(context)

    # ... rest of scope checking logic
```

### session_tools.py — GQL-Only Manifest Filtering

```python
# At top of file
from nautobot_app_mcp_server.mcp.commands import GRAPHQL_ONLY_MODE

# In _list_tools_handler(), at start of function:
_ALLOWED_GQL_ONLY_TOOLS = ("graphql_query", "graphql_introspect")

async def _list_tools_handler(ctx):
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

    registry = MCPToolRegistry.get_instance()

    # GQL-only mode: only show GraphQL tools
    if GRAPHQL_ONLY_MODE:
        all_tools = registry.get_all()
        return [
            ToolInstance(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
            )
            for t in all_tools
            if t.name in _ALLOWED_GQL_ONLY_TOOLS
        ]

    # ... rest of normal progressive disclosure logic
```

### UAT Auto-Detection (run_mcp_uat.py)

```python
def run_uat() -> bool:
    client = MCPClient(MCP_ENDPOINT, DEV_TOKEN)

    # Auto-detect mode at startup
    tools = client.list_tools()
    tool_names = [t["name"] for t in tools]

    if len(tools) == 2 and "graphql_query" in tool_names and "graphql_introspect" in tool_names:
        print("\n## GraphQL-Only Mode detected (2 tools)")
        # Run GQL-only tests only
        # T-45, T-46, T-47
        ...
        return runner.summary()

    print("\n## Normal mode detected (15 tools)")
    # Run full test suite (T-01 to T-44)
    ...
    return runner.summary()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All tools always visible | Progressive disclosure via session scopes (Phase 10) | 2026-04-07 | Scope-gated tool visibility |
| No GraphQL-only mode | Env-var gated GraphQL-only mode | Phase 18 | Operators can restrict to 2 tools at startup |

**Deprecated/outdated:**
- None relevant to this phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `graphql_query` and `graphql_introspect` are the only GraphQL tools | Architecture, Common Pitfalls | If names differ, enforcement would silently fail. Verified via `graphql_tool.py` registration |
| A2 | `ToolNotFoundError` is raised correctly by FastMCP for non-200 responses | D-04 | Verified via existing `ScopeGuardMiddleware` usage |
| A3 | Module-level constant import ordering works without circular imports | Pitfall 3 | `commands.py` does not import `middleware.py` or `session_tools.py` at module level |

## Open Questions

1. **Where to store the `ALLOWED_GQL_ONLY_TOOLS` tuple?**
   - Could be in `commands.py` (next to `GRAPHQL_ONLY_MODE`), imported by both `middleware.py` and `session_tools.py`
   - Could be in `middleware.py` (duplicated in both layers)
   - **Recommendation:** Store in `commands.py` as `ALLOWED_GQL_ONLY_TOOLS`, imported by both enforcement layers. Single source of truth.

2. **Should T-47 (default-off) be gated on something?**
   - T-47 verifies default mode (no env var) shows all 15 tools
   - If UAT is run against a GQL-only server, T-47 cannot be verified
   - **Recommendation:** T-47 only runs in normal mode (15-tool auto-detect). Already specified in D-09.

## Environment Availability

> Step 2.6: SKIPPED — no external dependencies identified (pure code/config changes).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django TestCase (`django.test.TestCase`) |
| Config file | `pyproject.toml` / `development.env` |
| Quick run command | `unset VIRTUAL_ENV && poetry run invoke unittest -b -f -s -l mcp.tests.test_graphql_only_mode` |
| Full suite command | `unset VIRTUAL_ENV && poetry run invoke unittest -b -f` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GQLONLY-01 | Env var `NAUTOBOT_MCP_GRAPHQL_ONLY=true` activates GQL-only mode | unit | `test_commands.py::test_graphql_only_mode_env_var` | new file |
| GQLONLY-02 | `_list_tools_handler` returns only 2 tools when flag is True | unit | `test_graphql_only_mode.py::test_list_tools_handler_gql_only_returns_two_tools` | new file |
| GQLONLY-03 | `ScopeGuardMiddleware` blocks non-GraphQL tools when flag is True | unit | `test_graphql_only_mode.py::test_middleware_blocks_non_graphql_tools` | new file |
| GQLONLY-04 | Default mode (no env var) shows all 15 tools | unit | `test_graphql_only_mode.py::test_default_mode_all_tools_visible` | new file |
| GQLONLY-05 | Unit tests cover manifest filtering, call-time enforcement, default-off | unit | All of above | new file |
| GQLONLY-06 | Documentation updated | manual | N/A (doc review) | CLAUDE.md + SKILL.md edits |

### Sampling Rate
- **Per task commit:** Quick run command for affected module
- **Per wave merge:** Full suite command
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `nautobot_app_mcp_server/mcp/tests/test_graphql_only_mode.py` — covers GQLONLY-01, GQLONLY-02, GQLONLY-03, GQLONLY-04, GQLONLY-05
- [ ] `nautobot_app_mcp_server/mcp/tests/__init__.py` — no changes needed (already present)
- Framework install: None — existing Django test infrastructure covers all phase requirements

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | yes | Env-var gated tool visibility — operators control exposure at deployment time |
| V5 Input Validation | no | No new user inputs; env var is deployment-time configuration |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Client bypasses manifest to call hidden tools | Spoofing / Elevation | `ScopeGuardMiddleware` call-time blocking — even if manifest is bypassed, call is blocked |
| Tool allowlist enforcement | Tampering | Name-based filter in both layers — hardcoded tuple `ALLOWED_GQL_ONLY_TOOLS` |

**Security note:** The two-layer enforcement (manifest filter + call-time block) ensures defense in depth. A client that manually crafts a `tools/call` request for a hidden tool will still be blocked by `ScopeGuardMiddleware`.

## Sources

### Primary (HIGH confidence)
- `nautobot_app_mcp_server/mcp/commands.py` — env var read pattern, `create_app()` flow
- `nautobot_app_mcp_server/mcp/session_tools.py` — `_list_tools_handler` progressive disclosure logic
- `nautobot_app_mcp_server/mcp/middleware.py` — `ScopeGuardMiddleware`, `ToolNotFoundError` definition
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry.get_all()`, `get_core_tools()`
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` — tool names registered: `"graphql_query"`, `"graphql_introspect"`

### Secondary (MEDIUM confidence)
- `nautobot_app_mcp_server/mcp/tests/test_session_tools.py` — test patterns for `_list_tools_handler`, `ScopeGuardMiddleware`
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — test patterns for GraphQL tools
- `scripts/run_mcp_uat.py` — UAT structure, `TestRunner`, `MCPClient`, `MCPToolError` classes

### Tertiary (LOW confidence)
- None required — all information verified via codebase reading.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; uses existing env-var pattern
- Architecture: HIGH — two-layer enforcement clearly mapped to existing code
- Pitfalls: HIGH — identified via codebase analysis of existing patterns

**Research date:** 2026-05-04
**Valid until:** 2026-06-03 (30 days — stable domain, no fast-moving libraries)
