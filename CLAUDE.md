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
unset VIRTUAL_ENV && poetry run invoke cli             # shell into running container
unset VIRTUAL_ENV && poetry run invoke unittest        # run unit tests only (no linters)

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

## Testing Workflow

All tests run **inside the Docker container** where Nautobot and all dependencies are installed.

### Start and Access the Container

```bash
# Start the dev stack (from host)
unset VIRTUAL_ENV && poetry run invoke start

# Shell into the running container
docker exec -it nautobot-app-mcp-server-nautobot-1 /bin/bash
```

### Run Tests (Inside Container Shell)

```bash
cd /source

# Run only the MCP unit tests (fastest — ~0.6s)
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests

# Run all unit tests for this app
poetry run nautobot-server test nautobot_app_mcp_server

# Run the full test suite from host (linters + unit tests)
unset VIRTUAL_ENV && poetry run invoke tests

# Run just linters from host
unset VIRTUAL_ENV && poetry run invoke ruff [--fix]
unset VIRTUAL_ENV && poetry run invoke pylint
```

### Inspect Modules and Debug Imports

```bash
# List what a module exports
python -c 'import mcp.server; print([x for x in dir(mcp.server) if not x.startswith("_")])'

# Check if a specific import works
python -c 'from fastmcp.server.context import Context; print(Context)'
python -c 'from mcp.types import Tool; print(Tool)'

# Verify source file changes work (source is volume-mounted at /source)
python -c 'import nautobot_app_mcp_server.mcp.server; print("OK")'
```

### Rebuild Docker Image (Required After Dependency Changes)

```bash
# Only needed when pyproject.toml or poetry.lock changes
unset VIRTUAL_ENV && poetry run invoke build

# After rebuild: remove old containers so Docker uses the new image
docker compose -f development/docker-compose.dev.yml down
docker compose -f development/docker-compose.dev.yml up --detach

# Verify new image is running
docker exec nautobot-app-mcp-server-nautobot-1 pip show fastmcp
```

### Key Gotchas

| Issue | Cause | Solution |
|---|---|---|
| `ImportError` on `mcp.server.Context` | FastMCP 3.x moved types | Use `from fastmcp.server.context import Context` |
| `ImportError` on `mcp.server.ToolInstance` | FastMCP 3.x moved types | Use `from mcp.types import Tool` |
| `@mcp.list_tools()` raises `TypeError` | FastMCP 3.x: async, not a decorator | Override `mcp._list_tools_mcp` directly |
| Source changes not picked up | Depends on whether it's volume-mounted | Source at `/source` IS volume-mounted — changes are immediate |
| `VIRTUAL_ENV=/usr` errors | WSL inherited env var | Always `unset VIRTUAL_ENV` before Poetry commands |
| Tests pass but `invoke tests` fails | `ruff format` or lint issues | Run `ruff format` in container: `cd /source && ruff format .` |

### Run Tests from Host Without Shelling In

