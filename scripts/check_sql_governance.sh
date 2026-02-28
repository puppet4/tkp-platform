#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

required_sql_files=(
  "infra/sql/000_extensions.sql"
  "infra/sql/010_tables.sql"
  "infra/sql/020_indexes.sql"
  "infra/sql/030_comments.sql"
  "infra/sql/040_seed_permissions.sql"
)

echo "[1/5] check required SQL files"
for f in "${required_sql_files[@]}"; do
  [[ -f "$f" ]] || { echo "missing required file: $f"; exit 1; }
done

echo "[2/5] check SQL scripts are FK-free"
if rg -n "(FOREIGN[[:space:]]+KEY|REFERENCES[[:space:]])" infra/sql/*.sql; then
  echo "foreign key clauses are forbidden by team policy"
  exit 1
fi

echo "[3/5] check no ORM auto-schema creation"
if rg -n "(create_all\\(|metadata\\.create_all)" services; then
  echo "ORM auto schema creation is forbidden"
  exit 1
fi

echo "[4/5] check no code-based schema sync scripts"
if find services -type f \( -name "*create_all*.py" -o -name "*sync_comments*.py" -o -name "*schema_sync*.py" \) | rg .; then
  echo "code-based schema sync scripts are forbidden"
  exit 1
fi

echo "[5/5] check SQL naming convention in table DDL"
if ! rg -n "CONSTRAINT[[:space:]]+uk_" infra/sql/010_tables.sql >/dev/null; then
  echo "expected uk_ unique constraints not found"
  exit 1
fi
if ! rg -n "CONSTRAINT[[:space:]]+ck_" infra/sql/010_tables.sql >/dev/null; then
  echo "expected ck_ check constraints not found"
  exit 1
fi

echo "SQL governance checks passed."
