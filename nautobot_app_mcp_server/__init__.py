"""App declaration for nautobot_app_mcp_server."""

from importlib import metadata

try:
    __version__ = metadata.version(__name__)
except metadata.PackageNotFoundError:
    # Fallback for development (editable install via PYTHONPATH/volume mount)
    __version__ = "0.1.0a0"

from nautobot.apps import NautobotAppConfig


class NautobotAppMcpServerConfig(NautobotAppConfig):
    """App configuration for the nautobot_app_mcp_server app."""

    name = "nautobot_app_mcp_server"
    verbose_name = "Nautobot App MCP Server"
    version = __version__
    author = "Le Anh Tuan"
    description = "Nautobot MCP Server App."
    base_url = "nautobot-app-mcp-server"
    required_settings = []
    default_settings = {}
    docs_view_name = "plugins:nautobot_app_mcp_server:docs"
    searchable_models = []
    urls = []

    def ready(self) -> None:
        """Initialize the MCP server app.

        1. Call super().ready() FIRST so Nautobot registers our urls.py via
           NautobotAppConfig.ready() → plugin_patterns.append(...).
        2. Import mcp.tools to trigger side-effect registration of all core tools
           in MCPToolRegistry.
        3. Write tool_registry.json to the package directory for cross-process
           discovery by the standalone MCP server.

        Note:
            Does NOT use post_migrate. post_migrate never fires in the MCP server
            process (Phase 8 runs django.setup() directly, not nautobot-server).
            The MCP server reads tool_registry.json at startup instead.
        """
        super().ready()  # Registers URL patterns (MUST be first)

        import json  # noqa: F401
        import os  # noqa: F401

        import nautobot_app_mcp_server.mcp.tools  # noqa: F401

        from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry.get_instance()

        # Build payload for tool_registry.json
        # Excludes 'func' (not JSON-serializable); input_schema included for
        # client-side visibility without calling the server.
        tools = registry.get_all()
        payload = [
            {
                "name": tool.name,
                "description": tool.description,
                "tier": tool.tier,
                "app_label": tool.app_label,
                "scope": tool.scope,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]

        # Write to package directory via __file__ (resolves correctly for both
        # installed packages and editable dev installations).
        package_dir = os.path.dirname(__file__)
        json_path = os.path.join(package_dir, "tool_registry.json")

        with open(json_path, "w") as f:
            json.dump(payload, f, indent=2)


config = NautobotAppMcpServerConfig  # pylint:disable=invalid-name
