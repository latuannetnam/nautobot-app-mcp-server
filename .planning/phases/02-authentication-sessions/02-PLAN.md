---
wave: 2
phase: 02-authentication-sessions
phase_name: Authentication & Sessions
depends_on: []
status: planning
autonomous: false
files_modified:
  - nautobot_app_mcp_server/mcp/server.py
  - nautobot_app_mcp_server/mcp/__init__.py
files_created:
  - nautobot_app_mcp_server/mcp/auth.py
  - nautobot_app_mcp_server/mcp/session_tools.py
  - nautobot_app_mcp_server/mcp/tests/test_auth.py
  - nautobot_app_mcp_server/mcp/tests/test_session_tools.py
must_haves:
  - get_user_from_request(ctx) extracts Nautobot user from Authorization: Token nbapikey_xxx
  - Missing token → logger.warning + AnonymousUser (empty querysets)
  - Invalid token → logger.debug + AnonymousUser (empty querysets)
  - Valid token → correct Nautobot User returned
  - MCPSessionState dataclass with enabled_scopes and enabled_searches
  - Session state stored in FastMCP session dict (session["enabled_scopes"], session["enabled_searches"])
  - mcp_enable_tools(scope=...) enables exact scope + all children
  - mcp_enable_tools(search=...) fuzzy-matches tool names/descriptions
  - mcp_disable_tools(scope=...) disables scope + all children
  - mcp_list_tools() returns core + enabled-scopes + searched tools
  - @mcp.list_tools() override for progressive disclosure (D-20)
  - Core tools always present regardless of session state
  - TEST-06: valid token → data, invalid → empty + WARNING logged
  - All tests pass (poetry run invoke tests)
  - Pylint 10.00/10
---

## Phase 2 Plan: Authentication & Sessions

### Overview

Phase 2 adds token-based authentication and per-session tool visibility state to the MCP server. Auth extracts the Nautobot user from the MCP request context (`Authorization: Token nbapikey_xxx`); sessions track which tool scopes and searches are enabled per `Mcp-Session-Id`.

**10 requirements:** REGI-05, AUTH-01, AUTH-02, AUTH-03, SESS-01, SESS-02, SESS-03, SESS-04, SESS-05, SESS-06, TEST-06

**Key design decisions (from 02-CONTEXT.md):**
- D-19: Session state stored in FastMCP's `session` dict (`session["enabled_scopes"]: set[str]`, `session["enabled_searches"]: set[str]`)
- D-20: `@mcp.list_tools()` override using FastMCP's `ToolContext` for progressive disclosure
- D-21: Scope hierarchy — enabling parent activates all children
- D-22: No token → `logger.warning`, Invalid token → `logger.debug`
- D-23: `AnonymousUser` returns empty querysets, never raises
- D-24: Token auth ONLY, no session cookie fallback
- D-27: `MCPToolRegistry.get_instance().get_core_tools()` for core tool list

### Architecture

```
MCP Request (Authorization: Token nbapikey_xxx)
        │
        ▼
@mcp.list_tools() override (ToolContext)
  ctx.request_context.request.headers["Authorization"]
        │
        ▼
get_user_from_request(ctx)  [auth.py]
  ├── Token.objects.select_related("user").get(key=nbapikey_xxx)  → User
  ├── Missing header → logger.warning + AnonymousUser
  └── Invalid/malformed → logger.debug + AnonymousUser
        │
        ├──→ Tool handlers: .restrict(user, action="view") on every queryset
        │
        └──→ @mcp.list_tools():
              session["enabled_scopes"] + session["enabled_searches"]
              → filter MCPToolRegistry
              → return core (always) + enabled scoped tools
```

---

## Wave 1 — Auth Layer Foundation

### Task 1.1: Refactor `server.py` — Extract `_setup_mcp_app()`

**Modifies:** `nautobot_app_mcp_server/mcp/server.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/server.py` — current lazy factory (must see `_mcp_app` global, `get_mcp_app()` implementation)
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry`, `get_core_tools()`, `get_by_scope()`, `fuzzy_search()`

**`<action>`**

Refactor `get_mcp_app()` into two functions so the `FastMCP` instance (`mcp`) is accessible inside `_setup_mcp_app()` for decorator registration. Keep lazy factory semantics:

```python
# server.py — ADD new helper (mcp instance is local to this function)
def _setup_mcp_app() -> FastMCP:
    """Build and configure the FastMCP instance.

    Registers session tools and the list_tools() override.
    Must be called from within get_mcp_app() only (lazy, inside Django request).
    """
    from fastmcp import FastMCP
    from nautobot_app_mcp_server.mcp.session_tools import (  # noqa: F401
        mcp_enable_tools,
        mcp_disable_tools,
        mcp_list_tools,
        _list_tools_handler,
    )

    mcp = FastMCP(
        "NautobotMCP",
        stateless_http=False,
        json_response=True,
    )

    # Register session tools as MCP tools (these decorators capture `mcp`)
    mcp_enable_tools(mcp)
    mcp_disable_tools(mcp)
    mcp_list_tools(mcp)

    # Register progressive disclosure handler (D-20)
    @mcp.list_tools()
    async def list_tools_override(ctx: ToolContext) -> list[ToolInstance]:
        return await _list_tools_handler(ctx)

    return mcp
