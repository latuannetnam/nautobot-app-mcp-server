# Phase 17: UAT & Documentation — Research

**Phase:** 17-uat-and-documentation
**Goal:** Add smoke test P-09, UAT suite T-37–T-43, and update SKILL.md
**Requirements:** GQL-18 (P-09), GQL-19 (T-37–T-43), GQL-20 (SKILL.md)
**Status:** Research — 2026-04-16

---

## 1. Implementation State

Both GraphQL tools are **already implemented** and unit-tested:

| File | Status |
|------|--------|
| `nautobot_app_mcp_server/mcp/tools/graphql_tool.py` | ✅ Fully implemented |
| `nautobot_app_mcp_server/mcp/tools/graphql_validation.py` | ✅ Fully implemented |
| `nautobot_app_mcp_server/mcp/tests/test_graphql_tool.py` | ✅ 15 unit tests (GQL-14 to GQL-17, GQL-10 to GQL-12) |

This phase adds only UAT/integration tests and documentation.

---

## 2. `graphql_query` Tool — Key Facts

### Function signature
```python
@register_tool(name="graphql_query", ...)
async def _graphql_query_handler(
    ctx: ToolContext,
    query: str,
    variables: dict | None = None,
) -> dict[str, Any]
```

### Return shape
Always returns `dict` with two keys:
```python
{"data": {...} | None, "errors": [...] | None}
```
- On success: `{"data": {"devices": [...], "errors": None}`
- On auth failure (anonymous): `{"data": None, "errors": [{"message": "Authentication required"}]}`
- On GraphQL error: `{"data": None, "errors": [{"message": "Field 'x' does not exist..."}]}`
- On syntax error: `{"data": None, "errors": [{"message": "Syntax Error: ..."}]}`
- **Never raises `MCPToolError`** — errors are always in the dict

### `_sync_graphql_query` — 4-phase pipeline
1. Auth guard (user=None or AnonymousUser → auth error dict)
2. `graphql_validation.parse(query)` → raises `GraphQLError` on bad syntax → returns errors dict
3. `graphql_validation.validate(schema, document, rules=[MaxDepthRule, QueryComplexityRule, ...])` → returns validation errors
4. `graphql.execute(schema, document, context_value=request, variable_values=variables)` → returns `ExecutionResult.formatted`

### Depth and complexity limits
- `MAX_DEPTH = 8` — nested fields deeper than 8 return `{"data": None, "errors": [{"message": "Query depth N exceeds..."}]}`
- `MAX_COMPLEXITY = 1000` — queries with >1000 fields return `{"data": None, "errors": [{"message": "Query complexity N exceeds..."}]}`
- Both return **structured error dicts** (HTTP 200), not HTTP 500

### Variables parameter
- `variables: dict | None` passed directly to `graphql.execute(variable_values=variables)`
- Works with GraphQL `query($var: Type!) { ... }` syntax

---

## 3. `graphql_introspect` Tool — Key Facts

### Function signature
```python
@register_tool(name="graphql_introspect", ...)
async def _graphql_introspect_handler(ctx: ToolContext) -> str
```

### Return shape
- On success: multi-line GraphQL SDL string (e.g., `"type Query {\n  devices: [Device]!\n  ...\n}"`)
- On auth failure: raises `ValueError("Authentication required")` → FastMCP returns `MCPToolError` (code -32602)

### SDL content
Returns the output of `graphql.print_schema(schema.graphql_schema)` from `graphene_django.settings.SCHEMA.graphql_schema`. Always contains:
- `type Query { ... }`
- `type Mutation { ... }` (if mutations are defined)
- `schema { ... }` directive
- `input ...` types for filter/creation inputs

---

## 4. P-09 Smoke Test Design

**File:** `scripts/test_mcp_simple.py`
**Pattern:** Single assertion, timed, passes/fails cleanly (same as P-01–P-08)

### What to test
Call `graphql_query` with a valid Nautobot GraphQL query and verify:
1. Response is a `dict` (not string, not exception)
2. `"data"` key is present and not `None`
3. `"errors"` key is present (may be `None` or `[]`)
4. Result returned within 5s

### Suitable Nautobot GraphQL query
```python
result = client.call_tool("graphql_query", {
    "query": "{ devices(first: 5) { name status } }"
})
# Or using variables:
result = client.call_tool("graphql_query", {
    "query": "query($limit: Int!) { devices(first: $limit) { name } }",
    "variables": {"limit": 5}
})
```

