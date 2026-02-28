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
migration_dir="infra/sql/migrations"
baseline_lock_file="infra/sql/baseline.lock"

echo "[1/7] check required SQL files"
for f in "${required_sql_files[@]}"; do
  [[ -f "$f" ]] || { echo "missing required file: $f"; exit 1; }
done

echo "[2/7] check SQL scripts are FK-free"
sql_files="$(find infra/sql -type f -name "*.sql" | sort)"
if [[ -n "$sql_files" ]] && rg -n "(FOREIGN[[:space:]]+KEY|REFERENCES[[:space:]])" $sql_files; then
  echo "foreign key clauses are forbidden by team policy"
  exit 1
fi

echo "[3/7] check no ORM auto-schema creation"
if rg -n "(create_all\\(|metadata\\.create_all)" services; then
  echo "ORM auto schema creation is forbidden"
  exit 1
fi

echo "[4/7] check no code-based schema sync scripts"
if find services -type f \( -name "*create_all*.py" -o -name "*sync_comments*.py" -o -name "*schema_sync*.py" \) | rg .; then
  echo "code-based schema sync scripts are forbidden"
  exit 1
fi

echo "[5/7] check SQL naming convention in table DDL"
if ! rg -n "CONSTRAINT[[:space:]]+uk_" infra/sql/010_tables.sql >/dev/null; then
  echo "expected uk_ unique constraints not found"
  exit 1
fi
if ! rg -n "CONSTRAINT[[:space:]]+ck_" infra/sql/010_tables.sql >/dev/null; then
  echo "expected ck_ check constraints not found"
  exit 1
fi

echo "[6/7] check migration directory and filename convention"
[[ -d "$migration_dir" ]] || { echo "missing migration directory: $migration_dir"; exit 1; }
while IFS= read -r file; do
  base_name="$(basename "$file")"
  if [[ ! "$base_name" =~ ^[0-9]{8}_[0-9]{6}_[a-z0-9_]+\.sql$ ]]; then
    echo "invalid migration filename: $file"
    echo "required pattern: YYYYMMDD_HHMMSS_description.sql"
    exit 1
  fi
  if ! rg -n "^[[:space:]]*BEGIN;[[:space:]]*$" "$file" >/dev/null; then
    echo "migration missing BEGIN; wrapper: $file"
    exit 1
  fi
  if ! rg -n "^[[:space:]]*COMMIT;[[:space:]]*$" "$file" >/dev/null; then
    echo "migration missing COMMIT; wrapper: $file"
    exit 1
  fi
done < <(find "$migration_dir" -maxdepth 1 -type f -name "*.sql" | sort)

echo "[7/7] check baseline lock integrity"
[[ -f "$baseline_lock_file" ]] || { echo "missing baseline lock file: $baseline_lock_file"; exit 1; }
while IFS= read -r line; do
  [[ -z "${line// }" ]] && continue
  [[ "$line" =~ ^# ]] && continue
  expected_hash="$(echo "$line" | awk '{print $1}')"
  path="$(echo "$line" | awk '{print $2}')"
  [[ -f "$path" ]] || { echo "baseline file missing: $path"; exit 1; }
  if command -v sha256sum >/dev/null 2>&1; then
    actual_hash="$(sha256sum "$path" | awk '{print $1}')"
  else
    actual_hash="$(shasum -a 256 "$path" | awk '{print $1}')"
  fi
  if [[ "$expected_hash" != "$actual_hash" ]]; then
    echo "baseline file checksum mismatch: $path"
    echo "do not modify baseline DDL directly; add incremental migration under $migration_dir"
    exit 1
  fi
done < "$baseline_lock_file"

echo "SQL governance checks passed."
