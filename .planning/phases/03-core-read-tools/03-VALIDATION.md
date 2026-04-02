---
phase: 03
slug: core-read-tools
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-02
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (pytest-style via `nautobot-server test`) |
| **Config file** | `pyproject.toml` [tool.coverage.run], `pyproject.toml` [tool.pytest] |
| **Quick run command** | `poetry run invoke unittest` |
| **Full suite command** | `poetry run invoke tests` |
| **Estimated runtime** | ~30-60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `poetry run invoke unittest`
- **After every plan wave:** Run `poetry run invoke tests`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | PAGE-01 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | PAGE-02 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | PAGE-03 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | PAGE-04 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | PAGE-05 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | TOOL-01 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | TOOL-02 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | TOOL-03 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 2 | TOOL-04 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-05 | 02 | 2 | TOOL-05 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-06 | 02 | 2 | TOOL-06 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-07 | 02 | 2 | TOOL-07 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-08 | 02 | 2 | TOOL-08 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-02-09 | 02 | 2 | TOOL-09 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 3 | TOOL-10 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 3 | TEST-02 | unit | `poetry run invoke unittest` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `nautobot_app_mcp_server/mcp/tests/test_pagination.py` — covers PAGE-01 through PAGE-05
- [ ] `nautobot_app_mcp_server/mcp/tests/test_tools.py` — covers TOOL-01 through TOOL-09
- [ ] `nautobot_app_mcp_server/mcp/tests/test_search.py` — covers TOOL-10
- [ ] `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — covers TEST-02 (auth enforcement, anonymous fallback)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| None | — | — | All phase behaviors have automated verification. |

*If none: "All phase behaviors have automated verification."*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
