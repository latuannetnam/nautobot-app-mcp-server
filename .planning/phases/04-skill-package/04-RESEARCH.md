# Phase 4: SKILL.md Package — Research Document

**Research date:** 2026-04-02
**Phase:** 04-skill-package
**Question:** "What do I need to know to PLAN this phase well?"

---

## Domain 1 — SKILL.md Conventions

### What AI Agents Expect from SKILL.md

SKILL.md is a **community-adopted convention** for self-documenting AI agent capabilities — it is not formally standardized by any governing body (MCP, Anthropic, etc.). It serves as both **human-readable reference** and **machine-parseable capability disclosure** for agents that read it at runtime.

The convention has gained traction in MCP ecosystem projects (e.g., npm MCP packages, Claude Desktop skill files). The core idea: when an AI agent encounters a new environment, it reads SKILL.md to understand what tools are available and how to use them.

### Standard SKILL.md Section Structure

Based on established community patterns (AI agent READMEs, MCP package conventions, and agent-framework documentation):

```
# <Skill/Agent Name>

## Overview
One-paragraph description of what this skill does.

## Quick Start
How to enable/configure. For MCP tools: call mcp_list_tools() to discover scopes.

## Tools
Table of available tools with name, description, parameters.

## Scope Management
How to enable/disable tool groups (mcp_enable_tools, mcp_disable_tools).

## Pagination
Cursor format, limits, summarize-at-N behavior.

## Investigation Workflows
Step-by-step tool sequences for common tasks.

## Limitations / Notes
Known constraints.
```

### Tool Reference Table Format

The most agent-readable format is a **pipe-separated markdown table** — it is both human-scannable and parseable by LLMs:

```
| Tool | Description | Parameters | Paginated |
|---|---|---|---|
| device_list | List network devices | limit, cursor | Yes (25/def, 1000/max) |
| device_get | Get device by name or ID | name_or_id | No |
```

**Critical decisions for this project:**

1. **One table for core tools, one for meta tools** — separates always-available from scope-gated
2. **Parameters column uses `{param_name}: {type}` format** — compact, avoids wrapping
3. **Pagination column is "Yes/No" with limits** — agents need to know cursor behavior at a glance
4. **No prose descriptions inside the table** — the description field IS the prose; table rows are scannable
5. **Workflows section uses numbered steps with inline tool calls** — e.g., `1. device_get(name_or_id="router-01")` as a complete call

### What to Avoid

- **Do not use YAML frontmatter** — agents don't parse it; adds noise to context
- **Do not use nested bullet lists** — hard to parse in a single pass
- **Do not omit the pagination section** — agents MUST know about summarize-at-100 and cursor format, otherwise they'll paginate incorrectly
- **Do not use abbreviations in tool names** — the table should use exact tool names as registered (e.g., `ipaddress_list`, not `ip_list`)

### Sources

- Community MCP SKILL.md conventions (web search: "MCP SKILL.md AI agent convention", April 2026)
- Anthropic agent documentation patterns (agent self-discovery conventions)
- Claude Code SKILL.md expectations: flat, table-based, minimal prose

---

## Domain 2 — Python Package Structure for SKILL.md

### Architecture Decision: Separate Package at Repo Root

The ROADMAP specifies `nautobot-mcp-skill/` at the **repo root** (not inside `nautobot_app_mcp_server/`). This is correct for two reasons:

1. **Separate installability** — `pip install ./nautobot-mcp-skill` must work independently of the main app
2. **Cleaner dependency boundary** — the skill package has **zero runtime dependencies**; it is pure documentation

### Package Structure

```
nautobot-mcp-skill/
├── SKILL.md
├── pyproject.toml
├── MANIFEST.in          # needed for setuptools sdist
└── nautobot_mcp_skill/
    └── __init__.py       # __version__ only
```

### pyproject.toml Configuration

**Build system:** Use `setuptools` (not Poetry) for this package. Rationale:

