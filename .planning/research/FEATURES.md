# Feature Research

**Domain:** Nautobot MCP Server — AI agent tooling for network infrastructure management
**Researched:** 2026-04-01
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **device_list** | Every network AI agent starts by inventorying devices | MEDIUM | Requires optimized queryset with `select_related`; `.restrict()` for permissions |
| **device_get** | Agents need full device context before taking action | MEDIUM | Must prefetch interfaces + relationships; single-object retrieval |
| **interface_list** | Network engineers interrogate interfaces constantly | MEDIUM | Must filter by `device_name`; N+1 risk without prefetch |
| **interface_get** | Interface-level details (VLANs, IPs, L2/L3 info) | MEDIUM | Prefetch `ip_addresses`, `tagged_vlans`, `untagged_vlan` |
| **ipaddress_list / ipaddress_get** | IP inventory is core Nautobot use case | MEDIUM | Must join VRF, tenant; complex filtering (address range, tenant, VRF) |
| **prefix_list** | Prefix space management is bread-and-butter IPAM | MEDIUM | Must join VRF, location, tenant; filter by `contains` prefix |
| **vlan_list** | VLAN inventory for L2 network planning | LOW | Must join site, group; relatively flat model |
| **location_list** | Physical/logical topology is foundational | LOW | Hierarchical (parent/child); natural tree structure |
| **search_by_name** | Agents discover objects without knowing model type | HIGH | Must query multiple models, rank by relevance; expensive if naive |
| **Token auth via Authorization header** | Nautobot's standard auth mechanism | LOW | Must extract `Token nbapikey_xxx`, attach `request.user` to context |
| **Object-level permissions enforcement** | Non-negotiable in enterprise; `Device.objects.restrict(user)` | MEDIUM | Every queryset must chain `.restrict()`; anonymous → empty results |
| **Cursor-based pagination** | Offset pagination breaks under concurrent writes | MEDIUM | base64-encoded PK cursor; `limit` capped at 1000; auto-summarize at 100+ |
| **MCP HTTP endpoint reachable** | Agents must be able to connect | MEDIUM | Must wire URL routing; ASGI mount vs. separate worker unresolved |
| **Meta tools (list/enable/disable)** | Agents must discover and manage tool scope | MEDIUM | `mcp_list_tools`, `mcp_enable_tools`, `mcp_disable_tools` — core tier always visible |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Progressive disclosure (Core + App tiers)** | Avoids tool explosion in Claude context window; differentiator vs. flat tool list | MEDIUM | Core (always visible) + per-app scopes (opt-in); session state controls visibility |
| **Third-party app tool registry (`register_mcp_tool()`)** | Turns Nautobot apps into MCP tool sources automatically; network effect | HIGH | Requires `post_migrate` signal (not `ready()`) to ensure ordering; public API contract |
| **Per-model named tools (not generic query tool)** | Claude gets concrete tool names — better intent matching than `query(model="Device", filter={...})` | LOW | Named tools are self-documenting; `device_list` vs `query(model="dcim/device")` |
| **Auto-summarize at 100+ results** | Prevents overwhelming agents with huge lists; forces deliberate navigation | LOW | Returns sample + total count + pagination hint; doesn't truncate arbitrarily |
| **Embedded in Django process** | Zero network hop vs. external MCP client; direct ORM access | MEDIUM | ASGI mount in Django is the key architectural decision (unresolved: Option A vs B) |
| **Optimized querysets per tool** | Prevents N+1 queries; essential for production performance | MEDIUM | `select_related`/`prefetch_related` chains per tool; must be tested with `assertNumQueries` |
| **SKILL.md package (separate pip)** | Independent versioning from the app; Claude Code can `skill add` it directly | LOW | Reference docs + workflow patterns; makes agents effective faster |
| **Per-scope exact matching** | `scope="netnam_cms_core.juniper.bgp"` activates only BGP tools; fine-grained | MEDIUM | Explicit `scope` field on `ToolDefinition`; avoids fragile prefix matching |
| **Anonymous returns empty (not error)** | Graceful degradation; agent can retry with auth rather than fail | LOW | Security: SEC-1 concern — prefer explicit 401 over silent empty in deployment |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Write tools (create/update/delete)** | Completeness — agents want to make changes | Write operations require transactional safety, rollback, Idempotency, and job queuing. Too many failure modes for v1. | Defer to v2; agents can use Nautobot REST API directly for writes |
| **Streaming SSE rows** | "Real-time" feels modern; avoids large payloads | SSE adds server complexity, connection management, and client complexity. Cursor pagination handles memory just fine. | Keep cursor pagination; SSE as future enhancement if genuinely needed |
| **Generic query tool** | Flexibility — one tool to rule them all | Claude intent matching is better with named tools. Generic routing makes the tool manifest opaque to the agent. | Named per-model tools + `search_by_name` for discovery |
| **Redis session backend (v1)** | Multi-worker production deployments | Adds ops complexity (Redis dependency, connection management). In-memory is fine for v1 validation. | Validate embedded + single-worker first; Redis as production swap-in |
| **MCP `resources` or `prompts` endpoints** | Full MCP spec compliance | Scope creep; focus is tools first. Resources/prompts are useful but not core to the value prop. | Tools only for v1; add later if genuine need emerges |
| **Field-level permissions** | Enterprise wants column-level access control | Nautobot doesn't have field-level permissions natively; would need custom implementation | Defer; Nautobot's object-level permissions are sufficient for v1 |
| **Tool-level rate limiting** | Prevent unbounded AI agent queries | Adds latency and complexity; Nautobot's own rate limiting can be used instead | Let Nautobot's existing infrastructure handle rate limits |
| **Real-time subscriptions (MCP sampling)** | Push model for network changes | Requires WebSocket/SSE infrastructure; far more complex than HTTP polling | Cursor pagination + periodic re-query is sufficient for AI agent use cases |
| **Separate MCP worker process (Option B)** | Simple deployment, no Django coupling | Introduces a second process to monitor, deploy, and scale. Redis required for cross-process state. Contradicts "embedded in Django" value prop. | Option A (ASGI mount) is the right architecture; resolve the implementation |
| **Global search with full-text ranking** | Users expect Google-like search | True full-text search requires PostgreSQL FTS config, index maintenance. Simple `name__icontains` is often sufficient for network device names. | `search_by_name` with `icontains` first; FTS as v1.x enhancement |

