---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified:
  - nautobot_app_mcp_server/mcp/tests/test_view.py
autonomous: false
---

# Phase 5 — Wave 2 Task: WAVE2-TEST-VIEW

**Task ID:** WAVE2-TEST-VIEW
**File:** `nautobot_app_mcp_server/mcp/tests/test_view.py`
**Requirements:** TEST-01 (update existing tests that assert old behavior)
**Blockers:** Wave 1 complete (WAVE2-VIEW must also be complete before running tests)

---

## read_first

- `nautobot_app_mcp_server/mcp/tests/test_view.py` (current state — lines 1–118)
- `nautobot_app_mcp_server/mcp/view.py` (updated by WAVE2-VIEW — new async_to_sync pattern)
- `nautobot_app_mcp_server/mcp/server.py` (updated by WAVE1-SERVER — `get_session_manager()` exists)

---

## context

Two tests in `test_view.py` need to change:

1. **`test_wsgi_to_asgi_is_used_in_view`** — asserts `WsgiToAsgi` is used (old pattern) and `async_to_sync` is NOT used. After the refactor, the opposite is true: `async_to_sync` is used, `WsgiToAsgi` is not.

2. **`test_view_calls_get_mcp_app`** — mocks `get_mcp_app` but the new `mcp_view` calls `get_session_manager` instead. Need to mock `get_session_manager` instead.

3. **`test_mcp_endpoint_resolves`** — no change needed (URL routing is unchanged).

4. **`test_mcp_view_imports_successfully`** — no change needed (import still works).

5. **New tests to add:**
   - Test that `get_session_manager()` returns the same singleton across calls
   - Test that `mcp_view` calls `get_session_manager()` (not `get_mcp_app()`)

---

## action

### 1. Update `test_wsgi_to_asgi_is_used_in_view`

Replace the test body with the new assertion (view now uses `async_to_sync`, not `WsgiToAsgi`):

```python
def test_async_to_sync_is_used_in_view(self):
    """REFA-01: Verify the view uses async_to_sync (not asyncio.run or WsgiToAsgi)."""
    import inspect

    from nautobot_app_mcp_server.mcp import view as view_module

    source = inspect.getsource(view_module)
    self.assertIn("async_to_sync", source)
    self.assertNotIn("asyncio.run", source)  # asyncio.run is the broken pattern
    self.assertNotIn("WsgiToAsgi", source)   # old pattern replaced
    self.assertIn("session_manager.run()", source)  # REFA-02
```

### 2. Update `test_view_calls_get_mcp_app`

Replace the test with one that verifies `get_session_manager` is called (not `get_mcp_app`):

```python
@override_settings(
    PLUGINS=["nautobot_app_mcp_server"],
    ROOT_URLCONF="nautobot_app_mcp_server.urls",
)
@patch("nautobot_app_mcp_server.mcp.view.get_session_manager")
def test_view_calls_get_session_manager(self, mock_get_mgr):
    """REFA-04: mcp_view calls get_session_manager() (not get_mcp_app())."""
    from nautobot_app_mcp_server.mcp.view import mcp_view

    mock_manager = MagicMock()
    mock_get_mgr.return_value = mock_manager

    mock_request = MagicMock()
    mock_request.method = "GET"
    mock_request.path = "/plugins/nautobot-app-mcp-server/mcp/"
    mock_request.META = {"QUERY_STRING": ""}
    mock_request.body = b""

    # Mock the async bridge — return a mock response
    with patch(
        "nautobot_app_mcp_server.mcp.view.async_to_sync",
        return_value=MagicMock(status=200, content=b"{}"),
    ):
        mcp_view(mock_request)

    mock_get_mgr.assert_called_once()
```

### 3. Add new test `test_get_session_manager_returns_singleton`

```python
def test_get_session_manager_returns_singleton(self):
    """REFA-04: get_session_manager() returns the same instance across calls."""
    from unittest.mock import patch

    # Patch FastMCP and http_app to avoid real initialization
    with patch(
        "nautobot_app_mcp_server.mcp.server._setup_mcp_app",
        return_value=MagicMock(_mcp_server=MagicMock()),
    ):
        from nautobot_app_mcp_server.mcp.server import get_session_manager

        mgr1 = get_session_manager()
        mgr2 = get_session_manager()
        self.assertIs(mgr1, mgr2)
```

### 4. Add test `test_session_manager_type`

```python
def test_session_manager_type(self):
    """REFA-04: get_session_manager() returns a StreamableHTTPSessionManager instance."""
    from unittest.mock import patch

    with patch(
        "nautobot_app_mcp_server.mcp.server._setup_mcp_app",
        return_value=MagicMock(_mcp_server=MagicMock()),
    ):
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from nautobot_app_mcp_server.mcp.server import get_session_manager

        mgr = get_session_manager()
        self.assertIsInstance(mgr, StreamableHTTPSessionManager)
```

---

## acceptance_criteria

1. `grep -n "async_to_sync" nautobot_app_mcp_server/mcp/tests/test_view.py` — shows the new test assertion
2. `grep -n "get_session_manager" nautobot_app_mcp_server/mcp/tests/test_view.py` — shows mock patch and call assertion
3. `grep -n "test_wsgi_to_asgi_is_used_in_view" nautobot_app_mcp_server/mcp/tests/test_view.py` — no longer exists (renamed to `test_async_to_sync_is_used_in_view`)
4. `grep -n "test_get_session_manager_returns_singleton" nautobot_app_mcp_server/mcp/tests/test_view.py` — shows the new singleton test
5. `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_view.py` — scores 10.00/10
6. `poetry run invoke ruff` passes on test_view.py
7. `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_view` — passes