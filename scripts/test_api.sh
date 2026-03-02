#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

TEST_SUITE="${TEST_SUITE:-full}" # full | smoke | permissions | all
TEST_HTTP_MODE="${TEST_HTTP_MODE:-postgres}" # postgres | sqlite
TEST_TARGET="${TEST_TARGET:-}"
TEST_PYTEST_OPTS="${TEST_PYTEST_OPTS:--q -s}"

TEST_DB_USER="${TEST_DB_USER:-postgres}"
TEST_DB_PASSWORD="${TEST_DB_PASSWORD:-postgres}"
TEST_DB_NAME="${TEST_DB_NAME:-tkp_api_test}"
TEST_PG_PORT="${TEST_PG_PORT:-55432}"
TEST_REDIS_PORT="${TEST_REDIS_PORT:-56379}"

usage() {
  cat <<'USAGE'
Usage: bash scripts/test_api.sh [options]

Options:
  --suite <full|smoke|permissions|all>  Test suite to run (default: full)
  --mode <postgres|sqlite>              Database mode (default: postgres)
  --target <pytest nodeid>              Custom pytest target (overrides suite)
  --pytest-opts "<opts>"                Pytest options (default: -q -s)
  -h, --help                            Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)
      TEST_SUITE="$2"
      shift 2
      ;;
    --mode)
      TEST_HTTP_MODE="$2"
      shift 2
      ;;
    --target)
      TEST_TARGET="$2"
      shift 2
      ;;
    --pytest-opts)
      TEST_PYTEST_OPTS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

case "$TEST_SUITE" in
  full|smoke|permissions|all) ;;
  *)
    echo "invalid --suite: $TEST_SUITE (expected: full|smoke|permissions|all)" >&2
    exit 1
    ;;
esac

case "$TEST_HTTP_MODE" in
  postgres|sqlite) ;;
  *)
    echo "invalid --mode: $TEST_HTTP_MODE (expected: postgres|sqlite)" >&2
    exit 1
    ;;
esac

export KD_STORAGE_ROOT="${KD_STORAGE_ROOT:-$ROOT_DIR/.storage-test}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv-cache}"
export TKP_TEST_LOG="${TKP_TEST_LOG:-1}"
export TKP_TEST_LOG_VERBOSE="${TKP_TEST_LOG_VERBOSE:-1}"
export TKP_TEST_LOG_PAYLOAD="${TKP_TEST_LOG_PAYLOAD:-0}"

configure_mode_env() {
  if [[ "$TEST_HTTP_MODE" == "postgres" ]]; then
    export KD_DATABASE_URL="${KD_DATABASE_URL:-postgresql+psycopg://$TEST_DB_USER:$TEST_DB_PASSWORD@127.0.0.1:$TEST_PG_PORT/$TEST_DB_NAME}"
    export KD_REDIS_URL="${KD_REDIS_URL:-redis://127.0.0.1:$TEST_REDIS_PORT/0}"
    export TKP_TEST_DB_MODE=postgres
  else
    export TKP_TEST_DB_MODE=sqlite
    unset KD_DATABASE_URL || true
    unset KD_REDIS_URL || true
  fi
}

suite_target() {
  case "$1" in
    full)
      echo "services/api/tests/test_http_api_full_coverage.py::test_http_api_full_workflow_with_permissions_and_coverage"
      ;;
    smoke)
      echo "services/api/tests/test_http_api_full_coverage.py::test_http_api_smoke_core_auth_and_health"
      ;;
    permissions)
      echo "services/api/tests/test_http_api_full_coverage.py::test_http_api_permissions_config_matrix_by_role"
      ;;
    *)
      echo "unsupported suite target: $1" >&2
      exit 1
      ;;
  esac
}

run_pytest_target() {
  local target="$1"
  echo "running HTTP API test:"
  echo "  mode:         $TEST_HTTP_MODE"
  echo "  suite:        $TEST_SUITE"
  echo "  target:       $target"
  echo "  pytest opts:  $TEST_PYTEST_OPTS"
  if [[ "$TEST_HTTP_MODE" == "postgres" ]]; then
    echo "  KD_DATABASE_URL=$KD_DATABASE_URL"
    echo "  KD_REDIS_URL=$KD_REDIS_URL"
  fi

  set +e
  PYTHONPATH=services/api/src uv run --project services/api --with pytest --with httpx \
    python -m pytest "$target" $TEST_PYTEST_OPTS
  local uv_exit_code=$?
  set -e

  if [[ "$uv_exit_code" -eq 0 ]]; then
    return 0
  fi

  echo "uv run failed with code $uv_exit_code, fallback to local .venv ..."
  local pytest_site_packages="${PYTEST_SITE_PACKAGES:-/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages}"
  PYTHONPATH=services/api/src .venv/bin/python - <<PY
import sys
sys.path.append("$pytest_site_packages")
import pytest
raise SystemExit(pytest.main(["$target", *"$TEST_PYTEST_OPTS".split()]))
PY
}

configure_mode_env

if [[ -n "$TEST_TARGET" ]]; then
  run_pytest_target "$TEST_TARGET"
  exit 0
fi

if [[ "$TEST_SUITE" == "all" ]]; then
  run_pytest_target "$(suite_target smoke)"
  run_pytest_target "$(suite_target permissions)"
  run_pytest_target "$(suite_target full)"
  exit 0
fi

run_pytest_target "$(suite_target "$TEST_SUITE")"
