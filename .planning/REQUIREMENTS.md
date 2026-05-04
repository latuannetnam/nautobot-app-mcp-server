# Requirements — Milestone v2.1 GraphQL-Only Mode

## Active Requirements

### GraphQL-Only Mode

- [ ] **GQLONLY-01**: Operator can set `NAUTOBOT_MCP_GRAPHQL_ONLY=true` env var and the MCP server starts in GraphQL-only mode
- [ ] **GQLONLY-02**: In GraphQL-only mode, the MCP tool list returns exactly `graphql_query` and `graphql_introspect` — no other tools visible
- [ ] **GQLONLY-03**: In GraphQL-only mode, calls to any non-GraphQL tool are blocked with a clear error
- [ ] **GQLONLY-04**: Without the env var (default), server behavior is identical to v2.0 — all 15 tools visible
- [ ] **GQLONLY-05**: Unit tests cover: GraphQL-only filtering in `_list_tools_handler`, call-time enforcement in `ScopeGuardMiddleware`, and default-off behavior
- [ ] **GQLONLY-06**: `NAUTOBOT_MCP_GRAPHQL_ONLY` is documented in CLAUDE.md and SKILL.md

## Future Requirements

- Write tools (create/update/delete) — deferred to v3.0
- Redis session backend for `--workers > 1` — deferred to v3.0

## Out of Scope

- Per-user or per-session GraphQL-only mode (this is a server-startup flag, not a session feature)
- Additional tool allowlist configurations beyond "graphql-only" (YAGNI — generalize if needed in v3.0)
- Combining GraphQL-only mode with progressive disclosure scopes in the same session

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| GQLONLY-01 | Phase 18 | Pending |
| GQLONLY-02 | Phase 18 | Pending |
| GQLONLY-03 | Phase 18 | Pending |
| GQLONLY-04 | Phase 18 | Pending |
| GQLONLY-05 | Phase 18 | Pending |
| GQLONLY-06 | Phase 18 | Pending |
