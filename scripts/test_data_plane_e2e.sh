#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-19080}"
RAG_HOST="${RAG_HOST:-127.0.0.1}"
RAG_PORT="${RAG_PORT:-19081}"

TEST_DB_USER="${TEST_DB_USER:-postgres}"
TEST_DB_PASSWORD="${TEST_DB_PASSWORD:-postgres}"
TEST_DB_NAME="${TEST_DB_NAME:-tkp_api_test}"
TEST_PG_PORT="${TEST_PG_PORT:-55432}"
TEST_REDIS_PORT="${TEST_REDIS_PORT:-56379}"
TEST_MINIO_PORT="${TEST_MINIO_PORT:-59000}"
TEST_MINIO_ROOT_USER="${TEST_MINIO_ROOT_USER:-minioadmin}"
TEST_MINIO_ROOT_PASSWORD="${TEST_MINIO_ROOT_PASSWORD:-minioadmin}"

KD_DATABASE_URL="${KD_DATABASE_URL:-postgresql+psycopg://$TEST_DB_USER:$TEST_DB_PASSWORD@127.0.0.1:$TEST_PG_PORT/$TEST_DB_NAME}"
KD_REDIS_URL="${KD_REDIS_URL:-redis://127.0.0.1:$TEST_REDIS_PORT/0}"
KD_INTERNAL_SERVICE_TOKEN="${KD_INTERNAL_SERVICE_TOKEN:-e2e-internal-token-please-change}"
KD_AUTH_JWT_SECRET="${KD_AUTH_JWT_SECRET:-local-dev-secret-key-at-least-32-bytes}"

LOG_DIR="${LOG_DIR:-$ROOT_DIR/.tmp/e2e-data-plane}"
mkdir -p "$LOG_DIR"
RAG_LOG="$LOG_DIR/rag.log"
API_LOG="$LOG_DIR/api.log"
WORKER_LOG="$LOG_DIR/worker.log"

RAG_PID=""
API_PID=""
WORKER_PID=""

cleanup() {
  local exit_code=$?

  for pid in "$WORKER_PID" "$API_PID" "$RAG_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
    fi
  done

  if [[ "$exit_code" -ne 0 ]]; then
    echo
    echo "[e2e] failed, logs:"
    [[ -f "$RAG_LOG" ]] && { echo "===== rag.log ====="; tail -n 80 "$RAG_LOG" || true; }
    [[ -f "$API_LOG" ]] && { echo "===== api.log ====="; tail -n 80 "$API_LOG" || true; }
    [[ -f "$WORKER_LOG" ]] && { echo "===== worker.log ====="; tail -n 80 "$WORKER_LOG" || true; }
  fi
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local label="$2"
  local timeout_s="${3:-60}"

  local i=0
  while [[ "$i" -lt "$timeout_s" ]]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[e2e] $label ready: $url"
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done

  echo "[e2e] $label not ready after ${timeout_s}s: $url" >&2
  return 1
}

assert_pid_alive() {
  local pid="$1"
  local label="$2"
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "[e2e] $label process exited unexpectedly (pid=$pid)" >&2
    return 1
  fi
}

echo "[e2e] prepare postgres/redis/minio test env"
TEST_MINIO_ENABLED=1 \
TEST_MINIO_PORT="$TEST_MINIO_PORT" \
TEST_MINIO_ROOT_USER="$TEST_MINIO_ROOT_USER" \
TEST_MINIO_ROOT_PASSWORD="$TEST_MINIO_ROOT_PASSWORD" \
TEST_DB_USER="$TEST_DB_USER" \
TEST_DB_PASSWORD="$TEST_DB_PASSWORD" \
TEST_DB_NAME="$TEST_DB_NAME" \
TEST_PG_PORT="$TEST_PG_PORT" \
TEST_REDIS_PORT="$TEST_REDIS_PORT" \
bash scripts/test_env_up.sh

echo "[e2e] start rag service"
(
  export KD_DATABASE_URL
  export KD_INTERNAL_SERVICE_TOKEN
  export PYTHONPATH="services/rag/src"
  .venv/bin/python -m uvicorn tkp_rag.app:app --host "$RAG_HOST" --port "$RAG_PORT"
) >"$RAG_LOG" 2>&1 &
RAG_PID=$!
sleep 1
assert_pid_alive "$RAG_PID" "rag"
wait_http "http://$RAG_HOST:$RAG_PORT/health/live" "rag" 90

echo "[e2e] start api service"
(
  export KD_DATABASE_URL
  export KD_REDIS_URL
  export KD_AUTH_JWT_SECRET
  export KD_AUTH_JWT_ALGORITHMS="HS256"
  export KD_RAG_BASE_URL="http://$RAG_HOST:$RAG_PORT"
  export KD_INTERNAL_SERVICE_TOKEN
  export KD_STORAGE_BACKEND="minio"
  export KD_STORAGE_BUCKET="tkp-documents"
  export KD_STORAGE_ENDPOINT="127.0.0.1:$TEST_MINIO_PORT"
  export KD_STORAGE_ACCESS_KEY="$TEST_MINIO_ROOT_USER"
  export KD_STORAGE_SECRET_KEY="$TEST_MINIO_ROOT_PASSWORD"
  export KD_STORAGE_SECURE="false"
  export PYTHONPATH="services/api/src"
  .venv/bin/python -m uvicorn tkp_api.main:app --host "$API_HOST" --port "$API_PORT"
) >"$API_LOG" 2>&1 &
API_PID=$!
sleep 1
assert_pid_alive "$API_PID" "api"
wait_http "http://$API_HOST:$API_PORT/api/health/ready" "api" 90

echo "[e2e] start worker service"
(
  export KD_DATABASE_URL
  export KD_STORAGE_BACKEND="minio"
  export KD_STORAGE_BUCKET="tkp-documents"
  export KD_STORAGE_ENDPOINT="127.0.0.1:$TEST_MINIO_PORT"
  export KD_STORAGE_ACCESS_KEY="$TEST_MINIO_ROOT_USER"
  export KD_STORAGE_SECRET_KEY="$TEST_MINIO_ROOT_PASSWORD"
  export KD_STORAGE_SECURE="false"
  export KD_WORKER_POLL_INTERVAL_SECONDS="0.5"
  export PYTHONPATH="services/worker/src"
  .venv/bin/python -m tkp_worker.main
) >"$WORKER_LOG" 2>&1 &
WORKER_PID=$!
sleep 1
assert_pid_alive "$WORKER_PID" "worker"

sleep 2

echo "[e2e] run prod-like HTTP data-plane test"
export TKP_E2E_API_BASE_URL="http://$API_HOST:$API_PORT"
export TKP_E2E_DATABASE_URL="$KD_DATABASE_URL"
export TKP_E2E_MINIO_ENDPOINT="127.0.0.1:$TEST_MINIO_PORT"
export TKP_E2E_MINIO_ACCESS_KEY="$TEST_MINIO_ROOT_USER"
export TKP_E2E_MINIO_SECRET_KEY="$TEST_MINIO_ROOT_PASSWORD"
export TKP_E2E_MINIO_BUCKET="tkp-documents"
export TKP_E2E_MINIO_SECURE="0"

PYTHONPATH=services/api/src .venv/bin/python -m pytest tests/e2e/test_prod_data_plane_http.py -q -s

echo "[e2e] success"
