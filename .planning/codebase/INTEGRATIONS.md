# INTEGRATIONS.md — External Integrations

## Nautobot (Primary Integration)

The app **is** a Nautobot App (plugin). It embeds inside a running Nautobot instance and exposes a Model Context Protocol (MCP) server for AI agents.

### How It Integrates

**App declaration** in `nautobot_app_mcp_server/__init__.py` (lines 11–26):
```python
class NautobotAppMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"
    verbose_name = "Nautobot App MCP Server"
    base_url = "mcp-server"
    required_settings = []
    default_settings = {}
    docs_view_name = "plugins:nautobot_app_mcp_server:docs"
    searchable_models = []
```

**Plugin registration** in `development/nautobot_config.py` (line 122):
```python
PLUGINS = ["nautobot_app_mcp_server"]
```

**Design intent** (from `docs/dev/DESIGN.md`): The MCP server is embedded inside Nautobot's Django process, using direct Django ORM calls (zero network overhead). The MCP endpoint is mounted at a URL like `/plugins/nautobot-app-mcp-server/mcp/` within Nautobot.

### What the App Reads from Nautobot

The app accesses Nautobot models directly via the Django ORM for read-only queries:

- `dcim.models.Device` — device inventory
- `dcim.models.Interface` — interface records
- `ipam.models.IPAddress` — IP address assignments
- `ipam.models.Prefix` — IP prefix space
- `ipam.models.VLAN` — VLAN records
- `dcim.models.Location` — location hierarchy
- `extras.models.ObjectPermission` — permission enforcement

Queries are always restricted with Nautobot's built-in `.restrict(user, action)` ORM method, enforcing Nautobot's permission system transparently.

### Nautobot Version Compatibility

| Nautobot | Status |
|---|---|
| `>=3.0.0,<4.0.0` | Supported (declared in `pyproject.toml` line 33) |
| Dev stack default | Nautobot 3.0.0 (`tasks.py` line 55) |
| Base Docker image | `ghcr.io/nautobot/nautobot-dev:${NAUTOBOT_VER}-py${PYTHON_VER}` |

A compatibility matrix is maintained at `docs/admin/compatibility_matrix.md`.

---

## Database (PostgreSQL / MySQL)

### PostgreSQL (Default)

File: `development/docker-compose.postgres.yml`

```yaml
db:
  image: "postgres:17-alpine"
  command: ["-c", "max_connections=200"]
```

Connection settings (from `development/nautobot_config.py` lines 35–56):
```python
DATABASES = {
    "default": {
        "ENGINE": os.getenv("NAUTOBOT_DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("NAUTOBOT_DB_NAME", "nautobot"),
        "USER": os.getenv("NAUTOBOT_DB_USER", ""),
        "PASSWORD": os.getenv("NAUTOBOT_DB_PASSWORD", ""),
        "HOST": os.getenv("NAUTOBOT_DB_HOST", "localhost"),   # "db" in Docker
        "PORT": os.getenv("NAUTOBOT_DB_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("NAUTOBOT_DB_TIMEOUT", "300")),
    }
}
```

Credentials are sourced from `creds.env` / `development.env`.

### MySQL (Optional / Alternative)

File: `development/docker-compose.mysql.yml`

```yaml
db:
  image: "mysql:lts"
  command: ["--max_connections=1000"]
```

Activated by replacing `docker-compose.postgres.yml` with `docker-compose.mysql.yml` in `compose_files` and setting `NAUTOBOT_DB_ENGINE=django.db.backends.mysql` in the Nautobot services.

Unicode handling for MySQL (`nautobot_config.py` lines 59–60):
```python
if DATABASES["default"]["ENGINE"] == "django.db.backends.mysql":
    DATABASES["default"]["OPTIONS"] = {"charset": "utf8mb4"}
```

### Database Tools (invoke tasks)

| Task | Command | Details |
|---|---|---|
| `invoke dbshell` | `psql` / `mysql` | SQL CLI inside `db` container |
| `invoke backup-db` | `pg_dump` / `mysqldump` | Dump to `dump.sql` |
| `invoke import-db` | `pg_restore` / `mysql` | Restore from `dump.sql` |
| `invoke migrate` | `nautobot-server migrate` | Run Django migrations |

