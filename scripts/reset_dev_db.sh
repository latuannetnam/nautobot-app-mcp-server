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
CREDS_FILE="$PROJECT_ROOT/development/creds.env"
if [[ ! -f "$CREDS_FILE" ]]; then
    echo "[ERROR] $CREDS_FILE not found — have you run 'poetry run invoke start'?"
    exit 1
fi
source "$CREDS_FILE"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nautobot-app-mcp-server}"
CONTAINER_NAUTOBOT="${COMPOSE_PROJECT_NAME}-nautobot-1"
CONTAINER_DB="${COMPOSE_PROJECT_NAME}-db-1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "[$(date +%H:%M:%S)] $*"
}

container_exec() {
    docker exec "$CONTAINER_NAUTOBOT" nautobot-server "$@"
}

db_exec() {
    docker exec "$CONTAINER_DB" psql -U postgres -t -c "$1"
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

log "Stopping Celery workers..."
docker compose stop worker beat 2>/dev/null || true

# ---------------------------------------------------------------------------
# Reset the database
# ---------------------------------------------------------------------------

log "Dropping and recreating the database..."
docker exec "$CONTAINER_DB" psql -U postgres -c "DROP DATABASE IF EXISTS nautobot;" 2>/dev/null || true
docker exec "$CONTAINER_DB" psql -U postgres -c "CREATE DATABASE nautobot;" 2>/dev/null || true

log "Running migrations..."
container_exec migrate --noinput

# Recreate superuser (if not exists)
log "Ensuring superuser exists..."
container_exec shell -c "
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
docker compose restart nautobot worker beat

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