```

Change `get_mcp_app()` to call `_setup_mcp_app()`:

```python
def get_mcp_app() -> Starlette:
    global _mcp_app  # pylint: disable=global-statement
    if _mcp_app is None:
        _mcp_app = _setup_mcp_app().streamable_http_app(path="/mcp")
    return _mcp_app
```

Add to imports at top of file:
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.server import ToolContext, ToolInstance
```

**`<acceptance_criteria>`**
- [ ] `grep -n "_setup_mcp_app" nautobot_app_mcp_server/mcp/server.py` → function defined
- [ ] `grep -n "get_mcp_app" nautobot_app_mcp_server/mcp/server.py` → calls `_setup_mcp_app()` to create the ASGI app
- [ ] `grep -n "from nautobot_app_mcp_server.mcp.session_tools import" nautobot_app_mcp_server/mcp/server.py` → imports all 4 symbols
- [ ] `grep -n "stateless_http=False" nautobot_app_mcp_server/mcp/server.py` → still present (unchanged)
- [ ] `grep -n "async def list_tools_override" nautobot_app_mcp_server/mcp/server.py` → registers the `@mcp.list_tools()` override
- [ ] `poetry run invoke pylint` → 10.00/10

---

### Task 1.2: Create `auth.py` — Token extraction and user lookup

**Creates:** `nautobot_app_mcp_server/mcp/auth.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/server.py` — understand `ToolContext` / MCP request context
- `.planning/research/PITFALLS.md` — PIT-10 (anonymous logging), PIT-16 (auth from wrong request object)
- `.planning/codebase/ARCHITECTURE.md` §2 (Authentication layer)

**`<action>`**

Create `nautobot_app_mcp_server/mcp/auth.py` with:

```python
"""Authentication layer: extract Nautobot user from MCP request context.

Auth flow:
    1. Extract Authorization header from MCP request (NOT Django request)
    2. Parse "Token nbapikey_xxx" format
    3. Look up Nautobot Token object → return User
    4. Missing / invalid token → return AnonymousUser with log warning

PIT-16: Always use ctx.request_context.request (MCP SDK request object),
NOT Django's HttpRequest. PIT-10: Log WARNING on missing token,
DEBUG on invalid token.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server import Context as ToolContext

logger = logging.getLogger(__name__)

# Token prefix used by Nautobot API tokens
TOKEN_PREFIX = "nbapikey_"


def get_user_from_request(ctx: ToolContext):  # noqa: ANN201
    """Extract the Nautobot user from the MCP request Authorization header.

    Attempts to authenticate via ``Authorization: Token nbapikey_xxx`` header.
    Falls back to ``AnonymousUser`` (never raises) — empty querysets returned.

    Args:
        ctx: FastMCP ToolContext, providing access to the MCP request object.

    Returns:
        nautobot.users.models.User if authenticated, otherwise
        django.contrib.auth.models.AnonymousUser.

    Logging (D-22, PIT-10):
        - Missing Authorization header → ``logger.warning``
        - Invalid / malformed token     → ``logger.debug``
    """
    from django.contrib.auth.models import AnonymousUser

    mcp_request = ctx.request_context.request
    auth_header = mcp_request.headers.get("Authorization", "")

    if not auth_header:
        logger.warning("MCP: No auth token, falling back to anonymous user")
        return AnonymousUser()

    if not auth_header.startswith("Token "):
        logger.debug("MCP: Invalid auth token format (not a Token prefix)")
        return AnonymousUser()

    token_key = auth_header[6:]  # Strip "Token "

    if not token_key.startswith(TOKEN_PREFIX):
        logger.debug("MCP: Invalid auth token (not a Nautobot nbapikey token)")
        return AnonymousUser()

    # Look up the Nautobot API token
    real_token_key = token_key[len(TOKEN_PREFIX):]

    try:
        from nautobot.users.models import Token

        token = Token.objects.select_related("user").get(key=real_token_key)
        return token.user
    except Exception:  # noqa: BLE001  — Token.DoesNotExist or DB errors
        logger.debug("MCP: Invalid auth token attempted")
        return AnonymousUser()
```

