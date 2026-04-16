---
status: issues
files_reviewed: 3
critical: 0
warning: 5
info: 4
total: 9
---

## Findings

### CRITICAL

_(None — no data corruption or unauthenticated execution paths found.)_

---

### WARNING

**W-1 [graphql_tool.py:63-73] `_sync_graphql_query` pollutes module-level namespace via test-only hack**

```python
import nautobot_app_mcp_server.mcp.tools.graphql_tool as _gt
_gt._graphql = _graphql_module
```

`graphql_tool.py` sets `_gt._graphql` at module level for test patching purposes, but `_graphql` is never read anywhere in the module. This dead write-only attribute is unnecessary and creates a risk: if any future code reads `_gt._graphql` assuming it is always set, it would fail in production (where `execute()` is always called directly). Remove the dead assignment entirely.

---

**W-2 [graphql_tool.py:97-98] `RequestFactory().post()` creates unauthenticated Django request — may cause ORM query failures**

```python
request = RequestFactory().post("/graphql/")
request.user = user
```

`RequestFactory().post()` produces a request object with no authentication attributes set (no session, no token). While `request.user = user` is assigned, downstream code in Nautobot's GraphQL execution path that accesses `request` may expect additional attributes (e.g., `request.META`, `request.id`, tenant-scoped headers). This is a latent compatibility issue. Consider documenting that only `request.user` is used, or wrapping in `force_authenticate()` if Nautobot's graphene middleware reads more than `request.user`.

---

**W-3 [graphql_tool.py:86-94] Security validation rules not enforced in Wave 1 scope — no-op stubs**

The docstring on `_sync_graphql_query` says Wave 1 security rules are "stubs", but `graphql_validation.py` contains fully implemented `MaxDepthRule` and `QueryComplexityRule`. The rules ARE being applied in Step 3. However, the constants `MAX_DEPTH = 8` and `MAX_COMPLEXITY = 1000` are hardcoded with no ability to configure them via environment variables. If these limits need tuning in production, the code requires a redeploy. Recommend documenting that these limits are not runtime-configurable.

---

**W-4 [graphql_validation.py:51-78] `MaxDepthRule._get_depth` re-counts shared subtrees — performance cliff with repeated fragments**

`_get_depth` re-traverses the entire fragment body on every `enter_field` call that reaches it. In a query with 100 fields each referencing the same fragment, the fragment is traversed 100 times. This is O(n × f) where n = field count and f = fragment size. Not a security vulnerability, but can cause a performance degradation under complex query shapes. Consider computing depth once per document (like `QueryComplexityRule.enter_document` does).

---

**W-5 [graphql_validation.py:51-78] Fragment cycle guard uses non-atomic `_visited_fragments` dict — theoretically racy in concurrent AST traversal**

`_visited_fragments` is a shared mutable dict mutated inside `_get_depth`. If two AST traversal paths entered `enter_field` concurrently (not possible today as graphql-core traverses sequentially, but fragile if traversal ever becomes parallel), the `finally` block's `del` could race with the initial insert. More importantly, the guard is at the wrong level: a fragment is only skipped if it was visited in the **current `_get_depth` call chain** — but once a fragment is entered, it marks itself visited and then deletes on `finally`. This works correctly for sequential traversal but would produce wrong results if traversal order changed. Since graphql-core is sequential today, this is **informational only**, but worth a comment documenting the sequential assumption.

---

### INFO

**I-1 [graphql_tool.py:70] Unused import alias — `_gt` is never read**

The line `import nautobot_app_mcp_server.mcp.tools.graphql_tool as _gt` is imported solely to set `_gt._graphql = _graphql_module`, and `_gt._graphql` is never read in the module. See W-1. This is dead code.

---

**I-2 [graphql_validation.py:21] `_INTROSPECTION_FIELDS` excludes `__typename` from depth but NOT from complexity — intentional but not documented**

`MaxDepthRule.enter_field` skips `__typename` from depth counting, but `_count_complexity` includes it. This is likely intentional (depth limit concerns nesting, `__typename` adds no nesting), but there is no comment explaining why. A one-line comment would prevent future confusion.

---

**I-3 [graphql_validation.py:111] `FragmentSpreadNode` counted as 1 in `_count_complexity` — over-counts relative to field weight**

`FragmentSpreadNode` contributes 1 to complexity, but the fragment it references could expand to 0 fields (empty fragment) or 100. Counting only the spread node underestimates the true cost of expanding that fragment. The same applies to `InlineFragmentNode` which recurses. This is a known limitation of the "simple field-count heuristic" mentioned in the docstring, but it's worth noting that a complex query with many empty fragments would pass the complexity check while still being expensive.

---

**I-4 [test_graphql_tool.py:63-65] Hardcoded plaintext password `"testpass"` in test fixtures — acceptable in test code but flagged**

`User.objects.create_superuser(... password="testpass")` appears in 6 test methods. While this is test-only code and acceptable practice, it should use a constant or be pulled from `settings.SECRET_KEY` / `django.utils.crypto.get_random_string` to avoid accidental inclusion in screenshots or logs. No security action required — informational only.

---

## Per-File Summary

| File | Issues |
|---|---|
| `graphql_tool.py` | W-1, W-2, W-3, I-1 |
| `graphql_validation.py` | W-4, W-5, I-2, I-3 |
| `test_graphql_tool.py` | I-4 |

## Recommendations

1. **Remove dead `_gt._graphql` assignment** (`graphql_tool.py:73`) — it is never read.
2. **Audit `request = RequestFactory().post()`** usage against Nautobot's graphene middleware to confirm no missing request attributes are accessed.
3. **Document that `MAX_DEPTH` and `MAX_COMPLEXITY` are not runtime-configurable** — add a comment or consider env-var support in a future phase.
4. **Add sequential-traversal assumption comment** to `MaxDepthRule._visited_fragments` guard.
5. **Add docstring note** explaining why `__typename` is excluded from depth but included in complexity.