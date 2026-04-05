---
gsd_phase: 08
wave: A
depends_on: []
phase_goal: Two Django management commands serving as standalone FastMCP server entry points — production (start_mcp_server) and development (start_mcp_dev_server) — backed by a shared create_app() factory.
requirements:
  - P1-01
  - P1-02
  - P1-03
  - P1-04
---

# Phase 8 Plan: Infrastructure — Management Commands

## Overview

Four plans covering two management commands, the shared `create_app()` factory, environment config, and unit tests.

- **08-01** — `start_mcp_server.py` production command
- **08-02** — `start_mcp_dev_server.py` dev command
- **08-03** — `create_app()` factory + unit tests
- **08-04** — Environment variable configuration (NAUTOBOT_CONFIG, PLUGINS_CONFIG)

---

## Plan 08-01: `start_mcp_server` Production Management Command

**Requirement:** P1-01

**File:** `nautobot_app_mcp_server/management/commands/start_mcp_server.py`

### Tasks

#### Task 1: Write `start_mcp_server.py`

**read_first:**
- `nautobot_app_mcp_server/management/commands/import_production_data.py` — structural template (BaseCommand, add_arguments, handle)
- `nautobot_app_mcp_server/__init__.py` — NautobotAppConfig, base_url, name
- `08-CONTEXT.md` — D-03 (nautobot.setup() before relative imports), D-19 (command name), D-22 (defaults 0.0.0.0:8005)
- `08-RESEARCH.md` — Synthesis Answer 1 (`mcp.run()` blocks forever), Answer 5 (nautobot.setup() idempotent)

**action:**

Write `nautobot_app_mcp_server/management/commands/start_mcp_server.py`:

```python
"""Django management command: start_mcp_server.

Production entry point for the standalone FastMCP server. Bootstrap Django via
nautobot.setup(), then run the FastMCP HTTP server indefinitely.

Usage:
    poetry run nautobot-server start_mcp_server
    poetry run nautobot-server start_mcp_server --host 0.0.0.0 --port 8005

The command blocks forever (mcp.run() does not return). Manage via systemd.
"""

from __future__ import annotations

import os

# STEP 1: nautobot.setup() — MUST be called before any relative imports.
# This satisfies P1-01 / D-03 and prevents "Django wasn't set up yet".
NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG

import nautobot  # noqa: E402

nautobot.setup()

# STEP 2: Now that Django is bootstrapped, safe to import MCP components.
from django.core.management.base import BaseCommand  # noqa: E402

from nautobot_app_mcp_server.mcp.commands import create_app  # noqa: E402


class Command(BaseCommand):
    """Production MCP server management command."""

    help = "Start the standalone FastMCP server (production mode). Blocks indefinitely."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="0.0.0.0",
            help="Host to bind to (default: 0.0.0.0)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8005,
            help="Port to bind to (default: 8005)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        self.stdout.write(
            self.style.HTTP_INFO(
                f"[start_mcp_server] Starting FastMCP (host={host}, port={port})..."
            )
        )

        try:
            mcp, bound_host, bound_port = create_app(host=host, port=port)
        except RuntimeError as exc:
            self.stderr.write(self.style.ERROR(f"[start_mcp_server] {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"[start_mcp_server] FastMCP listening on {bound_host}:{bound_port}"
            )
        )

        # mcp.run() blocks forever — correct for a production server.
        # Using HTTP transport (modern, recommended over legacy SSE).
        mcp.run(transport="http", host=bound_host, port=bound_port)
```

**Key decisions:**

- `nautobot.setup()` at top, before any relative imports (D-03 / P1-01).
- `NAUTOBOT_CONFIG` via `os.environ.get()` (D-14 / P1-04).
- CLI `--host`/`--port` with defaults: 0.0.0.0 / 8005 (D-19 / D-22).
- `RuntimeError` from `create_app()` caught and exits with `SystemExit(1)`.
- No tool registration yet — Phase 9 wires `register_all_tools_with_mcp()`.

**acceptance_criteria:**

