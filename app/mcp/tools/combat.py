"""MCP tools for combat data, spells, fame, and IP scaling.

Provides tools for querying spell/ability damage, weapon abilities,
destiny board fame requirements, and item power progression.
"""

from __future__ import annotations

from typing import Any

from app.data.destiny_database import default_destiny_database
from app.data.game_database import default_game_database
from app.data.spell_database import default_spell_database
from app.mcp.registry import Param, tool
from app.mcp.tool_templates import READ_ONLY_LOCAL, item_param, limit_param, quality_param, query_param

from ._resolve import attach_smart_resolution, capped_limit, resolve_with_smart_item

game_db = default_game_database
spell_db = default_spell_database
destiny_db = default_destiny_database

DESTINY_SLOT_TYPES = [
    "mainhand_1h",
    "mainhand_2h",
    "offhand",
    "head",
    "armor",
    "shoes",
    "bag",
    "cape",
    "mount",
]
_SPELL_SLOT_BY_ID = {"1": "Q", "2": "W", "3": "E"}


def _ip_scaling_payload(slot_type: str) -> dict[str, Any] | None:
    """Build normalized IP scaling payload for a destiny slot."""
    scaling = destiny_db.get_ip_scaling(slot_type)
    if not scaling:
        return None
    return {
        "slot_type": scaling.slot_type,
        "attack_damage_progression": scaling.attack_damage_progression,
        "ability_power_progression": scaling.ability_power_progression,
        "hp_progression": scaling.hp_progression,
        "armor_progression": scaling.armor_progression,
        "formula": "stat_at_ip = base_stat * progression ^ (IP / 100)",
    }


def _weapon_spell_slot_map(raw_data: dict[str, Any]) -> dict[str, str]:
    """Map spell unique names to user-facing slots (Q/W/E/passive)."""
    csl = raw_data.get("craftingspelllist", {})
    spell_entries = csl.get("craftspell", [])
    if isinstance(spell_entries, dict):
        spell_entries = [spell_entries]

    slot_map: dict[str, str] = {}
    for entry in spell_entries:
        if not isinstance(entry, dict):
            continue
        spell_name = entry.get("@uniquename", "")
        slots = entry.get("@slots", "")
        slot_map[spell_name] = _SPELL_SLOT_BY_ID.get(slots, "passive")
    return slot_map


