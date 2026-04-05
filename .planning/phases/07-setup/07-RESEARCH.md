# Phase 7: Setup — Research

**Phase:** 07-setup
**Research date:** 2026-04-05
**Status:** Complete

---

## Research Questions

### Q1: Best way to add a second service to Docker Compose?

### Q2: Env-var passthrough patterns (direct vs env_file)?

### Q3: uvicorn integration with FastMCP (version compatibility, `uvicorn.run()` API)?

### Q4: Nautobot Docker image usage for MCP server service?

---

## Q1: Adding a Second Service to Docker Compose

### Compose File Architecture

The project uses a **layered compose-file override pattern** defined in `tasks.py`:

```python
compose_files = [
    "docker-compose.base.yml",      # 1. Base (anchor defs + nautobot/worker/beat)
    "docker-compose.redis.yml",     # 2. Redis variant
    "docker-compose.postgres.yml",  # 3. DB variant
    "docker-compose.dev.yml",       # 4. Dev overrides (port 8080, volumes)
]
```

The MCP server service should be added to **`docker-compose.base.yml`** (D-07 decision). Rationale:
- All environments (dev, test, CI) inherit the same base services
- DB env-var passthrough is a universal requirement, not a dev-only concern
- Adding to `docker-compose.dev.yml` would mean the service is absent in other environments

### Service Definition Pattern

`docker-compose.base.yml` defines two reusable YAML anchors:

```yaml
x-nautobot-build: &nautobot-build
  build:
    context: "../"
    dockerfile: "development/Dockerfile"

x-nautobot-base: &nautobot-base
  image: "nautobot-app-mcp-server/nautobot:${NAUTOBOT_VER}-py${PYTHON_VER}"
  env_file:
    - "development.env"
    - "creds.env"
  tty: true
```

The MCP server service should mirror this pattern. The Docker image is the same (`nautobot-app-mcp-server/nautobot:${NAUTOBOT_VER}-py${PYTHON_VER}`) because:
1. The image contains all Poetry dependencies including FastMCP and uvicorn
2. Phase 8's management commands (`start_mcp_server.py`, `start_mcp_dev_server.py`) will be the entry point
3. No separate Dockerfile needed for Phase 7

### Dependency Ordering

The MCP server must wait for the database to be healthy before starting, same as the `nautobot` service:

```yaml
mcp:
  depends_on:
    db:
      condition: service_healthy
  # inherits &nautobot-base (image + env_file)
  <<: *nautobot-base
```

**No dependency on the `nautobot` service itself** — the MCP server connects directly to the DB, bypassing the Nautobot Django app entirely (per ROADMAP.md Option B architecture).

---

## Q2: Env-Var Passthrough Patterns

### Option A: `env_file` (Preferred)

`docker-compose.base.yml` already uses `env_file` for credential loading:

```yaml
# Existing pattern (nautobot service)
env_file:
  - "development.env"
  - "creds.env"
```

The `creds.env` file already contains:
```
NAUTOBOT_DB_PASSWORD=changeme
```

The `development.env` file already contains:
```
NAUTOBOT_DB_NAME=nautobot
NAUTOBOT_DB_USER=nautobot
NAUTOBOT_DB_HOST=db
```

**Advantage:** Single source of truth. Both `nautobot` and `mcp` services read from the same env files. Adding the MCP server service with the same `env_file` entries automatically gets all four `NAUTOBOT_DB_*` vars without duplication.

### Option B: Inline `environment`

```yaml
environment:
  - "NAUTOBOT_DB_USER=nautobot"
  - "NAUTOBOT_DB_PASSWORD=${NAUTOBOT_DB_PASSWORD}"
  # ...
```

**Disadvantage:** Duplicates variable names across the compose file. If the env file values change, the compose file must be kept in sync.

### Decision: Option A (`env_file`)

The MCP server service should inherit `env_file` from `&nautobot-base`, which already includes both `development.env` and `creds.env`. This satisfies P0-02 without any new code — all four `NAUTOBOT_DB_*` vars are already defined there.

The `nautobot_config.py` reads them directly:

```python
DATABASES = {
    "default": {
        "NAME": os.getenv("NAUTOBOT_DB_NAME", "nautobot"),
        "USER": os.getenv("NAUTOBOT_DB_USER", ""),
        "PASSWORD": os.getenv("NAUTOBOT_DB_PASSWORD", ""),
        "HOST": os.getenv("NAUTOBOT_DB_HOST", "localhost"),
        "PORT": os.getenv("NAUTOBOT_DB_PORT", "5432"),
    }
}
```