- File at `nautobot_app_mcp_server/management/commands/start_mcp_server.py` exists with `class Command(BaseCommand)`
- `nautobot.setup()` called before any import of `nautobot_app_mcp_server` modules
- `NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")` present
- `os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG` before `nautobot.setup()`
- `from nautobot_app_mcp_server.mcp.commands import create_app` after `nautobot.setup()`
- `add_arguments(parser)` defines `--host` (str, default "0.0.0.0") and `--port` (int, default 8005)
- `mcp.run(transport="http", host=bound_host, port=bound_port)` in `handle()`
- `RuntimeError` from `create_app()` caught, exits `SystemExit(1)`
- `help = "Start the standalone FastMCP server (production mode). Blocks indefinitely."`
- Ruff clean: `poetry run ruff check nautobot_app_mcp_server/management/commands/start_mcp_server.py`
- Pylint 10.00: `poetry run pylint nautobot_app_mcp_server/management/commands/start_mcp_server.py`

### Verification

| Check | Command |
|---|---|
| Importable | `poetry run python -c "from nautobot_app_mcp_server.management.commands.start_mcp_server import Command; print('OK')"` |
| Help text | `poetry run nautobot-server start_mcp_server --help` |
| nautobot.setup() precedes relative imports | `grep -n "import nautobot\|from nautobot_app_mcp_server" nautobot_app_mcp_server/management/commands/start_mcp_server.py` |
| Ruff clean | `poetry run ruff check nautobot_app_mcp_server/management/commands/start_mcp_server.py` |
| Pylint 10.00 | `poetry run pylint nautobot_app_mcp_server/management/commands/start_mcp_server.py` |

### must_haves

- `start_mcp_server.py` created in `management/commands/`
- `nautobot.setup()` before any relative imports
- `NAUTOBOT_CONFIG` from environment, default `"nautobot_config"`
- `create_app(host, port)` called, `RuntimeError` exits cleanly
- `mcp.run(transport="http", host, port)` — blocks forever (HTTP transport, modern recommended approach)
- `--host`/`--port` defaults 0.0.0.0 / 8005
- Pylint 10.00, Ruff clean

---

## Plan 08-02: `start_mcp_dev_server` Development Management Command

**Requirement:** P1-02

**File:** `nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py`

### Tasks

#### Task 1: Write `start_mcp_dev_server.py`

**read_first:**
- `nautobot_app_mcp_server/management/commands/import_production_data.py` — structural template
- `08-CONTEXT.md` — D-05 (command name), D-06 (create_app() + uvicorn.run()), D-07 (127.0.0.1:8005), D-08 (reload_dirs scoped to `nautobot_app_mcp_server/`)
- `08-RESEARCH.md` — RQ3 (`uvicorn.run(reload=True, reload_dirs=[...])` API), Synthesis Answer 2 (`mcp.http_app()` returns StarletteWithLifespan)

**action:**

Write `nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py`:

```python
"""Django management command: start_mcp_dev_server.

Development entry point for the standalone FastMCP server. Calls create_app()
to validate DB and build the FastMCP instance, then serves via uvicorn with
hot-reload.

Usage (run inside the Nautobot container):
    poetry run nautobot-server start_mcp_dev_server
    poetry run nautobot-server start_mcp_dev_server --port 8005

Reload watch is scoped to nautobot_app_mcp_server/ only (not the entire project
root) for faster restarts and fewer spurious reloads.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")
os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG

import nautobot  # noqa: E402

nautobot.setup()

from django.core.management.base import BaseCommand  # noqa: E402

from nautobot_app_mcp_server.mcp.commands import create_app  # noqa: E402


class Command(BaseCommand):
    """Development MCP server management command with hot-reload."""

    help = "Start the standalone FastMCP server in dev mode (uvicorn reload)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            default="127.0.0.1",
            help="Host to bind to (default: 127.0.0.1 — localhost only)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8005,
            help="Port to bind to (default: 8005)",
        )

    def handle(self, *args, **options):
        host = options["host"]
        port = options["port"]

        self.stdout.write(
            self.style.HTTP_INFO(
                f"[start_mcp_dev_server] Starting FastMCP dev server "
                f"(host={host}, port={port}, reload=True)..."
            )
        )

        try:
            mcp, bound_host, bound_port = create_app(host=host, port=port)
        except RuntimeError as exc:
            self.stderr.write(self.style.ERROR(f"[start_mcp_dev_server] {exc}"))
            raise SystemExit(1) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"[start_mcp_dev_server] FastMCP dev server listening on "
                f"{bound_host}:{bound_port} (auto-reload active)"
            )
        )

        # mcp.http_app() returns a StarletteWithLifespan ASGI callable (HTTP is the default).
        mcp_app = mcp.http_app()

        # reload_dirs scoped to nautobot_app_mcp_server/ only (D-08).
        package_root = Path(__file__).resolve().parents[3] / "nautobot_app_mcp_server"

        uvicorn.run(
            mcp_app,
            host=bound_host,
            port=bound_port,
            reload=True,
            reload_dirs=[str(package_root)],
            log_level="info",
        )
```

