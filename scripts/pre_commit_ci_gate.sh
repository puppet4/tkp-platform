#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DRY_RUN="${PRE_COMMIT_DRY_RUN:-0}"

run_step() {
  local label="$1"
  shift
  echo
  echo "[pre-commit] $label"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[pre-commit][dry-run] $*"
    return 0
  fi
  "$@"
}

echo "[pre-commit] 开始执行本地 CI 门禁校验..."

run_step "SQL governance" \
  bash scripts/check_sql_governance.sh

run_step "API smoke (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api_smoke.sh

run_step "API permissions matrix (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api_permissions_matrix.sh

run_step "API full (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api_full_coverage.sh

run_step "Prepare postgres+redis test env" \
  bash scripts/test_env_up.sh

run_step "API full (postgres)" \
  env TEST_HTTP_MODE=postgres TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api_full_coverage.sh

echo
echo "[pre-commit] 所有 CI 门禁校验通过，允许提交。"