### Key insight: `MCPToolError` vs dict error
`graphql_query` **never raises `MCPToolError`** — errors are always returned in the dict. So the smoke test:
```python
result = client.call_tool("graphql_query", {"query": "{ devices(first: 5) { name } }"})
assert "data" in result
assert result["data"] is not None  # Authenticated superuser → non-empty data
assert "errors" in result
```
Do NOT use `try/except MCPToolError` as a failure signal — that's only for `graphql_introspect`.

### Placement
Add after the existing P-08 block (line ~170 in `test_mcp_simple.py`), after the `device_get` section and before the final `print()`.

---

## 5. T-37–T-43 UAT Design

**File:** `scripts/run_mcp_uat.py`
**Category:** `"GraphQL Tools": ["T-37", "T-38", "T-39", "T-40", "T-41", "T-42", "T-43"]`
**Placement:** New section `### 4. GraphQL Tools` before the `summary()` block

### T-37: Valid query returns data with no errors
```python
def t37():
    result = client.call_tool("graphql_query", {
        "query": "{ devices(first: 5) { name status } }"
    })
    assert "data" in result, "Result must have 'data' key"
    assert "errors" in result, "Result must have 'errors' key"
    # Success: data is not None, errors is None or []
    assert result["data"] is not None, f"Expected data, got: {result}"
    return result
```
**Assertions:** `data` not None, `errors` is None/empty

### T-38: Syntax error returns structured errors (no HTTP 500)
```python
def t38():
    result = client.call_tool("graphql_query", {
        "query": "{ devices {"  # unclosed brace — syntax error
    })
    assert "data" in result
    assert "errors" in result
    assert result["data"] is None, "Syntax error → data must be None"
    assert result["errors"] is not None and len(result["errors"]) > 0
    assert "Syntax Error" in result["errors"][0]["message"]
    return {"syntax_error_handled": True}
```
**Assertions:** `data` is None, `errors` populated, "Syntax Error" in message
**Note:** No `MCPToolError` raised — syntax error is a structured dict response

### T-39: Introspection returns valid SDL schema
```python
def t39():
    sdl = client.call_tool("graphql_introspect", {})
    assert isinstance(sdl, str), "Introspect must return string"
    assert len(sdl) > 50, "SDL should be > 50 chars"
    assert "type Query" in sdl, "SDL must contain 'type Query'"
    return {"sdl_length": len(sdl)}
```
**Assertions:** Returns `str`, contains `type Query`, non-empty

### T-40: Permission enforcement — anonymous token
```python
def t40():
    # Anonymous client (no/invalid token) → auth error dict or empty data
    anon = MCPClient(MCP_ENDPOINT, "nbapikey_invalid_token_00000000000000")
    result = anon.call_tool("graphql_query", {
        "query": "{ devices { name } }"
    })
    # graphql_query returns a dict, not an exception
    # Auth failure: {"data": None, "errors": [{"message": "Authentication required"}]}
    assert "data" in result
    assert "errors" in result
    # Either data is None with auth error, or data is empty dict
    if result["data"] is None:
        assert any("Authentication" in str(e) for e in (result["errors"] or []))
    return {"anonymous_restricted": True}
```
**Key difference from T-27:** `graphql_query` returns a dict with `{"data": None, "errors": [...]}` for anonymous — NOT an empty `items: []` list like `device_list`. The error message contains "Authentication".
**Assertions:** `data` is None, auth error in `errors`

### T-41: Query variables injection
```python
def t41():
    result = client.call_tool("graphql_query", {
        "query": "query GetDevices($limit: Int!) { devices(first: $limit) { name } }",
        "variables": {"limit": 3}
    })
    assert "data" in result
    assert result["data"] is not None, f"Variables query failed: {result}"
    # If data is {"devices": [...]} check count
    return {"variables_working": True}
```
**Assertions:** `data` not None, variables dict forwarded correctly

### T-42: Valid token → full data access
```python
def t42():
    result = client.call_tool("graphql_query", {
        "query": "{ devices(first: 3) { name status } }"
    })
    assert "data" in result
    assert result["data"] is not None
    return {"token_authorized": True}
```
**Assertions:** `data` not None (authenticated user, not anonymous)

### T-43: Depth/complexity limit enforcement
```python
def t43():
    # Depth > 8 → structured error dict
    deep_query = "{ a { b { c { d { e { f { g { h { i } } } } } } } } }"  # depth 9
    result = client.call_tool("graphql_query", {"query": deep_query})
    assert "data" in result
    assert result["data"] is None
    assert result["errors"] is not None
    assert any("depth" in str(e).lower() for e in result["errors"])

    # Complexity > 1000 → structured error dict
    many_fields = ", ".join(f"field{i}: name" for i in range(1001))
    complex_query = f"{{ {many_fields} }}"
    result2 = client.call_tool("graphql_query", {"query": complex_query})
    assert result2["data"] is None
    assert result2["errors"] is not None
    assert any("complexity" in str(e).lower() for e in result2["errors"])

    return {"depth_and_complexity_limits_enforced": True}
```
**Assertions:** Both depth and complexity limits return `data=None` with structured errors
**Note:** Two separate queries in one test — depth and complexity are tested together

