---
wave: 1
depends_on: []
requirements:
  - SKILL-01
  - SKILL-02
  - SKILL-03
files_modified:
  - nautobot-mcp-skill/SKILL.md
  - nautobot-mcp-skill/pyproject.toml
  - nautobot-mcp-skill/MANIFEST.in
  - nautobot-mcp-skill/nautobot_mcp_skill/__init__.py
autonomous: true
---

# Phase 4 Plan — SKILL.md Package

**Phase goal:** Package `SKILL.md` as a standalone pip package (`nautobot-mcp-skill/`) consumable by AI agents.
**Requirements addressed:** SKILL-01, SKILL-02, SKILL-03

---

## Verification Criteria

Run these after all tasks to confirm success:

```bash
# 1. Install without errors
pip install ./nautobot-mcp-skill --quiet

# 2. SKILL.md readable from installed package
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

# 3. Scope management documented
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
for term in ['mcp_enable_tools', 'mcp_disable_tools', 'scope']:
    assert term in content, f'Missing: {term}'
print('OK: scope management documented')
"

# 4. Pagination documented
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
checks = [
    ('LIMIT_DEFAULT' in content or 'default=25' in content, 'default=25'),
    ('LIMIT_MAX' in content or 'max=1000' in content, 'max=1000'),
    ('summarize' in content.lower() and '100' in content, 'summarize-at-100'),
    ('cursor' in content.lower() and 'base64' in content.lower(), 'cursor+base64'),
]
for ok, label in checks:
    assert ok, f'Pagination check failed: {label}'
print('OK: pagination fully documented')
"

# 5. 3 investigation workflows present
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
workflows = ['device', 'prefix', 'interface']
found = [w for w in workflows if w in content.lower()]
assert len(found) >= 3, f'Only {len(found)}/3 workflows found'
print(f'OK: {len(found)} investigation workflows documented')
"
```

---

## Task 1 — Create Package Skeleton

<read_first>
- `.planning/phases/04-skill-package/04-RESEARCH.md` (Domain 2: Python Package Structure)
- `pyproject.toml` (version: `0.1.0a0`, author: "Le Anh Tuan <latuannetnam@gmail.com>")
</read_first>

<action>
Create the following directory and files at the repo root:

**`nautobot-mcp-skill/nautobot_mcp_skill/__init__.py`**
```python
"""nautobot-mcp-skill — SKILL.md package for nautobot-app-mcp-server AI agents."""

__version__ = "0.1.0a0"
```

**`nautobot-mcp-skill/pyproject.toml`**
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "nautobot-mcp-skill"
version = "0.1.0a0"
description = "SKILL.md for nautobot-app-mcp-server — AI agent capability reference"
readme = "SKILL.md"
license = {text = "Apache-2.0"}
authors = [{name = "Le Anh Tuan", email = "latuannetnam@gmail.com"}]
requires-python = ">=3.10"

[tool.setuptools]
include-package-data = true

[tool.setuptools.dynamic]
version = {attr = "nautobot_mcp_skill.__version__"}
```

**`nautobot-mcp-skill/MANIFEST.in`**
```
include SKILL.md
```

</action>

<acceptance_criteria>
- `test -f nautobot-mcp-skill/pyproject.toml` succeeds
- `test -f nautobot-mcp-skill/MANIFEST.in` succeeds
- `test -f nautobot-mcp-skill/nautobot_mcp_skill/__init__.py` succeeds
- `grep '__version__ = "0.1.0a0"' nautobot-mcp-skill/nautobot_mcp_skill/__init__.py` succeeds
- `grep 'build-backend = "setuptools.build_meta"' nautobot-mcp-skill/pyproject.toml` succeeds
- `grep 'include SKILL.md' nautobot-mcp-skill/MANIFEST.in` succeeds
</acceptance_criteria>

---

## Task 2 — Write SKILL.md

<read_first>
- `nautobot_app_mcp_server/mcp/tools/core.py` (all 10 core tools: names, input schemas, descriptions — verbatim from docstrings)
- `nautobot_app_mcp_server/mcp/tools/pagination.py` (LIMIT_DEFAULT=25, LIMIT_MAX=1000, LIMIT_SUMMARIZE=100, cursor format)
- `nautobot_app_mcp_server/mcp/session_tools.py` (3 meta tools: mcp_enable_tools, mcp_disable_tools, mcp_list_tools — verbatim from docstrings)
- `.planning/phases/04-skill-package/04-RESEARCH.md` (Domain 1: SKILL.md conventions, Domain 3: workflow format)
- `.planning/phases/04-skill-package/04-CONTEXT.md` (D-03 through D-09: content requirements)
</read_first>

<action>
Write `nautobot-mcp-skill/SKILL.md` with ALL of the following sections in order:

### Section 1 — Header
```
# Nautobot MCP Server — AI Agent Skill

