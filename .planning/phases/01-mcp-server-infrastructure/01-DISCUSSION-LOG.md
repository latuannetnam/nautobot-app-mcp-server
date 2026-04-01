# Phase 1: MCP Server Infrastructure - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-04-01
**Phase:** 01-mcp-server-infrastructure
**Mode:** assumptions (all decisions from research)
**Trigger:** /gsd:new-project --auto chain → /gsd:discuss-phase 1 --auto

## Assumptions Presented

### Architecture
| Assumption | Confidence | Evidence |
|---|---|---|
| Option A (ASGI bridge) not Option B (separate worker) | Confident | Nautobot plugin_patterns auto-discovery; `asgiref.wsgi.WsgiToAsgi` confirmed; `django-starlette` does not exist on PyPI |
| `WsgiToAsgi` not `async_to_sync` | Confident | Bridge direction is Django WSGI → FastMCP ASGI; `async_to_sync` is for async→sync |
| Lazy ASGI app init (not at import time) | Confident | Django startup lacks request context; `sync_to_async(thread_sensitive=True)` requires active context |
| In-memory session state (not Redis) | Confident | DESIGN.md defers Redis to v2; in-memory works for single-worker |

### Package Identity
| Assumption | Confidence | Evidence |
|---|---|---|
| Package name = `nautobot_app_mcp_server` | Confident | Matches actual directory name and pyproject.toml Poetry name |
| `base_url = "nautobot-app-mcp-server"` | Confident | Matches Nautobot plugin naming convention |
| DESIGN.md uses `nautobot_mcp_server` throughout (wrong) | Confident | DESIGN.md § Architecture, § Critical Files table |
| `base_url = "mcp-server"` in __init__.py (inconsistent) | Confident | `nautobot_app_mcp_server/__init__.py` line 19 |

### Tool Registry
| Assumption | Confidence | Evidence |
|---|---|---|
| Thread-safe singleton with `threading.Lock` | Confident | Django multi-threaded workers; double-checked locking pattern |
| `ToolDefinition` dataclass with explicit scope field | Confident | DESIGN.md §2 registry; scope matching doesn't rely on name prefixes |
| `register_mcp_tool()` callable from third-party `ready()` hooks | Confident | `post_migrate` fires after all `ready()` hooks complete |

### Stack
| Assumption | Confidence | Evidence |
|---|---|---|
| `mcp ^1.26.0` (Anthropic) | Confident | Current stable; PyPI verified |
| `fastmcp ^3.2.0` (Prefect) | Confident | Current stable; PyPI verified; powers 70% of MCP servers |
| `asgiref ^3.11.1` | Confident | Ships with Django; explicit dep recommended |
| No `channels` or `uvicorn` for Option A | Confident | No separate worker; runs in Django process |

## Auto-Resolved

All assumptions were Confident based on research evidence. No user corrections needed.

## External Research

- **Nautobot plugin URL system:** `nautobot/extras/plugins/urls.py` → plugin_patterns auto-includes `plugin.urls.urlpatterns`
- **FastMCP ASGI structure:** `streamable_http_app()` returns Starlette ASGI callable
- **asgiref bridge:** `WsgiToAsgi` converts WSGI → ASGI
- **PyPI packages:** `mcp 1.26.0`, `fastmcp 3.2.0`, `asgiref 3.11.1`, `starlette 0.40.0/1.0.0`
- **`django-starlette`:** Does NOT exist on PyPI — confirmed
- **Nautobot Django version:** Django ~4.2.26 (supports ASGI)
- **DESIGN.md issues found:** `NotImplementedError` in Option A, wrong package name throughout

## Decisions Captured in CONTEXT.md

All 18 decisions (D-01 through D-18) documented in `01-CONTEXT.md`.

## Why No User Discussion Needed

Phase 1 is pure infrastructure — the decisions are technical and evidence-based:
- Stack versions verified via PyPI live lookups
- Architecture resolved via Nautobot source code analysis
- Package identity confirmed from actual files
- Pitfalls documented with quality gates

These are implementation mechanics, not product choices. Research + evidence = sufficient confidence.
