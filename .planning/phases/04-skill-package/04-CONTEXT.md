# Phase 4: SKILL.md Package - Context

**Gathered:** 2026-04-02 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Package `SKILL.md` as a standalone pip package (`nautobot-mcp-skill/`) consumable by AI agents. This closes the "progressive disclosure" loop — agents read the skill file to understand available tools and workflows. Write tools and additional tool discovery are out of scope (handled in Phases 1–3).

</domain>

<decisions>
## Implementation Decisions

### Package Structure
- **D-01:** Package at repo root: `nautobot-mcp-skill/` with `SKILL.md` at package root, `pyproject.toml`, and `nautobot_mcp_skill/__init__.py`
- **D-02:** Version in `__init__.py` matching `pyproject.toml`; no separate release cycle for v1.0.0

### SKILL.md Content — Tools Reference
- **D-03:** One row per tool with: tool name, description, input parameters, pagination behavior
- **D-04:** All 10 core tools documented: `device_list`, `device_get`, `interface_list`, `interface_get`, `ipaddress_list`, `ipaddress_get`, `prefix_list`, `vlan_list`, `location_list`, `search_by_name`
- **D-05:** All 3 meta tools documented: `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools`

### SKILL.md Content — Pagination Docs
- **D-06:** Document cursor-based pagination: default=25, max=1000, summarize-at-100 behavior, cursor format (`base64(str(pk))`)

### SKILL.md Content — Scope Management Docs
- **D-07:** Document `mcp_enable_tools(scope=...)`, `mcp_disable_tools(scope=...)`, `mcp_list_tools()` with scope hierarchy explanation

### SKILL.md Content — Investigation Workflows
- **D-08:** 3 workflows documented with step-by-step tool sequences:
  1. Investigate device by name — `device_get` → `interface_list` → drill into specific interface
  2. Find IP address by prefix — `prefix_list` → `ipaddress_list` or `ipaddress_get`
  3. Explore device interfaces and BGP addresses — `device_get` → `interface_list` (device_name filter) → `ipaddress_list`

### SKILL.md Tone & Format
- **D-09:** Quick reference format — table-based, minimal prose, scan-able for agents. Concise descriptions, no lengthy explanations. Agents need to read and parse SKILL.md at runtime; verbosity wastes context.

### Package Distribution
- **D-10:** Internal distribution only — local `pip install ./nautobot-mcp-skill` from repo root. No PyPI publish in v1. Publish command: `pip install ./nautobot-mcp-skill`

### Claude's Discretion
- Exact wording per tool description (pull from existing `core.py` and `session_tools.py` docstrings)
- SKILL.md header/frontmatter content (version, last updated, etc.)
- `pyproject.toml` contents for the skill package (dependencies, build system)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 3 Code (tool definitions)
- `nautobot_app_mcp_server/mcp/tools/core.py` — all 10 core tools: names, descriptions, input schemas, docstrings
- `nautobot_app_mcp_server/mcp/tools/pagination.py` — pagination logic, cursor format, limits
- `nautobot_app_mcp_server/mcp/session_tools.py` — meta tools: `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools`, scope hierarchy docs

### Phase 2 Context (session patterns)
- `.planning/phases/02-authentication-sessions/02-CONTEXT.md` — scope hierarchy (D-21), session state structure
- `.planning/phases/03-core-read-tools/03-CONTEXT.md` — tool behavior decisions (D-01 through D-05)

### Project Config
- `pyproject.toml` (nautobot-app-mcp-server) — version number to match in skill package
- `CLAUDE.md` — conventions, Python version, toolchain

### Roadmap
- `.planning/ROADMAP.md` — Phase 4 requirements: SKILL-01, SKILL-02, SKILL-03; exact success criteria

</canonical_refs>

<codebase_context>
## Existing Code Insights

### Reusable Assets
- Tool docstrings in `core.py` — directly usable as tool descriptions in SKILL.md table
- `session_tools.py` docstrings for meta tools — `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` descriptions
- `pagination.py` constants: `LIMIT_DEFAULT=25`, `LIMIT_MAX=1000`, `LIMIT_SUMMARIZE=100`, cursor encoding

### Package Pattern
- No existing internal pip package in this repo — this is the first
- `nautobot_app_mcp_server/` app package uses similar structure: `__init__.py` with metadata

### Established Conventions
- Google-style docstrings throughout codebase
- Table-based documentation (ROADMAP.md traceability tables)
- No external docs system (MkDocs for API docs, SKILL.md is AI-agent-facing)

### Integration Points
- Skill package consumed by: Claude Code, Claude Desktop, any MCP-compatible AI agent
- SKILL.md must be parseable by AI agents at runtime (simple markdown, no frontmatter complexity)

</codebase_context>

<specifics>
## Specific Ideas

- SKILL.md should include a "Quick Start" header showing how to use `mcp_list_tools()` to discover available scopes
- The pagination table should explicitly show the summarize-at-100 behavior as an example
- Workflows should use actual tool names from `core.py` as the step labels

</specifics>

<deferred>
## Deferred Ideas

- PyPI publish workflow — future milestone (adds versioning overhead, not needed for v1.0.0)
- SKILL.md versioned releases per Nautobot app release — tracked separately

</deferred>

---

*Phase: 04-skill-package*
*Context gathered: 2026-04-02 (assumptions mode)*
