"""Auto-download game data files from ao-bin-dumps GitHub repo."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_GITHUB_RAW = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master"

GAME_FILES = {
    "items.json": f"{_GITHUB_RAW}/items.json",
    "localization.json": f"{_GITHUB_RAW}/localization.json",
    "spells.json": f"{_GITHUB_RAW}/spells.json",
    "achievements.json": f"{_GITHUB_RAW}/achievements.json",
    "gamedata.json": f"{_GITHUB_RAW}/gamedata.json",
    "characters.json": f"{_GITHUB_RAW}/characters.json",
}


def _missing_game_files(data_dir: Path) -> dict[str, str]:
    return {
        name: url
        for name, url in GAME_FILES.items()
        if not (data_dir / name).exists()
    }


def ensure_game_files(data_dir: Path) -> None:
    """Download game data files if they don't exist locally."""
    missing = _missing_game_files(data_dir)
    if not missing:
        return

    data_dir.mkdir(parents=True, exist_ok=True)
    logger.info("[GameData] Downloading %s game file(s) to %s", len(missing), data_dir)

    with httpx.Client(timeout=120) as client:
        for name, url in missing.items():
            target = data_dir / name
            logger.info("[GameData] Downloading %s...", name)
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with target.open("wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        f.write(chunk)
            logger.info(
                "[GameData] Saved %s (%.1f MB)",
                name,
                target.stat().st_size / 1024 / 1024,
            )
