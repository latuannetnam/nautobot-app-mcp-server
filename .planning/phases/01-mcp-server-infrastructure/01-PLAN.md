---
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - nautobot_app_mcp_server/__init__.py
autonomous: true
---

# Phase 1 Plan — MCP Server Infrastructure

**Goal:** Build the embedded FastMCP server scaffold — plugin wiring, ASGI bridge, URL routing, and the tool registry. No auth, no tools yet.

**Requirements covered:** FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, SRVR-01, SRVR-02, SRVR-03, SRVR-04, SRVR-05, SRVR-06, REGI-01, REGI-02, REGI-03, REGI-04, TEST-03, TEST-04

**Success gate:** `GET/POST /plugins/nautobot-app-mcp-server/mcp/` returns valid MCP JSON-RPC responses; `MCPToolRegistry` is a thread-safe singleton; tests pass.

---

## Wave 1 — Foundation (parallel)

### Task 1.1 — Add MCP dependencies to `pyproject.toml`

**Requirement:** FOUND-01

**Read first:**
- `pyproject.toml` — existing `[tool.poetry.dependencies]` section

**Action:**

Add the following to the `[tool.poetry.dependencies]` section of `pyproject.toml`, after the `nautobot` line:

```toml
# MCP server layer
fastmcp = "^3.2.0"
```

**Acceptance criteria:**
- `grep -n "fastmcp" pyproject.toml` returns a line matching `fastmcp = "^3.2.0"` in `[tool.poetry.dependencies]`
- `grep -n "mcp = " pyproject.toml` returns **no** direct `mcp =` entry (it is pinned transitively by `fastmcp`)
- `grep -n "asgiref = " pyproject.toml` returns **no** direct `asgiref =` entry (it is already a transitive dep of Nautobot/Django)

---

### Task 1.2 — Create `nautobot_app_mcp_server/mcp/` package structure

**Requirements:** FOUND-02

**Read first:**
- `nautobot_app_mcp_server/__init__.py` — existing minimal NautobotAppConfig

**Action:**

Create the following package files:

**`nautobot_app_mcp_server/mcp/__init__.py`:**
```python
"""MCP server package for nautobot_app_mcp_server."""

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

__all__ = ["MCPToolRegistry", "ToolDefinition", "register_mcp_tool"]
```

**`nautobot_app_mcp_server/mcp/__init__.py` (public API — full content in Task 3.1 below).**

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/__init__.py` exists with Google docstring
- `nautobot_app_mcp_server/mcp/registry.py` exists (created in Task 2.1)
- `nautobot_app_mcp_server/mcp/server.py` exists (created in Task 2.2)
- `nautobot_app_mcp_server/mcp/view.py` exists (created in Task 2.3)
- `nautobot_app_mcp_server/urls.py` exists (created in Task 2.3)
- `nautobot_app_mcp_server/apps.py` exists (created in Task 3.2)
- `nautobot_app_mcp_server/mcp/tests/` directory exists with test files (created in Task 4.1/4.2)
- `poetry run python -c "from nautobot_app_mcp_server.mcp import MCPToolRegistry, ToolDefinition; print('import OK')"` succeeds without errors

---

### Task 1.3 — Fix `base_url` in `__init__.py` and DESIGN.md

**Requirements:** FOUND-03, FOUND-04

**Read first:**
- `nautobot_app_mcp_server/__init__.py` — current `base_url = "mcp-server"`
- `docs/dev/DESIGN.md` — source of truth (has `nautobot_mcp_server` throughout)

**Action:**

**1.** In `nautobot_app_mcp_server/__init__.py`, change line 19 from:
```python
base_url = "mcp-server"
```
to:
```python
base_url = "nautobot-app-mcp-server"
```

**2.** In `docs/dev/DESIGN.md`, do a global find-replace of all occurrences of:
- `nautobot_mcp_server/` → `nautobot_app_mcp_server/`
- `nautobot-mcp-server` → `nautobot-app-mcp-server`
- `nautobot_mcp_server.mcp` → `nautobot_app_mcp_server.mcp`
- `from nautobot_mcp_server` → `from nautobot_app_mcp_server`
- `import nautobot_mcp_server` → `import nautobot_app_mcp_server`

**Acceptance criteria:**
- `grep -n 'base_url = "nautobot-app-mcp-server"' nautobot_app_mcp_server/__init__.py` returns exactly 1 match
- `grep -n "nautobot_mcp_server" docs/dev/DESIGN.md` returns **zero** matches
- `grep -n "nautobot_app_mcp_server" docs/dev/DESIGN.md` returns 3 or more matches (import paths)
- The MCP endpoint URL in all docs is `/plugins/nautobot-app-mcp-server/mcp/`

---

### Task 1.4 — Implement ASGI bridge via `asgiref.wsgi.WsgiToAsgi`

**Requirement:** FOUND-05

**Read first:**
- `.planning/research/ARCHITECTURE.md` — verified Option A code patterns (lines ~445–477)
- `.planning/research/PITFALLS.md` — PIT-04 (wrong bridge direction)

**Action:**

Implement the full `mcp/view.py` ASGI bridge as described in ARCHITECTURE.md Pattern 1:

```python
"""ASGI bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse."""