---

## Redis

File: `development/docker-compose.redis.yml`

```yaml
redis:
  image: "redis:6-alpine"
  command: ["sh", "-c", "redis-server --appendonly yes --requirepass $$NAUTOBOT_REDIS_PASSWORD"]
```

Redis is used by:
- **Celery** — task queue (worker + beat services). Redis is the Celery broker and result backend.
- **Django cache** — django-redis cache backend (inherited from Nautobot core settings). Used for concurrent locks.
- **MCP session state** — `docs/dev/DESIGN.md` indicates FastMCP's `StreamableHTTPSessionManager` stores per-session state in-memory, with Redis as a future swap-in backend.

Connection settings inherited from Nautobot core defaults via `nautobot.core.settings`.

Redis password: `NAUTOBOT_REDIS_PASSWORD` sourced from `creds.env`.

---

## Docker Compose Services Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Docker Compose Stack (invoke start / invoke stop)              │
│                                                                 │
│  ┌──────────┐   ┌───────────┐   ┌──────────┐                    │
│  │nautobot  │───│  worker   │   │   beat   │   (same image)    │
│  │:8080     │   │ Celery    │   │ Celery   │                    │
│  └────┬─────┘   └───────────┘   └──────────┘                    │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────┐   ┌──────────┐                                    │
│  │   redis  │   │    db    │                                    │
│  │ :6379    │   │:5432 pg17│                                    │
│  └──────────┘   └──────────┘                                    │
└────────────────────────────────────────────────────────────────┘
```

---

## AI Agents / MCP Clients

The primary purpose of the app: expose an **MCP server endpoint** for AI agents to interact with Nautobot data.

### MCP Clients

From `docs/dev/DESIGN.md`, the app is designed to serve:

- **Claude Code** — AI coding assistant (primary target)
- **Claude Desktop** — Desktop AI assistant
- **Antigravity** / **OpenClaw** — other MCP-compatible AI tools

### MCP Protocol Details

The app implements MCP over **HTTP** (streamable, stateful):

- Transport: `StreamableHTTPSessionManager` from FastMCP
- `stateless_http=False` — sessions tracked via `Mcp-Session-Id` header
- Session timeout: 3600s (1 hour idle) per `docs/dev/DESIGN.md`
- Auth: Nautobot API token in `Authorization: Token nbapikey_xxx` header
- Endpoint: `/plugins/nautobot-app-mcp-server/mcp/` (or Option B on a separate port)

### Third-Party Nautobot App Tool Registration

The app exposes a public API (`register_mcp_tool()`) that other Nautobot apps call during their `ready()` hook to register MCP tools. This is the **plugin extensibility mechanism**:

```python
# Third-party app __init__.py (from docs/dev/DESIGN.md)
from nautobot_mcp_server.mcp import register_mcp_tool

register_mcp_tool(
    name="juniper_interface_unit_list",
    func=juniper_interface_unit_list,
    description="List Juniper interface units...",
    input_schema={...},
    tier="app",
    app_label="netnam_cms_core",
    scope="netnam_cms_core.juniper",
)
```

Registration happens via Django's `post_migrate` signal (not `ready()`) to ensure all apps' `ready()` hooks complete before tool registration runs.

---

## Nautobot REST API

The MCP server does **not** use the REST API for internal data access — it queries the Django ORM directly. However, **external clients** interact with Nautobot's REST API for authentication tokens:

### Token Generation

Users create Nautobot API tokens via the Nautobot UI (`User > Tokens`). These tokens are sent in the `Authorization` header to the MCP endpoint.

### API Token Model

```python
# Nautobot's Token model (used in docs/dev/DESIGN.md auth.py)
from nautobot.extras.models import Token

