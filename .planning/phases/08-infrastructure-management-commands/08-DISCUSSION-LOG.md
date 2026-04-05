# Phase 8: Infrastructure — Management Commands - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 08-infrastructure-management-commands
**Areas discussed:** DB validation query, create_app() signature, dev server reload strategy

---

## DB Validation Query

| Option | Description | Selected |
|--------|-------------|----------|
| `connection.ensure_connection()` | Django's built-in connection pool check — generic, no Nautobot model dependency | ✓ |
| `extras_jobresult` query | Query Nautobot's JobResult model — more specifically Nautobot, but requires extras app | |
| `nautobot.setup()` call | Try to call nautobot.setup() to see if it succeeds | |

**User's choice:** `connection.ensure_connection()` (recommended default)
**Notes:** Generic and clean — no Nautobot model dependency. Fast, catches network-level failures. Using the simplest possible Django check rather than a specific Nautobot model query.

---

## `create_app()` Signature

| Option | Description | Selected |
|--------|-------------|----------|
| Accept host/port, return FastMCP instance | production calls `.run()`, dev calls `uvicorn.run(mcp.http_app)` | ✓ |
| Return (FastMCP, ASGI callable) tuple | Caller unpacks both | |
| Accept config path, return just the ASGI callable | Simpler but less flexible | |

**User's choice:** Accept host/port, return FastMCP instance (recommended default)
**Notes:** `create_app(host, port)` → returns FastMCP instance. Production: `mcp.run(transport="http")` (blocks forever). Dev: `uvicorn.run(mcp.http_app(), host, port, reload=True)`. `nautobot.setup()` called before any model imports (satisfies known pitfall PITFALL #1). DB validation via `connection.ensure_connection()` called first.

---

## Dev Server Reload Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| `nautobot_app_mcp_server/` only | Watch only the MCP server package — faster restart, matches changed files | ✓ |
| Whole `/source` project root | Simpler config, catches all changes | |
| Both (nautobot_app_mcp_server/ + development/) | Additional coverage | |

**User's choice:** `nautobot_app_mcp_server/` only (recommended default)
**Notes:** Scoped reload avoids unnecessary restarts when unrelated files change during dev. Config changes (env vars, docker-compose) require manual restart anyway.

---

## Claude's Discretion

- Exact `RuntimeError` message wording for DB validation failures
- Whether `start_mcp_server` accepts `--host`/`--port` CLI arguments
- Whether `start_mcp_dev_server` accepts `--reload` toggle
- How to handle `nautobot.setup()` failures beyond DB connectivity

## Deferred Ideas

None — discussion stayed within phase scope.