**Key decisions:**

- Same two-phase import pattern as `start_mcp_server` — `nautobot.setup()` before any relative imports.
- Default host `127.0.0.1` (localhost only, not externally exposed) per D-07.
- `mcp.http_app()` passed to `uvicorn.run()` (NOT `mcp.run()`) per D-06 — HTTP is the default transport.
- `reload_dirs=[str(package_root)]` scoped to `nautobot_app_mcp_server/` per D-08.
- `package_root = Path(__file__).resolve().parents[3] / "nautobot_app_mcp_server"` — reliable across environments.

**acceptance_criteria:**

- File at `nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` exists with `class Command(BaseCommand)`
- `nautobot.setup()` called before any import of `nautobot_app_mcp_server` modules
- `NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")` present
- `os.environ["DJANGO_SETTINGS_MODULE"] = NAUTOBOT_CONFIG` before `nautobot.setup()`
- `from nautobot_app_mcp_server.mcp.commands import create_app` after `nautobot.setup()`
- `add_arguments(parser)` defines `--host` (str, default "127.0.0.1") and `--port` (int, default 8005)
- `mcp_app = mcp.http_app()` present
- `uvicorn.run(mcp_app, ..., reload=True, reload_dirs=[...])` present
- `reload_dirs` contains path string with `nautobot_app_mcp_server` (NOT project root)
- `host="127.0.0.1"` in uvicorn.run() call
- `RuntimeError` from `create_app()` caught, exits `SystemExit(1)`
- `help = "Start the standalone FastMCP server in dev mode (uvicorn reload)."`
- Ruff clean: `poetry run ruff check nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py`
- Pylint 10.00: `poetry run pylint nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py`

### Verification

| Check | Command |
|---|---|
| Importable | `poetry run python -c "from nautobot_app_mcp_server.management.commands.start_mcp_dev_server import Command; print('OK')"` |
| Help text | `poetry run nautobot-server start_mcp_dev_server --help` |
| Default host is 127.0.0.1 | `grep "127.0.0.1" nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` |
| reload_dirs scoped correctly | `grep "reload_dirs" nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` |
| Ruff clean | `poetry run ruff check nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` |
| Pylint 10.00 | `poetry run pylint nautobot_app_mcp_server/management/commands/start_mcp_dev_server.py` |

### must_haves

- `start_mcp_dev_server.py` created in `management/commands/`
- `nautobot.setup()` before any relative imports
- `NAUTOBOT_CONFIG` from environment, default `"nautobot_config"`
- `create_app(host, port)` called, `RuntimeError` exits cleanly
- `mcp.http_app()` passed to `uvicorn.run()` (HTTP is default transport)
- `reload_dirs` scoped to `nautobot_app_mcp_server/` only
- `--host`/`--port` defaults 127.0.0.1 / 8005
- Pylint 10.00, Ruff clean

---

## Plan 08-03: `create_app()` Factory with DB Validation

**Requirement:** P1-03

**Files:**
- `nautobot_app_mcp_server/mcp/commands.py`
- `nautobot_app_mcp_server/mcp/tests/test_commands.py`

### Tasks

