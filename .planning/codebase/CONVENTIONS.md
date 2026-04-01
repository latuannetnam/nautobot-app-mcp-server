# Code Conventions — nautobot-app-mcp-server

> How this project is styled, structured, and kept healthy. Rules enforced by CI.

---

## Python Version & Runtime

| Concern | Value |
|---|---|
| Minimum Python | `>=3.10,<3.15` |
| Target (development) | `3.12` |
| Enforcement | `pyproject.toml` `tool.poetry.dependencies.python` |

---

## Toolchain

Every tool has its config declared inline in `pyproject.toml`. **Do not add external config files** (e.g. `.pylintrc`, `.ruff.toml`) unless a tool requires it.

| Tool | Purpose | Config location |
|---|---|---|
| **Ruff** | Formatting + linting (PEP 8, isort, flake8, bandit) | `pyproject.toml [tool.ruff]` |
| **Pylint** (+ `pylint-nautobot`, `pylint-django`) | Deep static analysis, Django-aware | `pyproject.toml [tool.pylint.*]` |
| **yamllint** | YAML file linting | CLI invocation in `tasks.py` |
| **djlint** | Django template linting | `pyproject.toml [tool.djlint]` |
| **djhtml** | Django template auto-formatting | CLI invocation in `tasks.py` |
| **pymarkdownlnt** | Markdown linting | `pyproject.toml [tool.pymarkdown]` |
| **Towncrier** | Changelog / release notes | `pyproject.toml [tool.towncrier]` |

### Running the Full Lint Suite

```bash
# All at once (used by CI)
poetry run invoke tests

# Individual tools
poetry run invoke ruff           # lint + format check
poetry run invoke ruff --fix     # auto-fix
poetry run invoke pylint
poetry run invoke yamllint
poetry run invoke djlint
poetry run invoke djhtml         # auto-format templates
poetry run invoke markdownlint
```

---

## Ruff

**Config** (`pyproject.toml`):
```toml
[tool.ruff]
line-length = 120
target-version = "py38"

[tool.ruff.lint]
select = ["D", "F", "E", "W", "S", "I"]
ignore = ["D203", "D212", "D213", "D401", "D407", "D416", "E501"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"nautobot_app_mcp_server/migrations/*" = ["D"]
"nautobot_app_mcp_server/tests/*" = ["D", "S"]
```

### What Ruff checks

| Rule prefix | What it catches |
|---|---|
| `F`, `E`, `W` | Pyflakes / pycodestyle (unused imports, undefined names, etc.) |
| `I` | isort import ordering |
| `D` | pydocstyle (missing / malformed docstrings) |
| `S` | bandit (security: hardcoded passwords, SQL injection, etc.) |

### Key Ruff settings

- **Line length**: `120` (not the default 88). Override in code with `# noqa: E501` if absolutely necessary, but prefer wrapping.
- **Google docstring convention** — the project uses Google-style docstrings.
- **D401 (imperative mood first line) is ignored** — the team does not require this style.
- **D documents not required** for migrations or test files (`per-file-ignores`).
- **`--fix`** is safe to run in CI or locally; ruff will auto-fix everything it can.

### Formatting with Ruff

```bash
# Check (non-destructive)
poetry run invoke ruff

# Auto-fix
poetry run invoke ruff --fix
```

---

## Pylint

**Critical rule**: Pylint score must remain **10.00/10** at all times. Any PR that drops the score must be fixed before merging.

**Config** (`pyproject.toml`):
```toml
[tool.pylint.master]
load-plugins = "pylint_django, pylint_nautobot"
ignore = ".venv"

[tool.pylint.basic]
no-docstring-rgx = "^(_|test_|Meta$)"

[tool.pylint.messages_control]
disable = """
    line-too-long,
    too-many-positional-arguments,
    nb-warn-dunder-filter-field,
    nb-no-search-function,
    nb-no-char-filter-q,
"""

[tool.pylint.miscellaneous]
notes = """
    FIXME,
    XXX,
"""
```

### Notable Pylint settings

- **`no-docstring-rgx`**: `_`-prefixed methods, `test_`-prefixed functions, and `Meta` inner classes are exempt from docstring requirements. This aligns with the `ruff` `D` rule exemptions.
- **TODO comments**: `FIXME` and `XXX` are permitted and do not fail the build.
- **Disabled checks**: `line-too-long` (handled by Ruff), `too-many-positional-arguments` (Django signals often require many args), and three Nautobot-specific `nb-*` codes.
- **Django-aware**: `pylint_django` and `pylint_nautobot` plugins suppress false positives from Django ORM patterns.

### Running Pylint

```bash
poetry run invoke pylint
```