```bash
# Entire pipeline: linters + unit tests
unset VIRTUAL_ENV && poetry run invoke tests

# Just unit tests
unset VIRTUAL_ENV && poetry run invoke unittest

# With coverage
unset VIRTUAL_ENV && poetry run invoke unittest --coverage
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

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Nautobot App MCP Server**

A Nautobot App that embeds a Model Context Protocol (MCP) server inside Nautobot's Django process, enabling AI agents (Claude Code, Claude Desktop) to interact with Nautobot data via MCP tools rather than an external REST API call. It exposes a FastMCP HTTP endpoint, uses direct Django ORM (zero network overhead), and supports progressive disclosure of tools — 10 Core tools always available, plus discoverable per-model tools from Nautobot apps.

**Core Value:** AI agents can query Nautobot network inventory data via MCP tools with full Nautobot permission enforcement, zero extra network hops, and progressive tool discovery.

### Constraints

- **Tech stack**: Python >=3.10 <3.15, Poetry-only (no pip), Nautobot >=3.0.0
- **No database models**: App is a protocol adapter, not a data model app
- **Pylint 10.00/10**: Score must never drop below 10.00
- **Docker Compose dev environment**: All tests run via `poetry run invoke tests`
- **Poetry shell WSL caveat**: `unset VIRTUAL_ENV` required before Poetry commands in WSL
- **Python undeclared**: `VIRTUAL_ENV=/usr` in WSL shell profiles — must unset
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Language & Runtime
| Item | Value | Source |
|---|---|---|
| **Language** | Python 3.10 – 3.14 | `pyproject.toml` line 31 |
| **Tested / Dev runtime** | Python 3.12 | `tasks.py` line 57 |
| **WSL VENV** | `/usr` (system site-packages) | CLAUDE.md |
## Package Manager
# development/Dockerfile lines 29–31
# Install deps after lockfile changes
# Run any command inside the venv
# Shell (activates venv, clears WSL VIRTUAL_ENV)
## Core Dependency: Nautobot
## Dev Dependencies
| Package | Purpose |
|---|---|
| `coverage` | Code coverage reporting |
| `django-debug-toolbar` | Django debug toolbar in dev |
| `invoke` | Task runner (the `tasks.py` framework) |
| `ipython` | Enhanced Python REPL |
| `pylint` | Code analysis |
| `pylint-django >=2.5.4` | Django-aware Pylint plugin |
| `pylint-nautobot >=0.3.1` | Nautobot-aware Pylint plugin |
| `ruff = 0.5.5` | Linter/formatter (flake8, isort, bandit, pydocstyle) |
| `yamllint` | YAML linting |
| `toml` | TOML file parsing |
| `pymarkdownlnt ~0.9.30` | Markdown linting |
| `Markdown` | Markdown processing |
| `towncrier >=23.6.0,<=24.8.0` | Changelog/release notes |
| `to-json-schema` | JSON schema generation |
| `jsonschema` | JSON schema validation |
| `djlint >=1.36.4,<2.0.0` | Django template linting |
| `djhtml >=3.0.8,<4.0.0` | Django HTML formatter |
| `tomli` (python < 3.11) | `tomllib` stdlib backport |
## Docs Dependencies
| Package | Purpose |
|---|---|
| `markdown-version-annotations = 1.0.1` | Render markdown annotations in release notes |
| `mkdocs = 1.6.0` | Docs site generator |
| `mkdocs-material = 9.5.32` | Material theme for MkDocs |
| `mkdocstrings = 0.25.2` | Autogenerate API docs from docstrings |
| `mkdocstrings-python = 1.10.8` | Python plugin for mkdocstrings |
| `mkdocs-autorefs = 1.2.0` | Auto reference links in docs |
| `griffe = 1.1.1` | Library used by mkdocstrings for Python inspection |
| `mkdocs-glightbox = 0.5.2` | Image lightbox in docs |
## Docker / Dev Environment
### Base Image
# development/Dockerfile line 16
### Services (Docker Compose)
| Service | Image | Notes |
|---|---|---|
| `nautobot` | built from `Dockerfile` | Django dev server on `:8080` |
| `worker` | same image | Celery worker (`nautobot-server celery worker`) |
| `beat` | same image | Celery beat scheduler |
| `db` | `postgres:17-alpine` (default) | PostgreSQL 17; also supports `mysql:lts` |
| `redis` | `redis:6-alpine` | Redis 6 with AOF and password auth |
### Environment Files
| File | Purpose |
|---|---|
| `development/development.env` | Non-secret env vars (debug on, ports, DB name/user) |
| `development/creds.env` | Secrets (passwords, secret keys, API tokens) — gitignored |
| `development/creds.example.env` | Template for `creds.env` |
## Configuration (nautobot_config.py)
# Database (PostgreSQL default; MySQL via NAUTOBOT_DB_ENGINE)
## Code Quality Tools
| Tool | Config location | Command |
|---|---|---|
| **Ruff** 0.5.5 | `pyproject.toml` `[tool.ruff]` | `invoke ruff [--fix]` |
| **Pylint** | `pyproject.toml` `[tool.pylint.master]` | `invoke pylint` |
| **yamllint** | `tasks.py` `yamllint` task | `invoke yamllint` |
| **djlint** | `pyproject.toml` `[tool.djlint]` | `invoke lint` (also runs djhtml) |
| **markdownlint** | `pyproject.toml` `[tool.pymarkdown]` | `invoke markdownlint [--fix]` |
| **Coverage** | `pyproject.toml` `[tool.coverage.run]` | `invoke coverage` |
| **Towncrier** | `pyproject.toml` `[tool.towncrier]` | `invoke generate-release-notes` |
## Changelog / Release Management
- `changes/added/`, `changes/changed/`, `changes/fixed/`, `changes/removed/`, `changes/breaking/`, `changes/deprecated/`, `changes/security/`, `changes/documentation/`, `changes/dependencies/`, `changes/housekeeping/`
## Invoke Task Framework
| Task | Command | Purpose |
|---|---|---|
| `invoke start` | `docker compose up --detach` | Start dev stack |
| `invoke tests` | runs all linters + unit tests | Full CI pipeline |
| `invoke lock [--constrain-nautobot-ver]` | `poetry lock` | Generate `poetry.lock` |
| `invoke build` | `docker compose build` | Build Docker image |
| `invoke cli` | `docker compose exec nautobot bash` | Shell into container |
| `invoke pylint` | Pylint + migrations checker | Lint with Django awareness |
| `invoke mkdocs` / `invoke docs` | `mkdocs serve` | Build/serve docs |
| `invoke dbshell` | `psql` / `mysql` in `db` container | DB CLI |
| `invoke backup-db` / `invoke import-db` | `pg_dump` / `pg_restore` | DB backup/restore |
| `invoke unittest [--coverage]` | `nautobot-server test` | Run tests |
| `invoke generate-release-notes` | `towncrier build` | Build changelog |
| `invoke validate-app-config` | `nbshell` with app schema | Validate `PLUGINS_CONFIG` schema |
## Static Files / Packaging
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Python Version & Runtime
| Concern | Value |
|---|---|
| Minimum Python | `>=3.10,<3.15` |
| Target (development) | `3.12` |
| Enforcement | `pyproject.toml` `tool.poetry.dependencies.python` |
## Toolchain
| Tool | Purpose | Config location |
|---|---|---|
| **Ruff** | Formatting + linting (PEP 8, isort, flake8, bandit) | `pyproject.toml [tool.ruff]` |
| **Pylint** (+ `pylint-nautobot`, `pylint-django`) | Deep static analysis, Django-aware | `pyproject.toml [tool.pylint.*]` |
| **yamllint** | YAML file linting | CLI invocation in `tasks.py` |
| **djlint** | Django template linting | `pyproject.toml [tool.djlint]` |
| **djhtml** | Django template auto-formatting | CLI invocation in `tasks.py` |
| **pymarkdownlnt** | Markdown linting | `pyproject.toml [tool.pymarkdown]` |
| **Towncrier** | Changelog / release notes | `pyproject.toml [tool.towncrier]` |
### Running the Full Lint Suite
## Ruff
### What Ruff checks
| Rule prefix | What it catches |
|---|---|
| `F`, `E`, `W` | Pyflakes / pycodestyle (unused imports, undefined names, etc.) |
| `I` | isort import ordering |
| `D` | pydocstyle (missing / malformed docstrings) |
| `S` | bandit (security: hardcoded passwords, SQL injection, etc.) |
### Key Ruff settings
- **Line length**: `120` (not the default 88). Override in code with `# noqa: E501` if absolutely necessary, but prefer wrapping.
- **Google docstring convention** — the project uses Google-style docstrings.
- **D401 (imperative mood first line) is ignored** — the team does not require this style.
- **D documents not required** for migrations or test files (`per-file-ignores`).
- **`--fix`** is safe to run in CI or locally; ruff will auto-fix everything it can.
### Formatting with Ruff
## Pylint
### Notable Pylint settings
- **`no-docstring-rgx`**: `_`-prefixed methods, `test_`-prefixed functions, and `Meta` inner classes are exempt from docstring requirements. This aligns with the `ruff` `D` rule exemptions.
- **TODO comments**: `FIXME` and `XXX` are permitted and do not fail the build.
- **Disabled checks**: `line-too-long` (handled by Ruff), `too-many-positional-arguments` (Django signals often require many args), and three Nautobot-specific `nb-*` codes.
- **Django-aware**: `pylint_django` and `pylint_nautobot` plugins suppress false positives from Django ORM patterns.
### Running Pylint
### Migrations Pylint (if migrations exist)
- `fatal` — new model fields without defaults
- `new-db-field-with-default` — missing callable defaults
- `missing-backwards-migration-callable`
## Docstrings
- **Convention**: Google style (set in `ruff [tool.ruff.lint.pydocstyle]`)
- **Required on**: all public modules, classes, methods, and functions
- **Not required on**: private helpers (`_func`), test functions (`test_*`), inner `Meta` classes
- **D401 ignored**: first line imperative mood is not enforced
## Naming Conventions
| Object | Convention | Example |
|---|---|---|
| Modules | `snake_case.py` | `nautobot_app_mcp_server/__init__.py` |
| Classes | `PascalCase` | `NautobotAppMcpServerConfig` |
| Functions / variables | `snake_case` | `is_truthy`, `compose_command_tokens` |
| Constants | `SCREAMING_SNAKE_CASE` | `LOG_LEVEL`, `NAUTOBOT_VER` |
| Private helpers | `_leading_underscore` | `_await_healthy_container()` |
| Django settings | `SCREAMING_SNAKE` inherited from Nautobot | `PLUGINS`, `DATABASES`, `MIDDLEWARE` |
| Config variables (invoke) | `snake_case` | `compose_dir`, `compose_files`, `nautobot_ver` |
| Package name | `snake_case` | `nautobot_app_mcp_server` |
| App `name` in config | `snake_case` | `"nautobot_app_mcp_server"` |
| App `base_url` | `kebab-case` or `slug` | `"mcp-server"` |
### `NautobotAppConfig` fields
## Imports & Ordering
## Error Handling
### Raising errors in `tasks.py`
### Raising errors in app code
### `warn=True` in invoke task runners
## Type Hints
- Use `from __future__ import annotations` (PEP 563) to avoid forward-reference string quotes.
- Use `# type: ignore` comments for third-party stubs that don't type cleanly (seen in `development/app_config_schema.py`).
- Pylint `init-hook` loads Nautobot before scanning so type inference works across the codebase.
## Logging
## Django App Structure (No Models)
- `nautobot_app_mcp_server/__init__.py` — `NautobotAppMcpServerConfig`
- `nautobot_app_mcp_server/tests/__init__.py` — test package marker
## Changelog / Release Notes
| Directory | Fragment type | Example filename |
|---|---|---|
| `changes/added/` | New feature | `42.added.md` |
| `changes/changed/` | Behavior change | `42.changed.md` |
| `changes/fixed/` | Bug fix | `42.fixed.md` |
| `changes/removed/` | Removed feature | `42.removed.md` |
| `changes/breaking/` | Breaking change | `42.breaking.md` |
| `changes/deprecated/` | Deprecation notice | `42.deprecated.md` |
| `changes/security/` | Security fix | `42.security.md` |
| `changes/documentation/` | Docs-only change | `42.documentation.md` |
| `changes/dependencies/` | Dependency change | `42.dependencies.md` |
| `changes/housekeeping/` | Internal housekeeping | `42.housekeeping.md` |
### Fragment file format
- One entry per line; multiple lines in the same file = multiple release note entries.
- Fragment files are **consumed** by Towncrier during release and deleted.
- Commit messages follow conventional format: `type: description` (e.g., `added: implement MCP tool registry`).
## Git Workflow
- **Branches**: `feature/...`, `fix/...`, `docs/...`
- **Commits**: conventional format — `type: description`
- **Before pushing**: run `poetry run invoke tests`
- **Before opening PR**: run `poetry run invoke lint` (includes ruff, djlint, yamllint, markdownlint, pylint, mkdocs)
- **PRs must not break existing tests** or reduce coverage.
## Docker / Development Environment
- **Python package manager**: Poetry exclusively. **Never use `pip`** directly.
- **Dev tools**: all run via `poetry run invoke <task>` or `poetry run <tool>`.
- **`VIRTUAL_ENV=/usr`** is set in WSL shell profiles — always `unset VIRTUAL_ENV` before Poetry commands.
- **Virtualenv**: created in-project at `.venv/` (`poetry config virtualenvs.in-project true`).
## No-DB Model Pattern
- `required_settings = []` and `default_settings = {}` in `NautobotAppConfig`
- `searchable_models = []`
- `migrations/` directory does not exist (no `makemigrations` output)
- `check_migrations` task in CI will pass trivially
- If migrations are ever needed in the future, use `invoke makemigrations nautobot_app_mcp_server`
## Code Quality Non-Negotiables
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## 1. What This App Actually Is
```
```
## 2. Design Pattern: Embedded Protocol Adapter
| Approach | Pros | Cons |
|---|---|---|
| External MCP server calling REST API | Simpler deployment | Extra network hop, no direct ORM access |
| **Embedded in Django process (this app)** | Direct ORM, permissions integration, no extra port | Couples MCP lifecycle to Django |
| Option B: Separate gunicorn worker on port 9001 | Simpler deployment, separate process | Requires separate startup, different URL |
```python
```
## 3. Layer-by-Layer Data Flow
### Layer 1 — Entry Point (Django → MCP)
```
```
```python
```
### Layer 2 — Authentication
```
```
### Layer 3 — Tool Registry (In-Memory Singleton)
```
```
```python
```
```
```
### Layer 4 — Tool Registration Lifecycle
```
```
```python
```
```python
```
### Layer 5 — Third-Party Tool Registration API
```python
```
### Layer 6 — Tool Executor (Sync → Async Bridge)
```python
```
### Layer 7 — Pagination and Summarization
```python
```
```python
```
### Layer 8 — Session State (Per-Conversation Scoping)
```python
```
```python
```
## 4. Key Abstractions
| Abstraction | File | Purpose |
|---|---|---|
| `NautobotAppMcpServerConfig` | `nautobot_app_mcp_server/__init__.py` | Nautobot plugin entry point |
| `MCPToolRegistry` | `nautobot_app_mcp_server/mcp/registry.py` | Thread-safe in-memory tool registry singleton |
| `ToolDefinition` | `nautobot_app_mcp_server/mcp/registry.py` | Dataclass describing one tool |
| `MCPSessionState` | `nautobot_app_mcp_server/mcp/session.py` | Per-conversation enabled-scopes/searches state |
| `PaginatedResult` | `nautobot_app_mcp_server/mcp/tools/pagination.py` | Cursor page + optional summary |
| `register_mcp_tool()` | `nautobot_app_mcp_server/mcp/__init__.py` | Public API for third-party apps |
| `get_user_from_request()` | `nautobot_app_mcp_server/mcp/auth.py` | Extract Nautobot user from request auth |
## 5. Entry Points
### Django Plugin Entry
```
```
### MCP HTTP Request Entry
```
```
### CLI / Development Entry
```
```
## 6. Permissions Model
```
```
## 7. Out of Scope for V1
| Feature | Reason |
|---|---|
| Write tools (create/update/delete) | Focus on read-only v1 |
| MCP `resources` or `prompts` endpoints | Tools first |
| Redis session backend | In-memory sessions sufficient for v1 |
| Tool-level field permissions | Deferred |
| Streaming (SSE rows) | Cursor pagination handles memory |
## 8. Influences and Source Patterns
| Source | Pattern Reused |
|---|---|
| `netnam-cms-core/models/querysets.py` | `for_list_view()` / `for_detail_view()` queryset builder patterns |
| `notebooklm-mcp-cli` | FastMCP + decorator registry pattern |
| Nautobot core plugin architecture | `NautobotAppConfig`, `post_migrate` signal timing |
| Nautobot `NautobotModelViewSet` | Cursor pagination with `limit` capping |
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
