# CONCERNS.md — Codebase Analysis

**Project:** `nautobot-app-mcp-server`
**Date:** 2026-04-01
**Status:** Pre-implementation shell (v0.1.0a0)

---

## Executive Summary

This is a **pre-implementation shell** — not a working application. The entire MCP server, tool registry, auth layer, and per-model tools described in `docs/dev/DESIGN.md` do not exist in code. `nautobot_app_mcp_server/__init__.py` is a minimal Nautobot app config with no functionality. No tests exercise any MCP behavior. The release notes and user docs are filled with `[!!! warning "Developer Note - Remove Me!"]` placeholders.

---

## Critical: Entire MCP Implementation Is Missing

### What EXISTS
- `nautobot_app_mcp_server/__init__.py` — 26 lines. Minimal `NautobotAppConfig` with no logic.
- `nautobot_app_mcp_server/tests/__init__.py` — 2 lines. Empty placeholder.
- `nautobot_app_mcp_server/app-config-schema.json` — Empty config schema (`{}`).
- `pyproject.toml` — Declares the app but has **zero MCP dependencies** (no `fastmcp`, no `mcp`).
- `docs/dev/DESIGN.md` — Detailed design spec for everything that doesn't exist yet.

### What DOES NOT EXIST (per DESIGN.md)
| Component | File | Status |
|---|---|---|
| FastMCP server | `nautobot_mcp_server/mcp/server.py` | **MISSING** |
| Tool registry | `nautobot_mcp_server/mcp/registry.py` | **MISSING** |
| Session state | `nautobot_mcp_server/mcp/session.py` | **MISSING** |
| Auth layer | `nautobot_mcp_server/mcp/auth.py` | **MISSING** |
| Core tools | `nautobot_mcp_server/mcp/tools/core.py` | **MISSING** |
| Pagination helpers | `nautobot_mcp_server/mcp/tools/pagination.py` | **MISSING** |
| Query utilities | `nautobot_mcp_server/mcp/tools/query_utils.py` | **MISSING** |
| Tool registration API | `nautobot_mcp_server/mcp/__init__.py` | **MISSING** |
| `apps.py` (signal wiring) | `nautobot_mcp_server/apps.py` | **MISSING** |
| URL routing | `nautobot_mcp_server/urls.py` | **MISSING** |
| SKILL.md package | `nautobot-mcp-skill/` | **MISSING** |
| `nautobot-mcp-skill/pyproject.toml` | — | **MISSING** |

The directory `nautobot_mcp_server/` does not exist. All code paths referenced in `DESIGN.md` are unimplemented stubs.

---

## Technical Debt

### TD-1: No Production Dependencies Declared
`pyproject.toml` line 33 declares only `nautobot = ">=3.0.0,<4.0.0"` as a main dependency. The app requires:
- `fastmcp` — MCP server framework
- `mcp` — MCP protocol types
- `starlette` or `asgiref` — ASGI bridge for mounting in Django

These are absent from `pyproject.toml`. The app cannot function without them.

### TD-2: Package Name Mismatch
`DESIGN.md` references `nautobot_mcp_server/` throughout, but the actual package directory is `nautobot_app_mcp_server/`. This is a **silent naming inconsistency** — if the `DESIGN.md` plan is followed literally, all import paths and the `base_url` in `__init__.py` (`"mcp-server"`) will need to be reconciled. The `base_url = "mcp-server"` in the config would conflict with the `/plugins/nautobot-mcp-server/` path assumed in `DESIGN.md`.

### TD-3: No Unit Tests
`nautobot_app_mcp_server/tests/__init__.py` is empty. `DESIGN.md` specifies tests for `test_registry.py`, `test_core_tools.py`, and `test_signal_integration.py` — none exist. CI runs `nautobot-server test nautobot_app_mcp_server` which exercises nothing.

Coverage is reported at ~90% via CI but only because there is no production code to cover.

### TD-4: CI Tests Pass Against Empty Code
`poetry run invoke unittest` currently passes because there are no tests. The test suite is a no-op. This creates a **false positive** — CI green doesn't validate anything.

### TD-5: Release v1.0 Is Promotional
`docs/admin/release_notes/version_1.0.md` claims this is a "Production/Stable" release (as declared in `pyproject.toml` classifiers line 14) but contains only placeholders. A fake bug fix `#123` appears in the changelog for a placeholder release dated 2021-09-08 — clearly copied from a cookiecutter template and never updated.

---

## Documentation Issues

### DOC-1: All User-Facing Docs Are Placeholders
Every user-facing document contains `[!!! warning "Developer Note - Remove Me!"]` blocks:
- `docs/user/app_overview.md` — No actual description of what the app does
- `docs/user/app_getting_started.md` — No first-steps guide
- `docs/user/app_use_cases.md` — Not reviewed here but likely similarly empty
- `docs/dev/extending.md` — Placeholder
- `docs/dev/arch_decision.md` — Placeholder
- `README.md` — All content marked "Developer Note - Remove Me!"

