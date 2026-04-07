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

| Tool | Description | Pagination |
|------|-------------|------------|
| `mcp_list_tools` | List all registered tools visible to the current session (core tools always shown; app-tier tools shown if their scope is enabled or matches an active search) | No |
| `mcp_enable_tools` | Enable an app-tier tool scope (e.g. `dcim`) or a fuzzy-search term for this session. Enabling a parent scope automatically activates all child scopes. | No |
| `mcp_disable_tools` | Disable a tool scope (or all non-core tools if no scope is given) | No |

### Core Read Tools

| Tool | Description | Pagination |
|------|-------------|------------|
| `device_list` | List network devices with status, platform, location, role, and tenant | Yes |
| `device_get` | Get a single device by name or UUID, with interfaces prefetched | No |
| `interface_list` | List network interfaces, optionally filtered by device name | Yes |
| `ipaddress_list` | List IP addresses with VRF, tenant, status, and role | Yes |
| `prefix_list` | List network prefixes with VRF, tenant, status, and role | Yes |
| `vlan_list` | List VLANs with site/group, status, and role | Yes |
| `location_list` | List locations with location type, parent, and tenant | Yes |
| `search_by_name` | Multi-model name search across devices, interfaces, IP addresses, prefixes, VLANs, and locations (AND semantics across space-separated terms) | Yes |

## Architecture

The MCP server is implemented as a [FastMCP](https://github.com/jlowin/fastmcp) server embedded in Nautobot's Django process. It runs as a standalone ASGI process on **port 8005** alongside Nautobot's Django HTTP server on port 8080. Both are started automatically via `invoke start`. The FastMCP server uses Nautobot's ORM and Token authentication infrastructure directly, so object permissions and user access control are enforced consistently whether data is accessed via the Nautobot UI or via MCP.

## Try it out

This App is installed in the Nautobot Community Sandbox found over at [demo.nautobot.com](https://demo.nautobot.com/)!

> For a full list of all the available always-on sandbox environments, head over to the main page on [networktocode.com](https://www.networktocode.com/nautobot/sandbox-environments/).

## Quick Start

### 1. Install dependencies

```shell
poetry self add poetry-plugin-shell
poetry shell
poetry install
```

### 2. Build and start the Docker dev stack

```shell
invoke build
invoke start
```

This starts both Nautobot (at <http://localhost:8080>) and the MCP server (at <http://localhost:8005/mcp/>) in the background.

### 3. Create an API token

Log into Nautobot at <http://localhost:8080> as `admin` / `admin`, then navigate to **Admin → Users → Tokens** and create a new token. Copy the 40-character hex value (no prefix).

### 4. Connect an MCP client

Point your MCP client at `http://localhost:8005/mcp/` and pass the token as:

```
Authorization: Token <your-40-char-hex-token>
```

See the [Usage](#usage) section below for Claude Code and Claude Desktop configuration.

## Usage

### Claude Code integration

Add the MCP server to your Claude Code `.mcp.json` configuration file:

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

### Claude Desktop integration

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

### Authentication

All MCP requests must include the Nautobot API token via the `Authorization` header:

```
Authorization: Token <40-char-hex>
```

The token is a standard Nautobot REST API key (found at **Admin → Users → Tokens**). The MCP server validates the token against Nautobot's auth backend and enforces the associated user's object permissions on every tool call.

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
    "arguments": {
      "limit": 10
    }
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
    "arguments": {
      "name_or_id": "router-01"
    }
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
    "arguments": {
      "query": "edge juniper"
    }
  },
  "id": 3
}
```

**Paginate through results using cursor:**

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "prefix_list",
    "arguments": {
      "limit": 50,
      "cursor": "eyJsYXN0X2lkIjogIjEyMyJ9"
    }
  },
  "id": 4
}
```

## Development

- **[Development Environment Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/dev_environment/)** — full setup: Docker Compose, Poetry, Invoke commands, debugging, running tests
- **[Import & UAT Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/import_and_uat/)** — importing production data into the dev DB and running the MCP UAT suite (37 scenarios in `scripts/run_mcp_uat.py`)
- **[Extending the App](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/extending/)** — registering custom MCP tools from third-party Nautobot apps using the `register_mcp_tool()` plugin API

## Documentation

Full documentation for this App can be found over on the [Nautobot Docs](https://docs.nautobot.com) website:

- [User Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/app_overview/) - Overview, Using the App, Getting Started
- [Administrator Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/admin/install/) - How to Install, Configure, Upgrade, or Uninstall the App
- [Developer Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/contributing/) - Extending the App, Code Reference, Contribution Guide
- [Release Notes / Changelog](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/admin/release_notes/)
- [Frequently Asked Questions](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/faq/)

### Contributing to the Documentation

You can find all the Markdown source for the App documentation under the [`docs`](https://github.com/latuannetnam/nautobot-app-mcp-server/tree/develop/docs) folder in this repository. For simple edits, a Markdown capable editor is sufficient: clone the repository and edit away.

If you need to view the fully-generated documentation site, you can build it with [MkDocs](https://www.mkdocs.org/). A container hosting the documentation can be started using the `invoke` commands (details in the [Development Environment Guide](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/dev/dev_environment/#docker-development-environment)) on [http://localhost:8001](http://localhost:8001). Using this container, as your changes to the documentation are saved, they will be automatically rebuilt and any pages currently being viewed will be reloaded in your browser.

Any PRs with fixes or improvements are very welcome!

## Questions

For any questions or comments, please check the [FAQ](https://docs.nautobot.com/projects/nautobot-app-mcp-server/en/latest/user/faq/) first. Feel free to also swing by the [Network to Code Slack](https://networktocode.slack.com/) (channel `#nautobot`), sign up [here](http://slack.networktocode.com/) if you don't have an account.
