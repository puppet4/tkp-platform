#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/infra/podman-compose.yml}"
STACK_ENV="${STACK_ENV:-dev}"
STACK_ENV_FILE="${STACK_ENV_FILE:-$ROOT_DIR/infra/env/${STACK_ENV}.env}"

if [[ -f "$HOME/.docker/config.json" ]] && grep -q '"credsStore"[[:space:]]*:[[:space:]]*"desktop"' "$HOME/.docker/config.json"; then
  if ! command -v docker-credential-desktop >/dev/null 2>&1; then
    export DOCKER_CONFIG="${DOCKER_CONFIG:-$ROOT_DIR/.docker-config-podman}"
    mkdir -p "$DOCKER_CONFIG"
    if [[ ! -f "$DOCKER_CONFIG/config.json" ]]; then
      printf '{}\n' > "$DOCKER_CONFIG/config.json"
    fi
  fi
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi
if [[ ! -f "$STACK_ENV_FILE" ]]; then
  echo "stack env file not found: $STACK_ENV_FILE" >&2
  exit 1
fi

cd "$ROOT_DIR"
podman compose --env-file "$STACK_ENV_FILE" -f "$COMPOSE_FILE" down --remove-orphans

echo "stack stopped (env=$STACK_ENV)"