---

## 6. Auth Test Pattern Comparison

| Test | Tool | Anonymous behavior | Error signal |
|------|------|--------------------|--------------|
| T-27 | `device_list` | Returns `{"items": []}` | No exception — empty list |
| T-40 | `graphql_query` | Returns `{"data": None, "errors": [{"message": "Authentication required"}]}` | No exception — error dict |
| T-39 (auth) | `graphql_introspect` | Raises `MCPToolError(code=-32602)` | Exception raised |

**Key distinction:** `graphql_query` uses dict-based error response (same as GraphQL spec). `graphql_introspect` uses exception-based error (same as other MCP tools).

This means T-40 looks different from T-27 in assertion style:
- T-27: `assert result.get("items") == []`
- T-40: `assert result["data"] is None` and `assert "Authentication" in result["errors"][0]["message"]`

---

## 7. SKILL.md Update Design

**File:** `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md`

### Placement
Add a new `## GraphQL Tools` section between `## Core Tools` and `## Meta Tools` (after the Core Tools table, line ~52). This groups all GraphQL tooling together.

### New section content

```markdown
## GraphQL Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| graphql_query | Execute an arbitrary GraphQL query against Nautobot's GraphQL API. Returns a dict with `data` and `errors` keys. Both keys are always present; `data` may be `None` on error. | `query: str`, `variables?: dict` |
| graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. Use to discover available types and fields. Requires auth. | (none) |

### graphql_query

Execute arbitrary GraphQL queries against Nautobot's graphene-django schema. Auth token is required.

**Parameters:**
- `query: str` — GraphQL query string (required)
- `variables: dict | None` — Optional variables for parameterized queries (default: `None`)

**Result shape:**
```json
{
  "data": { ... } | null,
  "errors": [ { "message": "...", "locations": [...], "path": [...] } ] | null
}
```

**Error cases:** Returns structured errors in the `errors` array. Common error messages:
- `"Authentication required"` — invalid or missing token
- `"Query depth N exceeds maximum allowed depth of 8"` — query too deeply nested
- `"Query complexity N exceeds maximum allowed complexity of 1000"` — query too many fields
- `"Syntax Error: ..."` — malformed GraphQL syntax

**Example queries:**

```graphql
# Simple device listing
query {
  devices(first: 10) {
    name
    status
  }
}
```

```graphql
# With variables
query GetDevices($limit: Int!) {
  devices(first: $limit) {
    name
    status
    platform {
      name
    }
    location {
      name
    }
  }
}
```
Variables: `{"limit": 5}`

### graphql_introspect

Returns the full Nautobot GraphQL schema as a GraphQL SDL string. Use this to discover available object types, fields, and relationships before writing queries.

**Returns:** Multi-line SDL string (e.g., `"type Query {\n  devices: [Device]!\n  ...\n}"`)

**Example:**
```python
sdl = mcp.call_tool("graphql_introspect", {})
# "schema {\n  query: Query\n}\ntype Query {\n  devices(first: Int): [Device]\n  ..."
```
```

---

### Update to `## Core Tools` table

Add `graphql_query` and `graphql_introspect` to the table (they are tier="core" so they belong there alongside `device_list`, etc.):

```markdown
| graphql_query | Execute an arbitrary GraphQL query against Nautobot's GraphQL API. Returns {data, errors}. | `query: str`, `variables?: dict` | No |
| graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. | (none) | No |
```

### What NOT to add
- Do NOT add a "GraphQL Workflow" in the Investigation Workflows section — the existing workflows cover the primary use case. If needed, add a brief note under Limitations.

---

## 8. Test Organization Summary

### P-09 (smoke) — `scripts/test_mcp_simple.py`
- Location: After the `device_get` block, before `print("All smoke tests PASSED")`
- Single `client.call_tool("graphql_query", {"query": "{ devices(first: 5) { name } }"})`
- Assertion: `result["data"] is not None and result["errors"] is not None`

### T-37–T-43 (UAT) — `scripts/run_mcp_uat.py`
- Location: New section `### 4. GraphQL Tools` after section `2e` (Auth Enforcement T-27 to T-29)
- Follow same `runner.test("T-NN ...", tNN)` pattern as existing tests
- Add `"GraphQL Tools"` to the `categories` dict in `summary()`

