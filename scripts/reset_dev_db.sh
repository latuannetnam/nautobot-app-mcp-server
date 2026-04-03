#!/usr/bin/env bash
# =============================================================================
# Reset the dev Nautobot database to a clean state and optionally fetch from
# production and/or import into the dev DB.
#
# Two-Phase Workflow:
#   Phase 1 – Fetch: Pull data from production via REST API → save to JSON cache
#              (Runs on host, no Docker needed)
#   Phase 2 – Import: Load cached JSON → bulk-insert into dev DB
#              (Runs inside Nautobot container, requires clean DB)
#
# Usage (interactive):
#   ./scripts/reset_dev_db.sh              # Show menu
#
# Usage (CLI flags):
#   ./scripts/reset_dev_db.sh --reset              # Reset DB only
#   ./scripts/reset_dev_db.sh --fetch              # Fetch from prod → JSON cache
#   ./scripts/reset_dev_db.sh --import             # Reset DB + import cached data
#   ./scripts/reset_dev_db.sh --all               # Reset + fetch + import
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

IMPORT_ENV_FILE="$PROJECT_ROOT/nautobot_import.env"
HAS_IMPORT_CONFIG=false
if [[ -f "$IMPORT_ENV_FILE" ]]; then
    HAS_IMPORT_CONFIG=true
    source "$IMPORT_ENV_FILE"
fi

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nautobot-app-mcp-server}"
DEV_DIR="$PROJECT_ROOT/development"
CACHE_DIR="$PROJECT_ROOT/import_cache"
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
        psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -c "$1"
}

cache_file_exists() {
    local name="$1"
    [[ -f "$CACHE_DIR/${name}.json" ]]
}

cache_record_count() {
    local name="$1"
    if cache_file_exists "$name"; then
        python3 -c "import json,sys; print(len(json.load(open('$CACHE_DIR/${name}.json'))))" 2>/dev/null || echo "?"
    else
        echo "—"
    fi
}

# ---------------------------------------------------------------------------
# Container health check
# ---------------------------------------------------------------------------

check_containers() {
    if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAUTOBOT}$"; then
        log "[ERROR] Nautobot container '$CONTAINER_NAUTOBOT' is not running."
        log "        Start the dev stack first: poetry run invoke start"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Phase 0: Reset (drop / migrate / superuser)
# ---------------------------------------------------------------------------

