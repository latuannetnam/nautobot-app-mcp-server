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
        """Connect post_migrate signal for tool registration.

        post_migrate fires after migrations for this app complete.
        At that point all other apps' ready() hooks have already run,
        so their register_mcp_tool() calls are already in the registry.
        """
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs) -> None:
        """Register MCP tools after this app's migrations complete."""
        if app_config.name == "nautobot_app_mcp_server":
            from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

            MCPToolRegistry.get_instance()


config = NautobotAppMcpServerConfig  # pylint:disable=invalid-name
