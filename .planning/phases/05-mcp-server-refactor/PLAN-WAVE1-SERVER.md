---
wave: 1
depends_on: []
files_modified:
  - nautobot_app_mcp_server/mcp/server.py
autonomous: false
---

# Phase 5 — Wave 1 Task: WAVE1-SERVER

**Task ID:** WAVE1-SERVER
**File:** `nautobot_app_mcp_server/mcp/server.py`
**Requirements:** REFA-04, REFA-05
**Priority:** P0

---

## read_first

- `nautobot_app_mcp_server/mcp/server.py` — current broken state; must see existing `_mcp_app`, `_setup_mcp_app()`, `get_mcp_app()` before making changes
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — D-05 through D-08 (session manager architecture decisions)

---

## action

### 1. Add imports at top of server.py (after existing imports)

```python
import threading

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
```

### 2. Add module-level globals (before `_setup_mcp_app()`)

```python
# Shared FastMCP instance — ensures only one server is ever created
_mcp_instance: FastMCP | None = None

# Lazy ASGI app (Starlette) + session manager singletons
_mcp_app: Starlette | None = None
_mcp_session_manager: StreamableHTTPSessionManager | None = None

# Double-checked locking locks
_app_lock = threading.Lock()
_session_lock = threading.Lock()
```

### 3. Modify `_setup_mcp_app()` to return the FastMCP instance (it already does)

No changes needed — it already returns `mcp` (the FastMCP instance).

### 4. Replace `get_mcp_app()` with thread-safe version

Replace server.py:109–131 with:

```python
def get_mcp_app() -> Starlette:
    """Lazily build the FastMCP ASGI app on first HTTP request.

    This MUST be called from within a Django request context (e.g., from
    mcp_view). Calling it at module import time causes Django ORM errors
    because no request thread context exists yet.

    Thread-safe: uses double-checked locking with threading.Lock to prevent
    duplicate FastMCP instances under concurrent Django workers.

    Returns:
        The FastMCP Starlette ASGI application, mounted at the /mcp/ path.

    Raises:
        RuntimeError: If called outside of a Django request context.
    """
    global _mcp_app, _mcp_instance  # pylint: disable=global-statement
    if _mcp_app is None:
        with _app_lock:
            if _mcp_app is None:  # double-checked locking
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_app = _mcp_instance.http_app(
                    path="/mcp",
                    transport="streamable-http",
                    stateless_http=False,
                    json_response=True,
                )
    return _mcp_app


def get_session_manager() -> StreamableHTTPSessionManager:
    """Return the StreamableHTTPSessionManager singleton.

    Lazily created alongside the FastMCP instance on first call.
    Both share the same _mcp_instance so only one FastMCP server is created.

    The session manager is the entry point for view.py's ASGI bridge:
    it must be passed to _call_starlette_handler() inside async_to_sync
    so that session_manager.run() can be entered (which sets
    Server.request_context and allows tool handlers to access session state).

    Returns:
        The StreamableHTTPSessionManager instance for this process.

    Raises:
        RuntimeError: If called before Django is fully initialized.
    """
    global _mcp_session_manager, _mcp_instance  # pylint: disable=global-statement
    if _mcp_session_manager is None:
        with _session_lock:
            if _mcp_session_manager is None:  # double-checked locking
                if _mcp_instance is None:
                    _mcp_instance = _setup_mcp_app()
                _mcp_session_manager = StreamableHTTPSessionManager(
                    app=_mcp_instance._mcp_server,
                    json_response=True,
                    stateless=False,
                )
    return _mcp_session_manager
```

### 5. Update TYPE_CHECKING block (add `FastMCP` to TYPE_CHECKING imports)

```python
if TYPE_CHECKING:
    from starlette.applications import Starlette
    from nautobot_app_mcp_server.mcp.server import FastMCP  # line already exists via _setup_mcp_app return
```

---

## acceptance_criteria

1. `grep -n "threading" nautobot_app_mcp_server/mcp/server.py` — shows `import threading`
2. `grep -n "StreamableHTTPSessionManager" nautobot_app_mcp_server/mcp/server.py` — shows import AND usage in `get_session_manager()`
3. `grep -n "_app_lock\|_session_lock" nautobot_app_mcp_server/mcp/server.py` — shows both lock variable definitions
4. `grep -n "def get_session_manager" nautobot_app_mcp_server/mcp/server.py` — shows the function definition
5. `grep -n "_mcp_instance" nautobot_app_mcp_server/mcp/server.py` — shows the shared FastMCP instance variable (used in both functions)
6. `grep -n "if _mcp_app is None:" nautobot_app_mcp_server/mcp/server.py` — shows outer check is outside the lock, inner check is inside the lock (double-checked locking pattern)
7. `grep -n "with _app_lock:" nautobot_app_mcp_server/mcp/server.py` — shows lock acquisition around `_mcp_app` creation
8. `grep -n "with _session_lock:" nautobot_app_mcp_server/mcp/server.py` — shows lock acquisition around `_mcp_session_manager` creation
9. `poetry run pylint nautobot_app_mcp_server/mcp/server.py` — scores 10.00/10
10. Existing `test_view.py::MCPAppFactoryTestCase::test_get_mcp_app_twice_returns_same_instance` still passes (patches `FastMCP.http_app`, so `_mcp_app` is set from first call; `_mcp_session_manager` uses same `_mcp_instance`)

---

## notes

- `_setup_mcp_app()` already returns the FastMCP instance — no change needed to that function
- The `TYPE_CHECKING` block at the top already imports `Starlette` from `starlette.applications`
- FastMCP is imported directly (not TYPE_CHECKING) since `_setup_mcp_app()` uses it at runtime
- The `_mcp_instance` shared variable ensures both `get_mcp_app()` and `get_session_manager()` create only one FastMCP server even if called concurrently
- `_mcp_session_manager` is created separately (with its own lock) but shares the same `_mcp_instance._mcp_server`