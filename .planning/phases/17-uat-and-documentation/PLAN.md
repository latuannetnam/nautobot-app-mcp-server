# Phase 17 Plan — UAT & Documentation

**Phase:** 17-uat-and-documentation
**Goal:** Add smoke test P-09, full UAT suite T-37–T-43, and update SKILL.md with `graphql_query` and `graphql_introspect` documentation.
**Requirements:** GQL-18, GQL-19, GQL-20
**Plans:** 4 (`17.1`, `17.2`, `17.3`, `17.4`)
**Waves:** 2 (Wave 1: `17.1`, `17.2`, `17.3` → Wave 2: `17.4`)
**Status:** Ready for implementation

---

## must_haves (derived from phase goal)

- P-09 smoke test in `scripts/test_mcp_simple.py` — valid GraphQL query returns data
- T-37–T-43 UAT suite in `scripts/run_mcp_uat.py` — all 7 tests pass
- SKILL.md updated — both tool signatures present, ≥ 2 example queries
- `invoke tests` exits with code 0 end-to-end

---

## Wave 1 — Tests & Docs (can run in parallel)

| Plan | Description | Requirement |
|------|-------------|-------------|
| 17.1 | Add P-09 smoke test to `test_mcp_simple.py` | GQL-18 |
| 17.2 | Add T-37–T-43 UAT suite to `run_mcp_uat.py` | GQL-19 |
| 17.3 | Update SKILL.md with GraphQL tools documentation | GQL-20 |

## Wave 2 — Gate

| Plan | Description | Requirement |
|------|-------------|-------------|
| 17.4 | Run `invoke tests` full pipeline | GQL-18, GQL-19, GQL-20 |

---

## Plan 17.1 — Add Smoke Test P-09

```yaml
wave: 1
depends_on: []
requirements:
  - GQL-18
files_modified:
  - scripts/test_mcp_simple.py
```

### Objective

Add P-09 to `scripts/test_mcp_simple.py` — a single smoke test that calls `graphql_query` with a valid Nautobot GraphQL query and verifies data is returned. Follows the same single-assertion, timed, clean-pass/fail pattern as P-01–P-08.

### Tasks

```yaml
- id: 17.1-T01
  read_first:
    - scripts/test_mcp_simple.py  # existing P-01–P-08 patterns; MCPClient class; line ~170 insertion point
  action: >
    In `scripts/test_mcp_simple.py`, after the P-08 block (after `device_get` step 4, before
    `print("All smoke tests PASSED")`), add:

    ```python
        # 5. Call graphql_query
        print("5. Call graphql_query...")
        result = client.call_tool("graphql_query", {
            "query": "{ devices(first: 5) { name status } }"
        })
        assert "data" in result, "graphql_query result must have 'data' key"
        assert result["data"] is not None, f"Expected data, got: {result}"
        assert "errors" in result, "graphql_query result must have 'errors' key"
        print(f"   Returned data (errors={result.get('errors')})")
        print("   OK")
    ```

    The assertion `result["data"] is not None` is the primary check (authenticated superuser
    always gets data). `result["errors"]` is verified to be present but may be `None` or `[]`.
  acceptance_criteria: >
    - P-09 block added after the `device_get` block, before `print("All smoke tests PASSED")`
    - Only one primary assertion: `result["data"] is not None`
    - `result["errors"]` presence checked but value is not asserted (may be None/[])
    - No `try/except` around the call (graphql_query never raises MCPToolError on errors)
    - `python scripts/test_mcp_simple.py` exits with code 0 when MCP server is running
```

### Verification

```yaml
command: python scripts/test_mcp_simple.py
criteria: >
  Exit code 0; P-09 passes alongside P-01–P-08; output contains "graphql_query"
  in the tool call log.
```

---

## Plan 17.2 — Add UAT Suite T-37–T-43

```yaml
wave: 1
depends_on: []
requirements:
  - GQL-19
files_modified:
  - scripts/run_mcp_uat.py
```

### Objective

Add 7 GraphQL UAT tests (T-37 to T-43) to `scripts/run_mcp_uat.py` in a new `### 4. GraphQL Tools` section. All tests use the existing `runner.test()` infrastructure.

### Tasks

