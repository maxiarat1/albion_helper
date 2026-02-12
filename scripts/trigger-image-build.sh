#!/usr/bin/env bash
set -euo pipefail

WORKFLOW_FILE="${WORKFLOW_FILE:-publish-images.yml}"
REF="${REF:-master}"
REPO="${REPO:-}"
WAIT_FOR_RUN="false"
TIMEOUT_S=1800
POLL_S=10
API_ROOT="https://api.github.com"

usage() {
  cat <<'EOF'
Trigger the GitHub Actions workflow that builds/publishes Docker images.

Usage:
  scripts/trigger-image-build.sh [options]

Options:
  --repo OWNER/REPO     GitHub repository (default: inferred from origin)
  --ref REF             Git ref to build (default: master)
  --workflow FILE       Workflow file name (default: publish-images.yml)
  --wait                Wait for workflow completion
  --timeout SECONDS     Max wait time when using --wait (default: 1800)
  --poll SECONDS        Poll interval when using --wait (default: 10)
  -h, --help            Show this help

Environment:
  GITHUB_TOKEN or GH_TOKEN must be set.
EOF
}

log() {
  printf '[trigger-image-build] %s\n' "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

infer_repo_from_origin() {
  local origin
  origin="$(git config --get remote.origin.url 2>/dev/null || true)"
  if [ -z "$origin" ]; then
    return 1
  fi

  if [[ "$origin" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    return 0
  fi

  return 1
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      REPO="${2:-}"
      shift 2
      ;;
    --ref)
      REF="${2:-}"
      shift 2
      ;;
    --workflow)
      WORKFLOW_FILE="${2:-}"
      shift 2
      ;;
    --wait)
      WAIT_FOR_RUN="true"
      shift
      ;;
    --timeout)
      TIMEOUT_S="${2:-}"
      shift 2
      ;;
    --poll)
      POLL_S="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd curl

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$TOKEN" ]; then
  echo "Set GITHUB_TOKEN or GH_TOKEN before running this script." >&2
  exit 1
fi

if [ -z "$REPO" ]; then
  infer_repo_from_origin || {
    echo "Unable to infer GitHub repo from origin. Pass --repo OWNER/REPO." >&2
    exit 1
  }
fi

DISPATCH_PAYLOAD="$(printf '{"ref":"%s"}' "$REF")"
START_EPOCH="$(date +%s)"

log "Dispatching ${WORKFLOW_FILE} on ${REPO} (ref=${REF})"
curl -fsS \
  -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${API_ROOT}/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches" \
  -d "${DISPATCH_PAYLOAD}" >/dev/null

log "Workflow dispatch sent."
log "View runs: https://github.com/${REPO}/actions/workflows/${WORKFLOW_FILE}"

if [ "$WAIT_FOR_RUN" != "true" ]; then
  exit 0
fi

require_cmd jq
DEADLINE=$((START_EPOCH + TIMEOUT_S))
RUN_ID=""

log "Waiting for run to appear..."
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  RESP="$(curl -fsS \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "${API_ROOT}/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?event=workflow_dispatch&per_page=20")"

  RUN_ID="$(echo "$RESP" | jq -r --argjson t "$START_EPOCH" '
    .workflow_runs
    | map(select((.created_at | fromdateiso8601) >= ($t - 10)))
    | sort_by(.created_at)
    | reverse
    | .[0].id // empty
  ')"

  if [ -n "$RUN_ID" ]; then
    break
  fi

  sleep "$POLL_S"
done

if [ -z "$RUN_ID" ]; then
  echo "Timed out waiting for a workflow run to be created." >&2
  exit 1
fi

log "Run detected: ${RUN_ID}"
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  RUN="$(curl -fsS \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "${API_ROOT}/repos/${REPO}/actions/runs/${RUN_ID}")"

  STATUS="$(echo "$RUN" | jq -r '.status')"
  CONCLUSION="$(echo "$RUN" | jq -r '.conclusion // ""')"
  URL="$(echo "$RUN" | jq -r '.html_url')"

  log "Run status: ${STATUS}${CONCLUSION:+ (${CONCLUSION})}"
  if [ "$STATUS" = "completed" ]; then
    if [ "$CONCLUSION" = "success" ]; then
      log "Workflow finished successfully: ${URL}"
      exit 0
    fi
    echo "Workflow failed: ${URL}" >&2
    exit 1
  fi

  sleep "$POLL_S"
done

echo "Timed out waiting for workflow completion." >&2
exit 1