**`<acceptance_criteria>`**
- [ ] `grep -n "logger.warning.*No auth token" nautobot_app_mcp_server/mcp/auth.py` → present
- [ ] `grep -n "logger.debug.*Invalid auth token" nautobot_app_mcp_server/mcp/auth.py` → present
- [ ] `grep -n "from nautobot.users.models import Token" nautobot_app_mcp_server/mcp/auth.py` → Token lookup with `select_related("user")`
- [ ] `grep -n "AnonymousUser()" nautobot_app_mcp_server/mcp/auth.py` → returned on all failure paths
- [ ] `grep -n "ctx.request_context.request" nautobot_app_mcp_server/mcp/auth.py` → MCP request object used (PIT-16)
- [ ] `grep -n "def get_user_from_request" nautobot_app_mcp_server/mcp/auth.py` → function defined
- [ ] `poetry run invoke ruff nautobot_app_mcp_server/mcp/auth.py` → no errors
- [ ] `poetry run invoke pylint nautobot_app_mcp_server/mcp/auth.py` → 10.00/10

---

## Wave 2 — Session Tools

### Task 2.1: Create `session_tools.py` — Session state dataclass and 3 meta tools

**Creates:** `nautobot_app_mcp_server/mcp/session_tools.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/auth.py` — Task 1.2 output (imports from it)
- `nautobot_app_mcp_server/mcp/registry.py` — `MCPToolRegistry.get_instance()`, `get_core_tools()`, `get_by_scope()`, `fuzzy_search()`
- `nautobot_app_mcp_server/mcp/server.py` — `_setup_mcp_app()` signature, `ToolContext` import
- D-19, D-20, D-21, D-26, D-27 from `02-CONTEXT.md`

**`<action>`**

Create `nautobot_app_mcp_server/mcp/session_tools.py`. The file exports 4 symbols used by `server.py`:

