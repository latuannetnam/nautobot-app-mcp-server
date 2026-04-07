# Project Roadmap — `nautobot-app-mcp-server`

**Project:** Nautobot App MCP Server
**Horizon:** v2.0
**Last updated:** 2026-04-07 after v1.2.0 shipped

---

## Milestones

- ✅ **v1.0 MVP** — Phases 0–4 (shipped 2026-04-02)
- ✅ **v1.1.0** — Phases 5–6 (shipped 2026-04-04)
- ✅ **v1.2.0** — Phases 7–13 (shipped 2026-04-07)
- 📋 **v2.0** — TBD (write tools, Redis sessions, horizontal scaling)

---

## Progress

| # | Phase | Milestone | Plans | Status | Completed |
|---|-------|-----------|-------|--------|-----------|
| 0 | Project Setup | v1.0 | 4/4 | Complete | 2026-04-01 |
| 1 | MCP Server Infrastructure | v1.0 | 11/11 | Complete | 2026-04-01 |
| 2 | Auth & Sessions | v1.0 | 7/7 | Complete | 2026-04-01 |
| 3 | Core Read Tools | v1.0 | 3/3 | Complete | 2026-04-02 |
| 4 | SKILL.md Package | v1.0 | 3/3 | Complete | 2026-04-02 |
| 5 | MCP Server Refactor | v1.1.0 | 7/7 | Complete | 2026-04-04 |
| 6 | UAT & Smoke Tests | v1.1.0 | 1/1 | Complete | 2026-04-04 |
| 7 | Setup | v1.2.0 | 3/3 | Complete | 2026-04-05 |
| 8 | Infrastructure | v1.2.0 | 4/4 | Complete | 2026-04-05 |
| 9 | Tool Registration | v1.2.0 | 6/6 | Complete | 2026-04-05 |
| 10 | Session State | v1.2.0 | 4/4 | Complete | 2026-04-05 |
| 11 | Auth Refactor | v1.2.0 | 2/2 | Complete | 2026-04-06 |
| 12 | Bridge Cleanup | v1.2.0 | 6/6 | Complete | 2026-04-06 |
| 13 | UAT & Validation | v1.2.0 | 5/5 | Complete | 2026-04-07 |

---

## v1.2.0 Archived

<details>
<summary>✅ v1.2.0 — Separate Process Refactor (SHIPPED 2026-04-07)</summary>

**Goal:** Migrate MCP server from embedded (Option A) to standalone (Option B).

**What shipped:**
- `start_mcp_server.py` + `start_mcp_dev_server.py` management commands
- FastMCP runs as standalone process on port 8005; `invoke start` launches it automatically
- `tool_registry.json` for cross-process plugin discovery
- All 10 core tools async + `sync_to_async(thread_sensitive=True)`
- Session state via FastMCP `ctx.get_state()`/`ctx.set_state()` (no monkey-patching)
- Auth: token from FastMCP headers, cached via `ctx.set_state("mcp:cached_user")`
- Embedded architecture deleted: `view.py`, `server.py`, `urls.py` removed
- UAT: 37/37 passed | Unit tests: 91/91 passed (89 pass, 2 skipped)
- FastMCP/MCP SDK outputSchema conflict fixed via `output_schema=None` in source

**Phase details:** `.planning/milestones/v1.2.0-ROADMAP.md`
**Requirements:** `.planning/milestones/v1.2.0-REQUIREMENTS.md`

</details>

---

## v2.0 — Next Milestone

**Status:** Planning pending

**Candidate features:**
- Write tools (create/update/delete)
- Redis session backend for `--workers > 1` horizontal scaling
- Tool-level field permissions

**Next step:** `/gsd-new-milestone`

---

*Roadmap last updated: 2026-04-07 after v1.2.0 shipped*
*Archived milestones: `.planning/milestones/`*
