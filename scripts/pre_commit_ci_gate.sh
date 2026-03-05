#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DRY_RUN="${PRE_COMMIT_DRY_RUN:-0}"
POSTGRES_ENV_READY=0

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

cleanup_test_env() {
  if [[ "$DRY_RUN" != "1" && "$POSTGRES_ENV_READY" == "1" ]]; then
    echo
    echo "[pre-commit] Cleanup postgres+redis test env"
    bash scripts/test_env_down.sh
  fi
}

trap cleanup_test_env EXIT

echo "[pre-commit] 开始执行本地 CI 门禁校验..."

run_step "SQL governance" \
  bash scripts/check_sql_governance.sh

run_step "API smoke (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api.sh --suite smoke

run_step "API retrieval eval quality gate (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=0 TKP_TEST_LOG_VERBOSE=0 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api.sh --target services/api/tests/test_retrieval_eval_service.py --pytest-opts "-q"

run_step "API permissions matrix (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api.sh --suite permissions

run_step "API full (sqlite)" \
  env TEST_HTTP_MODE=sqlite TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api.sh --suite full

run_step "Prepare postgres+redis test env" \
  bash scripts/test_env_up.sh
if [[ "$DRY_RUN" != "1" ]]; then
  POSTGRES_ENV_READY=1
fi

run_step "API full (postgres)" \
  env TEST_HTTP_MODE=postgres TKP_TEST_LOG=1 TKP_TEST_LOG_VERBOSE=1 TKP_TEST_LOG_PAYLOAD=0 \
  bash scripts/test_api.sh --suite full

echo
echo "[pre-commit] 所有 CI 门禁校验通过，允许提交。"