The README at line 26 says: "> Developer Note: Add a long (2-3 paragraphs) description of what the App does..." — this was never done.

### DOC-2: DESIGN.md Contains Unsolved Architectural Problems
`docs/dev/DESIGN.md` acknowledges unresolved decisions with `NotImplementedError` or `raise NotImplementedError`:

1. **Line 198** — Django-to-ASGI bridge: `raise NotImplementedError("Use asgiref WsgiToAsgiHandler or Starlette ASGI mount instead")`. The actual ASGI mounting approach is not resolved.

2. **Lines 201-207** — Option A (ASGI mount in `nautobot_config.py`) is described as "the verified approach" but with a fallback to Option B (separate worker) if ASGI mounting is unavailable. Two production deployment strategies with no resolution is a blocker.

3. **Line 774** — The `Critical Files to Modify/Create` table marks 20+ files as CREATE, yet zero of them exist.

### DOC-3: `DESIGN.md` References Non-Existent Source Paths
`DESIGN.md` line 15-17 references local Windows paths:
```
D:\latuan\Programming\nautobot-project\nautobot
D:\latuan\Programming\nautobot-project\netnam-cms-core
D:\latuan\Programming\nautobot-project\notebooklm-mcp-cli
```
These are not in the repo. If the implementation needs to reuse patterns from these projects, those projects must be accessible or their patterns must be documented inline.

---

## Security Concerns

### SEC-1: Anonymous Auth Returns Empty Results — Implicit Trust
`DESIGN.md` line 851 states: "Anonymous/unauthenticated requests return empty results — no error, no exposure."

This is an implicit design decision. However, since the MCP server is not implemented, there is no enforcement of this. If the auth layer is bypassed or misconfigured, anonymous users could receive data silently (not an error) with no indication that permissions were bypassed. This silent-fallback pattern can hide misconfigurations.

**Recommendation:** Explicitly deny anonymous access at the MCP endpoint layer (return HTTP 401) rather than silently returning empty results. Silent empty results should only apply after permissions are evaluated.

### SEC-2: No Token Validation Implemented
`DESIGN.md` line 805-824 specifies `get_user_from_request()` for token extraction. Since `mcp/auth.py` doesn't exist, there is no validation that the MCP server actually enforces this. A deployment that skipped implementing auth would appear to work.

### SEC-3: MCP Endpoint Not Exposed
The `nautobot_app_mcp_server/__init__.py` has `base_url = "mcp-server"` but no `urls.py` exists to route MCP requests. If the app is installed as-is, the MCP endpoint is unreachable. There is no risk of exposure, but the gap between "app installed" and "endpoint active" is a deployment risk.

---

## Performance Concerns

### PERF-1: In-Memory Session State Has No Redis Backend
`DESIGN.md` line 222 states: "Session storage is in-memory. Redis backend is a future swap-in."

For production multi-worker deployments (gunicorn with multiple workers), **in-memory session state is not viable**. Each worker maintains its own session dict. If a client's request routes to a different worker than the one that created the session, session state is lost.

This must be resolved before production use. The doc explicitly defers this, which means the app is not production-ready.

### PERF-2: No Query Optimization in Place
`DESIGN.md` lines 503-513 describe `select_related`/`prefetch_related` chains for each core tool. None of these tools exist yet. The ORM queries will need to be carefully constructed to avoid N+1 problems. There is no query monitoring or test asserting query counts.

### PERF-3: No Rate Limiting
The MCP endpoint has no rate limiting. An AI agent could make unbounded queries. This is a concern for both performance and cost.

---

## Fragile / At-Risk Areas

### FRAG-1: `post_migrate` Signal Timing Is Untested
`DESIGN.md` lines 396-491 describes using `post_migrate` to ensure tool registration happens after all apps' `ready()` hooks. The signal wiring in `apps.py` is specified but `apps.py` doesn't exist. The actual signal behavior in Django's startup sequence is complex and hard to test. This is a high-risk integration point.

### FRAG-2: `sync_to_async` Thread Sensitivity Not Validated
`DESIGN.md` line 609 specifies `thread_sensitive=True` for all `sync_to_async` calls into Django ORM. The comment says "reuses Django's thread → safe for ORM connection pool." This is the correct pattern, but it hasn't been tested. Incorrect thread sensitivity settings can cause Django's thread-local connection pool to be misused, leading to connection leaks or transaction confusion.

### FRAG-3: Option B (Separate Worker) vs Option A (ASGI Mount) Is Unresolved
`DESIGN.md` lines 168-217 describes two deployment strategies. Option A is recommended but has an unresolved `NotImplementedError`. Option B (separate gunicorn worker on port 9001) is presented as the fallback but is essentially a different architecture. The team needs to pick one before implementing.

### FRAG-4: Package Import Path Instability
The `DESIGN.md` uses import paths like `from nautobot_mcp_server.mcp import register_mcp_tool`. If the package is actually `nautobot_app_mcp_server`, these imports will all be wrong. Third-party apps (e.g., `netnam_cms_core`) are expected to import from `nautobot_mcp_server.mcp` — this is a hard API contract. The package name must be resolved before publishing.

