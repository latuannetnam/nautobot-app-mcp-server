# Phase 8: Infrastructure — Management Commands — Research

**Researched:** 2026-04-05
**Confidence:** HIGH — all answers verified via installed package source

---

## Research Question 1: `FastMCP(...).run(transport="sse")` — Does it block?

**Answer: Yes, it blocks forever.**

Verified from `fastmcp/server/mixins/transport.py` lines 77–98:

```python
def run(
    self: FastMCP,
    transport: Transport | None = None,
    show_banner: bool | None = None,
    **transport_kwargs: Any,
) -> None:
    """Run the FastMCP server. Note this is a synchronous function."""
    anyio.run(
        partial(
            self.run_async,
            transport,
            show_banner=show_banner,
            **transport_kwargs,
        )
    )
```

`anyio.run()` blocks until the async task completes (which never happens for a server). The `run_async` path calls `uvicorn.Server(config).serve()` (line 303 of the same file), which is an awaitable that resolves only on shutdown. This is the correct production pattern: call it once, and the process runs until killed.

**Key implication for management command design:** `start_mcp_server.py` calls `mcp.run(transport="sse")` and the `handle()` method returns only on SIGTERM/SIGINT. This is correct behavior.

---

## Research Question 2: `FastMCP(...).http_app` — What does it return?

**Answer: `StarletteWithLifespan` — a Starlette ASGI app, callable as `app(scope, receive, send)`.**

Verified from `fastmcp/server/mixins/transport.py` lines 305–365:

```python
def http_app(
    self: FastMCP,
    path: str | None = None,
    ...
    transport: Literal["http", "streamable-http", "sse"] = "http",
    ...
) -> StarletteWithLifespan:
```

The return type is `StarletteWithLifespan`, which inherits from `Starlette` (verified in `fastmcp/server/http.py` line 70: `class StarletteWithLifespan(Starlette)`). `StarletteWithLifespan` IS an ASGI callable — it has `async def __call__(self, scope, receive, send)` from Starlette's base class.

`StarletteWithLifespan` is returned by all three transport modes in `http_app()`:
- `"streamable-http"` → `create_streamable_http_app(...)` returns `StarletteWithLifespan`
- `"http"` → same as above
- `"sse"` → `create_sse_app(...)` returns `StarletteWithLifespan`

**Key implication for management command design:** `create_app()` returns a `StarletteWithLifespan` which is passed to `uvicorn.run()`. `uvicorn.run()` accepts any ASGI app callable as its first argument.

---

## Research Question 3: `uvicorn.run()` API — reload + reload_dirs

**Answer: `uvicorn.run()` accepts `reload=True` and `reload_dirs` as separate arguments.**

Verified from `uvicorn/main.py` lines 486–557:

```python
def run(
    app: ASGIApplication | Callable[..., Any] | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    ...
    reload: bool = False,
    reload_dirs: list[str] | str | None = None,
    reload_includes: list[str] | str | None = None,
    reload_excludes: list[str] | str | None = None,
    reload_delay: float = 0.25,
    ...
) -> None:
```

**Key parameters for Phase 8:**

| Parameter | Type | Notes |
|---|---|---|
| `reload` | `bool` | Default `False` — enable file-watch restart |
| `reload_dirs` | `list[str] \| str \| None` | Directories to watch. Default: CWD. Can be list of paths. |
| `reload_includes` | `list[str] \| str \| None` | Glob patterns to include in watch (e.g. `"*.py"`) |
| `reload_excludes` | `list[str] \| str \| None` | Glob patterns to exclude |
| `reload_delay` | `float` | Default `0.25`s — debounce delay |

**Phase 8 usage pattern (D-08: reload scoped to `nautobot_app_mcp_server/`):**

```python
import uvicorn

uvicorn.run(
    mcp_app,
    host="127.0.0.1",
    port=8005,
    reload=True,
    reload_dirs=[str(project_root / "nautobot_app_mcp_server")],
)
```

**Additional uvicorn.run() parameters relevant to Phase 8:**

| Parameter | Value for Phase 8 | Rationale |
|---|---|---|
| `lifespan` | `"on"` | Required for FastMCP lifespan context manager |
| `ws` | `"websockets-sansio"` | Prevents websockets from blocking; FastMCP doesn't use WS |
| `timeout_graceful_shutdown` | `2` | Short grace period for clean shutdown |
| `log_level` | `"info"` | Standard log level |

**Note on `lifespan="on"`:** `FastMCP` has its own lifespan manager. When FastMCP's `http_app()` is passed to uvicorn, it wraps the app in a `StarletteWithLifespan` that correctly delegates to FastMCP's lifespan. Setting `lifespan="on"` (which is the default) tells uvicorn to use the app's own lifespan context manager.

---

## Research Question 4: `connection.ensure_connection()` — Failure behavior

**Answer: Raises `ProgrammingError` (wrapped in `django.db.utils.DatabaseErrorWrapper`) on connection failure.**

Verified from `django/db/backends/base/base.py` lines 271–285:

