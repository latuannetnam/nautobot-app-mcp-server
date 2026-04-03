# Phase 5: MCP Server Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 05-mcp-server-refactor
**Mode:** discuss
**Areas discussed:** ASGI scope builder, Session manager architecture, Integration test design

---

## ASGI Scope Builder

### Q1: Server address and scheme
| Option | Description | Selected |
|--------|-------------|----------|
| request.get_host()/get_port() directly | Simple, no proxy headers trusted | ✓ |
| Trust X-Forwarded-Host/Port | Respect proxy headers behind nginx | |
| Always hardcoded ("127.0.0.1", 8080) | Current broken approach | |

**User's choice:** `request.get_host()/get_port()` directly
**Notes:** Works for direct Docker connections. Proxy handling deferred to production infra.

### Q2: Client IP field
| Option | Description | Selected |
|--------|-------------|----------|
| request.META REMOTE_ADDR | Direct WSGI environ; proxy: trust X-Forwarded-For separately | ✓ |
| Trust X-Forwarded-For (first hop) | Respect X-Forwarded-For | |
| Omit client field | Leave empty | |

**User's choice:** `request.META REMOTE_ADDR`
**Notes:** Simple approach. Proxy handling deferred.

---

## Session Manager Architecture

### Q1: How to expose get_session_manager()
| Option | Description | Selected |
|--------|-------------|----------|
| Separate get_session_manager() singleton | Two singletons, clean separation | ✓ |
| Return both from get_mcp_app() as tuple | Single factory, coupled | |
| Property on FastMCP instance | Fragile private API | |

**User's choice:** Separate `get_session_manager()` function
**Notes:** Clean separation of concerns. `view.py` calls both functions.

### Q2: Double-checked locking
| Option | Description | Selected |
|--------|-------------|----------|
| Separate locks per singleton | One lock per _mcp_app, one per _session_mgr | ✓ |
| Single lock guarding both | One lock for both initializations | |

**User's choice:** Separate locks per singleton
**Notes:** Independent initialization. More verbose but correct.

---

## Integration Test Design

### Q1: Session persistence test approach
| Option | Description | Selected |
|--------|-------------|----------|
| Real StreamableHTTPSessionManager | Actual FastMCP session, no mocks | ✓ |
| Django test client + real server | Django client against live server | |
| Fast unit tests only | Assertions on async_to_sync call signature | |

**User's choice:** Real `StreamableHTTPSessionManager`
**Notes:** End-to-end verification that scope enabled in req1 is visible in req2's `mcp_list_tools`.

---

## No Corrections

All assumptions confirmed by user selection.

---

*Discussion mode: discuss*
