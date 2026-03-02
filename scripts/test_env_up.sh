#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

TEST_PG_CONTAINER="${TEST_PG_CONTAINER:-tkp-postgres-test}"
TEST_REDIS_CONTAINER="${TEST_REDIS_CONTAINER:-tkp-redis-test}"
TEST_PG_IMAGE="${TEST_PG_IMAGE:-docker.io/pgvector/pgvector:pg16}"
TEST_REDIS_IMAGE="${TEST_REDIS_IMAGE:-docker.io/library/redis:7}"
TEST_DB_NAME="${TEST_DB_NAME:-tkp_api_test}"
TEST_DB_USER="${TEST_DB_USER:-postgres}"
TEST_DB_PASSWORD="${TEST_DB_PASSWORD:-postgres}"
TEST_PG_PORT="${TEST_PG_PORT:-55432}"
TEST_REDIS_PORT="${TEST_REDIS_PORT:-56379}"
TEST_PG_DATA_DIR="${TEST_PG_DATA_DIR:-$HOME/Documents/docker/postgres/test}"
TEST_REDIS_DATA_DIR="${TEST_REDIS_DATA_DIR:-$HOME/Documents/docker/redis/test}"

mkdir -p "$TEST_PG_DATA_DIR" "$TEST_REDIS_DATA_DIR"

ensure_container_running() {
  local name="$1"
  local image="$2"
  shift 2
  if podman ps -a --format '{{.Names}}' | grep -qx "$name"; then
    podman start "$name" >/dev/null
    return
  fi
  podman run -d --name "$name" "$@" "$image" >/dev/null
}

if [[ "${TEST_ENV_RECREATE:-0}" == "1" ]]; then
  podman rm -f "$TEST_PG_CONTAINER" >/dev/null 2>&1 || true
  podman rm -f "$TEST_REDIS_CONTAINER" >/dev/null 2>&1 || true
fi

ensure_container_running \
  "$TEST_PG_CONTAINER" \
  "$TEST_PG_IMAGE" \
  -e "POSTGRES_PASSWORD=$TEST_DB_PASSWORD" \
  -e "POSTGRES_USER=$TEST_DB_USER" \
  -v "$TEST_PG_DATA_DIR:/var/lib/postgresql/data:Z" \
  -p "${TEST_PG_PORT}:5432"

ensure_container_running \
  "$TEST_REDIS_CONTAINER" \
  "$TEST_REDIS_IMAGE" \
  -v "$TEST_REDIS_DATA_DIR:/data:Z" \
  -p "${TEST_REDIS_PORT}:6379"

echo "waiting postgres..."
for _ in $(seq 1 60); do
  if podman exec "$TEST_PG_CONTAINER" pg_isready -U "$TEST_DB_USER" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! podman exec "$TEST_PG_CONTAINER" pg_isready -U "$TEST_DB_USER" >/dev/null 2>&1; then
  echo "postgres not ready" >&2
  exit 1
fi

DB_EXISTS="$(
  podman exec "$TEST_PG_CONTAINER" psql -U "$TEST_DB_USER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${TEST_DB_NAME}'"
)"
if [[ "$DB_EXISTS" != "1" ]]; then
  podman exec "$TEST_PG_CONTAINER" createdb -U "$TEST_DB_USER" -T template0 "$TEST_DB_NAME"
fi

for f in \
  "$ROOT_DIR/infra/sql/000_extensions.sql" \
  "$ROOT_DIR/infra/sql/010_tables.sql" \
  "$ROOT_DIR/infra/sql/020_indexes.sql" \
  "$ROOT_DIR/infra/sql/030_comments.sql" \
  "$ROOT_DIR/infra/sql/040_seed_permissions.sql"
do
  echo "apply: ${f##*/}"
  podman exec -i "$TEST_PG_CONTAINER" \
    psql -U "$TEST_DB_USER" -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 < "$f"
done

while IFS= read -r f; do
  echo "apply migration: ${f##*/}"
  podman exec -i "$TEST_PG_CONTAINER" \
    psql -U "$TEST_DB_USER" -d "$TEST_DB_NAME" -v ON_ERROR_STOP=1 < "$f"
done < <(find "$ROOT_DIR/infra/sql/migrations" -maxdepth 1 -type f -name "*.sql" | sort)

echo
echo "test environment is ready:"
echo "  postgres: postgresql+psycopg://$TEST_DB_USER:$TEST_DB_PASSWORD@127.0.0.1:$TEST_PG_PORT/$TEST_DB_NAME"
echo "  redis:    redis://127.0.0.1:$TEST_REDIS_PORT/0"