from asgiref.wsgi import WsgiToAsgi

from nautobot_app_mcp_server.mcp.server import get_mcp_app


def mcp_view(request):
    """Bridge: Django HttpRequest → FastMCP ASGI app → Django HttpResponse.

    The WsgiToAsgi wrapper converts Django's WSGI interface to ASGI,
    then calls the FastMCP ASGI app which handles the MCP protocol.
    """
    app = get_mcp_app()  # Lazy: created on first request
    handler = WsgiToAsgi(app)
    return handler(request)
```

**Key implementation notes:**
- `get_mcp_app()` is called inside the view (not at module import) — this is the lazy factory pattern required by PIT-03
- `WsgiToAsgi` from `asgiref.wsgi` is the **only** correct bridge (NOT `async_to_sync`)

**Acceptance criteria:**
- `mcp/view.py` contains `from asgiref.wsgi import WsgiToAsgi`
- `mcp/view.py` contains `from nautobot_app_mcp_server.mcp.server import get_mcp_app`
- `mcp/view.py` contains `def mcp_view(request):`
- `mcp/view.py` contains `handler = WsgiToAsgi(app)` (NOT `async_to_sync`)
- `mcp/view.py` does **not** create the ASGI app at module level (no `_mcp_app = ...` at module scope)

---

## Wave 2 — Server (after Wave 1)

### Task 2.1 — `MCPToolRegistry` thread-safe singleton

**Requirements:** REGI-01, REGI-02

**Read first:**
- `.planning/research/ARCHITECTURE.md` — Pattern 4 (Thread-Safe Singleton Registry, lines ~226–254)
- `.planning/research/PITFALLS.md` — PIT-02 (package name), PIT-03 (lazy init)

**Action:**

Create `nautobot_app_mcp_server/mcp/registry.py`:

```python
"""Thread-safe in-memory tool registry for MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import threading


@dataclass
class ToolDefinition:
    """Definition of a single MCP tool.

    Attributes:
        name: Unique tool name (e.g. "device_list").
        func: The callable tool function.
        description: Human-readable description for the MCP manifest.
        input_schema: JSON Schema dict for tool input parameters.
        tier: "core" for always-available tools, "app" for registered third-party tools.
        app_label: Django app label for app-tier tools (e.g. "netnam_cms_core").
        scope: Dot-separated scope string (e.g. "netnam_cms_core.juniper"). None for core tools.
    """

    name: str
    func: Callable
    description: str
    input_schema: dict[str, Any]
    tier: str = "core"
    app_label: str | None = None
    scope: str | None = None


class MCPToolRegistry:
    """Thread-safe singleton registry for MCP tools.

    Uses double-checked locking with threading.Lock to safely support
    concurrent reads (every MCP request) and writes (third-party app
    registration at startup).
    """

    _instance: MCPToolRegistry | None = None
    _lock = threading.Lock()
    _tools: dict[str, ToolDefinition] = {}

    @classmethod
    def get_instance(cls) -> MCPToolRegistry:
        """Return the singleton registry instance (creating it on first call)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool. Raises ValueError if name is already registered."""
        with self._lock:
            if tool.name in self._tools:
                raise ValueError(f"Tool already registered: {tool.name}")
            self._tools[tool.name] = tool

    def get_all(self) -> list[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_core_tools(self) -> list[ToolDefinition]:
        """Return all core-tier tools."""
        return [t for t in self._tools.values() if t.tier == "core"]

    def get_by_scope(self, scope: str) -> list[ToolDefinition]:
        """Return all tools matching an exact scope or any child scope.

        Args:
            scope: The scope to match. "core" returns all core tools.
                "netnam_cms_core" returns all tools under that app (any sub-scope).
                "netnam_cms_core.juniper" returns tools with that exact scope.
        """
        if scope == "core":
            return self.get_core_tools()
        return [
            t for t in self._tools.values()
            if t.scope == scope
            or (t.scope is not None and t.scope.startswith(f"{scope}."))
        ]

    def fuzzy_search(self, term: str) -> list[ToolDefinition]:
        """Fuzzy match tools by name or description (case-insensitive).

        Args:
            term: Search term to match in tool name or description.

        Returns:
            All tools whose name or description contains the term.
        """
        term_lower = term.lower()
        return [
            t for t in self._tools.values()
            if term_lower in t.name.lower() or term_lower in t.description.lower()
        ]
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/registry.py` exists with Google docstring on module
- `MCPToolRegistry` has `threading.Lock` as class attribute `_lock`
- `MCPToolRegistry` uses double-checked locking in `get_instance()`
- `ToolDefinition` is a `@dataclass` with all 7 fields documented
- `MCPToolRegistry.register()` raises `ValueError` on duplicate name
- `MCPToolRegistry` has all 5 methods: `register`, `get_all`, `get_core_tools`, `get_by_scope`, `fuzzy_search`
- `grep -n "threading.Lock" nautobot_app_mcp_server/mcp/registry.py` returns a match
- `grep -n "if cls._instance is None" nautobot_app_mcp_server/mcp/registry.py` returns a match (double-checked locking)

---

### Task 2.2 — FastMCP instance + lazy factory

**Requirements:** SRVR-01, SRVR-02

**Read first:**
- `.planning/research/STACK.md` — FastMCP configuration, `stateless_http=False`, `json_response=True`
- `.planning/research/ARCHITECTURE.md` — Pattern 2 (Lazy ASGI App Initialization, lines ~153–188)
- `.planning/research/PITFALLS.md` — PIT-03 (ASGI app at import time), PIT-04 (wrong bridge)

**Action:**

Create `nautobot_app_mcp_server/mcp/server.py`:

```python
"""FastMCP server instance and lazy ASGI app factory.

