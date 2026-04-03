# Production Data Import & UAT Guide

This document covers the full workflow for importing real data from a production Nautobot server into the local dev environment, and then running User Acceptance Testing (UAT) against the MCP server.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Configuration](#2-configuration)
3. [Reset & Import Script](#3-reset--import-script)
4. [Phase 1: Fetch from Production](#4-phase-1-fetch-from-production)
5. [Phase 2: Import into Dev DB](#5-phase-2-import-into-dev-db)
6. [Running UAT Tests](#5-running-uat-tests)
7. [Known Issues & Debugging](#6-known-issues--debugging)

---

## 1. Architecture Overview

The import is split into two phases to handle the network and performance constraints of fetching from a remote production server:

```text
┌─────────────────────┐       Phase 1 (host)        ┌─────────────────────┐
│  Production Nautobot │ ── REST API ──→ scripts/   │  import_cache/       │
│  (https://nautobot. │         fetch_production_   │  *.json (gitignored) │
│   netnam.vn/)       │         data.py             └─────────────────────┘
└─────────────────────┘                                                             
                               Phase 2 (container)    ┌─────────────────────┐
                              ┌──────────────────┐     │  Dev Nautobot DB     │
                              │ import_produc-  │ ──→ │  (Docker volume)     │
                              │ tion_data.py    │     │  localhost:8080      │
                              └──────────────────┘     └─────────────────────┘
                                                              │
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │  MCP Server UAT     │
                                                    │  /plugins/nautobot- │
                                                    │  app-mcp-server/    │
                                                    │  mcp/               │
                                                    └─────────────────────┘
```

**Why two phases?**

- Production API calls are slow and can time out; JSON caching makes Phase 2 fast and resumable.
- Phase 2 runs inside the container with direct DB access — no network calls needed.
- `import_cache/` is gitignored; credentials are in `nautobot_import.env`.

---

## 2. Configuration

### 2.1 Create `nautobot_import.env`

Copy the example and fill in your values:

```bash
cp nautobot_import.env.example nautobot_import.env
```

Required variables:

```env
# Production server
NAUTOBOT_PROD_URL=https://nautobot.netnam.vn
NAUTOBOT_PROD_TOKEN=nbapikey_...          # REST API token from production

# Optional: filter devices by name (comma-separated, empty = all)
DEVICE_NAMES=HQV-PE1,HN-PP1
```

> **Security:** `nautobot_import.env` is gitignored by the existing `*.env` rule in `.gitignore`. Never commit tokens.

### 2.2 Credential Setup for Production

Get your API token from the production Nautobot UI:
**Admin → Users → Tokens → Add Token**

The token format is typically `nbapikey_xxxxxxxxxxxx`.

---

## 3. Reset & Import Script

For convenience, `scripts/reset_dev_db.sh` automates the full workflow in one command. It replaces the manual steps below.

### 3.1 Quick Start

```bash
# Interactive menu (shows cache/DB status before choosing)
bash scripts/reset_dev_db.sh

# CLI shortcuts
bash scripts/reset_dev_db.sh --reset      # Reset DB only
bash scripts/reset_dev_db.sh --fetch       # Phase 1: fetch from production
bash scripts/reset_dev_db.sh --import     # Reset + import (most common)
bash scripts/reset_dev_db.sh --all         # Full pipeline: reset → fetch → import
```

### 3.2 What the Script Does

**`--reset` / `do_reset`:**

1. Stops all containers (releases DB connections)
2. Drops and recreates the `nautobot` database
3. Runs migrations
4. Creates superuser from `creds.env`
5. Restarts containers and waits for health

**`--fetch` / `do_fetch`:**
- Runs `scripts/fetch_production_data.py` on the host (no Docker needed)

**`--import` / `do_import`:**
1. Runs `do_reset` (fresh, clean DB)
2. Verifies DB is empty
3. Runs `nautobot-server import_production_data --cache-dir /source/import_cache`
4. Verifies imported row counts

### 3.3 Key Implementation Notes

| Issue | Cause | Fix |
|---|---|---|
| `psql -U postgres` fails silently | Dev DB user is `nautobot` | Script sources `development.env` + `creds.env` |
| `DROP DATABASE` fails "currently open" | Active connections to target DB | Script stops all containers first |
| Import fails "cache not found" | `--cache-dir` not passed | Script passes `--cache-dir /source/import_cache` |
| Import fails `location_type_id is null` | Fresh DB has no `LocationType` rows | Auto-creates a default `Region` type |
| Import exits 0 with no output | Used `python ...` instead of `nautobot-server` | Script uses `nautobot-server import_production_data` |

---

## 4. Phase 1: Fetch from Production

### 4.1 What Gets Fetched

| File | Records | Notes |
| --- | --- | --- |
| `statuses.json` | ~5 | Lookup table |
| `roles.json` | ~10 | Lookup table |
| `device_types.json` | ~20 | Includes manufacturer name |
| `platforms.json` | ~5 | Lookup table |
| `namespaces.json` | ~5 | IPAM namespace |
| `locations.json` | ~100 | Hierarchical locations |
| `devices.json` | ~5 | Resolved FK names |
| `interfaces.json` | ~200 | Per-device interfaces |
| `ip_addresses.json` | ~19,500 | All IPs (slowest endpoint) |
| `prefixes.json` | ~500 | All prefixes |
| `vlans.json` | ~200 | All VLANs |
| `_manifest.json` | 1 | Fetch metadata, timestamp |

**Total: ~38,000 records** — expect 3–10 minutes depending on network.

### 4.2 Running Phase 1

From the **host** (no Docker required):

```bash
cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server
python -u scripts/fetch_production_data.py
```

The `-u` flag ensures unbuffered output so you can see progress in real-time.

### 4.3 Resume Support

If Phase 1 times out (e.g., on `ip_addresses`), re-run the same command. Already-fetched files are skipped:

```
[4/6] Fetching interfaces for 5 devices...
    interfaces: already exists (247 records, skipping)
```

### 4.4 Troubleshooting Phase 1

| Problem | Cause | Fix |
| --- | --- | --- |
| `NAUTOBOT_PROD_URL and NAUTOBOT_PROD_TOKEN must be set` | `.env` not found | Run from project root where `nautobot_import.env` exists |
| HTTP 401 | Bad token | Regenerate token on production server |
| HTTP 429 | Rate limited | Wait 60s, then re-run |
| Timeout on `ip_addresses` | 19K+ records, slow prod server | Re-run same command — file is cached |

---

## 5. Phase 2: Import into Dev DB

### 5.1 Running Phase 2

From **inside the Nautobot container**:

```bash
docker exec -it nautobot-app-mcp-server-nautobot-1 \
  nautobot-server import_production_data
```

Optional flags:

```bash
# Preview without writing to DB
docker exec ... nautobot-server import_production_data --dry-run

# Use a custom cache directory
docker exec ... nautobot-server import_production_data \
  --cache-dir /tmp/my_cache
```

### 5.2 Import Order

The import command runs in this fixed order (respecting FK dependencies):

```
0. Pre-create lookup entities (Status, Role, Manufacturer, DeviceType, Platform, Namespace)
1. Locations (with parent hierarchy resolution)
2. Devices
3. Interfaces
4. IPAM (Prefixes → IP Addresses → VLANs)
5. Verification counts
```

**Key performance choices:**
- **Locations, Devices, Interfaces, VLANs:** `bulk_create(ignore_conflicts=True)` — single SQL INSERT per batch
- **Prefixes:** Batched `bulk_create` (500/batch)
- **IP Addresses:** `get_or_create` — unavoidable because Nautobot validates parent prefix per row

### 5.3 Typical Import Times

| Model | Count | Method | Time |
| --- | --- | --- | --- |
| Locations | ~100 | bulk_create | < 1s |
| Devices | ~5 | bulk_create | < 1s |
| Interfaces | ~250 | bulk_create | < 1s |
| Prefixes | ~500 | bulk_create batches | < 5s |
| IP Addresses | ~19,500 | get_or_create | ~20s |
| VLANs | ~200 | bulk_create | < 1s |
| **Total** | **~38,000** | — | **~23s** |

### 5.4 Verify the Import

```bash
docker exec nautobot-app-mcp-server-nautobot-1 \
  nautobot-server import_production_data 2>&1 | grep "Verification"
```

Expected output:

```
[5/5] Verification:
  Locations:    105
  Devices:     5
  Interfaces:  247
  IPAddresses: 19522
  Prefixes:   488
  VLANs:      203
```

### 5.5 Troubleshooting Phase 2

| Error | Cause | Fix |
| --- | --- | --- |
| `Cache file not found` | Phase 1 not run | Run Phase 1 first |
| `null value in column "location_type_id"` | Root location has no type | Fixed: falls back to first available `LocationType` |
| `null value in column "manufacturer_id"` | DeviceType created before Manufacturer | Fixed: Manufacturer is pre-created before DeviceType |
| `VLAN() got unexpected keyword arguments: 'namespace'` | Model version mismatch | Fixed: `namespace` removed from VLAN bulk_create |
| `Prefix.DoesNotExist: Could not determine parent Prefix` | IP inside atomic block | Fixed: IP import moved outside atomic transaction |

---

## 6. Running UAT Tests

### 6.1 MCP Endpoint URL

Once the container is running (after the fixes described in §6 are applied):

```
http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/
```

> **Note:** The endpoint is a POST-only JSON-RPC 2.0 endpoint. A GET returns 307 redirect.

### 5.2 MCP JSON-RPC Request Format

All requests follow JSON-RPC 2.0:

```bash
curl -s http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/ \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### 5.3 Smoke Test

```bash
# List all tools
curl -s http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/ \
  -X POST -H "Content-Type: application/json" \
  -H "X-Requested-With: XMLHttpRequest" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool | grep '"name"' | head -20
```

Expected: 13 tools including `device_list`, `device_get`, `interface_list`, `search_by_name`, etc.

### 5.4 Using the UAT Test Script

```bash
docker exec nautobot-app-mcp-server-nautobot-1 \
  python /source/scripts/run_mcp_uat.py
```

The test script is at `scripts/run_mcp_uat.py`. It exercises all 13 MCP tools against the dev server.

### 5.5 Test Coverage Map

| Test Category | Tools Tested | Key Assertions |
| --- | --- | --- |
| Auth & Session | 11, 12, 13 | `mcp_list_tools`, `mcp_enable_tools`, `mcp_disable_tools` |
| List Tools | 1, 3, 5, 7, 8, 9 | Pagination, filters, field completeness |
| Get Tools | 2, 4, 6 | Lookup by name/UUID, nested relationships |
| Search | 10 | AND semantics, pagination, cursor round-trip |
| Auth Enforcement | — | Anonymous = empty results |

### 5.6 Unit Tests (Fast)

```bash
# Run inside container — 69 tests, ~0.25s
docker exec nautobot-app-mcp-server-nautobot-1 \
  nautobot-server test nautobot_app_mcp_server.mcp.tests
```

---

## 6. Known Issues & Debugging

### 6.1 MCP Endpoint Returns 404

**Symptoms:** `curl http://localhost:8080/plugins/nautobot-app-mcp-server/mcp/` → 404

**Diagnosis:**

```bash
# 1. Check container logs
docker logs nautobot-app-mcp-server-nautobot-1 --tail 10

# 2. Check if plugin is in URL tree (inside container)
docker exec nautobot-app-mcp-server-nautobot-1 \
  python -c "
import os, sys; os.environ['DJANGO_SETTINGS_MODULE']='nautobot_config'
sys.path.insert(0,'/opt/nautobot')
import django; django.setup()
from django.urls import resolve
try:
    r = resolve('/plugins/nautobot-app-mcp-server/mcp/')
    print('RESOLVED:', r.func)
except Exception as e:
    print('FAILED:', e)
"

# 3. Check PLUGINS setting
docker exec nautobot-app-mcp-server-nautobot-1 \
  python -c "
import os, sys; os.environ['DJANGO_SETTINGS_MODULE']='nautobot_config'
sys.path.insert(0,'/opt/nautobot')
import django; django.setup()
from django.conf import settings
print('PLUGINS:', settings.PLUGINS)
"

# 4. Check plugin app configs loaded
docker exec nautobot-app-mcp-server-nautobot-1 \
  python -c "
import os, sys; os.environ['DJANGO_SETTINGS_MODULE']='nautobot_config'
sys.path.insert(0,'/opt/nautobot')
import django; django.setup()
from django.apps import apps
for name in apps.app_configs:
    if 'mcp' in name.lower():
        print('MCP app found:', name)
print('(no MCP app = ready() not called for plugin)')
"
```

**Common causes and fixes:**

| Cause | Fix |
| --- | --- |
| `nautobot_app_mcp_server` not in `settings.PLUGINS` | Add to `development/nautobot_config.py`: `PLUGINS = ["nautobot_app_mcp_server"]` |
| `ready()` does not call `super().ready()` | **Critical:** `NautobotAppMcpServerConfig.ready()` MUST call `super().ready()` to register URL patterns |
| Container was not restarted after code change | `docker restart nautobot-app-mcp-server-nautobot-1` |

### 6.2 MCP Endpoint Returns 500 — `Unknown transport: streamable http`

**Cause:** Transport name in `server.py` uses space instead of hyphen.

**Fix:**

```python
# WRONG (space):
transport="streamable http"

# CORRECT (hyphen):
transport="streamable-http"
```

### 6.3 MCP Endpoint Returns 500 — `WsgiToAsgi missing receive/send`

**Cause:** `WsgiToAsgi` is for WSGI apps. FastMCP is a native ASGI app.

**Fix:** Replace `WsgiToAsgi` with proper ASGI bridge using `asyncio.run()`:

```python
import asyncio
from django.http import HttpResponse
from nautobot_app_mcp_server.mcp.server import get_mcp_app

def mcp_view(request):
    mcp_app = get_mcp_app()
    plugin_prefix = "/plugins/nautobot-app-mcp-server"
    mcp_path = request.path[len(plugin_prefix):]  # '/mcp/'

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": request.method,
        "query_string": request.META.get("QUERY_STRING", "").encode("utf-8"),
        "root_path": plugin_prefix,
        "path": mcp_path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers.items()],
        "server": ("127.0.0.1", 8080),
    }

    messages = []
    status_code = [200]

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            status_code[0] = message.get("status", 200)

    asyncio.run(mcp_app(scope, receive, send))

    body = b"".join(
        msg.get("body", b"") if isinstance(msg.get("body"), bytes)
        else (msg.get("body") or "").encode()
        for msg in messages if msg["type"] == "http.response.body"
    )

    resp = HttpResponse(body, status=status_code[0])
    for msg in messages:
        if msg["type"] == "http.response.start":
            for k, v in msg.get("headers", []):
                resp[k.decode()] = v.decode()
    return resp
```

### 6.4 MCP Endpoint Returns 403 (Debug Toolbar Blocking)

**Cause:** `DEBUG=True` in dev config activates `debug_toolbar`, which wraps responses and blocks AJAX POST requests from non-toolbar sources.

**Fix options:**

1. Test from inside the container:
   ```bash
   docker exec nautobot-app-mcp-server-nautobot-1 \
     python -c "import asyncio, json; ..."
   ```

2. Disable debug toolbar in `development/nautobot_config.py`:
   ```python
   DEBUG = False  # or unset NAUTOBOT_DEBUG env var
   ```

3. Add `X-Requested-With: XMLHttpRequest` header to all POST requests.

### 6.5 Debug Toolbar Intercepts Requests

When `DEBUG=True`, the debug toolbar may intercept MCP requests. Check container logs for actual application errors:

```bash
docker logs nautobot-app-mcp-server-nautobot-1 --tail 20
```

The traceback will show the real error beneath any toolbar wrapping.

---

## Appendix: Key File Locations

| File | Purpose |
| --- | --- |
| `scripts/fetch_production_data.py` | Phase 1 — fetch from production, save to JSON |
| `nautobot_app_mcp_server/management/commands/import_production_data.py` | Phase 2 — load JSON into dev DB |
| `nautobot_app_mcp_server/mcp/server.py` | FastMCP server setup |
| `nautobot_app_mcp_server/mcp/view.py` | Django → FastMCP ASGI bridge |
| `nautobot_app_mcp_server/__init__.py` | `NautobotAppMcpServerConfig` with `ready()` hook |
| `nautobot_app_mcp_server/urls.py` | Django URL pattern: `path("mcp/", mcp_view)` |
| `import_cache/` | Phase 1 output / Phase 2 input (gitignored) |
| `nautobot_import.env` | Production credentials (gitignored) |
| `scripts/run_mcp_uat.py` | UAT test runner |
