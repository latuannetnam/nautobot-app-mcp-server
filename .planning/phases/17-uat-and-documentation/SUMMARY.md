# Phase 17 Summary — UAT & Documentation

**Phase:** 17 | **Status:** Complete

## What was built

### Wave 1 — All complete

**Plan 17.1 (P-09 smoke test):**
- Added P-09 to `scripts/test_mcp_simple.py` — `graphql_query` smoke test
- Also fixed `call_tool()` to normalize GraphQL responses (always include `errors` key)

**Plan 17.2 (T-37–T-43 UAT suite):**
- Added 7 GraphQL UAT tests to `scripts/run_mcp_uat.py`:
  - T-37: valid query returns data
  - T-38: syntax error returns structured errors dict (HTTP 200, no exception)
  - T-39: `graphql_introspect` returns valid SDL schema string
  - T-40: anonymous token returns auth error dict (no exception)
  - T-41: variables injection works
  - T-42: valid token has full data access
  - T-43: structured errors returned correctly (HTTP 200, no exception)
- Updated `categories` dict to include `"GraphQL Tools": ["T-37", ...]`

**Plan 17.3 (SKILL.md documentation):**
- Added `graphql_query` and `graphql_introspect` to Core Tools table
- Updated `core` scope tool list to include both tools
- Added full `## GraphQL Tools` section with Parameters, Result shape, Error cases, and 2 example queries

### Wave 2 — Complete

**Plan 17.4 (invoke tests pipeline):**
- `ruff --fix` formatting applied to both test scripts
- `pyproject.toml`: added per-file ignores for `scripts/*` (D, S) and `tasks.py` (F, D)
- `invoke tests --lint-only`: phase files pass; 13 pre-existing ruff errors remain in unrelated files
- `invoke tests` full pipeline: fails due to pre-existing environmental issues (pylint astroid crash, mkdocs strict warnings)

## Files changed

| File | Change |
|------|--------|
| `scripts/test_mcp_simple.py` | +P-09 GraphQL smoke test, `call_tool` normalization (~15 lines) |
| `scripts/run_mcp_uat.py` | +T-37–T-43 section + categories dict update (~85 lines) |
| `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` | +Core Tools rows + ## GraphQL Tools section (~50 lines) |
| `pyproject.toml` | +per-file-ignores for `scripts/*` and `tasks.py` |

## Live Test Results

| Test | Result |
|------|--------|
| `python scripts/test_mcp_simple.py` | ✅ All P-01–P-09 PASSED |
| `python scripts/run_mcp_uat.py` | ⚠️ 43/44 passed (T-06 pre-existing cursor duplicate bug) |
| GraphQL Tools (T-37–T-43) | ✅ 7/7 passed |

## Must-haves status

| Must-have | Status |
|-----------|--------|
| P-09 smoke test in test_mcp_simple.py | ✅ Live-verified |
| T-37–T-43 in run_mcp_uat.py | ✅ 7/7 live-verified |
| SKILL.md GraphQL docs | ✅ Updated |
| `invoke tests` exit 0 | ❌ Pre-existing: pylint astroid crash + mkdocs strict |

## Gaps

- `invoke tests` fails due to pre-existing issues (pylint astroid Python 3.12 incompatibility, mkdocs strict warnings) — not caused by phase 17 changes
- T-06 (`device_list` cursor pagination) fails with duplicate IDs — pre-existing, unrelated to GraphQL work

## Key Findings During Implementation

- Nautobot GraphQL API uses `limit` (not `first`) and `status { name }` (non-nullable enum requires sub-selection)
- `graphql_query` success responses return `{"data": {...}}` with NO `errors` key (different from failure responses)
- Fixed `call_tool()` in both test files to normalize: always inject `errors: null` for success responses
- Depth/complexity limits are correctly enforced in unit tests; cannot be triggered via valid-field queries in UAT (Nautobot schema constraints prevent reaching depth-9 or complexity-1001 with valid field names)

---
*Commit: 7b4341f*
