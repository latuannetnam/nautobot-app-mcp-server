# Phase 17 Review — UAT & Documentation Scripts

**Reviewer:** Claude Sonnet 4.6
**Files Reviewed:** `scripts/test_mcp_simple.py`, `scripts/run_mcp_uat.py`, `pyproject.toml`
**Depth:** Quick

---

## Summary

No security vulnerabilities or bugs that would break correct operation. Two production-grade issues and several minor quality notes are documented below.

---

## Critical / High

### 1. `pyproject.toml` version mismatch

- **File:** `pyproject.toml` line 3
- **Issue:** `version = "0.2.0"` — does not match the shipped version `v1.2.0` documented in `CLAUDE.md`.
- **Impact:** `poetry version` and `towncrier` release notes would produce the wrong version number.
- **Fix:** Update to `version = "1.2.0"`.

---

### 2. `requests` and `python-dotenv` in main dependencies

- **File:** `pyproject.toml` lines 39–40
- **Issue:** Both packages are listed as regular `[tool.poetry.dependencies]` but are only used by `scripts/test_mcp_simple.py`, `scripts/run_mcp_uat.py`, and `management/commands/import_production_data.py` — none of which ship in the production Docker image.
- **Impact:** Bloats the production container image; these packages are never needed by the MCP server itself.
- **Fix:** Move both to `[tool.poetry.group.dev.dependencies]`.

---

## Medium

### 3. `ruff` `target-version = "py38"` inconsistent with Python floor

- **File:** `pyproject.toml` line 109
- **Issue:** `target-version = "py38"` but the package requires `python = ">=3.10,<3.15"`.
- **Impact:** Low — `ruff` still analyzes the actual runtime Python. However, `py38` may cause ruff to suppress rules that are only violations on newer interpreters (e.g., from `f-string`, `pattern matching`, etc.).
- **Fix:** Set `target-version = "py310"`.

---

### 4. `nautobot_import.env` path does not exist in the repo

- **Files:** `scripts/test_mcp_simple.py` line 18, `scripts/run_mcp_uat.py` line 41
- **Issue:** Both scripts look for `Path(__file__).parent.parent / "nautobot_import.env"`, but only `development/creds.env.example` exists in the repo.
- **Impact:** The `load_dotenv` call silently does nothing on a fresh clone. Scripts still work because env vars can be set externally, but first-run experience is confusing.
- **Fix:** Update `ENV_FILE` to point to `development/creds.env` (which users are instructed to create from the `.example`), or add a clear comment that `nautobot_import.env` must be created manually.

---

## Low / Notes

### 5. Token format in anonymous/invalid-token tests is misleading

- **Files:** `scripts/run_mcp_uat.py` lines 645, 663, 819
- **Issue:** Tests use tokens with `nbapikey_` prefix (`"nbapikey_invalid_token_00000000000000"`, `"nbapikey_invalid_write_only_token_00000"`), but the auth layer expects **raw 40-char hex with no prefix** (documented correctly in the file header and `CLAUDE.md`).
- **Impact:** A reader could be misled into thinking `nbapikey_<hex>` is a valid format. No functional bug — the tests are correct and documented.
- **Fix:** Replace with raw hex strings that match the documented format, e.g., `"a" * 40` or `"0" * 40"`.

### 6. `MCPToolError.__init__` signature inconsistent with call sites

- **File:** `scripts/run_mcp_uat.py`
- **Issue:** `MCPToolError(code, message, data=None)` but at line 173 the call passes `(code, error_text)` — relying on positional arg injection where `error_text` lands in `message` and `data` gets a default. No runtime bug, but fragile.
- **Fix:** Use keyword arguments at the call site: `MCPToolError(code=..., message=error_text)`.

### 7. `TestRunner.test()` `expected_error` parameter is dead code

- **File:** `scripts/run_mcp_uat.py` line 240
- **Issue:** `expected_error: type | None = None` parameter is accepted but no call site ever passes it. The code path checking `e.code == expected_error.code` (line 248) is never exercised.
- **Impact:** No functional impact; low maintenance burden.
- **Fix:** Remove the parameter (and the conditional branch), or wire up T-16/T-18/T-21 to use it.

### 8. Incomplete `_parse_sse` error message in `test_mcp_simple.py`

- **File:** `scripts/test_mcp_simple.py` line 124
- **Issue:** `raise RuntimeError(f"No SSE data line in response: {text[:200]!r}")` — if the SSE body is binary or non-text, slicing may produce confusing output.
- **Impact:** Minor — this is a smoke test script, not production code.
- **Fix:** Truncate after splitting, not on the raw text, e.g., `text[:200]` instead of `text[:200]!r`.

### 9. `run_mcp_uat.py` test T-43 duplicates T-38

- **File:** `scripts/run_mcp_uat.py` lines 854–867 vs 793–807
- **Issue:** Both T-38 and T-43 send `{ devices {` (unclosed brace) and assert `"Syntax Error"` in errors. The category label for T-43 ("structured errors — no exception thrown") is functionally identical to T-38's assertion.
- **Impact:** One test is redundant; no correctness issue.
- **Fix:** Replace T-43 with a genuinely different case, e.g., a depth-limit or complexity-exceeded query, per the existing T-43 docstring.

### 10. T-28 does not assert data presence

- **File:** `scripts/run_mcp_uat.py` lines 653–658
- **Issue:** T-28 ("Valid token — returns data") only checks `has_data = len(...) > 0` and passes regardless of whether data is present. The test name over-promises.
- **Impact:** Test passes with empty DB just as easily as with populated data.
- **Fix:** Add `assert has_data` when the test is run against a known-populated DB, or rename to reflect it is informational only.

---

## Security Notes

- No hardcoded credentials. Tokens all use `os.environ.get` with fallback to a clearly-named placeholder (`"0123...abcd"`). ✅
- No `eval`, `exec`, or string interpolation of untrusted input. ✅
- `Authorization: Token <token>` header sent on every request — token lives only in env vars, not in code. ✅
- No SQL injection risk — all queries go through Django ORM. ✅
- Both scripts are UAT/test utilities that run from the host, not inside the server. No new attack surface introduced. ✅