Version: 0.1.0a0
Last Updated: 2026-04-02
Nautobot: >=3.0.0, <4.0.0
```

### Section 2 — Overview
One paragraph: "This skill provides MCP tools for querying Nautobot network inventory data. All tools enforce Nautobot object-level permissions. Tool visibility is controlled via session scopes (mcp_enable_tools / mcp_disable_tools)."

### Section 3 — Quick Start
Bulleted list:
- Call `mcp_list_tools()` to discover all available tools for the current session
- Call `mcp_enable_tools(scope="dcim")` to enable DCIM tools (devices, interfaces)
- Call `mcp_enable_tools(scope="ipam")` to enable IPAM tools (prefixes, VLANs, IP addresses)
- Core tools (device_list, device_get, etc.) are always available without enabling

### Section 4 — Pagination
Text block explaining:
- Default limit: 25 items per request
- Maximum limit: 1000 items per request
- Cursor format: `base64(str(pk))` — opaque token from `cursor` field of previous response
- `LIMIT_SUMMARIZE=100`: when total results exceed 100, the response includes a `summary` dict with `total_count` and a message; raw items are still returned
- To get the next page: pass the `cursor` value from the previous response as the `cursor` parameter

### Section 5 — Core Tools
Markdown table with these exact columns:
```
| Tool | Description | Parameters | Paginated |
|---|---|---|---|
```

One row per tool. Pull description text DIRECTLY from the tool's `register_mcp_tool(description=...)` call in `core.py`:

| Tool | Description (from code) | Parameters |
|---|---|---|
| device_list | List network devices with status, platform, location, and more. | `limit?: int (default=25, max=1000)`, `cursor?: str` |
| device_get | Get a single device by name or ID, with interfaces prefetched. | `name_or_id: str` |
| interface_list | List network interfaces, optionally filtered by device name. | `device_name?: str`, `limit?: int (default=25, max=1000)`, `cursor?: str` |
| interface_get | Get a single interface by name or ID, with IP addresses prefetched. | `name_or_id: str` |
| ipaddress_list | List IP addresses with tenant, VRF, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` |
| ipaddress_get | Get a single IP address by address or ID, with interfaces prefetched. | `name_or_id: str` |
| prefix_list | List network prefixes with VRF, tenant, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` |
| vlan_list | List VLANs with site/group, status, and role. | `limit?: int (default=25, max=1000)`, `cursor?: str` |
| location_list | List locations with location type, parent, and tenant. | `limit?: int (default=25, max=1000)`, `cursor?: str` |
| search_by_name | Multi-model name search across devices, interfaces, IP addresses, prefixes, VLANs, and locations. All search terms must match (AND semantics). | `query: str`, `limit?: int (default=25, max=1000)`, `cursor?: str` |

All 10 rows must have `Paginated: Yes`.

### Section 6 — Meta Tools
Markdown table with these exact columns:
```
| Tool | Description | Parameters |
|---|---|---|
```

| Tool | Description (from code) | Parameters |
|---|---|---|
| mcp_enable_tools | Enable tool scopes or fuzzy-search matches for this session. | `scope?: str`, `search?: str` |
| mcp_disable_tools | Disable a tool scope for this session. | `scope?: str` |
| mcp_list_tools | Return all registered tools visible to this session. | (none) |

### Section 7 — Scope Management
Text section explaining:
- Three tool scopes: `core` (always enabled), `dcim` (devices, interfaces), `ipam` (prefixes, VLANs, IP addresses, locations)
- `mcp_enable_tools(scope="dcim")` enables all DCIM tools and stays active for the session
- `mcp_enable_tools(scope="dcim.interface")` enables only interface tools
- `mcp_disable_tools(scope="dcim")` disables DCIM tools and all their children
- `mcp_disable_tools()` with no arguments disables all non-core tools
- Tool scope hierarchy: enabling a parent scope (e.g. `dcim`) activates all child scopes (e.g. `dcim.device`, `dcim.interface`)
- Fuzzy search: `mcp_enable_tools(search="bgp")` enables all tools whose name or description matches "bgp"

### Section 8 — Investigation Workflows

**Workflow 1: Investigate a Device by Name**
Goal: Get full device details and its network interfaces.
1. `search_by_name(query="router-01")` — find the device; note its `pk`
2. `device_get(name_or_id="router-01")` — get device with status, platform, location, and nested interfaces
3. `interface_list(device_name="router-01", limit=50)` — list all interfaces on this device
4. `interface_get(name_or_id="<interface pk>")` — get a specific interface with its IP addresses

**Workflow 2: Find IP Addresses in a Prefix**
Goal: List all IP addresses within a given prefix.
1. `prefix_list(limit=25)` — browse prefixes; find the target prefix, note its `pk`
2. `ipaddress_list(limit=100)` — list IP addresses; use cursor pagination to scan through addresses in the target range
3. Alternatively: `search_by_name(query="10.0.0")` — fuzzy search for IPs in the 10.0.0.x range

**Workflow 3: Explore Device Interfaces and IP Addresses**
Goal: Get a device's interfaces and their assigned IP addresses.
1. `device_get(name_or_id="router-01")` — verify the device exists; note its name
2. `interface_list(device_name="router-01", limit=100)` — list all interfaces with `mac_address`, `description`
3. `interface_get(name_or_id="<interface pk>")` — get a specific interface; response includes nested `ip_addresses` with `address`, `tenant`, `vrf`
4. Use the IPs from step 3 in `ipaddress_get(name_or_id="<ip pk>")` for full IP details

### Section 9 — Limitations
- Write tools (create/update/delete) are not available in v1
- Results are subject to Nautobot object-level permissions (`.restrict(user, action="view")`)
- Cursor pagination uses `pk__gt` — results are ordered by primary key insertion order
- Session state is in-memory (not persisted across server restarts)

</action>

<acceptance_criteria>
- `grep -c "device_list" nautobot-mcp-skill/SKILL.md` ≥ 1
- `grep -c "mcp_enable_tools" nautobot-mcp-skill/SKILL.md` ≥ 2
- `grep -c "mcp_disable_tools" nautobot-mcp-skill/SKILL.md` ≥ 1
- `grep -c "mcp_list_tools" nautobot-mcp-skill/SKILL.md` ≥ 1
- `grep -c "search_by_name" nautobot-mcp-skill/SKILL.md` ≥ 2
- `grep "base64" nautobot-mcp-skill/SKILL.md` succeeds
- `grep "summarize" nautobot-mcp-skill/SKILL.md` succeeds
- `grep "Workflow 1" nautobot-mcp-skill/SKILL.md` succeeds
- `grep "Workflow 2" nautobot-mcp-skill/SKILL.md` succeeds
- `grep "Workflow 3" nautobot-mcp-skill/SKILL.md` succeeds
- `grep "0.1.0a0" nautobot-mcp-skill/SKILL.md` succeeds
- Total line count of SKILL.md ≥ 150 lines
</acceptance_criteria>

---

## Task 3 — Verify Package Installs and SKILL.md is Present

<read_first>
- `nautobot-mcp-skill/pyproject.toml`
- `nautobot-mcp-skill/MANIFEST.in`
</read_first>

<action>
Run the following in sequence:

```bash
# 1. Build the package (wheel + sdist)
cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server
python -m build --wheel --sdist -o nautobot-mcp-skill/dist nautobot-mcp-skill