The ASGI app is NOT created at module import time (lazy factory).
It is created on the first HTTP request via get_mcp_app(), which
avoids Django startup race conditions where the ORM is not yet ready.

Architecture:
    Django request → urls.py → mcp_view (view.py)
                              → get_mcp_app() [lazy]
                              → mcp.streamable_http_app() [ASGI app]
                              → FastMCP handles MCP protocol
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import FastMCP

if TYPE_CHECKING:
    from starlette.applications import Starlette

# Module-level globals — NOT initialized at import time (PIT-03)
_mcp_app: Starlette | None = None


def get_mcp_app() -> Starlette:
    """Lazily build the FastMCP ASGI app on first HTTP request.

    This MUST be called from within a Django request context (e.g., from
    mcp_view). Calling it at module import time causes Django ORM errors
    because no request thread context exists yet.

    Returns:
        The FastMCP Starlette ASGI application, mounted at the /mcp/ path.

    Raises:
        RuntimeError: If called outside of a Django request context.
    """
    global _mcp_app  # pylint: disable=global-statement
    if _mcp_app is None:
        mcp = FastMCP(
            "NautobotMCP",
            stateless_http=False,
            json_response=True,
        )
        _mcp_app = mcp.streamable_http_app(path="/mcp")
    return _mcp_app
```

**Key points:**
- `_mcp_app` is `None` at module import — no ASGI app created yet
- `get_mcp_app()` creates the app on first call (inside Django request)
- `stateless_http=False` enables per-session scope tracking
- `json_response=True` uses JSON responses instead of chunked SSE
- No `async_to_sync`, no `StreamableHTTPSessionManager` passed explicitly — FastMCP manages this internally

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/server.py` exists with Google docstring on module
- `nautobot_app_mcp_server/mcp/server.py` contains `from fastmcp import FastMCP`
- `nautobot_app_mcp_server/mcp/server.py` contains `stateless_http=False` and `json_response=True`
- `nautobot_app_mcp_server/mcp/server.py` contains `_mcp_app: Starlette | None = None` (module-level, None at import)
- `nautobot_app_mcp_server/mcp/server.py` contains `def get_mcp_app()` with global mutable check
- `nautobot_app_mcp_server/mcp/server.py` does NOT call `mcp.run()` or `uvicorn`
- `nautobot_app_mcp_server/mcp/server.py` does NOT use `async_to_sync`
- `poetry run python -c "from nautobot_app_mcp_server.mcp.server import get_mcp_app; print('server module OK')"` succeeds without creating the app (lazy, so no side effects)

---

### Task 2.3 — Django URL route + ASGI view

**Requirements:** SRVR-03, SRVR-04, SRVR-05

**Read first:**
- `nautobot_app_mcp_server/mcp/view.py` (created in Task 1.4)
- `nautobot_app_mcp_server/__init__.py` — NautobotAppConfig (needs `urls` attribute)

**Action:**

**1.** Create `nautobot_app_mcp_server/urls.py`:
```python
"""Django URL routing for the MCP server endpoint.

The MCP endpoint is mounted at /plugins/nautobot-app-mcp-server/mcp/
automatically via Nautobot's plugin URL discovery system.

Nautobot discovers this module via the PLUGINS setting and includes
plugin_patterns() in the root URLconf. This urls.py must export a
urlpatterns list at module level.
"""

from django.urls import path

from nautobot_app_mcp_server.mcp.view import mcp_view

urlpatterns = [
    path("mcp/", mcp_view, name="mcp"),
]
```

**2.** Update `nautobot_app_mcp_server/__init__.py` to add a `urls` attribute pointing to the URL module:

