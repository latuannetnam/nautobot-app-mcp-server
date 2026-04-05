---
phase: 11
slug: auth-refactor
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django Test (nautobot-server test) |
| **Config file** | `pyproject.toml` (poetry environment) |
| **Quick run command** | `docker exec nautobot-app-mcp-server-nautobot-1 poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_auth` |
| **Full suite command** | `docker exec nautobot-app-mcp-server-nautobot-1 poetry run nautobot-server test nautobot_app_mcp_server` |
| **Estimated runtime** | ~2 seconds (auth tests only) |

---

## Sampling Rate

- **After every task commit:** Run `test_auth` quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 11-01 | 1 | P4-01 | T-11-01 | Token read from FastMCP headers, not Django request | unit | `grep "async def get_user_from_request" auth.py` | ✅ | ⬜ pending |
| 11-01-02 | 11-01 | 1 | P4-01 | T-11-01 | Authorization header parsed as `Token <hex>` | unit | `grep "Authorization" auth.py` | ✅ | ⬜ pending |
| 11-02-01 | 11-02 | 1 | P4-02 | — | Cache stores `str(user.pk)` in `ctx.set_state("mcp:cached_user")` | unit | `grep "mcp:cached_user" auth.py` | ✅ | ⬜ pending |
| 11-02-02 | 11-02 | 1 | P4-02 | — | No `_cached_user` attribute remains | unit | `grep "_cached_user" auth.py` → 0 matches | ✅ | ⬜ pending |
| 11-02-03 | 11-02 | 1 | P4-02 | — | `get_state`/`set_state` are `await`ed | unit | `grep -n "await ctx.get_state\|await ctx.set_state" auth.py` | ✅ | ⬜ pending |
| 11-02-04 | 11-02 | 1 | P4-02 | — | Tests use AsyncMock for state API | unit | `grep "get_state\|set_state" test_auth.py` | ✅ | ⬜ pending |
| 11-03-01 | 11-03 | 1 | P4-03 | — | 10 core tools call `await get_user_from_request(ctx)` | unit | `grep -c "await get_user_from_request" core.py` → 10 | ✅ | ⬜ pending |
| 11-03-02 | 11-03 | 1 | P4-03 | — | `.restrict(` still present in query_utils.py | unit | `grep -c "\.restrict(" query_utils.py` → 10 | ✅ | ⬜ pending |
| 11-04-01 | 11-04 | 2 | P4-04 | — | nginx directive in upgrade.md | manual | `grep "proxy_set_header Authorization" docs/admin/upgrade.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- `nautobot_app_mcp_server/mcp/tests/test_auth.py` — existing file, update for async API (no stubs needed)
- `conftest.py` — existing shared fixtures, update `_make_mock_ctx` for async `get_state`/`set_state`

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| nginx config directive in upgrade.md | P4-04 | Requires reading docs to confirm formatting and context | `grep -A5 "proxy_set_header Authorization" docs/admin/upgrade.md`; confirm directive appears with explanatory comment |

*All other behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending