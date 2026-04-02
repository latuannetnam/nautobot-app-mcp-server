# CLAUDE.md — Nautobot App MCP Server

Project-specific instructions for Claude Code working in this repository.

---

## Project Overview

**nautobot-app-mcp-server** is a Nautobot App that exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server. It is **not** a data model app — it is a protocol adapter layer embedded in Nautobot's Django process.

- **Repository:** https://github.com/latuannetnam/nautobot-app-mcp-server
- **License:** Apache-2.0
- **Python:** >=3.10, <3.15 (dev runtime: 3.12)
- **Nautobot:** >=3.0.0, <4.0.0

---

## Poetry — Critical Rules

This project uses **Poetry exclusively**. Never use `pip` directly.

- **`VIRTUAL_ENV=/usr`** is set in WSL shell profiles — **always `unset VIRTUAL_ENV`** before Poetry commands.
- Virtualenv: `.venv/` in project root (via `poetry config virtualenvs.in-project true`).
- **All commands:** `poetry run <command>` or `poetry shell`.

### Common Commands

```bash
# Development
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server && poetry shell    # activate venv
unset VIRTUAL_ENV && poetry lock && poetry install                                              # install deps

# Docker / Dev Stack
unset VIRTUAL_ENV && poetry run invoke start          # start Docker Compose dev stack
unset VIRTUAL_ENV && poetry run invoke cli            # shell into running container
unset VIRTUAL_ENV && poetry run invoke build         # rebuild Docker image (after poetry.lock change)

# Testing (run inside container: docker exec -it nautobot-app-mcp-server-nautobot-1 bash)
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests    # MCP tests only (~0.6s)
poetry run nautobot-server test nautobot_app_mcp_server              # all app tests
unset VIRTUAL_ENV && poetry run invoke unittest        # unit tests (from host)
unset VIRTUAL_ENV && poetry run invoke unittest --coverage  # with coverage
unset VIRTUAL_ENV && poetry run invoke tests           # full CI pipeline (linters + tests)

# Linting
unset VIRTUAL_ENV && poetry run invoke ruff [--fix]    # ruff: PEP 8, isort, flake8, bandit
unset VIRTUAL_ENV && poetry run invoke pylint         # pylint (must stay 10.00/10)
unset VIRTUAL_ENV && poetry run invoke djlint         # djlint + djhtml
unset VIRTUAL_ENV && poetry run invoke yamllint       # YAML files
unset VIRTUAL_ENV && poetry run invoke mkdocs         # build docs

# Other
unset VIRTUAL_ENV && poetry run invoke generate-release-notes  # towncrier build
```

---

## Development Environment

Docker Compose in `development/`. Start with `poetry run invoke start`. Nautobot at http://localhost:8080.

First time setup:
```bash
cp development/creds.env.example development/creds.env
# Edit development/creds.env with your secrets
```

---

## Testing Workflow

All tests run **inside the Docker container** where Nautobot and all dependencies are installed.

```bash
# Start and access container
unset VIRTUAL_ENV && poetry run invoke start
docker exec -it nautobot-app-mcp-server-nautobot-1 /bin/bash

# Inside container
cd /source
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests   # fast
poetry run nautobot-server test nautobot_app_mcp_server             # all tests
```

**Debug import errors** (inside container):
```bash
# List module exports
python -c 'import mcp.server; print([x for x in dir(mcp.server) if not x.startswith("_")])'

# Check specific import
python -c 'from fastmcp.server.context import Context; print(Context)'
python -c 'from mcp.types import Tool; print(Tool)'
```

**Key Gotchas**

| Issue | Cause | Fix |
|---|---|---|
| `ImportError` on `mcp.server.Context` | FastMCP 3.x moved types | `from fastmcp.server.context import Context` |
| `ImportError` on `mcp.server.ToolInstance` | FastMCP 3.x moved types | `from mcp.types import Tool` |
| `@mcp.list_tools()` raises `TypeError` | FastMCP 3.x: async, not a decorator | Override `mcp._list_tools_mcp` directly |
| Source changes not picked up | Source is volume-mounted at `/source` | Changes are immediate; rebuild only for deps |
| `VIRTUAL_ENV=/usr` errors | WSL inherited env var | Always `unset VIRTUAL_ENV` before Poetry |
| Tests pass but `invoke tests` fails | `ruff format` issues | `ruff format .` inside container |

---

## Conventions

### Code Quality (Non-Negotiables)

- **Pylint score: 10.00/10.** PRs that drop the score must fix issues before merging.
- **`invoke tests` must pass** before pushing.
- **`ruff --fix` is safe** to run locally or in CI — it auto-fixes what it can.

