"""App declaration for nautobot_app_mcp_server."""

# Metadata is inherited from Nautobot. If not including Nautobot in the environment, this should be added
from importlib import metadata

from nautobot.apps import NautobotAppConfig

__version__ = metadata.version(__name__)


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
    urls = ["nautobot_app_mcp_server.urls"]

    def ready(self) -> None:
        """Initialize the MCP server app.

        1. Call super().ready() FIRST so Nautobot registers our urls.py via
           NautobotAppConfig.ready() → plugin_patterns.append(...).
        2. Connect post_migrate signal AFTER so register_mcp_tool() calls from
           other apps (that fire on their own post_migrate) are already in the registry.
        """
        super().ready()  # Registers URL patterns (MUST be first)

        from django.db.models.signals import post_migrate

        import nautobot_app_mcp_server.mcp.tools  # noqa: F401

        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs) -> None:
        """Register MCP tools after this app's migrations complete."""
        if app_config.name == "nautobot_app_mcp_server":
            from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

            MCPToolRegistry.get_instance()


config = NautobotAppMcpServerConfig  # pylint:disable=invalid-name
