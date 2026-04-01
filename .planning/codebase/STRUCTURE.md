# Project Structure — `nautobot-app-mcp-server`

> What every directory and key file is for, how naming conventions work, and where to find things.

---

## 1. Root Directory

```
nautobot-app-mcp-server/          ← Repository root (git)
├── CLAUDE.md                     ← Claude Code project instructions (you are here)
├── README.md                     ← Public overview, links to docs
├── pyproject.toml                ← Poetry project config, tool config (ruff, pylint, towncrier, etc.)
├── poetry.lock                   ← Locked dependency versions
├── tasks.py                      ← Invoke automation tasks (poetry run invoke <task>)
├── changes/                      ← Towncrier changelog fragments (not committed individually)
│   └── .gitignore
└── .claude/                      ← Claude Code agent definitions and settings
    └── settings.local.json       ← Custom permissions for Claude Code
```

---

## 2. App Package — `nautobot_app_mcp_server/`

```
nautobot_app_mcp_server/           ← The actual Nautobot app package
├── __init__.py                   ← NautobotAppMcpServerConfig entry point
├── api/                          ← REST API (INTENTIONALLY EMPTY — no models)
│   ├── __init__.py
│   └── (serializers.py, views.py, urls.py — NOT created)
├── tests/                        ← Unit tests
│   ├── __init__.py
│   ├── test_registry.py          ← planned
│   ├── test_core_tools.py        ← planned
│   └── test_signal_integration.py ← planned
├── mcp/                          ← MCP server implementation
│   ├── __init__.py               ← Public API: register_mcp_tool()
│   ├── server.py                 ← FastMCP server init + get_mcp_app() lazy loader
│   ├── registry.py               ← MCPToolRegistry singleton + ToolDefinition
│   ├── session.py                ← MCPSessionState per Mcp-Session-Id
│   ├── auth.py                   ← get_user_from_request()
│   ├── urls.py                   ← URL routing: /mcp/ endpoint
│   └── tools/                    ← Tool implementations
│       ├── __init__.py
│       ├── core.py               ← Core tools (always visible, tier="core")
│       ├── pagination.py         ← paginate_queryset(), PaginatedResult dataclass
│       ├── permissions.py       ← Nautobot permission helpers
│       └── query_utils.py        ← Shared queryset builders (select_related chains)
├── static/                       ← Static assets served by Nautobot
│   └── nautobot_app_mcp_server/
│       └── docs/                 ← Built MkDocs docs (served at /plugins/mcp-server/docs/)
└── templates/                   ← Django templates (minimal for this app)
```

**Key naming conventions for the `mcp/` package:**

| File | Convention | Content |
|---|---|---|
| `mcp/__init__.py` | Exposes public API only | `register_mcp_tool`, `MCPToolRegistry`, `ToolDefinition` |
| `mcp/server.py` | One noun, `.py` | FastMCP instance, `get_mcp_app()` factory |
| `mcp/registry.py` | One noun, `.py` | `MCPToolRegistry` class, `ToolDefinition` dataclass |
| `mcp/session.py` | One noun, `.py` | `MCPSessionState` dataclass |
| `mcp/auth.py` | One noun, `.py` | `get_user_from_request()` function |
| `mcp/urls.py` | Django convention | URL patterns for the MCP endpoint |
| `mcp/tools/core.py` | Domain noun, `.py` | Core tool functions + tool registration |
| `mcp/tools/pagination.py` | Feature noun, `.py` | Pagination helpers |

---

## 3. Development Environment — `development/`

```
development/                       ← Docker Compose dev environment
├── docker-compose.base.yml       ← Base compose config (nautobot + worker + beat + db + redis)
├── docker-compose.dev.yml       ← Dev overrides: ports 8080/8001, volume mounts, runserver
├── docker-compose.postgres.yml  ← Postgres database service
├── docker-compose.mysql.yml     ← MySQL database service (optional alt to postgres)
├── docker-compose.redis.yml     ← Redis service
├── nautobot_config.py            ← Nautobot Django settings (PLUGINS=["nautobot_app_mcp_server"])
├── Dockerfile                   ← Builds the app Docker image (poetry install)
├── development.env               ← Non-sensitive default env vars
├── creds.example.env             ← Template for secrets (copy to creds.env)
├── creds.env                     ← Actual secrets (gitignored)
├── towncrier_header.txt         ← Towncrier changelog header fragment
├── towncrier_template.j2        ← Towncrier changelog template
├── app_config_schema.py         ← App config schema generation/validation script
└── bin/
    └── ensure_release_notes.py  ← Ensures release notes file exists before towncrier build
```