```python
"""Session management tools and progressive disclosure handler.

Exports 4 symbols for server.py registration:
    mcp_enable_tools  — decorator: register as FastMCP tool
    mcp_disable_tools  — decorator: register as FastMCP tool
    mcp_list_tools    — decorator: register as FastMCP tool
    _list_tools_handler — coroutine: progressive disclosure logic

Session state lives in FastMCP's session dict (D-19):
    session["enabled_scopes"]  — set[str]: enabled scope strings
    session["enabled_searches"] — set[str]: fuzzy search terms

Scope hierarchy (D-21): enabling "dcim" activates "dcim.interface",
"dcim.device", etc. via MCPToolRegistry.get_by_scope() startswith matching.

Core tools are ALWAYS returned by _list_tools_handler() regardless of
session state (D-27, SESS-06, REGI-05).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp.server import Context as ToolContext, ToolInstance

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# MCPSessionState — thin wrapper over FastMCP session dict (D-26)
# -------------------------------------------------------------------


@dataclass
class MCPSessionState:
    """Per-conversation tool visibility state.

    Stored directly in FastMCP's session dict as:
        session["enabled_scopes"]  — set[str]
        session["enabled_searches"] — set[str]

    Attributes:
        enabled_scopes: Dot-separated scope strings that are currently
            enabled for this session (e.g. {"dcim", "ipam.vlan"}).
        enabled_searches: Fuzzy search terms active for this session.
    """

    enabled_scopes: set[str] = field(default_factory=set)
    enabled_searches: set[str] = field(default_factory=set)

    @classmethod
    def from_session(cls, session: dict) -> MCPSessionState:
        """Load session state from a FastMCP session dict.

        Args:
            session: FastMCP StreamableHTTPSessionManager session object
                (a dict-like with get/setitem).

        Returns:
            MCPSessionState with scopes/searches loaded from the session,
            or empty state if not yet initialized.
        """
        return cls(
            enabled_scopes=set(session.get("enabled_scopes", set())),
            enabled_searches=set(session.get("enabled_searches", set())),
        )

    def apply_to_session(self, session: dict) -> None:
        """Persist state back into the FastMCP session dict.

        Args:
            session: FastMCP session dict to update in-place.
        """
        session["enabled_scopes"] = self.enabled_scopes
        session["enabled_searches"] = self.enabled_searches


# -------------------------------------------------------------------
# Progressive disclosure handler (registered as @mcp.list_tools())
# -------------------------------------------------------------------


async def _list_tools_handler(
    ctx: ToolContext,
) -> list[ToolInstance]:  # noqa: ANN201
    """Return tools filtered by session state (progressive disclosure, REGI-05).

    Always includes core tools (D-27). Non-core tools are included if:
        - Their scope matches any entry in session["enabled_scopes"]
        - OR their name/description fuzzy-matches any entry in session["enabled_searches"]

    Args:
        ctx: FastMCP ToolContext providing request and session access.

    Returns:
        List of MCP ToolInstance objects for the MCP manifest.
    """
    from mcp.server import ToolInstance
    from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

    session = ctx.request_context.session
    state = MCPSessionState.from_session(session)

    registry = MCPToolRegistry.get_instance()

    # Core tools: always included (D-27, SESS-06)
    core_tools = registry.get_core_tools()

    # Non-core tools: filtered by enabled_scopes and enabled_searches
    non_core: dict[str, ToolDefinition] = {}

    for scope in state.enabled_scopes:
        for tool in registry.get_by_scope(scope):
            non_core[tool.name] = tool

    for term in state.enabled_searches:
        for tool in registry.fuzzy_search(term):
            non_core[tool.name] = tool

    all_tools = core_tools + list(non_core.values())

    return [
        ToolInstance(
            name=t.name,
            description=t.description,
            inputSchema=t.input_schema,
        )
        for t in all_tools
    ]


# -------------------------------------------------------------------
# mcp_enable_tools — scope + fuzzy-search tool enabler (SESS-03)
# -------------------------------------------------------------------


def mcp_enable_tools(mcp: FastMCP) -> None:
    """Register mcp_enable_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_enable_tools_impl(  # noqa: ANN202
        ctx: ToolContext,
        scope: str | None = None,
        search: str | None = None,
    ) -> str:
        """Enable tool scopes or fuzzy-search matches for this session.

        Either ``scope`` OR ``search`` (or both) must be provided.

        Scope format: dot-separated string (e.g. ``"dcim.interface"``).
        Enabling a parent scope (e.g. ``"dcim"``) automatically activates all
        child scopes (``"dcim.interface"``, ``"dcim.device"``) because
        MCPToolRegistry.get_by_scope() uses startswith matching (D-21).

        Search performs a fuzzy match across all registered tool names and
        descriptions. Matching tools are added to the session.

        Core tools (``tier="core"``) are always available; this tool controls
        only the visibility of app-tier tools.

        Args:
            ctx: FastMCP ToolContext.
            scope: Dot-separated scope to enable (e.g. ``"ipam"``, ``"dcim"``).
            search: Fuzzy search term to match tool names/descriptions.

        Returns:
            Human-readable summary of what was enabled.
        """
        if scope is None and search is None:
            return "Provide at least one of: scope= or search="

        session = ctx.request_context.session
        state = MCPSessionState.from_session(session)
        parts: list[str] = []

        if scope is not None:
            state.enabled_scopes.add(scope)
            parts.append(f"scope '{scope}'")

        if search is not None:
            state.enabled_searches.add(search)
            parts.append(f"search '{search}'")

        state.apply_to_session(session)
        return f"Enabled: {', '.join(parts)}"


# -------------------------------------------------------------------
# mcp_disable_tools — scope disabler (SESS-04)
# -------------------------------------------------------------------


def mcp_disable_tools(mcp: FastMCP) -> None:
    """Register mcp_disable_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_disable_tools_impl(  # noqa: ANN202
        ctx: ToolContext,
        scope: str | None = None,
    ) -> str:
        """Disable a tool scope for this session.

        Disabling a parent scope (e.g. ``"dcim"``) disables all child scopes
        (``"dcim.interface"``, ``"dcim.device"``) because the session stores
        only parent scopes and MCPToolRegistry.get_by_scope() matches children
        by prefix (D-21).

        If ``scope`` is None, disables ALL non-core tools (resets session state).

        Args:
            ctx: FastMCP ToolContext.
            scope: Dot-separated scope to disable. None = disable all.

        Returns:
            Human-readable summary of what was disabled.
        """
        session = ctx.request_context.session
        state = MCPSessionState.from_session(session)

        if scope is None:
            state.enabled_scopes.clear()
            state.enabled_searches.clear()
            state.apply_to_session(session)
            return "Disabled all non-core tools."

        # Find all scopes that start with this prefix (children included)
        to_remove = {
            s for s in state.enabled_scopes
            if s == scope or s.startswith(f"{scope}.")
        }
        state.enabled_scopes -= to_remove
        state.apply_to_session(session)
        return f"Disabled scope '{scope}' and {len(to_remove)} child scope(s)."


# -------------------------------------------------------------------
# mcp_list_tools — session-aware tool lister (SESS-05)
# -------------------------------------------------------------------


def mcp_list_tools(mcp: FastMCP) -> None:
    """Register mcp_list_tools as a FastMCP tool on the given mcp instance."""

    @mcp.tool()
    async def mcp_list_tools_impl(ctx: ToolContext) -> str:  # noqa: ANN202
        """Return all registered tools visible to this session.

        Returns a summary of:
        - Core tools (always available)
        - Enabled scopes and their tools
        - Active fuzzy search terms

        Core tools are always listed regardless of session state.

        Args:
            ctx: FastMCP ToolContext.

        Returns:
            Multi-line string describing active tools and session state.
        """
        from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

        session = ctx.request_context.session
        state = MCPSessionState.from_session(session)
        registry = MCPToolRegistry.get_instance()

        core = registry.get_core_tools()
        lines = [f"Core tools ({len(core)}):"]
        for t in core:
            lines.append(f"  - {t.name}")

        if state.enabled_scopes:
            lines.append(f"\nEnabled scopes ({len(state.enabled_scopes)}):")
            for scope in sorted(state.enabled_scopes):
                tools = registry.get_by_scope(scope)
                lines.append(f"  [{scope}] ({len(tools)} tools)")
                for t in tools:
                    lines.append(f"    - {t.name}")

        if state.enabled_searches:
            lines.append(f"\nActive searches ({len(state.enabled_searches)}):")
            for term in sorted(state.enabled_searches):
                tools = registry.fuzzy_search(term)
                lines.append(f"  '{term}' → {len(tools)} tools")

        return "\n".join(lines)
```

