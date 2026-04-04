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

### Resetting & Importing the Dev DB

The script `scripts/reset_dev_db.sh` handles the full two-phase workflow. Requires `nautobot_import.env` (see `docs/dev/import_and_uat.md`).

```bash
# Interactive menu (shows cache/DB status before choosing)
bash scripts/reset_dev_db.sh

# CLI shortcuts:
bash scripts/reset_dev_db.sh --reset      # Reset DB only (drop/migrate/superuser)
bash scripts/reset_dev_db.sh --fetch     # Phase 1: pull from production → JSON cache
bash scripts/reset_dev_db.sh --import    # Reset DB + import cached data (most common)
bash scripts/reset_dev_db.sh --all       # Full pipeline: reset → fetch → import
```

Key implementation notes for Claude memory:
- Docker compose files live in `development/`, not project root — use `--project-directory` with `-f` flags.
- DB user is `nautobot`, not `postgres` — always use `NAUTOBOT_DB_USER` from `development.env`.
- Management commands must use `nautobot-server import_production_data`, not bare `python ...`.
- Pass `--cache-dir /source/import_cache` (volume-mounted from host's `import_cache/`).
- Fresh DB has no `LocationType` rows — `import_production_data.py` auto-creates a default `Region` type.

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
nautobot_app_mcp_server/
│   ├── __init__.py                # Config + post_migrate signal → init registry
│   ├── mcp/
│   │   ├── __init__.py            # register_mcp_tool() — public plugin API
│   │   ├── server.py             # FastMCP lazy singleton, _list_tools_mcp override
│   │   ├── session_tools.py      # MCPSessionState, progressive disclosure handler
│   │   ├── registry.py           # MCPToolRegistry singleton + ToolDefinition dataclass
│   │   ├── view.py               # mcp_view: Django→ASGI bridge (async_to_sync)
│   │   ├── auth.py               # get_user_from_request() — Token auth, _cached_user
│   │   ├── tools/
│   │   │   ├── __init__.py       # Imports all core tools (side-effect registers them)
│   │   │   ├── core.py           # 10 read tools (list/create/update/delete)
│   │   │   ├── pagination.py     # Paginator helper
│   │   │   └── query_utils.py    # Query-building helpers
│   │   └── tests/
│   │       ├── test_view.py, test_auth.py, test_session_tools.py, test_core_tools.py
│   │       ├── test_signal_integration.py, test_session_persistence.py
development/                       # Docker Compose dev environment
docs/dev/                          # Developer docs
scripts/reset_dev_db.sh            # DB reset + production import
tasks.py                           # Invoke automation
pyproject.toml                     # Poetry + tool config
changes/                           # Towncrier release note fragments
```

---

## MCP Server Architecture

### Request Flow

```
Django HTTP request
  → mcp_view() [view.py, @csrf_exempt, async_to_sync]
    → _bridge_django_to_asgi() [stores Django request in _django_request_ctx ContextVar]
      → get_mcp_app() [server.py, lazy singleton, double-check locking]
        → FastMCP http_app() [Starlette ASGI app, StreamableHTTPSessionManager]
          → progressive_list_tools_mcp() [overrides mcp._list_tools_mcp]
            → _list_tools_handler() [session_tools.py — filters by session state]
              → MCPToolRegistry [registry.py — scope prefix matching for hierarchy]
                → Auth guard [auth.py — Token header, _cached_user per RequestContext]
                  → Tool function [tools/core.py]
```

### Key Design Decisions

| Aspect | Decision | Rationale |
|---|---|---|
| Session state storage | `RequestContext._mcp_tool_state` dict, NOT `ServerSession` | `ServerSession` is NOT dict-like — latent bug if you store on session directly |
| Event loop persistence | Daemon thread runs `lifespan_context()` + `Event.wait()` | Single event loop shared across Django requests preserves session state |
| FastMCP initialization | Lazy `get_mcp_app()` on first HTTP request | Django ORM not ready at import time |
| Progressive disclosure | Override `mcp._list_tools_mcp` directly | FastMCP 3.x `@mcp.list_tools()` is async decorator → TypeError |
| Tool registration | `register_mcp_tool()` called at module import time | Third-party apps call it in `ready()` or `post_migrate` signal |
| Scope hierarchy | Prefix matching (`t.scope.startswith(f"{scope}.")`) | Enabling `dcim` auto-activates `dcim.interface`, `dcim.device`, etc. |
| Auth caching | `_cached_user` on `RequestContext` | Avoids repeated DB lookups per request batch |

### `register_mcp_tool()` — Public Plugin API

```python
def register_mcp_tool(
    name: str,
    func: Callable,              # async function(ctx, **kwargs) → dict
    description: str,
    input_schema: dict,          # JSON Schema
    tier: str = "app",           # "core" (always visible) or "app" (progressive)
    app_label: str | None = None,
    scope: str | None = None,    # dot-separated, e.g. "dcim.device"
) -> None
```

All 13 tools (3 session + 10 core read) are registered via this API in `mcp/tools/__init__.py`.

### `MCPToolRegistry` Singleton (`registry.py`)

Thread-safe singleton with double-checked locking. Stores `ToolDefinition(name, func, description, input_schema, tier, app_label, scope)`. Key methods:
- `register()` — raises `ValueError` on duplicate
- `get_core_tools()` — all `tier="core"`
- `get_by_scope(scope)` — exact match + all child scopes (prefix match)
- `fuzzy_search(term)` — case-insensitive substring on name + description

---

## Auth — Token Format & Gotchas

- Token key: **40-char hex, no prefix** (NOT `nbapikey_<hex>`)
- Source: `Authorization: Token <key>` header on **MCP request**, not Django request (PIT-16)
- Cache: `_cached_user` on `RequestContext` — per-request, not cross-request
- On missing/invalid token: returns `AnonymousUser` (empty querysets via `.restrict()`); logs `WARNING` (missing) or `DEBUG` (invalid)

---

## FastMCP 3.x Gotchas (Current Implementation)

| Issue | Location | Detail |
|---|---|---|
| `@mcp.list_tools()` raises `TypeError` | server.py L76 | FastMCP 3.x: async decorator, not usable → override `mcp._list_tools_mcp` |
| `ServerSession` is NOT dict-like | session_tools.py L13 | Store state on `request_context`, not `session` directly |
| Django ORM not ready at import time | server.py L4-5 | Lazy `get_mcp_app()` defers FastMCP creation to first request |
| Event loop must persist across requests | view.py L117 | Use `async_to_sync` (reuses existing loop), NOT `asyncio.run()` |
| `StreamableHTTPSessionManager.run()` needs lifespan | server.py L135-167 | Daemon thread: `lifespan_context()` → `Event.wait()` |
| `_cached_user` is per-`RequestContext` | auth.py L85 | Caches per-request, not across requests |

---

## Permissions Note for Claude Code

Custom permissions in `.claude/settings.local.json` are required for:
- Poetry commands (`poetry run`, `poetry install`, `poetry lock`)
- Docker/invoke commands
- GitHub API access via `gh`
- WebFetch for GitHub domains
- Context7 MCP for Nautobot docs lookup

Do not remove these permissions.