### Ruff (PEP 8, isort, flake8, bandit)

- **Line length: 120.** Wrap with `# noqa: E501` only when necessary.
- **Docstring convention: Google style.**
- **D401 ignored** (imperative mood first line not required).
- **D docs not required** for migrations or test files.
- **Rule prefixes:** `F/E/W` (pyflakes), `I` (isort), `D` (pydocstyle), `S` (bandit).

### Pylint (Django-aware via pylint-nautobot)

- **No docstring required for:** `_`-prefixed methods, `test_*` functions, `Meta` inner classes.
- **TODO comments:** `FIXME` and `XXX` are permitted.
- **Disabled checks:** `line-too-long` (Ruff handles it), `too-many-positional-arguments`.

### Type Hints

- Use `from __future__ import annotations` (PEP 563).
- Use `# type: ignore` for third-party stubs that don't type cleanly.
- Pylint `init-hook` loads Nautobot before scanning.

### Naming

| Object | Convention | Example |
|---|---|---|
| Modules | `snake_case.py` | `nautobot_app_mcp_server/__init__.py` |
| Classes | `PascalCase` | `NautobotAppMcpServerConfig` |
| Functions / variables | `snake_case` | `is_truthy`, `compose_command_tokens` |
| Constants | `SCREAMING_SNAKE_CASE` | `LOG_LEVEL`, `NAUTOBOT_VER` |
| Private helpers | `_leading_underscore` | `_await_healthy_container()` |

### No Database Models

This app has **no Django database models**. Removed: `models.py`, `filters.py`, `forms.py`, `tables.py`, `views.py`, `urls.py`, `api/`, `navigation.py`, `migrations/`.

---

## Git Workflow

- **Branches:** `feature/...`, `fix/...`, `docs/...`
- **Commits:** conventional format — `type: description`
- **Before pushing:** `poetry run invoke tests`
- **Before opening PR:** `poetry run invoke ruff [--fix]`, `poetry run invoke pylint`

---

## GSD Workflow Enforcement

Use GSD commands for all implementation work. Do not make direct repo edits outside a GSD workflow unless the user explicitly asks.

- `/gsd:quick` — small fixes, doc updates, ad-hoc tasks
- `/gsd:debug` — investigation and bug fixing
- `/gsd:execute-phase` — planned phase work

---

## Project Structure

```
nautobot_app_mcp_server/          # Main app package (no DB models)
│   ├── __init__.py              # NautobotAppMcpServerConfig + post_migrate signal
│   ├── api/                     # REST API (empty — no models)
│   ├── mcp/
│   │   ├── server.py            # FastMCP lazy factory (PIT-03)
│   │   ├── session_tools.py     # MCPSessionState + session management tools
│   │   ├── registry.py          # MCPToolRegistry singleton + ToolDefinition
│   │   ├── view.py             # Django → FastMCP ASGI bridge
│   │   ├── auth.py             # get_user_from_request()
│   │   └── tests/              # Unit tests
│   └── tests/                  # Unit tests
development/                     # Docker Compose dev environment
docs/dev/                        # Developer documentation
tasks.py                         # Invoke automation tasks
pyproject.toml                   # Poetry + tool config
changes/                        # Towncrier release notes fragments
```

---

## MCP Server Implementation

Key files and their purpose:

| File | Purpose |
|---|---|
| `mcp/server.py` | FastMCP instance setup; progressive disclosure via `_list_tools_mcp` override |
| `mcp/session_tools.py` | `MCPSessionState`, `_list_tools_handler`, `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` |
| `mcp/registry.py` | `MCPToolRegistry` (thread-safe singleton), `ToolDefinition` dataclass |
| `mcp/view.py` | `mcp_view` — Django WSGI → FastMCP ASGI bridge |
| `mcp/auth.py` | `get_user_from_request()` — extract Nautobot user from Django session |
| `mcp/__init__.py` | `register_mcp_tool()` — public API for third-party Nautobot apps |

**Session state** (`session_tools.py`): Per-conversation enabled scopes and fuzzy searches stored in FastMCP's session dict. Core tools always visible; app-tier tools filtered by scope hierarchy.

---

## Permissions Note for Claude Code

Custom permissions in `.claude/settings.local.json` are required for:
- Poetry commands (`poetry run`, `poetry install`, `poetry lock`)
- Docker/invoke commands
- GitHub API access via `gh`
- WebFetch for GitHub domains
- Context7 MCP for Nautobot docs lookup

Do not remove these permissions.
