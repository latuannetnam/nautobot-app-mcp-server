# Phase 8: Infrastructure — Management Commands - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Two Django management commands that serve as standalone FastMCP server entry points — production (`start_mcp_server`) and development (`start_mcp_dev_server`). These are the Phase 8 deliverables. Tool registration (Phase 9) and everything after depends on these being in place. DB validation, environment config, and all related mechanics are scoped here.

</domain>

<decisions>
## Implementation Decisions

### P1-01: `start_mcp_server` Production Command
- **D-01:** Management command name: `start_mcp_server`
- **D-02:** Entry point flow: `nautobot.setup()` → register tools → `mcp.run(transport="sse")` (blocks forever)
- **D-03:** `nautobot.setup()` called at the **top** of the command entry point, before any relative imports — satisfies PITFALL #1 (RuntimeError: Django wasn't set up yet)
- **D-04:** Production server binds to `0.0.0.0:8005`

### P1-02: `start_mcp_dev_server` Development Command
- **D-05:** Management command name: `start_mcp_dev_server`
- **D-06:** Uses `create_app()` factory + `uvicorn.run(reload=True)` with file-watch restart
- **D-07:** Dev server binds to `127.0.0.1:8005` (localhost only — no external exposure in dev)
- **D-08:** Reload watch scoped to `nautobot_app_mcp_server/` directory only — not the entire project root. Faster restart, matches the files that change during MCP server development.

### P1-03: `create_app()` Factory
- **D-09:** Signature: `create_app(host: str = "0.0.0.0", port: int = 8005) -> FastMMC` (where `MMC` is `FastMCP`)
- **D-10:** DB validation: `from django.db import connection; connection.ensure_connection()` — called first, before `nautobot.setup()`. Generic Django check, no Nautobot model dependency.
- **D-11:** On DB failure: raises `RuntimeError("Database connectivity check failed: <detail>")`
- **D-12:** After DB check: `import nautobot; nautobot.setup()` — bootstraps Django ORM for standalone process
- **D-13:** Returns a configured `FastMCP` instance with `host`/`port` passed to the constructor

### P1-04: Environment Variable Configuration
- **D-14:** `create_app()` reads `NAUTOBOT_CONFIG` from environment via `os.environ.get("NAUTOBOT_CONFIG")` — sets Django settings module before `nautobot.setup()`
- **D-15:** `PLUGINS_CONFIG` read from environment — used to configure Nautobot's `PLUGINS_CONFIG` dict if needed
- **D-16:** Default: `NAUTOBOT_CONFIG = "nautobot_config"` (resolved relative to cwd or via `sys.path`)

### Claude's Discretion
- Exact `RuntimeError` message wording
- Whether `start_mcp_server` accepts `--host`/`--port` CLI arguments (defaults to D-04 values)
- Whether `start_mcp_dev_server` accepts `--reload` toggle or always reloads
- How to handle `nautobot.setup()` failures beyond DB connectivity

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 8 Scope
- `.planning/ROADMAP.md` §Phase 8 — phase goal, 4 requirements (P1-01–P1-04), success criteria, known pitfalls
- `.planning/REQUIREMENTS.md` §v1.2.0 Requirements — P1-01, P1-02, P1-03, P1-04

### Prior Phase Context
- `.planning/phases/07-setup/07-CONTEXT.md` — Phase 7 decisions (docker-compose MCP service, uvicorn dep, upgrade docs)
- `.planning/phases/05-mcp-server-refactor/05-CONTEXT.md` — Phase 5 D-09: `async_to_sync` pattern, D-24: session dict usage
- `.planning/phases/01-mcp-server-infrastructure/01-CONTEXT.md` — Phase 1 D-08: `FastMCP("NautobotMCP", stateless_http=False, json_response=True)` FastMCP constructor config

### Stack & Conventions
- `.planning/codebase/CONVENTIONS.md` — Python naming, docstrings, error handling, management command structure
- `.planning/codebase/STACK.md` — Python 3.12, Poetry, uvicorn, asgiref, Django config from env

### Implementation Reference
- `nautobot_app_mcp_server/management/commands/import_production_data.py` — existing management command as structural template
- `development/nautobot_config.py` — how `NAUTOBOT_CONFIG` env var is used today
- `nautobot_app_mcp_server/__init__.py` — `NautobotAppConfig` pattern (base_url, name)

### Architecture (for FastMCP patterns)
- `.planning/research/ARCHITECTURE.md` — FastMCP `mcp.run()` transport options, `http_app` property (Phase 1 research)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `import_production_data.py` management command: Django `BaseCommand` subclass with `add_arguments()` and `handle()` — use as structural template
- `development/nautobot_config.py`: `os.getenv("NAUTOBOT_CONFIG", ...)` pattern already established
- Phase 5 `server.py` pattern: `nautobot.setup()` is the standard standalone Django bootstrap call

### Established Patterns
- Management commands live in `nautobot_app_mcp_server/management/commands/`
- `from django.core.management.base import BaseCommand` — standard import
- Google-style docstrings required on all public functions/classes (Ruff D rules)
- Error messages use `self.stderr.write(self.style.ERROR(...))` and `sys.exit(1)` pattern (from `import_production_data.py`)

### Integration Points
- `start_mcp_server.py` and `start_mcp_dev_server.py` in `management/commands/`
- `create_app()` is called by both commands — single source of truth for FastMCP instantiation
- Phase 9 tool registration will call `create_app()` or extend it — keep the factory clean and minimal now
- `uvicorn` is already added as explicit dependency in Phase 7 (P0-01)

</code_context>

<specifics>
## Specific Ideas

- "FastMCP `http_app` property returns the Starlette ASGI callable — `uvicorn.run(mcp.http_app, ...)` is the uvicorn pattern"
- Phase 8 focus is purely mechanical — get the server to start and block. No tool registration code needed yet (that's Phase 9).

</specifics>

<deferred>
## Deferred Ideas

**None — all Phase 8 decisions are scoped and captured above.**

</deferred>

---

*Phase: 08-infrastructure-management-commands*
*Context gathered: 2026-04-05*
