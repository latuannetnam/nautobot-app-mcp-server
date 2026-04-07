# CLAUDE.md — Nautobot App MCP Server

Project-specific instructions for Claude Code working in this repository.

---

## Project Overview

**nautobot-app-mcp-server** is a Nautobot App that exposes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server as a **standalone FastMCP process** (separate from Nautobot's Django process). AI agents (Claude Code, Claude Desktop) interact with Nautobot data via MCP tools running on port 8005.

- **Repository:** https://github.com/latuannetnam/nautobot-app-mcp-server
- **License:** Apache-2.0
- **Python:** >=3.10, <3.15 (dev runtime: 3.12)
- **Nautobot:** >=3.0.0, <4.0.0
- **Current version:** v1.2.0 (shipped 2026-04-07)

---

## Poetry — Critical Rules

This project uses **Poetry exclusively**. Never use `pip` directly.

- **`VIRTUAL_ENV=/usr`** is set in WSL shell profiles — **always `unset VIRTUAL_ENV`** before Poetry commands.
- Virtualenv: `.venv/` in project root (via `poetry config virtualenvs.in-project true`).
- **All commands:** `poetry run <command>` or `poetry shell`.

### Common Commands

```bash
# Development
unset VIRTUAL_ENV && poetry run invoke start          # start Docker Compose (Nautobot 8080 + MCP 8005)
unset VIRTUAL_ENV && poetry run invoke cli            # shell into running container
unset VIRTUAL_ENV && poetry run invoke build         # rebuild Docker image (after poetry.lock change)

# Testing (run inside container)
docker exec -it nautobot-app-mcp-server-nautobot-1 /bin/bash
cd /source
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests    # MCP tests only
poetry run nautobot-server test nautobot_app_mcp_server              # all app tests

# From host
unset VIRTUAL_ENV && poetry run invoke unittest        # unit tests
unset VIRTUAL_ENV && poetry run invoke unittest --coverage  # with coverage
unset VIRTUAL_ENV && poetry run invoke tests           # full CI pipeline (linters + tests)

# Linting
unset VIRTUAL_ENV && poetry run invoke ruff [--fix]    # ruff: PEP 8, isort, flake8, bandit
unset VIRTUAL_ENV && poetry run invoke pylint         # pylint (must stay 10.00/10)
unset VIRTUAL_ENV && poetry run invoke djlint         # djlint + djhtml
unset VIRTUAL_ENV && poetry run invoke yamllint       # YAML files
unset VIRTUAL_ENV && poetry run invoke mkdocs         # build docs

# UAT (from host, hits running MCP server on port 8005)
python scripts/test_mcp_simple.py
python scripts/run_mcp_uat.py
```

---

## Development Environment

Docker Compose files in `development/`. Start with `poetry run invoke start`. Two services:

- Nautobot: <http://localhost:8080>
- MCP server: <http://localhost:8005/mcp/> (FastMCP HTTP transport)

First time setup:
```bash
cp development/creds.env.example development/creds.env
# Edit development/creds.env with your secrets
```

### Docker Compose Files

`invoke start` loads all compose files from `development/`:

- `docker-compose.dev.yml` — Nautobot service (port 8080)
- `docker-compose.mcp.yml` — MCP server service (port 8005, auto-started by `invoke start`)

**Container naming:** `nautobot-app-mcp-server-*` prefix (from project name in `pyproject.toml`).

### Resetting & Importing the Dev DB

```bash
# Interactive menu
bash scripts/reset_dev_db.sh

# CLI shortcuts:
bash scripts/reset_dev_db.sh --reset      # Reset DB only (drop/migrate/superuser)
bash scripts/reset_dev_db.sh --fetch     # Pull from production → JSON cache
bash scripts/reset_dev_db.sh --import    # Reset DB + import cached data (most common)
bash scripts/reset_dev_db.sh --all       # Full pipeline: reset → fetch → import
```

Key notes:

- Docker compose files live in `development/` — use `--project-directory` with `-f` flags.
- DB user is `nautobot` (from `NAUTOBOT_DB_USER` in `development.env`).
- Pass `--cache-dir /source/import_cache` (volume-mounted from host's `import_cache/`).
- Fresh DB has no `LocationType` rows — `import_production_data.py` auto-creates a default `Region` type.

---

## Testing Workflow

**All tests run inside the Docker container** where Nautobot and all dependencies are installed.

```bash
# Start and access container
unset VIRTUAL_ENV && poetry run invoke start
docker exec -it nautobot-app-mcp-server-nautobot-1 /bin/bash
```

**Debug import errors** (inside container):
```bash
python -c 'import mcp.server; print([x for x in dir(mcp.server) if not x.startswith("_")])'
python -c 'from fastmcp.server.context import Context; print(Context)'
python -c 'from mcp.types import Tool; print(Tool)'
```

**UAT tests** (run from host, NOT inside container):
```bash
python scripts/test_mcp_simple.py       # 8 quick smoke tests (P-01–P-08)
python scripts/run_mcp_uat.py           # 37 full UAT tests (T-01–T-36)
```

**Key Gotchas**

| Issue | Cause | Fix |
|---|---|---|
| Source changes not picked up | Source is volume-mounted at `/source` | Changes are immediate; rebuild only for deps |
| `VIRTUAL_ENV=/usr` errors | WSL inherited env var | Always `unset VIRTUAL_ENV` before Poetry |
| Tests pass but `invoke tests` fails | `ruff format` issues | `ruff format .` inside container |
| "Connection not available" in async tools | Django ORM called without `sync_to_async` | Use `sync_to_async(..., thread_sensitive=True)` |

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

This app has **no Django database models**. Removed: `models.py`, `filters.py`, `forms.py`, `tables.py`, `api/`, `navigation.py`, `migrations/`.

---

## Git Workflow

- **Branches:** `feature/...`, `fix/...`, `docs/...`
- **Commits:** conventional format — `type: description`
- **Before pushing:** `poetry run invoke tests`
- **Before opening PR:** `poetry run invoke ruff [--fix]`, `poetry run invoke pylint`

---

## GSD Workflow Enforcement

Use GSD commands for all implementation work. Do not make direct repo edits outside a GSD workflow unless the user explicitly asks.

GSD commands available from `.claude/skills/` of current project:

| Command | Skill | When to use |
|---|---|---|
| `/gsd-do` | gsd-do | Dispatch any freeform task to the right GSD command |
| `/gsd-debug` | gsd-debug | Investigate and fix bugs using scientific method |
| `/gsd-execute-phase` | gsd-execute-phase | Execute planned phase work with wave-based subagents |
| `/gsd-complete-milestone` | gsd-complete-milestone | Archive milestone, update docs, git tag |
| `/gsd-new-milestone` | gsd-new-milestone | Start next milestone: questioning → research → requirements |
| `/gsd-quick` | gsd-quick | Small fixes, doc updates, ad-hoc tasks |

---

## Project Structure

```
nautobot_app_mcp_server/
│   ├── __init__.py                # Config: ready() writes tool_registry.json
│   ├── urls.py                   # Empty (no URL routing — v1.2.0 deleted embedded endpoint)
│   ├── mcp/
│   │   ├── __init__.py           # register_mcp_tool() / register_tool() — public plugin API
│   │   ├── commands.py           # create_app() factory — standalone FastMCP build
│   │   ├── registry.py           # MCPToolRegistry singleton + ToolDefinition dataclass
│   │   ├── auth.py               # get_user_from_request() — Token auth, ctx.get_state cache
│   │   ├── middleware.py         # ScopeGuardMiddleware — enforces scope at tool-call time
│   │   ├── session_tools.py      # Session state tools + _list_tools_handler (progressive UX)
│   │   ├── schema.py             # func_signature_to_input_schema()
│   │   ├── tool_registry.json    # Written by ready() at plugin startup (cross-process)
│   │   ├── tools/
│   │   │   ├── __init__.py       # Side-effect: imports all tools → @register_tool fires
│   │   │   ├── core.py           # 10 read tools (device, interface, ipaddress, prefix, etc.)
│   │   │   ├── pagination.py     # PaginatedResult: base64(pk) cursor, LIMIT_DEFAULT=25, LIMIT_MAX=1000
│   │   │   └── query_utils.py    # Query-building helpers, field name fixes for Nautobot 3.x
│   │   └── tests/                # Unit tests (auth, session, core tools, commands, signal)
│   ├── management/
│   │   └── commands/
│   │       ├── start_mcp_server.py      # Production entry point: mcp.run(transport="http")
│   │       ├── start_mcp_dev_server.py # Dev entry point: uvicorn with auto-reload
│   │       └── import_production_data.py
├── development/
│   ├── docker-compose.dev.yml    # Nautobot service (port 8080)
│   ├── docker-compose.mcp.yml    # MCP server service (port 8005, starts with invoke start)
│   └── *.env                     # Environment config
├── scripts/
│   ├── test_mcp_simple.py        # 8 quick smoke tests P-01–P-08 (run from host)
│   ├── run_mcp_uat.py            # 37 full UAT tests (run from host)
│   └── reset_dev_db.sh           # DB reset + production import
├── docs/dev/
│   ├── patch_fastmcp_issue.md    # FastMCP/MCP SDK outputSchema conflict analysis
│   ├── import_and_uat.md         # Dev DB import and UAT workflow
│   └── *.md                      # Other developer docs
├── tasks.py                      # Invoke automation
├── pyproject.toml
└── changes/                     # Towncrier release note fragments
```

---

## MCP Server Architecture (v1.2.0 — Standalone Process)

### Architecture Overview

The MCP server runs as a **standalone FastMCP process** on port 8005, separate from Nautobot's Django process. This is Option B from the v1.2.0 refactor.

```
AI Agent (Claude Code)
  → HTTP POST http://localhost:8005/mcp/ (MCP protocol)
    → FastMCP StreamableHTTPSessionManager
      → ScopeGuardMiddleware (enforces session scope at tool-call time)
        → Auth guard: get_user_from_request() [ctx: ToolContext]
          → Tool function [tools/core.py]
            → Django ORM via sync_to_async(thread_sensitive=True)
```

### Management Commands

| Command | Purpose | Transport |
|---|---|---|
| `nautobot-server start_mcp_server` | Production entry point | `mcp.run(transport="http")` |
| `nautobot-server start_mcp_dev_server` | Dev entry point | `uvicorn` + auto-reload |

`invoke start` automatically starts the MCP server via `docker-compose.mcp.yml` (no separate command needed).

### Tool Registration Flow

```
Plugin startup (NautobotAppMcpServerConfig.ready())
  → Writes tool_registry.json (cross-process discovery)

MCP server startup (create_app() in commands.py)
  → nautobot.setup() — bootstrap Django
  → Reads tool_registry.json (validates cross-process discovery)
  → Side-effect import: mcp/tools/__init__.py
    → @register_tool() fires → populates MCPToolRegistry
  → register_all_tools_with_mcp(mcp)
    → mcp.tool(func, output_schema=None) for each tool
      → Fixes FastMCP/MCP SDK outputSchema conflict
  → mcp.add_middleware(ScopeGuardMiddleware())
```

### Session State (v1.2.0 — FastMCP MemoryStore)

Session state is stored in FastMCP's in-memory `MemoryStore`, keyed by `session_id:mcp:*`. No monkey-patching required.

| Key | Value | Lifetime |
|---|---|---|
| `mcp:cached_user` | User PK as string | Per-session |
| `mcp:enabled_scopes` | `list[str]` of enabled scopes | Per-session |
| `mcp:enabled_searches` | `list[str]` of search terms | Per-session |

### Auth Flow (v1.2.0)

```
MCP request → FastMCP ToolContext
  → get_user_from_request(ctx)
    → Extract Authorization: Token <40-char-hex> header
    → Check ctx.get_state("mcp:cached_user")
      → Cache hit: re-fetch user from DB (validates deletion/deactivation)
      → Cache miss: Token.objects.get(key=...) → User
    → ctx.set_state("mcp:cached_user", str(user.pk))
    → Return User or AnonymousUser
```

All ORM calls wrapped in `sync_to_async(..., thread_sensitive=True)` because FastMCP runs async tools in a thread pool where Django's default DB connection (bound to the main thread) is not available.

### Progressive Disclosure (Scope Guard)

| Layer | What it does | File |
|---|---|---|
| `mcp_list_tools` tool | Returns filtered tool manifest by reading session state | `session_tools.py` |
| `ScopeGuardMiddleware` (Security) | Blocks tool-call for disabled scopes | `middleware.py` |

Core tools (`tier="core"`) always pass both layers. App-tier tools require their scope to be enabled first via `mcp_enable_tools`.

### Key Design Decisions

| Aspect | Decision | Rationale |
|---|---|---|
| Standalone process (Option B) | MCP server is separate from Django | Cleaner separation; no WSGI→ASGI bridge; production-realistic |
| `tool_registry.json` | Plugin writes it at `ready()`, MCP reads at startup | `post_migrate` never fires in standalone process |
| `output_schema=None` | Passed to `mcp.tool()` in `register_all_tools_with_mcp()` | Suppresses FastMCP auto-derivation; prevents MCP SDK output validation error |
| Session state via FastMCP MemoryStore | `ctx.get_state()` / `ctx.set_state()` | Official FastMCP 3.2.0 API; no monkey-patching needed |
| `@` cursor separator for `search_by_name` | `base64(f"{model}@{pk}")` for search cursor | UUIDs contain dots — `.` splits UUID at wrong position. List tools use `base64(pk)` (no separator needed) |
| Auth token from FastMCP headers | `get_http_request()` reads `Authorization: Token` | Works even when `ctx.request_context` is None during StreamableHTTPSessionManager calls |
| `sync_to_async(..., thread_sensitive=True)` | All ORM calls in async tools | FastMCP thread pool ≠ Django's main thread; `thread_sensitive=True` routes to the correct DB connection |
| `--workers 1` documented | In-memory sessions | Multi-worker requires Redis backend (deferred to v2.0) |

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
    output_schema: dict | None = None,
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
- Source: `Authorization: Token <key>` header on **MCP request**
- Cache: `ctx.set_state("mcp:cached_user", str(user.pk))` — per FastMCP session
- On missing/invalid token: returns `AnonymousUser` (empty querysets via `.restrict()`); logs `WARNING` (missing) or `DEBUG` (invalid)
- **CRITICAL:** All ORM calls in `get_user_from_request()` use `sync_to_async(..., thread_sensitive=True)` — not doing this causes "Connection not available" errors

---

## FastMCP 3.x / MCP SDK Gotchas

| Issue | Location | Detail |
|---|---|---|
| `outputSchema` validation error | `register_all_tools_with_mcp()` | FastMCP auto-derives `output_schema={"type": "object"}` from return type. MCP SDK `handle_call_tool()` errors if structured content is missing. Fix: pass `output_schema=None` to `mcp.tool()` (uses FastMCP `NotSet` sentinel to skip derivation) |
| Progressive disclosure via `mcp_list_tools` tool | `session_tools.py` | Not via FastMCP middleware override. The `mcp_list_tools` tool (registered via `mcp.tool()`) reads session state and returns filtered tool lists. `ScopeGuardMiddleware` blocks calls to disabled scopes as a security backstop |
| `ServerSession` is NOT dict-like | N/A | v1.2.0 uses `ctx.get_state()`/`ctx.set_state()` instead |
| Django ORM not ready at import time | `commands.py` | `create_app()` calls `nautobot.setup()` before any ORM access |
| `StreamableHTTPSessionManager` needs lifespan | `mcp.http_app()` | Handled by FastMCP's built-in lifespan context |
| `_cached_user` is per-session | `auth.py` | Stored via `ctx.set_state("mcp:cached_user", str(pk))` — FastMCP MemoryStore is per-session |
| `ctx.request_context` is `None` during HTTP tool calls | `auth.py` | Use `get_http_request()` from `fastmcp.server.dependencies` which reads FastMCP's `_current_http_request` ContextVar directly |
| Cursor separator is `@` (search_by_name only) | `query_utils.py` | `search_by_name` encodes `base64(f"{model}@{pk}")` — `@` is used because neither model names nor UUIDs contain `@`. List tools use `base64(pk)` with no separator. Previously used `.` which split UUIDs at the wrong position (T-25 fix) |

---
