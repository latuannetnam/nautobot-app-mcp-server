---
phase: 15
slug: introspection-permissions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test (nautobot-server test) |
| **Config file** | `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` |
| **Quick run command** | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool` |
| **Full suite command** | `poetry run nautobot-server test nautobot_app_mcp_server` |
| **Estimated runtime** | ~15 seconds (graphql_tool tests only) |

---

## Sampling Rate

- **After every task commit:** Run `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_graphql_tool`
- **After every plan wave:** Run `poetry run nautobot-server test nautobot_app_mcp_server`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15.1-01 | 01 | 1 | GQL-08, GQL-09 | — | Auth required (no schema leak) | unit | `nautobot-server test test_graphql_tool` | ✅ | ⬜ pending |
| 15.3-01 | 01 | 1 | GQL-09 | — | N/A | unit | `nautobot-server test test_graphql_tool` | ✅ | ⬜ pending |
| 15.2-01 | 02 | 1 | GQL-13 | T-15-01 | Anonymous gets empty | unit | `nautobot-server test test_graphql_tool` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` — add `GraphQLIntrospectHandlerTestCase` test class with `test_introspect_returns_sdl_string`, `test_sync_graphql_introspect_sdl_valid_via_build_schema`, `test_introspect_raises_on_anonymous`, `test_auth_required_call_order` methods

*All other infrastructure already exists from Phase 14.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `graphql_introspect` returns valid SDL (end-to-end) | GQL-09 | Requires live Nautobot DB with populated models for realistic SDL | Start container (`invoke start`), call `graphql_introspect` tool via MCP client, assert response is non-empty str containing `"type Query"` |

*All unit-testable behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

