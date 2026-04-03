---
wave: 1
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/server.py
  - nautobot_app_mcp_server/mcp/auth.py
  - nautobot_app_mcp_server/mcp/session_tools.py
autonomous: false
---

# Phase 5 — Wave 1 Plan: Foundation

**Wave:** 1 (of 2)
**Phase:** 05-mcp-server-refactor
**Requirements:** REFA-04, REFA-05, AUTH-01, AUTH-02
**Execution mode:** Autonomous-capable (3 files, no inter-file dependencies)

---

## Wave Goal

Create the thread-safe singleton infrastructure (`server.py`) and auth caching layer (`auth.py`) that Wave 2's bridge refactor depends on. Also fix the `MCPSessionState` session dict latent bug (`session_tools.py`).

---

## Task WAVE1-SERVER: Thread-safe singletons + get_session_manager()

**File:** `nautobot_app_mcp_server/mcp/server.py`
**Requirements:** REFA-04, REFA-05
**Read first:** `nautobot_app_mcp_server/mcp/server.py` (current state)

### Current State

```python
# server.py:24-26
_mcp_app: Starlette | None = None   # No lock, no session manager

# server.py:109-131 — get_mcp_app() has unguarded lazy init
def get_mcp_app() -> Starlette:
    global _mcp_app  # pylint: disable=global-statement
    if _mcp_app is None:
        mcp_instance = _setup_mcp_app()
        _mcp_app = mcp_instance.http_app(...)
    return _mcp_app
```

### Changes Required

**Add imports:**
```python
import threading
from typing import TYPE_CHECKING
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
```

**Add module-level globals:**
```python
_mcp_app: Starlette | None = None
_mcp_session_manager: StreamableHTTPSessionManager | None = None
_app_lock = threading.Lock()
_session_lock = threading.Lock()
```

**Modify `get_mcp_app()` with double-checked locking:**
```python
def get_mcp_app() -> Starlette:
    global _mcp_app
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:  # double-check
                mcp_instance = _setup_mcp_app()
                _mcp_app = mcp_instance.http_app(
                    path="/mcp",
                    transport="streamable-http",
                    stateless_http=False,
                    json_response=True,
                )
    return _mcp_app
```

**Add `get_session_manager()`:**
```python
def get_session_manager() -> StreamableHTTPSessionManager:
    """Return the StreamableHTTPSessionManager singleton.

    Lazily created alongside _mcp_app on first call. Both share the same
    FastMCP server instance (_mcp_app.http_app() uses the same mcp._mcp_server
    underneath). The session manager is the bridge entry point for
    view.py: it is passed to _call_starlette_handler() inside async_to_sync.

    Raises:
        RuntimeError: If called before Django is fully initialized (outside
            a request context). Use lazy factory so ORM is ready.
    """
    global _mcp_session_manager
    if _mcp_session_manager is None:
        with _session_lock:
            if _mcp_session_manager is None:
                _mcp_session_manager = StreamableHTTPSessionManager(
                    app=_setup_mcp_app()._mcp_server,
                    json_response=True,
                    stateless=False,
                )
    return _mcp_session_manager
```

**IMPORTANT — duplicate FastMCP instance:** Creating a second `FastMCP()` in `get_session_manager()` would be a separate server. Instead, call `get_mcp_app()` first which ensures `_mcp_app` is set, then access `getattr(_mcp_app, "state", None)` to find the session manager from the FastMCP app. BUT from research: FastMCP's `http_app()` creates its own internal session manager and doesn't expose it on `app.state`.

**SIMPLER APPROACH (use FastMCP's internal session manager):** The Starlette app from `http_app()` has `app.state.fastmcp_server` set (from fastmcp/server/http.py:258). The session manager is accessible via:
```python
# After _mcp_app is set:
app = get_mcp_app()
# app.state.fastmcp_server is the FastMCP server instance
# The StreamableHTTPSessionManager used by http_app() is created internally
# We need to create our OWN session manager that shares the FastMCP server
```

**CORRECT IMPLEMENTATION:** Use `_setup_mcp_app()` once and share the same `mcp_instance` between both `get_mcp_app()` and `get_session_manager()`:
```python
_mcp_instance: FastMCP | None = None  # Shared between app and manager

def get_mcp_app() -> Starlette:
    global _mcp_app, _mcp_instance
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_app = _mcp_instance.http_app(...)
    return _mcp_app

def get_session_manager() -> StreamableHTTPSessionManager:
    global _mcp_session_manager, _mcp_instance
    if _mcp_session_manager is None:
        with _session_lock:
            if _mcp_session_manager is None:
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_session_manager = StreamableHTTPSessionManager(
                    app=_mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
    return _mcp_session_manager
```

Both functions call `_setup_mcp_app()` lazily but the `_mcp_instance` is shared so only one FastMCP instance is ever created.

### Acceptance Criteria

1. `grep -n "threading.Lock" server.py` returns at least two lines (one per lock)
2. `grep -n "get_session_manager" server.py` returns the function definition
3. `grep -n "double-check\|None.*if.*None" server.py` shows double-checked locking pattern
4. `grep -n "_app_lock\|_session_lock" server.py` shows both lock variables
5. `grep -n "_mcp_instance" server.py` shows the shared FastMCP instance variable
6. `poetry run invoke pylint` scores 10.00/10 on server.py
7. Existing tests in `test_view.py::MCPAppFactoryTestCase` still pass (singleton returns same instance)