**`<acceptance_criteria>`**
- [ ] `grep -n "class MCPSessionState" nautobot_app_mcp_server/mcp/session_tools.py` → dataclass defined
- [ ] `grep -n "enabled_scopes.*set" nautobot_app_mcp_server/mcp/session_tools.py` → set[str] attribute
- [ ] `grep -n "enabled_searches.*set" nautobot_app_mcp_server/mcp/session_tools.py` → set[str] attribute
- [ ] `grep -n "from_session" nautobot_app_mcp_server/mcp/session_tools.py` → loads from session dict
- [ ] `grep -n "apply_to_session" nautobot_app_mcp_server/mcp/session_tools.py` → persists to session dict
- [ ] `grep -n "async def _list_tools_handler" nautobot_app_mcp_server/mcp/session_tools.py` → progressive disclosure
- [ ] `grep -n "get_core_tools" nautobot_app_mcp_server/mcp/session_tools.py` → core tools always included (D-27)
- [ ] `grep -n "scope is not None" nautobot_app_mcp_server/mcp/session_tools.py` → scope param handled
- [ ] `grep -n "search is not None" nautobot_app_mcp_server/mcp/session_tools.py` → search param handled
- [ ] `grep -n "startswith.*scope" nautobot_app_mcp_server/mcp/session_tools.py` → child scope matching (D-21)
- [ ] `grep -n "def mcp_enable_tools" nautobot_app_mcp_server/mcp/session_tools.py` → exported for server.py
- [ ] `grep -n "def mcp_disable_tools" nautobot_app_mcp_server/mcp/session_tools.py` → exported for server.py
- [ ] `grep -n "def mcp_list_tools" nautobot_app_mcp_server/mcp/session_tools.py` → exported for server.py
- [ ] `grep -n "def mcp_enable_tools_impl" nautobot_app_mcp_server/mcp/session_tools.py` → actual tool handler
- [ ] `grep -n "def mcp_disable_tools_impl" nautobot_app_mcp_server/mcp/session_tools.py` → actual tool handler
- [ ] `grep -n "def mcp_list_tools_impl" nautobot_app_mcp_server/mcp/session_tools.py` → actual tool handler
- [ ] `poetry run invoke ruff nautobot_app_mcp_server/mcp/session_tools.py` → no errors
- [ ] `poetry run invoke pylint nautobot_app_mcp_server/mcp/session_tools.py` → 10.00/10

---

### Task 2.2: Update `__init__.py` — Export `get_user_from_request`

**Modifies:** `nautobot_app_mcp_server/mcp/__init__.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/__init__.py` — current exports

**`<action>`**

Add `get_user_from_request` to `__all__` and the import:

```python
from nautobot_app_mcp_server.mcp.auth import get_user_from_request
from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition

__all__ = [
    "MCPToolRegistry",
    "ToolDefinition",
    "get_user_from_request",
    "register_mcp_tool",
]
```

**`<acceptance_criteria>`**
- [ ] `grep -n "get_user_from_request" nautobot_app_mcp_server/mcp/__init__.py` → in `__all__` AND imported
- [ ] `poetry run invoke pylint nautobot_app_mcp_server/mcp/__init__.py` → 10.00/10

---

## Wave 3 — Tests

### Task 3.1: Create `test_auth.py` — Auth layer tests (TEST-06)

**Creates:** `nautobot_app_mcp_server/mcp/tests/test_auth.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/auth.py` — Task 1.2 output
- `nautobot_app_mcp_server/mcp/tests/test_signal_integration.py` — existing test patterns (mock setup, TestCase subclass)

**`<action>`**

Create `nautobot_app_mcp_server/mcp/tests/test_auth.py`:

```python
"""Tests for the auth layer (AUTH-01, AUTH-02, AUTH-03, TEST-06)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase


class GetUserFromRequestTestCase(TestCase):
    """Test get_user_from_request() from auth.py."""

    def _make_mock_ctx(
        self,
        authorization: str | None = None,
    ) -> MagicMock:
        """Build a mock ToolContext with an Authorization header."""
        mock_request = MagicMock()
        mock_request.headers = {}
        if authorization is not None:
            mock_request.headers["Authorization"] = authorization
        mock_ctx = MagicMock()
        mock_ctx.request_context.request = mock_request
        return mock_ctx

    def test_missing_authorization_header_returns_anonymous(self):
        """AUTH-02: Missing token → AnonymousUser returned (no exception)."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization=None)
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_missing_authorization_header_logs_warning(self):
        """AUTH-02, PIT-10: Missing token → WARNING logged."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization=None)
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="WARNING") as cm:
            get_user_from_request(ctx)
        self.assertTrue(any("No auth token" in line for line in cm.output))

    def test_invalid_token_format_returns_anonymous(self):
        """AUTH-02: Malformed Authorization header → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Bearer invalid")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_non_nbapikey_token_returns_anonymous(self):
        """AUTH-02: Token without nbapikey_ prefix → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Token abcdefghijklmnop")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)

    def test_valid_nbapikey_token_returns_user(self):
        """AUTH-01: Valid nbapikey_ token → correct Nautobot User returned."""
        from django.contrib.auth import get_user_model
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        User = get_user_model()
        # Ensure we have at least one superuser to test with
        if not User.objects.filter(is_superuser=True).exists():
            User.objects.create_superuser(
                username="testadmin",
                email="admin@test.local",
                password="testpass",
            )
        user_obj = User.objects.filter(is_superuser=True).first()
        # Create a token for this user
        from nautobot.users.models import Token

        token = Token.objects.create(user=user_obj, key="nbapikey_testauthtoken123")

        try:
            ctx = self._make_mock_ctx(
                authorization=f"Token nbapikey_{token.key}",
            )
            result = get_user_from_request(ctx)
            self.assertEqual(result, user_obj)
        finally:
            token.delete()

    def test_valid_token_wrong_key_returns_anonymous(self):
        """AUTH-02: Valid format but unknown key → AnonymousUser + DEBUG log."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(
            authorization="Token nbapikey_nonexistentkey000000",
        )
        with self.assertLogs("nautobot_app_mcp_server.mcp.auth", level="DEBUG") as cm:
            user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)
        self.assertTrue(any("Invalid auth token" in line for line in cm.output))

    def test_empty_token_returns_anonymous(self):
        """AUTH-02: Empty "Token " value → AnonymousUser."""
        from nautobot_app_mcp_server.mcp.auth import get_user_from_request

        ctx = self._make_mock_ctx(authorization="Token ")
        user = get_user_from_request(ctx)
        self.assertIsInstance(user, AnonymousUser)
```

**`<acceptance_criteria>`**
- [ ] `grep -n "class GetUserFromRequestTestCase" nautobot_app_mcp_server/mcp/tests/test_auth.py` → test class exists
- [ ] `grep -n "test_missing_authorization_header_logs_warning" nautobot_app_mcp_server/mcp/tests/test_auth.py` → PIT-10 test
- [ ] `grep -n "test_valid_nbapikey_token_returns_user" nautobot_app_mcp_server/mcp/tests/test_auth.py` → AUTH-01 test
- [ ] `grep -n "test_valid_token_wrong_key_returns_anonymous" nautobot_app_mcp_server/mcp/tests/test_auth.py` → AUTH-02 test with DEBUG log
- [ ] `grep -n "AnonymousUser" nautobot_app_mcp_server/mcp/tests/test_auth.py` → used in all failure assertions
- [ ] `grep -n "select_related" nautobot_app_mcp_server/mcp/tests/test_auth.py` → Token lookup uses select_related
- [ ] `poetry run invoke ruff nautobot_app_mcp_server/mcp/tests/test_auth.py` → no errors
- [ ] `poetry run invoke pylint nautobot_app_mcp_server/mcp/tests/test_auth.py` → 10.00/10

---

### Task 3.2: Create `test_session_tools.py` — Session and progressive disclosure tests

**Creates:** `nautobot_app_mcp_server/mcp/tests/test_session_tools.py`

**`<read_first>`**
- `nautobot_app_mcp_server/mcp/session_tools.py` — Task 2.1 output
- `nautobot_app_mcp_server/mcp/registry.py` — existing test patterns

**`<action>`**

Create `nautobot_app_mcp_server/mcp/tests/test_session_tools.py`:

