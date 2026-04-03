---
wave: 2
depends_on:
  - .planning/phases/05-mcp-server-refactor/PLAN-WAVE1.md
files_modified:
  - nautobot_app_mcp_server/mcp/view.py
autonomous: false
---

# Phase 5 — Wave 2 Plan: Bridge Refactor

**Wave:** 2 (of 2)
**Phase:** 05-mcp-server-refactor
**Requirements:** REFA-01, REFA-02, REFA-03
**Blockers:** Wave 1 complete (provides `get_session_manager()`)

---

## Wave Goal

Replace the broken `asyncio.run()` WSGI→ASGI bridge in `view.py` with the django-mcp-server pattern: `async_to_sync(_call_starlette_handler)(request, session_manager)`. The `_call_starlette_handler` function builds the full ASGI scope from the Django request, enters `session_manager.run()` (which sets `Server.request_context`), calls `handle_request()`, and assembles the `HttpResponse`.

This is the P0 fix that restores session persistence and makes `Server.request_context.get()` work inside tool handlers.

---

## Task WAVE2-VIEW: Replace asyncio.run() bridge

**File:** `nautobot_app_mcp_server/mcp/view.py`
**Requirements:** REFA-01, REFA-02, REFA-03
**Read first:**
- `nautobot_app_mcp_server/mcp/view.py` (current state — lines 1–83)
- `nautobot_app_mcp_server/mcp/server.py` (updated by WAVE1-SERVER — see `get_session_manager()`)
- `.planning/research/ARCHITECTURE.md` §Pattern 1 (exact `_call_starlette_handler` implementation)
- `.planning/research/STACK.md` §How to Build the ASGI Scope (django-mcp-server ASGI scope pattern)

### Current State (broken)

```python
# view.py:1-83 — entire file
"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

import asyncio

from django.http import HttpResponse

from nautobot_app_mcp_server.mcp.server import get_mcp_app


def mcp_view(request):
    mcp_app = get_mcp_app()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": request.method,
        "query_string": request.META.get("QUERY_STRING", "").encode("utf-8"),
        "root_path": plugin_prefix,
        "path": mcp_path,
        "headers": [...],
        "server": ("127.0.0.1", 8080),  # HARDCODED
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}  # EMPTY BODY

    async def send(message: dict):
        ...

    asyncio.run(mcp_app(scope, receive, send))  # DESTROYS SESSION STATE
    ...
```

### Changes Required

**Step 1. Replace all imports**

Remove `asyncio` import. Add `asgiref.sync.async_to_sync`, `contextvars`, `starlette.datastructures.Headers`, `starlette.types` (`Scope`, `Receive`, `Send`). Import `get_session_manager` (NOT `get_mcp_app`):

```python
from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse
from starlette.datastructures import Headers
from starlette.types import Receive, Scope, Send

from nautobot_app_mcp_server.mcp.server import get_session_manager

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
```

**Step 2. Add module-level context var for Django request passthrough**

```python
# Stores the Django HttpRequest for the duration of the async bridge call.
# Allows sync tool wrappers to access the request without coupling to MCP internals.
_django_request_ctx: ContextVar[HttpRequest] = ContextVar("django_request")
```

**Step 3. Define `_call_starlette_handler` async function**

