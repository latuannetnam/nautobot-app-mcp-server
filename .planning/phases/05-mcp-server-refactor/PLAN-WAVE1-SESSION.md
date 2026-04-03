---
wave: 1
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/session_tools.py
autonomous: false
---

# Phase 5 — Wave 1 Task: WAVE1-SESSION

**Task ID:** WAVE1-SESSION
**File:** `nautobot_app_mcp_server/mcp/session_tools.py`
**Requirements:** (Latent bug fix — required for REFA-02 to work)
**Priority:** P0 (latent bug — only surfaces once REFA-01/REFA-02 are fixed)

---

## read_first

- `nautobot_app_mcp_server/mcp/session_tools.py` — current state; see `MCPSessionState.from_session()`, `apply_to_session()`, `_list_tools_handler`, `_mcp_enable_tools_impl`, `_mcp_disable_tools_impl`
- `.planning/phases/05-mcp-server-refactor/05-RESEARCH.md` §3 (Server.request_context ContextVar — MCPSessionState latent bug)
- `mcp/server/lowlevel/servertypes.py` (in installed `.venv/`) — verify `ServerSession` has no dict-like interface

---

## context

**The latent bug:** `MCPSessionState.from_session(session)` calls `session.get("enabled_scopes", set())`. But `session` is a `ServerSession` instance (set by `MCPServer._handle_request()` at line 750 of `mcp/server/lowlevel/server.py`). `ServerSession` has no `get()`, `__getitem__()`, or `__setitem__()` methods — verified by reading the full class in `mcp/server/session.py`.

Currently this "works" only because `asyncio.run()` causes `Server.request_context.get()` to raise `LookupError` in `_list_tools_mcp` before `MCPSessionState.from_session(session)` is ever called. Once REFA-01/REFA-02 fix the `asyncio.run()` issue, `Server.request_context.get()` succeeds and then `session.get()` would raise `AttributeError`.

**The fix:** Store session state as a dict on the `request_context` dataclass object itself. `request_context` is a plain Python dataclass that always supports attribute access, even if the embedded `session` is not dict-like.

---

## action

### 1. Add helper functions for request_context-based state storage

Add these at the module level of `session_tools.py` (after the imports, before `MCPSessionState`):

```python
# -------------------------------------------------------------------
# Request-context-based state storage (replaces session dict pattern)
# -------------------------------------------------------------------
# FastMCP's ServerSession has no dict-like interface (no get/setitem).
# State is stored as a dict attribute on the RequestContext dataclass.
# These helpers safely get/set the state, falling back to empty on first access.


def _get_tool_state(ctx: ToolContext) -> dict:
    """Get the MCP tool state dict from request_context, creating if needed.

    The state dict is stored as _mcp_tool_state on the RequestContext object.
    This avoids depending on ServerSession having dict-like methods.
    """
    req_ctx = ctx.request_context
    state = getattr(req_ctx, "_mcp_tool_state", None)
    if state is None:
        state = {"enabled_scopes": set(), "enabled_searches": set()}
        req_ctx._mcp_tool_state = state  # Monkey-patch dataclass
    return state


def _make_session_wrapper(state: dict) -> dict:
    """Build a dict-like wrapper that reads/writes the state dict.

    Returns a plain dict that _list_tools_handler, _mcp_enable_tools_impl,
    etc. can use with the existing MCPSessionState.from_session() and
    apply_to_session() methods without modification.
    """
    return state
```

### 2. Update `MCPSessionState.from_session()` to accept a dict

The signature stays `from_session(session: dict)`. No change needed — it already reads `session.get("enabled_scopes", set())` and `session.get("enabled_searches", set())`. The caller just needs to pass a dict.

### 3. Update `_list_tools_handler` to use `_get_tool_state()`

Find `session = ctx.request_context.session` (line 111). Replace the two lines:

```python
# OLD (line 111-112):
session = ctx.request_context.session
state = MCPSessionState.from_session(session)

# NEW:
tool_state = _get_tool_state(ctx)
state = MCPSessionState.from_session(tool_state)
```

### 4. Update `_mcp_enable_tools_impl` to use `_get_tool_state()`

Find `session = ctx.request_context.session` (line 180–181). Replace:

```python
# OLD (line 180-181):
session = ctx.request_context.session
state = MCPSessionState.from_session(session)

# NEW:
tool_state = _get_tool_state(ctx)
state = MCPSessionState.from_session(tool_state)
```

And replace the `state.apply_to_session(session)` call:

```python
# OLD (line 192):
state.apply_to_session(session)

# NEW:
# State is already stored in tool_state by reference; no need to re-apply.
# Just update tool_state in-place:
tool_state["enabled_scopes"] = state.enabled_scopes
tool_state["enabled_searches"] = state.enabled_searches
```

### 5. Update `_mcp_disable_tools_impl` to use `_get_tool_state()`

Find `session = ctx.request_context.session` (line 241–242). Replace:

```python
# OLD (line 241-242):
session = ctx.request_context.session
state = MCPSessionState.from_session(session)

# NEW:
tool_state = _get_tool_state(ctx)
state = MCPSessionState.from_session(tool_state)
```

And replace the `state.apply_to_session(session)` calls:

```python
# OLD (line 247, 253):
state.apply_to_session(session)

# NEW (both occurrences):
# State already stored in tool_state by reference
tool_state["enabled_scopes"] = state.enabled_scopes
tool_state["enabled_searches"] = state.enabled_searches
```

### 6. Update `_mcp_list_tools_impl` to use `_get_tool_state()`

Find `session = ctx.request_context.session` (line 293–294). Replace:

```python
# OLD (line 293-294):
session = ctx.request_context.session
state = MCPSessionState.from_session(session)

# NEW:
tool_state = _get_tool_state(ctx)
state = MCPSessionState.from_session(tool_state)
```

### 7. Update module docstring

Update the header docstring of `session_tools.py` to reflect the new state storage:

```python
"""Session management tools and progressive disclosure handler.

Exports 4 symbols for server.py registration:
    mcp_enable_tools  — factory: register as FastMCP tool + MCPToolRegistry
    mcp_disable_tools  — factory: register as FastMCP tool + MCPToolRegistry
    mcp_list_tools    — factory: register as FastMCP tool + MCPToolRegistry
    _list_tools_handler — coroutine: progressive disclosure logic

Session state lives in FastMCP's RequestContext dataclass (D-24):
    ctx.request_context._mcp_tool_state["enabled_scopes"]  — set[str]
    ctx.request_context._mcp_tool_state["enabled_searches"] — set[str]

This replaces the old session["enabled_scopes"] pattern, which relied on
ServerSession being dict-like (it is not — this was a latent bug).

Scope hierarchy (D-21): enabling "dcim" activates "dcim.interface",
"dcim.device", etc. via MCPToolRegistry.get_by_scope() startswith matching.

Core tools are ALWAYS returned by _list_tools_handler() regardless of
session state (D-27, SESS-06, REGI-05).

Registration strategy: Tool implementations are defined at module level so
they can be registered in MCPToolRegistry unconditionally. The FastMCP
factory functions (passed to _setup_mcp_app()) apply the @mcp.tool()
decorator. This ensures tools appear in the registry even without a live
FastMCP server (tests, migrations).
"""
```

---

## acceptance_criteria

1. `grep -n "_mcp_tool_state\|_get_tool_state\|_make_session_wrapper" nautobot_app_mcp_server/mcp/session_tools.py` — shows all helper function definitions
2. `grep -n "ctx.request_context.session" nautobot_app_mcp_server/mcp/session_tools.py` — returns 0 matches (old pattern removed)
3. `grep -n "tool_state = _get_tool_state" nautobot_app_mcp_server/mcp/session_tools.py` — shows 4 replacements (one per tool function)
4. `grep -n "_mcp_tool_state = state" nautobot_app_mcp_server/mcp/session_tools.py` — shows state saved back to request_context
5. `grep -n "Session state lives in" nautobot_app_mcp_server/mcp/session_tools.py` — shows updated module docstring
6. `poetry run pylint nautobot_app_mcp_server/mcp/session_tools.py` — scores 10.00/10
7. `poetry run invoke ruff` passes with no errors on session_tools.py

---

## notes

- The `MCPSessionState` dataclass itself does NOT change — it still has `from_session(dict)` and `apply_to_session(dict)` methods
- The `_make_session_wrapper` function is defined but not currently used — it documents the interface. If future code needs a dict-like wrapper, call `_make_session_wrapper(_get_tool_state(ctx))` to get a plain dict
- The unit tests in `test_session_tools.py` pass a plain `dict` to `MCPSessionState.from_session()` — no test changes needed since the mock already provides a plain dict
- `tool_state` is passed by reference to `MCPSessionState.from_session()` — when `state.enabled_scopes` and `state.enabled_searches` are modified, the changes are visible in `tool_state` immediately. The explicit `tool_state["enabled_scopes"] = state.enabled_scopes` writes are belt-and-suspenders safety for when `state` is a copy rather than the same object