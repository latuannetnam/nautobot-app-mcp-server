# Pitfalls Research — Adding a Separate-Process MCP Server to Nautobot Apps

**Domain:** Nautobot App + FastMCP separate-process architecture migration
**Researched:** 2026-04-05
**Confidence:** HIGH
**Driven by:** `docs/dev/ARCHITECTURE.md` (standalone verification), `docs/dev/mcp-implementation-analysis.md`, `ROADMAP.md`, current codebase state

---

## Critical Pitfalls

### Pitfall 1: `nautobot.setup()` Called After Model Imports

**What goes wrong:**
The MCP server fails to start with `RuntimeError: Django wasn't set up yet. Run nautobot.setup() first.`

If `nautobot.setup()` is called inside `__init__.py` at import time, and `__init__.py` is imported before Django is initialized (e.g., by another plugin's `ready()` hook that triggers a side-effect import), the setup call happens too early. Alternatively, if model imports happen before `nautobot.setup()`:

```python
# WRONG — model imported before setup
from nautobot.dcim.models import Device  # ← raises if Django not set up
nautobot.setup()
```

**Why it happens:**
`nautobot.setup()` checks `django._setup` (a sentinel boolean). If any model class or Django model metaclass is accessed before this flag is set, Django raises `SynchronousOnlyOperation`. The Python import system means any `from x.models import Y` triggers Django model class construction, which requires `django.setup()` to have already run.

**How to avoid:**
Follow the reference architecture's `main.py` pattern — `nautobot.setup()` at the **top of the entry point**, before any relative imports from the package:

```python
# main.py — entry point, first line of user-facing code
import nautobot
nautobot.setup()  # Must be the very first thing

# Only NOW safe to import models
from nautobot.dcim.models import Device  # ✅
```

If `__init__.py` must call `nautobot.setup()`, guard it to run exactly once:
```python
# __init__.py — only run if called as entry point
import sys
if __name__ == "__main__" or getattr(sys, '_nautobot_mcp_setup', False):
    import nautobot
    nautobot.setup()
```

**Warning signs:**
- `RuntimeError: Django wasn't set up yet` at import or startup
- Model import errors in the traceback when running `nautobot-server start_mcp_server`
- Container fails to start with no useful logs (Django import errors swallowed)

**Phase to address:** Phase 0 (Project Setup)

---

### Pitfall 2: `DJANGO_SETTINGS_MODULE` / `NAUTOBOT_CONFIG` Misconfigured

**What goes wrong:**
`nautobot.setup()` silently uses the wrong config (or falls back to a minimal Django settings) and the MCP server connects to the wrong database — or a database with no schema at all (empty tables). Tools return data from a different Nautobot instance, or fail with `relation does not exist`.

**Why it happens:**
`nautobot.setup()` reads `NAUTOBOT_CONFIG` env var, falling back to `~/.nautobot/nautobot_config.py`. If neither is set, it falls back to Django defaults, which connect to `localhost:5432` with no schema. The MCP server silently starts against the wrong DB.

Production Docker deployment also needs `NAUTOBOT_CONFIG` pointing to the same `nautobot_config.py` that Nautobot itself uses.

**How to avoid:**
Document the required env vars explicitly and validate them at startup:
```bash
# Required env vars for MCP server
NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py
NAUTOBOT_DB_HOST=nautobot-db        # Must match Nautobot's DB host
NAUTOBOT_DB_PORT=5432
NAUTOBOT_DB_NAME=nautobot
NAUTOBOT_DB_USER=nautobot
NAUTOBOT_DB_PASSWORD=<from nautobot_config.py>
```

Validate at startup before calling `nautobot.setup()`:
```python
import os
config_path = os.environ.get("NAUTOBOT_CONFIG", "~/.nautobot/nautobot_config.py")
if not os.path.exists(os.path.expanduser(config_path)):
    raise RuntimeError(f"NAUTOBOT_CONFIG not found at {config_path}")
```

**Warning signs:**
- MCP server starts but returns no data — DB has no schema
- `relation "dcim_device" does not exist` errors
- Data returned by MCP doesn't match Nautobot UI data
- `nautobot-setup` health check passes but DB queries fail

**Phase to address:** Phase 0 (Project Setup) — Docker Compose env var wiring

---

### Pitfall 3: `post_migrate` Signal Never Fires (Plugin Tools Not Registered)

**What goes wrong:**
Third-party Nautobot apps call `register_mcp_tool()` from their `AppConfig.ready()` hooks, but in the standalone process those apps are loaded via `django.setup()` (from `nautobot_config.py`'s `INSTALLED_APPS`) without any `post_migrate` signal firing. Tool registrations are silently missing.

**Why it happens:**
`nautobot_database_ready` is sent by Nautobot's `nautobot.core.management.commands.post_migrate` signal hook. When the MCP server runs `django.setup()` directly (not via `nautobot-server`), no `migrate` command is run, so `post_migrate` never fires. Additionally, Django's `post_migrate` signal requires the `django migrations` app, not the `nautobot.core.management.commands.post_migrate` subclass.

The reference architecture (ARCHITECTURE.md §5.7) notes this explicitly: "The `post_migrate` signal that fires `nautobot_database_ready` is **not triggered** by standalone `django.setup()`."

**How to avoid:**
Use a startup discovery mechanism instead of relying on `post_migrate`:
```python
# main.py or server.py — called after nautobot.setup() + django.setup()
def discover_plugin_tools():
    """Called at startup after nautobot.setup(). Discovers plugin mcp_tools modules."""
    from django.apps import apps
    for app_config in apps.get_app_configs():
        if app_config.name.startswith(("django.", "nautobot.core")):
            continue
        try:
            mcp_module = importlib.import_module(f"{app_config.name}.mcp_tools")
            # mcp_module.register_tools(mcp) — convention: module exposes register function
        except ImportError:
            continue
```

Or keep the `MCPToolRegistry` as an in-process registry that third-party apps register into via a conventional import-time call, but call `nautobot.setup()` first in the entry point so Django is ready.

**Warning signs:**
- `mcp_list_tools` returns only core tools, no third-party plugin tools
- Third-party app's `ready()` hook fires but its tools don't appear
- `MCPToolRegistry.get_all()` returns fewer tools than expected

**Phase to address:** Phase 2 (Tool Registration Refactor)

---

### Pitfall 4: In-Memory Sessions Lost on Multi-Worker Deployment

**What goes wrong:**
When running `uvicorn --workers 4`, sessions are stored in each worker's in-memory `StreamableHTTPSessionManager` dict. If a client is routed to worker 1 for request 1, then routed to worker 2 for request 2, the session state from worker 1 is gone. `mcp_enable_tools` on request 1 appears to work, but `mcp_list_tools` on request 2 shows nothing.

**Why it happens:**
FastMCP's `StreamableHTTPSessionManager` stores sessions in `_server_instances: dict[str, StreamableHTTPServerTransport]`. Each uvicorn worker is a separate Python process with its own memory space. Session dict is not shared across processes.

**How to avoid:**
For v1 (single-worker acceptable): document `--workers 1` as a hard requirement for session persistence:
```bash
# v1: single worker for session persistence
uvicorn nautobot_app_mcp_server.main:app --host 0.0.0.0 --port 8005 --workers 1
```

For v2 (multi-worker): implement Redis-backed session storage by subclassing `StreamableHTTPSessionManager` or wrapping the session dict access:
```python
# v2 approach — store session state in Redis
import redis
_redis = redis.Redis.from_url(os.environ["REDIS_URL"])

async def get_session_state(session_id: str) -> dict:
    data = _redis.get(f"mcp:session:{session_id}")
    return json.loads(data) if data else {}
```

**Warning signs:**
- Sessions work on first request, fail on second (worker switched)
- `mcp_enable_tools` result confirmed but next request shows no scope enabled
- Works with `--workers 1`, broken with `--workers 4`

**Phase to address:** Phase 0 (document as known limitation) + Phase 6 (UAT validation)

---

### Pitfall 5: ORM Calls Without `sync_to_async` Raise `SynchronousOnlyOperation`

**What goes wrong:**
Async tool handlers call Django ORM directly:
```python
@mcp.tool()
async def device_list(ctx, limit=25):
    devices = Device.objects.all()  # ← SynchronousOnlyOperation
```
The error only surfaces at runtime — not on module import, not in unit tests that mock the ORM.

**Why it happens:**
Django's `SyncToAsyncWrapper` raises `SynchronousOnlyOperation` when a synchronous ORM call is made from inside an async function that was not explicitly wrapped with `sync_to_async`. FastMCP tool handlers are `async def`. The ORM call is synchronous. The error is raised at the ORM call site.

This pattern is already correctly implemented in the current embedded code (Phase 3 had `PAGE-05` requirement), but when migrating to standalone, the `sync_to_async` wrapper pattern must be maintained and not accidentally removed during refactoring.

**How to avoid:**
Every ORM call inside an async tool handler must be wrapped:
```python
@mcp.tool()
async def device_list(ctx, limit=25):
    @sync_to_async
    def _query():
        return list(Device.objects.select_related("status").all()[:limit])
    devices = await _query()
    return [serialize(d) for d in devices]
```

Enforce via code review checklist item: "Every ORM call in `tools/` is inside a `@sync_to_async`-wrapped inner function."

**Warning signs:**
- `SynchronousOnlyOperation: You cannot call this from an async context` at runtime
- Only surfaces with real ORM (unit tests mock it away)
- Most likely to appear in `search_by_name` which does multi-model queries

**Phase to address:** Phase 2 (Tool Registration Refactor) — re-verify all tool implementations

---

### Pitfall 6: `contextvars.ContextVar` and `_mcp_tool_state` Monkey-Patching Broken in Standalone

**What goes wrong:**
The embedded code uses `ctx.request_context._mcp_tool_state` (monkey-patching the RequestContext dataclass) and `_cached_user` on the same dataclass. In the standalone process, FastMCP runs in its own event loop without the Django `RequestContext` wrapper that the embedded bridge was creating. These patterns may not work the same way.

**Why it happens:**
In the embedded architecture, `view.py` builds a custom `RequestContext` object and passes it through the ASGI call chain. The standalone FastMCP process uses its own `Server.request_context` (`contextvars.ContextVar`) which holds FastMCP's internal `RequestContext` dataclass — a different type, from `mcp.server.lowlevel`.

Specifically:
- `ctx.request_context._mcp_tool_state` — assumes the `request_context` is the embedded bridge's custom type
- `ctx.request_context._cached_user` — same assumption

In standalone FastMCP, `ctx.request_context` is `mcp.server.lowlevel.RequestContext` (different shape).

**How to avoid:**
Replace monkey-patched dataclass attributes with session dict access (which IS cross-version compatible):
```python
# Old (embedded): monkey-patch RequestContext dataclass
ctx.request_context._cached_user = user
cached = ctx.request_context._cached_user

# New (standalone): use FastMCP session dict (always available, always dict-like)
ctx.request_context.session["cached_user"] = user
cached = ctx.request_context.session.get("cached_user")
```

For progressive disclosure, the session dict approach (already in `session_tools.py` `MCPSessionState.from_session()`) is already correct. The fix is to remove the `_get_tool_state()` monkey-patch helper entirely and access the session dict directly.

**Warning signs:**
- `AttributeError: 'RequestContext' object has no attribute '_mcp_tool_state'`
- `AttributeError: 'RequestContext' object has no attribute '_cached_user'`
- Progressive disclosure tools return wrong tool list

**Phase to address:** Phase 3 (Session State Simplification) — replace monkey-patching with session dict

---

### Pitfall 7: Auth Token Read from Wrong Place (MCP vs Django Request)

**What goes wrong:**
Auth extracts the token from `ctx.request_context.request.headers` — which in the embedded bridge came from the MCP HTTP request, but in standalone FastMCP, `request_context.request` is set by FastMCP's own HTTP handler. These should be the same thing, but if any middleware or proxy modifies headers before FastMCP sees them, the token may be lost or overwritten.

**Why it happens:**
In the embedded architecture, the Django view bridges the HTTP request into ASGI, building headers from `django_request.headers`. In standalone, FastMCP receives the HTTP request directly from uvicorn. The token is in the `Authorization` header. The risk is:
1. Reverse proxy (nginx) strips or modifies the `Authorization` header
2. Token is read from FastMCP's request object but the wrong header key is used (case sensitivity)
3. Token is forwarded but the format changes (e.g., nginx `auth_request` strips headers)

**How to avoid:**
Verify the auth header reaches FastMCP in deployment:
```python
# Debug endpoint during development
@mcp.tool()
async def debug_auth_headers(ctx) -> dict:
    """DEBUG ONLY — list all request headers."""
    return dict(ctx.request_context.request.headers)
```

In production (nginx), ensure `Authorization` header is explicitly forwarded:
```nginx
location /mcp/ {
    proxy_pass http://127.0.0.1:8005;
    proxy_set_header Authorization $http_authorization;  # must be explicit
    proxy_pass_header Authorization;  # if backend expects it
}
```

**Warning signs:**
- Auth works in dev (direct connection), fails in production (behind nginx)
- Token visible in MCP client logs but auth fails server-side
- `Authorization` header missing from FastMCP's `request.headers` dict

**Phase to address:** Phase 4 (Auth Refactor) — verify token extraction in deployment config

---

### Pitfall 8: MCPToolRegistry Accessed Before `nautobot.setup()` in Standalone Process

**What goes wrong:**
Third-party code or tests import from `nautobot_app_mcp_server` and try to access `MCPToolRegistry.get_instance()` or `register_mcp_tool()` before `nautobot.setup()` has run. If `MCPToolRegistry` or the tools module imports any Django model at module level, this raises `RuntimeError: Django wasn't set up yet`.

**Why it happens:**
The embedded architecture's `MCPToolRegistry` is Django-model-agnostic (only stores function references). But `register_mcp_tool()` calls in `tools/__init__.py` import tool implementations that may transitively import Django models.

```python
# tools/core.py
from nautobot.dcim.models import Device  # ← if this import runs at module level
                                       #    before nautobot.setup(), it fails
```

**How to avoid:**
Keep all model imports **inside** tool functions (lazy) or **inside** `@sync_to_async`-wrapped inner functions. The `MCPToolRegistry` itself has no Django dependencies — only the tool implementations do.

```python
# CORRECT: model imported inside the async tool handler
async def device_list(ctx, limit=25):
    from nautobot.dcim.models import Device  # ← lazy import, safe
    @sync_to_async
    def _query():
        return list(Device.objects.all()[:limit])
    return await _query()
```

Add a startup validation test that imports the entire tools package before `nautobot.setup()` and asserts it succeeds (it should, if lazy imports are used).

**Warning signs:**
- `RuntimeError: Django wasn't set up yet` when importing `nautobot_app_mcp_server.tools`
- Works after `nautobot.setup()`, fails before
- Third-party `register_mcp_tool()` calls fail at import time

**Phase to address:** Phase 2 (Tool Registration Refactor) — lazy import audit

---

### Pitfall 9: MCP Endpoint URL Changes — Clients Break

**What goes wrong:**
Claude Desktop or other MCP clients are configured to connect to `http://nautobot:8080/plugins/nautobot-app-mcp-server/mcp/`. After migration to standalone, the endpoint moves to `http://mcp-server:8005/mcp/`. All client configs are now wrong.

**Why it happens:**
The embedded MCP server was at Nautobot's plugin URL. The standalone MCP server runs on its own port. The URL change is a breaking change for all MCP clients.

**How to avoid:**
Provide a clear migration path with a deprecation period:
1. Keep the embedded endpoint functional at the old URL during a transition window
2. Update `SKILL.md` and documentation to reflect the new URL
3. Provide a CLI flag `--legacy-embedded-mode` that preserves the old URL during transition
4. Document the new URL prominently in `docs/admin/upgrade.md`

```python
# upgrade path in nautobot-server management command
# Keep old endpoint alive for deprecation period:
# 1.x: Both embedded (old) and standalone (new) available
# 2.0: Standalone only, embedded removed
```

**Warning signs:**
- MCP clients return "connection refused" or "invalid endpoint" after upgrade
- `SKILL.md` references old URL
- Documentation still points to `/plugins/nautobot-app-mcp-server/mcp/`

**Phase to address:** Phase 6 (UAT & Validation) — full client reconfiguration validation

---

### Pitfall 10: `NautobotAppConfig` Still Required for Plugin Discovery

**What goes wrong:**
If the app is migrated to standalone but still has a `NautobotAppConfig` in `__init__.py`, and is listed in `PLUGINS`, Nautobot may try to auto-discover and load it as a plugin. This could cause duplicate initialization or conflicts between the app plugin loading and the standalone server.

**Why it happens:**
Nautobot's plugin system loads any app in `PLUGINS` by importing its `__init__.py` and calling `setup()` on the `NautobotAppConfig`. If the standalone MCP server is also running (started separately), both the plugin loader and the standalone process try to initialize the same components.

**How to avoid:**
If keeping the standalone as a Nautobot app (for settings management and config inheritance):
```python
# __init__.py — guard to prevent double-init
class NautobotAppMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"

    def ready(self):
        # Only register if NOT running as standalone MCP server
        if os.environ.get("NAUTOBOT_MCP_STANDALONE") != "1":
            from .mcp import register_core_tools
            register_core_tools()  # No-op if already registered by standalone
```

Alternatively, remove from `PLUGINS` entirely and manage config via env vars or `nautobot_config.py`'s `PLUGINS_CONFIG`.

**Warning signs:**
- Duplicate tool registrations (same tool registered twice)
- `ValueError: Tool already registered` on startup
- Plugin appears twice in Nautobot admin UI

**Phase to address:** Phase 0 (Project Setup) — decide app vs standalone-only packaging

---

### Pitfall 11: Database Connection to Wrong Instance (Split-Brain)

**What goes wrong:**
The MCP server's `nautobot_config.py` points to `NAUTOBOT_DB_HOST=localhost` (the default), while Nautobot itself connects to `nautobot-db` (Docker service name). The MCP server reads from a local SQLite or wrong Postgres, while Nautobot writes to the real DB. Data is stale or missing.

**Why it happens:**
`nautobot.setup()` reads DB connection params from `NAUTOBOT_DB_*` env vars. If the MCP server's env doesn't include these (the Docker container doesn't inherit Nautobot's env), it falls back to Django defaults.

**How to avoid:**
Explicitly pass all DB connection env vars to the MCP server container:
```yaml
# docker-compose.yml
services:
  nautobot-mcp:
    environment:
      NAUTOBOT_CONFIG: /config/nautobot_config.py
      NAUTOBOT_DB_HOST: nautobot-db        # Must match Nautobot's DB host
      NAUTOBOT_DB_PORT: 5432
      NAUTOBOT_DB_NAME: ${NAUTOBOT_DB_NAME}
      NAUTOBOT_DB_USER: ${NAUTOBOT_DB_USER}
      NAUTOBOT_DB_PASSWORD: ${NAUTOBOT_DB_PASSWORD}
    volumes:
      - ./nautobot_config.py:/config/nautobot_config.py:ro
    depends_on:
      - nautobot-db
```

Also validate at startup by querying a known Nautobot-only table:
```python
nautobot.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("SELECT 1 FROM extras_jobresult LIMIT 1")  # nautobot-specific table
```

**Warning signs:**
- MCP returns empty querysets for data known to exist in Nautobot
- `device_list` returns 0 devices on MCP but 5 in Nautobot UI
- MCP server has no `extras_jobresult` table

**Phase to address:** Phase 0 (Project Setup) — Docker Compose env var wiring

---

### Pitfall 12: `view.py` and `urls.py` Not Removed — Old Endpoint Still Accessible

**What goes wrong:**
After migrating to standalone, `view.py` and `urls.py` are left in the codebase. If the app is still in `PLUGINS`, the old embedded endpoint is still mounted at `/plugins/nautobot-app-mcp-server/mcp/`. Users hit the old endpoint and get the broken embedded behavior while the documentation says to use the new standalone port.

**Why it happens:**
The Phase 5 "Bridge Cleanup" task is deferred or forgotten. `view.py` and `urls.py` are still committed. The `NautobotAppConfig` still has `name = "nautobot_app_mcp_server"` and `urls.py` is auto-discovered by Nautobot's plugin URL routing.

**How to avoid:**
Include `view.py` and `urls.py` removal as an explicit Phase 5 task with a checklist:
- [ ] Delete `nautobot_app_mcp_server/urls.py`
- [ ] Remove `urls` from `NautobotAppConfig` in `__init__.py`
- [ ] Remove `@csrf_exempt` and `mcp_view` from `__init__.py` exports
- [ ] Verify old endpoint returns 404 after cleanup
- [ ] Document new standalone endpoint in upgrade notes

**Warning signs:**
- Old endpoint still responds with MCP JSON-RPC after migration
- Two endpoints both serve MCP (old broken + new standalone)
- `urls.py` still has `path("mcp/", mcp_view)` after Phase 5

**Phase to address:** Phase 5 (Bridge Cleanup) — explicit deletion checklist

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `--workers 1` | Sessions work out of the box | No horizontal scaling, single point of failure | v1 only; must document as limitation |
| In-memory session storage | No Redis dependency | Sessions lost on restart or worker switch | Single-worker dev; document clearly |
| Lazy model imports | App loads without Django setup | Harder to catch import errors early | Always — never import Django models at module level |
| Skip Docker health check | Faster startup | Silent failures, hard to debug | Never — add `livenessProbe` for MCP server |
| Keep old `view.py` during transition | Backward compat | Users hit wrong endpoint | Only during explicit deprecation window, documented |
| Single DB connection (no pooling config) | Simple config | Connection exhaustion under load | Only for low-traffic dev; use `CONN_MAX_AGE` in prod |

---

## Integration Gotchas

### Integration: uvicorn ↔ FastMCP

| Common Mistake | Correct Approach |
|----------------|------------------|
| Not specifying `--workers 1` | Sessions live in each process; workers > 1 = session loss between requests |
| Missing `--host 127.0.0.1` (exposes publicly) | Bind to localhost for proxy-only access; `--host 0.0.0.0` only with firewall |
| Not configuring `proxy_fix` middleware | `X-Forwarded-*` headers ignored; `request.is_secure()` wrong behind nginx |
| Not setting `BACKWARD_COMPAT_MODE` env | Old clients break without a clear error message |

### Integration: Nautobot ↔ Standalone MCP Server

| Common Mistake | Correct Approach |
|----------------|------------------|
| Different `NAUTOBOT_CONFIG` files | Both must use the same `nautobot_config.py` — shared volume in Docker |
| MCP server starts before Nautobot DB is ready | Add `depends_on: nautobot-db` with healthcheck in docker-compose |
| `nautobot.setup()` called twice (import + direct) | It's idempotent but confirms mis-structured startup |
| Token auth uses wrong token format (with `nbapikey_` prefix) | Nautobot tokens are 40-char hex with no prefix; strip prefix in auth |
| MCP server uses stale token DB | Tokens are in shared DB — no special handling needed |

### Integration: Third-Party Plugins ↔ Standalone MCP Registry

| Common Mistake | Correct Approach |
|----------------|------------------|
| Plugins call `register_mcp_tool()` from `ready()` — but `nautobot.setup()` not called yet | Entry point calls `nautobot.setup()` first; plugin `ready()` hooks fire during `django.setup()` which happens inside `nautobot.setup()` |
| Plugin's `mcp_tools` module imports models at top level | Convention: `mcp_tools` modules must use lazy imports; audit with import test |
| Tool registration in `post_migrate` never fires | Replace with startup discovery in `main.py` after `django.setup()` completes |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `CONN_MAX_AGE` not set | New DB connection per request | Set `CONN_MAX_AGE=300` in `nautobot_config.py` | ~50+ concurrent MCP requests |
| `select_related` missing on list tools | N+1 queries per page | Require `select_related` chain in code review for every list tool | list tools with >10 results |
| No pagination limit cap | Client requests `limit=1000000` | Enforce `LIMIT_MAX=1000` in `paginate_queryset` | Large limit crashes or timeouts |
| Session dict deserialization per tool call | CPU overhead at scale | Session dict ops are O(1) dict access — not a concern at expected scale | >10k tools with complex session state |
| No connection pool sizing for multi-worker | DB connection exhaustion | uvicorn `--workers 4` + PostgreSQL `max_connections` ≥ `(workers × pool_size) + nautobot_connections` | 4+ workers, high concurrency |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| MCP server exposed publicly (no auth) | Unauthenticated access to all Nautobot data | Always require `Authorization: Token <key>` header; reject at FastMCP layer if missing |
| Token key logged in plaintext | Token exposure in server logs | Never log `auth_header[6:]`; log only `Token abc...12` (last 2 chars) |
| `Authorization` header forwarded by nginx without `InternalRedirect` | Token visible in access logs | Use `proxy_set_header` not `proxy_pass_header` for `Authorization` |
| MCP server can be reached without TLS in production | Token interception via network eavesdropping | Put behind HTTPS-terminating reverse proxy; uvicorn listens on localhost only |
| No rate limiting on MCP endpoint | Token enumeration via brute force | Nautobot Token lookup is DB-backed; add uvicorn `--limit-concurrency` for DDoS protection |
| `nautobot_config.py` world-readable in container | DB credentials exposed | `0600` permissions on config file; use Docker secrets for production |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Old endpoint documented in SKILL.md | Claude Desktop connects to wrong URL and fails silently | Update SKILL.md endpoint URL as part of Phase 5 cleanup; version the SKILL.md package |
| No error message when token is expired | Agent retries forever with no explanation | Check `token.is_expired` in auth and return explicit error dict, not silent `AnonymousUser` |
| Progressive disclosure not explained | New users don't know how to enable DCIM/IPAM tools | SKILL.md must document `mcp_enable_tools(scope="dcim")` with clear examples |
| Session state not visible to user | User enables tools but can't verify it worked | `mcp_list_tools` should return structured output (not just text) so agent can parse |

---

## "Looks Done But Isn't" Checklist

- [ ] **`nautobot.setup()` placed at entry point:** Verified at first line of `main.py`, before any model imports
- [ ] **All model imports are lazy:** `from nautobot.dcim.models import Device` is inside tool handlers, not at module level — audit `tools/core.py`
- [ ] **`--workers 1` enforced in deployment:** `docker-compose.yml` and systemd unit file both specify single worker
- [ ] **DB connection validated at startup:** Startup script queries a Nautobot-specific table (e.g., `extras_jobresult`) and exits non-zero on failure
- [ ] **`NAUTOBOT_DB_*` env vars documented:** All required env vars listed in `docs/admin/install.md` with example values
- [ ] **`nautobot_config.py` shared with Nautobot:** Docker volume mount verified in `docker-compose.yml`
- [ ] **`view.py` and `urls.py` deleted:** Old endpoint no longer accessible; verified by `GET /plugins/nautobot-app-mcp-server/mcp/` → 404
- [ ] **SKILL.md endpoint updated:** References `http://localhost:8005/mcp/` (or production equivalent), not the old plugin URL
- [ ] **`MCPToolRegistry` accessible to third-party plugins:** `register_mcp_tool()` works from `AppConfig.ready()` hooks; tested with a dummy plugin
- [ ] **Auth token format correct:** 40-char hex key, no `nbapikey_` prefix, verified against live Nautobot Token model
- [ ] **Session state survives across requests:** UAT test with two sequential requests verifies progressive disclosure works end-to-end
- [ ] **`sync_to_async` used on all ORM calls:** Code review checklist item passed; no `SynchronousOnlyOperation` in logs

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| P1: `nautobot.setup()` called after model imports | LOW | Move `nautobot.setup()` to entry point; convert top-level model imports to lazy imports |
| P2: Wrong DB config | MEDIUM | Update env vars or `nautobot_config.py`; restart container; verify with data smoke test |
| P3: `post_migrate` never fires | MEDIUM | Implement startup plugin discovery in `main.py`; add integration test for third-party tool registration |
| P4: Sessions lost on multi-worker | HIGH | Switch to `--workers 1` (immediate fix); implement Redis sessions for v2 |
| P5: ORM without `sync_to_async` | LOW | Wrap all ORM calls in `@sync_to_async(thread_sensitive=True)` inner functions |
| P6: Monkey-patched dataclass attrs | LOW | Replace `._mcp_tool_state` and `._cached_user` with session dict access |
| P7: Auth token stripped by proxy | MEDIUM | Update nginx config with explicit `proxy_set_header Authorization`; test with debug tool |
| P8: Registry accessed before setup | LOW | Audit `tools/` package for top-level model imports; fix to lazy imports |
| P9: Old endpoint still accessible | LOW | Delete `view.py` + `urls.py`; update SKILL.md; restart container |
| P10: Duplicate plugin init | LOW | Remove from `PLUGINS` or add env var guard in `ready()` |
| P11: Split-brain DB | MEDIUM | Update Docker env vars to point to correct DB; run data smoke test |
| P12: Old bridge files left in place | LOW | Delete `view.py`, `urls.py`; verify 404 on old endpoint |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|--------------|
| P1: `nautobot.setup()` ordering | Phase 0 | `python -c "from nautobot_app_mcp_server.tools import *"` succeeds before setup |
| P2: `NAUTOBOT_CONFIG` misconfigured | Phase 0 | Container starts, DB query succeeds, `extras_jobresult` table accessible |
| P3: `post_migrate` not firing | Phase 2 | Integration test: fake plugin calls `register_mcp_tool()` from `ready()` → tool appears |
| P4: Multi-worker session loss | Phase 0 | Document `--workers 1` requirement; UAT with `uvicorn --workers 4` shows failure |
| P5: ORM without `sync_to_async` | Phase 2 | `grep -r "Device.objects" nautobot_app_mcp_server/mcp/tools/` returns only inside `@sync_to_async` blocks |
| P6: Monkey-patching broken | Phase 3 | Progressive disclosure integration test passes with real `ctx.request_context.session` |
| P7: Auth header stripped | Phase 4 | Dev proxy test: `curl -H "Authorization: Token $KEY"` arrives at FastMCP |
| P8: Registry accessed early | Phase 2 | Startup validation test: import all tools modules before `nautobot.setup()` |
| P9: Old endpoint breaks clients | Phase 6 | Old URL returns 404; new URL works; SKILL.md updated |
| P10: Plugin double-init | Phase 0 | App not in `PLUGINS`; OR env var guard present; no duplicate registrations |
| P11: Split-brain DB | Phase 0 | Docker health check + startup DB query validation |
| P12: Old bridge files remain | Phase 5 | `view.py` deleted; `urls.py` deleted; `__init__.py` exports checked |

---

## Sources

- `docs/dev/ARCHITECTURE.md` — standalone verification, `nautobot.setup()` analysis, Docker deployment design
- `docs/dev/mcp-implementation-analysis.md` — session persistence patterns, FastMCP `StreamableHTTPSessionManager` internals
- `ROADMAP.md` — Phase 0–6 scope, migration requirements, tool registration API design
- `STATE.md` — current embedded architecture state (8 concurrency primitives, monkey-patching patterns to remove)
- `nautobot_app_mcp_server/mcp/server.py` — current `_list_tools_mcp` override pattern to replace
- `nautobot_app_mcp_server/mcp/session_tools.py` — current monkey-patched `_mcp_tool_state` pattern to replace with session dict
- `nautobot_app_mcp_server/mcp/auth.py` — current `._cached_user` monkey-patch to replace with session dict
- `nautobot_app_mcp_server/mcp/view.py` — current bridge to delete in Phase 5
- `docs/dev/import_and_uat.md` — UAT patterns applicable to new architecture

---
*Pitfalls research for: Nautobot App + FastMCP separate-process architecture migration*
*Researched: 2026-04-05*
