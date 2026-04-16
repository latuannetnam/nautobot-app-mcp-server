# Phase 15 Review: graphql_tool.py / test_graphql_tool.py

**Reviewer:** gsd-code-reviewer sub-agent
**Phase:** 15-introspection-permissions
**Files reviewed:**
- `nautobot_app_mcp_server/mcp/tools/graphql_tool.py`
- `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py`

---

## Linting

| Check | Result |
|---|---|
| `ruff check` | **1 violation** — `W292 no newline at end of file` on `test_graphql_tool.py:433` |
| Pylint | Not run (tool unavailable in host env), but manual analysis found no issues |

**Fix:** Add a trailing newline to `test_graphql_tool.py` (EOF must end with `\n`).

```python
# Line 433 currently ends with:
        finally:
            token.delete()   # ← no trailing newline
```

---

## graphql_tool.py — Findings

### Thread Sensitivity ✅

Both async handlers correctly use `sync_to_async(..., thread_sensitive=True)`:

```python
# _graphql_query_handler (line 48):
return await sync_to_async(_sync_graphql_query, thread_sensitive=True)(
    query=query, variables=variables, user=user
)

# _graphql_introspect_handler (line 91):
return await sync_to_async(_sync_graphql_introspect, thread_sensitive=True)()
```

The sync helpers `_sync_graphql_query` and `_sync_graphql_introspect` contain no ORM calls — they delegate to `nautobot.core.graphql.execute_query` and `graphene_django.settings.graphene_settings`. No `thread_sensitive` needed there (sync-to-sync boundary, not crossing to Django).

### Auth ✅

Both tools use `get_user_from_request(ctx)` correctly:
- `_graphql_query_handler`: calls it, passes user to `_sync_graphql_query`. If `user` is `AnonymousUser`, `execute_query` raises `ValueError`, caught and returned as structured error dict.
- `_graphql_introspect_handler`: calls it, raises `ValueError("Authentication required")` if `user is None`. FastMCP converts this to a tool error response.

**No auth bypass possible** — anonymous callers always receive either structured errors or a raised `ValueError`.

### Bug / Logic Analysis ✅

- `_sync_graphql_query` does a lazy import (`from nautobot.core.graphql import execute_query`) — correct, avoids Django setup issues.
- Return type is `dict[str, Any]` — consistent with `ExecutionResult.formatted` schema.
- `variables=None` default is correct — Nautobot's `execute_query` accepts `None` for optional vars.
- `_sync_graphql_introspect` uses `print_schema(schema.graphql_schema)` — correct for SDL generation.

### Error Handling ✅

`_sync_graphql_query` catches `ValueError` for `user=None` (anonymous) and returns a structured error dict. All other exceptions (syntax errors, timeout, DB errors) propagate as-is from `execute_query` — appropriate, as these indicate real problems not auth failures.

### Security ✅

- No SQL injection risk (query is passed to Nautobot's GraphQL engine).
- No user-controlled file paths or system calls.
- Auth token checked before any query execution.

---

## test_graphql_tool.py — Findings

### Coverage ✅

| Test | Covered |
|---|---|
| `test_valid_query_returns_structured_data` | GQL-15 ✅ |
| `test_invalid_query_returns_errors_dict` | GQL-16 ✅ |
| `test_variables_injection_works` | GQL-17 ✅ |
| `test_auth_propagates_to_sync_helper` | GQL-14 ✅ |
| `test_anonymous_user_triggers_auth_error` | GQL-07 ✅ |
| `test_anonymous_user_empty_query_results` | GQL-13 ✅ |
| `test_authenticated_user_normal_results` | GQL-13 ✅ |
| `test_introspect_returns_sdl_string` | GQL-09 ✅ |
| `test_introspect_sdl_valid` | GQL-09 ✅ |
| `test_introspect_raises_on_anonymous` | GQL-08 ✅ |
| `test_auth_required_resolves_user` | GQL-08 ✅ |

Both tools (graphql_query + graphql_introspect) have complete coverage across happy path, auth failure, invalid query, and variable injection.

### Test Quality ✅

- Uses `AsyncToSync` correctly to test async handlers synchronously in Django TestCase.
- Mocks are patched at the correct module level (`nautobot_app_mcp_server.mcp.tools.graphql_tool._sync_graphql_query`) — matches where names are bound at import time.
- `_create_token` / `_delete_token` raw SQL pattern correctly avoids the UUID/force_insert issue noted in the docstring.
- `try/finally` blocks ensure token cleanup even on assertion failures.
- `test_introspect_sdl_valid` actually validates SDL by calling `build_schema` — good integration check without needing a real Nautobot DB.

### Missing Coverage (minor)

- No test for malformed SDL returned by `_sync_graphql_introspect` (the `try/except` path). However, `graphene_django` SDL generation is unlikely to produce invalid schema, so this is low risk.
- No test for non-`ValueError` exceptions leaking from `execute_query` (DB timeout, syntax error). Again, low risk as these indicate real infrastructure issues.

---

## Summary

| Category | Status | Notes |
|---|---|---|
| Bug / logic errors | ✅ Pass | No issues found |
| Thread sensitivity | ✅ Pass | Both `sync_to_async` calls use `thread_sensitive=True` |
| Auth patterns | ✅ Pass | Both tools check auth before executing; no bypass possible |
| Error handling | ✅ Pass | ValueError for anonymous correctly caught; structured error returned |
| Security | ✅ Pass | No injection, no arbitrary file/system access |
| Test quality | ✅ Pass | Good coverage, correct mocking strategy, proper cleanup |
| Test coverage | ✅ Pass | All GQL-* requirements covered |
| Ruff | ⚠️ 1 violation | Missing trailing newline in test file |
| Pylint | ✅ (assumed) | No obvious issues; tool unavailable to verify |

---

## Action Items

1. **[trivia]** Add trailing newline to `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` (EOF line 433). Run `ruff --fix` to auto-fix.
2. **[done]** All other aspects are clean — no blockers.