---

## 9. Key Pitfalls and Decisions

### Pitfall 1: `MCPToolError` vs dict errors
`graphql_query` never raises `MCPToolError` — errors are always in the returned dict. Tests that expect `MCPToolError` for `graphql_query` errors will fail. Use:
```python
result = client.call_tool("graphql_query", {"query": "..."})
assert result["data"] is None
assert result["errors"] is not None
```
NOT:
```python
try:
    client.call_tool("graphql_query", {"query": "..."})
    raise AssertionError("Expected error")
except MCPToolError:  # WRONG for graphql_query
    pass
```

### Pitfall 2: Anonymous behavior differs between tools
- `device_list` (T-27): returns `{"items": []}` — empty list, no error key
- `graphql_query` (T-40): returns `{"data": None, "errors": [{"message": "Authentication required"}]}`
- `graphql_introspect` (T-39 auth): raises `MCPToolError(-32602)`

Test each tool's anonymous behavior separately with appropriate assertions.

### Pitfall 3: `variables` parameter is optional but must be handled
`graphql_query` accepts `variables: dict | None = None`. When calling from MCP client:
```python
# With variables
result = client.call_tool("graphql_query", {
    "query": "query($limit: Int!) { devices(first: $limit) { name } }",
    "variables": {"limit": 3}
})
# Without variables (None default)
result = client.call_tool("graphql_query", {
    "query": "{ devices { name } }"
})
```
Both work — variables dict can be absent or `null`.

### Pitfall 4: Depth limit query must be syntactically valid
A depth-9 query like `{ a { b { c { d { e { f { g { h { i } } } } } } } } }` must be **syntactically valid GraphQL** (all braces closed) so it passes `parse()` and fails at the `validate()` step with a depth error. A syntax error would fail at `parse()` instead, which is the T-38 case.

### Pitfall 5: Complexity query must be syntactically valid
The `many_fields` query `{ field0: name, field1: name, ..., field1000: name }` must be valid GraphQL — each `fieldN: name` is a valid field selection. This passes `parse()` and fails at `validate()` with a complexity error.

### Decision: P-09 tests one assertion or two?
P-01–P-08 each have one main assertion. For P-09, follow the same pattern:
- Main assertion: `result["data"] is not None` (authenticated → data returned)
- Secondary check: `result["errors"] is not None` (errors key present)

### Decision: T-43 tests depth OR complexity OR both?
Test both in one function (T-43) using sequential queries. This is efficient and tests both GQL-10 and GQL-11 in one UAT case. If either fails, the test fails — which is correct behavior.

---

## 10. Verification Gates

### P-09 smoke test
```bash
python scripts/test_mcp_simple.py
# Exit code 0 → P-09 passed
```

### T-37–T-43 full suite
```bash
python scripts/run_mcp_uat.py
# Exit code 0 → all tests passed; "GraphQL Tools: 7/7" in summary
```

### SKILL.md validation
```bash
# Check section exists and is well-formed
grep -c "graphql_query" nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md  # ≥ 4 occurrences
grep -c "graphql_introspect" ...  # ≥ 3 occurrences
```

### Full gate
```bash
poetry run invoke tests
# All linters + unit tests + UAT must pass
```

---

## 11. File Summary

| File | Change |
|------|--------|
| `scripts/test_mcp_simple.py` | Add P-09 smoke test (8–12 lines) |
| `scripts/run_mcp_uat.py` | Add `### 4. GraphQL Tools` section with T-37–T-43 (60–80 lines) |
| `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` | Add `## GraphQL Tools` section + update Core Tools table (~40 lines) |

---

## 12. Open Questions (Resolved)

| Question | Resolution |
|----------|-----------|
| Does `graphql_query` raise `MCPToolError` on errors? | No — always returns dict with `data` and `errors` keys |
| What does anonymous get from `graphql_query`? | `{"data": None, "errors": [{"message": "Authentication required"}]}` |
| Does `graphql_introspect` raise on no auth? | Yes — `ValueError("Authentication required")` → `MCPToolError(-32602)` |
| Is T-43 one test or two? | One test — tests both depth and complexity limits sequentially |
| What query is syntactically valid but depth>8? | `{ a { b { c { d { e { f { g { h { i } } } } } } } } }` (9 levels) |
| What query is syntactically valid but complexity>1000? | `{ field0: name, field1: name, ..., field1000: name }` (1001 fields) |

---

*Research: 17-uat-and-documentation*
*GQL-18, GQL-19, GQL-20*