No additional env vars needed for Phase 7. The management commands (Phase 8) will also read `NAUTOBOT_CONFIG` and `PLUGINS_CONFIG`, but those are Phase 8 concerns.

---

## Q3: uvicorn Integration with FastMCP

### Version Compatibility

- **FastMCP:** `^3.2.0` (already in `pyproject.toml`)
- **uvicorn:** `>= 0.35.0` (to be added explicitly per P0-01)

FastMCP 3.x uses uvicorn internally as its ASGI server. The explicit `uvicorn >= 0.35.0` dependency ensures:
1. Access to `uvicorn.run()` programmatic API (used in `start_mvic_dev_server.py`, Phase 8)
2. The `reload` parameter works correctly (added in uvicorn ~0.20)
3. The `factory=True` parameter is available (added in uvicorn ~0.22)

FastMCP's own `mcp.run()` method wraps uvicorn internally. For the production management command (Phase 8, P1-01), `mcp.run(transport="sse")` handles server lifecycle automatically. For the dev command (Phase 8, P1-02), we call `uvicorn.run(reload=True)` directly.

### `uvicorn.run()` API (inspected from uvicorn 0.35.x)

```python
uvicorn.run(
    app,                        # ASGI app instance (or str for factory mode)
    host="127.0.0.1",           # bind address
    port=8000,                  # port
    reload=False,               # enable auto-reload (dev only)
    reload_dirs=None,           # dirs to watch (defaults to app_dir)
    workers=None,               # number of workers (must be 1 for in-memory sessions)
    factory=False,              # True if app is a callable factory
    env_file=None,              # load env vars from file
    log_level="info",
    timeout_graceful_shutdown=None,
    # ... additional params
)
```

**Key note on `factory`:** `factory=False` (default) means `app` must be an actual ASGI app instance. `FastMCP.http_app()` returns a Starlette app (an ASGI app instance), so it should be passed with `factory=False`.

### FastMCP.http_app() Return Value

Inspected via Python introspection:

```python
# FastMCP.http_app() signature:
http_app(
    path: 'str | None' = None,
    middleware: 'list[ASGIMiddleware] | None' = None,
    json_response: 'bool | None' = None,
    stateless_http: 'bool | None' = None,
    transport: "Literal['http', 'streamable-http', 'sse']" = 'http',
    event_store: 'EventStore | None' = None,
    retry_interval: 'int | None' = None,
) -> 'StarletteWithLifespan'
```

Returns a Starlette ASGI application with lifespan management. This is the object to pass to `uvicorn.run()`.

### Phase 8 Usage Pattern (Deferred)

This research covers only Phase 7 (dependency + wiring). For Phase 8 planning, the two entry points are:

```python
# Production (start_mcp_server.py, Phase 8 P1-01):
mcp.run(transport="sse")  # mcp owns the event loop; blocks forever

# Development (start_mcp_dev_server.py, Phase 8 P1-02):
uvicorn.run(
    mcp.http_app(transport="streamable-http"),
    host="0.0.0.0",
    port=8005,
    reload=True,
)
```

---

## Q4: Nautobot Docker Image for MCP Server Service

### Image Selection

The MCP server service uses the **same Docker image** as the Nautobot service:

```yaml
image: "nautobot-app-mcp-server/nautobot:${NAUTOBOT_VER}-py${PYTHON_VER}"
```

Rationale:
1. The image is built from `development/Dockerfile` and includes all Poetry dependencies (`fastmcp`, `uvicorn`, `nautobot`, etc.)
2. The image is already volume-mounted with the project source at `/source`
3. No separate image or Dockerfile is needed for Phase 7
4. Phase 8's management commands are installed as part of `poetry install`

### Volume Mounts

The MCP server service needs:
- Source code at `/source` (same as `nautobot` service in dev)
- `nautobot_config.py` at the path referenced by `NAUTOBOT_CONFIG` env var

```yaml
# In docker-compose.dev.yml (dev overrides for mcp service)
volumes:
  - "./nautobot_config.py:/opt/nautobot/nautobot_config.py"
  - "../:/source"
```

Note: `docker-compose.base.yml` uses `env_file` for config path; `development.env` does not set `NAUTOBOT_CONFIG`. The `nautobot_config.py` is referenced by path in docker-compose.dev.yml. Phase 8 will set `NAUTOBOT_CONFIG` explicitly in the service definition.