**Compose service ports (dev mode):**

| Service | Port | Purpose |
|---|---|---|
| `nautobot` | `8080` | Nautobot web UI + REST API |
| `docs` | `8001` | MkDocs live-reload dev docs server |
| `db` (postgres) | `5432` (optional, commented out) | PostgreSQL database |
| `redis` | `6379` (optional, commented out) | Redis cache + Celery broker |

**How `PLUGINS` is configured:**

```python
# development/nautobot_config.py (line 122)
PLUGINS = ["nautobot_app_mcp_server"]
```

---

## 4. Documentation — `docs/`

```
docs/                             ← MkDocs documentation source
├── index.md                     ← Docs landing page
├── dev/
│   ├── DESIGN.md                ← Implementation plan (AS-IS / future state)
│   ├── arch_decision.md         ← Architecture Decision Records (minimal — shell)
│   ├── contributing.md          ← How to contribute
│   ├── dev_environment.md       ← Docker dev setup guide
│   ├── extending.md             ← How to extend (register tools from third-party apps)
│   ├── release_checklist.md     ← Release procedure
│   └── code_reference/
│       ├── index.md             ← Code reference landing
│       └── package.md           ← API reference (auto-generated from docstrings)
├── admin/
│   ├── install.md               ← Installation guide
│   ├── upgrade.md               ← Upgrade guide
│   ├── uninstall.md             ← Uninstallation guide
│   ├── compatibility_matrix.md  ← Nautobot version compatibility
│   ├── release_notes/
│   │   ├── index.md             ← Release notes index
│   │   └── version_1.0.md       ← v1.0 release notes
│   └── release_notes/version_1.0.md ← Also at this path (towncrier output target)
└── user/
    ├── app_overview.md          ← User-facing overview
    ├── app_use_cases.md         ← Screenshots / use cases
    ├── app_getting_started.md   ← Quick start
    ├── external_interactions.md ← How it talks to other systems
    └── faq.md                   ← Frequently asked questions
```

**MkDocs config** is at `mkdocs.yml` (not shown — standard Nautobot app template).

**Docs build output:** `nautobot_app_mcp_server/static/nautobot_app_mcp_server/docs/` — served by Nautobot at `/plugins/nautobot_app_mcp_server/docs/`.

---

## 5. Tests — `nautobot_app_mcp_server/tests/`

```
nautobot_app_mcp_server/tests/
├── __init__.py
├── test_registry.py             ← MCPToolRegistry singleton behavior
├── test_core_tools.py            ← Core tool input/output validation
└── test_signal_integration.py   ← post_migrate registration timing
```

**Naming conventions for test files:**
- `test_<module_name>.py` — one test file per module being tested
- Test class naming: `Test<ModuleName>` (e.g., `TestMCPToolRegistry`)
- Test method naming: `test_<what_is_tested>()` (lowercase, underscores)

**Running tests:**

```bash
poetry run invoke unittest                    # run tests
poetry run invoke unittest --keepdb          # reuse test DB (faster)
poetry run invoke unittest -k="test_name"    # run specific test
poetry run invoke tests                      # full suite: lint + tests + coverage
```

---

## 6. The Planned `mcp/` Module (Per DESIGN.md)

