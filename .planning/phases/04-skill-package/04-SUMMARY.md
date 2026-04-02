---
phase: 04-skill-package
plan: "01"
subsystem: documentation
tags: [mcp, skill-package, setuptools, python-package]

# Dependency graph
requires:
  - phase: 03-core-read-tools
    provides: 10 core tools, 3 meta tools, pagination, session management
provides:
  - nautobot-mcp-skill pip package with SKILL.md
affects: [05-deployment]

# Tech tracking
tech-stack:
  added: [setuptools, python-packaging]
  patterns: [standalone pip package, dynamic version from attr, MANIFEST.in + package-data]

key-files:
  created:
    - nautobot-mcp-skill/SKILL.md
    - nautobot-mcp-skill/pyproject.toml
    - nautobot-mcp-skill/MANIFEST.in
    - nautobot-mcp-skill/nautobot_mcp_skill/__init__.py
    - nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md
  modified: []

key-decisions:
  - "SKILL.md lives at package root AND inside nautobot_mcp_skill/ (wheel globs only match inside package dirs)"
  - "setuptools `package-data` for wheel inclusion; `include-package-data` + `MANIFEST.in` for sdist"
  - "setuptools `dynamic.version = {attr}` reads `__version__` from installed __init__.py"

patterns-established:
  - "Pattern: standalone pip package at repo root with zero runtime dependencies"
  - "Pattern: dynamic version from package attr for single-source-of-truth versioning"

requirements-completed: [SKILL-01, SKILL-02, SKILL-03]

# Metrics
duration: 8 min
completed: 2026-04-02
---

# Phase 4 Plan 01: SKILL.md Package

**SKILL.md pip package `nautobot-mcp-skill` v0.1.0a0 — AI agent capability reference with 13 tools, pagination docs, scope management, and 3 investigation workflows**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-02T08:22:00Z
- **Completed:** 2026-04-02T08:30:00Z
- **Tasks:** 4
- **Files modified:** 5

## Accomplishments
- `nautobot-mcp-skill/` pip package created at repo root (zero runtime dependencies)
- SKILL.md with all 13 tools documented: 10 core tools + 3 meta tools
- Pagination fully documented: default=25, max=1000, summarize-at-100, base64 cursor
- Scope management documented: core/dcim/ipam tiers, hierarchy, session persistence
- 3 investigation workflows: device investigation, IP by prefix, interface exploration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Package Skeleton** — `48aae6d` (feat)
2. **Task 2: Write SKILL.md** — `88afaab` (docs)
3. **Task 3: Verify Package Installs** — `b20cb2c` (fix)
4. **Task 4: Final Verification** — verification only (no commit needed)

**Plan metadata:** pending gsd-tools metadata commit

## Files Created/Modified
- `nautobot-mcp-skill/pyproject.toml` — setuptools build, dynamic version from attr, package-data
- `nautobot-mcp-skill/MANIFEST.in` — includes SKILL.md in sdist
- `nautobot-mcp-skill/nautobot_mcp_skill/__init__.py` — `__version__ = "0.1.0a0"`
- `nautobot-mcp-skill/SKILL.md` — 174-line AI agent skill reference (repo root, for sdist)
- `nautobot-mcp-skill/nautobot_mcp_skill/SKILL.md` — copy for wheel inclusion

## Decisions Made

- **SKILL.md in two places:** `MANIFEST.in` includes SKILL.md from repo root (sdist). For wheels, `package-data` globs are relative to the package dir, so SKILL.md must also exist inside `nautobot_mcp_skill/`. Both are kept in sync (same content, two copies).
- **setuptools `package-data` over `include-package-data` alone:** `include-package-data = true` only helps sdist via MANIFEST.in; wheels need explicit `package-data` globs to pick up files inside package dirs.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

**Blocking bug discovered during Task 3:** Wheel built without SKILL.md despite `MANIFEST.in include SKILL.md`.
- **Root cause:** `MANIFEST.in` only controls sdist. `include-package-data = true` doesn't help wheels. `package-data` globs are relative to the package subdirectory — not the repo root.
- **Fix:** Added `package-data = {nautobot_mcp_skill = ["SKILL.md"]}` to pyproject.toml AND copied SKILL.md into `nautobot_mcp_skill/` so the glob resolves.
- **Committed in:** `b20cb2c` (Task 3 commit)

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Phase 4 (SKILL.md Package) is complete. Phase 5 (Deployment) is next. The skill package is ready for AI agents to consume via `pip install ./nautobot-mcp-skill`.

---
*Phase: 04-skill-package*
*Completed: 2026-04-02*
