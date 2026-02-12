#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${ALBION_HELPER_HOME:-$HOME/.albion-helper}"
REPO="${ALBION_HELPER_REPO:-maxiarat1/albion_helper}"
REF="${ALBION_HELPER_REF:-master}"
COMPOSE_FILE_NAME="docker-compose.yml"
ENV_FILE_NAME=".env"
SKIP_OLLAMA_PULL="false"
ENABLE_CAPTURE_PROFILE="false"
START_STACK="true"
SCRIPT_DIR=""
LOCAL_ROOT=""

usage() {
  cat <<'USAGE'
Install and run Albion Helper from prebuilt Docker images.

Usage:
  install-runtime.sh [options]

Options:
  --dir PATH              Install directory (default: ~/.albion-helper)
  --repo OWNER/REPO       GitHub repo for runtime files (default: maxiarat1/albion_helper)
  --ref REF               Git ref (branch/tag/SHA) for runtime files (default: master)
  --skip-ollama-pull      Do not run 'ollama pull <model>'
  --with-capture          Enable optional albiondata-client profile
  --no-start              Download files only; do not run docker compose
  -h, --help              Show this help

Environment overrides:
  ALBION_HELPER_HOME, ALBION_HELPER_REPO, ALBION_HELPER_REF
USAGE
}

log() {
  printf '[albion-helper-install] %s\n' "$*"
}

fail() {
  printf '[albion-helper-install] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

env_value_or_default() {
  local file="$1"
  local key="$2"
  local fallback="$3"
  local value
  value="$(awk -F= -v target="$key" '
    $1 == target {
      print $2
      found = 1
      exit
    }
    END {
      if (!found) {
        print ""
      }
    }
  ' "$file")"
  value="${value%%[[:space:]]*}"
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return
  fi
  printf '%s' "$fallback"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir)
      INSTALL_DIR="${2:-}"
      shift 2
      ;;
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    --skip-ollama-pull)
      SKIP_OLLAMA_PULL="true"
      shift
      ;;
    --with-capture)
      ENABLE_CAPTURE_PROFILE="true"
      shift
      ;;
    --no-start)
      START_STACK="false"
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

require_cmd curl
require_cmd docker

docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 plugin is required (docker compose ...)"

RAW_BASE_URL="https://raw.githubusercontent.com/${REPO}/${REF}"
COMPOSE_DEST="${INSTALL_DIR}/${COMPOSE_FILE_NAME}"
ENV_DEST="${INSTALL_DIR}/${ENV_FILE_NAME}"
SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"

if [ -n "$SCRIPT_SOURCE" ] && [ -f "$SCRIPT_SOURCE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ]; then
  CANDIDATE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  if [ -f "$CANDIDATE_ROOT/docker-compose.runtime.yml" ] && [ -f "$CANDIDATE_ROOT/.env.runtime.example" ]; then
    LOCAL_ROOT="$CANDIDATE_ROOT"
  fi
fi

mkdir -p "$INSTALL_DIR"

if [ -n "$LOCAL_ROOT" ]; then
  log "Using local runtime compose from ${LOCAL_ROOT}"
  cp "$LOCAL_ROOT/docker-compose.runtime.yml" "$COMPOSE_DEST"
else
  log "Downloading runtime compose file"
  curl -fsSL "${RAW_BASE_URL}/docker-compose.runtime.yml" -o "$COMPOSE_DEST"
fi

if [ -f "$ENV_DEST" ]; then
  log "Keeping existing ${ENV_DEST}"
else
  if [ -n "$LOCAL_ROOT" ]; then
    log "Using local runtime env template from ${LOCAL_ROOT}"
    cp "$LOCAL_ROOT/.env.runtime.example" "$ENV_DEST"
  else
    log "Downloading default runtime env"
    curl -fsSL "${RAW_BASE_URL}/.env.runtime.example" -o "$ENV_DEST"
  fi
fi

if [ "$SKIP_OLLAMA_PULL" != "true" ]; then
  require_cmd ollama

  OLLAMA_MODEL="$(env_value_or_default "$ENV_DEST" "OLLAMA_MODEL" "llama3")"

  log "Ensuring Ollama model is available: ${OLLAMA_MODEL}"
  ollama pull "$OLLAMA_MODEL"
fi

if [ "$START_STACK" != "true" ]; then
  log "Files downloaded. Start manually with:"
  printf '  docker compose --env-file %q -f %q up -d\n' "$ENV_DEST" "$COMPOSE_DEST"
  exit 0
fi

PROFILE_ARGS=()
if [ "$ENABLE_CAPTURE_PROFILE" = "true" ]; then
  PROFILE_ARGS+=(--profile capture)
fi

log "Pulling latest images"
docker compose --env-file "$ENV_DEST" -f "$COMPOSE_DEST" "${PROFILE_ARGS[@]}" pull

log "Starting Albion Helper"
docker compose --env-file "$ENV_DEST" -f "$COMPOSE_DEST" "${PROFILE_ARGS[@]}" up -d

log "Albion Helper is running"
UI_PORT="$(env_value_or_default "$ENV_DEST" "ALBION_HELPER_UI_PORT" "5173")"
API_PORT="$(env_value_or_default "$ENV_DEST" "ALBION_HELPER_API_PORT" "8000")"
printf '  UI:  http://localhost:%s\n' "$UI_PORT"
printf '  API: http://localhost:%s/docs\n' "$API_PORT"

log "Manage the stack with:"
printf '  docker compose --env-file %q -f %q logs -f\n' "$ENV_DEST" "$COMPOSE_DEST"
printf '  docker compose --env-file %q -f %q down\n' "$ENV_DEST" "$COMPOSE_DEST"
