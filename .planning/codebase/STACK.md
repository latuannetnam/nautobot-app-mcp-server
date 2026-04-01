# STACK.md — Technology Stack

## Language & Runtime

| Item | Value | Source |
|---|---|---|
| **Language** | Python 3.10 – 3.14 | `pyproject.toml` line 31 |
| **Tested / Dev runtime** | Python 3.12 | `tasks.py` line 57 |
| **WSL VENV** | `/usr` (system site-packages) | CLAUDE.md |

Python version constraints are declared in `pyproject.toml`:

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.15"
```

The Dockerfile defaults to `PYTHON_VER=3.12` and pins the Nautobot base image accordingly.

---

## Package Manager

**Poetry** (`poetry-core >=2.0.0,<3.0.0`) is the exclusive package manager.

```toml
[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
```

Poetry is installed manually inside the Docker image via its official installer script (the base Nautobot image ships an older Poetry version, so the Dockerfile upgrades it):

```dockerfile
# development/Dockerfile lines 29–31
RUN which poetry || curl -sSL https://install.python-poetry.org | python3 - && \
    poetry config virtualenvs.create false
```

Key Poetry commands used in this project:

```bash
# Install deps after lockfile changes
poetry lock && poetry install

# Run any command inside the venv
poetry run <command>

# Shell (activates venv, clears WSL VIRTUAL_ENV)
unset VIRTUAL_ENV && cd /home/latuan/.../nautobot-app-mcp-server && poetry shell
```

Lockfile: `poetry.lock` (committed to repo).

---

## Core Dependency: Nautobot

```toml
[tool.poetry.dependencies]
nautobot = ">=3.0.0,<4.0.0"
```

The app is a **Nautobot App** (plugin). It inherits from `NautobotAppConfig` (the Nautobot plugin API) in `nautobot_app_mcp_server/__init__.py` (lines 11–26). It has **no database models** — see CLAUDE.md's "No Database Models" note. The app is declared in `PLUGINS` in `development/nautobot_config.py` (line 122):

```python
PLUGINS = ["nautobot_app_mcp_server"]
```

The Nautobot version used in the dev stack is configured in `tasks.py` (line 55):
```python
"nautobot_ver": "3.0.0",
```

The Dockerfile resolves the exact Nautobot version at build time:
```dockerfile
RUN if [ -z "${CI+x}" ]; then \
    INSTALLED_NAUTOBOT_VER=$(pip show nautobot | grep "^Version" | sed "s/Version: //"); \
    poetry add --lock nautobot@${INSTALLED_NAUTOBOT_VER} --python ${PYTHON_VER} || \
    poetry add --lock git+https://github.com/nautobot/nautobot.git#${NAUTOBOT_VER} --python ${PYTHON_VER}; fi
```

This means `invoke lock --constrain-nautobot-ver` pins the lockfile to the exact version from the Docker base image, avoiding mismatches between what's installed in the container and what the lockfile specifies.

---

## Dev Dependencies

Declared in `pyproject.toml` under `[tool.poetry.group.dev.dependencies]` (lines 35–54):

| Package | Purpose |
|---|---|
| `coverage` | Code coverage reporting |
| `django-debug-toolbar` | Django debug toolbar in dev |
| `invoke` | Task runner (the `tasks.py` framework) |
| `ipython` | Enhanced Python REPL |
| `pylint` | Code analysis |
| `pylint-django >=2.5.4` | Django-aware Pylint plugin |
| `pylint-nautobot >=0.3.1` | Nautobot-aware Pylint plugin |
| `ruff = 0.5.5` | Linter/formatter (flake8, isort, bandit, pydocstyle) |
| `yamllint` | YAML linting |
| `toml` | TOML file parsing |
| `pymarkdownlnt ~0.9.30` | Markdown linting |
| `Markdown` | Markdown processing |
| `towncrier >=23.6.0,<=24.8.0` | Changelog/release notes |
| `to-json-schema` | JSON schema generation |
| `jsonschema` | JSON schema validation |
| `djlint >=1.36.4,<2.0.0` | Django template linting |
| `djhtml >=3.0.8,<4.0.0` | Django HTML formatter |
| `tomli` (python < 3.11) | `tomllib` stdlib backport |

---

## Docs Dependencies

Declared in `pyproject.toml` under `[tool.poetry.group.docs.dependencies]` (lines 56–69):

| Package | Purpose |
|---|---|
| `markdown-version-annotations = 1.0.1` | Render markdown annotations in release notes |
| `mkdocs = 1.6.0` | Docs site generator |
| `mkdocs-material = 9.5.32` | Material theme for MkDocs |
| `mkdocstrings = 0.25.2` | Autogenerate API docs from docstrings |
| `mkdocstrings-python = 1.10.8` | Python plugin for mkdocstrings |
| `mkdocs-autorefs = 1.2.0` | Auto reference links in docs |
| `griffe = 1.1.1` | Library used by mkdocstrings for Python inspection |
| `mkdocs-glightbox = 0.5.2` | Image lightbox in docs |

Built docs are served at `http://localhost:8001` in dev (via `invoke docs`) and embedded in Nautobot at `/static/nautobot_app_mcp_server/docs/` (included in the package via `pyproject.toml` lines 25–28).

---

## Docker / Dev Environment

### Base Image

```dockerfile
# development/Dockerfile line 16
FROM ghcr.io/nautobot/nautobot-dev:${NAUTOBOT_VER}-py${PYTHON_VER}
```

This is the official Nautobot development Docker image from GitHub Container Registry, which includes most CI dependencies already.

### Services (Docker Compose)

Files: `development/docker-compose.base.yml`, `.dev.yml`, `.postgres.yml`, `.redis.yml`, `.mysql.yml`

The invoke namespace in `tasks.py` (lines 60–65) sets the compose file order:
```python
"compose_files": [
    "docker-compose.base.yml",
    "docker-compose.redis.yml",
    "docker-compose.postgres.yml",   # or docker-compose.mysql.yml
    "docker-compose.dev.yml",
],
```

| Service | Image | Notes |
|---|---|---|
| `nautobot` | built from `Dockerfile` | Django dev server on `:8080` |
| `worker` | same image | Celery worker (`nautobot-server celery worker`) |
| `beat` | same image | Celery beat scheduler |
| `db` | `postgres:17-alpine` (default) | PostgreSQL 17; also supports `mysql:lts` |
| `redis` | `redis:6-alpine` | Redis 6 with AOF and password auth |

### Environment Files

| File | Purpose |
|---|---|
| `development/development.env` | Non-secret env vars (debug on, ports, DB name/user) |
| `development/creds.env` | Secrets (passwords, secret keys, API tokens) — gitignored |
| `development/creds.example.env` | Template for `creds.env` |

---

## Configuration (nautobot_config.py)

File: `development/nautobot_config.py`

Key settings derived from environment variables:

```python
# Database (PostgreSQL default; MySQL via NAUTOBOT_DB_ENGINE)
nautobot_db_engine = os.getenv("NAUTOBOT_DB_ENGINE", "django.db.backends.postgresql")
DATABASES = {
    "default": {
        "NAME": os.getenv("NAUTOBOT_DB_NAME", "nautobot"),
        "USER": os.getenv("NAUTOBOT_DB_USER", ""),
        "PASSWORD": os.getenv("NAUTOBOT_DB_PASSWORD", ""),
        "HOST": os.getenv("NAUTOBOT_DB_HOST", "localhost"),
        "PORT": os.getenv("NAUTOBOT_DB_PORT", "5432"),  # 3306 for MySQL
        "CONN_MAX_AGE": int(os.getenv("NAUTOBOT_DB_TIMEOUT", "300")),
        "ENGINE": nautobot_db_engine,
    }
}
```

Redis settings are inherited from Nautobot core defaults (`nautobot.core.settings`).

Debug toolbar is conditionally enabled in the config (lines 17–22):
```python
if DEBUG and not _TESTING:
    DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda _request: True}
    INSTALLED_APPS.append("debug_toolbar")
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")
```

---

## Code Quality Tools

| Tool | Config location | Command |
|---|---|---|
| **Ruff** 0.5.5 | `pyproject.toml` `[tool.ruff]` | `invoke ruff [--fix]` |
| **Pylint** | `pyproject.toml` `[tool.pylint.master]` | `invoke pylint` |
| **yamllint** | `tasks.py` `yamllint` task | `invoke yamllint` |
| **djlint** | `pyproject.toml` `[tool.djlint]` | `invoke lint` (also runs djhtml) |
| **markdownlint** | `pyproject.toml` `[tool.pymarkdown]` | `invoke markdownlint [--fix]` |
| **Coverage** | `pyproject.toml` `[tool.coverage.run]` | `invoke coverage` |
| **Towncrier** | `pyproject.toml` `[tool.towncrier]` | `invoke generate-release-notes` |

**Pylint score must remain 10.00/10** per CLAUDE.md.

Ruff lint rules enabled: `D` (pydocstyle), `F/E/W` (flake8), `S` (bandit), `I` (isort).

Pylint loads: `pylint_django` and `pylint_nautobot` plugins (line 77).

---

## Changelog / Release Management

Towncrier manages release notes under `changes/` directory. Fragment directories:

- `changes/added/`, `changes/changed/`, `changes/fixed/`, `changes/removed/`, `changes/breaking/`, `changes/deprecated/`, `changes/security/`, `changes/documentation/`, `changes/dependencies/`, `changes/housekeeping/`

Files named `{issue_number}.{type}.md` (e.g., `42.added.md`). Release notes built into `docs/admin/release_notes/version_X.Y.md` via:
```bash
poetry run towncrier build
```

---

## Invoke Task Framework

File: `tasks.py`

Tasks are registered via the custom `@task` decorator (line 95) which wraps `invoke.task` and adds each function to the `namespace` collection.

Configuration is stored in the `namespace` object (lines 51–69), which can be overridden via `invoke.yml` or environment variables prefixed `INVOKE_NAUTOBOT_APP_MCP_SERVER_`.

Notable tasks:

| Task | Command | Purpose |
|---|---|---|
| `invoke start` | `docker compose up --detach` | Start dev stack |
| `invoke tests` | runs all linters + unit tests | Full CI pipeline |
| `invoke lock [--constrain-nautobot-ver]` | `poetry lock` | Generate `poetry.lock` |
| `invoke build` | `docker compose build` | Build Docker image |
| `invoke cli` | `docker compose exec nautobot bash` | Shell into container |
| `invoke pylint` | Pylint + migrations checker | Lint with Django awareness |
| `invoke mkdocs` / `invoke docs` | `mkdocs serve` | Build/serve docs |
| `invoke dbshell` | `psql` / `mysql` in `db` container | DB CLI |
| `invoke backup-db` / `invoke import-db` | `pg_dump` / `pg_restore` | DB backup/restore |
| `invoke unittest [--coverage]` | `nautobot-server test` | Run tests |
| `invoke generate-release-notes` | `towncrier build` | Build changelog |
| `invoke validate-app-config` | `nbshell` with app schema | Validate `PLUGINS_CONFIG` schema |

---

## Static Files / Packaging

The built MkDocs site is embedded in the package distribution:
```toml
include = [
    { path = "nautobot_app_mcp_server/static/nautobot_app_mcp_server/docs/**/*", format = ["sdist", "wheel"] }
]
```

This allows `nautobot-server test` to serve the docs without a separate docs container.
