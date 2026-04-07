# Getting Started with the App

This document provides a step-by-step guide to getting the Nautobot App MCP Server running and connected to an AI agent.

## Install the App

### Development

For local development, use Docker Compose:

```shell
poetry self add poetry-plugin-shell
poetry shell
poetry install
invoke build
invoke start
```

The Docker Compose stack starts two services:

- **Nautobot** at <http://localhost:8080>
- **MCP server** at <http://localhost:8005/mcp/>

### Production

In a production Nautobot installation, install the package and add it to `PLUGINS` in `nautobot_config.py`:

```python
PLUGINS = [
    "nautobot_app_mcp_server",
]
```

The MCP server will start automatically on port 8005 when Nautobot restarts.

## Create an API Token

The MCP server authenticates using a standard Nautobot REST API token.

1. Log into Nautobot as an admin user.
2. Navigate to **Admin → Users → Tokens**.
3. Click **Add** and create a token. Copy the 40-character hex value (no prefix — not `nbapikey_...`).

This token will be passed to your MCP client as the `Authorization` header.

## Connect an MCP Client

### Claude Code

Add the server to your `.mcp.json` file:

```json
{
  "mcpServers": {
    "nautobot": {
      "url": "http://localhost:8005/mcp/",
      "headers": {
        "Authorization": "Token <your-40-char-hex-token>"
      }
    }
  }
}
```

Restart the Claude Code session to load the new configuration.

### Claude Desktop

Add the server to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "nautobot": {
      "url": "http://localhost:8005/mcp/",
      "headers": {
        "Authorization": "Token <your-40-char-hex-token>"
      }
    }
  }
}
```

Restart Claude Desktop to load the new configuration.

## Start Using Tools

Once connected, the AI agent can call any of the 13 MCP tools. For example:

- `"List all devices in the production site"` → calls `device_list`
- `"Find the interface ge-0/0/0 on router-01"` → calls `device_get` then `interface_list`
- `"Search for all objects with 'edge' and 'juniper' in their name"` → calls `search_by_name`

Session tools (`mcp_list_tools`, `mcp_enable_tools`, `mcp_disable_tools`) control progressive disclosure — by default the AI sees only core tools. The `mcp_enable_tools` tool can be used to activate additional scopes for app-tier tools registered by other Nautobot apps.

## Next Steps

- See the [Usage section in the README](../../README.md#usage) for detailed JSON-RPC examples including pagination with cursors.
- See [Extending the App](../dev/extending.md) to register custom MCP tools from third-party Nautobot apps.
- Run the UAT suite with `bash scripts/reset_dev_db.sh --import && docker exec nautobot-app-mcp-server-nautobot-1 python /source/scripts/run_mcp_uat.py` to verify the installation end-to-end.