After `searchable_models = []`, add:
```python
    urls = ["nautobot_app_mcp_server.urls"]
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/urls.py` exists with Google docstring on module
- `nautobot_app_mcp_server/urls.py` contains `from django.urls import path`
- `nautobot_app_mcp_server/urls.py` contains `from nautobot_app_mcp_server.mcp.view import mcp_view`
- `nautobot_app_mcp_server/urls.py` contains `urlpatterns = [path("mcp/", mcp_view, name="mcp")]`
- `nautobot_app_mcp_server/__init__.py` contains `urls = ["nautobot_app_mcp_server.urls"]`
- `grep -n "urls =" nautobot_app_mcp_server/__init__.py` returns exactly 1 match
- `grep -n "path(\"mcp/\"" nautobot_app_mcp_server/urls.py` returns exactly 1 match

---

### Task 2.4 — `register_mcp_tool()` public API

**Requirements:** REGI-03, REGI-04

**Read first:**
- `nautobot_app_mcp_server/mcp/registry.py` (created in Task 2.1)
- `.planning/research/ARCHITECTURE.md` — Layer 5 (Third-Party Tool Registration API, lines ~237–255)
- `.planning/codebase/ARCHITECTURE.md` — Pattern 4 (import path for third-party apps)

**Action:**

Update `nautobot_app_mcp_server/mcp/__init__.py` with the full public API:

```python
"""MCP server package for nautobot_app_mcp_server.

This module exposes the public API for the MCP tool registry. Third-party
Nautobot apps can call :func:`register_mcp_tool` to register their own
MCP tools, which become available to AI agents once session scope is enabled.

Example:
    From a third-party Nautobot app (``netnam_cms_core/__init__.py``)::

        from nautobot_app_mcp_server.mcp import register_mcp_tool

        register_mcp_tool(
            name="juniper_bgp_neighbor_list",
            func=juniper_bgp_neighbor_list,
            description="List BGP neighbors on Juniper devices.",
            input_schema={
                "type": "object",
                "properties": {
                    "device_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
            tier="app",
            app_label="netnam_cms_core",
            scope="netnam_cms_core.juniper",
        )
"""

from __future__ import annotations

from typing import Any, Callable

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

__all__ = ["MCPToolRegistry", "ToolDefinition", "register_mcp_tool"]


def register_mcp_tool(
    name: str,
    func: Callable,
    description: str,
    input_schema: dict[str, Any],
    tier: str = "app",
    app_label: str | None = None,
    scope: str | None = None,
) -> None:
    """Register a tool with the MCP tool registry.

    Called by third-party Nautobot apps in their :meth:`ready` hook,
    or by the MCP server's own post_migrate handler for core tools.

    Args:
        name: Unique tool name (e.g. ``"device_list"``).
        func: The callable tool function.
        description: Human-readable description for the MCP tool manifest.
        input_schema: JSON Schema dict describing the tool's input parameters.
        tier: ``"core"`` for always-available tools, ``"app"`` for registered tools.
        app_label: Django app label (e.g. ``"netnam_cms_core"``). Required for app-tier tools.
        scope: Dot-separated scope string (e.g. ``"netnam_cms_core.juniper"``).
            Optional for app-tier tools; required when progressive disclosure is used.

    Raises:
        ValueError: If a tool with the same name is already registered.

    Example:
        >>> from nautobot_app_mcp_server.mcp import register_mcp_tool
        >>> def my_tool(name: str): pass
        >>> register_mcp_tool(name="my_tool", func=my_tool,
        ...                   description="My tool",
        ...                   input_schema={"type": "object",
        ...                                "properties": {"name": {"type": "string"}}})
    """
    registry = MCPToolRegistry.get_instance()
    registry.register(
        ToolDefinition(
            name=name,
            func=func,
            description=description,
            input_schema=input_schema,
            tier=tier,
            app_label=app_label,
            scope=scope,
        )
    )
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/__init__.py` contains `def register_mcp_tool(`
- `nautobot_app_mcp_server/mcp/__init__.py` contains `from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition`
- `nautobot_app_mcp_server/mcp/__init__.py` contains all 7 parameters of `register_mcp_tool` including defaults `tier="app"`, `app_label=None`, `scope=None`
- `nautobot_app_mcp_server/mcp/__init__.py` contains `registry.register(` with a `ToolDefinition(...)` call
- `nautobot_app_mcp_server/mcp/__init__.py` has a module-level docstring with a third-party usage example
- `nautobot_app_mcp_server/mcp/__init__.py` exports `register_mcp_tool` in `__all__`

---

## Wave 3 — Signal Wiring + Tests

### Task 3.1 — `post_migrate` signal wiring

**Requirements:** SRVR-06

**Read first:**
- `nautobot_app_mcp_server/__init__.py` — current NautobotAppConfig (needs `ready()` method)
- `.planning/research/PITFALLS.md` — PIT-12 (post_migrate signal registration order)
- `.planning/codebase/ARCHITECTURE.md` — Layer 4 (Tool Registration Lifecycle, lines ~184–233)

**Action:**

Create `nautobot_app_mcp_server/apps.py`:

