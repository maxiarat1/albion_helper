"""MCP tools for game static data.

Provides tools for querying item information, crafting recipes,
and searching the game database.
"""

from __future__ import annotations

from typing import Any

from app.data.activity_catalog import default_activity_catalog
from app.data.destiny_database import default_destiny_database
from app.data.game_database import default_game_database
from app.data.item_resolver import smart_resolver
from app.data.spell_database import default_spell_database
from app.mcp.registry import Param, tool
from app.mcp.tool_templates import READ_ONLY_LOCAL, item_param, limit_param, query_param

from ._resolve import (
    attach_smart_resolution,
    capped_limit,
    normalize_item_input,
    resolve_item_smart,
    resolve_with_smart_item,
)

game_db = default_game_database
activity_catalog = default_activity_catalog
spell_db = default_spell_database
destiny_db = default_destiny_database

_ITEM_NUMERIC_MODIFIERS: dict[str, str] = {
    "@hitpointsmax": "max_hp",
    "@energymax": "max_energy",
    "@physicalarmor": "physical_armor",
    "@magicresistance": "magic_resistance",
    "@movespeedbonus": "move_speed_bonus",
    "@attackspeedbonus": "attack_speed_bonus",
    "@healmodifier": "healing_modifier",
    "@energycostreduction": "energy_cost_reduction",
    "@magiccooldownreduction": "magic_cooldown_reduction",
    "@magiccasttimereduction": "cast_time_reduction",
    "@physicalattackdamagebonus": "physical_attack_damage_bonus",
    "@magicattackdamagebonus": "magic_attack_damage_bonus",
    "@physicalspelldamagebonus": "physical_spell_damage_bonus",
    "@magicspelldamagebonus": "magic_spell_damage_bonus",
    "@crowdcontrolresistance": "crowd_control_resistance",
    "@bonusdefensevsplayers": "defense_vs_players_bonus",
    "@bonusdefensevsmobs": "defense_vs_mobs_bonus",
    "@bonusccdurationvsplayers": "cc_duration_vs_players_bonus",
    "@bonusccdurationvsmobs": "cc_duration_vs_mobs_bonus",
    "@threatbonus": "threat_bonus",
}

_QUALITY_NAMES = {
    1: "Normal",
    2: "Good",
    3: "Outstanding",
    4: "Excellent",
    5: "Masterpiece",
}
_OPTIONAL_SPELL_FIELDS = (
    "category",
    "cooldown",
    "energy_cost",
    "cast_range",
    "casting_time",
    "damage",
    "effects",
    "buffs",
    "crowd_control",
)