- Poetry cannot install a subdirectory package from the parent repo root via `pip install ./nautobot-mcp-skill` without complex workspace configuration
- `setuptools` is the universal build backend and works reliably for pure-documentation packages
- The main app continues to use Poetry; this is a sibling package with its own `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "nautobot-mcp-skill"
version = "0.1.0a0"          # Must match main pyproject.toml (see Domain 4)
description = "SKILL.md for nautobot-app-mcp-server — AI agent capability reference"
readme = "SKILL.md"
license = {text = "Apache-2.0"}
authors = [{name = "Le Anh Tuan", email = "latuannetnam@gmail.com"}]
requires-python = ">=3.10"

[tool.setuptools]
include-package-data = true   # reads MANIFEST.in

[tool.setuptools.dynamic]
version = {attr = "nautobot_mcp_skill.__version__"}
```

**Why `setuptools_dynamic_version`:** This pattern reads `__version__` from the installed `__init__.py`, eliminating duplication. See Domain 4 for version sync strategy.

### MANIFEST.in

Required for setuptools sdist to include SKILL.md:

```in
include SKILL.md
```

Without this, `python -m build --sdist` will silently omit SKILL.md.

### package_data vs include_package_data

| Approach | Mechanism | SKILL.md included? |
|---|---|---|
| `package_data = {"": ["SKILL.md"]}` | globs relative to package dir | No — SKILL.md is at repo root, not inside `nautobot_mcp_skill/` |
| `include_package_data = true` + `MANIFEST.in` | MANIFEST.in controls sdist | Yes for sdist |
| `include = ["SKILL.md"]` (Poetry) | Poetry-specific | Yes for both sdist + wheel |

**Recommended:** `MANIFEST.in` + `include-package-data = true`. This works for both sdist and wheel via setuptools.

**Alternative (simpler):** Add SKILL.md inside `nautobot_mcp_skill/SKILL.md` (package subdirectory). Then use `package_data = {"nautobot_mcp_skill": ["SKILL.md"]}`. This is easier to verify but changes the path agents use to read it.

**Decision for this project:** Keep SKILL.md at package root (`./SKILL.md`) per the ROADMAP. Use `MANIFEST.in` + `include-package-data`.

### Verification of SKILL.md Location Post-Install

After `pip install ./nautobot-mcp-skill`, verify SKILL.md exists at the expected location:

```bash
python -c "import os, nautobot_mcp_skill; print(os.path.join(os.path.dirname(nautobot_mcp_skill.__file__), 'SKILL.md'))"
# Expected: .../nautobot_mcp_skill-0.1.0a0.dist-info/../../../SKILL.md
# Or more reliably:
python -c "import os, importlib.resources; print(importlib.resources.files('nautobot_mcp_skill') / 'SKILL.md')"
```

For agents reading SKILL.md at runtime, the recommended approach is:
```python
import os
pkg_root = os.path.dirname(__file__)  # __init__.py directory
skill_path = os.path.join(pkg_root, "..", "SKILL.md")  # one level up
```

### What to Avoid

- **Do not add runtime dependencies** — this package is pure documentation
- **Do not use `packages = [find:]`** — there is only one package dir with no `__init__.py`-heavy structure; just use the implicit package format
- **Do not skip MANIFEST.in** — sdist builds will silently omit SKILL.md without it

### Sources

