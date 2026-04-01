# Phase 2: Authentication & Sessions - Discussion Log

> **Audit trail only.** Do not use as input to planning or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-01
**Phase:** 02-authentication-sessions
**Mode:** discuss
**Areas discussed:** Session storage architecture, Progressive disclosure mechanism, Scope hierarchy, Anonymous auth logging level

---

## Session Storage Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Inside FastMCP session dict (Recommended) | FastMCP handles Mcp-Session-Id lifecycle; we read/write session data directly. One store. | ✓ |
| Separate module-level MCPSessionStore | Own dict keyed by Mcp-Session-Id, separate from FastMCP's session. More control, more sync complexity. | |
| Thread-local in addition to session | MCPSessionState in FastMCP session, plus thread-local accessor. More layers. | |

**User's choice:** Inside FastMCP session dict
**Notes:** FastMCP already manages session lifecycle. Storing `enabled_scopes`/`enabled_searches` directly in the session dict avoids a second store to keep in sync.

---

## Progressive Disclosure Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Custom @mcp.list_tools() with ToolContext (Recommended) | Override FastMCP's list_tools using ToolContext. Access session via ctx.request_context.request. Works natively with FastMCP 3.x. | ✓ |
| Module-level session accessor function | Global get_session_tools(ctx) function. Centralizes access but adds a helper layer. | |
| FastMCP context_var pattern | contextvars for session ID. Clean async, but more indirection. | |

**User's choice:** Custom @mcp.list_tools() with ToolContext
**Notes:** FastMCP's ToolContext gives direct access to the session dict. No extra accessor needed.

---

## Scope Hierarchy — Child Scope Activation

| Option | Description | Selected |
|--------|-------------|----------|
| Children inherit parent (Recommended) | Enabling 'dcim' makes all dcim.* tools visible. Common hierarchical pattern, simpler UX. | ✓ |
| Exact scope only | Each scope must be enabled individually. More explicit, more tool calls. | |
| Exact + one level down | 'dcim' enables 'dcim.*' but not 'dcim.interface.*'. Middle ground. | |

**User's choice:** Children inherit parent
**Notes:** Registry's get_by_scope() already implements hierarchical matching. Same for disable — disabling parent disables all children.

---

## Anonymous Auth Logging Level

| Option | Description | Selected |
|--------|-------------|----------|
| WARNING for no token, DEBUG for invalid token (Recommended) | No token = possible misconfiguration (WARNING). Invalid token = common/testing (DEBUG). | ✓ |
| DEBUG for both | Both quiet. Only WARN on suspicious patterns. | |
| INFO for both | Log every anonymous attempt at INFO. Most visible, noisy. | |

**User's choice:** WARNING for no token, DEBUG for invalid token
**Notes:** No token signals possible misconfiguration — needs attention. Invalid token is common in testing and CI — quieter is appropriate.

---

## Claude's Discretion

- Session expiry duration — FastMCP default acceptable
- Exact session dict structure (set vs list for enabled_scopes) — use set for O(1) membership
- FastMCP session TTL configuration — use FastMCP defaults

## Deferred Ideas

None — discussion stayed within phase scope.

---
*Phase: 02-authentication-sessions*
*Context gathered: 2026-04-01*
