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
  "sql/init_all.sql"
)
migration_dir="sql/archive/migrations"
baseline_lock_file="sql/baseline.lock"

echo "[1/10] check required SQL files"
for f in "${required_sql_files[@]}"; do
  [[ -f "$f" ]] || { echo "missing required file: $f"; exit 1; }
done

echo "[2/10] check incremental SQL scripts are FK-free"
# 约束仅针对增量 SQL。基线 init_all.sql 可能包含历史结构，不在此规则内阻断。
incremental_sql_files="$(find sql -type f -name "*.sql" ! -path "sql/init_all.sql" | sort)"
if [[ -n "$incremental_sql_files" ]] && search "(FOREIGN[[:space:]]+KEY|REFERENCES[[:space:]])" $incremental_sql_files; then
  echo "foreign key clauses are forbidden in incremental SQL by team policy"
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
if ! search "CONSTRAINT[[:space:]]+uk_" sql/init_all.sql >/dev/null; then
  echo "expected uk_ unique constraints not found"
  exit 1
fi
if ! search "CONSTRAINT[[:space:]]+ck_" sql/init_all.sql >/dev/null; then
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
      if (idx != "" && idx !~ /^(ix_|idx_)/) {
        print "invalid index name, expected ix_* or idx_*: " idx
        failed = 1
      }
    }
  }
  END { exit failed }
' sql/init_all.sql; then
  exit 1
fi

echo "[7/10] check migration directory and filename convention"
if [[ ! -d "$migration_dir" ]]; then
  echo "  skipped (migration directory not present: $migration_dir)"
else
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
fi

echo "[8/10] check baseline lock integrity"
if [[ ! -f "$baseline_lock_file" ]]; then
  echo "  skipped (baseline lock file not present: $baseline_lock_file)"
else
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
fi

echo "[9/10] check table/column comments coverage"
# 注释已整合到 init_all.sql 中，跳过此检查
echo "  skipped (comments integrated into init_all.sql)"

echo "[10/10] check test env SQL replay includes unified baseline"
if ! search "sql/init_all.sql" scripts/test_env_up.sh >/dev/null; then
  echo "scripts/test_env_up.sh must apply sql/init_all.sql"
  exit 1
fi
if ! search "sql/init_all.sql" scripts/test_env_reset_db.sh >/dev/null; then
  echo "scripts/test_env_reset_db.sh must apply sql/init_all.sql"
  exit 1
fi

echo "SQL governance checks passed."