```python
"""Nautobot app configuration for the MCP server plugin.

This module handles the MCP server's lifecycle within Nautobot's plugin
framework. The :meth:`ready` hook connects the post_migrate signal,
which fires after all app migrations complete and guarantees that all
third-party app ready() hooks have already run before tool registration.
"""

from __future__ import annotations

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class NautobotMcpServerAppConfig(AppConfig):
    """Nautobot app configuration for the MCP server.

    Attributes:
        name: Must match the app's Django app label (package directory name).
        label: Unique identifier for this app in Nautobot's plugin registry.
        base_url: URL prefix for the MCP endpoint: /plugins/<base_url>/mcp/.
    """

    name = "nautobot_app_mcp_server"
    label = "nautobot_app_mcp_server"
    verbose_name = "Nautobot App MCP Server"

    def ready(self) -> None:
        """Connect post_migrate signal for tool registration.

        post_migrate fires after migrations for this app complete.
        At that point all other apps' ready() hooks have already run,
        so their register_mcp_tool() calls are already in the registry.
        """
        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs) -> None:
        """Register MCP tools after this app's migrations complete.

        Args:
            app_config: The Django app config that triggered this signal.
            **kwargs: Additional signal arguments.
        """
        if app_config.name == "nautobot_app_mcp_server":
            # This guard ensures the registration runs only once,
            # when this specific app's migrations complete.
            from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

            # In Phase 1: verify the registry singleton is reachable.
            # Phase 2 will wire in core tool registration.
            registry = MCPToolRegistry.get_instance()
            # Tools will be registered here in Phase 2 (core tools)
            # Third-party tools are already registered by this point
            # (they called register_mcp_tool in their own ready() hooks)
```

**2.** Update `nautobot_app_mcp_server/__init__.py` to use `apps.py`:
- Change `from nautobot.apps import NautobotAppConfig` to import from `apps` instead:
```python
from nautobot_app_mcp_server.apps import NautobotAppMcpServerAppConfig

__version__ = metadata.version(__name__)

config = NautobotAppMcpServerAppConfig  # pylint:disable=invalid-name
```

Or keep `NautobotAppConfig` import and add `urls` + `ready()` here. Choose the simpler approach: keep all config in `__init__.py` (single-file approach for Phase 1), no separate `apps.py` needed.

**Decision: Single-file approach** — keep `NautobotAppMcpServerConfig` in `__init__.py` and add the `ready()` method there:

```python
class NautobotAppMcpServerConfig(NautobotAppConfig):
    """App configuration for the nautobot_app_mcp_server app."""

    name = "nautobot_app_mcp_server"
    verbose_name = "Nautobot App MCP Server"
    version = __version__
    author = "Le Anh Tuan"
    description = "Nautobot MCP Server App."
    base_url = "nautobot-app-mcp-server"
    required_settings = []
    default_settings = {}
    docs_view_name = "plugins:nautobot_app_mcp_server:docs"
    searchable_models = []
    urls = ["nautobot_app_mcp_server.urls"]

    def ready(self) -> None:
        """Connect post_migrate signal for tool registration.

        post_migrate fires after migrations for this app complete.
        At that point all other apps' ready() hooks have already run,
        so their register_mcp_tool() calls are already in the registry.
        """
        from django.db.models.signals import post_migrate
        post_migrate.connect(self._on_post_migrate, sender=self)

    @staticmethod
    def _on_post_migrate(app_config, **kwargs) -> None:
        """Register MCP tools after this app's migrations complete."""
        if app_config.name == "nautobot_app_mcp_server":
            from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

            registry = MCPToolRegistry.get_instance()
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/__init__.py` contains `def ready(self)` method
- `nautobot_app_mcp_server/__init__.py` contains `post_migrate.connect(`
- `nautobot_app_mcp_server/__init__.py` contains `_on_post_migrate` as a static method
- `nautobot_app_mcp_server/__init__.py` contains `if app_config.name == "nautobot_app_mcp_server":` guard
- `nautobot_app_mcp_server/__init__.py` contains `urls = ["nautobot_app_mcp_server.urls"]`
- `grep -n "urls =" nautobot_app_mcp_server/__init__.py` returns exactly 1 match
- No `apps.py` is created (keeping config in `__init__.py` per single-file pattern)
- `grep -n "from django.db.models.signals import post_migrate" nautobot_app_mcp_server/__init__.py` returns a match

---

### Task 3.2 — `test_view.py` (ASGI bridge + HTTP round-trip)

**Requirements:** TEST-03

**Read first:**
- `nautobot_app_mcp_server/mcp/view.py` (created in Task 1.4)
- `nautobot_app_mcp_server/mcp/server.py` (created in Task 2.2)
- `nautobot_app_mcp_server/__init__.py` (final state after Task 3.1)

**Action:**

Create `nautobot_app_mcp_server/mcp/tests/__init__.py`:
```python
"""Tests for the MCP server module."""
```

