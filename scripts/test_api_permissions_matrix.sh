#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export TEST_HTTP_MODE="${TEST_HTTP_MODE:-sqlite}"
export TEST_TARGET="services/api/tests/test_http_api_full_coverage.py::test_http_api_permissions_config_matrix_by_role"
export TEST_PYTEST_OPTS="${TEST_PYTEST_OPTS:--q -s}"

bash scripts/test_api_full_coverage.sh
