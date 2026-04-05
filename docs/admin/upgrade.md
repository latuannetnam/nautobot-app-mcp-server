# Upgrading the App

Here you will find any steps necessary to upgrade the App in your Nautobot environment.

## Upgrade Guide

!!! warning "Developer Note - Remove Me!"
    Add more detailed steps on how the app is upgraded in an existing Nautobot setup and any version specifics (such as upgrading between major versions with breaking changes).

When a new release comes out it may be necessary to run a migration of the database to account for any changes in the data models used by this app. Execute the command `nautobot-server post-upgrade` within the runtime environment of your Nautobot installation after updating the `nautobot-app-mcp-server` package via `pip`.

## Worker Process Requirement

!!! warning "Single Worker Required"
    The MCP server **must** be run with `--workers 1` (the default for uvicorn).

### Rationale

The MCP server stores session state in-memory. Running with multiple workers
(`--workers N` where `N > 1`) causes sessions to be lost when requests are routed
to different worker processes, breaking the progressive tool discovery feature.

### Production Deployment

For production deployments using systemd, the default uvicorn worker count (1)
is already correct. If explicitly setting workers:

```ini
[Service]
ExecStart=/opt/nautobot/venv/bin/nautobot-server start_mcp_server --workers 1
```

### Development

The development server (`start_mcp_dev_server`) uses `uvicorn.run(reload=True)`
which always runs with a single worker.

### Future: Horizontal Scaling

For deployments requiring `--workers N` where `N > 1`, a Redis session backend
is required to share session state across processes. This is planned for v2.0.