## Feature Dependencies

```
[MCP HTTP Endpoint] ──────────────> [Tool Registry]
        │                                  │
        │                                  ├──requires──> [post_migrate Signal Wiring]
        │                                                             │
[Auth Extraction] ──requires──> [Token from Authorization header] <──┘
                                                           │
[Core Tools (10)] ──enforce──> [Object-level .restrict(user)] ◄──┘
        │
        ├───[device_list / device_get] ──requires──> [Optimized Querysets]
        │                                               ├──select_related()
        │                                               └──prefetch_related()
        │
        ├───[All list tools] ──requires──> [Cursor Pagination]
        │                                    ├──base64 PK cursor
        │                                    └──auto-summarize at 100+
        │
        └───[search_by_name] ──requires──> [Multi-model Query Utility]
                                        ├──Device.objects.filter(...)
                                        ├──Prefix.objects.filter(...)
                                        └──Rank/merge results

[Progressive Disclosure] ──requires──> [MCPSessionState per Mcp-Session-Id]
        │                                      │
        │                                      └──stored in FastMCP SessionManager
        │
        ├──[mcp_enable_tools] ──modifies──> [MCPSessionState]
        ├──[mcp_disable_tools] ──modifies──> [MCPSessionState]
        └──[mcp_list_tools] ───queries────> [MCPSessionState]

[Third-Party App Registration] ──requires──> [register_mcp_tool() public API]
        │                                        │
        │                                        └──called in third-party ready()
        │                                            (after post_migrate fires)
        │
        └──[SKILL.md Package] ──documents──> [All tool names + workflows]
                                   (independent of registry — Claude can call any tool)

[Sync-to-Async Bridge] ──required by──> [All tool handlers]
        └──sync_to_async(thread_sensitive=True) ── Django ORM access from FastMCP async context
```

### Dependency Notes

