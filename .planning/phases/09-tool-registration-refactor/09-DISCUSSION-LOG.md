# Phase 9: Tool Registration Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 09-tool-registration-refactor
**Mode:** discuss
**Areas discussed:** @register_tool wiring & timing, tool_registry.json path & format, Lazy import migration strategy, P2-05 lazy import conversion

---

## @register_tool Wiring & Timing

| Option | Description | Selected |
|--------|-------------|----------|
| Deferred wiring | @register_tool writes to MCPToolRegistry only. register_all_tools_with_mcp(mcp) called after create_app(). Clean separation. | ✓ |
| Immediate at decoration | @register_tool calls mcp.tool() right away at decoration time. Requires create_app() before any tool imports. | |
| JSON file plugin ready() | Plugin ready() writes tool metadata to tool_registry.json. MCP server reads it at startup. Eliminates runtime import coupling. | |

**User's choice:** Deferred wiring — clean separation between registration and FastMCP wiring
**Notes:** Deferred wiring chosen because it keeps concerns separate: register_mcp_tool() handles registry, register_all_tools_with_mcp() handles FastMCP wiring.

---

## @register_tool Schema Generation

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-generate | @register_tool infers input_schema from inspect.signature. Users pass only name, func, description. Simpler, DRY. | ✓ |
| Explicit only | input_schema always required — explicit is clearer, avoids signature-change surprises. | |

**User's choice:** Auto-generate — simpler API, less boilerplate, explicit input_schema still overrides when provided

---

## tool_registry.json Path

| Option | Description | Selected |
|--------|-------------|----------|
| Same dir as __init__.py | Plugin __init__.py uses os.path.dirname(__file__) to write JSON. No hardcoded path. | ✓ |
| Django MEDIA_ROOT | Write to Django's MEDIA_ROOT or STATIC_ROOT. Central location but may not be reliable at ready() time. | |
| Environment variable | MCP server reads path from env var. Explicit but adds configuration burden. | |

**User's choice:** Same dir as __init__.py — simplest, no extra configuration

---

## Lazy Import Migration Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Manual grep + convert | grep for module-level imports, move each to inside the function that uses it. Keep TYPE_CHECKING block. Transparent and auditable. | ✓ |
| One-time AST script | Write a script using Python AST to auto-detect and rewrite module-level imports. Faster but less auditable. | |
| TYPE_CHECKING guard only | Move imports under if TYPE_CHECKING: for type hints. Add lazy imports in functions at runtime. Two places to maintain. | |

**User's choice:** Manual grep + convert — clearest audit trail in git history

---

## P2-05 Lazy Import Conversion

| Option | Description | Selected |
|--------|-------------|----------|
| Manual grep + convert | Use grep to find module-level imports, move each to inside the function that uses it. Keep TYPE_CHECKING block for type hints. Transparent and easy to audit. | ✓ |
| One-time AST script | Write a script using Python AST to auto-detect and rewrite module-level imports. Faster for large files, less auditable. | |
| TYPE_CHECKING guard only | Move imports under if TYPE_CHECKING: for type hints. Add explicit lazy imports in functions that need the model at runtime. Two places to maintain. | |

**User's choice:** Manual grep + convert — same as strategy above, applied to query_utils.py module-level imports

---

## Claude's Discretion

The following were noted as Claude's discretion for the planner:

- Exact `inspect.signature` → JSON Schema type mapping (int/float/bool/str/None → JSON types; complex annotations → `{"type": "object"}` fallback)
- Error message wording when input_schema generation fails
- Exact `tool_registry.json` filename
- How to handle third-party tool modules (not in `nautobot_app_mcp_server/mcp/tools/`)
- Whether `MCPToolRegistry.get_all()` returns tools in registration order
