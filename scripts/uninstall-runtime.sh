#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${ALBION_HELPER_HOME:-$HOME/.albion-helper}"
COMPOSE_FILE_NAME="docker-compose.yml"
ENV_FILE_NAME=".env"
KEEP_FILES="false"

usage() {
  cat <<'USAGE'
Stop and remove Albion Helper runtime installation.

Usage:
  uninstall-runtime.sh [options]

Options:
  --dir PATH      Install directory (default: ~/.albion-helper)
  --keep-files    Keep install files after removing containers/volumes
  -h, --help      Show this help

Environment overrides:
  ALBION_HELPER_HOME
USAGE
}

log() {
  printf '[albion-helper-uninstall] %s\n' "$*"
}

fail() {
  printf '[albion-helper-uninstall] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --keep-files)
      KEEP_FILES="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      fail "Unknown option: $1"
      ;;
  esac
done

[ -n "$INSTALL_DIR" ] || fail "Install directory cannot be empty"

COMPOSE_PATH="${INSTALL_DIR}/${COMPOSE_FILE_NAME}"
ENV_PATH="${INSTALL_DIR}/${ENV_FILE_NAME}"

if [ -f "$COMPOSE_PATH" ]; then
  require_cmd docker
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 plugin is required (docker compose ...)"

  log "Stopping containers and removing volumes"
  if [ -f "$ENV_PATH" ]; then
    docker compose --env-file "$ENV_PATH" -f "$COMPOSE_PATH" down -v --remove-orphans
  else
    docker compose -f "$COMPOSE_PATH" down -v --remove-orphans
  fi
else
  log "Compose file not found at ${COMPOSE_PATH}; skipping container teardown"
fi

if [ "$KEEP_FILES" = "true" ]; then
  log "Keeping install files in ${INSTALL_DIR}"
  exit 0
fi

if [ -d "$INSTALL_DIR" ]; then
  rm -rf "$INSTALL_DIR"
  log "Removed ${INSTALL_DIR}"
else
  log "Nothing to remove at ${INSTALL_DIR}"
fi
