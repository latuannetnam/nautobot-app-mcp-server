# Nautobot App MCP Server

<p align="center">
  <img src="https://raw.githubusercontent.com/latuannetnam/nautobot-app-mcp-server/develop/docs/images/icon-nautobot-app-mcp-server.png" class="logo" height="200px">
  <br>
  <a href="https://github.com/latuannetnam/nautobot-app-mcp-server/actions"><img src="https://github.com/latuannetnam/nautobot-app-mcp-server/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/"><img src="https://readthedocs.org/projects/nautobot-app-mcp-server/badge/"></a>
  <a href="https://pypi.org/project/nautobot-app-mcp-server/"><img src="https://img.shields.io/pypi/v/nautobot-app-mcp-server"></a>
  <a href="https://pypi.org/project/nautobot-app-mcp-server/"><img src="https://img.shields.io/pypi/dm/nautobot-app-mcp-server"></a>
  <br>
  An <a href="https://networktocode.com/nautobot-apps/">App</a> for <a href="https://nautobot.com/">Nautobot</a>.
</p>

## Try it out

This App is installed in the **Nautobot Community Sandbox** at [demo.nautobot.com](https://demo.nautobot.com/)!

> For a full list of available sandbox environments, visit [networktocode.com/nautobot/sandbox-environments](https://www.networktocode.com/nautobot/sandbox-environments/).

## Overview

Nautobot App MCP Server is a Nautobot plugin that exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server, giving AI agents like Claude direct, tool-driven access to Nautobot's network infrastructure data. Rather than requiring an AI to parse raw API responses or navigate the Nautobot UI, the MCP server presents a curated set of typed tools — listing devices, interfaces, IP addresses, prefixes, VLANs, and locations — that AI agents can call naturally as part of their reasoning workflow.

The app bridges the gap between AI-assisted automation and the network data stored in Nautobot. A network engineer or SRE can ask Claude to "find all Juniper devices at the DC-1 site and check their interface statuses," and Claude can use the MCP tools to query that data directly, without requiring custom API scripts or manual data exports.

This app is **not** a data model extension — it introduces no new database models, custom fields, or jobs. It is purely a protocol adapter that wraps Nautobot's existing ORM and permission system behind the MCP interface, so AI agents get the same view of the network that a human user with the same permissions would have.

## What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) is an open standard developed by Anthropic that defines how AI applications (clients) connect to external data sources and tools (servers). MCP replaces the need for every AI integration to define its own bespoke API adapters: instead, an MCP server exposes a manifest of named, typed **tools**, and the AI client calls them via JSON-RPC 2.0 over HTTP. This makes adding Nautobot to any MCP-compatible AI agent — Claude Code, Claude Desktop, or any other MCP client — a matter of pointing the client at the server URL and providing an auth token. No custom prompt engineering or API wrapper code is required on the client side.

## MCP Tools

The server exposes **13 tools** — 3 session tools and 10 core read tools. All read tools respect Nautobot's object-level permissions, so AI agents see only what the associated Nautobot user is permitted to view.

### Session Tools

Session tools control progressive disclosure — what subset of tools the MCP manifest exposes to the AI for a given session.

| Tool | Description |
| --- | --- |
| `mcp_list_tools` | List all registered tools visible to the current session |
| `mcp_enable_tools` | Enable an app-tier tool scope (e.g. `dcim`) or a search term |
| `mcp_disable_tools` | Disable a tool scope (or all non-core tools if no scope given) |

### Core Read Tools

| Tool | Description |
| --- | --- |
| `device_list` | List network devices with status, platform, location, role, and tenant |
| `device_get` | Get a single device by name or UUID, with interfaces prefetched |
| `interface_list` | List network interfaces, optionally filtered by device name |
| `ipaddress_list` | List IP addresses with VRF, tenant, status, and role |
| `prefix_list` | List network prefixes with VRF, tenant, status, and role |
| `vlan_list` | List VLANs with site/group, status, and role |
| `location_list` | List locations with location type, parent, and tenant |
| `search_by_name` | Multi-model name search across devices, interfaces, IPs, prefixes, VLANs, and locations |

## Installation

Choose the path that matches your environment.

---

### Development (Docker Compose)

Get up and running locally in minutes.

#### 1. Install dependencies

```shell
poetry self add poetry-plugin-shell
poetry shell
poetry install
```

#### 2. Build and start the dev stack

```shell
invoke build
invoke start
```

This starts both Nautobot (at <http://localhost:8080>) and the MCP server (at <http://localhost:8005/mcp/>) in the background.

#### 3. Create an API token

Log into Nautobot at <http://localhost:8080> as `admin` / `admin`, then navigate to **Admin → Users → Tokens** and create a new token. Copy the 40-character hex value (no prefix).

#### 4. Connect an MCP client

```shell
claude mcp add --transport http \
  --header "Authorization: Token <your-40-char-hex-token>" \
  --scope user \
  nautobot \
  http://localhost:8005/mcp/
```

Or add manually to `~/.claude.json`:

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

---

### Production (standalone server)

Install the MCP server on a running Nautobot host (e.g. at `nautobot.example.com`). The MCP server runs as a **standalone FastMCP process on port 8005**, independent of the Nautobot WSGI service.

#### Prerequisites

- Nautobot installed at `/opt/nautobot` (or your install path)
- Nautobot running as the `nautobot` user
- Python 3.12+ with `pip` in the Nautobot venv
- Nautobot v3.0.0+ already configured and running

#### 1. Build the wheel package

On your **development machine**:

```shell
git clone https://github.com/latuannetnam/nautobot-app-mcp-server
cd nautobot-app-mcp-server
poetry install
poetry run poetry build --format wheel
```

Copy the resulting `.whl` file to the production server:

```shell
scp dist/nautobot_app_mcp_server-*.whl nautobot@nautobot.example.com:/tmp/
```

#### 2. Install the wheel

SSH into the production server, then as the `nautobot` user:

```shell
/opt/nautobot/bin/pip install --no-input /tmp/nautobot_app_mcp_server-*.whl
```

This installs the package into `/opt/nautobot/lib/python3.12/site-packages/`.

#### 3. Add to `PLUGINS` in `nautobot_config.py`

Edit `/opt/nautobot/nautobot_config.py` and add the app to the `PLUGINS` list:

```python
PLUGINS = [
    # ... existing plugins ...
    "nautobot_app_mcp_server",   # ← add this line
]
```

#### 4. Restart Nautobot WSGI service

```shell
sudo systemctl restart nautobot.service
```

#### 5. Start the MCP server

The MCP server does **not** auto-start via the WSGI service — it must be launched separately. As the `nautobot` user:

```shell
NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py \
  /opt/nautobot/bin/nautobot-server start_mcp_server
```

For production use, manage it via `systemd`. Create `/etc/systemd/system/nautobot-mcp.service`:

```ini
[Unit]
Description=Nautobot MCP Server
After=network.target nautobot.service

[Service]
User=nautobot
Group=nautobot
WorkingDirectory=/opt/nautobot
Environment="NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py"
ExecStart=/opt/nautobot/bin/nautobot-server start_mcp_server
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```shell
sudo systemctl daemon-reload
sudo systemctl enable --now nautobot-mcp.service
```

#### 6. Connect an MCP client

The MCP server will be available at `http://nautobot.example.com:8005/mcp/` (replace with your server's hostname/IP).

> **Note:** If connecting from a remote machine, ensure port 8005 is open in the firewall.

```shell
claude mcp add --transport http \
  --header "Authorization: Token <your-40-char-hex-token>" \
  --scope user \
  nautobot \
  http://nautobot.example.com:8005/mcp/
```

Or add manually to `~/.claude.json`:

```json
{
  "mcpServers": {
    "nautobot": {
      "url": "http://nautobot.example.com:8005/mcp/",
      "headers": {
        "Authorization": "Token <your-40-char-hex-token>"
      }
    }
  }
}
```

Create the API token at **Admin → Users → Tokens**. The token is a 40-character hex string — **do not** include the `nbapikey_` prefix.

---

## Usage

### Authentication

All MCP requests must include the Nautobot API token via the `Authorization` header:

```text
Authorization: Token <40-char-hex>
```

The token is a standard Nautobot REST API key (found at **Admin → Users → Tokens**). The MCP server validates the token against Nautobot's auth backend and enforces the associated user's object permissions on every tool call.

### Claude Desktop

Add the server to your Claude Desktop `claude_desktop_config.json`:

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

### Example JSON-RPC 2.0 tool calls

**List devices (paginated):**

```json
POST /mcp/ HTTP/1.1
Host: localhost:8005
Authorization: Token 0123456789abcdef0123456789abcdef01234567
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "device_list",
    "arguments": { "limit": 10 }
  },
  "id": 1
}
```

**Get a specific device:**

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "device_get",
    "arguments": { "name_or_id": "router-01" }
  },
  "id": 2
}
```

**Search for objects by name:**

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "search_by_name",
    "arguments": { "query": "edge juniper" }
  },
  "id": 3
}
```

**Paginate through results:**

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "prefix_list",
    "arguments": { "limit": 50, "cursor": "eyJsYXN0X2lkIjogIjEyMyJ9" }
  },
  "id": 4
}
```

## Architecture

The MCP server is implemented as a standalone [FastMCP](https://github.com/jlowin/fastmcp) HTTP server running on **port 8005**, alongside Nautobot's Django HTTP server on port 8080. It runs as an independent ASGI process managed by `nautobot-server start_mcp_server`, not inside the Nautobot WSGI service.

Both services are started automatically via `invoke start` in the development environment. In production, the WSGI service is managed by `systemd`/`uwsgi`, and the MCP server is managed by a separate `systemd` unit (see [Installation → Production](#production-standalone-server)).

The FastMCP server uses Nautobot's ORM and Token authentication infrastructure directly, so object permissions and user access control are enforced consistently whether data is accessed via the Nautobot UI or via MCP.

## Development

- **[Development Environment Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/dev_environment/)** — full setup: Docker Compose, Poetry, Invoke commands, debugging, running tests
- **[Import & UAT Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/import_and_uat/)** — importing production data into the dev DB and running the MCP UAT suite (37 scenarios in `scripts/run_mcp_uat.py`)
- **[Extending the App](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/extending/)** — registering custom MCP tools from third-party Nautobot apps using the `register_mcp_tool()` plugin API

## Documentation

Full documentation for this App can be found on the [Nautobot Docs](https://docs.nautobot.com) website:

- [User Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/app_overview/) — Overview, Using the App, Getting Started
- [Administrator Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/admin/install/) — Installation, Configuration, Upgrade, Uninstall
- [Developer Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/contributing/) — Extending the App, Code Reference, Contribution Guide
- [Release Notes / Changelog](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/admin/release_notes/)
- [Frequently Asked Questions](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/faq/)

### Contributing to the Documentation

You can find all the Markdown source for the App documentation under the [`docs`](https://github.com/latuannetnam/nautobot-app-mcp-server/tree/develop/docs) folder in this repository. For simple edits, a Markdown capable editor is sufficient: clone the repository and edit away.

If you need to view the fully-generated documentation site, you can build it with [MkDocs](https://www.mkdocs.org/). A container hosting the documentation can be started using the `invoke` commands (details in the [Development Environment Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/dev_environment/#docker-development-environment)) on [http://localhost:8001](http://localhost:8001). As your changes to the documentation are saved, they are automatically rebuilt and any pages currently being viewed are reloaded in your browser.

Any PRs with fixes or improvements are very welcome!

## Questions

For any questions or comments, please check the [FAQ](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/faq/) first. Feel free to also swing by the [Network to Code Slack](https://networktocode.slack.com/) (channel `#nautobot`), sign up [here](http://slack.networktocode.com/) if you don't have an account.
