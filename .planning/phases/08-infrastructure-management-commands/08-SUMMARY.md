# Phase 8 Summary: Infrastructure — Management Commands

**Executed:** 2026-04-05
**Status:** ✅ Complete
**Commit:** `9215257`

---

## Deliverables

### Files Created

| File | Purpose |
|------|---------|
| `management/commands/start_mcp_server.py` | Production entry point — `mcp.run(transport="http", ...)` blocks forever |
| `management/commands/start_mcp_dev_server.py` | Dev entry point — `uvicorn.run(reload=True)` with hot-reload |
| `mcp/commands.py` | `create_app()` factory — DB check → `nautobot.setup()` → `FastMCP` instance |
| `mcp/tests/test_commands.py` | 2 unit tests: return-type check + DB failure RuntimeError |

### Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Added per-file-ignores for `management/commands/*`: D (docstrings), S104 (bind to all interfaces) |

---

## Requirements Met

| Requirement | Status | Evidence |
|---|---|---|
| **P1-01** `start_mcp_server` production command | ✅ | `management/commands/start_mcp_server.py` with `--host`/`--port`, `nautobot.setup()` at top |
| **P1-02** `start_mcp_dev_server` dev command | ✅ | `management/commands/start_mcp_dev_server.py` with `uvicorn.run(reload=True)`, `127.0.0.1:8005` defaults |
| **P1-03** `create_app()` factory with DB validation | ✅ | `mcp/commands.py` — `connection.ensure_connection()` before `nautobot.setup()`, raises `RuntimeError` on failure |
| **P1-04** Environment variable configuration | ✅ | `NAUTOBOT_CONFIG` and `PLUGINS_CONFIG` read via `os.environ.get()` with docs in docstring |

---

## Key Implementation Decisions

### FastMCP 3.x Breaking Change: `stateless_http` / `json_response`

FastMCP 3.x no longer accepts `stateless_http` or `json_response` in the constructor. These must be passed at run time:

- **Production:** `mcp.run(transport="http", host=..., port=..., stateless_http=False)`
- **Development:** `mcp.http_app(transport="http", stateless_http=False)`

The `create_app()` factory creates a bare `FastMCP("NautobotMCP")` instance (no constructor kwargs).

### Two-Phase Import Pattern

All three files use the same pattern:
1. `NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")` + `os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG`
2. `import nautobot` + `nautobot.setup()`
3. `from django.core.management.base import BaseCommand` + `from nautobot_app_mcp_server.mcp.commands import create_app`

This satisfies P1-01/D-03: `nautobot.setup()` must be called **before** any relative imports of `nautobot_app_mcp_server` modules.

### `reload_dirs` Scoping

`start_mcp_dev_server` uses `Path(__file__).resolve().parents[3] / "nautobot_app_mcp_server"` to compute the package root. This resolves reliably across Docker volume mounts, WSL, and bare Python invocations.

### Phase 9 Integration Point

`create_app()` has a `# STEP 4: Phase 9` comment placeholder. Phase 9 will add `register_all_tools_with_mcp()` call here to wire all MCP tools.

---

## Tests

```bash
poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_commands --keepdb
```

```
Ran 2 tests in 0.014s
OK
```

| Test | Description |
|------|-------------|
| `test_create_app_returns_tuple_of_three` | Verifies `(mcp, host, port)` tuple returned with correct values |
| `test_create_app_db_failure_raises_runtime_error` | Mocks `connection.ensure_connection()` failure; verifies `RuntimeError` with descriptive message |

---

## Linting

| Tool | Result |
|------|--------|
| Ruff | ✅ All checks passed |
| Pylint | ⚠️ `invoke pylint` crashes on this codebase (pre-existing crash on `registry.py`) — tests pass via `nautobot-server test` |

---

## Phase Exit Gate

✅ Both management commands are importable (verified via `docker exec`):
```bash
poetry run nautobot-server start_mcp_server --help
poetry run nautobot-server start_mcp_dev_server --help
```

✅ `create_app()` raises `RuntimeError` when DB is unreachable (verified by unit test)

---

## Next

**Phase 9: Tool Registration Refactor** — `@register_tool` decorator, `register_all_tools_with_mcp()`, `tool_registry.json`, lazy imports.