The `tasks.py` pylint task uses a special init hook to load Nautobot before scanning:
```python
base_pylint_command = (
    'pylint --verbose '
    '--init-hook "import nautobot; nautobot.setup()" '
    '--rcfile pyproject.toml'
)
```

### Migrations Pylint (if migrations exist)

If `nautobot_app_mcp_server/migrations/` exists, a second pylint pass runs with `pylint_django.checkers.migrations` enabled, checking only for:
- `fatal` — new model fields without defaults
- `new-db-field-with-default` — missing callable defaults
- `missing-backwards-migration-callable`

---

## Docstrings

- **Convention**: Google style (set in `ruff [tool.ruff.lint.pydocstyle]`)
- **Required on**: all public modules, classes, methods, and functions
- **Not required on**: private helpers (`_func`), test functions (`test_*`), inner `Meta` classes
- **D401 ignored**: first line imperative mood is not enforced

```python
"""Module or file-level summary.

More detailed explanation if needed.

Args:
    context: Description of the first argument.
    foo: Description of the second argument.

Returns:
    What is returned.

Raises:
    ValueError: When this error occurs.
"""
```

---

## Naming Conventions

| Object | Convention | Example |
|---|---|---|
| Modules | `snake_case.py` | `nautobot_app_mcp_server/__init__.py` |
| Classes | `PascalCase` | `NautobotAppMcpServerConfig` |
| Functions / variables | `snake_case` | `is_truthy`, `compose_command_tokens` |
| Constants | `SCREAMING_SNAKE_CASE` | `LOG_LEVEL`, `NAUTOBOT_VER` |
| Private helpers | `_leading_underscore` | `_await_healthy_container()` |
| Django settings | `SCREAMING_SNAKE` inherited from Nautobot | `PLUGINS`, `DATABASES`, `MIDDLEWARE` |
| Config variables (invoke) | `snake_case` | `compose_dir`, `compose_files`, `nautobot_ver` |
| Package name | `snake_case` | `nautobot_app_mcp_server` |
| App `name` in config | `snake_case` | `"nautobot_app_mcp_server"` |
| App `base_url` | `kebab-case` or `slug` | `"mcp-server"` |

### `NautobotAppConfig` fields

```python
class NautobotAppMcpServerConfig(NautobotAppConfig):
    name = "nautobot_app_mcp_server"          # matches package dir name
    verbose_name = "Nautobot App MCP Server"
    version = __version__                     # from importlib.metadata
    author = "Le Anh Tuan"
    description = "Nautobot MCP Server App."
    base_url = "mcp-server"
    required_settings = []                    # empty (no DB models)
    default_settings = {}                    # empty
    docs_view_name = "plugins:nautobot_app_mcp_server:docs"
    searchable_models = []                   # empty (no models)

config = NautobotAppMcpServerConfig  # pylint:disable=invalid-name
```

---

## Imports & Ordering

Enforced by Ruff (`I` rules / isort). Standard order within a file:

1. `"""docstring"""` (if file-level docstring)
2. `from __future__ import` annotations (if needed)
3. Standard library
4. Third-party packages
5. Django / Nautobot
6. Local application imports

Use `from nautobot.apps import NautobotAppConfig` (not `nautobot.core`).

```python
"""Module docstring."""

import os
import re
from pathlib import Path
from time import sleep

from invoke.collection import Collection
from invoke.exceptions import Exit, UnexpectedExit
from invoke.tasks import task as invoke_task

from nautobot.apps import NautobotAppConfig
```

---

## Error Handling

### Raising errors in `tasks.py`

Use **`Exit`** (from `invoke.exceptions`) for task-level failures that should produce a non-zero exit code:

```python
from invoke.exceptions import Exit

raise Exit(code=1)
raise Exit("Error message here")
```

Use **`raise ValueError`** for argument validation that cannot proceed at all:

```python
if input_file and query:
    raise ValueError("Cannot specify both, `input_file` and `query` arguments")
if output_file and not (input_file or query):
    raise ValueError("`output_file` argument requires `input_file` or `query` argument")
```

### Raising errors in app code

Standard Python exceptions. Document expected exceptions in docstrings:

```python
"""Fetch Nautobot objects.

Args:
    model_class: The Nautobot model class.

Raises:
    RuntimeError: When the MCP server is not initialized.
"""
```

### `warn=True` in invoke task runners

When running external commands with `run_command()` or `docker_compose()` inside an invoke task, use `warn=True` and handle the exit code manually — this lets the task aggregate failures and exit once at the end rather than crashing immediately:

```python
def ruff(context, ...):
    if not run_command(context, command, warn=True):
        exit_code = 1
    ...
    if exit_code != 0:
        raise Exit(code=exit_code)
```

---

## Type Hints