token = Token.objects.select_related("user").get(key=token_key)
user = token.user
```

---

## Celery / Task Queue

Celery workers run alongside the Nautobot Django process:

| Service | Command | Purpose |
|---|---|---|
| `worker` | `nautobot-server celery worker -l $LOG_LEVEL --events` | Process async tasks |
| `beat` | `nautobot-server celery beat -l $LOG_LEVEL` | Periodic task scheduler |

In dev mode (`docker-compose.dev.yml`), `worker` uses `watchmedo auto-restart` to reload on code changes:
```yaml
entrypoint: "sh -c 'watchmedo auto-restart --directory ./ --pattern *.py --recursive -- nautobot-server celery worker -l $$NAUTOBOT_LOG_LEVEL --events'"
```

---

## NAPALM (Optional)

`development/creds.env` contains placeholder NAPALM credentials:
```
NAUTOBOT_NAPALM_USERNAME=''
NAUTOBOT_NAPALM_PASSWORD=''
```

NAPALM is used by Nautobot core for interacting with network devices. The app itself does not call NAPALM directly — it reads from the Nautobot database only.

---

## External Documentation Site

Docs are built with **MkDocs** and served in two ways:

1. **In Nautobot** — at `/static/nautobot_app_mcp_server/docs/` (embedded in the package)
2. **Standalone** — at `http://localhost:8001` via `invoke docs` (MkDocs livereload server)

The docs container uses the same Docker image as Nautobot but with MkDocs as the entrypoint:
```yaml
# docker-compose.dev.yml lines 20–27
docs:
  entrypoint: "mkdocs serve -v --livereload -a 0.0.0.0:8080"
  ports:
    - "8001:8080"
```

---

## Environment / Secrets Management

Secrets are managed via Docker Compose env files:

| File | Managed by | In git? |
|---|---|---|
| `development/development.env` | Developer | Yes (no secrets) |
| `development/creds.env` | `cp creds.example.env creds.env` then edit | **No** (gitignored) |
| `development/creds.example.env` | Template | Yes |

Secrets defined in `creds.example.env`:
```
NAUTOBOT_CREATE_SUPERUSER=true
NAUTOBOT_DB_PASSWORD=changeme
NAUTOBOT_NAPALM_USERNAME=''
NAUTOBOT_NAPALM_PASSWORD=''
NAUTOBOT_REDIS_PASSWORD=changeme
NAUTOBOT_SECRET_KEY='changeme'
NAUTOBOT_SUPERUSER_NAME=admin
NAUTOBOT_SUPERUSER_EMAIL=admin@example.com
NAUTOBOT_SUPERUSER_PASSWORD=admin
NAUTOBOT_SUPERUSER_API_TOKEN=0123456789abcdef0123456789abcdef01234567
```

---

## Optional Integrations (Environment-Enabled)

These are activated via environment variables or compose file swaps:

| Integration | How to Enable |
|---|---|
| **MySQL** instead of PostgreSQL | Swap `docker-compose.postgres.yml` → `docker-compose.mysql.yml`; set `NAUTOBOT_DB_ENGINE=django.db.backends.mysql` |
| **Local dev** (no Docker) | `unset VIRTUAL_ENV && poetry shell`, then run Nautobot manually |
| **Prometheus metrics** | `NAUTOBOT_METRICS_ENABLED=True` (set in `development.env` line 12) |
| **Debug toolbar** | `NAUTOBOT_DEBUG=True` (set in `development.env` line 9); auto-enables `debug_toolbar` in `nautobot_config.py` |

---

## GitHub

| Item | Value |
|---|---|
| Repository | `https://github.com/latuannetnam/nautobot-app-mcp-server` |
| CI base image | `ghcr.io/nautobot/nautobot-dev:${NAUTOBOT_VER}-py${PYTHON_VER}` |
| Issue tracker | GitHub Issues |
| Release notes | GitHub Releases + Towncrier (`{issue_format}` in `pyproject.toml` line 169) |

CI (when `CI` env var is set) uses a fallback path in the Dockerfile:
```dockerfile
RUN if [ -z "${CI+x}" ]; then \
    poetry add --lock nautobot@${INSTALLED_NAUTOBOT_VER} --python ${PYTHON_VER} || \
    poetry add --lock git+https://github.com/nautobot/nautobot.git#${NAUTOBOT_VER} --python ${PYTHON_VER}; fi
```