### FRAG-5: `mcp_enable_tools` Scope Matching Relies on Naming Conventions
`DESIGN.md` lines 434-440 describes scope matching in `MCPSessionState.get_active_tools()`. While `DESIGN.md` line 35 claims "Explicit `scope` field on `ToolDefinition` — avoids relying on tool name prefix convention," the actual scope matching in the `get_by_scope()` method (lines 314-318) still uses string prefix matching (`scope.startswith(f"{scope}.")`). This is fragile if scopes are not consistently namespaced.

---

## Version / Dependency Risks

### VER-1: Development Status Misleading
`pyproject.toml` line 14 declares `"Development Status :: 5 - Production/Stable"` — the highest maturity level. This is a cookiecutter artifact. The app is a pre-Alpha shell.

### VER-2: Classifier Declares Python 3.14 Support
`pyproject.toml` lines 17-20 declare support for Python 3.10 through 3.14. Python 3.14 has not been released as of April 2026 (target release: October 2025). This is likely a copy-paste error. Verify actual support matrix.

### VER-3: `nautobot = ">=3.0.0,<4.0.0"` Is Wide
No upper bound constraint on Nautobot beyond the major version. `DESIGN.md` line 33 in the sources section references Nautobot core but doesn't pin versions. API compatibility with Nautobot's ORM and permissions system must be verified against each Nautobot release.

---

## Test Gaps

| Test File | Status |
|---|---|
| `tests/__init__.py` | Empty stub |
| `test_registry.py` | **MISSING** — DESIG N.md specifies this |
| `test_core_tools.py` | **MISSING** |
| `test_signal_integration.py` | **MISSING** |

The `DESIGN.md` "Verification" section (lines 782-798) lists 14 verification steps. None are automated. CI cannot verify the app works.

---

## Process Issues

### PROC-1: Changelog Contains Fake Entries
`docs/admin/release_notes/version_1.0.md` contains a fake bug fix referencing `#[123]` dated 2021-09-08 — clearly a template artifact. Release notes for a v1.0 release that describe nothing are misleading.

### PROC-2: Version Number Pre-Release Marker
`pyproject.toml` line 3: `version = "0.1.0a0"` — this is correct for a pre-release, but the CI classifier and release process treat this as a real release. The v1.0.md changelog should not exist at this stage.

---

## Summary Table

| ID | Category | Severity | Issue |
|---|---|---|---|
| TD-1 | Tech Debt | **Critical** | No MCP dependencies in pyproject.toml |
| TD-2 | Tech Debt | **High** | Package name mismatch: `nautobot_mcp_server` vs `nautobot_app_mcp_server` |
| TD-3 | Tech Debt | **High** | Zero unit tests |
| TD-4 | Tech Debt | **High** | CI passes on empty test suite |
| TD-5 | Tech Debt | **Medium** | v1.0 release notes are placeholders |
| DOC-1 | Documentation | **High** | All user docs are placeholder stubs |
| DOC-2 | Documentation | **High** | DESIGN.md has unresolved `NotImplementedError` |
| DOC-3 | Documentation | **Medium** | DESIGN.md references local Windows paths |
| SEC-1 | Security | **High** | Silent empty-result auth pattern can hide misconfigs |
| SEC-2 | Security | **Medium** | No token validation exists |
| SEC-3 | Security | **Low** | MCP endpoint not actually wired |
| PERF-1 | Performance | **High** | In-memory session state broken in multi-worker deployments |
| PERF-2 | Performance | **Medium** | No query optimization tests |
| PERF-3 | Performance | **Low** | No rate limiting |
| FRAG-1 | Fragility | **High** | `post_migrate` signal timing is untested |
| FRAG-2 | Fragility | **Medium** | `sync_to_async` thread sensitivity untested |
| FRAG-3 | Fragility | **High** | Deployment strategy (Option A vs B) unresolved |
| FRAG-4 | Fragility | **High** | Package import path is an API contract with third parties |
| FRAG-5 | Fragility | **Medium** | Scope matching still uses string prefix logic |
| VER-1 | Version | **Medium** | "Production/Stable" classifier on pre-Alpha code |
| VER-2 | Version | **Low** | Python 3.14 declared but not released |
| PROC-1 | Process | **Low** | Changelog contains fake entries |

---

## Recommended Priority Order

1. **Decide package name** — resolve `nautobot_mcp_server` vs `nautobot_app_mcp_server` before writing any code
2. **Add MCP dependencies** to `pyproject.toml` (`fastmcp`, `mcp`, `starlette`)
3. **Pick deployment strategy** — Option A (ASGI mount) or Option B (separate worker)
4. **Implement minimal viable MCP server** — FastMCP mount + `device_list` tool + token auth
5. **Write real tests** for the registry and tool execution
6. **Replace all placeholder docs** with real content
7. **Fix CI** to actually test MCP behavior
8. **Address session state** with Redis backend before production