```python
async def _call_starlette_handler(
    django_request: HttpRequest,
    session_manager: StreamableHTTPSessionManager,
) -> HttpResponse:
    """Bridge a Django HttpRequest into FastMCP via StreamableHTTPSessionManager.

    This is the WSGI→ASGI bridge. It:
    1. Stores the Django request in _django_request_ctx for tool access
    2. Builds an ASGI scope from the Django request (REFA-03)
    3. Defines receive() returning the actual request body
    4. Defines send() collecting http.response.start + http.response.body
    5. Enters session_manager.run() — sets Server.request_context (REFA-02)
    6. Calls handle_request() — FastMCP protocol runs (REFA-01)
    7. Assembles and returns the Django HttpResponse
    """
    _django_request_ctx.set(django_request)

    # REFA-03: Full ASGI scope from Django request
    plugin_prefix = "/plugins/nautobot-app-mcp-server"
    full_path = django_request.path
    assert full_path.startswith(plugin_prefix + "/mcp"), (
        f"Unexpected request.path: {full_path!r}; "
        f"expected to start with {plugin_prefix!r}"
    )
    mcp_path = full_path[len(plugin_prefix):]  # e.g. '/mcp/' → '/mcp/'

    # Build headers list: lowercased keys, latin-1 encoded
    headers_list: list[tuple[bytes, bytes]] = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in django_request.headers.items()
        if k.lower() != "content-length"
    ]

    # Add Content-Length from actual body size
    body = django_request.body
    content_length = str(len(body)).encode("latin-1")
    headers_list.append((b"content-length", content_length))

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": django_request.method,
        "query_string": django_request.META.get("QUERY_STRING", "").encode("latin-1"),
        "path": mcp_path,
        "root_path": plugin_prefix,
        "headers": headers_list,
        # REFA-03: server derived from request, not hardcoded
        "server": (django_request.get_host(), django_request.get_port()),
        # REFA-03: scheme from request.is_secure()
        "scheme": "https" if django_request.is_secure() else "http",
        # REFA-03: client from META
        "client": (django_request.META.get("REMOTE_ADDR", ""), 0),
    }

    # receive() returns the actual request body, not empty
    async def receive() -> Receive:
        return {"type": "http.request", "body": body, "more_body": False}

    # send() collects start and body messages into mutable containers
    response_started: dict = {}
    response_body = bytearray()

    async def send(message: Send) -> None:
        if message["type"] == "http.response.start":
            response_started["status"] = message.get("status", 200)
            response_started["headers"] = Headers(raw=message.get("headers", []))
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    # REFA-02: Enter session_manager.run() — this sets Server.request_context
    # so that Server.request_context.get() works inside tool handlers.
    # REFA-01: async_to_sync is the outer wrapper (see mcp_view below).
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

    # Assemble Django HttpResponse from collected messages
    status = response_started.get("status", 500)
    headers = response_started.get("headers", Headers(raw=[]))

    django_response = HttpResponse(bytes(response_body), status=status)
    for key, value in headers.multi_items():
        django_response[key] = value
    return django_response
```

**Step 4. Replace `mcp_view()` function body**

```python
def mcp_view(request: HttpRequest) -> HttpResponse:
    """Django view: /plugins/nautobot-app-mcp-server/mcp/

    Receives all HTTP methods (GET, POST, DELETE) and bridges them to FastMCP
    via StreamableHTTPSessionManager.

    The bridge uses asgiref.sync.async_to_sync (NOT asyncio.run) so that
    FastMCP's event loop persists across requests and session state is preserved.

    Args:
        request: Django HttpRequest.

    Returns:
        Django HttpResponse with the MCP JSON-RPC response.
    """
    session_manager = get_session_manager()
    return async_to_sync(_call_starlette_handler)(request, session_manager)
```

### Acceptance Criteria

1. `grep -n "asyncio.run" nautobot_app_mcp_server/mcp/view.py` — returns 0 matches (old pattern removed)
2. `grep -n "async_to_sync" nautobot_app_mcp_server/mcp/view.py` — shows import AND usage in `mcp_view`
3. `grep -n "session_manager.run()" nautobot_app_mcp_server/mcp/view.py` — shows `async with session_manager.run():` inside `_call_starlette_handler`
4. `grep -n "handle_request" nautobot_app_mcp_server/mcp/view.py` — shows `await session_manager.handle_request(scope, receive, send)`
5. `grep -n "get_session_manager" nautobot_app_mcp_server/mcp/view.py` — shows import and call in `mcp_view`
6. `grep -n "django_request.get_host\|get_port\|is_secure\|REMOTE_ADDR" nautobot_app_mcp_server/mcp/view.py` — shows dynamic server/client/scheme from request
7. `grep -n '"server":.*request' nautobot_app_mcp_server/mcp/view.py` — shows `server` key not hardcoded
8. `grep -n "127.0.0.1.*8080\|8080.*127.0.0.1" nautobot_app_mcp_server/mcp/view.py` — returns 0 matches (hardcoded address removed)
9. `grep -n "async def _call_starlette_handler" nautobot_app_mcp_server/mcp/view.py` — shows the async bridge function definition
10. `grep -n "Content-Length\|content.length" nautobot_app_mcp_server/mcp/view.py` — shows Content-Length in ASGI scope
11. `poetry run pylint nautobot_app_mcp_server/mcp/view.py` — scores 10.00/10
12. `poetry run invoke ruff` passes with no errors on view.py
