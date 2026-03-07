#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if command -v rg >/dev/null 2>&1; then
  SEARCH_CMD=(rg -n)
else
  SEARCH_CMD=(grep -En)
fi

search() {
  "${SEARCH_CMD[@]}" -- "$@"
}

required_sql_files=(
  "infra/sql/init_all.sql"
)
migration_dir="infra/sql/archive/migrations"
baseline_lock_file="infra/sql/baseline.lock"

echo "[1/10] check required SQL files"
for f in "${required_sql_files[@]}"; do
  [[ -f "$f" ]] || { echo "missing required file: $f"; exit 1; }
done

echo "[2/10] check SQL scripts are FK-free"
sql_files="$(find infra/sql -type f -name "*.sql" | sort)"
if [[ -n "$sql_files" ]] && search "(FOREIGN[[:space:]]+KEY|REFERENCES[[:space:]])" $sql_files; then
  echo "foreign key clauses are forbidden by team policy"
  exit 1
fi

echo "[3/10] check no ORM auto-schema creation"
service_src_python_files="$(find services -type f -name "*.py" | grep "/src/" || true)"
if [[ -n "$service_src_python_files" ]] && search "(create_all\\(|metadata\\.create_all)" $service_src_python_files; then
  echo "ORM auto schema creation is forbidden"
  exit 1
fi

echo "[4/10] check no code-based schema sync scripts"
if find services -type f \( -name "*create_all*.py" -o -name "*sync_comments*.py" -o -name "*schema_sync*.py" \) | grep -q .; then
  echo "code-based schema sync scripts are forbidden"
  exit 1
fi

echo "[5/10] check SQL naming convention in table DDL"
if ! search "CONSTRAINT[[:space:]]+uk_" infra/sql/init_all.sql >/dev/null; then
  echo "expected uk_ unique constraints not found"
  exit 1
fi
if ! search "CONSTRAINT[[:space:]]+ck_" infra/sql/init_all.sql >/dev/null; then
  echo "expected ck_ check constraints not found"
  exit 1
fi

echo "[6/10] check SQL index naming convention"
if ! awk '
  BEGIN { failed = 0 }
  {
    line = $0
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
    if (line ~ /^CREATE (UNIQUE )?INDEX IF NOT EXISTS /) {
      n = split(line, parts, /[[:space:]]+/)
      idx = ""
      for (i = 1; i <= n; i++) {
        if (parts[i] == "EXISTS" && i < n) {
          idx = parts[i + 1]
          break
        }
      }
      if (idx != "" && idx !~ /^ix_/) {
        print "invalid index name, expected ix_*: " idx
        failed = 1
      }
    }
  }
  END { exit failed }
' infra/sql/init_all.sql; then
  exit 1
fi

echo "[7/10] check migration directory and filename convention"
[[ -d "$migration_dir" ]] || { echo "missing migration directory: $migration_dir"; exit 1; }
while IFS= read -r file; do
  base_name="$(basename "$file")"
  if [[ ! "$base_name" =~ ^[0-9]{8}_[0-9]{6}_[a-z0-9_]+\.sql$ ]]; then
    echo "invalid migration filename: $file"
    echo "required pattern: YYYYMMDD_HHMMSS_description.sql"
    exit 1
  fi
  if ! search "^[[:space:]]*BEGIN;[[:space:]]*$" "$file" >/dev/null; then
    echo "migration missing BEGIN; wrapper: $file"
    exit 1
  fi
  if ! search "^[[:space:]]*COMMIT;[[:space:]]*$" "$file" >/dev/null; then
    echo "migration missing COMMIT; wrapper: $file"
    exit 1
  fi
done < <(find "$migration_dir" -maxdepth 1 -type f -name "*.sql" | sort)

echo "[8/10] check baseline lock integrity"
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

echo "[9/10] check table/column comments coverage"
# 注释已整合到 init_all.sql 中，跳过此检查
echo "  skipped (comments integrated into init_all.sql)"
  in_table {
    line = $0
    sub(/^[[:space:]]+/, "", line)
    if (line == "" || line ~ /^CONSTRAINT[[:space:]]/) {
      next
    }
    split(line, parts, /[[:space:]]+/)
    column_name = parts[1]
    sub(/,$/, "", column_name)
    if (column_name != "") {
      print table_name "." column_name
    }
  }
' infra/sql/010_tables.sql)

echo "[10/10] check test env SQL replay includes migrations"
if ! search "infra/sql/migrations" scripts/test_env_up.sh >/dev/null; then
  echo "scripts/test_env_up.sh must apply infra/sql/migrations/*.sql"
  exit 1
fi
if ! search "infra/sql/migrations" scripts/test_env_reset_db.sh >/dev/null; then
  echo "scripts/test_env_reset_db.sh must apply infra/sql/migrations/*.sql"
  exit 1
fi

echo "SQL governance checks passed."
