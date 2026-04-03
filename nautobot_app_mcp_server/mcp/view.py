"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

import asyncio

from django.http import HttpResponse

from nautobot_app_mcp_server.mcp.server import get_mcp_app


def mcp_view(request):
    """Bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse.

    FastMCP's http_app() is a native ASGI app: async(scope, receive, send).
    Since Django's runserver is synchronous, we create a fresh asyncio event loop
    with asyncio.run() to drive the async FastMCP app to completion.
    """
    mcp_app = get_mcp_app()  # Lazy: created on first request

    # Build ASGI scope from Django request.
    # FastMCP mounts its HTTP handler at /mcp (inside this Django view's /mcp/ path).
    # So we pass path='/mcp' (the FastMCP mount point) and root_path='/plugins/nautobot-app-mcp-server'
    # (the Django prefix that is stripped before routing to this view).
    plugin_prefix = "/plugins/nautobot-app-mcp-server"
    full_path = request.path
    assert full_path.startswith(plugin_prefix + "/mcp"), (
        f"Unexpected request.path: {full_path!r}; expected to start with {plugin_prefix!r}"
    )
    mcp_path = full_path[len(plugin_prefix):]  # e.g. '/mcp/' → '/mcp/'

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": request.method,
        "query_string": request.META.get("QUERY_STRING", "").encode("utf-8"),
        "root_path": plugin_prefix,
        "path": mcp_path,
        "headers": [
            (k.lower().encode("utf-8"), v.encode("utf-8"))
            for k, v in request.headers.items()
        ],
        "server": ("127.0.0.1", 8080),
    }

    # Collect ASGI messages from the FastMCP app
    messages: list[dict] = []
    status_code = [200]
    response_headers: dict[str, str] = {}

    async def receive():
        # FastMCP's streamable-http reads body asynchronously; send empty initially
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict):
        messages.append(message)
        if message["type"] == "http.response.start":
            status_code[0] = message.get("status", 200)
            response_headers = {k.decode(): v.decode() for k, v in message.get("headers", [])}

    # Drive the async FastMCP app to completion
    asyncio.run(mcp_app(scope, receive, send))

    if not messages:
        return HttpResponse("MCP endpoint ready", status=200)

    # FastMCP streams responses — assemble final body from all http.response.body messages
    body = b"".join(
        msg.get("body", b"") if isinstance(msg.get("body"), bytes) else (msg.get("body", "") or "").encode("utf-8")
        for msg in messages
        if msg["type"] == "http.response.body"
    )

    # Extract headers from the start message
    headers: dict[str, str] = {}
    for msg in messages:
        if msg["type"] == "http.response.start":
            headers = {k.decode(): v.decode() for k, v in msg.get("headers", [])}

    django_response = HttpResponse(body, status=status_code[0])
    for key, value in headers.items():
        django_response[key] = value
    return django_response