#### Task 1: Write `nautobot_app_mcp_server/mcp/commands.py`

**read_first:**
- `08-CONTEXT.md` — D-09 (signature), D-10 (DB check first), D-11 (RuntimeError message), D-12 (nautobot.setup()), D-13 (returns tuple), D-31 (file location)
- `08-RESEARCH.md` — RQ4 (`connection.ensure_connection()` raises), RQ5 (nautobot.setup() idempotent, uses NAUTOBOT_CONFIG), Synthesis (FastMCP 3.x host/port not in constructor)
- `nautobot_app_mcp_server/mcp/registry.py` — existing MCPToolRegistry pattern

**action:**

Write `nautobot_app_mcp_server/mcp/commands.py`:

```python
"""FastMCP server entry point: create_app() factory.

Phase 8 infrastructure — standalone FastMCP process entry point.
This module is imported by both management commands:
  - start_mcp_server.py   → mcp.run(transport="http", host, port)   (production)
  - start_mcp_dev_server.py → uvicorn.run(mcp.http_app(...), ...)    (development)

Phase 9 wires register_all_tools_with_mcp() into this module.
"""

from __future__ import annotations

import os

from django.db import connection

import nautobot


def create_app(host: str = "0.0.0.0", port: int = 8005) -> tuple:
    """Build a standalone FastMCP server instance.

    Validates DB connectivity, bootstraps Django via nautobot.setup(), then
    returns the FastMCP instance with bound host/port for the caller to use.

    Args:
        host: Host to bind to. Defaults to "0.0.0.0" (all interfaces).
        port: Port to bind to. Defaults to 8005.

    Returns:
        A 3-tuple of (FastMCP instance, host, port).

    Raises:
        RuntimeError: If the database is unreachable or the config file is missing.
    """
    # STEP 1: DB connectivity check — before nautobot.setup() so failures are fast.
    try:
        connection.ensure_connection()
    except Exception as exc:  # noqa: BLE001 — OperationalError, DatabaseError, etc.
        raise RuntimeError(f"Database connectivity check failed: {exc}") from exc

    # STEP 2: Bootstrap Django via nautobot.setup().
    nautobot.setup()

    # STEP 3: Build FastMCP instance.
    # FastMCP 3.x does NOT accept host/port in the constructor — passed at run time.
    from fastmcp import FastMCP

    mcp = FastMCP(
        "NautobotMCP",
        stateless_http=False,
        json_response=True,
    )

    # STEP 4: Phase 9 — wire register_all_tools_with_mcp() here.
    # (Placeholder until Phase 9 lands.)

    return (mcp, host, port)
```

**Key decisions:**

- `connection.ensure_connection()` called FIRST, before `nautobot.setup()` (D-10) — fast failure.
- Generic `except Exception` (D-11) — safe per Django's `wrap_database_errors`.
- `RuntimeError(f"Database connectivity check failed: {exc}")` per D-11 / P1-03.
- `nautobot.setup()` after DB check (D-12) — bootstraps Django ORM for standalone process.
- `FastMCP("NautobotMCP", stateless_http=False, json_response=True)` — same config as Phase 1 D-08.
- Returns `(mcp, host, port)` per D-09 / D-13 — host/port passed at run time.
- `register_all_tools_with_mcp()` TODO stub for Phase 9 integration.

**acceptance_criteria:**

- File at `nautobot_app_mcp_server/mcp/commands.py` exists
- `from django.db import connection` at module level
- `connection.ensure_connection()` called before `nautobot.setup()`
- `RuntimeError(f"Database connectivity check failed: {exc}")` raised on DB failure
- `nautobot.setup()` called after DB check
- `from fastmcp import FastMCP` inside `create_app()` (lazy import after nautobot.setup())
- `FastMCP("NautobotMCP", stateless_http=False, json_response=True)` instantiated
- Returns `(mcp, host, port)` tuple
- Signature: `create_app(host: str = "0.0.0.0", port: int = 8005) -> tuple`
- Docstring with Args, Returns, Raises sections
- TODO comment for Phase 9 `register_all_tools_with_mcp()` call
- Ruff clean: `poetry run ruff check nautobot_app_mcp_server/mcp/commands.py`
- Pylint 10.00: `poetry run pylint nautobot_app_mcp_server/mcp/commands.py`