- [Python Packaging User Guide: Package Data](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [setuptools docs: include_package_data vs package_data](https://setuptools.pypa.io/en/latest/userguide/datafiles.html)
- Poetry `include` field behavior (Poetry-specific, not used here)

---

## Domain 3 — Investigation Workflow Documentation

### Effective Workflow Documentation for AI Agents

The goal is to document **step-by-step tool sequences** that agents can follow to accomplish real-world tasks. Agents read these as instructions, not as prose to summarize.

### Format Principles

1. **Numbered steps** — sequential, unambiguous order
2. **Tool calls as inline code** — `tool_name(param="value")` — agents recognize these as executable calls
3. **Input/output context** — briefly note what the output enables for the next step
4. **Compact** — each workflow fits on one screen; no excessive explanation
5. **Real parameter values** — use realistic examples (e.g., `"router-01"`, not `"<device_name>"`)

### Example: Investigate Device by Name

```markdown
### Workflow 1: Investigate a Device by Name

**Goal:** Get full device details and its network interfaces.

1. `search_by_name(query="router-01")` — find the device; note its `pk`
2. `device_get(name_or_id="<pk or name>")` — get device with status, platform, location
3. `interface_list(device_name="router-01", limit=50)` — list all interfaces
4. For a specific interface: `interface_get(name_or_id="<interface pk or name>")`
```

### Example: Find IP Address by Prefix

```markdown
### Workflow 2: Find IP Addresses in a Prefix

**Goal:** List all IP addresses within a given prefix.

1. `prefix_list(limit=25)` — browse prefixes; find the prefix you need, note its `pk`
2. `ipaddress_list(limit=100)` — list IP addresses; Nautobot associates them with prefixes via assignment
   - Note: filter by prefix is not available; iterate with cursor pagination through relevant prefixes
3. Alternatively: `search_by_name(query="10.0.0")` — fuzzy search for IPs in the 10.0.0.x range
```

### Example: Explore Device Interfaces and BGP Addresses

```markdown
### Workflow 3: Explore Device Interfaces and IP Addresses

**Goal:** Get a device's interfaces and their assigned IP addresses.

1. `device_get(name_or_id="<device>")` — verify device exists; note name
2. `interface_list(device_name="<device>", limit=100)` — list all interfaces with `mac_address`, `description`
3. For each interface of interest: `interface_get(name_or_id="<interface pk>")`
   — returns nested `ip_addresses` with address, tenant, VRF
4. For BGP peer IPs: filter `ipaddress_list()` by the interface IPs from step 3
```

### What to Avoid

- **Do not use placeholder brackets without explanation** — `device_get(name_or_id=...)` is confusing; show real example: `device_get(name_or_id="router-01")`
- **Do not mix tool names and conceptual steps** — "First, find the device" (concept) vs `search_by_name(query="...")` (tool call)
- **Do not skip the "why"** — briefly note what the output enables: "note its pk for next step"
- **Do not include error handling** — agents need the happy path; errors are their own recovery workflow

### Sources

- MCP tool documentation patterns from anthropic/mcp, prefect/fastmcp SDKs
- Claude Code tool documentation standards (agent actionability over completeness)

---

## Domain 4 — Version Alignment

### The Version Sync Problem

The skill package and the main app must share the same version number (`0.1.0a0`). The ROADMAP (D-02) specifies: "Version in `__init__.py` matching `pyproject.toml`; no separate release cycle."

### Current Version Source in Main App

The main `nautobot_app_mcp_server/__init__.py` reads version dynamically:

```python
from importlib import metadata
__version__ = metadata.version(__name__)  # reads from installed package metadata
```

This works because the main app is built and installed as a proper package.

### Version Options for Skill Package

| Approach | Mechanism | Pros | Cons |
|---|---|---|---|
| Hardcode in pyproject.toml only | Static string | Simple | Must update MANUALLY in two places at release |
| `__version__` in `__init__.py` + `setuptools_dynamic_version` | attr directive | Single source of truth | Requires build to resolve; not visible in `pip show` |
| `__version__` in `__init__.py` + mirror in pyproject.toml | Manual | Simple | Manual sync required |
| Git tag via `setuptools-scm` | Git tag → version | Auto, accurate | Overkill for internal-only package |

**Recommended:** `__version__` in `nautobot_mcp_skill/__init__.py` + `setuptools_dynamic_version` in pyproject.toml.

```python
# nautobot_mcp_skill/__init__.py
__version__ = "0.1.0a0"
```

```toml
# pyproject.toml (skill package)
[tool.setuptools.dynamic]
version = {attr = "nautobot_mcp_skill.__version__"}
```

**Why this:** The `attr` directive reads from the installed `__init__.py`. During `pip install ./nautobot-mcp-skill`, setuptools reads the attribute value and stamps it into the wheel metadata. This is the same pattern used by thousands of Python packages.

### Manual Version Bump Protocol (v1.0.0)

At each release, update both locations atomically in the same commit:

```bash
# 1. Update main app __init__.py (if it uses a static version — currently uses importlib.metadata so no change needed there)
# 2. Update skill package __init__.py
sed -i 's/__version__ = ".*"/__version__ = "1.0.0"/' nautobot-mcp-skill/nautobot_mcp_skill/__init__.py
# 3. Commit with release tag
git add -A && git commit -m "release: v1.0.0"
```

**Note:** The main app's `__init__.py` uses `metadata.version(__name__)` which reads from the installed wheel metadata — it does not need to be changed at release time. The skill package's `__init__.py` MUST be updated manually since it uses a static string.

### Towncrier Integration

Towncrier (already in the main project's dev dependencies) is **not needed for the skill package** — it manages changelog fragments for the main project only. The skill package is documentation-only; its version follows the main app's release cycle.

Towncrier's `[[tool.towncrier.type]]` fragments in the main `pyproject.toml` cover changes to the MCP server, not to the skill package. SKILL.md changes (SKILL-02, SKILL-03) should be documented as "documentation" type in the main project's towncrier fragments.

### Sources

- [setuptools dynamic versioning](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html#dynamic-versioning)
- [Python Packaging User Guide: Versioning](https://packaging.python.org/en/latest/guides/distributing-packages-using-setuptools/#version)
- Towncrier documentation (for main project integration, not skill package)

---

## Domain 5 — Verification Approach

### Verification Strategy

The success criteria from the ROADMAP must be verifiable via shell commands, not visual inspection.

### Criterion 1: `pip install` Without Errors

```bash
pip install ./nautobot-mcp-skill
# Expected: successful install with no errors
pip show nautobot-mcp-skill | grep Version
# Expected: 0.1.0a0
```

**What can go wrong:**
- Missing `MANIFEST.in` → SKILL.md missing from sdist → install succeeds but no SKILL.md
- Wrong `build-backend` → build fails
- Missing `requires-python` → pip may reject on some Python versions

### Criterion 2: SKILL.md Exists with Core Tools Table (10 + 3)

```bash
python -c "
import os, nautobot_mcp_skill
skill_path = os.path.join(os.path.dirname(nautobot_mcp_skill.__file__), 'SKILL.md')
assert os.path.exists(skill_path), f'SKILL.md not found at {skill_path}'
content = open(skill_path).read()
required_tools = [
    'device_list', 'device_get', 'interface_list', 'interface_get',
    'ipaddress_list', 'ipaddress_get', 'prefix_list', 'vlan_list',
    'location_list', 'search_by_name',
    'mcp_enable_tools', 'mcp_disable_tools', 'mcp_list_tools',
]
missing = [t for t in required_tools if t not in content]
assert not missing, f'Missing tools: {missing}'
print(f'OK: SKILL.md exists with all 13 tools documented')
"
```

### Criterion 3: Scope Management Documentation

```bash
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
for term in ['mcp_enable_tools', 'mcp_disable_tools', 'scope', 'session']:
    assert term in content, f'Missing: {term}'
print('OK: scope management documented')
"
```

### Criterion 4: Pagination Documentation

```bash
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
checks = [
    ('25' in content and 'default' in content.lower(), 'default=25'),
    ('1000' in content or 'max' in content.lower(), 'max=1000'),
    ('100' in content and 'summarize' in content.lower(), 'summarize-at-100'),
    ('cursor' in content.lower() and 'base64' in content.lower(), 'cursor+base64'),
]
for ok, label in checks:
    assert ok, f'Pagination check failed: {label}'
print('OK: pagination fully documented')
"
```

### Criterion 5: 3 Investigation Workflows

```bash
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
workflows = ['device', 'prefix', 'interface']
found = [w for w in workflows if w in content.lower()]
assert len(found) >= 3, f'Only {len(found)}/3 workflows found'
print(f'OK: {len(found)} investigation workflows documented')
"
```

### Installability Test (sdist + wheel)

```bash
cd nautobot-mcp-skill
python -m build --sdist --wheel
pip install dist/nautobot_mcp_skill-*.whl --force-reinstall --no-deps
python -c "import nautobot_mcp_skill; print(nautobot_mcp_skill.__version__)"
```

### What to Avoid

- **Do not rely on visual inspection of `pip install` output** — use assertions
- **Do not skip the sdist/wheel build test** — SKILL.md may be missing from sdist without MANIFEST.in
- **Do not test SKILL.md content with regex** — use substring checks for tool names (prone to false positives with regex patterns)

### Integration with `invoke tests`

The main project's `invoke tests` command runs ruff, pylint, djlint, and unit tests. The skill package is **not included** in the main project's `pyproject.toml` or `tasks.py`. It should have its own minimal test, runnable via:

```bash
cd nautobot-mcp-skill
python -m build && pip install dist/*.whl --force-reinstall --no-deps
# Then run the verification checks above
```

Or as a single invoke task added to `tasks.py`:

```python
@task
def skill_tests(c):
    """Run skill package verification tests."""
    c.run("cd nautobot-mcp-skill && python -m build -w")
    c.run("pip install ./nautobot-mcp-skill/dist/*.whl --force-reinstall --no-deps")
    c.run("python -c 'import nautobot_mcp_skill; print(nautobot_mcp_skill.__version__)'")
```

### Sources

- [pip installation verification patterns](https://pip.pypa.io/en/stable/topics/comparing-package-versions/)
- [Python build verification: sdist + wheel](https://packaging.python.org/en/latest/tutorials/packaging-projects/)

---

## Synthesis: What to Do in the PLAN

### Structural Decisions (already made in 04-CONTEXT.md)

These are resolved and need no further investigation:
- D-01: Package at repo root `nautobot-mcp-skill/`
- D-02: Version in `__init__.py` matching main `pyproject.toml`
- D-03–D-05: Tool reference table content
- D-06–D-07: Pagination and scope management docs
- D-08: 3 investigation workflows
- D-09: Table-based, minimal prose
- D-10: Local pip install only

### Planning Inputs Still Needed

Before writing the plan, the following are needed from the PLAN phase:

1. **Exact SKILL.md header content** — Does it need a version number and last-updated date? Yes: add `Version: {version}` and `Last Updated: {date}` as plain text lines at top.
2. **SKILL.md location inside the package after install** — Root-relative (`./SKILL.md`) is specified in ROADMAP. Agents must use `os.path.dirname(__file__) + "/../SKILL.md"` or `importlib.resources`. This must be documented in the SKILL.md itself.
3. **Skill package in `invoke` tasks** — Should `tasks.py` gain a `skill-tests` task? Recommend: yes, a lightweight one.
4. **Towncrier fragment type for SKILL changes** — "documentation" type in main project's `changes/` directory. This is a process decision, not an implementation decision.

### File Creation List (from research)

```
nautobot-mcp-skill/
├── SKILL.md              # Primary skill definition
├── pyproject.toml        # setuptools build, dynamic version
├── MANIFEST.in           # include SKILL.md in sdist
└── nautobot_mcp_skill/
    └── __init__.py       # __version__ = "0.1.0a0"
```

### Implementation Steps (summary from all domains)

1. Create `nautobot-mcp-skill/pyproject.toml` with setuptools + dynamic version
2. Create `nautobot-mcp-skill/MANIFEST.in` with `include SKILL.md`
3. Create `nautobot-mcp-skill/nautobot_mcp_skill/__init__.py` with `__version__`
4. Write `nautobot-mcp-skill/SKILL.md`:
   - Header: name, version, last updated
   - Quick Start: call `mcp_list_tools()` to discover
   - Core Tools table: 10 tools with name, description, params, paginated?
   - Meta Tools table: 3 tools
   - Scope Management section
   - Pagination section: defaults, limits, cursor format, summarize-at-100
   - Investigation Workflows section: 3 workflows
5. Verify: `pip install ./nautobot-mcp-skill` + Python assertions
6. Add `invoke skill-tests` to `tasks.py` (optional but recommended)

### Sources Referenced

- [Python Packaging User Guide](https://packaging.python.org/) — package structure, versioning
- [setuptools dynamic versioning](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html) — attr-based version
- [pip documentation](https://pip.pypa.io/) — installation verification
- Community MCP SKILL.md conventions (web search, April 2026)
- Towncrier documentation (version management patterns)

---

*Research complete: 2026-04-02*
*Domains covered: SKILL.md conventions, Python package structure, workflow documentation, version alignment, verification approach*
