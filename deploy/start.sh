#!/bin/sh
set -eu

service_role="${1:-api}"

require_value() {
    variable_name="$1"
    variable_value="$(printenv "$variable_name" 2>/dev/null || true)"
    if [ -z "$variable_value" ]; then
        echo "Required deployment setting is empty: $variable_name" >&2
        exit 64
    fi
    case "$variable_value" in
        *REPLACE*|*YOUR_*)
            echo "Replace the example value for deployment setting: $variable_name" >&2
            exit 64
            ;;
    esac
}

case "$service_role" in
    api|worker)
        [ "${APP_ENV:-}" = "local" ] || {
            echo "This Compose profile is for private synthetic-data demos; set APP_ENV=local." >&2
            exit 64
        }
        for name in DATABASE_URL WORKFLOW_DATABASE_URL MILVUS_URI MILVUS_TOKEN \
            LAYA_BASE_URL WORKFLOW_API_TOKEN WORKFLOW_REVIEWER_TOKEN; do
            require_value "$name"
        done
        case "$DATABASE_URL" in
            postgresql://*|postgres://*) ;;
            *) echo "DATABASE_URL must be a PostgreSQL URL." >&2; exit 64 ;;
        esac
        case "$WORKFLOW_DATABASE_URL" in
            postgresql://*|postgres://*) ;;
            *) echo "WORKFLOW_DATABASE_URL must be a PostgreSQL URL." >&2; exit 64 ;;
        esac
        [ "$DATABASE_URL" != "$WORKFLOW_DATABASE_URL" ] || {
            echo "Use separate Neon credentials/databases for order reads and workflow writes." >&2
            exit 64
        }
        [ "$WORKFLOW_API_TOKEN" != "$WORKFLOW_REVIEWER_TOKEN" ] || {
            echo "Support and reviewer tokens must be different." >&2
            exit 64
        }
        [ "${#WORKFLOW_API_TOKEN}" -ge 32 ] && [ "${#WORKFLOW_REVIEWER_TOKEN}" -ge 32 ] || {
            echo "Use random support and reviewer tokens with at least 32 characters." >&2
            exit 64
        }
        case "$LAYA_BASE_URL" in
            http://127.0.0.1*|https://127.0.0.1*|http://localhost*|https://localhost*|http://\[::1\]*|https://\[::1\]*)
                echo "LAYA_BASE_URL must be reachable from the API container; loopback points at the container." >&2
                exit 64
                ;;
        esac
        ;;
    *)
        echo "Unknown container role: $service_role" >&2
        exit 64
        ;;
esac

if [ "$service_role" = "worker" ]; then
    exec python -m backend.app.worker
fi

exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1