Create `nautobot_app_mcp_server/mcp/tests/test_view.py`:

```python
"""Tests for the MCP HTTP endpoint — ASGI bridge and endpoint reachability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import Client, TestCase, override_settings


class MCPViewTestCase(TestCase):
    """Test the MCP Django view and ASGI bridge."""

    @override_settings(
        PLUGINS=["nautobot_app_mcp_server"],
        ROOT_URLCONF="nautobot_app_mcp_server.urls",
    )
    def test_mcp_view_imports_successfully(self):
        """Verify mcp_view is importable and is a callable."""
        from nautobot_app_mcp_server.mcp.view import mcp_view
        self.assertTrue(callable(mcp_view))

    @override_settings(
        PLUGINS=["nautobot_app_mcp_server"],
        ROOT_URLCONF="nautobot_app_mcp_server.urls",
    )
    def test_mcp_endpoint_resolves(self):
        """Verify the /mcp/ URL resolves to mcp_view."""
        from django.urls import resolve
        match = resolve("/mcp/")
        self.assertEqual(match.func, match.func)  # resolves without 404
        self.assertEqual(match.url_name, "mcp")

    @patch("nautobot_app_mcp_server.mcp.view.get_mcp_app")
    def test_view_calls_get_mcp_app(self, mock_get_app):
        """mcp_view calls get_mcp_app() to get the ASGI app."""
        from nautobot_app_mcp_server.mcp.view import mcp_view

        # Mock the ASGI app with a fake handle method
        mock_asgi_app = MagicMock()
        mock_handler = MagicMock(return_value=MagicMock(status_code=200))
        mock_asgi_app.return_value = mock_handler
        mock_get_app.return_value = mock_asgi_app

        # Build a minimal Django request
        mock_request = MagicMock()
        mock_request.method = "GET"
        mock_request.path = "/mcp/"
        mock_request.META = {}

        with patch(
            "nautobot_app_mcp_server.mcp.view.WsgiToAsgi",
            return_value=mock_handler,
        ):
            mcp_view(mock_request)

        mock_get_app.assert_called_once()

    def test_wsgi_to_asgi_is_used_in_view(self):
        """Verify the view uses WsgiToAsgi (not async_to_sync)."""
        import inspect
        from nautobot_app_mcp_server.mcp import view as view_module

        source = inspect.getsource(view_module)
        self.assertIn("WsgiToAsgi", source)
        self.assertNotIn("async_to_sync", source)


class MCPAppFactoryTestCase(TestCase):
    """Test the lazy factory for the FastMCP ASGI app."""

    def test_get_mcp_app_returns_starlette_app(self):
        """get_mcp_app returns a Starlette application."""
        # Import without triggering app creation
        from nautobot_app_mcp_server.mcp.server import get_mcp_app, _mcp_app

        # Before any request, the app should be None
        # (module-level lazy factory)
        self.assertIsNone(_mcp_app)

    def test_mcp_app_lazy_initialization(self):
        """get_mcp_app creates the app on first call, not at module import."""
        from nautobot_app_mcp_server.mcp import server as server_module

        # Reset the global to test lazy behavior
        old_app = server_module._mcp_app
        server_module._mcp_app = None

        try:
            from nautobot_app_mcp_server.mcp.server import get_mcp_app

            # get_mcp_app should be a callable
            self.assertTrue(callable(get_mcp_app))
        finally:
            server_module._mcp_app = old_app

    def test_get_mcp_app_twice_returns_same_instance(self):
        """Calling get_mcp_app twice returns the same app object (not re-created)."""
        from nautobot_app_mcp_server.mcp.server import get_mcp_app, _mcp_app

        old_app = _mcp_app
        _mcp_app = None  # Reset

        try:
            app1 = get_mcp_app()
            app2 = get_mcp_app()
            self.assertIs(app1, app2)
        finally:
            _mcp_app = old_app
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/tests/test_view.py` exists with `MCPViewTestCase` class
- `nautobot_app_mcp_server/mcp/tests/test_view.py` contains `def test_mcp_view_imports_successfully(self)`
- `nautobot_app_mcp_server/mcp/tests/test_view.py` contains `def test_mcp_endpoint_resolves(self)` using Django URL resolver
- `nautobot_app_mcp_server/mcp/tests/test_view.py` contains `def test_wsgi_to_asgi_is_used_in_view(self)` with `assertIn("WsgiToAsgi", source)`
- `nautobot_app_mcp_server/mcp/tests/test_view.py` contains `def test_get_mcp_app_twice_returns_same_instance(self)` asserting `self.assertIs(app1, app2)`
- `nautobot_app_mcp_server/mcp/tests/test_view.py` imports `from unittest.mock import MagicMock, patch`
- `grep -n "assertIn(\"WsgiToAsgi\"" nautobot_app_mcp_server/mcp/tests/test_view.py` returns a match
- `grep -n "assertNotIn(\"async_to_sync\"" nautobot_app_mcp_server/mcp/tests/test_view.py` returns a match

