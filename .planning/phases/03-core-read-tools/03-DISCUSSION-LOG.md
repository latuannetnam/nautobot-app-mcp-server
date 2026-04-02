# Phase 3: Core Read Tools - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-02
**Phase:** 03-core-read-tools
**Mode:** discuss
**Areas discussed:** Search query format, Not-found behavior, Identifier lookup

## Search Query Format

| Option | Description | Selected |
|--------|-------------|----------|
| AND match | Both terms must appear somewhere in the name (recommended) | ✓ |
| OR match | Either term matches | |
| Phrase match | Exact sequence only | |

**User's choice:** AND match — both "juniper" AND "router" must appear in the name.
**Notes:** More precise, fewer false positives for fuzzy name search.

---

## Not-Found Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Error message | Raise/die with clear error: 'Device "router-01" not found' (recommended) | ✓ |
| Null / empty | Return null or empty object | |
| Null with warning | Return null AND log a warning | |

**User's choice:** Error message — MCP best practice so the caller knows something went wrong.
**Notes:** Consistent with how MCP tools should signal failures.

---

## Identifier Lookup

| Option | Description | Selected |
|--------|-------------|----------|
| Name OR pk (auto-detect) | UUID-like → pk lookup, otherwise → name lookup (recommended) | ✓ |
| Name only | Only name lookup | |
| Separate parameters | `name=` and `pk=` as separate optional params | |

**User's choice:** Name OR pk auto-detect — simpler for callers.
**Notes:** AI agents and human users naturally think in terms of names.

---

## Gray Areas Resolved by Scope

The following areas were NOT discussed (decided by ROADMAP or prior phases):
- **Pagination constants:** cursor-based `base64(str(pk))`, default=25, max=1000, summarize-at-100 — from ROADMAP.md (PAGE-01 to PAGE-04)
- **Auth enforcement:** `.restrict(user, "view")` on every queryset — from Phase 2 STATE.md (AUTH-03)
- **Core tools always visible:** scope="core", bypass progressive disclosure — from Phase 2 (SESS-06)
- **Tool registration:** module-level `register_mcp_tool()` calls — from Phase 1 codebase pattern
- **Async/ORM bridge:** `sync_to_async(fn, thread_sensitive=True)` — from ROADMAP.md (PAGE-05)

---

## Claude's Discretion

The following were left to Claude during planning/execution:
- Exact serializer field lists per tool
- `select_related`/`prefetch_related` chain configuration per tool
- `search_by_name` result limit behavior
- Error message format for not-found
- Test structure and mock strategy for `test_core_tools.py`

---

## Deferred Ideas

None — discussion stayed within Phase 3 scope.

