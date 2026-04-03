#!/usr/bin/env bash
# =============================================================================
# Reset the dev Nautobot database to a clean state and optionally re-import
# production data.
#
# Usage:
#   ./scripts/reset_dev_db.sh           # Reset to empty dev DB
#   ./scripts/reset_dev_db.sh import    # Reset + re-import from production
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Load dev credentials
# ---------------------------------------------------------------------------
DEV_ENV_FILE="$PROJECT_ROOT/development/development.env"
CREDS_FILE="$PROJECT_ROOT/development/creds.env"
if [[ ! -f "$DEV_ENV_FILE" ]]; then
    echo "[ERROR] $DEV_ENV_FILE not found — have you run 'poetry run invoke start'?"
    exit 1
fi
if [[ ! -f "$CREDS_FILE" ]]; then
    echo "[ERROR] $CREDS_FILE not found — have you run 'poetry run invoke start'?"
    exit 1
fi
source "$DEV_ENV_FILE"
source "$CREDS_FILE"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nautobot-app-mcp-server}"
DEV_DIR="$PROJECT_ROOT/development"
CONTAINER_NAUTOBOT="${COMPOSE_PROJECT_NAME}-nautobot-1"
CONTAINER_DB="${COMPOSE_PROJECT_NAME}-db-1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "[$(date +%H:%M:%S)] $*"
}

compose() {
    docker compose \
        --project-directory "$DEV_DIR" \
        -f "$DEV_DIR/docker-compose.base.yml" \
        -f "$DEV_DIR/docker-compose.redis.yml" \
        -f "$DEV_DIR/docker-compose.postgres.yml" \
        -f "$DEV_DIR/docker-compose.dev.yml" \
        "$@"
}

container_exec() {
    docker exec "$CONTAINER_NAUTOBOT" nautobot-server "$@"
}

db_exec() {
    docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
        psql -U "$NAUTOBOT_DB_USER" -c "$1"
}

log "Checking containers..."
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAUTOBOT}$"; then
    log "[ERROR] Nautobot container '$CONTAINER_NAUTOBOT' is not running."
    log "        Start the dev stack first: poetry run invoke start"
    exit 1
fi

# ---------------------------------------------------------------------------
# Stop Celery workers (release DB locks)
# ---------------------------------------------------------------------------

log "Stopping services (releasing DB connections)..."
compose stop nautobot worker beat 2>/dev/null || true

# ---------------------------------------------------------------------------
# Reset the database
# ---------------------------------------------------------------------------

log "Dropping and recreating the database..."
# Terminate all remaining connections via the 'postgres' helper DB.
docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
    psql -U "$NAUTOBOT_DB_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$NAUTOBOT_DB_NAME';"
# Drop and recreate via the 'postgres' helper DB so we never hold a connection to the target.
docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
    psql -U "$NAUTOBOT_DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $NAUTOBOT_DB_NAME;"
docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
    psql -U "$NAUTOBOT_DB_USER" -d postgres -c "CREATE DATABASE $NAUTOBOT_DB_NAME;"

log "Running migrations..."
container_exec migrate --noinput

# Recreate superuser (if not exists)
log "Ensuring superuser exists..."
container_exec shell --command "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$NAUTOBOT_SUPERUSER_NAME').exists():
    User.objects.create_superuser(
        '$NAUTOBOT_SUPERUSER_NAME',
        '$NAUTOBOT_SUPERUSER_EMAIL',
        '$NAUTOBOT_SUPERUSER_PASSWORD'
    )
    print('Superuser created')
else:
    print('Superuser already exists')
" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Restart services
# ---------------------------------------------------------------------------

log "Restarting services..."
compose restart nautobot worker beat

log "Waiting for Nautobot to be healthy..."
for i in {1..30}; do
    if docker exec "$CONTAINER_NAUTOBOT" nautobot-server health_check &>/dev/null; then
        log "Nautobot is healthy"
        break
    fi
    if [[ $i -eq 30 ]]; then
        log "[ERROR] Nautobot failed to become healthy after 150s"
        exit 1
    fi
    sleep 5
done

# ---------------------------------------------------------------------------
# Verify the database is clean
# ---------------------------------------------------------------------------

log "Verifying database is clean..."
PASS=true

# Helper: query a table and check row count; log FAIL if non-zero or table missing.
# Suppresses psql errors so missing tables are treated as 0, not script failures.
verify_zero() {
    local table="$1"
    local result
    # Use a subshell to suppress 'set -e' from psql ERROR exit codes.
    result=$( (docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
        psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -t -c \
        "SELECT COUNT(*) FROM $table;" 2>&1 || true) | tr -d '[:space:]')
    # If table doesn't exist psql outputs an error line; detect that and treat as 0.
    if [[ "$result" =~ ^ERROR ]] || [[ "$result" =~ doesnotexist ]]; then
        log "  [OK]  $table = 0 (table not yet created by migrations)"
    elif [[ -z "$result" ]] || [[ "$result" == "0" ]]; then
        log "  [OK]  $table = 0"
    else
        log "  [FAIL] $table = $result (expected 0)"
        PASS=false
    fi
}

# Helper: check a table exists.
verify_exists() {
    local table="$1"
    local exists
    exists=$(docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
        psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -t -c \
        "SELECT to_regclass('$table');" 2>&1 | tr -d '[:space:]')
    if [[ -n "$exists" && "$exists" != "" ]]; then
        log "  [OK]  $table exists"
    else
        log "  [FAIL] $table missing"
        PASS=false
    fi
}

verify_zero "dcim_device"
verify_zero "ipam_prefix"
verify_zero "ipam_ipaddress"
verify_zero "ipam_vlan"
verify_zero "circuits_circuit"
verify_zero "virtualization_vm"
verify_zero "extras_configcontext"
verify_exists "dcim_device"
verify_exists "ipam_prefix"
verify_exists "auth_user"

if [[ "$PASS" == "false" ]]; then
    log "[FAIL] Database verification failed — data may still exist."
    exit 1
fi

log "Database verification passed."

# ---------------------------------------------------------------------------
# Optional: re-import from production
# ---------------------------------------------------------------------------

if [[ "${1:-}" == "import" ]]; then
    if [[ ! -f "$PROJECT_ROOT/nautobot_import.env" ]]; then
        log "[WARN] nautobot_import.env not found — skipping import"
        log "       Copy nautobot_import.env.example to nautobot_import.env and re-run with 'import'"
    else
        log "Running production data import..."
        docker exec \
            -e NAUTOBOT_CONFIG=/source/development/nautobot_config.py \
            "$CONTAINER_NAUTOBOT" \
            python /source/nautobot_app_mcp_server/management/commands/import_production_data.py
    fi
else
    log "Dev DB reset complete. To import production data, run:"
    log "  ./scripts/reset_dev_db.sh import"
fi

log "Done."
