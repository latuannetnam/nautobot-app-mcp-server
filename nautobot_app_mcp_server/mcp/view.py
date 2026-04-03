"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.http import HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from starlette.types import Receive, Scope, Send

from nautobot_app_mcp_server.mcp.server import get_session_manager

if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


# Stores the Django HttpRequest for the duration of the async bridge call.
# Allows sync tool wrappers to access the request without coupling to MCP internals.
_django_request_ctx: ContextVar[HttpRequest] = ContextVar("django_request")


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

    # REFA-02: Enter session_manager.run() — this sets Server.request_context
    # so that Server.request_context.get() works inside tool handlers.
    # REFA-01: async_to_sync is the outer wrapper (see mcp_view below).
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

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
