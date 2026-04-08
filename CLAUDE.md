# Nautobot App MCP Server

Nautobot App exposing a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server as a **standalone FastMCP process** on port 8005. AI agents (Claude Code, Claude Desktop) interact with Nautobot data via MCP tools.

- **Repo:** https://github.com/latuannetnam/nautobot-app-mcp-server
- **Python:** >=3.10, <3.15 | **Nautobot:** >=3.0.0, <4.0.0
- **Version:** v1.2.0 (shipped 2026-04-07)
- **This app has no Django database models** (no `models.py`, `filters.py`, `forms.py`, `api/`, `migrations/`)

---

## Commands

All commands: `poetry run <command>` or `poetry shell`. Always `unset VIRTUAL_ENV` first in WSL.

```bash
# Dev
unset VIRTUAL_ENV && poetry run invoke start     # Docker Compose: Nautobot 8080 + MCP 8005
unset VIRTUAL_ENV && poetry run invoke cli       # shell into running container
unset VIRTUAL_ENV && poetry run invoke build    # rebuild image (after poetry.lock change)

# Tests
unset VIRTUAL_ENV && poetry run invoke unittest         # unit tests
unset VIRTUAL_ENV && poetry run invoke unittest --coverage  # with coverage
unset VIRTUAL_ENV && poetry run invoke tests          # full CI pipeline (linters + tests)

# Linting
unset VIRTUAL_ENV && poetry run invoke ruff [--fix]   # PEP 8, isort, flake8, bandit
unset VIRTUAL_ENV && poetry run invoke pylint        # must stay 10.00/10
unset VIRTUAL_ENV && poetry run invoke djlint        # djlint + djhtml
unset VIRTUAL_ENV && poetry run invoke mkdocs        # build docs

# DB
bash scripts/reset_dev_db.sh --import   # reset + import cached data (most common)
bash scripts/reset_dev_db.sh --all      # full pipeline: reset → fetch → import

# UAT (from host, hits MCP server on port 8005)
python scripts/test_mcp_simple.py       # 8 smoke tests P-01–P-08
python scripts/run_mcp_uat.py          # 37 full UAT tests T-01–T-36
```

**Inside container for MCP tests:**
```bash
docker exec -it nautobot-app-mcp-server-nautobot-1 /bin/bash
cd /source
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests
```

**Debug imports:**
```bash
python -c 'from mcp.types import Tool; print(Tool)'
python -c 'from fastmcp.server.context import Context; print(Context)'
```

---

## Environment Setup

```bash
cp development/creds.env.example development/creds.env
# Edit development/creds.env with your secrets
```

Services started by `invoke start`:

| Service | URL |
|---|---|
| Nautobot | <http://localhost:8080> |
| MCP server | <http://localhost:8005/mcp/> (FastMCP HTTP transport) |
| Container prefix | `nautobot-app-mcp-server-*` |

Docker compose files live in `development/`. DB user is `nautobot` (from `NAUTOBOT_DB_USER` in `development.env`).

---

## Code Quality (Non-Negotiables)

- **Pylint: 10.00/10.** PRs that drop the score must fix before merging.
- **`invoke tests` must pass** before pushing.
- **`ruff --fix` is safe** — auto-fixes what it can.
- **Line length: 120.** Wrap with `# noqa: E501` only when necessary.
- **Docstring convention:** Google style; D401 ignored; D docs not required for migrations/test files.
- **`FIXME` and `XXX` permitted** in TODO comments.
- **`from __future__ import annotations`** (PEP 563) for type hints.
- **Naming:** `snake_case.py`, `PascalCase`, `snake_case` functions, `SCREAMING_SNAKE_CASE` constants.

---

## Architecture

```
AI Agent → HTTP POST localhost:8005/mcp/
  → FastMCP StreamableHTTPSessionManager
    → ScopeGuardMiddleware (enforces session scope at tool-call time)
      → get_user_from_request() [reads Authorization: Token header]
        → Tool function [tools/core.py]
          → Django ORM via sync_to_async(..., thread_sensitive=True)
```

**Entry points:**

| Command | Purpose | Transport |
|---|---|---|
| `nautobot-server start_mcp_server` | Production | `mcp.run(transport="http")` |
| `nautobot-server start_mcp_dev_server` | Dev | `uvicorn` + auto-reload |