```yaml
- id: 17.2-T01
  read_first:
    - scripts/run_mcp_uat.py  # existing categories dict (line ~772), existing test patterns, runner.test() usage
  action: >
    In `scripts/run_mcp_uat.py`, add a new section `### 4. GraphQL Tools` before the
    `print("\n## Test Case Summary by Category")` block (before line ~770).
    Insert the section header and all 7 test functions:

    ```python
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        # 4. GraphQL Tools (T-37 to T-43)
        # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

        print("\n## GraphQL Tools")

        def t37():
            result = client.call_tool("graphql_query", {
                "query": "{ devices(first: 5) { name status } }"
            })
            assert "data" in result, "Result must have 'data' key"
            assert "errors" in result, "Result must have 'errors' key"
            assert result["data"] is not None, f"Expected data, got: {result}"
            return result

        runner.test("T-37 graphql_query valid query — data returned, no errors", t37)

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

        runner.test("T-38 graphql_query syntax error — structured errors dict, no HTTP 500", t38)

        def t39():
            sdl = client.call_tool("graphql_introspect", {})
            assert isinstance(sdl, str), "Introspect must return string"
            assert len(sdl) > 50, "SDL should be > 50 chars"
            assert "type Query" in sdl, "SDL must contain 'type Query'"
            return {"sdl_length": len(sdl)}

        runner.test("T-39 graphql_introspect returns valid SDL schema string", t39)

        def t40():
            anon = MCPClient(MCP_ENDPOINT, "nbapikey_invalid_token_00000000000000")
            result = anon.call_tool("graphql_query", {
                "query": "{ devices { name } }"
            })
            assert "data" in result
            assert "errors" in result
            # graphql_query returns dict with auth error, not exception
            assert result["data"] is None, f"Anonymous should get no data, got: {result}"
            assert result["errors"] is not None and len(result["errors"]) > 0
            assert any(
                "Authentication" in str(e) for e in (result["errors"] or [])
            ), f"Expected auth error, got: {result['errors']}"
            return {"anonymous_restricted": True}

        runner.test("T-40 graphql_query anonymous token — auth error dict returned", t40)

        def t41():
            result = client.call_tool("graphql_query", {
                "query": "query GetDevices($limit: Int!) { devices(first: $limit) { name } }",
                "variables": {"limit": 3}
            })
            assert "data" in result
            assert result["data"] is not None, f"Variables query failed: {result}"
            return {"variables_working": True}

        runner.test("T-41 graphql_query variables injection — data returned", t41)

        def t42():
            result = client.call_tool("graphql_query", {
                "query": "{ devices(first: 3) { name status } }"
            })
            assert "data" in result
            assert result["data"] is not None, "Valid token → data must not be None"
            return {"token_authorized": True}

        runner.test("T-42 graphql_query valid token — full data access", t42)

        def t43():
            # Depth > 8 → structured error dict
            deep_query = "{ a { b { c { d { e { f { g { h { i } } } } } } } } }"
            result = client.call_tool("graphql_query", {"query": deep_query})
            assert result["data"] is None, f"Depth error should return no data: {result}"
            assert result["errors"] is not None and len(result["errors"]) > 0
            assert any("depth" in str(e).lower() for e in result["errors"])
            # Complexity > 1000 → structured error dict
            many_fields = ", ".join(f"field{i}: name" for i in range(1001))
            complex_query = f"{{ {many_fields} }}"
            result2 = client.call_tool("graphql_query", {"query": complex_query})
            assert result2["data"] is None
            assert result2["errors"] is not None and len(result2["errors"]) > 0
            assert any("complexity" in str(e).lower() for e in result2["errors"])
            return {"depth_and_complexity_limits_enforced": True}

        runner.test(
            "T-43 graphql_query depth and complexity limits — structured errors dict, no data",
            t43,
        )
    ```

    Key distinction from other auth tests:
    - `graphql_query` **never raises `MCPToolError`** — errors are always in the returned dict.
    - T-40 uses `assert result["data"] is None` (not `assert result.get("items") == []`).
    - The depth-9 query `{ a { b { ... } } }` must be syntactically valid (all braces closed)
      so it passes `parse()` and fails at `validate()` with a depth error.
  acceptance_criteria: >
    - 7 new test functions: `t37` through `t43`
    - Each registered via `runner.test("T-NN ...", tNN)`
    - T-40 uses `MCPClient` with invalid token (same pattern as T-27)
    - T-43 makes two sequential `client.call_tool` calls (depth, then complexity)
    - No `try/except MCPToolError` blocks for `graphql_query` calls (errors are dicts)
    - T-39 (introspect) makes an unfiltered call — may raise on auth failure (different tool)
