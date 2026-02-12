"""Application service for item label resolution."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

_TIER_PREFIX_RE = re.compile(r"^T([1-8])_")


class ItemLabelApplicationService:
    def __init__(self, *, game_db: Any) -> None:
        self._game_db = game_db

    def get_labels(self, ids: str) -> dict[str, Any]:
        item_ids: list[str] = []
        seen: set[str] = set()

        for raw in ids.split(","):
            item_id = raw.strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            item_ids.append(item_id)

        if not item_ids:
            raise ValueError("Query parameter 'ids' is required")
        if len(item_ids) > 200:
            raise ValueError("Maximum 200 item IDs per request")

        return {
            "count": len(item_ids),
            "items": [self._build_item_label(item_id) for item_id in item_ids],
        }

    @staticmethod
    def _parse_tier_from_item_id(item_id: str) -> int | None:
        match = _TIER_PREFIX_RE.match(item_id)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _parse_enchantment_from_item_id(item_id: str) -> int:
        if "@" not in item_id:
            return 0
        suffix = item_id.rsplit("@", 1)[-1]
        try:
            return int(suffix)
        except ValueError:
            return 0

    @staticmethod
    def _item_display_name(item: Any) -> str:
        names = item.localized_names or {}
        for key in ("EN-US", "EN", "en-US", "en"):
            if names.get(key):
                return str(names[key])
        if names:
            return str(next(iter(names.values())))
        return item.unique_name

    @staticmethod
    def _item_icon_url(item_id: str) -> str:
        return f"https://render.albiononline.com/v1/item/{quote(item_id, safe='')}.png"

    def _item_tier_and_enchantment(self, item_id: str, item: Any | None = None) -> tuple[int | None, int]:
        tier = (item.tier if item else None) or self._parse_tier_from_item_id(item_id)
        enchantment = (item.enchantment if item else 0) or self._parse_enchantment_from_item_id(item_id)
        return tier, enchantment

    def _build_item_label(self, item_id: str) -> dict[str, Any]:
        item = self._game_db.get_item(item_id)
        tier, enchantment = self._item_tier_and_enchantment(item_id, item)
        if item:
            return {
                "id": item_id,
                "found": True,
                "display_name": self._item_display_name(item),
                "tier": tier,
                "enchantment": enchantment,
                "icon_url": self._item_icon_url(item_id),
            }

        return {
            "id": item_id,
            "found": False,
            "display_name": item_id,
            "tier": tier,
            "enchantment": enchantment,
            "icon_url": self._item_icon_url(item_id),
        }