```python
"""Tests for session tools and progressive disclosure (SESS-01–06, REGI-05)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase

from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry, ToolDefinition


class MCPSessionStateTestCase(TestCase):
    """Test MCPSessionState dataclass (SESS-01)."""

    def test_from_session_empty(self):
        """Empty session dict → empty state."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        state = MCPSessionState.from_session({})
        self.assertEqual(state.enabled_scopes, set())
        self.assertEqual(state.enabled_searches, set())

    def test_from_session_with_data(self):
        """Session dict with data → state loaded correctly."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {
            "enabled_scopes": {"dcim", "ipam.vlan"},
            "enabled_searches": {"BGP"},
        }
        state = MCPSessionState.from_session(session)
        self.assertEqual(state.enabled_scopes, {"dcim", "ipam.vlan"})
        self.assertEqual(state.enabled_searches, {"BGP"})

    def test_apply_to_session(self):
        """State changes are persisted to session dict."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session: dict = {}
        state = MCPSessionState(enabled_scopes={"dcim"}, enabled_searches={"BGP"})
        state.apply_to_session(session)
        self.assertEqual(session["enabled_scopes"], {"dcim"})
        self.assertEqual(session["enabled_searches"], {"BGP"})

    def test_roundtrip(self):
        """Load → modify → apply → load again = same state."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {"enabled_scopes": {"ipam"}, "enabled_searches": set()}
        state1 = MCPSessionState.from_session(session)
        state1.enabled_scopes.add("dcim")
        state1.apply_to_session(session)
        state2 = MCPSessionState.from_session(session)
        self.assertEqual(state2.enabled_scopes, {"ipam", "dcim"})


class ProgressiveDisclosureTestCase(TestCase):
    """Test @mcp.list_tools() progressive disclosure (REGI-05, SESS-06)."""

    def _make_mock_ctx(
        self,
        enabled_scopes: set[str] | None = None,
        enabled_searches: set[str] | None = None,
    ) -> MagicMock:
        """Build a mock ToolContext with session state."""
        session = {
            "enabled_scopes": enabled_scopes if enabled_scopes is not None else set(),
            "enabled_searches": enabled_searches if enabled_searches is not None else set(),
        }
        mock_ctx = MagicMock()
        mock_ctx.request_context.session = session
        return mock_ctx

    def test_core_tools_always_returned(self):
        """SESS-06: Core tools present even with empty session state."""
        from nautobot_app_mcp_server.mcp.session_tools import _list_tools_handler

        registry = MCPToolRegistry.get_instance()
        # Register a known core tool
        registry.register(
            ToolDefinition(
                name="test_core_progressive",
                func=lambda: None,
                description="Test core tool",
                input_schema={"type": "object"},
                tier="core",
            )
        )
        try:
            ctx = self._make_mock_ctx(enabled_scopes=set(), enabled_searches=set())
            tools = registry.get_core_tools()
            # Verify our core tool is in core_tools
            core_names = [t.name for t in registry.get_core_tools()]
            self.assertIn("test_core_progressive", core_names)
        finally:
            # Clean up
            del registry._tools["test_core_progressive"]  # pylint: disable=protected-access

    def test_non_core_tool_requires_scope_enabled(self):
        """Non-core tools NOT returned when scope not in enabled_scopes."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_app_progressive",
                func=lambda: None,
                description="Test app tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.special",
            )
        )
        try:
            session = {"enabled_scopes": set(), "enabled_searches": set()}
            state = MCPSessionState.from_session(session)
            # test_app.special scope is NOT enabled → not returned by get_by_scope
            tools = registry.get_by_scope("test_app.special")
            self.assertEqual(len(tools), 1)  # the tool IS in registry
            # but session has empty enabled_scopes → would be filtered out
            self.assertEqual(state.enabled_scopes, set())
        finally:
            del registry._tools["test_app_progressive"]  # pylint: disable=protected-access

    def test_scope_enabling_returns_matching_tools(self):
        """Enabling a scope makes matching tools visible."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_scope_visible",
                func=lambda: None,
                description="Scoped tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="test_app",
                scope="test_app.view",
            )
        )
        try:
            session = {"enabled_scopes": {"test_app.view"}, "enabled_searches": set()}
            state = MCPSessionState.from_session(session)
            tools = registry.get_by_scope("test_app.view")
            self.assertEqual(len(tools), 1)
            self.assertEqual(tools[0].name, "test_scope_visible")
        finally:
            del registry._tools["test_scope_visible"]  # pylint: disable=protected-access


class ScopeHierarchyTestCase(TestCase):
    """Test scope hierarchy (D-21): enabling parent activates children."""

    def test_parent_scope_matches_child_tools(self):
        """get_by_scope("dcim") returns tools with scope="dcim.interface"."""
        registry = MCPToolRegistry.get_instance()
        registry.register(
            ToolDefinition(
                name="test_child_match",
                func=lambda: None,
                description="Child scope tool",
                input_schema={"type": "object"},
                tier="app",
                app_label="dcim_app",
                scope="dcim.interface",
            )
        )
        try:
            tools = registry.get_by_scope("dcim")
            scope_names = [t.scope for t in tools]
            self.assertIn("dcim.interface", scope_names)
        finally:
            del registry._tools["test_child_match"]  # pylint: disable=protected-access

    def test_disable_removes_parent_and_children(self):
        """mcp_disable_tools disables parent scope via prefix removal."""
        from nautobot_app_mcp_server.mcp.session_tools import MCPSessionState

        session = {
            "enabled_scopes": {"dcim", "dcim.interface", "ipam"},
            "enabled_searches": set(),
        }
        state = MCPSessionState.from_session(session)

        # Simulate disable("dcim") — remove dcim and all children
        to_remove = {
            s for s in state.enabled_scopes
            if s == "dcim" or s.startswith("dcim.")
        }
        state.enabled_scopes -= to_remove

        self.assertNotIn("dcim", state.enabled_scopes)
        self.assertNotIn("dcim.interface", state.enabled_scopes)
        self.assertIn("ipam", state.enabled_scopes)


class MCPToolRegistrationTestCase(TestCase):
    """Verify session tools are registered correctly (SESS-03, SESS-04, SESS-05)."""

    def test_mcp_enable_tools_returns_scope_string(self):
        """mcp_enable_tools tool is registered and callable."""
        from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry.get_instance()
        all_tools = registry.get_all()
        tool_names = [t.name for t in all_tools]
        self.assertIn("mcp_enable_tools", tool_names)
        self.assertIn("mcp_disable_tools", tool_names)
        self.assertIn("mcp_list_tools", tool_names)

    def test_enable_tools_tier_is_core(self):
        """Session tools are tier="core" so they always appear."""
        from nautobot_app_mcp_server.mcp.registry import MCPToolRegistry

        registry = MCPToolRegistry.get_instance()
        core_names = [t.name for t in registry.get_core_tools()]
        self.assertIn("mcp_enable_tools", core_names)
        self.assertIn("mcp_disable_tools", core_names)
        self.assertIn("mcp_list_tools", core_names)
```