def _to_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _extract_maxload_buffs(item_effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buffs: list[dict[str, Any]] = []
    seen: set[tuple[str, float, bool]] = set()
    for effect in item_effects:
        source_spell = str(effect.get("spell_id", "") or "")
        effect_buffs = effect.get("buffs")
        if not isinstance(effect_buffs, list):
            continue
        for buff in effect_buffs:
            if not isinstance(buff, dict):
                continue
            if buff.get("type") != "maxload":
                continue
            values = buff.get("values")
            if not isinstance(values, dict):
                continue
            raw_value = _to_number(values.get("value"))
            if raw_value is None:
                continue
            value = float(raw_value)
            ignore_ability_scaling = _to_bool(values.get("ignoreabilitypowerscaling"))
            key = (source_spell, value, ignore_ability_scaling)
            if key in seen:
                continue
            seen.add(key)
            buffs.append({
                "source_spell": source_spell,
                "value": value,
                "ignore_ability_power_scaling": ignore_ability_scaling,
            })
    return buffs


def _build_item_power_profiles(
    item: Any,
) -> tuple[dict[int, int], dict[int, int], list[dict[str, Any]]] | None:
    """Build reusable per-enchantment/per-quality item power rows."""
    enchantment_item_power = {0: int(item.item_power)}
    enchantment_item_power.update({int(k): int(v) for k, v in item.enchantment_ips.items()})
    quality_levels = list(range(1, min(int(item.max_quality), 5) + 1))

    try:
        quality_ip_bonus = {quality: destiny_db.get_quality_bonus(quality) for quality in quality_levels}
    except Exception:
        return None

    profiles: list[dict[str, Any]] = []
    for enchantment, enchant_ip in sorted(enchantment_item_power.items()):
        for quality in quality_levels:
            item_power = int(enchant_ip + quality_ip_bonus[quality])
            profiles.append({
                "tier": f"{item.tier}.{enchantment}",
                "enchantment": enchantment,
                "quality": quality,
                "quality_name": _QUALITY_NAMES.get(quality, f"Q{quality}"),
                "item_power": item_power,
            })
    return enchantment_item_power, quality_ip_bonus, profiles


def _build_max_load_payload(item: Any, item_effects: list[dict[str, Any]]) -> dict[str, Any] | None:
    maxload_buffs = _extract_maxload_buffs(item_effects)
    if not maxload_buffs:
        return None

    try:
        progression_slot = item.ip_progression_type or item.slot_type
        ip_scaling = destiny_db.get_ip_scaling(progression_slot) if progression_slot else None
        ability_power_progression = (
            float(ip_scaling.ability_power_progression) if ip_scaling else 1.0
        )
        ability_config = destiny_db.get_ability_power_progression()
        base_damage = float(ability_config.base_damage)
        base_load = float(ability_config.base_load)
        load_progression = float(ability_config.load_progression)
    except Exception:
        # Keep item_info resilient even when destiny data is unavailable.
        return None

    profile_data = _build_item_power_profiles(item)
    if not profile_data:
        return None
    enchantment_item_power, quality_ip_bonus, item_power_profiles = profile_data

    profiles: list[dict[str, Any]] = []
    for buff in maxload_buffs:
        buff_value = float(buff["value"])
        ignore_ability_scaling = bool(buff["ignore_ability_power_scaling"])
        values: list[dict[str, Any]] = []

        for profile in item_power_profiles:
            item_power = int(profile["item_power"])
            if ignore_ability_scaling:
                scaled_value = buff_value
            else:
                ability_power_at_ip = float(item.ability_power) * (
                    ability_power_progression ** (item_power / 100.0)
                )
                scaled_value = buff_value * base_load * (
                    ((ability_power_at_ip / base_damage) ** load_progression) - 1.0
                )
            values.append({
                **profile,
                "max_load_kg": int(round(scaled_value)),
            })

        profiles.append({
            "source_spell": buff["source_spell"],
            "buff_value": buff_value,
            "ignore_ability_power_scaling": ignore_ability_scaling,
            "values": values,
        })

    payload: dict[str, Any] = {
        "formula": (
            "max_load = round(buff_value * base_load * "
            "((base_ability_power * ability_power_progression^(item_power/100) "
            "/ base_damage)^load_progression - 1))"
        ),
        "constants": {
            "base_ability_power": float(item.ability_power),
            "ability_power_progression": ability_power_progression,
            "base_damage": base_damage,
            "base_load": base_load,
            "load_progression": load_progression,
            "quality_item_power_bonus": quality_ip_bonus,
        },
        "enchantment_item_power": enchantment_item_power,
    }
    if len(profiles) == 1:
        payload.update(profiles[0])
    else:
        payload["profiles"] = profiles
    return payload


def _build_cape_energy_payload(item: Any) -> dict[str, Any] | None:
    if item.slot_type != "cape":
        return None

    try:
        ip_scaling = destiny_db.get_ip_scaling(item.ip_progression_type or "cape")
        if not ip_scaling:
            return None
        energy_progression = float(ip_scaling.energy_progression)
        energy_share = destiny_db.get_energy_share("cape")
        if energy_share in (None, 0):
            return None
        base_stats = destiny_db.get_base_stats()
        base_energy = float(base_stats.get("energy", 0.0))
        base_energy_regen = float(base_stats.get("energy_regen", 0.0))
    except Exception:
        # Keep item_info resilient even when destiny data is unavailable.
        return None

    profile_data = _build_item_power_profiles(item)
    if not profile_data:
        return None
    enchantment_item_power, quality_ip_bonus, item_power_profiles = profile_data

    base_energy_from_slot = base_energy * float(energy_share)
    base_energy_regen_from_slot = base_energy_regen * float(energy_share)
    values: list[dict[str, Any]] = []
    for profile in item_power_profiles:
        item_power = int(profile["item_power"])
        scale_factor = (energy_progression ** (item_power / 100.0)) - 1.0
        values.append({
            **profile,
            "max_energy": int(round(base_energy_from_slot * scale_factor)),
            "energy_regeneration_per_second": round(
                base_energy_regen_from_slot * scale_factor, 2
            ),
        })

    return {
        "formula": (
            "value = round(base_stat * energy_share * "
            "(energy_progression^(item_power/100) - 1))"
        ),
        "constants": {
            "energy_progression": energy_progression,
            "energy_share": float(energy_share),
            "base_energy": base_energy,
            "base_energy_regen_per_second": base_energy_regen,
            "quality_item_power_bonus": quality_ip_bonus,
        },
        "enchantment_item_power": enchantment_item_power,
        "values": values,
    }


def _item_stats_payload(
    item: Any, *, item_effects: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    enchantment_ips = {0: item.item_power}
    enchantment_ips.update(item.enchantment_ips)

    modifiers: dict[str, int | float] = {}
    raw_data = item.raw_data if isinstance(item.raw_data, dict) else {}
    for raw_key, output_key in _ITEM_NUMERIC_MODIFIERS.items():
        numeric = _to_number(raw_data.get(raw_key))
        if numeric in (None, 0, 0.0):
            continue
        modifiers[output_key] = numeric

    payload: dict[str, Any] = {
        "item_power": item.item_power,
        "ability_power": item.ability_power,
        "two_handed": item.two_handed,
        "ip_progression_type": item.ip_progression_type,
        "combat_spec_node": item.combat_spec_achievement,
        "enchantment_item_power": enchantment_ips,
    }
    if modifiers:
        payload["modifiers"] = modifiers
    # Weapon auto-attack stats
    if item.attack_damage:
        payload["attack_damage"] = item.attack_damage
    if item.attack_speed:
        payload["attack_speed"] = item.attack_speed
    if item.attack_range:
        payload["attack_range"] = item.attack_range
    if item.attack_type:
        payload["attack_type"] = item.attack_type
    if item_effects is not None:
        max_load = _build_max_load_payload(item, item_effects)
        if max_load:
            payload["max_load"] = max_load
    cape_energy = _build_cape_energy_payload(item)
    if cape_energy:
        payload["cape_energy"] = cape_energy
    return payload


def _item_effects_payload(item: Any) -> list[dict[str, Any]]:
    spell_entries = game_db.get_item_spell_entries(item.unique_name)
    effects: list[dict[str, Any]] = []

    for spell_entry in spell_entries:
        spell_id = spell_entry["spell_id"]
        resolved = spell_db.resolve_spell_chain(spell_id)
        if not resolved:
            effects.append({
                "spell_id": spell_id,
                "slot": spell_entry["slot"],
            })
            continue

        payload: dict[str, Any] = {
            "spell_id": resolved["spell_id"],
            "name": resolved["display_name"],
            "slot": spell_entry["slot"],
        }
        for field in _OPTIONAL_SPELL_FIELDS:
            value = resolved.get(field)
            if value:
                payload[field] = value
        effects.append(payload)

    return effects


def _activity_hint(query: str, limit: int = 3) -> dict[str, Any] | None:
    """Return activity guidance when a query appears to be a game mode, not an item."""
    matches = activity_catalog.search(query=query, limit=limit)
    if not matches:
        return None
    return {
        "message": (
            "Query appears to reference an activity/game mode rather than an item. "
            "Use `search_activities` for activity lookup."
        ),
        "count": len(matches),
        "activities": matches,
    }


@tool(
    name="item_info",
    description="Look up detailed information about a game item including tier, category, stats, and crafting availability.",
    params=[
        item_param(
            required=True,
            description="Item name or unique ID. Accepts: display name, tier shorthand, or unique ID.",
        ),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def item_info(args: dict[str, Any]) -> dict[str, Any]:
    """Look up detailed information about a game item."""
    name_or_id = args.get("item", "")
    item, resolution_note = resolve_with_smart_item(name_or_id, game_db.get_item)

    if not item:
        return {
            "found": False,
            "query": name_or_id,
            "error": f"Item '{name_or_id}' not found in game database",
        }

    item_effects = _item_effects_payload(item)
    item_stats = _item_stats_payload(item, item_effects=item_effects)

    result: dict[str, Any] = {
        "found": True,
        "unique_name": item.unique_name,
        "tier": item.tier,
        "enchantment": item.enchantment,
        "category": item.category,
        "subcategory": item.subcategory,
        "slot_type": item.slot_type,
        "weight": item.weight,
        "max_quality": item.max_quality,
        "has_crafting_recipe": len(item.crafting_recipes) > 0,
        "localized_names": item.localized_names,
        "item_stats": item_stats,
        "item_effects": item_effects,
    }

    return attach_smart_resolution(result, resolution_note)


@tool(
    name="crafting_recipe",
    description="Get crafting requirements for an item, including materials, silver cost, and focus cost.",
    params=[
        item_param(required=True, description="Item name or unique ID to get recipe for"),
        Param(
            "recipe_index",
            "integer",
            "Recipe variant index (some items have multiple recipes). Default: 0",
            minimum=0,
        ),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def crafting_recipe(args: dict[str, Any]) -> dict[str, Any]:
    """Get crafting requirements for an item."""
    name_or_id = args.get("item", "")
    recipe_index = args.get("recipe_index", 0)
    recipe, resolution_note = resolve_with_smart_item(
        name_or_id,
        lambda item_id: game_db.get_crafting_recipe(item_id, recipe_index),
    )

    if not recipe:
        return {
            "found": False,
            "query": name_or_id,
            "error": f"No crafting recipe found for '{name_or_id}'",
        }

    return {"found": True, **attach_smart_resolution(recipe, resolution_note)}


@tool(
    name="search_items",
    description="Search for items by name, category, or tier. Returns a list of matching items.",
    params=[
        query_param(description="Search query to match against item names"),
        Param("category", "string", "Filter by category: 'weapon', 'equipmentitem', 'simpleitem', 'mount', etc."),
        Param("tier", "integer", "Filter by tier (1-8)", minimum=1, maximum=8),
        limit_param(description="Maximum results to return (default 20, max 50)", maximum=50),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def search_items(args: dict[str, Any]) -> dict[str, Any]:
    """Search for items by name, category, or tier."""
    query = args.get("query", "")
    category = args.get("category", "")
    tier = args.get("tier")
    limit = capped_limit(args.get("limit"), default=20, maximum=50)

    results = game_db.search_items(
        query=query,
        category=category,
        tier=tier,
        limit=limit,
    )

    response = {
        "query": query,
        "category": category,
        "tier": tier,
        "count": len(results),
        "items": results,
    }
    if query and not results:
        hint = _activity_hint(query)
        if hint:
            response["activity_hint"] = hint
    return response


@tool(
    name="resolve_item",
    description="Resolve an item query to specific item IDs using fuzzy matching. Handles tier prefixes, shorthand, typos, and disambiguation.",
    params=[
        query_param(
            required=True,
            description="Item query. Accepts: display name, tier shorthand (<tier>.<enchant> <name>), or unique ID.",
        ),
        limit_param(description="Max disambiguation options (default 10, max 20)", maximum=20),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def resolve_item(args: dict[str, Any]) -> dict[str, Any]:
    """Resolve an ambiguous item query with fuzzy matching."""
    query = normalize_item_input(args.get("query", ""))
    limit = capped_limit(args.get("limit"), default=10, maximum=20)

    result = smart_resolver.resolve(query, limit=limit)
    payload = result.to_dict()
    if not payload.get("match_count"):
        hint = _activity_hint(query)
        if hint:
            payload["activity_hint"] = hint
    return payload


@tool(
    name="search_activities",
    description=(
        "Search Albion activities/game modes "
        "and return recommended fame focus for item progression."
    ),
    params=[
        query_param(description="Activity query — matches against activity names and descriptions."),
        Param(
            "category",
            "string",
            "Optional category filter: instanced_pvpve, solo_pvpve, group_pvpve, open_world, group_pve, solo_pve, open_world_pve",
            enum=[
                "instanced_pvpve",
                "solo_pvpve",
                "group_pvpve",
                "open_world",
                "group_pve",
                "solo_pve",
                "open_world_pve",
            ],
        ),
        limit_param(description="Maximum activities to return (default 20, max 50)", maximum=50),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def search_activities(args: dict[str, Any]) -> dict[str, Any]:
    """Search known activities and return activity metadata."""
    query = args.get("query", "")
    category = args.get("category", "")
    limit = capped_limit(args.get("limit"), default=20, maximum=50)

    results = activity_catalog.search(
        query=query,
        category=category,
        limit=limit,
    )

    return {
        "query": query,
        "category": category,
        "count": len(results),
        "activities": results,
    }