**Tool registration flow:** `ready()` → writes `tool_registry.json` → MCP server reads it at startup → side-effect import fires `@register_tool()` → `register_all_tools_with_mcp()` registers each tool via `mcp.tool(func, output_schema=None)`.

**Session state** (FastMCP MemoryStore, keyed `session_id:mcp:*`):
- `mcp:cached_user` — User PK, per-session
- `mcp:enabled_scopes` — list of enabled scopes
- `mcp:enabled_searches` — list of search terms

**Progressive disclosure:** Core tools (`tier="core"`) always visible. App-tier tools require `mcp_enable_tools` first, then `ScopeGuardMiddleware` blocks unauthorized calls.

**13 tools total:** 3 session + 10 core read. All registered via `register_mcp_tool()` in `mcp/tools/__init__.py`.

---

## Auth

- Token: **40-char hex, no prefix** (NOT `nbapikey_<hex>`)
- Header: `Authorization: Token <key>` on MCP request
- Cache: `ctx.set_state("mcp:cached_user", str(user.pk))` per FastMCP session
- Missing/invalid token → `AnonymousUser` (empty querysets via `.restrict()`)
- **All ORM calls must use `sync_to_async(..., thread_sensitive=True)`** — FastMCP thread pool ≠ Django's main thread; skipping `thread_sensitive=True` causes "Connection not available" errors.

---

## Gotchas

| Issue | Fix |
|---|---|
| Source changes not picked up | Changes are immediate (volume-mounted at `/source`); rebuild only for deps |
| `VIRTUAL_ENV=/usr` errors | Always `unset VIRTUAL_ENV` before Poetry commands in WSL |
| `invoke tests` fails after tests pass | `ruff format .` inside container |
| "Connection not available" in async tools | Use `sync_to_async(..., thread_sensitive=True)` for ALL ORM calls |
| Cursor separator in `search_by_name` | Uses `base64(f"{model}@{pk}")` — `@` used because UUIDs contain dots. List tools use plain `base64(pk)` (no separator) |
| `outputSchema` validation error | Always pass `output_schema=None` to `mcp.tool()` |
| `ctx.request_context` is `None` during HTTP tool calls | Use `get_http_request()` from `fastmcp.server.dependencies` |
| `tool_registry.json` not written at startup | `post_migrate` doesn't fire in standalone process — plugin writes it at `ready()` instead |
| Multi-worker deployments | Not supported (in-memory sessions); use `--workers 1`; Redis deferred to v2.0 |

---

## GSD Workflow

Use GSD commands for all implementation work. No direct repo edits outside a GSD workflow unless user explicitly asks.

| Command | Use when |
|---|---|
| `/gsd-do` | Dispatch freeform task to the right GSD command |
| `/gsd-debug` | Investigate and fix bugs (scientific method) |
| `/gsd-execute-phase` | Execute planned phase work |
| `/gsd-quick` | Small fixes, doc updates, ad-hoc tasks |

---

## Key Files

```
nautobot_app_mcp_server/
├── __init__.py              # ready() writes tool_registry.json
├── mcp/
│   ├── __init__.py          # register_mcp_tool() / register_tool() — public plugin API
│   ├── commands.py          # create_app() factory — standalone FastMCP build
│   ├── registry.py          # MCPToolRegistry singleton + ToolDefinition dataclass
│   ├── auth.py              # get_user_from_request()
│   ├── middleware.py        # ScopeGuardMiddleware
│   ├── session_tools.py    # Session tools + _list_tools_handler
│   ├── tools/
│   │   ├── __init__.py      # side-effect: @register_tool fires on import
│   │   ├── core.py          # 10 read tools
│   │   ├── pagination.py    # PaginatedResult
│   │   └── query_utils.py   # Query-building helpers
│   └── tests/               # Unit tests
├── management/commands/
│   ├── start_mcp_server.py
│   ├── start_mcp_dev_server.py
│   └── import_production_data.py
├── development/             # Docker Compose + env files
├── scripts/                  # test_mcp_simple.py, run_mcp_uat.py, reset_dev_db.sh
└── docs/dev/                # Developer docs
```
