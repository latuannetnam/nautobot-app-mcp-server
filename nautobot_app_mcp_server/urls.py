"""Django URL routing for the MCP server endpoint.

The MCP endpoint is mounted at /plugins/nautobot-app-mcp-server/mcp/
automatically via Nautobot's plugin URL discovery system.

Nautobot discovers this module via the PLUGINS setting and includes
plugin_patterns() in the root URLconf. This urls.py must export a
urlpatterns list at module level.
"""

from django.urls import path

from nautobot_app_mcp_server.mcp.view import mcp_view

urlpatterns = [
    path("mcp/", mcp_view, name="mcp"),
]
