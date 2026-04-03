# Nautobot App MCP Server

## What This Is

A Nautobot App that embeds a Model Context Protocol (MCP) server inside Nautobot's Django process, enabling AI agents (Claude Code, Claude Desktop) to interact with Nautobot data via MCP tools rather than an external REST API call. It exposes a FastMCP HTTP endpoint, uses direct Django ORM (zero network overhead), and supports progressive disclosure of tools — 10 Core tools always available, plus discoverable per-model tools from Nautobot apps.

## Core Value

AI agents can query Nautobot network inventory data via MCP tools with full Nautobot permission enforcement, zero extra network hops, and progressive tool discovery.

## Requirements

### Validated

- [x] Nautobot MCP server embedded in Django process via FastMCP ASGI app
- [x] MCPToolRegistry singleton (thread-safe, in-memory) for tool registration
- [x] `post_migrate` signal for tool registration (runs after all apps' ready() hooks)
- [x] Public `register_mcp_tool()` API for third-party Nautobot apps
- [x] 10 Core read tools: device_list, device_get, interface_list, interface_get, ipaddress_list, ipaddress_get, prefix_list, vlan_list, location_list, search_by_name *(Phase 03)*
- [x] Nautobot token auth extraction from Authorization header *(Phase 03)*
- [x] Nautobot object-level permissions via `.restrict(user, action="view")` *(Phase 03)*
- [x] Cursor-based pagination (limit default=25, max=1000) with auto-summarize at 100+ *(Phase 03)*

### Active

- [ ] Streamable HTTP endpoint at `/plugins/nautobot-app-mcp-server/mcp/` with `stateless_http=False`
- [ ] 3 Meta tools: mcp_enable_tools, mcp_disable_tools, mcp_list_tools
- [ ] Session state per Mcp-Session-Id via FastMCP StreamableHTTPSessionManager
- [x] `nautobot-mcp-skill` SKILL.md package with tool reference and workflows *(Phase 04)*
- [ ] All code exercised by unit tests (full coverage of MCP behavior)

### Out of Scope

- Write tools (create/update/delete) — deferred to v2
- MCP `resources` or `prompts` endpoints — focus is tools first
- Redis session backend — in-memory sessions sufficient for v1
- Tool-level field permissions — deferred
- Streaming (SSE rows) — cursor pagination handles memory
- Separate MCP worker process — embed in Django process only

## Context

**Existing codebase state (pre-implementation shell):** `nautobot_app_mcp_server/__init__.py` is a minimal 26-line NautobotAppConfig. No MCP server, no tools, no registry, no auth, no tests. The entire implementation described in `docs/dev/DESIGN.md` is unimplemented.

**Critical concerns from codebase map:**
- Package name: actual = `nautobot_app_mcp_server`, DESIGN.md uses `nautobot_mcp_server/` — must reconcile before implementing
- `base_url = "mcp-server"` in config vs `/plugins/nautobot-mcp-server/` in DESIGN.md — must pick one
- Option A (ASGI mount) in DESIGN.md has `NotImplementedError` — Option B (separate worker) or django-starlette approach needs resolution before Phase 1
- No `fastmcp`/`mcp` Python dependencies in `pyproject.toml` — must add before building

**Sources referenced in DESIGN.md:**
- `nautobot` — Nautobot core plugin architecture
- `netnam-cms-core` — production Nautobot app with optimized querysets
- `notebooklm-mcp-cli` — FastMCP + decorator registry pattern

## Constraints

- **Tech stack**: Python >=3.10 <3.15, Poetry-only (no pip), Nautobot >=3.0.0
- **No database models**: App is a protocol adapter, not a data model app
- **Pylint 10.00/10**: Score must never drop below 10.00
- **Docker Compose dev environment**: All tests run via `poetry run invoke tests`
- **Poetry shell WSL caveat**: `unset VIRTUAL_ENV` required before Poetry commands in WSL
- **Python undeclared**: `VIRTUAL_ENV=/usr` in WSL shell profiles — must unset

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| FastMCP ASGI app embedded in Django | Zero network overhead, direct ORM access, embedded in Nautobot process | — Pending |
| `stateless_http=False` with Mcp-Session-Id | Per-conversation scope state works across all MCP clients | — Pending |
| `post_migrate` signal for tool registration | Fires after all apps' ready() hooks — guarantees MCP server tools registered before third-party apps call `register_mcp_tool()` | — Pending |
| Cursor-based pagination (base64 PK) | Stable across concurrent writes, memory-safe, avoids offset instability | ✅ Implemented Phase 03 |
| Progressive disclosure (Core + Per-model tiers) | Avoids tool explosion in Claude context; session state controls visibility | — Pending |
| `select_related`/`prefetch_related` chains per tool | Memory optimization, follows netnam-cms-core patterns | — Pending |
| Package name `nautobot_app_mcp_server` | Matches actual directory name (DESIGN.md uses `nautobot_mcp_server`) | ⚠️ Needs resolution |
| `base_url = "mcp-server"` | Matches `__init__.py` config; DESIGN.md uses `/plugins/nautobot-mcp-server/` | ⚠️ Needs resolution |
| Option A vs B (ASGI mount vs separate worker) | DESIGN.md Option A has NotImplementedError; resolve before Phase 1 | ⚠️ Needs resolution |

---

## Current Milestone: v1.1.0 MCP Server Refactor

**Goal:** Research django-mcp-server deeply, then refactor the MCP server to fix critical session state and progressive disclosure bugs identified in `docs/dev/mcp-implementation-analysis.md`.

**Target features:**
- Fix P0: Replace `asyncio.run()` with `async_to_sync` in `view.py` — session state broken
- Fix P0: Fix progressive disclosure session context access (`Server.request_context.get()` LookupError)
- Fix P1: Thread-safe singleton locking for `get_mcp_app()`
- Fix P1: User token lookup caching in auth layer
- Fix P1: Derive server address from `request.get_host()` in ASGI scope
- UAT coverage: update UAT tests, ensure all unit tests pass

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---

*Last updated: 2026-04-03 after v1.1.0 milestone started*
