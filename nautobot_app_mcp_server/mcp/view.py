"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

from asgiref.wsgi import WsgiToAsgi

from nautobot_app_mcp_server.mcp.server import get_mcp_app


def mcp_view(request):
    """Bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse.

    The WsgiToAsgi wrapper converts Django's WSGI interface to ASGI,
    then calls the FastMCP ASGI app which handles the MCP protocol.
    """
    app = get_mcp_app()  # Lazy: created on first request
    handler = WsgiToAsgi(app)
    return handler(request)
