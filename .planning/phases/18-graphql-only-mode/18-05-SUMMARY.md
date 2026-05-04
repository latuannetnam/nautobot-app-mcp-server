---
phase: "18-graphql-only-mode"
plan: "18-05"
subsystem: Documentation
tags:
  - graphql-only-mode
  - documentation
key-files:
  created: []
  modified:
    - CLAUDE.md
    - nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md
metrics:
  commits: 1
  tasks: 2
  lines_added: 22
---

## Summary

Documented `NAUTOBOT_MCP_ENABLE_ALL` in both CLAUDE.md and SKILL.md:

**CLAUDE.md:** Added row to Gotchas table:
`| GraphQL-only mode hides non-GraphQL tools | Set/unset NAUTOBOT_MCP_ENABLE_ALL env var and restart (default: GQL-only mode on) |`

**SKILL.md:** Added "GraphQL-Only Mode" section before "Meta Tools" with:
- Description of default behavior (only graphql_query + graphql_introspect visible)
- How to enable all 15 tools (set NAUTOBOT_MCP_ENABLE_ALL=true)
- Table showing env variable, default, and effect

## Commits

| # | Description |
|---|-------------|
| 1 | docs(phase-18): document NAUTOBOT_MCP_ENABLE_ALL in CLAUDE.md and SKILL.md |

## Deviations

None — implementation matched plan exactly.

## Self-Check

**PASSED**

- `grep -n "NAUTOBOT_MCP_ENABLE_ALL" CLAUDE.md` → found in Gotchas table
- `grep -n "GraphQL-Only Mode\|NAUTOBOT_MCP_ENABLE_ALL" SKILL.md` → found section and env var name