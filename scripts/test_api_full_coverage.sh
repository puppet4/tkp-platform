#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

TEST_HTTP_MODE="${TEST_HTTP_MODE:-postgres}" # postgres | sqlite
TEST_TARGET="${TEST_TARGET:-services/api/tests/test_http_api_full_coverage.py::test_http_api_full_workflow_with_permissions_and_coverage}"
TEST_PYTEST_OPTS="${TEST_PYTEST_OPTS:--q -s}"

TEST_DB_USER="${TEST_DB_USER:-postgres}"
TEST_DB_PASSWORD="${TEST_DB_PASSWORD:-postgres}"
TEST_DB_NAME="${TEST_DB_NAME:-tkp_api_test}"
TEST_PG_PORT="${TEST_PG_PORT:-55432}"
TEST_REDIS_PORT="${TEST_REDIS_PORT:-56379}"

export KD_STORAGE_ROOT="${KD_STORAGE_ROOT:-$ROOT_DIR/.storage-test}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/.uv-cache}"
export TKP_TEST_LOG="${TKP_TEST_LOG:-1}"
export TKP_TEST_LOG_VERBOSE="${TKP_TEST_LOG_VERBOSE:-1}"
export TKP_TEST_LOG_PAYLOAD="${TKP_TEST_LOG_PAYLOAD:-0}"

if [[ "$TEST_HTTP_MODE" == "postgres" ]]; then
  export KD_DATABASE_URL="${KD_DATABASE_URL:-postgresql+psycopg://$TEST_DB_USER:$TEST_DB_PASSWORD@127.0.0.1:$TEST_PG_PORT/$TEST_DB_NAME}"
  export KD_REDIS_URL="${KD_REDIS_URL:-redis://127.0.0.1:$TEST_REDIS_PORT/0}"
  export TKP_TEST_DB_MODE=postgres
elif [[ "$TEST_HTTP_MODE" == "sqlite" ]]; then
  export TKP_TEST_DB_MODE=sqlite
  unset KD_DATABASE_URL || true
  unset KD_REDIS_URL || true
else
  echo "invalid TEST_HTTP_MODE: $TEST_HTTP_MODE (expected: postgres|sqlite)" >&2
  exit 1
fi

echo "running HTTP API test:"
echo "  mode:         $TEST_HTTP_MODE"
echo "  target:       $TEST_TARGET"
echo "  pytest opts:  $TEST_PYTEST_OPTS"
if [[ "$TEST_HTTP_MODE" == "postgres" ]]; then
  echo "  KD_DATABASE_URL=$KD_DATABASE_URL"
  echo "  KD_REDIS_URL=$KD_REDIS_URL"
fi

set +e
PYTHONPATH=services/api/src uv run --project services/api --with pytest --with httpx \
  python -m pytest "$TEST_TARGET" $TEST_PYTEST_OPTS
UV_EXIT_CODE=$?
set -e

if [[ "$UV_EXIT_CODE" -eq 0 ]]; then
  exit 0
fi

echo "uv run failed with code $UV_EXIT_CODE, fallback to local .venv ..."
PYTEST_SITE_PACKAGES="${PYTEST_SITE_PACKAGES:-/Library/Frameworks/Python.framework/Versions/3.13/lib/python3.13/site-packages}"
PYTHONPATH=services/api/src .venv/bin/python - <<PY
import sys
sys.path.append("$PYTEST_SITE_PACKAGES")
import pytest
raise SystemExit(pytest.main(["$TEST_TARGET", *"$TEST_PYTEST_OPTS".split()]))
PY
