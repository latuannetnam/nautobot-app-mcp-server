# 17-REVIEW-FIX.md — Phase 17 Review Fixes

**Phase:** 17-UAT-and-Documentation
**Fixed by:** Claude Sonnet 4.6
**Date:** 2026-04-16
**Commits:** `7a24ba5`, `7532fc5`

---

## Summary

All 10 findings (Critical ×1, High ×1, Medium ×2, Low ×6) have been addressed.

---

## Fixes Applied

### Finding 1 — Critical: `pyproject.toml` version mismatch ✅

**File:** `pyproject.toml` line 3
**Before:** `version = "0.2.0"`
**After:** `version = "1.2.0"`
**Commit:** `7a24ba5`

### Finding 2 — High: `requests` and `python-dotenv` in main dependencies ✅

**File:** `pyproject.toml` lines 39–40
**Before:** Listed under `[tool.poetry.dependencies]`
**After:** Moved to `[tool.poetry.group.dev.dependencies]` (alongside the existing dev deps)
**Rationale:** These are only used by `scripts/run_mcp_uat.py`, `scripts/test_mcp_simple.py`, and
`management/commands/import_production_data.py` — none of which ship in the production Docker image.
**Commit:** `7a24ba5`

### Finding 3 — Medium: `ruff` `target-version = "py38"` inconsistent with Python floor ✅

**File:** `pyproject.toml` line 109
**Before:** `target-version = "py38"`
**After:** `target-version = "py310"`
**Commit:** `7a24ba5`

### Finding 4 — Medium: `nautobot_import.env` path does not exist in the repo ✅

**Files:** `scripts/test_mcp_simple.py` line 18, `scripts/run_mcp_uat.py` line 41
**Before:** `Path(__file__).parent.parent / "nautobot_import.env"`
**After:** `Path(__file__).parent.parent / "development" / "creds.env"`
**Rationale:** `development/creds.env.example` is the documented template users copy to
`development/creds.env`. The new path matches the onboarding instructions in `CLAUDE.md`.
**Commit:** `7532fc5`

### Finding 5 — Low: Token format in anonymous/invalid-token tests is misleading ✅

**Files:** `scripts/run_mcp_uat.py` lines 645, 663, 819
**Before:** `nbapikey_invalid_token_00000000000000`, `nbapikey_invalid_write_only_token_00000`
**After:** `"a" * 40` (T-27, T-40), `"0" * 40` (T-29)
**Rationale:** Matches the documented 40-char raw hex format (no prefix). Raw hex is
unambiguous and consistent with the codebase auth docs.
**Commit:** `7532fc5`

### Finding 6 — Low: `MCPToolError.__init__` call uses positional args ✅

**File:** `scripts/run_mcp_uat.py` line 173
**Before:** `raise MCPToolError(-32602, error_text)`
**After:** `raise MCPToolError(code=-32602, message=error_text)`
**Rationale:** Keyword arguments make the call self-documenting and future-proof against
signature changes.
**Commit:** `7532fc5`

### Finding 7 — Low: `TestRunner.test()` `expected_error` parameter is dead code ✅

**File:** `scripts/run_mcp_uat.py` line 240
**Before:** `def test(self, name: str, fn, expected_error: type | None = None)` plus the
conditional branch `if expected_error and e.code == expected_error.code:`
**After:** `def test(self, name: str, fn)` — dead branch removed
**Rationale:** No call site ever passed `expected_error`; the branch was never exercised.
**Commit:** `7532fc5`

### Finding 8 — Low: Incomplete `_parse_sse` error message truncation ✅

**File:** `scripts/test_mcp_simple.py` line 124
**Before:** `raise RuntimeError(f"No SSE data line in response: {text[:200]!r}")`
**After:** `raise RuntimeError(f"No SSE data line in response: {text[:200]}")`
**Rationale:** Removes the `!r` repr-coercion so the truncation is applied to the plain
string, making the error message cleaner and easier to read in test output.
**Commit:** `7532fc5`

### Finding 9 — Low: T-43 duplicates T-38 ✅

**File:** `scripts/run_mcp_uat.py` lines 854–867
**Before:** T-43 sent `{ devices {` (unclosed brace) and asserted `"Syntax Error"` —
identical to T-38.
**After:** T-43 now sends `{ devices(limit: 5) { nonexistent_field } }` and asserts a
field-not-found error (`"nonexistent_field" in str(e) or "Unknown field" in str(e)`).
This genuinely tests structured error handling for a *different* error category than T-38.
**Commit:** `7532fc5`

### Finding 10 — Low: T-28 does not assert data presence ✅

**File:** `scripts/run_mcp_uat.py` lines 653–658
**Before:** `has_data = len(...) > 0` computed but not asserted; test passed regardless.
**After:** `assert has_data, "T-28 requires a populated DB; no devices found"`
**Rationale:** The test name "Valid token — returns data" promises data is returned.
Adding the assertion makes it fail fast against an unpopulated DB, rather than
silently passing with `{"has_data": false}`.
**Commit:** `7532fc5`

---

## Skipped

None — all 10 findings addressed.

---

## Commit History

| Commit | Description |
|--------|-------------|
| `7a24ba5` | fix: bump version to 1.2.0 in pyproject.toml |
| `7532fc5` | fix: update ENV_FILE path and token format in UAT scripts |

The `pyproject.toml` ruff `target-version` fix and the `requests`/`python-dotenv` move to
dev dependencies landed in commit `7a24ba5` alongside the version bump.
