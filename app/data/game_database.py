"""Game static database service.

Loads and indexes game data from ao-bin-dumps for fast lookups.
Provides item info, crafting recipes, and search functionality.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import GameDataConfig
from .gamedata import ensure_game_files

logger = logging.getLogger(__name__)

GAME_DATA_DIR = GameDataConfig().dir
ITEMS_FILE = GAME_DATA_DIR / "items.json"


@dataclass
class CraftResource:
    """A single crafting resource requirement."""
    item_id: str
    count: int
    max_return: int = 0


@dataclass
class CraftingRecipe:
    """Crafting recipe for an item."""
    silver_cost: int = 0
    crafting_focus: int = 0
    time_seconds: float = 0
    resources: list[CraftResource] = field(default_factory=list)


@dataclass
class ItemInfo:
    """Information about a game item."""
    unique_name: str
    tier: int = 0
    enchantment: int = 0
    category: str = ""
    subcategory: str = ""
    slot_type: str = ""
    weight: float = 0
    max_quality: int = 1
    item_power: int = 0
    ability_power: int = 0
    two_handed: bool = False
    ip_progression_type: str = ""
    combat_spec_achievement: str = ""
    spell_list: list[str] = field(default_factory=list)
    enchantment_ips: dict[int, int] = field(default_factory=dict)
    localized_names: dict[str, str] = field(default_factory=dict)
    crafting_recipes: list[CraftingRecipe] = field(default_factory=list)
    consume_spell: str = ""  # @consumespell for food/potions
    attack_damage: float = 0  # weapon auto-attack
    attack_speed: float = 0
    attack_range: float = 0
    attack_type: str = ""  # "melee", "ranged"
    raw_data: dict[str, Any] = field(default_factory=dict)


class GameDatabase:
    """Service for querying game static data."""

    def __init__(self, items_path: Path | None = None) -> None:
        self._items_path = items_path or ITEMS_FILE
        self._items: dict[str, ItemInfo] = {}
        self._name_index: dict[str, str] = {}  # lowercase name -> unique_name
        self._loaded = False

    def _ensure_loaded(self) -> None:
        """Load data if not already loaded."""
        if self._loaded:
            return
        self._loaded = True
        ensure_game_files(self._items_path.parent)
        self._load_items()
        logger.info("[GameDB] Loaded %s items", len(self._items))

    def _load_items(self) -> None:
        """Load and index all items from items.json."""
        if not self._items_path.exists():
            logger.warning("[GameDB] Items file not found: %s", self._items_path)
            return

        try:
            raw = json.loads(self._items_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[GameDB] Failed to load items: %s", exc)
            return

        items_root = raw.get("items", {})
        
        # Process each item category
        categories = [
            "equipmentitem", "weapon", "mount", "simpleitem", 
            "consumableitem", "furnitureitem", "farmableitem"
        ]
        
        for category in categories:
            items_list = items_root.get(category, [])
            if isinstance(items_list, dict):
                items_list = [items_list]
            if not isinstance(items_list, list):
                continue
                
            for item_data in items_list:
                if not isinstance(item_data, dict):
                    continue
                item = self._parse_item(item_data, category)
                if item:
                    self._items[item.unique_name] = item
                    self._index_item(item)

    def _parse_item(self, data: dict[str, Any], category: str) -> ItemInfo | None:
        """Parse raw item data into ItemInfo."""
        unique_name = data.get("@uniquename", "")
        if not unique_name:
            return None

        # Parse tier and enchantment from name (e.g., T6_2H_BOW@2 = tier 6, enchant 2)
        tier = 0
        enchant = 0
        tier_str = data.get("@tier", "")
        if tier_str:
            try:
                tier = int(tier_str)
            except ValueError:
                pass
        if "@" in unique_name:
            parts = unique_name.split("@")
            try:
                enchant = int(parts[-1])
            except ValueError:
                pass

        # Parse localized names
        localized = {}
        loc_names = data.get("LocalizedNames") or data.get("localizeddescriptions", {})
        if isinstance(loc_names, dict):
            for lang, name in loc_names.items():
                if name:
                    localized[lang.lstrip("@")] = str(name)

        # Parse crafting recipes
        recipes = []
        craft_reqs = data.get("craftingrequirements", [])
        if isinstance(craft_reqs, dict):
            craft_reqs = [craft_reqs]
        for req in craft_reqs:
            if isinstance(req, dict):
                recipe = self._parse_recipe(req)
                if recipe:
                    recipes.append(recipe)

        # Parse spell list from craftingspelllist
        spell_list: list[str] = []
        csl = data.get("craftingspelllist", {})
        if isinstance(csl, dict):
            spells = csl.get("craftspell", [])
            if isinstance(spells, dict):
                spells = [spells]
            for sp in spells:
                if isinstance(sp, dict) and sp.get("@uniquename"):
                    spell_list.append(sp["@uniquename"])

        # Parse enchantment IP values
        enchantment_ips: dict[int, int] = {}
        enchants_data = data.get("enchantments", {})
        if isinstance(enchants_data, dict):
            ench_list = enchants_data.get("enchantment", [])
            if isinstance(ench_list, dict):
                ench_list = [ench_list]
            for e in ench_list:
                if isinstance(e, dict):
                    try:
                        lvl = int(e.get("@enchantmentlevel", 0))
                        ip = int(e.get("@itempower", 0))
                        if lvl and ip:
                            enchantment_ips[lvl] = ip
                    except (ValueError, TypeError):
                        pass

        return ItemInfo(
            unique_name=unique_name,
            tier=tier,
            enchantment=enchant,
            category=category,
            subcategory=data.get("@shopsubcategory1", ""),
            slot_type=data.get("@slottype", ""),
            weight=float(data.get("@weight", 0) or 0),
            max_quality=int(data.get("@maxqualitylevel", 1) or 1),
            item_power=int(data.get("@itempower", 0) or 0),
            ability_power=int(data.get("@abilitypower", 0) or 0),
            two_handed=str(data.get("@twohanded", "false")).lower() == "true",
            ip_progression_type=data.get("@itempowerprogressiontype", ""),
            combat_spec_achievement=data.get("@combatspecachievement", ""),
            spell_list=spell_list,
            enchantment_ips=enchantment_ips,
            localized_names=localized,
            crafting_recipes=recipes,
            consume_spell=str(data.get("@consumespell", "") or ""),
            attack_damage=float(data.get("@attackdamage", 0) or 0),
            attack_speed=float(data.get("@attackspeed", 0) or 0),
            attack_range=float(data.get("@attackrange", 0) or 0),
            attack_type=str(data.get("@attacktype", "") or ""),
            raw_data=data,
        )

    def _parse_recipe(self, data: dict[str, Any]) -> CraftingRecipe | None:
        """Parse crafting requirements into a recipe."""
        resources = []
        craft_res = data.get("craftresource", [])
        if isinstance(craft_res, dict):
            craft_res = [craft_res]
        
        for res in craft_res:
            if isinstance(res, dict):
                item_id = res.get("@uniquename", "")
                count = int(res.get("@count", 0) or 0)
                max_ret = int(res.get("@maxreturnamount", 0) or 0)
                if item_id and count > 0:
                    resources.append(CraftResource(item_id, count, max_ret))

        if not resources:
            return None

        return CraftingRecipe(
            silver_cost=int(data.get("@silver", 0) or 0),
            crafting_focus=int(data.get("@craftingfocus", 0) or 0),
            time_seconds=float(data.get("@time", 0) or 0),
            resources=resources,
        )

    def _index_item(self, item: ItemInfo) -> None:
        """Add item to search indexes."""
        # Index by unique name (lowercase)
        self._name_index[item.unique_name.lower()] = item.unique_name
        
        # Index by localized names
        for name in item.localized_names.values():
            if name:
                self._name_index[name.lower()] = item.unique_name

    def get_item(self, name_or_id: str) -> ItemInfo | None:
        """Look up item by name or ID."""
        self._ensure_loaded()
        
        # Try direct lookup
        if name_or_id in self._items:
            return self._items[name_or_id]
        
        # Try lowercase index
        lowered = name_or_id.lower()
        if lowered in self._name_index:
            return self._items.get(self._name_index[lowered])
        
        # Try partial match
        for key, item_id in self._name_index.items():
            if lowered in key or key in lowered:
                return self._items.get(item_id)
        
        return None

    def get_crafting_recipe(self, name_or_id: str, recipe_index: int = 0) -> dict[str, Any] | None:
        """Get crafting recipe for an item."""
        item = self.get_item(name_or_id)
        if not item or not item.crafting_recipes:
            return None
        
        if recipe_index >= len(item.crafting_recipes):
            recipe_index = 0
        
        recipe = item.crafting_recipes[recipe_index]
        return {
            "item_id": item.unique_name,
            "tier": item.tier,
            "silver_cost": recipe.silver_cost,
            "crafting_focus": recipe.crafting_focus,
            "time_seconds": recipe.time_seconds,
            "materials": [
                {"item_id": r.item_id, "count": r.count}
                for r in recipe.resources
            ],
            "recipe_count": len(item.crafting_recipes),
        }

    def get_item_spell_entries(self, name_or_id: str) -> list[dict[str, str]]:
        """Return item spell entries with resolved craftingspelllist references.

        Output entries are normalized as:
        - spell_id: spell unique name
        - slot: Q/W/E/passive/consumable
        """
        self._ensure_loaded()
        item = self.get_item(name_or_id)
        if not item:
            return []
        entries = self._extract_item_spell_entries(item.raw_data.get("craftingspelllist"), seen_refs=set())
        # Consumables (food/potions) use @consumespell instead of craftingspelllist
        if not entries and item.consume_spell:
            entries = [{"spell_id": item.consume_spell, "slot": "consumable"}]
        return entries

    def _extract_item_spell_entries(
        self,
        craftingspelllist: dict[str, Any] | None,
        *,
        seen_refs: set[str],
    ) -> list[dict[str, str]]:
        """Extract craftspell entries and recursively resolve @reference nodes."""
        if not isinstance(craftingspelllist, dict):
            return []

        slot_map = {"1": "Q", "2": "W", "3": "E"}
        entries: list[dict[str, str]] = []
        seen_spell_slots: set[tuple[str, str]] = set()

        # Some items inherit spell lists from another item via @reference.
        reference = craftingspelllist.get("@reference", "")
        if isinstance(reference, str) and reference and reference not in seen_refs:
            seen_refs.add(reference)
            ref_item = self._items.get(reference)
            if ref_item:
                inherited_entries = self._extract_item_spell_entries(
                    ref_item.raw_data.get("craftingspelllist"),
                    seen_refs=seen_refs,
                )
                for inherited in inherited_entries:
                    key = (inherited.get("spell_id", ""), inherited.get("slot", "passive"))
                    if key[0] and key not in seen_spell_slots:
                        seen_spell_slots.add(key)
                        entries.append(inherited)

        craftspell = craftingspelllist.get("craftspell", [])
        if isinstance(craftspell, dict):
            craftspell = [craftspell]
        if not isinstance(craftspell, list):
            return entries

        for spell_entry in craftspell:
            if not isinstance(spell_entry, dict):
                continue
            spell_id = spell_entry.get("@uniquename", "")
            if not isinstance(spell_id, str) or not spell_id:
                continue
            slot = slot_map.get(str(spell_entry.get("@slots", "")), "passive")
            key = (spell_id, slot)
            if key in seen_spell_slots:
                continue
            seen_spell_slots.add(key)
            entries.append({"spell_id": spell_id, "slot": slot})

        return entries

    def search_items(
        self,
        query: str = "",
        category: str = "",
        tier: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for items matching criteria."""
        self._ensure_loaded()
        
        results = []
        query_lower = query.lower()
        
        for item in self._items.values():
            # Filter by category
            if category and item.category != category:
                continue
            
            # Filter by tier
            if tier is not None and item.tier != tier:
                continue
            
            # Filter by query (name match)
            if query:
                name_match = query_lower in item.unique_name.lower()
                loc_match = any(query_lower in n.lower() for n in item.localized_names.values())
                if not (name_match or loc_match):
                    continue
            
            results.append({
                "unique_name": item.unique_name,
                "tier": item.tier,
                "category": item.category,
                "subcategory": item.subcategory,
                "has_recipe": len(item.crafting_recipes) > 0,
            })
            
            if len(results) >= limit:
                break
        
        return results


# Default instance
default_game_database = GameDatabase()