#### Task 2: Write `nautobot_app_mcp_server/mcp/tests/test_commands.py`

**read_first:**
- `nautobot_app_mcp_server/mcp/tests/test_signal_integration.py` — existing test patterns
- `nautobot_app_mcp_server/mcp/tests/test_core_tools.py` — test imports and fixtures

**action:**

```python
"""Tests for mcp/commands.py — create_app() factory."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase


class TestCreateApp(TestCase):
    """Test create_app() factory."""

    def test_create_app_returns_tuple_of_three(self):
        """create_app() returns (mcp, host, port) when DB is reachable."""
        from nautobot_app_mcp_server.mcp.commands import create_app

        result = create_app(host="127.0.0.1", port=9000)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        mcp, host, port = result
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 9000)

    def test_create_app_db_failure_raises_runtime_error(self):
        """connection.ensure_connection() failure raises RuntimeError with descriptive message."""
        from nautobot_app_mcp_server.mcp.commands import create_app

        with patch(
            "nautobot_app_mcp_server.mcp.commands.connection.ensure_connection"
        ) as mock_ensure:
            mock_ensure.side_effect = Exception("connection refused")

            with self.assertRaises(RuntimeError) as ctx:
                create_app()

            self.assertIn("Database connectivity check failed:", str(ctx.exception))
            self.assertIn("connection refused", str(ctx.exception))
```

**Key decisions:**

- Uses `django.test.TestCase` (no DB writes needed).
- `test_create_app_returns_tuple_of_three` — verifies correct return type/values with real DB.
- `test_create_app_db_failure_raises_runtime_error` — mocks `connection.ensure_connection()` with `side_effect=Exception(...)`; verifies `RuntimeError` message contains `"Database connectivity check failed:"`.

**acceptance_criteria:**

- File at `nautobot_app_mcp_server/mcp/tests/test_commands.py` exists
- `test_create_app_returns_tuple_of_three` — asserts return is 3-tuple, host/port correct
- `test_create_app_db_failure_raises_runtime_error` — mocks `ensure_connection()`; asserts `RuntimeError` with message containing `"Database connectivity check failed:"`
- `from unittest.mock import patch` imported
- Uses `django.test.TestCase`
- Ruff clean: `poetry run ruff check nautobot_app_mcp_server/mcp/tests/test_commands.py`
- Pylint 10.00: `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_commands.py`
- Tests pass: `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_commands`

### Verification

| Check | Command |
|---|---|
| Function importable | `poetry run python -c "from nautobot_app_mcp_server.mcp.commands import create_app; print('OK')"` |
| Signature correct | `poetry run python -c "import inspect; from nautobot_app_mcp_server.mcp.commands import create_app; print(inspect.signature(create_app))"` |
| Tests pass | `poetry run nautobot-server test nautobot_app_mcp_server.mcp.tests.test_commands` |
| Ruff clean | `poetry run ruff check nautobot_app_mcp_server/mcp/tests/test_commands.py` |
| Pylint 10.00 | `poetry run pylint nautobot_app_mcp_server/mcp/tests/test_commands.py` |

### must_haves

- `nautobot_app_mcp_server/mcp/commands.py` created
- `connection.ensure_connection()` before `nautobot.setup()` — raises `RuntimeError` on DB failure
- `nautobot.setup()` called in `create_app()`
- Returns `(mcp, host, port)` tuple
- FastMCP 3.x constructor has no `host`/`port` kwargs
- `register_all_tools_with_mcp()` TODO stub for Phase 9 integration
- `test_commands.py` with 2 test cases (DB failure + return value)
- Tests pass, Pylint 10.00, Ruff clean

---

## Plan 08-04: Environment Variable Configuration

**Requirement:** P1-04

**File:** `nautobot_app_mcp_server/mcp/commands.py` (additive — same file as 08-03)

### Tasks

