#!/bin/sh
set -e

BINARY_PATH="/data/albiondata-client"
VERSION_FILE="/data/version"
CHECKSUM_FILE="/data/checksum"
GITHUB_API="https://api.github.com/repos/ao-data/albiondata-client/releases/latest"
ASSET_NAME="update-linux-amd64.gz"

# Pinned release -- update both tag and checksum together.
PINNED_TAG="0.1.48"
PINNED_SHA256="0d0fa645ec4afff015395d3336e804cb4012774c0a5534a48be56a8038fc1d0d"

log() { echo "[albiondata-client] $*"; }

get_installed_version() {
    if [ -f "$VERSION_FILE" ]; then
        cat "$VERSION_FILE"
    else
        echo ""
    fi
}

verify_checksum() {
    local file="$1"
    local expected="$2"
    local actual
    actual=$(sha256sum "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        log "ERROR: SHA256 mismatch!"
        log "  Expected: $expected"
        log "  Got:      $actual"
        rm -f "$file"
        return 1
    fi
    log "SHA256 verified: $actual"
    return 0
}

fetch_latest_tag() {
    curl -sf --max-time 15 "$GITHUB_API" 2>/dev/null | jq -r '.tag_name' 2>/dev/null
}

download_binary() {
    local tag="$1"
    local expected_hash="$2"
    local url="https://github.com/ao-data/albiondata-client/releases/download/${tag}/${ASSET_NAME}"

    log "Downloading ${ASSET_NAME} (${tag})..."
    curl -fSL --max-time 120 -o /tmp/binary.gz "$url"

    if [ -n "$expected_hash" ]; then
        if ! verify_checksum /tmp/binary.gz "$expected_hash"; then
            log "ERROR: Integrity check failed. Aborting."
            exit 1
        fi
    else
        log "WARNING: No checksum available for ${tag} -- skipping verification."
    fi

    gunzip -f /tmp/binary.gz
    mv /tmp/binary "$BINARY_PATH"
    chmod +x "$BINARY_PATH"
    echo "$tag" > "$VERSION_FILE"
    log "Installed version ${tag}"
}

# --- Main ---

log "Checking for updates..."

LATEST_TAG=$(fetch_latest_tag) || LATEST_TAG=""

# Determine which tag and checksum to use.
# If the latest upstream matches our pinned tag, use the pinned checksum.
# If upstream is newer, download it but warn about missing checksum.
if [ -n "$LATEST_TAG" ] && [ "$LATEST_TAG" != "null" ]; then
    TARGET_TAG="$LATEST_TAG"
    if [ "$LATEST_TAG" = "$PINNED_TAG" ]; then
        TARGET_HASH="$PINNED_SHA256"
    else
        log "WARNING: Upstream ${LATEST_TAG} differs from pinned ${PINNED_TAG}."
        log "WARNING: Update PINNED_TAG and PINNED_SHA256 in entrypoint.sh to verify the new release."
        TARGET_HASH=""
    fi
else
    log "WARNING: Could not reach GitHub API, using pinned version ${PINNED_TAG}"
    TARGET_TAG="$PINNED_TAG"
    TARGET_HASH="$PINNED_SHA256"
fi

INSTALLED=$(get_installed_version)

if [ "$TARGET_TAG" = "$INSTALLED" ] && [ -x "$BINARY_PATH" ]; then
    log "Already up to date (${INSTALLED})"
else
    if [ -n "$INSTALLED" ]; then
        log "Updating: ${INSTALLED} -> ${TARGET_TAG}"
    else
        log "First install: ${TARGET_TAG}"
    fi
    download_binary "$TARGET_TAG" "$TARGET_HASH"
fi

log "Starting albiondata-client..."
exec "$BINARY_PATH" "$@"