# 2. Install from wheel (no deps — pure documentation package)
pip install nautobot-mcp-skill/dist/*.whl --force-reinstall --no-deps --quiet

# 3. Verify version
python -c "import nautobot_mcp_skill; assert nautobot_mcp_skill.__version__ == '0.1.0a0', nautobot_mcp_skill.__version__; print('version OK')"

# 4. Verify SKILL.md is accessible from installed package
python -c "
import os, nautobot_mcp_skill
pkg_root = os.path.dirname(nautobot_mcp_skill.__file__)
skill_path = os.path.join(pkg_root, 'SKILL.md')
assert os.path.exists(skill_path), f'SKILL.md not at {skill_path}'
assert os.path.getsize(skill_path) > 5000, 'SKILL.md too small'
print(f'SKILL.md OK: {skill_path}')
"

# 5. Verify all 13 tools in installed SKILL.md
python -c "
import os, nautobot_mcp_skill
pkg_root = os.path.dirname(nautobot_mcp_skill.__file__)
content = open(os.path.join(pkg_root, 'SKILL.md')).read()
required = [
    'device_list', 'device_get', 'interface_list', 'interface_get',
    'ipaddress_list', 'ipaddress_get', 'prefix_list', 'vlan_list',
    'location_list', 'search_by_name',
    'mcp_enable_tools', 'mcp_disable_tools', 'mcp_list_tools',
]
missing = [t for t in required if t not in content]
assert not missing, f'Missing: {missing}'
print('All 13 tools present in SKILL.md')
"

# 6. Cleanup dist/
rm -rf nautobot-mcp-skill/dist
```

</action>

<acceptance_criteria>
- `python -m build --wheel --sdist` exits with code 0
- `pip install .../*.whl --no-deps` exits with code 0
- `python -c "import nautobot_mcp_skill; assert nautobot_mcp_skill.__version__ == '0.1.0a0'"` succeeds
- `python -c "... SKILL.md accessible from installed package ..."` succeeds
- `python -c "... all 13 tools present in SKILL.md ..."` succeeds
- `nautobot-mcp-skill/dist/` is removed (clean state)
</acceptance_criteria>

---

## Task 4 — Final Verification Against Phase Success Criteria

<read_first>
- `.planning/ROADMAP.md` (Phase 4 success criteria)
</read_first>

<action>
Run all 5 phase success criteria from ROADMAP.md:

```bash
cd /home/latuan/Local_Programming/nautobot-project/nautobot-app-mcp-server

# Criterion 1: pip install succeeds
pip install ./nautobot-mcp-skill --quiet
echo "Criterion 1: PASSED"

# Criterion 2: SKILL.md with Core Tools table (10 core + 3 meta = 13 tools)
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
tools = ['device_list','device_get','interface_list','interface_get',
         'ipaddress_list','ipaddress_get','prefix_list','vlan_list',
         'location_list','search_by_name']
meta  = ['mcp_enable_tools','mcp_disable_tools','mcp_list_tools']
missing = [t for t in tools+meta if t not in content]
assert not missing, f'Missing tools: {missing}'
print(f'Criterion 2: PASSED — all 13 tools documented')
"

# Criterion 3: Scope management documented
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
checks = ['mcp_enable_tools', 'mcp_disable_tools', 'mcp_list_tools', 'scope']
missing = [c for c in checks if c not in content]
assert not missing, f'Missing scope terms: {missing}'
print('Criterion 3: PASSED — scope management documented')
"

# Criterion 4: Pagination documented
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
checks = [
    ('LIMIT_DEFAULT' in content or 'default=25' in content, 'default=25'),
    ('LIMIT_MAX' in content or 'max=1000' in content, 'max=1000'),
    ('summarize' in content.lower(), 'summarize-at-100'),
    ('base64' in content.lower(), 'cursor+base64'),
]
for ok, label in checks:
    assert ok, f'Pagination failed: {label}'
print('Criterion 4: PASSED — pagination documented')
"

# Criterion 5: 3 investigation workflows
python -c "
content = open('nautobot-mcp-skill/SKILL.md').read()
wf = ['Workflow 1', 'Workflow 2', 'Workflow 3']
missing = [w for w in wf if w not in content]
assert not missing, f'Missing workflows: {missing}'
print('Criterion 5: PASSED — 3 workflows present')
"

echo ""
echo "=== Phase 4 complete: SKILL.md package verified ==="
```

</action>

<acceptance_criteria>
- All 5 `echo "Criterion N: PASSED"` lines are printed
- No Python assertion errors
- Exit code of entire task is 0
</acceptance_criteria>

---

## Must-Haves (Goal-Backward)

| Must-have | Verified by |
|---|---|
| `nautobot-mcp-skill/` package directory exists at repo root | `test -d nautobot-mcp-skill` |
| `SKILL.md` at package root with 13 tools | Criterion 2 Python assertion |
| Scope management docs (enable/disable/list) | Criterion 3 Python assertion |
| Pagination docs (default=25, max=1000, summarize-at-100, base64 cursor) | Criterion 4 Python assertion |
| 3 investigation workflows with step-by-step tool sequences | Criterion 5 Python assertion |
| `pip install ./nautobot-mcp-skill` succeeds | Criterion 1 |
| SKILL.md readable from installed package | Task 3 acceptance |

---

## File Summary

| File | Action |
|---|---|
| `nautobot-mcp-skill/pyproject.toml` | Create — setuptools build with dynamic version |
| `nautobot-mcp-skill/MANIFEST.in` | Create — includes SKILL.md in sdist |
| `nautobot-mcp-skill/nautobot_mcp_skill/__init__.py` | Create — `__version__ = "0.1.0a0"` |
| `nautobot-mcp-skill/SKILL.md` | Create — full skill reference |
| `.planning/STATE.md` | Update — mark Phase 4 executed |
| `.planning/ROADMAP.md` | Update — mark SKILL-01/02/03 complete |
| `.planning/REQUIREMENTS.md` | Update — mark SKILL-01/02/03 complete |