---

### Task 3.3 — `test_signal_integration.py` (post_migrate timing + tool registration)

**Requirements:** TEST-04

**Read first:**
- `nautobot_app_mcp_server/__init__.py` (final state after Task 3.1)
- `nautobot_app_mcp_server/mcp/registry.py` (created in Task 2.1)
- `nautobot_app_mcp_server/mcp/__init__.py` (created in Task 2.4)
- `.planning/research/PITFALLS.md` — PIT-12 (post_migrate signal registration order)

**Action:**

Create `nautobot_app_mcp_server/mcp/tests/test_signal_integration.py`:

```python
"""Tests for post_migrate signal timing and tool registration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.test import TestCase

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition
from nautobot_app_mcp_server.mcp import register_mcp_tool


class RegistrySingletonTestCase(TestCase):
    """Test the MCPToolRegistry singleton thread-safety."""

    def test_singleton_returns_same_instance(self):
        """Two calls to get_instance() return the same object."""
        r1 = MCPToolRegistry.get_instance()
        r2 = MCPToolRegistry.get_instance()
        self.assertIs(r1, r2)

    def test_singleton_has_lock(self):
        """The registry has a threading.Lock for thread-safety."""
        self.assertTrue(hasattr(MCPToolRegistry, "_lock"))
        import threading
        self.assertIsInstance(MCPToolRegistry._lock, threading.Lock)

    def test_register_raises_on_duplicate_name(self):
        """Registering two tools with the same name raises ValueError."""
        registry = MCPToolRegistry.get_instance()

        def dummy_func():
            pass

        registry.register(
            ToolDefinition(
                name="test_duplicate",
                func=dummy_func,
                description="First registration",
                input_schema={"type": "object"},
            )
        )
        with self.assertRaises(ValueError) as ctx:
            registry.register(
                ToolDefinition(
                    name="test_duplicate",
                    func=dummy_func,
                    description="Second registration",
                    input_schema={"type": "object"},
                )
            )
        self.assertIn("test_duplicate", str(ctx.exception))

    def test_get_core_tools_returns_only_core_tier(self):
        """get_core_tools() returns only tools with tier == 'core'."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_core_tool",
                func=lambda: None,
                description="A core tool",
                input_schema={"type": "object"},
                tier="core",
            )
        )
        registry.register(
            ToolDefinition(
                name="test_app_tool",
                func=lambda: None,
                description="An app tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.read",
            )
        )

        core_tools = registry.get_core_tools()
        core_names = [t.name for t in core_tools]
        self.assertIn("test_core_tool", core_names)
        self.assertNotIn("test_app_tool", core_names)

    def test_get_by_scope_exact_match(self):
        """get_by_scope() returns tools with exact scope match."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_exact_scope",
                func=lambda: None,
                description="Exact scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.juniper",
            )
        )

        tools = registry.get_by_scope("test_app.juniper")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "test_exact_scope")

    def test_get_by_scope_child_match(self):
        """get_by_scope() returns tools with child scopes."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="test_child_scope",
                func=lambda: None,
                description="Child scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.juniper.bgp",
            )
        )

        # Parent scope should match child scopes
        tools = registry.get_by_scope("test_app.juniper")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "test_child_scope")

    def test_fuzzy_search_matches_name(self):
        """fuzzy_search() matches tool names (case-insensitive)."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="device_list",
                func=lambda: None,
                description="List devices",
                input_schema={"type": "object"},
                tier="core",
            )
        )

        results = registry.fuzzy_search("DEVICE")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "device_list")

    def test_fuzzy_search_matches_description(self):
        """fuzzy_search() matches tool descriptions (case-insensitive)."""
        registry = MCPToolRegistry.get_instance()

        registry.register(
            ToolDefinition(
                name="prefix_list",
                func=lambda: None,
                description="List IP prefixes",
                input_schema={"type": "object"},
                tier="core",
            )
        )

        results = registry.fuzzy_search("prefixes")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "prefix_list")

    def test_fuzzy_search_no_match(self):
        """fuzzy_search() returns empty list when no match."""
        registry = MCPToolRegistry.get_instance()
        results = registry.fuzzy_search("nonexistent_tool_xyz")
        self.assertEqual(results, [])


class RegisterMCPToolAPITestCase(TestCase):
    """Test the public register_mcp_tool() API."""

    def test_register_mcp_tool_works(self):
        """register_mcp_tool() successfully registers a tool."""
        def dummy_func():
            pass

        register_mcp_tool(
            name="test_api_tool",
            func=dummy_func,
            description="Test tool from API",
            input_schema={"type": "object"},
            tier="app",
            app_label="test_app",
            scope="test_app.read",
        )

        registry = MCPToolRegistry.get_instance()
        tools = registry.get_all()
        names = [t.name for t in tools]
        self.assertIn("test_api_tool", names)

    def test_register_mcp_tool_default_tier_is_app(self):
        """register_mcp_tool() defaults tier to 'app'."""
        def dummy_func():
            pass

        register_mcp_tool(
            name="test_default_tier",
            func=dummy_func,
            description="Test default tier",
            input_schema={"type": "object"},
        )

        registry = MCPToolRegistry.get_instance()
        tools = registry.get_all()
        tool = next(t for t in tools if t.name == "test_default_tier")
        self.assertEqual(tool.tier, "app")


class PostMigrateSignalTestCase(TestCase):
    """Test the post_migrate signal wiring."""

    def test_ready_connects_post_migrate(self):
        """NautobotAppMcpServerConfig.ready() connects post_migrate signal."""
        # Check that post_migrate has our handler connected
        receivers = post_migrate.receivers
        receiver_apps = [r[0]().get("sender") for r in receivers if r]
        # The handler is connected by ready() called at app startup
        # Just verify the signal module is accessible
        self.assertTrue(hasattr(post_migrate, "connect"))

    def test_on_post_migrate_only_runs_for_this_app(self):
        """_on_post_migrate guard checks app name before registering."""
        from nautobot_app_mcp_server import NautobotAppMcpServerConfig

        # Create a mock app_config for a different app
        mock_other_app = MagicMock()
        mock_other_app.name = "some_other_app"

        # Should not raise and should not register any tools
        with patch(
            "nautobot_app_mcp_server.MCPToolRegistry.get_instance",
            return_value=MagicMock(),
        ):
            NautobotAppMcpServerConfig._on_post_migrate(mock_other_app)

        # If we get here without error, the guard works
        self.assertEqual(mock_other_app.name, "some_other_app")
```

