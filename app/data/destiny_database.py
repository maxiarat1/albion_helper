"""Destiny board and progression database service.

Loads achievements.json (fame templates + destiny nodes),
gamedata.json (IP scaling, quality levels), and
characters.json (base stats, premium bonuses).
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


@dataclass
class FameLevel:
    """A single level in a destiny board template."""

    level: int
    fame_required: int
    lp_cost: int = 0


@dataclass
class DestinyNode:
    """A destiny board progression node."""

    node_id: str
    template_name: str = ""
    category: str = ""  # "fighting", "gathering", "crafting", etc.
    mission_type: str = ""  # "killmobfame", "gatherresourcefame", etc.
    levels: list[FameLevel] = field(default_factory=list)
    total_fame: int = 0
    total_levels: int = 0


@dataclass
class IPScalingConfig:
    """IP-to-stat scaling factors for a slot type."""

    slot_type: str
    attack_damage_progression: float = 1.0
    ability_power_progression: float = 1.0
    hp_progression: float = 1.0
    armor_progression: float = 1.0
    cc_resistance_progression: float = 1.0
    energy_progression: float = 1.0


@dataclass
class AbilityPowerProgressionConfig:
    """Global ability-power scaling constants used by spell formulas."""

    base_damage: float = 100.0
    base_load: float = 25.0
    resistance_progression: float = 1.0
    hitpoint_progression: float = 1.0
    load_progression: float = 1.0
    cc_duration_factor_players: float = 1.0
    cc_duration_factor_mobs: float = 1.0


class DestinyDatabase:
    """Service for destiny board fame, IP scaling, and base stats."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or GAME_DATA_DIR
        self._templates: dict[str, list[FameLevel]] = {}
        self._nodes: dict[str, DestinyNode] = {}
        self._node_name_index: dict[str, str] = {}  # lowercase -> node_id
        self._ip_scaling: dict[str, IPScalingConfig] = {}
        self._ability_power_progression = AbilityPowerProgressionConfig()
        self._energy_share: dict[str, float] = {}
        self._quality_bonuses: dict[int, int] = {1: 0}  # level 1 = no bonus
        self._base_stats: dict[str, Any] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        ensure_game_files(self._data_dir)
        self._load_achievements()
        self._load_gamedata()
        self._load_characters()
        logger.info(
            "[DestinyDB] Loaded %s nodes, %s IP scaling configs",
            len(self._nodes),
            len(self._ip_scaling),
        )

    def _load_achievements(self) -> None:
        path = self._data_dir / "achievements.json"
        if not path.exists():
            logger.warning("[DestinyDB] Achievements file not found: %s", path)
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[DestinyDB] Failed to load achievements: %s", exc)
            return

        root = raw.get("achievements", {})

        # Parse templates
        for tmpl in root.get("template", []):
            if not isinstance(tmpl, dict):
                continue
            name = tmpl.get("@name", "")
            if not name:
                continue
            levels = self._parse_template_levels(tmpl)
            self._templates[name] = levels

        # Parse template achievements (destiny nodes)
        for ta in root.get("templateachievement", []):
            if not isinstance(ta, dict):
                continue
            node = self._parse_node(ta)
            if node:
                self._nodes[node.node_id] = node
                self._node_name_index[node.node_id.lower()] = node.node_id

    def _parse_template_levels(self, tmpl: dict[str, Any]) -> list[FameLevel]:
        """Parse base + elite levels from a template."""
        levels: list[FameLevel] = []

        for section_key in ("baselevels", "elitelevels"):
            section = tmpl.get(section_key, {})
            if not isinstance(section, dict):
                continue
            text = section.get("#text", "")
            if not text:
                continue
            for i, line in enumerate(text.strip().split("\n"), start=len(levels) + 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(";")
                if len(parts) < 2:
                    continue
                try:
                    fame = int(parts[0])
                    lp = int(parts[1])
                    levels.append(FameLevel(level=i, fame_required=fame, lp_cost=lp))
                except (ValueError, IndexError):
                    pass

        return levels

    def _parse_node(self, data: dict[str, Any]) -> DestinyNode | None:
        node_id = data.get("@id", "")
        if not node_id:
            return None

        template_name = data.get("@usetemplate", "")
        levels = list(self._templates.get(template_name, []))
        total_fame = sum(lvl.fame_required for lvl in levels)

        return DestinyNode(
            node_id=node_id,
            template_name=template_name,
            category=data.get("@category", ""),
            mission_type=data.get("@missiontype", ""),
            levels=levels,
            total_fame=total_fame,
            total_levels=len(levels),
        )

    def _load_gamedata(self) -> None:
        path = self._data_dir / "gamedata.json"
        if not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[DestinyDB] Failed to load gamedata: %s", exc)
            return

        items = raw.get("AO-GameData", {}).get("Items", {})

        # Parse IP scaling
        ipp = items.get("ItemPowerProgression", {})
        for slot_type, data in ipp.items():
            if not isinstance(data, dict):
                continue
            self._ip_scaling[slot_type] = IPScalingConfig(
                slot_type=slot_type,
                attack_damage_progression=float(data.get("@attackdamageprogression", 1.0)),
                ability_power_progression=float(data.get("@abilitypowerprogression", 1.0)),
                hp_progression=float(data.get("@hitpointsprogression", 1.0)),
                armor_progression=float(data.get("@armorprogression", 1.0)),
                cc_resistance_progression=float(data.get("@crowdcontrolresistanceprogression", 1.0)),
                energy_progression=float(data.get("@energyprogression", 1.0)),
            )

        # Parse global ability-power scaling constants
        app = items.get("AbilityPowerProgression", {})
        if isinstance(app, dict):
            self._ability_power_progression = AbilityPowerProgressionConfig(
                base_damage=float(app.get("@basedamage", 100.0)),
                base_load=float(app.get("@baseload", 25.0)),
                resistance_progression=float(app.get("@resistanceprogression", 1.0)),
                hitpoint_progression=float(app.get("@hitpointprogression", 1.0)),
                load_progression=float(app.get("@loadprogression", 1.0)),
                cc_duration_factor_players=float(app.get("@ccdurationfactorplayers", 1.0)),
                cc_duration_factor_mobs=float(app.get("@ccdurationfactormobs", 1.0)),
            )

        # Parse shared energy contribution factors by equipment slot.
        energy_share = ipp.get("energyshare", {})
        if isinstance(energy_share, dict):
            for key, value in energy_share.items():
                if not isinstance(key, str) or not key.startswith("@"):
                    continue
                slot_name = key.lstrip("@")
                try:
                    self._energy_share[slot_name] = float(value)
                except (TypeError, ValueError):
                    continue

        # Parse quality levels
        ql = items.get("QualityLevels", {})
        for entry in ql.get("qualitylevel", []):
            if isinstance(entry, dict):
                try:
                    level = int(entry["@level"])
                    bonus = int(entry["@itempowerbonus"])
                    self._quality_bonuses[level] = bonus
                except (KeyError, ValueError):
                    pass

    def _load_characters(self) -> None:
        path = self._data_dir / "characters.json"
        if not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[DestinyDB] Failed to load characters: %s", exc)
            return

        defaults = (
            raw.get("CharacterData", {}).get("Characters", {}).get("DefaultValues", {})
        )
        if not defaults:
            return

        self._base_stats = {
            "hp": float(defaults.get("@hitpointsmax", 1200)),
            "hp_regen": float(defaults.get("@hitpointsregeneration", 12)),
            "energy": float(defaults.get("@energymax", 120)),
            "energy_regen": float(defaults.get("@energyregeneration", 1.5)),
            "premium_fame_factor": float(
                defaults.get("@premiumdestinyboardprogressionfactor", 1.5)
            ),
            "premium_silver_factor": float(
                defaults.get("@premiumsilverlootfactor", 1.5)
            ),
            "premium_loot_factor": float(
                defaults.get("@premiummoblootfactor", 1.5)
            ),
            "lp_fame_factor": float(
                defaults.get("@learningpointfamefactor", 5)
            ),
        }

    # --- Public API ---

    def get_destiny_node(self, node_id: str) -> DestinyNode | None:
        """Look up a destiny board node by ID."""
        self._ensure_loaded()
        if node_id in self._nodes:
            return self._nodes[node_id]
        lowered = node_id.lower()
        if lowered in self._node_name_index:
            return self._nodes.get(self._node_name_index[lowered])
        return None

    def get_fame_to_level(
        self, node_id: str, from_level: int = 0, to_level: int | None = None
    ) -> dict[str, Any] | None:
        """Calculate fame required from one level to another."""
        self._ensure_loaded()
        node = self.get_destiny_node(node_id)
        if not node or not node.levels:
            return None

        if to_level is None:
            to_level = node.total_levels

        to_level = min(to_level, node.total_levels)
        from_level = max(from_level, 0)

        selected = [lvl for lvl in node.levels if from_level < lvl.level <= to_level]
        total_fame = sum(lvl.fame_required for lvl in selected)
        total_lp = sum(lvl.lp_cost for lvl in selected)

        return {
            "node_id": node.node_id,
            "template": node.template_name,
            "category": node.category,
            "from_level": from_level,
            "to_level": to_level,
            "total_fame_required": total_fame,
            "total_lp_cost": total_lp,
            "level_count": len(selected),
            "levels": [
                {
                    "level": lvl.level,
                    "fame": lvl.fame_required,
                    "lp": lvl.lp_cost,
                }
                for lvl in selected
            ],
        }

    def get_ip_scaling(self, slot_type: str) -> IPScalingConfig | None:
        """Get IP scaling factors for a slot type."""
        self._ensure_loaded()
        return self._ip_scaling.get(slot_type)

    def get_quality_bonus(self, quality: int) -> int:
        """Get IP bonus for a quality level (1-5)."""
        self._ensure_loaded()
        return self._quality_bonuses.get(quality, 0)

    def get_ability_power_progression(self) -> AbilityPowerProgressionConfig:
        """Get global ability-power progression constants."""
        self._ensure_loaded()
        return self._ability_power_progression

    def get_energy_share(self, slot_type: str) -> float | None:
        """Get the shared energy contribution factor for a slot type."""
        self._ensure_loaded()
        return self._energy_share.get(slot_type)

    def get_base_stats(self) -> dict[str, Any]:
        """Get base character stats."""
        self._ensure_loaded()
        return dict(self._base_stats)

    def get_all_ip_scaling(self) -> dict[str, dict[str, float]]:
        """Get all IP scaling configs as dicts."""
        self._ensure_loaded()
        return {
            slot: {
                "attack_damage": cfg.attack_damage_progression,
                "ability_power": cfg.ability_power_progression,
                "hp": cfg.hp_progression,
                "armor": cfg.armor_progression,
                "cc_resistance": cfg.cc_resistance_progression,
                "energy": cfg.energy_progression,
            }
            for slot, cfg in self._ip_scaling.items()
        }

    def search_destiny_nodes(
        self, query: str = "", category: str = "", limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search destiny board nodes."""
        self._ensure_loaded()
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        for node in self._nodes.values():
            if category and node.category != category:
                continue
            if query and query_lower not in node.node_id.lower():
                continue
            results.append({
                "node_id": node.node_id,
                "template": node.template_name,
                "category": node.category,
                "mission_type": node.mission_type,
                "total_levels": node.total_levels,
                "total_fame": node.total_fame,
            })
            if len(results) >= limit:
                break

        return results


# Default instance
default_destiny_database = DestinyDatabase()
