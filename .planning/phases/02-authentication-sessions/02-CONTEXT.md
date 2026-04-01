# Phase 2: Authentication & Sessions - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Add token-based auth and per-session tool visibility state. Auth extracts the Nautobot user from the MCP request context; sessions track which tool scopes are enabled per `Mcp-Session-Id`. No write tools, no pagination yet — those belong to Phase 3.

**Phase 2 produces:** `MCPSessionState` dataclass, `mcp_enable_tools`/`mcp_disable_tools`/`mcp_list_tools` tools, `get_user_from_request()`, auth enforcement on all querysets, `TEST-06` auth test.

</domain>

<decisions>
## Implementation Decisions

### Session Storage Architecture
- **D-19:** MCPSessionState stored directly in FastMCP's `session` dict (managed by `StreamableHTTPSessionManager`). FastMCP handles Mcp-Session-Id lifecycle, session creation, and expiry. Phase 2 code reads/writes `session["enabled_scopes"]: set[str]` and `session["enabled_searches"]: set[str]`. NOT in a separate module-level dict.

### Progressive Disclosure Mechanism
- **D-20:** Override FastMCP's `@mcp.list_tools()` with a custom handler that receives `ToolContext`. Access session via `ctx.request_context.request` — the MCP SDK request object (NOT Django `HttpRequest`, see PIT-16). Read `enabled_scopes` and `enabled_searches` from the session dict to filter which tools appear in the manifest. Core tools always included regardless of session state.

### Scope Hierarchy
- **D-21:** Scope hierarchy is hierarchical. Enabling a parent scope (e.g., `"dcim"`) automatically activates all child scopes (`"dcim.interface"`, `"dcim.device"`, etc.). `MCPToolRegistry.get_by_scope()` already implements this via `startswith(f"{scope}.")` matching. Same behavior for `mcp_disable_tools` — disabling parent disables all children.

### Auth Token Extraction
- **D-22:** Extract token from MCP request context: `ctx.request_context.request.headers.get("Authorization", "")` (PIT-16 — NOT Django `request`). Format: `Authorization: Token nbapikey_xxx`. Nautobot Token lookup: `nautobot.users.models.Token.objects.select_related("user").get(key=token_key)`.

### Anonymous Auth Logging
- **D-23:** No token (missing Authorization header) → `logger.warning("MCP: No auth token, falling back to anonymous user")`. Invalid/malformed token → `logger.debug("MCP: Invalid auth token attempted")`. Both return `AnonymousUser` with empty querysets.

### Auth Behavior
- **D-24:** `AnonymousUser` (missing or invalid token) returns empty querysets, never raises an error. All querysets call `.restrict(user, action="view")` — Nautobot's object-level permissions return empty queryset for unauthenticated users naturally.
- **D-25:** Token auth ONLY — no session cookie fallback for MCP requests. MCP clients always send tokens. Session cookie auth (Django web UI) is out of scope for v1.

### MCPSessionState Structure
- **D-26:** `MCPSessionState` is not a separate dataclass — Phase 2 stores `enabled_scopes: set[str]` and `enabled_searches: set[str]` directly in FastMCP's session dict. No `MCPSessionState` dataclass needed unless Phase 3 requires richer session metadata.

### Tool Registration
- **D-27 (REGI-05):** `@mcp.list_tools()` override registers with FastMCP using `ToolContext` parameter. `MCPToolRegistry.get_instance()` provides the tool list. Core tools always returned; non-core tools filtered by `enabled_scopes` and `enabled_searches`.

### Claude's Discretion
- Exact session expiry duration (FastMCP default is acceptable)
- Internal structure of `session["enabled_scopes"]` vs a dataclass wrapper
- How FastMCP session TTL is configured (use FastMCP defaults)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Auth & Session Architecture
- `.planning/research/PITFALLS.md` — PIT-10 (anonymous logging), PIT-13 (progressive disclosure), PIT-16 (auth from wrong request object)
- `.planning/codebase/ARCHITECTURE.md` §2 — Layer 2 Authentication and §8 Session State patterns
- `nautobot_app_mcp_server/mcp/server.py` — FastMCP instance (stateless_http=False already set)
- `nautobot_app_mcp_server/mcp/registry.py` — MCPToolRegistry, get_by_scope() with hierarchical scope matching

### Phase 1 Context
- `.planning/phases/01-mcp-server-infrastructure/01-CONTEXT.md` — All Phase 1 decisions carry forward (D-01 through D-18)

### Project Constraints
- `CLAUDE.md` — Pylint 10.00/10, Poetry-only, no pip
- `.planning/PROJECT.md` — No database models, read-only v1

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `MCPToolRegistry.get_instance().get_core_tools()` — returns core tools, no session filtering yet
- `MCPToolRegistry.get_instance().get_by_scope(scope)` — already handles hierarchical scope matching
- `MCPToolRegistry.get_instance().fuzzy_search(term)` — available for session search filtering
- FastMCP `StreamableHTTPSessionManager` — already configured (stateless_http=False in server.py)

### Established Patterns
- Thread-safe singleton with `threading.Lock` — Phase 1 established this
- Lazy factory pattern for FastMCP app — Phase 1 established
- No Django models — protocol adapter only

### Integration Points
- `nautobot_app_mcp_server/mcp/server.py` — add `@mcp.list_tools()` override here
- `nautobot_app_mcp_server/__init__.py` — `_on_post_migrate` is where core tools will be registered
- `nautobot_app_mcp_server/mcp/` — new files: `auth.py`, `session_tools.py`, tests

</code_context>

<specifics>
## Specific Ideas

- "No token vs invalid token have different log levels — this helps triage auth issues in production"
- "Session state lives where FastMCP already manages it — don't reinvent session tracking"

</specifics>

<deferred>
## Deferred Ideas

- Redis session backend for multi-worker deployments — v2 (per DESIGN.md out of scope)
- Tool-level field permissions — deferred
- Write tools (create/update/delete) — Phase 5+

</deferred>

---

*Phase: 02-authentication-sessions*
*Context gathered: 2026-04-01*