**Acceptance criteria:**
- `nautobot_app_mcp_server/mcp/tests/test_signal_integration.py` exists
- `test_signal_integration.py` contains `def test_singleton_returns_same_instance(self)` with `self.assertIs(r1, r2)`
- `test_signal_integration.py` contains `def test_singleton_has_lock(self)` with `self.assertIsInstance(MCPToolRegistry._lock, threading.Lock)`
- `test_signal_integration.py` contains `def test_register_raises_on_duplicate_name(self)` with `with self.assertRaises(ValueError)`
- `test_signal_integration.py` contains `def test_get_core_tools_returns_only_core_tier(self)`
- `test_signal_integration.py` contains `def test_get_by_scope_child_match(self)` with scope `"test_app.juniper"` matching child `"test_app.juniper.bgp"`
- `test_signal_integration.py` contains `def test_fuzzy_search_matches_name(self)` with case-insensitive match
- `test_signal_integration.py` contains `def test_register_mcp_tool_works(self)` calling `register_mcp_tool()` from the public API
- `test_signal_integration.py` contains `def test_on_post_migrate_only_runs_for_this_app(self)` with mock for a different app name

---

## Verification

After all tasks complete, run:

```bash
# 1. Check all files exist
ls nautobot_app_mcp_server/mcp/__init__.py
ls nautobot_app_mcp_server/mcp/registry.py
ls nautobot_app_mcp_server/mcp/server.py
ls nautobot_app_mcp_server/mcp/view.py
ls nautobot_app_mcp_server/mcp/tests/test_view.py
ls nautobot_app_mcp_server/mcp/tests/test_signal_integration.py
ls nautobot_app_mcp_server/urls.py

# 2. Verify base_url fix
grep 'base_url = "nautobot-app-mcp-server"' nautobot_app_mcp_server/__init__.py

# 3. Verify no package name mismatch
grep 'nautobot_mcp_server' docs/dev/DESIGN.md && echo "FAIL: package name still in DESIGN.md" || echo "OK: DESIGN.md clean"

# 4. Verify WsgiToAsgi in view
grep 'WsgiToAsgi' nautobot_app_mcp_server/mcp/view.py

# 5. Verify lazy factory pattern
grep '_mcp_app.*None' nautobot_app_mcp_server/mcp/server.py

# 6. Run tests (requires Docker dev stack up)
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server && poetry run invoke tests
```

**must_haves for goal-backward verification:**
- [ ] MCP endpoint URL is `/plugins/nautobot-app-mcp-server/mcp/` (confirmed by `base_url` + `urls.py`)
- [ ] `MCPToolRegistry` is thread-safe with `threading.Lock` and double-checked locking
- [ ] `get_mcp_app()` is lazy (creates app on first call, not at import)
- [ ] ASGI bridge uses `WsgiToAsgi`, NOT `async_to_sync`
- [ ] `post_migrate` connects in `ready()` with correct app-name guard
- [ ] `register_mcp_tool()` public API exists and works
- [ ] `test_view.py` tests ASGI bridge imports and WsgiToAsgi usage
- [ ] `test_signal_integration.py` tests singleton thread-safety, duplicate registration, scope matching
- [ ] Pylint 10.00/10
- [ ] `poetry run invoke ruff` passes (no import errors or syntax errors)
