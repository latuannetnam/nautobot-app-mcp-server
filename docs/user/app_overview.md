# App Overview

This document provides an overview of the Nautobot App MCP Server, including its purpose, audience, and the Nautobot features it interacts with.

!!! note
    Throughout this documentation, the terms "app" and "plugin" will be used interchangeably.

## Description

Nautobot App MCP Server is a **protocol adapter** — it is not a data model extension. The app adds no new database tables, custom fields, jobs, or web UI elements to Nautobot. Instead, it embeds a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server alongside Nautobot's HTTP service, exposing a curated set of typed read tools that AI agents can call via the MCP standard.

The MCP server runs on **port 8005** (separate from Nautobot's web UI on port 8080). When an AI agent connects using a Nautobot API token, the server wraps Nautobot's Django ORM behind the MCP interface, enforcing the same object-level permissions that would apply to a human user logging into the Nautobot UI.

The core value proposition is **AI-assisted network operations**: instead of writing one-off API scripts or exporting data manually, a network engineer or SRE can ask an AI agent to query Nautobot directly using natural language, and the agent uses MCP tools to fetch the data.

## Audience (User Personas)

This app is designed for:

- **Network Engineers** who want AI agents to answer ad-hoc questions about network inventory — device lists, interface assignments, IP allocations — without leaving their terminal or writing API code.
- **Site Reliability Engineers (SREs)** who manage Nautobot as a source of truth and want to integrate network data queries into automated runbooks and incident response workflows.
- **AI/ML Practitioners** building automation or orchestration tools that need structured, permission-aware access to Nautobot's network data.
- **Platform Teams** evaluating or building MCP-compatible AI integrations against Nautobot as a backend data source.

## Nautobot Features Used

This app uses only Nautobot's **core** infrastructure — it does not install custom models, signals, or jobs.

| Nautobot Feature | How the App Uses It |
|------------------|---------------------|
| **Django ORM** | All read tools query Nautobot models (`dcim.Device`, `dcim.Interface`, `ipam.IPAddress`, etc.) via Django ORM. |
| **Token Authentication** | MCP connections authenticate via the standard Nautobot REST API token (`Authorization: Token <hex>` header). The app never implements its own auth. |
| **Object Permissions** | Every ORM query is restricted by `user.queryset(Model).restrict()` so agents see exactly what the associated token's user is permitted to view. |
| **Plugin Infrastructure** | The app follows Nautobot's plugin pattern in `__init__.py` (`NautobotAppMcpServerConfig`) and registers its entry points via `pyproject.toml`. |
| **App Config Schema** | `app-config-schema.json` is included for standard Nautobot app configuration validation. |

### Extras

This app does **not** create any custom fields, jobs, web UI views, or export templates. It is intentionally scoped to the MCP protocol layer only.

!!! note
    Because the app has no database models, there are no Django migrations to run after installation. The MCP server is available as soon as the plugin is activated.
