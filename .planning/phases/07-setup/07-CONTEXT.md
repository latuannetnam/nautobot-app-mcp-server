# Phase 7: Setup - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Prerequisite wiring for the separate-process MCP server migration. Three mechanical changes:
1. Explicit `uvicorn` dependency in `pyproject.toml`
2. Docker Compose env-var passthrough to MCP server service
3. `--workers 1` warning in upgrade docs

No new capabilities. Phase 7 enables Phase 8 (management commands).

</domain>

<decisions>
## Implementation Decisions

### Dependency Management (P0-01)
- **D-01:** Add `uvicorn >= 0.35.0` explicitly under `[tool.poetry.dependencies]` in `pyproject.toml`
- **D-02:** Pin lower bound only (not upper bound) — allows FastMCP's transitive uvicorn constraint to apply

### Docker Compose (P0-02)
- **D-03:** Add a new MCP server service to `development/docker-compose.base.yml` (or `docker-compose.dev.yml` — see below)
- **D-04:** Pass all four `NAUTOBOT_DB_*` env vars to the MCP server service:
  - `NAUTOBOT_DB_USER`
  - `NAUTOBOT_DB_PASSWORD`
  - `NAUTOBOT_DB_HOST`
  - `NAUTOBOT_DB_NAME`
- **D-05:** All four vars are required — omitting any one causes silent auth failures at `nautobot.setup()`
- **D-06:** MCP server service must expose port 8005 (per ROADMAP.md: `http://localhost:8005/mcp/`)

### Docker Compose File Choice (D-07)
- **D-07:** The ROADMAP.md references `development/docker-compose.yml` but the actual project uses `docker-compose.base.yml` + `docker-compose.dev.yml` split. Decision needed: add MCP server service to `docker-compose.base.yml` (applies to all variants) or `docker-compose.dev.yml` (dev-only). **Recommendation: `docker-compose.base.yml`** — all environments need DB vars.

### Documentation (P0-03)
- **D-08:** Add `--workers 1` warning section to `docs/admin/upgrade.md`
- **D-09:** Warning explains: in-memory sessions are lost with `--workers > 1`; Redis backend deferred to v2

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Docker Compose
- `development/docker-compose.base.yml` — base service definitions (where MCP server service will be added)
- `development/docker-compose.dev.yml` — dev override (volume mounts, port 8080 for nautobot)
- `development/docker-compose.postgres.yml` — postgres variant override

### Config
- `pyproject.toml` — dependency section for uvicorn addition

### Docs
- `docs/admin/upgrade.md` — where `--workers 1` warning will be added

### Architecture
- `nautobot_app_mcp_server/__init__.py` — plugin config (may need `base_url` or other settings)
- `development/Dockerfile` — existing MCP server container definition (reference for service addition)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `development/docker-compose.base.yml`: Already defines `nautobot`, `worker`, `beat` services with `x-nautobot-base` YAML anchor — MCP server should follow the same pattern
- `development/development.env`: Contains `NAUTOBOT_DB_*` defaults — MCP server service should use the same env vars
- `development/nautobot_config.py`: `nautobot.setup()` config path

### Established Patterns
- YAML anchors (`&nautobot-build`, `&nautobot-base`) for shared service config
- `env_file:` directive for credential loading (`creds.env`)
- Docker healthchecks on `nautobot` service using `service_healthy` condition

### Integration Points
- MCP server service in docker-compose: needs `depends_on: db` (with healthcheck), same `env_file` as nautobot, and DB env vars
- Port 8005: expose for MCP client connections

</code_context>

<specifics>
## Specific Ideas

- "MCP server runs as its own service, NOT inside the nautobot container" (per ROADMAP.md known pitfall P0-02)
- uvicorn `>= 0.35.0` — lower bound only, no upper cap (per ROADMAP.md)
- No new Nautobot plugin settings needed for Phase 7

</specifics>

<deferred>
## Deferred Ideas

**None — Phase 7 is pure prerequisite wiring, all scoped items have clear success criteria.**

### docker-compose File Choice
- If user wants MCP server dev-only (not in base), it goes in `docker-compose.dev.yml` instead. This is a deployment concern for Phase 7 planning to decide.

</deferred>

---

*Phase: 07-setup*
*Context gathered: 2026-04-05*