- **MCP HTTP Endpoint requires Tool Registry:** The endpoint won't function without tools registered. Tool registration must fire before any MCP request is handled.
- **post_migrate Signal requires Tool Registry:** `post_migrate` is the mechanism to guarantee ordering — it fires after ALL `ready()` hooks, including third-party apps that call `register_mcp_tool()`.
- **Progressive Disclosure requires MCPSessionState:** The core value proposition of "10 always-visible + discoverable app tools" depends on per-session state tracked by `Mcp-Session-Id`.
- **Core Tools require Object-level .restrict():** Nautobot permissions are the primary security boundary. Every queryset must chain `.restrict(user, action="view")`. Anonymous users get empty results — no exception, no exposure.
- **Cursor Pagination requires base64 PK encoding:** Cursor must be stable across concurrent writes. Using `pk__gt` after `order_by("pk")` ensures this.
- **Auto-summarize requires count before slice:** The current DESIGN.md `paginate_queryset` has a bug — it counts after slicing. Must count before slice to trigger summarize correctly.
- **Optimized Querysets enhance all list tools:** Without `select_related`/`prefetch_related`, each tool will generate N+1 queries. This is the highest-risk performance gap.
- **Auth Extraction feeds all tool handlers:** `get_user_from_request()` must be called in every async tool handler and passed to the sync ORM function.
- **SKILL.md is independent of session state:** Claude can call any registered tool by name regardless of session state (Option C in DESIGN.md). The manifest controls Claude's awareness; the registry controls execution.
- **Option B (separate worker) conflicts with progressive disclosure:** Separate worker on port 9001 cannot share in-memory `MCPSessionState` with the Django process without Redis. This undermines the core value prop.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] **MCP HTTP endpoint (Option A: ASGI mount)** — core accessibility; the MCP server must be reachable at `/plugins/nautobot-mcp-server/mcp/`. If this doesn't work, nothing else matters.
- [ ] **10 Core read tools** (device_list, device_get, interface_list, interface_get, ipaddress_list, ipaddress_get, prefix_list, vlan_list, location_list, search_by_name) — validates that MCP-to-Nautobot-ORM bridge works; these are the primary user-facing value.
- [ ] **Token auth via Authorization header** — validates that Nautobot's permission system integrates with MCP tools. Anonymous → empty is acceptable for v1.
- [ ] **Cursor-based pagination** — validates memory-safe result handling; agents must be able to page through large inventories.
- [ ] **Object-level .restrict() on all querysets** — validates that Nautobot's permission model is the security boundary, not the MCP endpoint.

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] **MCPSessionState + progressive disclosure** — enable third-party app tools to be discovered and activated per session. Trigger: third-party app owners request MCP tool registration.
- [ ] **register_mcp_tool() public API** — publish the API contract; trigger: a real third-party Nautobot app wants to register tools.
- [ ] **post_migrate signal wiring** — guarantee ordering of tool registration across all apps. Trigger: need to support third-party tool registration.
- [ ] **3 Meta tools** (mcp_enable_tools, mcp_disable_tools, mcp_list_tools) — needed once progressive disclosure is active.
- [ ] **Optimized querysets with assertNumQueries tests** — trigger: performance testing reveals N+1 queries.
- [ ] **SKILL.md package** — trigger: agents need guidance on when to use which tool and workflow patterns.
- [ ] **Auto-summarize at 100+ results** — trigger: testing with realistic inventories (>100 devices).

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Write tools (create/update/delete)** — large surface area; requires transactional safety, idempotency, and job queuing. Only after read tools are validated.
- [ ] **Redis session backend** — necessary only if multi-worker production deployments are the target. Validate single-worker first.
- [ ] **MCP `resources` endpoint** — could expose Nautobot templates as MCP resources. Defer until tools-only approach is validated.
- [ ] **MCP `prompts` endpoint** — could expose common investigation workflows as MCP prompts. Defer unless natural demand emerges.
- [ ] **Streaming SSE for large result sets** — only if agents genuinely need real-time row streaming. Cursor pagination is sufficient for most cases.
- [ ] **Field-level permissions** — requires Nautobot-level support; not core to MCP server value.
- [ ] **Tool-level rate limiting** — Nautobot's existing infrastructure can handle this; not MCP server's job.
- [ ] **Option B (separate worker)** — only if Option A ASGI mount proves unworkable in practice. Not the preferred path.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| MCP HTTP endpoint reachable | **HIGH** | MEDIUM | **P1** |
| 10 Core read tools | **HIGH** | MEDIUM | **P1** |
| Token auth (Authorization header) | **HIGH** | LOW | **P1** |
| Object-level .restrict() on all querysets | **HIGH** | LOW | **P1** |
| Cursor-based pagination | **HIGH** | MEDIUM | **P1** |
| MCPSessionState + progressive disclosure | **MEDIUM** | MEDIUM | **P2** |
| register_mcp_tool() public API | **MEDIUM** | MEDIUM | **P2** |
| 3 Meta tools (enable/disable/list) | **MEDIUM** | LOW | **P2** |
| Optimized querysets (select_related/prefetch_related) | **MEDIUM** | MEDIUM | **P2** |
| SKILL.md package | **MEDIUM** | LOW | **P2** |
| post_migrate signal wiring | **MEDIUM** | MEDIUM | **P2** |
| Auto-summarize at 100+ results | **MEDIUM** | LOW | **P2** |
| Search_by_name multi-model query | **MEDIUM** | HIGH | **P2** |
| Write tools (create/update/delete) | **HIGH** | **HIGH** | **P3** |
| Redis session backend | **LOW** | MEDIUM | **P3** |
| MCP resources endpoint | **LOW** | MEDIUM | **P3** |
| MCP prompts endpoint | **LOW** | LOW | **P3** |
| Streaming SSE | **LOW** | MEDIUM | **P3** |
| Option B separate worker | **LOW** | HIGH | **P3** |
| Field-level permissions | **MEDIUM** | **HIGH** | **P3** |
| Tool-level rate limiting | **LOW** | MEDIUM | **P3** |

