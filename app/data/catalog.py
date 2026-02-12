"""Item catalog loading and name resolution."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .config import ItemCatalogConfig

_ITEM_ID_RE = re.compile(r"^[A-Z0-9_@]+$")


@dataclass(frozen=True)
class ItemResolution:
    item_id: str
    strategy: str
    display_name: str | None = None


class ItemResolver:
    """Resolves human-readable item names to unique IDs."""

    def __init__(self, catalog_path: Path | None = None) -> None:
        self._catalog_path = catalog_path
        self._name_to_id: dict[str, str] = {}
        self._loaded = False

    @classmethod
    def from_env(cls) -> "ItemResolver":
        config = ItemCatalogConfig()
        return cls(config.path)

    def _load_catalog(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._catalog_path or not self._catalog_path.exists():
            return

        try:
            raw = json.loads(self._catalog_path.read_text(encoding="utf-8"))
        except Exception:
            return

        items = self._extract_items(raw)
        for item in items:
            unique_name = (
                item.get("UniqueName")
                or item.get("uniqueName")
                or item.get("unique_name")
                or item.get("name")
            )
            if not unique_name:
                continue

            unique_name = str(unique_name)
            self._name_to_id[unique_name.lower()] = unique_name

            localized_names = (
                item.get("LocalizedNames")
                or item.get("localizedNames")
                or item.get("localized_names")
            )
            if isinstance(localized_names, dict):
                for value in localized_names.values():
                    if value:
                        self._name_to_id[str(value).lower()] = unique_name

            display_name = item.get("LocalizedName") or item.get("localizedName")
            if display_name:
                self._name_to_id[str(display_name).lower()] = unique_name

    def _extract_items(self, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        if isinstance(raw, dict):
            for key in ("items", "Items", "data"):
                value = raw.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def resolve(self, name: str) -> ItemResolution | None:
        name = name.strip()
        if not name:
            return None

        self._load_catalog()

        lowered = name.lower()
        if lowered in self._name_to_id:
            item_id = self._name_to_id[lowered]
            return ItemResolution(item_id=item_id, strategy="catalog")

        if _ITEM_ID_RE.fullmatch(name.upper()):
            return ItemResolution(item_id=name.upper(), strategy="id")

        normalized = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
        if not normalized:
            return None
        return ItemResolution(item_id=normalized, strategy="normalized_guess", display_name=name)
