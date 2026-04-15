---
status: clean
files_reviewed: 3
phase: 14
phase_name: graphql-tool-scaffold
depth: standard
critical: 0
warning: 0
info: 3
total: 3
---

# 14-REVIEW.md — GraphQL Tool Scaffold

**Phase:** 14-graphql-tool-scaffold
**Files reviewed:**
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py`
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py`
- `nautobot_app_mcp_server/mcp/tools/__init__.py`

---

## Implementation Summary

### `graphql_tool.py`

- Single tool: `graphql_query`, tier=`core`, scope=`core`.
- Async handler `_graphql_query_handler` calls `get_user_from_request(ctx)` then dispatches to sync helper via `sync_to_async(..., thread_sensitive=True)` — correct.
- `_sync_graphql_query` does a lazy import of `nautobot.core.graphql.execute_query`, calls it, and catches `ValueError` (raised when `user` is `None`) to return a structured error dict `{"data": None, "errors": [{"message": "Authentication required"}]}`. Falls through to `result.formatted` otherwise.
- Tool description is reasonable; parameters (`query`, `variables`) are cleanly typed.

### `__init__.py`

- Side-effect import `from nautobot_app_mcp_server.mcp.tools import graphql_tool` present and ordered correctly after `core`.
- `__all__` contains only pagination exports — `graphql_tool` is intentionally absent since it is a side-effect registration only (consistent with `core` pattern).

### `test_graphql_tool.py`

- **5 test cases** covering: valid query (GQL-15), invalid query error dict (GQL-16), variables injection (GQL-17), auth propagation (GQL-14), and anonymous user auth error (GQL-07).
- Token creation uses raw SQL `INSERT` to avoid UUID field issues with `force_insert` — correct pattern per repo gotchas.
- Mocks patch at `nautobot_app_mcp_server.mcp.tools.graphql_tool.*` module level (where names are bound at import time) — standard approach. For the anonymous-user test, the lazy import forces patching at `nautobot.core.graphql.execute_query` instead — explained in comment.
- `call_args` inspection used for kwarg verification — clean.
- All tests have `finally: token.delete()` to clean up raw-SQL-created tokens.

---

## Observations

### Strengths

1. **Thread-safety correct:** `sync_to_async(..., thread_sensitive=True)` used throughout — no "Connection not available" risk.
2. **Lazy import pattern** for `nautobot.core.graphql` avoids Django setup issues in the standalone FastMCP process.
3. **Graceful auth error handling:** `ValueError` caught and returned as a structured dict rather than propagating — callers always get a predictable shape.
4. **`result.formatted` used correctly:** matches the `ExecutionResult.formatted` structure the tests assert on (`{"data": ..., "errors": ...}`).
5. **Test isolation:** raw SQL token create/delete keeps tests independent of ORM token model quirks.
6. **Type annotations:** `dict[str, Any]` return type on sync helper; `query: str`, `variables: dict | None` on handler.

### Minor points

1. **`TYPE_CHECKING` block is empty** (`if TYPE_CHECKING: pass`) — harmless but unusual. No types are imported under `TYPE_CHECKING`, so this block does nothing.
2. **`variables: dict | None` — `dict` is unparameterized.** Could be `dict[str, Any] | None` for slightly better specificity, but this matches the style of other tools in the repo.
3. **Docstring return description is accurate** and matches what the function actually returns.
4. **Tool description says "auth token is required"** but the implementation silently returns empty data for anonymous users rather than enforcing token presence — this is intentional per the description ("anonymous queries return empty data"), and the tests confirm it. The behavior matches Nautobot's own `execute_query` semantics.

---

## Alignment with Repo Standards

| Standard | Status |
|---|---|
| `sync_to_async(..., thread_sensitive=True)` for all ORM calls | ✅ |
| Pylint 10.00 target (no `noqa` flags needed) | ✅ Looks clean |
| Line length 120 | ✅ |
| Google-style docstrings, D401 ignored | ✅ |
| `from __future__ import annotations` | ✅ |
| `@register_tool` decorator (module-level, side-effect import in `__init__`) | ✅ |
| Tier/scope pattern (`TOOLS_TIER = "core"`, `TOOLS_SCOPE = "core"`) | ✅ |
| Tool registered via `register_tool` in `__init__.py` side-effect | ✅ |

---

## Conclusion

Solid scaffold. Implementation is idiomatic, thread-safe, and consistent with existing tool patterns. Tests are thorough and cover the four primary code paths (valid, invalid, variables, auth). No issues requiring changes before merging.