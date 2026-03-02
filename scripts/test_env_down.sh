#!/usr/bin/env bash
set -euo pipefail

TEST_PG_CONTAINER="${TEST_PG_CONTAINER:-tkp-postgres-test}"
TEST_REDIS_CONTAINER="${TEST_REDIS_CONTAINER:-tkp-redis-test}"

podman stop "$TEST_REDIS_CONTAINER" >/dev/null 2>&1 || true
podman stop "$TEST_PG_CONTAINER" >/dev/null 2>&1 || true

echo "test containers stopped: $TEST_PG_CONTAINER, $TEST_REDIS_CONTAINER"