**Priority key:**
- **P1: Must have for launch** — without these, the product does not work at all
- **P2: Should have, add when possible** — validate core first, then expand
- **P3: Nice to have, future consideration** — defer until product-market fit established

## Competitor Feature Analysis

> *Note: There are no direct competitors providing an embedded MCP server for Nautobot as of April 2026. The competitive landscape consists of adjacent approaches: external MCP clients, Nautobot REST API directly, and generic network automation frameworks.*

| Feature | External MCP Client (Status quo) | Nautobot REST API Directly | Our Approach (Embedded MCP) |
|---------|-----------------------------------|----------------------------|-----------------------------|
| **Auth integration** | Manual token passing; no Nautobot session reuse | Token auth; no MCP-level session | Token extracted per-request; Nautobot permissions enforced |
| **Tool discovery** | Generic REST calls; no progressive disclosure | None — raw API surface | Progressive disclosure (Core + App tiers) |
| **Third-party app tools** | None — must call REST API manually | None | `register_mcp_tool()` API for app extensibility |
| **Performance** | Network hop to REST API; no ORM optimization | Network hop; standard Django ORM | Zero network hop; direct ORM with optimized querysets |
| **Permissions** | REST API permissions only | REST API permissions only | Nautobot object-level `.restrict()` enforced |
| **Pagination** | REST API page/offset | REST API page/offset | Cursor-based with auto-summarize at 100+ |
| **Session state** | None — stateless by default | N/A | MCPSessionState per Mcp-Session-Id |
| **Deployment** | Separate Python process; must manage lifecycle | N/A — uses existing Nautobot | Embedded in Django; no separate process |
| **SKILL.md guidance** | None | None | Separate pip package with tool reference + workflows |

### Key Differentiators vs. Alternatives

1. **vs. External MCP Client:** Our approach has zero network overhead, Nautobot permissions enforced at the ORM level, and progressive disclosure that external clients can't match without the same tool registry design.

2. **vs. REST API directly:** MCP tools provide named, discoverable interfaces that are far more agent-friendly than raw REST endpoints. The MCP protocol also handles pagination, auth headers, and session state natively.

3. **vs. Generic Network Automation (Ansible, Nornir):** These are agent-side tools. Our MCP server enables AI agents (Claude Code, Claude Desktop) to query network state — a fundamentally different use case than programmatic network control.

---

*Feature research for: nautobot-app-mcp-server v1*
*Researched: 2026-04-01*
*Confidence: HIGH — all conclusions drawn from DESIGN.md, PROJECT.md, CONCERNS.md; no external web research needed*