def _append_damage_summary(
    *,
    spell_name: str,
    resolved: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Attach per-target damage summary for a resolved spell."""
    if not resolved["damage"]:
        return
    for damage in resolved["damage"]:
        source_spell = damage["source_spell"]
        if source_spell != spell_name and not source_spell.startswith(spell_name):
            continue  # Skip damage from unrelated sub-spells (e.g. burning arrows)
        if damage["target"] == "enemyplayers":
            payload["damage_vs_players"] = damage["base_damage"]
            payload["damage_type"] = damage["type"]
        elif damage["target"] == "enemymobs":
            payload["damage_vs_mobs"] = damage["base_damage"]
        elif damage["target"] == "enemy":
            payload["base_damage"] = damage["base_damage"]
            payload["damage_type"] = damage["type"]


def _weapon_ability_payload(spell_name: str, resolved: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "spell_id": resolved["spell_id"],
        "name": resolved["display_name"],
        "cooldown": resolved["cooldown"],
        "energy_cost": resolved["energy_cost"],
        "cast_range": resolved["cast_range"],
    }
    _append_damage_summary(spell_name=spell_name, resolved=resolved, payload=payload)
    return payload


@tool(
    name="spell_info",
    description=(
        "Look up a spell/ability by name or ID. Returns base damage values, "
        "cooldown, energy cost, cast range, and resolved sub-spell effects. "
        "Damage values are base values that scale with Item Power."
    ),
    params=[
        Param(
            "spell", "string",
            "Spell name or unique ID. Accepts: display name or internal ID.",
            required=True,
            min_length=1,
        ),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def spell_info(args: dict[str, Any]) -> dict[str, Any]:
    """Look up a spell/ability with resolved damage values."""
    query = args.get("spell", "")
    result = spell_db.resolve_spell_chain(query)
    if not result:
        return {
            "found": False,
            "query": query,
            "error": f"Spell '{query}' not found",
        }
    return {"found": True, **result}


@tool(
    name="weapon_abilities",
    description=(
        "Get all abilities (Q/W/E/passive) available on a weapon, with base damage "
        "values and cooldowns. Also returns the weapon's base Item Power and ability power."
    ),
    params=[
        item_param(
            required=True,
            description="Weapon name or ID. Accepts: display name, tier shorthand, or unique ID.",
        ),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def weapon_abilities(args: dict[str, Any]) -> dict[str, Any]:
    """Get all abilities for a weapon with damage values."""
    name_or_id = args.get("item", "")
    item, resolution_note = resolve_with_smart_item(name_or_id, game_db.get_item)

    if not item:
        return {
            "found": False,
            "query": name_or_id,
            "error": f"Weapon '{name_or_id}' not found",
        }

    if not item.spell_list:
        return {
            "found": False,
            "query": name_or_id,
            "error": f"'{item.unique_name}' has no abilities (not a weapon?)",
        }

    # Get spell details for each ability, grouped by slot.
    # In items.json craftingspelllist: @slots 1=Q, 2=W, 3=E, no slots=passive.
    abilities: dict[str, list[dict[str, Any]]] = {"Q": [], "W": [], "E": [], "passive": []}
    spell_slot_map = _weapon_spell_slot_map(item.raw_data)

    for spell_name in item.spell_list:
        resolved = spell_db.resolve_spell_chain(spell_name)
        if not resolved:
            continue

        slot = spell_slot_map.get(spell_name, "passive")
        abilities[slot].append(_weapon_ability_payload(spell_name, resolved))

    # Build enchantment IP map including base
    enchantment_ips = {0: item.item_power}
    enchantment_ips.update(item.enchantment_ips)

    result: dict[str, Any] = {
        "found": True,
        "weapon_id": item.unique_name,
        "tier": item.tier,
        "two_handed": item.two_handed,
        "base_item_power": item.item_power,
        "ability_power": item.ability_power,
        "ip_progression_type": item.ip_progression_type,
        "combat_spec_node": item.combat_spec_achievement,
        "enchantment_ips": enchantment_ips,
        "abilities": {k: v for k, v in abilities.items() if v},
        "note": "Damage values are base at weapon's ability power. Scale with Item Power.",
    }

    return attach_smart_resolution(result, resolution_note)


@tool(
    name="destiny_fame",
    description=(
        "Calculate fame and learning point requirements for a destiny board node "
        "between two levels."
    ),
    params=[
        Param(
            "node",
            "string",
            "Destiny board node ID. Format: <CATEGORY>_<TYPE> or <CATEGORY>_<TYPE>_<TIER>.",
            required=True,
            min_length=1,
        ),
        Param("from_level", "integer", "Starting level for fame calc (default: 0)", minimum=0),
        Param("to_level", "integer", "Target level for fame calc (default: max)", minimum=0),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def destiny_fame(args: dict[str, Any]) -> dict[str, Any]:
    """Return fame requirements for a destiny node and level range."""
    node_id = args["node"]
    from_level = args.get("from_level", 0)
    to_level = args.get("to_level")
    fame = destiny_db.get_fame_to_level(node_id, from_level, to_level)
    if not fame:
        return {
            "found": False,
            "node": node_id,
            "error": f"Destiny node '{node_id}' not found",
        }
    return {
        "found": True,
        "node": fame["node_id"],
        "fame": fame,
    }


@tool(
    name="destiny_ip_scaling",
    description=(
        "Get IP scaling progression factors for a slot type. "
        "Optionally include base character stats."
    ),
    params=[
        Param(
            "ip_slot_type",
            "string",
            "Slot type to inspect: mainhand_1h, mainhand_2h, offhand, head, armor, shoes, bag, cape, mount",
            required=True,
            enum=DESTINY_SLOT_TYPES,
        ),
        Param("include_base_stats", "boolean", "Include base character stats (HP, energy, premium bonuses)"),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def destiny_ip_scaling(args: dict[str, Any]) -> dict[str, Any]:
    """Return IP scaling data for a destiny slot type."""
    slot_type = args["ip_slot_type"]
    scaling = _ip_scaling_payload(slot_type)
    if not scaling:
        return {
            "found": False,
            "slot_type": slot_type,
            "error": f"Unknown slot type '{slot_type}'",
        }

    result: dict[str, Any] = {
        "found": True,
        "ip_scaling": scaling,
    }
    if args.get("include_base_stats"):
        result["base_stats"] = destiny_db.get_base_stats()
    return result


@tool(
    name="destiny_quality_bonus",
    description="Get the Item Power bonus for an item quality level.",
    params=[
        quality_param(
            required=True,
            description=(
                "Quality level to inspect (1=Normal, 2=Good, 3=Outstanding, "
                "4=Excellent, 5=Masterpiece)"
            ),
        ),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def destiny_quality_bonus(args: dict[str, Any]) -> dict[str, Any]:
    """Return quality-based IP bonus from destiny configuration."""
    quality = args["quality"]
    bonus = destiny_db.get_quality_bonus(quality)
    return {
        "quality": quality,
        "ip_bonus": bonus,
    }


@tool(
    name="search_destiny",
    description=(
        "Search for destiny board nodes by name or category. "
        "Returns node IDs that can be used with destiny_fame."
    ),
    params=[
        query_param(description="Search query — matches against node names and categories."),
        Param("category", "string", "Filter: fighting, gathering, crafting, farming", enum=["fighting", "gathering", "crafting", "farming"]),
        limit_param(description="Max results (default 20)", maximum=50),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def search_destiny(args: dict[str, Any]) -> dict[str, Any]:
    """Search destiny board nodes."""
    query = args.get("query", "")
    category = args.get("category", "")
    limit = capped_limit(args.get("limit"), default=20, maximum=50)

    results = destiny_db.search_destiny_nodes(query=query, category=category, limit=limit)
    return {
        "query": query,
        "category": category,
        "count": len(results),
        "nodes": results,
    }