do_reset() {
    log "Stopping services (releasing DB connections)..."
    compose stop nautobot worker beat 2>/dev/null || true

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
    local output
    output=$(container_exec shell --command "
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
" 2>&1)
    log "  $output"
}

# ---------------------------------------------------------------------------
# Verify the database is clean
# ---------------------------------------------------------------------------

do_verify() {
    log "Verifying database is clean..."
    local PASS=true

    # Helper: query a table and check row count.
    verify_zero() {
        local table="$1"
        local result
        result=$( (docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
            psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -t -c \
            "SELECT COUNT(*) FROM $table;" 2>&1 || true) | tr -d '[:space:]')
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
}

# ---------------------------------------------------------------------------
# Phase 1: Fetch from production (host-side, no Docker needed)
# ---------------------------------------------------------------------------

do_fetch() {
    if [[ "$HAS_IMPORT_CONFIG" == "false" ]]; then
        log "[ERROR] nautobot_import.env not found."
        log "        Copy nautobot_import.env.example to nautobot_import.env and fill in your values."
        exit 1
    fi

    if [[ -z "${NAUTOBOT_PROD_URL:-}" ]] || [[ -z "${NAUTOBOT_PROD_TOKEN:-}" ]]; then
        log "[ERROR] NAUTOBOT_PROD_URL and NAUTOBOT_PROD_TOKEN must be set in nautobot_import.env."
        exit 1
    fi

    mkdir -p "$CACHE_DIR"

    log "Fetching from $NAUTOBOT_PROD_URL ..."
    log "Output: $CACHE_DIR/"
    python3 -u "$PROJECT_ROOT/scripts/fetch_production_data.py"
}

# ---------------------------------------------------------------------------
# Phase 2: Import cached data into dev DB (container-side)
# ---------------------------------------------------------------------------

do_import() {
    if [[ "$HAS_IMPORT_CONFIG" == "false" ]]; then
        log "[ERROR] nautobot_import.env not found — cannot run import."
        exit 1
    fi

    if [[ ! -d "$CACHE_DIR" ]]; then
        log "[ERROR] Cache directory not found: $CACHE_DIR"
        log "        Run Phase 1 (fetch) first: $0 --fetch"
        exit 1
    fi

    # Show what's cached
    log "Cache contents ($CACHE_DIR/):"
    local cache_files=("statuses" "roles" "device_types" "platforms" "namespaces" "locations" "devices" "interfaces" "ip_addresses" "prefixes" "vlans")
    for f in "${cache_files[@]}"; do
        if cache_file_exists "$f"; then
            local count
            count=$(cache_record_count "$f")
            log "  $f.json  → $count records"
        fi
    done

    log "Running production data import (Phase 2)..."
    # The host's import_cache/ is volume-mounted at /source/import_cache/ in the container.
    # Pass --cache-dir directly so the management command finds it without relying on
    # NAUTOBOT_CONFIG path resolution (which incorrectly calculates /import_cache).
    log "  -> Executing import (this takes ~1 minute)..."
    docker exec \
        -e NAUTOBOT_CONFIG=/source/development/nautobot_config.py \
        "$CONTAINER_NAUTOBOT" \
        nautobot-server import_production_data --cache-dir /source/import_cache

    # Post-import verification: show actual DB row counts vs cached records
    log "Verifying imported data..."
    local table_counts=(
        "dcim_device:devices"
        "ipam_prefix:prefixes"
        "ipam_ipaddress:ip_addresses"
        "ipam_vlan:vlans"
        "circuits_circuit:circuits"
    )
    local all_ok=true
    for entry in "${table_counts[@]}"; do
        local db_table="${entry%%:*}"
        local cache_file="${entry##*:}"
        local db_count
        db_count=$( (docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
            psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -t -c \
            "SELECT COUNT(*) FROM $db_table;" 2>&1 || true) | tr -d '[:space:]')
        if [[ "$db_count" =~ ^ERROR ]] || [[ -z "$db_count" ]]; then
            log "  $db_table = —"
        else
            log "  $db_table = $db_count"
        fi
    done

    log "Import complete."
}

# ---------------------------------------------------------------------------
# Status: show current state
# ---------------------------------------------------------------------------

show_status() {
    echo ""
    echo "=== Dev DB Status ==="
    echo ""
    echo "  Containers:"
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAUTOBOT}$"; then
        echo "    nautobot  → running"
    else
        echo "    nautobot  → NOT running (start with: poetry run invoke start)"
    fi

    echo ""
    echo "  Import config:"
    if [[ "$HAS_IMPORT_CONFIG" == "true" ]]; then
        echo "    nautobot_import.env  → found"
        echo "    Production URL: ${NAUTOBOT_PROD_URL:-not set}"
    else
        echo "    nautobot_import.env  → MISSING"
        echo "    Copy nautobot_import.env.example → nautobot_import.env"
    fi

    echo ""
    echo "  Cache ($CACHE_DIR/):"
    local cache_files=("statuses" "roles" "device_types" "platforms" "namespaces" "locations" "devices" "interfaces" "ip_addresses" "prefixes" "vlans")
    local any_cached=false
    for f in "${cache_files[@]}"; do
        if cache_file_exists "$f"; then
            any_cached=true
            local count
            count=$(cache_record_count "$f")
            echo "    $f.json  [$count records]"
        fi
    done
    if [[ "$any_cached" == "false" ]]; then
        echo "    (no cache files — run Phase 1 to fetch from production)"
    fi

    echo ""
    echo "  DB row counts:"
    local tables=("dcim_device" "ipam_prefix" "ipam_ipaddress" "ipam_vlan" "circuits_circuit" "auth_user")
    for t in "${tables[@]}"; do
        local cnt
        cnt=$( (docker exec -e PGPASSWORD="$NAUTOBOT_DB_PASSWORD" "$CONTAINER_DB" \
            psql -U "$NAUTOBOT_DB_USER" -d "$NAUTOBOT_DB_NAME" -t -c \
            "SELECT COUNT(*) FROM $t;" 2>&1 || true) | tr -d '[:space:]')
        if [[ "$cnt" =~ ^ERROR ]] || [[ -z "$cnt" ]]; then
            echo "    $t = —"
        else
            echo "    $t = $cnt"
        fi
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------

show_menu() {
    show_status

    echo "=== Actions ==="
    echo ""
    echo "  1) [Reset]       Reset DB only (drop, migrate, create superuser)"
    echo "  2) [Fetch]       Phase 1: Fetch from production → JSON cache"
    echo "  3) [Import]      Reset DB + import cached data into dev"
    echo "  4) [All]         Reset + fetch + import (full pipeline)"
    echo "  5) [Reset+Fetch] Reset DB + fetch from production"
    echo ""
    echo "  Q) Quit"
    echo ""
}

interactive_menu() {
    local choice
    while true; do
        show_menu
        read -rp "Select option: " choice
        case "$choice" in
            1)
                check_containers
                do_reset
                do_verify
                log "Done. Dev DB is clean."
                ;;
            2)
                do_fetch
                log "Done. Data cached in $CACHE_DIR/"
                ;;
            3)
                check_containers
                do_reset
                do_verify
                do_import
                log "Done. Production data is now in the dev DB."
                ;;
            4)
                check_containers
                do_reset
                do_verify
                do_fetch
                do_import
                log "Done. Full pipeline complete."
                ;;
            5)
                check_containers
                do_reset
                do_verify
                do_fetch
                log "Done. DB reset and data cached."
                ;;
            Q|q)
                exit 0
                ;;
            *)
                echo "Unknown option '$choice'. Try again."
                ;;
        esac
        echo ""
    done
}

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

main() {
    if [[ $# -eq 0 ]]; then
        interactive_menu
        return
    fi

    local do_reset_db=false
    local do_fetch_prod=false
    local do_import_prod=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --reset)
                do_reset_db=true
                ;;
            --fetch)
                do_fetch_prod=true
                ;;
            --import)
                do_reset_db=true
                do_import_prod=true
                ;;
            --all)
                do_reset_db=true
                do_fetch_prod=true
                do_import_prod=true
                ;;
            --help|-h)
                echo "Usage: $0 [options]"
                echo "  --reset    Reset DB only"
                echo "  --fetch    Fetch from production (Phase 1)"
                echo "  --import   Reset DB + import cached data"
                echo "  --all      Full pipeline: reset + fetch + import"
                echo "  (no args)  Interactive menu"
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                echo "Run '$0 --help' for usage."
                exit 1
                ;;
        esac
        shift
    done

    if [[ "$do_reset_db" == "true" ]]; then
        check_containers
        do_reset
        do_verify
    fi

    if [[ "$do_fetch_prod" == "true" ]]; then
        do_fetch
    fi

    if [[ "$do_import_prod" == "true" ]]; then
        check_containers
        do_import
    fi

    log "Done."
}

main "$@"
