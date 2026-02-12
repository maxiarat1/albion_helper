"""Albion activity catalog for game-mode and dungeon intent resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


@dataclass(frozen=True)
class ActivityInfo:
    """Normalized activity metadata exposed to MCP tools."""

    activity_id: str
    name: str
    category: str
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    recommended_fame_focus: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "aliases": list(self.aliases),
            "recommended_fame_focus": list(self.recommended_fame_focus),
        }


class ActivityCatalog:
    """Simple in-memory catalog for common Albion activities."""

    def __init__(self) -> None:
        self._activities = self._seed_activities()
        self._by_id = {entry.activity_id: entry for entry in self._activities}
        self._alias_index: dict[str, str] = {}
        for entry in self._activities:
            self._alias_index[_normalize(entry.name)] = entry.activity_id
            for alias in entry.aliases:
                self._alias_index[_normalize(alias)] = entry.activity_id

    def resolve(self, query: str) -> ActivityInfo | None:
        """Resolve the best activity match for a query string."""
        normalized = _normalize(query)
        if not normalized:
            return None

        activity_id = self._alias_index.get(normalized)
        if activity_id:
            return self._by_id.get(activity_id)

        ranked = self.search(query=query, limit=1)
        if ranked:
            return self._by_id.get(ranked[0]["activity_id"])
        return None

    def search(
        self,
        query: str = "",
        category: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search activities by name/alias with optional category filter."""
        normalized_query = _normalize(query)
        normalized_category = _normalize(category)

        ranked: list[tuple[int, ActivityInfo]] = []
        for entry in self._activities:
            if normalized_category and _normalize(entry.category) != normalized_category:
                continue
            score = self._score_match(entry, normalized_query)
            if score <= 0:
                continue
            ranked.append((score, entry))

        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [entry.to_dict() for _, entry in ranked[: max(1, limit)]]

    def _score_match(self, entry: ActivityInfo, normalized_query: str) -> int:
        if not normalized_query:
            return 1

        normalized_name = _normalize(entry.name)
        if normalized_query == normalized_name:
            return 100
        if normalized_query in normalized_name:
            return 80

        best_alias_score = 0
        for alias in entry.aliases:
            norm_alias = _normalize(alias)
            if normalized_query == norm_alias:
                return 95
            if normalized_query in norm_alias:
                best_alias_score = max(best_alias_score, 70)
        return best_alias_score

    def _seed_activities(self) -> tuple[ActivityInfo, ...]:
        """Static catalog for current core activity names and aliases."""
        return (
            ActivityInfo(
                activity_id="THE_DEPTHS",
                name="The Depths",
                category="instanced_pvpve",
                description="Small-group infernal activity focused on PvPvE combat and standing rewards.",
                aliases=("depth", "depths", "the depth activity"),
                recommended_fame_focus=(
                    "Main weapon specialization for your Depths build",
                    "Chest armor specialization used in your comp",
                    "Helmet and shoe lines tied to your engage/disengage role",
                ),
            ),
            ActivityInfo(
                activity_id="MISTS",
                name="The Mists",
                category="open_world_instanced",
                description="Solo or duo mist zones with PvPvE encounters and roaming objectives.",
                aliases=("mist", "mists", "greater mists", "lethal mists"),
                recommended_fame_focus=(
                    "Primary solo or duo weapon line",
                    "Armor lines matching your sustain and mobility setup",
                ),
            ),
            ActivityInfo(
                activity_id="CORRUPTED_DUNGEONS",
                name="Corrupted Dungeons",
                category="solo_pvpve",
                description="Solo dungeon PvPvE with invasions in Hunter, Stalker, and Slayer tiers.",
                aliases=("corrupted", "cd", "corrupted dungeon", "corrupted dungeons"),
                recommended_fame_focus=(
                    "Main 1v1 weapon line",
                    "Chest and offhand lines used for your matchup profile",
                ),
            ),
            ActivityInfo(
                activity_id="HELLGATES",
                name="Hellgates",
                category="group_pvpve",
                description="Instanced team PvPvE fights (2v2, 5v5, 10v10 formats).",
                aliases=("hellgate", "hellgates", "hg"),
                recommended_fame_focus=(
                    "Weapon line for your team role",
                    "Defensive armor lines for your Hellgate comp",
                ),
            ),
            ActivityInfo(
                activity_id="ROADS_OF_AVALON",
                name="Roads of Avalon",
                category="open_world",
                description="Networked zones for roaming, objectives, gathering, and small-scale fights.",
                aliases=("roads", "ava roads", "roads of avalon"),
                recommended_fame_focus=(
                    "Flexible roaming weapon line",
                    "Escape/mobility armor lines for small-scale survival",
                ),
            ),
            ActivityInfo(
                activity_id="AVALONIAN_DUNGEONS",
                name="Avalonian Dungeons",
                category="group_pve",
                description="Group PvE expeditions against Avalonian enemies and elite bosses.",
                aliases=("avalonian dungeon", "avalonian dungeons", "ava dungeon", "ava dungeons"),
                recommended_fame_focus=(
                    "PvE damage weapon line for your role",
                    "Support or tank armor lines for coordinated groups",
                ),
            ),
            ActivityInfo(
                activity_id="SOLO_RANDOM_DUNGEONS",
                name="Solo Randomized Dungeons",
                category="solo_pve",
                description="Solo dungeon content with open-world entrances and loot/fame farming.",
                aliases=("solo dungeon", "solo dungeons", "srds", "random dungeon solo"),
                recommended_fame_focus=(
                    "Fast-clear solo weapon line",
                    "Armor lines that improve sustain and clear speed",
                ),
            ),
            ActivityInfo(
                activity_id="GROUP_RANDOM_DUNGEONS",
                name="Group Randomized Dungeons",
                category="group_pve",
                description="Group dungeon farming content with scalable fame and loot efficiency.",
                aliases=("group dungeon", "group dungeons", "random dungeon group"),
                recommended_fame_focus=(
                    "Group PvE weapon specialization for your role",
                    "Tank/healer/DPS armor lines aligned with party composition",
                ),
            ),
            ActivityInfo(
                activity_id="STATIC_DUNGEONS",
                name="Static Dungeons",
                category="open_world_pve",
                description="Always-open dungeons with contested farming and PvP pressure.",
                aliases=("static", "statics", "static dungeon", "static dungeons"),
                recommended_fame_focus=(
                    "High-efficiency PvE weapon line",
                    "Armor lines that balance clear speed with PvP survivability",
                ),
            ),
        )


default_activity_catalog = ActivityCatalog()

