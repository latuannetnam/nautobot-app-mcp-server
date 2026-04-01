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
    base_url = "mcp-server"
    required_settings = []
    default_settings = {}
    docs_view_name = "plugins:nautobot_app_mcp_server:docs"
    searchable_models = []


config = NautobotAppMcpServerConfig  # pylint:disable=invalid-name
