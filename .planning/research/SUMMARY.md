# Research Summary — Nautobot MCP Server

**Project:** `nautobot-app-mcp-server`
**Domain:** Nautobot MCP Server — embedded protocol adapter
**Date:** 2026-04-01

---

## Key Findings

### 1. Option A (ASGI Bridge) Resolved — Use It

The DESIGN.md marks Option A as `NotImplementedError`. This is unnecessary.

**Resolution: Option A — Django URL Route + ASGI Bridge** is the correct approach. Evidence:
- Nautobot's `plugin_patterns` auto-discovers `plugin.urls.urlpatterns` — zero core file modifications
- FastMCP's `streamable_http_app()` returns a pure Starlette ASGI app
- Bridge is `asgiref.wsgi.WsgiToAsgi(app)` — one line, no extra packages
- `django-starlette` does NOT exist on PyPI — this is a non-starter
- **Option B (separate worker) is an anti-feature**: extra port, firewall rules, requires Redis for session sharing, breaks unified permission model

### 2. `django-starlette` Is a Dead End

The approach in DESIGN.md references `django-starlette` for ASGI mounting. This package doesn't exist on PyPI. Use `asgiref` instead — it's already included with Django.

### 3. `mcp` SDK (Anthropic) vs `fastmcp` (Prefect) Clarified

Both are real and compatible:
- `mcp = "^1.26.0"` — official Anthropic MCP Python SDK
- `fastmcp = "^3.2.0"` — Prefect's fastmcp package, powers 70% of MCP servers

The `fastmcp` standalone package (prefect/jlowin) re-exports from `mcp.server.fastmcp` and is actively maintained. Use it directly.

### 4. `sync_to_async` Thread Sensitivity Is Critical

`asgiref.sync.sync_to_async(fn, thread_sensitive=True)` is mandatory for all Django ORM calls from FastMCP async tool handlers. Without `thread_sensitive=True`, Django's thread-local connection pool is lost on every call.

### 5. FastMCP Session State Is In-Memory

FastMCP's `StreamableHTTPSessionManager` stores per-conversation state in-memory. This works fine for single-worker deployments (dev, Docker Compose). Multi-worker gunicorn deployments lose sessions across workers — document as a v2 item, not a v1 blocker.

### 6. Auth Token Comes From MCP Request Context

`ctx.request_context.request` is the MCP SDK's request object (not Django's `HttpRequest`). Header extraction (`Authorization: Token`) uses this, not `request.headers` from Django.

### 7. `post_migrate` Signal Chain Is Correct

Django fires `post_migrate` after migrations for each app. Connecting `register_mcp_tools()` to `post_migrate` from within `ready()` means the signal fires when THIS app's migrations run — guaranteeing all third-party `ready()` hooks have already completed. The order is safe.

---

## Stack Recommendations

| Package | Version | Notes |
|---|---|---|
| `mcp` | `^1.26.0` | Official Anthropic MCP Python SDK |
| `fastmcp` | `^3.2.0` | FastMCP server framework (prefect) |
| `asgiref` | `^3.11.1` | Django ASGI bridge (ships with Django, explicit dep) |
| `starlette` | `>=1.0.0` | FastMCP dependency, Python >=3.10 |
| `anyio` | `>=3.6.2` | Async I/O foundation (mcp/starlette dependency) |

**Do NOT add**: `django-starlette`, `channels`, `uvicorn` (unless running Option B)

---

## Features: Table Stakes vs Differentiators vs Anti-Features

### Table Stakes (must have or users leave)
- 10 core read tools: device_list/get, interface_list/get, ipaddress_list/get, prefix_list, vlan_list, location_list, search_by_name
- 3 meta tools: mcp_enable_tools, mcp_disable_tools, mcp_list_tools
- Token auth with Nautobot `.restrict()` enforcement
- Cursor pagination (default 25, max 1000) with auto-summarize at 100+
- MCP endpoint reachable at `/plugins/<base_url>/mcp/`

### Differentiators (competitive advantage)
- Progressive disclosure (Core + App tiers) — avoids Claude tool explosion
- `register_mcp_tool()` public API for third-party Nautobot apps — network effect
- Per-model named tools (not generic query) — better Claude discoverability
- Embedded in Django (zero network hop)
- `nautobot-mcp-skill` SKILL.md package

### Anti-Features (do NOT build in v1)
- Write tools (create/update/delete)
- MCP `resources` or `prompts` endpoints
- Redis session backend
- Option B separate worker
- Tool-level field permissions
- Streaming SSE

---

## Top Pitfalls

| # | Pitfall | Severity | Phase |
|---|---|---|---|
| PIT-01 | Missing fastmcp/mcp dependencies | Critical | Phase 1a |
| PIT-02 | Package name mismatch (nautobot_mcp_server vs nautobot_app_mcp_server) | Critical | Phase 0 |
| PIT-03 | ASGI app created at import time | High | Phase 1b |
| PIT-04 | Wrong ASGI bridge (async_to_sync instead of WsgiToAsgi) | High | Phase 1b |
| PIT-07 | Pagination counts after slice (auto-summarize never fires) | High | Phase 3 |
| PIT-09 | base_url mismatch (mcp-server vs nautobot-mcp-server) | High | Phase 0 |
| PIT-10 | Anonymous auth silent empty results | High | Phase 2 |
| PIT-14 | search_by_name complexity underestimated | High | Phase 4 |
| PIT-16 | Auth token from wrong request object (MCP not Django) | Medium | Phase 2 |

---

## Research Coverage

| Document | Lines | Coverage |
|---|---|---|
| `STACK.md` | 348 | Python 3.10-14, Poetry, Nautobot, Docker, MCP SDK, dependencies |
| `FEATURES.md` | 216 | 21 features categorized, complexity, dependencies, MVP definition |
| `ARCHITECTURE.md` | 543 | 8-layer data flow, 10 components, Option A/B resolution, 5-phase build order |
| `PITFALLS.md` | 415 | 18 pitfalls, warning signs, prevention, quality gates |

---

*Last updated: 2026-04-01 after research synthesis*
