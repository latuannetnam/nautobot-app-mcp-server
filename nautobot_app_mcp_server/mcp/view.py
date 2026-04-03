"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

from __future__ import annotations

from contextvars import ContextVar

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from starlette.types import Receive, Scope, Send

from nautobot_app_mcp_server.mcp.server import get_mcp_app

# Stores the Django HttpRequest for the duration of the async bridge call.
# Allows sync tool wrappers to access the request without coupling to MCP internals.
_django_request_ctx: ContextVar[HttpRequest] = ContextVar("django_request")


async def _bridge_django_to_asgi(django_request: HttpRequest) -> HttpResponse:
    """Bridge a Django HttpRequest into the FastMCP ASGI app.

    This is the WSGI→ASGI bridge. It:
    1. Stores the Django request in _django_request_ctx for tool access
    2. Builds an ASGI scope from the Django request (REFA-03)
    3. Defines receive() returning the actual request body
    4. Defines send() collecting http.response.start + http.response.body
    5. Calls the Starlette ASGI app (lifespan already running session_manager.run())

    The lifespan (started by _ensure_lifespan_started in server.py) keeps
    FastMCP's StreamableHTTPSessionManager.run() alive in a background thread,
    so sessions persist across Django requests without needing per-request run() calls.
    """
    _django_request_ctx.set(django_request)

    # REFA-03: Full ASGI scope from Django request
    plugin_prefix = "/plugins/nautobot-app-mcp-server"
    full_path = django_request.path
    if not full_path.startswith(plugin_prefix + "/mcp"):  # noqa: S101
        msg = f"Unexpected request.path: {full_path!r}; expected to start with {plugin_prefix!r}"
        raise ValueError(msg)
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
            # Decode ASGI byte headers to str for Django HttpResponse
            raw_headers = message.get("headers", [])
            response_started["headers"] = {
                k.decode("latin-1") if isinstance(k, bytes) else k: v.decode("latin-1") if isinstance(v, bytes) else v
                for k, v in raw_headers
            }
        elif message["type"] == "http.response.body":
            response_body.extend(message.get("body", b""))

    # Call the Starlette ASGI app directly.
    # The lifespan started by _ensure_lifespan_started() keeps session_manager.run()
    # alive in a background thread, so sessions are managed globally.
    asgi_app = get_mcp_app()
    await asgi_app(scope, receive, send)

    # Assemble Django HttpResponse from collected messages
    status = response_started.get("status", 500)
    headers = response_started.get("headers", {})

    django_response = HttpResponse(bytes(response_body), status=status)
    for key, value in headers.items():
        django_response[key] = value
    return django_response


@csrf_exempt
def mcp_view(request: HttpRequest) -> HttpResponse:
    """Django view: /plugins/nautobot-app-mcp-server/mcp/.

    Receives all HTTP methods (GET, POST, DELETE) and bridges them to FastMCP
    via the Starlette ASGI app. The lifespan is started once in a background
    thread and keeps FastMCP's session manager running for all requests.

    The bridge uses asgiref.sync.async_to_sync (NOT asyncio.run) so that
    FastMCP's event loop persists across requests and session state is preserved.

    Args:
        request: Django HttpRequest.

    Returns:
        Django HttpResponse with the MCP JSON-RPC response.
    """
    return async_to_sync(_bridge_django_to_asgi)(request)