### Port Exposure

MCP server on port **8005** (per ROADMAP.md: `http://localhost:8005/mcp/`):

```yaml
# In docker-compose.dev.yml (dev overrides for mcp service)
ports:
  - "8005:8005"
```

---

## Implementation Plan Summary

### P0-01: Add uvicorn dependency

**File:** `pyproject.toml`

**Change:** Add to `[tool.poetry.dependencies]`:

```toml
uvicorn = ">=0.35.0"
```

Placement: after the `# MCP server layer` comment block (line 35-36), alongside `fastmcp = "^3.2.0"`.

**Verification:**
```bash
grep "uvicorn" pyproject.toml
# Expected: uvicorn = ">=0.35.0"
```

### P0-02: Add MCP server service to docker-compose

**Files:**
1. `development/docker-compose.base.yml` — service definition (applies to all variants)
2. `development/docker-compose.dev.yml` — port exposure + volume mounts (dev only)

**docker-compose.base.yml change:**

```yaml
services:
  # ... existing services (nautobot, worker, beat)

  mcp:
    depends_on:
      db:
        condition: service_healthy
    <<: *nautobot-base
    # entrypoint will be set by Phase 8 management commands
    # for now, uses default entrypoint from image (bash)
```

**docker-compose.dev.yml change:**

```yaml
services:
  mcp:
    entrypoint: "nautobot-server start_mcp_dev_server"
    ports:
      - "8005:8005"
    volumes:
      - "./nautobot_config.py:/opt/nautobot/nautobot_config.py"
      - "../:/source"
```

Note: The actual entrypoint command (`start_mcp_dev_server`) is Phase 8 work. For Phase 7, the service definition exists but the container will fail to start without Phase 8's management command. The Phase 7 success criterion for P0-02 is purely about env vars being passed — the service entrypoint can be a no-op placeholder.

**Env var verification:**
```bash
docker compose config | grep -A 20 "mcp:"
# Should show NAUTOBOT_DB_USER, NAUTOBOT_DB_PASSWORD, NAUTOBOT_DB_HOST, NAUTOBOT_DB_NAME
# from env_file inheritance
```

### P0-03: Document `--workers 1` requirement

**File:** `docs/admin/upgrade.md`

**Change:** Add new section after the existing content:

```markdown
## Worker Process Requirement

!!! warning "Single Worker Required"
    The MCP server **must** be run with `--workers 1` (the default for uvicorn).

### Rationale

The MCP server stores session state in-memory. Running with multiple workers
(`--workers N` where `N > 1`) causes sessions to be lost when requests are routed
to different worker processes, breaking the progressive tool discovery feature.

### Production Deployment

For production deployments using systemd:

```ini
[Service]
ExecStart=/opt/nautobot/venv/bin/nautobot-server start_mcp_server
# uvicorn defaults to workers=1 — no explicit flag needed
```

For horizontal scaling with multiple workers, a Redis session backend is required.
This is planned for a future release (v2.0).

### Development

The development server (`start_mcp_dev_server`) uses `uvicorn.run(reload=True)`
which always runs with a single worker.
```

---

## Open Questions

| # | Question | Resolution |
|---|----------|------------|
| 1 | Should the MCP service entrypoint in Phase 7 be a no-op placeholder or commented out? | **Add the service but use a no-op entrypoint** — this makes P0-02 verifiable (service starts but does nothing) while Phase 8 fills in the real entrypoint |
| 2 | Does the MCP server service need Redis env vars? | **Not for Phase 7.** `nautobot.setup()` needs the DB only. Redis is for Celery (nautobot worker/beat), not the MCP server. Phase 11's auth refactor does not change this. |
| 3 | Should `NAUTOBOT_CONFIG` be set explicitly in the docker-compose service? | **Phase 8 concern.** `nautobot_config.py` path is set via volume mount in dev; production will need explicit `NAUTOBOT_CONFIG` env var. |

---

## References

- [Docker Compose file documentation](https://docs.docker.com/compose/compose-file/)
- [uvicorn API reference](https://www.uvicorn.org/server/)
- [FastMCP GitHub — FastMCP.run() and http_app()](https://github.com/jlowin/fastmcp)
- [Docker Compose multi-service pattern — Nautobot docs](https://docs.nautobot.com/)
- [pyproject.toml Poetry dependencies](https://python-poetry.org/docs/dependency-specification/)