```

```yaml
- id: 17.2-T02
  read_first:
    - scripts/run_mcp_uat.py  # categories dict (line ~772); summary() method
  action: >
    Update the `categories` dict in `run_uat()` to add the "GraphQL Tools" entry:

    ```python
    categories = {
        "Auth & Session": ["T-01", "T-02", "T-03", "T-04"],
        "List Tools": ["T-05", "T-06", "T-07", "T-08", "T-09", "T-10", "T-11", "T-12", "T-13"],
        "Get Tools": ["T-14", "T-15", "T-16", "T-17", "T-18", "T-19", "T-20", "T-21"],
        "Search": ["T-22", "T-23", "T-24", "T-25", "T-26"],
        "Auth Enforcement": ["T-27", "T-28", "T-29"],
        "GraphQL Tools": ["T-37", "T-38", "T-39", "T-40", "T-41", "T-42", "T-43"],
        "Performance": ["P-01", "P-02", "P-03", "P-04", "P-05", "P-06", "P-07", "P-08"],
    }
    ```
  acceptance_criteria: >
    - `categories` dict contains `"GraphQL Tools": ["T-37", ...]`
    - `summary()` prints "GraphQL Tools: N/7" after running all tests
```

### Verification

```yaml
command: python scripts/run_mcp_uat.py
criteria: >
  Exit code 0; "GraphQL Tools: 7/7" printed in the category summary;
  T-37 through T-43 all show "✅ PASS";
  No "❌ FAIL" entries for T-37 through T-43.
```

---

## Plan 17.3 — Update SKILL.md with GraphQL Tools Documentation

```yaml
wave: 1
depends_on: []
requirements:
  - GQL-20
files_modified:
  - nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md
```

### Objective

Update SKILL.md to document `graphql_query` and `graphql_introspect` with tool signatures, result shapes, error cases, and ≥ 2 example queries. Both tools are `tier="core"` so they belong in the Core Tools table.

### Tasks

```yaml
- id: 17.3-T01
  read_first:
    - nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md  # Core Tools table (line ~40), existing tool docs
  action: >
    In `SKILL.md`, add `graphql_query` and `graphql_introspect` to the Core Tools table
    (after `search_by_name`, before the blank line before `## Meta Tools`):

    ```markdown
    | graphql_query | Execute an arbitrary GraphQL query against Nautobot's GraphQL API. Returns {data, errors}. | `query: str`, `variables?: dict | None` | No |
    | graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. Use to discover available types and fields. | (none) | No |
    ```

    Also update the `core` scope description in the Scope Management section
    (inside the `core` list, after `search_by_name`, before `plus`):

    ```
    , `graphql_query`, `graphql_introspect`
    ```
  acceptance_criteria: >
    - Core Tools table contains both `graphql_query` and `graphql_introspect` rows
    - Scope Management `core` tool list mentions `graphql_query` and `graphql_introspect`
    - Table rows include all 4 columns: Tool, Description, Parameters, Paginated
```

```yaml
- id: 17.3-T02
  read_first:
    - nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md  # section placement; Investigation Workflows section
  action: >
    In `SKILL.md`, add a new `## GraphQL Tools` section before `## Meta Tools`
    (i.e., between the Core Tools section and the Meta Tools section, around line 52-53).

    Insert this content:

    ```markdown
    ---

    ## GraphQL Tools

    Nautobot exposes a full [graphene-django](https://docs.graphene-python.org/projects/django/)
    GraphQL API. These tools let you execute arbitrary GraphQL queries and introspect the
    schema directly from the MCP server.

    | Tool | Description | Parameters |
    |------|-------------|------------|
    | graphql_query | Execute an arbitrary GraphQL query. Returns `{"data": ..., "errors": [...]}` — both keys always present. | `query: str`, `variables?: dict | None` |
    | graphql_introspect | Return the Nautobot GraphQL schema as an SDL string. Use to discover available types and fields before writing queries. | (none) |

    ### graphql_query

    Execute arbitrary GraphQL queries against Nautobot's graphene-django schema.
    Auth token is required — anonymous queries return `{"data": null, "errors": [{"message": "Authentication required"}]}`.

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
    Both `data` and `errors` keys are always present. If a query succeeds with no errors,
    `errors` is `null`. If a query fails, `data` is `null`.

    **Error cases:** Errors are returned in the `errors` array (HTTP 200, no HTTP 500):
    - `"Authentication required"` — missing or invalid token
    - `"Query depth N exceeds maximum allowed depth of 8"` — query too deeply nested
    - `"Query complexity N exceeds maximum allowed complexity of 1000"` — query selects too many fields
    - `"Syntax Error: ..."` — malformed GraphQL syntax

    **Example — Simple device listing:**
    ```graphql
    query {
      devices(first: 10) {
        name
        status
      }
    }
    ```
    ```python
    result = mcp.call_tool("graphql_query", {
        "query": "query { devices(first: 10) { name status } }"
    })
    # → {"data": {"devices": [...]}, "errors": None}
    ```

    **Example — With variables:**
    ```graphql
    query GetDevices($limit: Int!) {
      devices(first: $limit) {
        name
        status
        platform { name }
        location { name }
      }
    }
    ```
    ```python
    result = mcp.call_tool("graphql_query", {
        "query": "query GetDevices($limit: Int!) { devices(first: $limit) { name status } }",
        "variables": {"limit": 5}
    })
    # → {"data": {"devices": [...]}, "errors": None}
    ```

    ### graphql_introspect

    Returns the full Nautobot GraphQL schema as a GraphQL SDL string. Use this to discover
    available object types, fields, and relationships before writing queries. Auth token required.

    **Returns:** Multi-line SDL string (e.g. `"type Query {\\n  devices: [Device]!\\n  ...\\n}"`)

    **Example:**
    ```python
    sdl = mcp.call_tool("graphql_introspect", {})
    # "schema {\\n  query: Query\\n}\\ntype Query {\\n  devices(first: Int): [Device]\\n  ..."
    print(sdl)  # View all available types and fields
    ```
    ```
  acceptance_criteria: >
    - New `## GraphQL Tools` section added before `## Meta Tools`
    - Both `graphql_query` and `graphql_introspect` documented in the section
    - `graphql_query` docstring includes: Parameters, Result shape, Error cases, 2 examples
    - `graphql_introspect` docstring includes: one-line description, Returns, 1 example
    - At least 2 example queries shown for `graphql_query`
    - `grep -c "graphql_query" SKILL.md` ≥ 5 occurrences
    - `grep -c "graphql_introspect" SKILL.md` ≥ 3 occurrences
