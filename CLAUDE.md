# CLAUDE.md — Nautobot App MCP Server

Project-specific instructions for Claude Code working in this repository.

---

## Project Overview

**nautobot-app-mcp-server** is a Nautobot App that exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server, allowing AI tools (like Claude Code) to interact with Nautobot's data and API. It is **not** a traditional Nautobot app with database models — it is a protocol adapter layer.

**Repository:** https://github.com/latuannetnam/nautobot-app-mcp-server
**Author:** Le Anh Tuan <latuannetnam@gmail.com>
**License:** Apache-2.0
**Python:** >=3.10, <3.15 (tested on 3.12)

---

## Poetry — Critical Rules

This project uses **Poetry** exclusively. `pip` must NEVER be used directly.

- `VIRTUAL_ENV=/usr` is set in WSL Ubuntu 24.04 shell profiles — **always `unset VIRTUAL_ENV`** before Poetry commands.
- Virtualenv is created in-project at `.venv/` (via `poetry config virtualenvs.in-project true`).
- **All commands** must use `poetry run <command>` or `poetry shell`.

### Common Commands

```bash
# Shell — activates the Poetry venv
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server && poetry shell

# Install dependencies (after poetry.lock changes)
unset VIRTUAL_ENV && poetry lock && poetry install

# Run invoke tasks (most common dev tasks)
unset VIRTUAL_ENV && poetry run invoke --list          # list all tasks
unset VIRTUAL_ENV && poetry run invoke tests           # run full test suite
unset VIRTUAL_ENV && poetry run invoke ruff            # lint with ruff
unset VIRTUAL_ENV && poetry run invoke yamllint       # lint YAML files
unset VIRTUAL_ENV && poetry run invoke mkdocs          # build docs
unset VIRTUAL_ENV && poetry run invoke pylint          # run pylint
unset VIRTUAL_ENV && poetry run invoke start           # start Docker Compose dev stack

# Run a single command in the venv
unset VIRTUAL_ENV && poetry run nautobot-server --version
```

---

## Development Environment

The dev environment uses **Docker Compose** defined in `development/`.

1. Copy credentials file:
   ```bash
   cp development/creds.env.example development/creds.env
   # Then edit development/creds.env with your secrets
   ```

2. Start the stack:
   ```bash
   unset VIRTUAL_ENV && poetry run invoke start
   ```
   Nautobot will be available at http://localhost:8080

3. Other useful invoke tasks:
   ```bash
   poetry run invoke makemigrations   # generate migrations
   poetry run invoke createsuperuser   # create admin user
   poetry run invoke ruff --fix        # auto-fix lint issues
   poetry run invoke coverage          # run tests with coverage
   ```

---

## Code Quality Tools

| Tool | Command | Notes |
|---|---|---|
| Ruff | `poetry run invoke ruff` | PEP 8, isort, flake8, bandit |
| Pylint | `poetry run invoke pylint` | Django-aware via pylint-nautobot |
| yamllint | `poetry run invoke yamllint` | YAML linting |
| djlint | `poetry run invoke lint` | Django template linting |
| mkdocs | `poetry run invoke mkdocs` | Build docs at `nautobot_app_mcp_server/static/nautobot_app_mcp_server/docs/` |

> **Pylint score must remain 10.00/10.** Any PR that drops the score must fix the issues before merging.

---

## Project Structure

```
nautobot-app-mcp-server/
├── nautobot_app_mcp_server/     # Main app package
│   ├── __init__.py             # NautobotAppMcpServerConfig
│   ├── api/                    # REST API (currently empty — no models)
│   ├── tests/                  # Unit tests
│   └── ...
├── development/                # Docker Compose dev environment
│   ├── docker-compose.base.yml
│   ├── docker-compose.dev.yml
│   ├── docker-compose.postgres.yml
│   ├── docker-compose.redis.yml
│   ├── nautobot_config.py
│   └── Dockerfile
├── docs/                       # MkDocs documentation
│   ├── user/                   # User guide
│   ├── admin/                  # Admin guide
│   └── dev/                    # Developer guide
├── tasks.py                    # Invoke automation tasks
├── pyproject.toml              # Poetry + tool config
└── CLAUDE.md                   # This file
```

---

## No Database Models

This app has **no Django database models**. The following boilerplate has been intentionally removed:
- `models.py`, `filters.py`, `forms.py`, `tables.py`, `views.py`, `urls.py`
- `api/serializers.py`, `api/urls.py`, `api/views.py`
- `navigation.py`, `migrations/`

The app focuses on MCP protocol implementation and Nautobot plugin integration only.

---

## Changelog (Towncrier)

Changes are managed via [Towncrier](https://towncrier.readthedocs.io/). Do NOT edit release notes files directly.

To add a change entry, create a file in `changes/` with the appropriate directory:

| Directory | Type |
|---|---|
| `changes/added/` | New feature |
| `changes/changed/` | Change in existing behavior |
| `changes/fixed/` | Bug fix |
| `changes/removed/` | Removed feature |
| `changes/breaking/` | Breaking change |
| `changes/deprecated/` | Deprecation notice |
| `changes/security/` | Security fix |
| `changes/documentation/` | Docs-only change |
| `changes/dependencies/` | Dependency change |
| `changes/housekeeping/` | Internal housekeeping |

Filename format: `{issue_number}.{type}.md` (e.g., `42.added.md`)

To build the changelog:
```bash
poetry run towncrier build
```

---

## Pre-Commit Hooks

Set up pre-commit (optional but recommended):
```bash
poetry run pre-commit install
poetry run pre-commit run --all-files
```

---

## Git Workflow

- Branch naming: `feature/...`, `fix/...`, `docs/...`
- Commits follow conventional format: `type: description`
- Run all tests (`poetry run invoke tests`) before pushing
- Run `poetry run invoke lint` before opening PR

---

## MCP Server Implementation

The MCP server implementation belongs in `nautobot_app_mcp_server/`. Key areas to develop:

- MCP protocol handler / server setup
- Nautobot API integration (read-only access to Nautobot objects)
- Tool/Resource definitions exposed via MCP
- Authentication and security considerations

---

## Permissions Note for Claude Code

This project has custom Claude Code permissions in `.claude/settings.local.json` that allow:
- Poetry environment management (`poetry run`, `poetry install`, `poetry lock`, etc.)
- Docker/invoke commands
- GitHub API access via `gh`
- WebFetch for GitHub domains
- Context7 MCP for Nautobot docs lookup

Do not remove these permissions — they are required for Claude Code to function properly in this project.