```
nautobot_app_mcp_server/mcp/       ← MCP server package (PLANNED — does not exist yet)

server.py                          ← FastMCP("NautobotMCP", stateless_http=False)
                                     + get_mcp_app() lazy ASGI factory
                                     + StreamableHTTPSessionManager

registry.py                        ← MCPToolRegistry (thread-safe singleton)
                                     + ToolDefinition dataclass
                                     + MCPToolRegistry.get_instance()
                                     + register / get_all / get_core_tools
                                     + get_by_scope / fuzzy_search

session.py                         ← MCPSessionState dataclass
                                     + enabled_scopes, enabled_searches
                                     + get_active_tools(registry)

auth.py                            ← get_user_from_request(request) → User|AnonymousUser
                                     + Token.objects.select_related("user").get(key=xxx)

tools/
├── core.py                        ← Core tool functions (10 read tools + 3 meta tools)
│                                    + get_core_tool_definitions()
│                                    Device: device_list, device_get
│                                    Interface: interface_list, interface_get
│                                    IP: ipaddress_list, ipaddress_get
│                                    Prefix: prefix_list
│                                    VLAN: vlan_list
│                                    Location: location_list
│                                    Search: search_by_name
│                                    Meta: mcp_enable_tools, mcp_disable_tools, mcp_list_tools
│
├── pagination.py                   ← paginate_queryset(qs, limit, cursor) → PaginatedResult
│                                    + LIMIT_DEFAULT, LIMIT_MAX, LIMIT_SUMMARIZE
│                                    + _encode_cursor(pk), _decode_cursor(cursor)
│
├── permissions.py                 ← get_user_from_request() helper reuse
│                                    + check_view_permission(user, model)
│
└── query_utils.py                  ← Shared queryset builder functions
                                     + for_list_view(model) → queryset with select_related
                                     + for_detail_view(model) → queryset with prefetch_related
                                     + _serialize(obj) → dict
```

---

## 7. `.planning/` Directory

```
.planning/
└── codebase/
    ├── ARCHITECTURE.md            ← This file: pattern, layers, data flow, abstractions
    └── STRUCTURE.md               ← This file: directory layout, naming conventions
```

---

## 8. Changes (Towncrier Changelog Fragments)

```
changes/                           ← Towncrier changelog fragments
     .gitignore                    ← Don't commit individual fragment files
     (empty — fragments added per PR)
```

**Fragment types:**

| Directory | Type | Example filename |
|---|---|---|
| `changes/added/` | New feature | `42.added.md` |
| `changes/changed/` | Behavior change | `42.changed.md` |
| `changes/fixed/` | Bug fix | `42.fixed.md` |
| `changes/removed/` | Removed feature | `42.removed.md` |
| `changes/breaking/` | Breaking change | `42.breaking.md` |
| `changes/deprecated/` | Deprecation | `42.deprecated.md` |
| `changes/security/` | Security fix | `42.security.md` |
| `changes/documentation/` | Docs-only | `42.documentation.md` |
| `changes/dependencies/` | Dependency change | `42.dependencies.md` |
| `changes/housekeeping/` | Internal | `42.housekeeping.md` |

---

## 9. `.claude/` — Claude Code Configuration

```
.claude/
├── settings.local.json            ← Claude Code permissions (Poetry, Docker, GitHub)
└── agents/                        ← GSD agent definitions (researcher, planner, etc.)
```

---

## 10. Key File Relationships

```
nautobot_config.py
    → PLUGINS = ["nautobot_app_mcp_server"]
    → activates the app

nautobot_app_mcp_server/__init__.py
    → NautobotAppMcpServerConfig
    → name = "nautobot_app_mcp_server"
    → base_url = "mcp-server"          → /plugins/mcp-server/ prefix

nautobot_app_mcp_server/mcp/__init__.py
    → exports register_mcp_tool()       → called by third-party apps
    → exports MCPToolRegistry, ToolDefinition

nautobot_app_mcp_server/mcp/server.py   (planned)
    → FastMCP instance                  → used by urls.py

nautobot_app_mcp_server/mcp/urls.py     (planned)
    → path("mcp/", mcp_view)            → /plugins/mcp-server/mcp/

nautobot_app_mcp_server/mcp/tools/core.py  (planned)
    → core tool functions               → called by register_mcp_tools()

pyproject.toml
    → packages = [{ include = "nautobot_app_mcp_server" }]
    → defines all dev tools (ruff, pylint, towncrier)

tasks.py
    → invoke unittest                   → runs tests via nautobot-server test
    → invoke tests                      → full pipeline
    → invoke start                      → docker compose up
```

---

## 11. What's NOT in This App

By design, these standard Nautobot app components are **not created** (stated in `CLAUDE.md`):

| Standard File | Reason |
|---|---|
| `models.py` | No database models — it's a protocol adapter |
| `filters.py` | No REST API views to filter |
| `forms.py` | No web UI forms |
| `tables.py` | No web UI tables |
| `views.py` | No web UI views |
| `urls.py` (root) | No web UI URL routes |
| `api/serializers.py` | No REST API |
| `api/views.py` | No REST API |
| `api/urls.py` | No REST API |
| `navigation.py` | No nav menu entries |
| `migrations/` | No database migrations |