- Use `from __future__ import annotations` (PEP 563) to avoid forward-reference string quotes.
- Use `# type: ignore` comments for third-party stubs that don't type cleanly (seen in `development/app_config_schema.py`).
- Pylint `init-hook` loads Nautobot before scanning so type inference works across the codebase.

```python
from __future__ import annotations

def docker_compose(context, command, **kwargs):
    # types declared inline
    ...
```

---

## Logging

Logging is configured in `development/nautobot_config.py` using Python's standard `logging` module. The pattern used:

```python
LOG_LEVEL = "DEBUG" if DEBUG else "INFO"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "normal": {...},
        "verbose": {...},  # includes filename and funcName
    },
    "handlers": {
        "normal_console": {...},
        "verbose_console": {...},
    },
    "loggers": {
        "django": {"handlers": ["normal_console"], "level": "INFO"},
        "nautobot": {
            "handlers": ["verbose_console" if DEBUG else "normal_console"],
            "level": LOG_LEVEL,
        },
    },
}
```

---

## Django App Structure (No Models)

This app intentionally ships with **no database models**. The following Django app components are absent:

```
models.py      ← absent
filters.py     ← absent
forms.py       ← absent
tables.py      ← absent
views.py       ← absent
urls.py        ← absent
api/serializers.py  ← absent
api/views.py        ← absent
api/urls.py         ← absent
navigation.py       ← absent
migrations/         ← absent
```

The app **only** contains:
- `nautobot_app_mcp_server/__init__.py` — `NautobotAppMcpServerConfig`
- `nautobot_app_mcp_server/tests/__init__.py` — test package marker

When adding MCP server logic, it belongs directly in `nautobot_app_mcp_server/` as new modules. Do not create empty model files to mimic a standard Nautobot app structure.

---

## Changelog / Release Notes

Managed by **Towncrier**. Never edit release notes files directly.

| Directory | Fragment type | Example filename |
|---|---|---|
| `changes/added/` | New feature | `42.added.md` |
| `changes/changed/` | Behavior change | `42.changed.md` |
| `changes/fixed/` | Bug fix | `42.fixed.md` |
| `changes/removed/` | Removed feature | `42.removed.md` |
| `changes/breaking/` | Breaking change | `42.breaking.md` |
| `changes/deprecated/` | Deprecation notice | `42.deprecated.md` |
| `changes/security/` | Security fix | `42.security.md` |
| `changes/documentation/` | Docs-only change | `42.documentation.md` |
| `changes/dependencies/` | Dependency change | `42.dependencies.md` |
| `changes/housekeeping/` | Internal housekeeping | `42.housekeeping.md` |

### Fragment file format

Each file contains **plain text**, 1+ lines, past tense, complete sentences:

```markdown title="changes/42.added.md"
Added MCP server initialization handler.
Added support for Nautobot object introspection.
```

**Rules**:
- One entry per line; multiple lines in the same file = multiple release note entries.
- Fragment files are **consumed** by Towncrier during release and deleted.
- Commit messages follow conventional format: `type: description` (e.g., `added: implement MCP tool registry`).

---

## Git Workflow

- **Branches**: `feature/...`, `fix/...`, `docs/...`
- **Commits**: conventional format — `type: description`
- **Before pushing**: run `poetry run invoke tests`
- **Before opening PR**: run `poetry run invoke lint` (includes ruff, djlint, yamllint, markdownlint, pylint, mkdocs)
- **PRs must not break existing tests** or reduce coverage.

---

## Docker / Development Environment

- **Python package manager**: Poetry exclusively. **Never use `pip`** directly.
- **Dev tools**: all run via `poetry run invoke <task>` or `poetry run <tool>`.
- **`VIRTUAL_ENV=/usr`** is set in WSL shell profiles — always `unset VIRTUAL_ENV` before Poetry commands.
- **Virtualenv**: created in-project at `.venv/` (`poetry config virtualenvs.in-project true`).

---

## No-DB Model Pattern

Since this app has no models, certain boilerplate decisions apply:

- `required_settings = []` and `default_settings = {}` in `NautobotAppConfig`
- `searchable_models = []`
- `migrations/` directory does not exist (no `makemigrations` output)
- `check_migrations` task in CI will pass trivially
- If migrations are ever needed in the future, use `invoke makemigrations nautobot_app_mcp_server`

---

## Code Quality Non-Negotiables

1. **Pylint 10.00** — never merged below this.
2. **All `invoke tests` checks pass** before any PR.
3. **No bare `except:`** — always catch specific exceptions.
4. **No `# noqa: E501`** unless absolutely necessary; prefer wrapping to 120 chars.
5. **Towncrier fragments** required for every PR to `develop` or `next`.
6. **Poetry-only** for dependency management — no pip.
7. **No models** unless explicitly required; if models are added, full boilerplate (filters, forms, serializers) must follow Nautobot app patterns.