```python
@async_unsafe
def ensure_connection(self):
    """Guarantee that a connection to the database is established."""
    if self.connection is None:
        if self.in_atomic_block and self.closed_in_transaction:
            raise ProgrammingError(
                "Cannot open a new connection in an atomic block."
            )
        with self.wrap_database_errors:
            self.connect()
```

**Failure modes:**
1. `connect()` raises a DB-API-level exception (e.g., `OperationalError` for connection refused)
2. `wrap_database_errors` wraps it as `django.db.utils.DatabaseError` (parent of `ProgrammingError`, `OperationalError`, etc.)
3. The exception propagates up through `ensure_connection()` → `handle()` → any ORM call

**Key implication for Phase 8 `create_app()` DB check:**

```python
from django.db import connection

def _check_db_connection() -> None:
    """Verify DB is reachable; raises on failure."""
    try:
        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001 — could be OperationalError, DatabaseError, etc.
        raise RuntimeError(f"Database connectivity check failed: {exc}") from exc
```

The `wrap_database_errors` context manager in Django's base backend uses `try/except` and re-raises as the appropriate Django exception type. A generic `except Exception` is safe here since all DB failures surface as subclasses of `django.db.utils.DatabaseError` or `OperationalError`.

---

## Research Question 5: `nautobot.setup()` — Arguments

**Answer: `nautobot.setup(config_path=None)` — optional config path, falls back to `NAUTOBOT_CONFIG` env var.**

Verified from `nautobot/__init__.py` lines 48–76:

```python
def setup(config_path=None):
    """Similar to `django.setup()`, this configures Django with the appropriate Nautobot settings data."""
    from nautobot.core.cli import get_config_path, load_settings

    global __initialized

    if __initialized:
        return

    if config_path is None:
        config_path = get_config_path()

    # Point Django to our 'nautobot_config' pseudo-module that we'll load from the provided config path
    os.environ["DJANGO_SETTINGS_MODULE"] = "nautobot_config"

    if "nautobot_config" not in sys.modules:
        load_settings(config_path)
    django.setup()

    logger.info("Nautobot %s initialized!", __version__)
    __initialized = True
```

**`get_config_path()` implementation** (from `nautobot/core/cli/__init__.py` lines 206–214):

```python
def get_config_path():
    """Get the default Nautobot config file path based on the NAUTOBOT_CONFIG or NAUTOBOT_ROOT environment variables."""
    return os.getenv(
        "NAUTOBOT_CONFIG",
        os.path.join(
            os.getenv("NAUTOBOT_ROOT", os.path.expanduser("~/.nautobot")),
            "nautobot_config.py",
        ),
    )
```

**Key behavior:**
- `NAUTOBOT_CONFIG` env var takes precedence if set
- Falls back to `NAUTOBOT_ROOT/nautobot_config.py` (default `~/.nautobot/nautobot_config.py`)
- `nautobot.setup()` is idempotent — subsequent calls return immediately after the first
- `load_settings(config_path)` raises `FileNotFoundError` if the config file does not exist

**Phase 8 integration pattern:**

```python
import os
from django.db import connection

NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
# Set DJANGO_SETTINGS_MODULE is handled internally by nautobot.setup()
# but setting it explicitly is harmless and documents intent
os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG

import nautobot
nautobot.setup()  # uses NAUTOBOT_CONFIG from env
```

**No additional Django setup needed after `nautobot.setup()`:** The function calls `django.setup()` internally. After the call, all Django models (`Device`, `Token`, etc.) are immediately usable.

---

## Research Question 6: Existing FastMCP Management Commands in Reference Project

**Answer: Yes — `start_mcp_server.py` and `start_mcp_dev_server.py` exist in the `nautobot-app-mcp` reference project.**

Confirmed from architecture research (`ARCHITECTURE.md` sources section). These management commands use the patterns described in the Phase 8 requirements:
- Production: `FastMCP("NautobotMCP").run(transport="sse")`
- Dev: `create_app()` factory + `uvicorn.run(reload=True)`

The reference project structure is the source for all Phase 8 design decisions (D-01 through D-16 in `08-CONTEXT.md`).

---

## Additional Findings

### FastMCP Transport Names

The `Transport` type alias (line 155 of `server.py`):
```python
Transport = Literal["stdio", "http", "sse", "streamable-http"]
```

All four transports are valid. The ROADMAP uses `"sse"`. The dev command should use the same transport to keep parity between environments.

### FastMCP Constructor Has No `host`/`port` Parameters

This is a **breaking change in FastMCP 3.x** vs. what the reference project used. The `_REMOVED_KWARGS` dict (lines 122–138) shows:
```python
"host": "Pass `host` to `run_http_async()`, or set FASTMCP_HOST.",
"port": "Pass `port` to `run_http_async()`, or set FASTMCP_PORT.",
```

**Confirmed:** FastMCP 3.x (installed: 3.2.0) does NOT accept `host`/`port` in the constructor. Both are passed to `run()` / `run_http_async()` / `http_app()`.

