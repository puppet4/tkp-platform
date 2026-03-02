#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

TEST_PG_CONTAINER="${TEST_PG_CONTAINER:-tkp-postgres-test}"
TEST_DB_NAME="${TEST_DB_NAME:-tkp_api_test}"
TEST_DB_USER="${TEST_DB_USER:-postgres}"

podman exec "$TEST_PG_CONTAINER" dropdb -U "$TEST_DB_USER" --if-exists "$TEST_DB_NAME"
podman exec "$TEST_PG_CONTAINER" createdb -U "$TEST_DB_USER" -T template0 "$TEST_DB_NAME"

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

echo "database reset done: $TEST_DB_NAME"
