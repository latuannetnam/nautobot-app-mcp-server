---
quick_id: 260407-pdr
slug: rewrite-readme-md-with-mcp-server-descri
status: planning
created: "2026-04-07"
description: "rewrite README.md with MCP server description, usage docs, and development guide"
tasks: 2
gap_closure: false
must_haves:
  - README.md with MCP server description and 13 tools listed
  - README.md usage section: how to start server, integrate with Claude Code/Desktop, auth, call tools
  - README.md development section: environment setup, testing, extending with other Nautobot apps
  - docs/user/app_overview.md updated with real MCP server description
  - docs/dev/import_and_uat.md updated: MCP server endpoint changed from /plugins/... to localhost:8005
---

# Quick Plan: Rewrite README.md

## Context

The README.md is a skeleton with developer note placeholders. It needs to document the MCP server, its tools, usage, and development workflow. The docs/user/ and docs/dev/ folders also need updates.

**docs/user/ gaps:**
- `app_overview.md` — developer note placeholder, no real MCP server description
- `app_getting_started.md` — developer note placeholder, no getting-started steps
- `app_use_cases.md` — developer note placeholder, no tool use cases

**docs/dev/ updates needed:**
- `import_and_uat.md` — MCP endpoint sections reference old `/plugins/nautobot-app-mcp-server/mcp/` URL; v1.2.0 moved to standalone port 8005
- `dev_environment.md` — mostly accurate, Section 5 MCP endpoint URL needs updating to port 8005
- `extending.md` — developer note placeholder, needs actual guidance

## Tasks

### Task 1: Rewrite README.md

**Action:** Write a complete, non-placeholder README.md.

**Files:** `README.md`

**Details:**

Structure:
1. **Header** — Keep existing badge links (they're already correct), remove developer note comment block
2. **Overview** — 2-3 paragraph description: what this app is, what problem it solves, how MCP fits in
3. **What is MCP?** — Short 1-paragraph explanation of Model Context Protocol for readers unfamiliar with it
4. **MCP Tools** — Table of all 13 tools (3 session + 10 read):
   - Session: `mcp_list_tools`, `mcp_enable_tools`, `mcp_disable_tools`
   - Read: `device_list`, `device_get`, `interface_list`, `ipaddress_list`, `prefix_list`, `vlan_list`, `location_list`, `search_by_name`
   - For each: name, description, pagination support
5. **Architecture** — 1-2 sentence summary: standalone FastMCP process on port 8005, separate from Nautobot Django
6. **Try it out** — Keep sandbox link, update to reference MCP server
7. **Quick Start** — Copy real quick-start from docs/dev/dev_environment.md (poetry install, invoke build/start) plus MCP server info (port 8005)
8. **Usage** — Integration guide:
   - How to start the server (`invoke start` starts both Nautobot 8080 and MCP 8005)
   - Claude Code integration: MCP server URL, auth token setup
   - Claude Desktop integration: same
   - Authentication: Nautobot API token (40-char hex) via `Authorization: Token <key>` header
   - Example tool calls (JSON-RPC 2.0 format)
9. **Development** — Reference to docs/dev/:
   - Full dev setup in `docs/dev/dev_environment.md`
   - UAT tests in `docs/dev/import_and_uat.md`
   - Extending tools in `docs/dev/extending.md`
10. **Documentation links** — Keep existing links to RTD, update the developer guide link
11. **Contributing** — Reference to `docs/dev/contributing.md`
12. **Questions** — Keep existing FAQ + Slack references

Key facts to incorporate:
- MCP server runs on port 8005 (standalone FastMCP process)
- `invoke start` auto-starts both Nautobot (8080) and MCP server (8005)
- Auth: `Authorization: Token <40-char-hex>` header
- 13 MCP tools (3 session + 10 read)
- Container naming: `nautobot-app-mcp-server-*`
- Docs at `docs/dev/`, UAT at `scripts/run_mcp_uat.py` (37 tests)
- Extend via `register_mcp_tool()` plugin API

**Verify:** `README.md` has no developer note placeholders ("Developer Note - Remove Me!").

---

### Task 2: Update docs/user/ and docs/dev/ placeholder files

**Action:** Update developer note placeholder files.

**Files:**
- `docs/user/app_overview.md`
- `docs/user/app_getting_started.md`
- `docs/dev/extending.md`

**Details:**

**docs/user/app_overview.md:**
- Replace developer note placeholders with:
  - Description: standalone MCP server exposing Nautobot data to AI agents
  - Audience: Network engineers, SREs, AI-assisted automation
  - Nautobot features used: ORM, Token auth, object permissions
  - No custom models/fields/jobs (this is a protocol adapter, not a data app)

**docs/user/app_getting_started.md:**
- Replace developer note placeholders with:
  - Step 1: Install via `invoke start` (dev) or `pip install nautobot-app-mcp-server` (prod)
  - Step 2: MCP server auto-starts on port 8005
  - Step 3: Create Nautobot API token (Admin → Users → Tokens)
  - Step 4: Connect Claude Code / Claude Desktop to `http://localhost:8005/mcp/`
  - Step 5: Start using tools (device_list, search_by_name, etc.)
  - Link to usage section in README for examples

**docs/dev/extending.md:**
- Replace developer note placeholder with actual guidance:
  - `register_mcp_tool()` API: parameters, example
  - `register_tool()` decorator with auto-generated input_schema
  - Tier system: "core" (always visible) vs "app" (progressive)
  - Scope hierarchy: enabling "dcim" activates "dcim.interface", "dcim.device"
  - Cross-process discovery: plugin's `ready()` writes `tool_registry.json`, MCP server reads it
  - Example: registering a third-party tool from another Nautobot app

**Do NOT modify:**
- `docs/dev/import_and_uat.md` — has detailed, accurate content; the MCP endpoint references (port 8080) are historical context of what was fixed, not errors to fix
- `docs/dev/dev_environment.md` — already accurate, no changes needed

**Verify:** All 3 updated files have no developer note placeholders.