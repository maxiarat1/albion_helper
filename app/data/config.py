"""Configuration for Albion Online Data Project (AODP) integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

# Regional API endpoints for AODP
REGION_URLS = {
    "europe": "https://europe.albion-online-data.com",
    "west": "https://west.albion-online-data.com",  # Americas
    "east": "https://east.albion-online-data.com",  # Asia
}

DEFAULT_REGION = "europe"
_DEFAULT_GAME_DATA_DIR = Path("data/gamedata")
_BUNDLED_GAME_DATA_DIR = Path("docs/ao-bin-dumps")


def _get_base_url() -> str:
    """Get base URL from env var or derive from region."""
    explicit_url = os.getenv("AODP_BASE_URL")
    if explicit_url:
        return explicit_url
    region = os.getenv("AODP_REGION", DEFAULT_REGION).lower()
    return REGION_URLS.get(region, REGION_URLS[DEFAULT_REGION])


def _get_game_data_dir() -> Path:
    """Resolve game-data directory.

    Priority:
    1. Explicit `GAME_DATA_DIR` env override.
    2. Bundled repository data (`docs/ao-bin-dumps`) when present.
    3. Writable runtime cache path (`data/gamedata`).
    """
    explicit = os.getenv("GAME_DATA_DIR")
    if explicit:
        return Path(explicit)
    if _BUNDLED_GAME_DATA_DIR.exists():
        return _BUNDLED_GAME_DATA_DIR
    return _DEFAULT_GAME_DATA_DIR


@dataclass(frozen=True)
class AODPConfig:
    region: str = field(default_factory=lambda: os.getenv("AODP_REGION", DEFAULT_REGION).lower())
    base_url: str = field(default_factory=_get_base_url)
    timeout_s: float = float(os.getenv("AODP_TIMEOUT_S", "15"))
    cache_ttl_s: float = float(os.getenv("AODP_CACHE_TTL_S", "60"))
    freshness_ttl_s: float = float(os.getenv("AODP_FRESHNESS_TTL_S", "900"))  # 15 minutes


@dataclass(frozen=True)
class GameDataConfig:
    dir: Path = field(default_factory=_get_game_data_dir)


@dataclass(frozen=True)
class ItemCatalogConfig:
    path: Path | None = (
        Path(os.getenv("ITEM_CATALOG_PATH")) if os.getenv("ITEM_CATALOG_PATH") else None
    )