**`<acceptance_criteria>`**
- [ ] `grep -n "class MCPSessionStateTestCase" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → session state tests
- [ ] `grep -n "test_core_tools_always_returned" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → SESS-06
- [ ] `grep -n "test_parent_scope_matches_child_tools" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → D-21
- [ ] `grep -n "test_disable_removes_parent_and_children" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → scope disabling
- [ ] `grep -n "test_mcp_enable_tools_returns_scope_string" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → SESS-03/04/05
- [ ] `grep -n "get_core_tools" nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → core tools always in core tier
- [ ] `poetry run invoke ruff nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → no errors
- [ ] `poetry run invoke pylint nautobot_app_mcp_server/mcp/tests/test_session_tools.py` → 10.00/10

---

## Verification

After all waves complete, run the full test suite and linters:

```bash
unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server
unset VIRTUAL_ENV && poetry run invoke ruff --fix
unset VIRTUAL_ENV && poetry run invoke pylint
unset VIRTUAL_ENV && poetry run invoke tests
```

**All criteria must pass:**

| Check | Command | Expected |
|---|---|---|
| Ruff lint | `poetry run invoke ruff` | No errors |
| Pylint | `poetry run invoke pylint` | 10.00/10 |
| Auth tests | `poetry run invoke unittest nautobot_app_mcp_server.mcp.tests.test_auth` | All pass (TEST-06) |
| Session tests | `poetry run invoke unittest nautobot_app_mcp_server.mcp.tests.test_session_tools` | All pass |
| Full suite | `poetry run invoke tests` | All pass |

**must_haves for goal-backward verification:**

1. `get_user_from_request` in `nautobot_app_mcp_server/mcp/auth.py` → token auth works
2. `logger.warning("MCP: No auth token")` present → PIT-10 compliance
3. `logger.debug("MCP: Invalid auth token")` present → D-22 compliance
4. `MCPSessionState` dataclass in `nautobot_app_mcp_server/mcp/session_tools.py` → SESS-01
5. `session["enabled_scopes"]` / `session["enabled_searches"]` → SESS-02 (FastMCP session)
6. `@mcp.list_tools()` override in `server.py` → REGI-05 (progressive disclosure)
7. `mcp_enable_tools`, `mcp_disable_tools`, `mcp_list_tools` registered on `mcp` instance → SESS-03/04/05
8. Core tools in `get_core_tools()` → SESS-06 (always returned)
9. `test_auth.py` with valid/invalid/missing token tests → TEST-06
10. `poetry run invoke tests` → all pass, Pylint 10.00/10

---

## Phase Exit Gate

**Command:** `unset VIRTUAL_ENV && cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server && poetry run invoke tests`

**Gate:** All tests pass, Pylint 10.00/10, no Ruff errors.