**Phase 8 implementation impact:**
```python
# WRONG for FastMCP 3.x:
mcp = FastMCP("NautobotMCP", host="0.0.0.0", port=8005)  # raises TypeError

# CORRECT for FastMCP 3.x:
mcp = FastMCP("NautobotMCP")
# host/port passed at run time:
mcp.run(transport="sse", host="0.0.0.0", port=8005)           # production
uvicorn.run(mcp.http_app(), host="127.0.0.1", port=8005)      # dev
```

This means `create_app()` should NOT pass `host`/`port` to `FastMCP()`. It should store them as return metadata or attach them to the app. The cleanest approach: `create_app()` returns a `(mcp_instance, host, port)` tuple, or returns the `mcp` instance and lets the caller (`start_mcp_dev_server`) pass `host`/`port` to `uvicorn.run()`.

### `StarletteWithLifespan` Has No `lifespan` Property

The FastMCP `http_app()` creates a Starlette app with its own lifespan already baked in. When passing `mcp.http_app()` to `uvicorn.run()`, uvicorn will use the app's lifespan automatically when `lifespan="on"` (default). No explicit `lifespan=mcp_app.lifespan` needed.

### `PLUGINS_CONFIG` Not Needed in Phase 8

Phase 8 management commands are standalone processes. They don't go through Nautobot's plugin loading system — they call `nautobot.setup()` directly. `PLUGINS_CONFIG` is read by `nautobot.core.settings`, which is loaded by `nautobot.setup()`. If the config file has `PLUGINS_CONFIG`, it's already in the environment/Django settings. The Phase 8 decision to read it from environment variables is for cases where the management command needs to override or validate plugin config. For now, simply relying on `nautobot.setup()` loading the settings from the config path is sufficient.

---

## Synthesis for Implementation Planning

### Answer 1: `mcp.run(transport="sse")` blocks — no return value

- Use: `mcp.run(transport="sse", host="0.0.0.0", port=8005)` — blocks until SIGTERM
- `handle()` in `start_mcp_server.py` will not return normally — this is correct

### Answer 2: `http_app()` returns `StarletteWithLifespan` — proper ASGI app

- Use: `mcp_app = mcp.http_app(transport="sse")` → pass to `uvicorn.run(mcp_app, ...)`
- The app already has lifespan wired; `uvicorn.run(lifespan="on")` picks it up automatically

### Answer 3: uvicorn reload API

- `uvicorn.run(app, reload=True, reload_dirs=[str(watch_dir)])`
- `watch_dir` = `project_root / "nautobot_app_mcp_server"` for Phase 8 dev
- `reload_dirs` accepts a list of absolute paths as strings

### Answer 4: `connection.ensure_connection()` raises on failure

- Wrap in `try/except` → raise `RuntimeError("Database connectivity check failed: {exc}")`
- Generic `except Exception` is safe since all DB failures are subclasses of Django's `DatabaseError`

### Answer 5: `nautobot.setup(config_path=None)` — uses `NAUTOBOT_CONFIG` env var by default

- No need to pass any argument if `NAUTOBOT_CONFIG` is set in the environment
- Set `os.environ["DJANGO_SETTINGS_MODULE"] = "nautobot_config"` before calling for clarity
- Idempotent — subsequent calls are no-ops

### Answer 6: Reference project management commands exist

- Pattern is confirmed: `FastMCP("Name").run(transport="sse")` for production
- `create_app()` + `uvicorn.run(reload=True)` for development

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| `nautobot.setup()` called before ORM is needed | Low | Pattern confirmed in reference project |
| `uvicorn.run(reload=True)` conflicts with Docker volume mounts | Medium | `reload_dirs` scoping to `nautobot_app_mcp_server/` avoids watching Postgres files |
| `FastMCP()` constructor receives `host`/`port` kwargs | HIGH (breaking change in 3.x) | Do NOT pass `host`/`port` to `FastMCP()`; pass to `run()` / `uvicorn.run()` |
| `ensure_connection()` raises unexpected exception type | Low | Wrap with generic `except Exception` |
| `StarletteWithLifespan` not accepted by `uvicorn.run()` | None | Confirmed StarletteWithLifespan inherits from Starlette, is a valid ASGI app |

---

## Sources

- `fastmcp/server/mixins/transport.py` — `run()`, `run_async()`, `run_http_async()`, `http_app()` signatures
- `fastmcp/server/server.py` — `_REMOVED_KWARGS`, `FastMCP` constructor, `Transport` type alias
- `fastmcp/server/http.py` — `create_sse_app()`, `StarletteWithLifespan` class
- `django/db/backends/base/base.py` — `ensure_connection()` implementation
- `nautobot/__init__.py` — `setup()` implementation
- `nautobot/core/cli/__init__.py` — `get_config_path()`, `load_settings()` implementation
- `uvicorn/main.py` — `run()` signature, `reload`, `reload_dirs` parameters
- `development/nautobot_config.py` — `NAUTOBOT_CONFIG` usage pattern
- `.planning/research/ARCHITECTURE.md` — confirmed reference project patterns