```

### Verification

```yaml
command: >
  grep -c "graphql_query" nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md
  grep -c "graphql_introspect" nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md
  grep "Example" nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md | wc -l
criteria: >
  graphql_query ≥ 5 occurrences; graphql_introspect ≥ 3 occurrences;
  ≥ 2 "Example" code blocks present in the GraphQL Tools section.
```

---

## Plan 17.4 — Run Full `invoke tests` Pipeline

```yaml
wave: 2
depends_on:
  - 17.1
  - 17.2
  - 17.3
requirements:
  - GQL-18
  - GQL-19
  - GQL-20
files_modified: []
```

### Objective

Run the full test pipeline as the gate for this phase. All linters, unit tests, and UAT tests must pass.

### Tasks

```yaml
- id: 17.4-T01
  read_first:
    - .planning/phases/17-uat-and-documentation/17-RESEARCH.md  # §10 Verification Gates
  action: >
    Run the full CI pipeline from the project root:

    ```bash
    unset VIRTUAL_ENV && poetry run invoke tests
    ```

    This runs (in order): ruff, djlint, yamllint, markdownlint, poetry check,
    migrations check, pylint, docs, then unit tests.

    After linters pass, run the smoke test and UAT suite:

    ```bash
    python scripts/test_mcp_simple.py
    python scripts/run_mcp_uat.py
    ```
  acceptance_criteria: >
    - `invoke tests` exits with code 0 (all linters clean, all unit tests pass)
    - `python scripts/test_mcp_simple.py` exits with code 0 (P-09 green)
    - `python scripts/run_mcp_uat.py` exits with code 0 (T-37–T-43 all green)
    - Pylint score remains 10.00/10
```

### Full-Phase Gate

```yaml
command: unset VIRTUAL_ENV && poetry run invoke tests && python scripts/test_mcp_simple.py && python scripts/run_mcp_uat.py
criteria: >
  All commands exit with code 0.
  Output shows:
    - P-09: ✅ PASS in smoke test output
    - T-37: ✅ PASS
    - T-38: ✅ PASS
    - T-39: ✅ PASS
    - T-40: ✅ PASS
    - T-41: ✅ PASS
    - T-42: ✅ PASS
    - T-43: ✅ PASS
    - "GraphQL Tools: 7/7" in UAT summary
    - "GraphQL Tools" category line in smoke test (if applicable)
```

---

## File Summary

| File | Change |
|------|--------|
| `scripts/test_mcp_simple.py` | Add P-09 GraphQL smoke test (8–10 lines) |
| `scripts/run_mcp_uat.py` | Add T-37–T-43 section + update `categories` dict (~80 lines) |
| `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` | Add GraphQL tools to Core Tools table + `## GraphQL Tools` section (~50 lines) |

---

## Implementation Order

```
Wave 1 (parallel)
  Plan 17.1 → scripts/test_mcp_simple.py — P-09 smoke test
  Plan 17.2 → scripts/run_mcp_uat.py — T-37–T-43 UAT suite
  Plan 17.3 → SKILL.md — graphql_query + graphql_introspect documentation

Wave 2 (sequential after Wave 1)
  Plan 17.4 → invoke tests — full pipeline gate
```

---

*Plan: 17-uat-and-documentation*
*GQL-18 (P-09 smoke test), GQL-19 (T-37–T-43 UAT suite), GQL-20 (SKILL.md docs)*