#### Task 1: Add `PLUGINS_CONFIG` read to `create_app()`

**read_first:**
- `08-CONTEXT.md` — D-14 (NAUTOBOT_CONFIG from env), D-15 (PLUGINS_CONFIG from env), D-16 (default "nautobot_config")
- `08-RESEARCH.md` — §"PLUGINS_CONFIG Not Needed" — `nautobot.setup()` loads it from config path; Phase 8 reads from env for override/validation
- `development/nautobot_config.py` — how `NAUTOBOT_CONFIG` env var is used today

**action:**

Add the following to `nautobot_app_mcp_server/mcp/commands.py` at the top of `create_app()`:

```python
# Before STEP 1 (DB check) in create_app():

# STEP 0: Read NAUTOBOT_CONFIG from environment.
# nautobot.setup() uses this to locate the config file.
# Default "nautobot_config" is resolved by nautobot.core.cli.get_config_path().
_NAUTOBOT_CONFIG = os.environ.get("NAUTOBOT_CONFIG", "nautobot_config")

# STEP 0b: Optionally read PLUGINS_CONFIG from environment for override/validation.
# nautobot.setup() loads PLUGINS_CONFIG from the config file; this env var allows
# the management command to override it at startup if needed.
_PLUGINS_CONFIG = os.environ.get("PLUGINS_CONFIG")
```

Then update the docstring of `create_app()` to document P1-04:

```python
"""Build a standalone FastMCP server instance.

Validates DB connectivity, bootstraps Django via nautobot.setup(), then
returns the FastMCP instance with bound host/port for the caller to use.

Reads the following from environment variables:
    NAUTOBOT_CONFIG: Path to Nautobot config file.
        Defaults to "nautobot_config" (resolved by nautobot.core.cli.get_config_path()).
    PLUGINS_CONFIG: Nautobot PLUGINS_CONFIG dict. If set, overrides the value in the
        config file at startup.

Args:
    host: Host to bind to. Defaults to "0.0.0.0" (all interfaces).
    port: Port to bind to. Defaults to 8005.

Returns:
    A 3-tuple of (FastMCP instance, host, port).

Raises:
    RuntimeError: If the database is unreachable or the config file is missing.
"""
```

**Key decisions:**

- `NAUTOBOT_CONFIG` read via `os.environ.get()` (D-14 / P1-04) — already set at module level in management commands before `create_app()` is called, but `create_app()` also reads it for self-contained operation.
- `PLUGINS_CONFIG` read via `os.environ.get()` (D-15 / P1-04) — allows management command to override at startup.
- Both documented in docstring.

**acceptance_criteria:**

- `os.environ.get("NAUTOBOT_CONFIG")` present in `create_app()` with default "nautobot_config"
- `os.environ.get("PLUGINS_CONFIG")` present in `create_app()`
- Both env vars documented in docstring under a "Reads" section
- Ruff clean: `poetry run ruff check nautobot_app_mcp_server/mcp/commands.py`
- Pylint 10.00: `poetry run pylint nautobot_app_mcp_server/mcp/commands.py`

### Verification

| Check | Command |
|---|---|
| NAUTOBOT_CONFIG in code | `grep "NAUTOBOT_CONFIG" nautobot_app_mcp_server/mcp/commands.py` |
| PLUGINS_CONFIG in code | `grep "PLUGINS_CONFIG" nautobot_app_mcp_server/mcp/commands.py` |
| Both in docstring | `grep -A2 "NAUTOBOT_CONFIG\|PLUGINS_CONFIG" nautobot_app_mcp_server/mcp/commands.py` |
| Ruff clean | `poetry run ruff check nautobot_app_mcp_server/mcp/commands.py` |
| Pylint 10.00 | `poetry run pylint nautobot_app_mcp_server/mcp/commands.py` |

### must_haves

- `NAUTOBOT_CONFIG` read from `os.environ.get()` with default "nautobot_config"
- `PLUGINS_CONFIG` read from `os.environ.get()` (optional override)
- Both documented in docstring
- Phase exit gate: Both management commands importable; `create_app()` raises `RuntimeError` on unreachable DB
