# Testing — nautobot-app-mcp-server

> How tests are written, run, and enforced in this project.

---

## Framework

| Concern | Value |
|---|---|
| Test framework | Django `unittest` (Nautobot's standard) |
| Test runner | `nautobot-server test <label>` |
| Coverage tool | `coverage` (handles `.coveragerc`-style config in `pyproject.toml`) |
| CI entry point | `poetry run invoke tests` |

This project does **not** use `pytest` or `unittest` directly — it relies on Nautobot's Django test infrastructure, which provides:
- Transaction-level test isolation
- Automatic database setup/teardown per test run
- Integration with Nautobot's model mixins and base test classes

---

## Running Tests

### Full CI suite

```bash
poetry run invoke tests
```

Runs, in order:
1. `ruff` (lint + format check)
2. `djlint` (Django template linting)
3. `yamllint` (YAML validation)
4. `markdownlint` (Markdown linting)
5. `poetry check` (lockfile validity)
6. `check_migrations` (dry-run migration check)
7. `pylint` (full static analysis)
8. `mkdocs build --strict` (docs build)
9. `validate_app_config` (JSON schema validation)
10. `unittest` with coverage
11. `unittest_coverage` (coverage report)
12. `coverage_lcov` (LCoV format for CI tools)

### Unit tests only

```bash
poetry run invoke unittest
```

With coverage:
```bash
poetry run invoke unittest --coverage
```

With coverage report:
```bash
poetry run invoke unittest --coverage
poetry run invoke unittest-coverage
```

### Individual test runner with options

```bash
# Keep the test DB between runs (faster repeated runs)
poetry run invoke unittest --keepdb

# Fail fast on first failure
poetry run invoke unittest --failfast

# Run only tests matching a pattern
poetry run invoke unittest --pattern "test_mcp*"

# Run in verbose mode
poetry run invoke unittest --verbose

# Skip docs build (used when tests are invoked by `invoke tests` which already built docs)
poetry run invoke unittest --skip-docs-build
```

### Lint only (skip unit tests)

```bash
poetry run invoke tests --lint-only
```

---

## Test File Location

Tests live at:

```
nautobot_app_mcp_server/tests/
```

Currently the directory is minimal — `__init__.py` only:

```
nautobot_app_mcp_server/tests/__init__.py   ← package marker
```

When tests are added, they follow Django's discovery convention: any `test*.py` file in this directory is automatically discovered by `nautobot-server test`.

```
nautobot_app_mcp_server/tests/
├── __init__.py
├── test_mcp_server.py       ← MCP server unit tests
└── test_integration.py     ← integration tests (optional)
```

---

## Test Structure & Patterns

### Basic test file skeleton

Since the app currently has no models, tests will primarily exercise MCP server logic, Nautobot API integration, and configuration.

```python
"""Unit tests for the MCP server module."""

from nautobot.apps.testing import TransactionTestCase
from nautobot.apps import NautobotAppConfig

from nautobot_app_mcp_server import config


class ConfigTestCase(TransactionTestCase):
    """Test NautobotAppMcpServerConfig."""

    def test_config_name(self):
        """App name must match the package."""
        self.assertEqual(config.name, "nautobot_app_mcp_server")

    def test_config_version(self):
        """Version must be a valid semver string."""
        self.assertIsInstance(config.version, str)
        self.assertGreater(len(config.version), 0)

    def test_config_base_url(self):
        """Base URL should be a slug-compatible string."""
        self.assertEqual(config.base_url, "mcp-server")

    def test_required_settings_empty(self):
        """No required settings since there are no models."""
        self.assertEqual(config.required_settings, [])

    def test_default_settings_empty(self):
        """No default settings since there are no models."""
        self.assertEqual(config.default_settings, {})

    def test_searchable_models_empty(self):
        """No searchable models since there are no models."""
        self.assertEqual(config.searchable_models, [])
```

### Using `TransactionTestCase`

Use `from nautobot.apps.testing import TransactionTestCase` (not plain `unittest.TestCase`). This is Nautobot's base test class and provides:

- Automatic database transaction isolation per test
- Nautobot model registry setup
- Plugin loading (important since the app is a plugin)

```python
from nautobot.apps.testing import TransactionTestCase


class MyServerTestCase(TransactionTestCase):
    """Base test case for MCP server tests."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        # Nautobot is fully loaded here

    def tearDown(self):
        """Clean up after tests."""
        # Any mock teardown goes here
        super().tearDown()
```

### Mocking external services

Use `unittest.mock` (Python standard library) for mocking:

```python
from unittest.mock import patch, MagicMock


class NautobotAPITestCase(TransactionTestCase):
    """Tests for Nautobot API integration."""

    @patch("nautobot_app_mcp_server.some_module.NautobotClient")
    def test_client_initialization(self, mock_client_class):
        """NautobotClient should be initialized with correct base URL."""
        mock_instance = MagicMock()
        mock_client_class.return_value = mock_instance

        from nautobot_app_mcp_server.some_module import get_client
        client = get_client(base_url="http://localhost:8080")

        mock_client_class.assert_called_once_with("http://localhost:8080")
        self.assertEqual(client, mock_instance)

    @patch("nautobot_app_mcp_server.some_module.requests.get")
    def test_api_fetch_devices(self, mock_get):
        """Should return device list from Nautobot API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": [{"name": "sw01"}]}
        mock_get.return_value = mock_response

        from nautobot_app_mcp_server.some_module import fetch_devices
        devices = fetch_devices()

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["name"], "sw01")
```

### Testing invoke tasks

Use `invoke.testing.CliRunner` to test invoke task functions:

```python
from invoke.testing import CliRunner
from tasks import ruff


def test_ruff_lint_passes():
    """Ruff lint check should pass when code is clean."""
    runner = CliRunner()
    result = runner.invoke(ruff, ["--fix"])
    # Exit code 0 = success
    assert result.exit_code == 0
```

### Testing exception paths

```python
def test_dbshell_raises_on_unsupported_backend(monkeypatch):
    """dbshell should raise ValueError for unsupported database backends."""
    monkeypatch.setenv("NAUTOBOT_DB_ENGINE", "sqlite3")  # not supported

    from tasks import dbshell
    runner = CliRunner()

    result = runner.invoke(dbshell, ["--query", "SELECT 1"])
    assert result.exit_code != 0
    assert "Unsupported database backend" in result.output
```

---

## Coverage

### Configuration

Coverage is configured in `pyproject.toml`:

```toml
[tool.coverage.run]
disable_warnings = ["already-imported"]
relative_files = true
omit = ["*/tests/*"]
include = ["nautobot_app_mcp_server/*"]
```

- **Omit tests themselves** (`*/tests/*`) — coverage is measured only on application code.
- **Relative file paths** (`relative_files = true`) — ensures consistent paths in CI.
- **Suppress "already-imported" warning** — this fires because Nautobot's core is imported before coverage starts measuring.

### Running coverage

```bash
# Run tests with coverage enabled
poetry run invoke unittest --coverage

# Pretty terminal report
poetry run invoke unittest_coverage

# LCoV format (for CI tools like Codecov)
poetry run invoke coverage-lcov

# XML format (for CI tools)
poetry run invoke coverage-xml
```

### Coverage thresholds

Currently **no minimum coverage percentage is enforced**. However, the project convention (from `docs/dev/contributing.md`) is:
- All new features **must** include unit tests.
- PRs that reduce overall test coverage may be requested to add additional tests.

---

## Test Data & Fixtures

### No factory patterns yet

Since the app has no models, there are no `django_factory` patterns or `FixtureLoader` usages yet. When models are added, follow Nautobot's conventions:

```python
from nautobot.dcim.models import Device, DeviceType, Manufacturer

class DeviceTestCase(TransactionTestCase):
    """Test device-related MCP tools."""

    def setUp(self):
        super().setUp()
        self.manufacturer = Manufacturer.objects.create(name="Acme")
        self.device_type = DeviceType.objects.create(
            manufacturer=self.manufacturer,
            model="Switch-48",
            slug="switch-48",
        )
        self.device = Device.objects.create(
            name="sw01",
            device_type=self.device_type,
            status=Status.objects.get(name="Active"),
        )
```

### Temporary files in tests

Use Python's `tempfile` module for any temporary file operations:

```python
import tempfile
from pathlib import Path


def test_export_config():
    """Config export should write a valid JSON file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "config.json"
        export_config(output_path)
        assert output_path.exists()
        import json
        data = json.loads(output_path.read_text())
        assert "nautobot_app_mcp_server" in data
```

---

## CI Integration

The full test suite is enforced by `.github/workflows/ci.yml` (or equivalent CI config). The `invoke tests` command is the canonical gate:

```bash
# In CI pipeline
poetry install
poetry run invoke tests
```

### Docker-based CI

Tests run **inside Docker containers** (via `invoke` → `docker compose`), not on the host. This ensures:
- Consistent Nautobot version (`3.0.0` by default)
- Consistent Python version (`3.12`)
- Isolated database (PostgreSQL or MySQL via Docker Compose)
- Redis available for Celery workers

To run locally in the same way CI does:
```bash
poetry run invoke tests
```

To run locally on the host (bypass Docker):
```yaml
# invoke.yml
nautobot_app_mcp_server:
  local: true
```

Then:
```bash
poetry run invoke tests
```

---

## Testing Standards (from `docs/dev/contributing.md`)

| Expectation | Rule |
|---|---|
| New features | **Must** include unit tests |
| Bug fixes | **Should** include regression tests |
| Existing tests | **Must not** be broken by a PR |
| Coverage | PRs reducing coverage may be requested to add more tests |
| Local + CI | Tests must pass locally before pushing |

---

## App Config Validation in Tests

The `validate_app_config` task runs as part of the CI suite. It uses `jsonschema` to validate `PLUGINS_CONFIG` against `nautobot_app_mcp_server/app-config-schema.json`:

```bash
poetry run invoke validate-app-config
```

This is not a unit test per se, but it is enforced automatically in CI. If you add new configuration settings, regenerate the schema:

```bash
poetry run invoke generate-app-config-schema
# Review and edit the generated file, then commit
```

---

## No Migrations Pattern

Since this app has no database models, `invoke check-migrations` is a **pass-through** in CI (it will report "no migrations needed"). If you add models in the future:

1. Run `poetry run invoke makemigrations nautobot_app_mcp_server`
2. Commit the generated migration file
3. A second pylint pass will run against `nautobot_app_mcp_server/migrations/` checking for:
   - `new-db-field-with-default`
   - `missing-backwards-migration-callable`
   - `fatal` (any breaking change)

---

## Key Files

| File | Purpose |
|---|---|
| `nautobot_app_mcp_server/tests/__init__.py` | Test package marker (empty) |
| `pyproject.toml` `[tool.coverage.run]` | Coverage configuration |
| `tasks.py` `unittest` task | Runs `nautobot-server test` |
| `tasks.py` `tests` task | Full CI suite entry point |
| `development/nautobot_config.py` | Django settings used during tests (`_TESTING` flag) |
| `docs/dev/contributing.md` | Project-level testing standards |
