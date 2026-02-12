"""Spell/ability database service.

Loads and indexes spell data from ao-bin-dumps spells.json.
Provides spell lookup, chain resolution, and search functionality.
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
SPELLS_FILE = GAME_DATA_DIR / "spells.json"
LOCALIZATION_FILE = GAME_DATA_DIR / "localization.json"


@dataclass
class SpellEffect:
    """A damage/heal/buff effect from a spell."""

    target: str  # "enemy", "enemyplayers", "enemymobs", "self", etc.
    attribute: str  # "health", "movespeed", etc.
    change: float  # negative = damage, positive = heal
    effect_type: str  # "physical", "magic"
    # DoT/HoT specifics (None for instant effects)
    interval: float | None = None  # tick interval in seconds
    ticks: int | None = None  # number of ticks


@dataclass
class SpellBuff:
    """A buff payload from a spell (permanent or timed)."""

    buff_type: str
    values: dict[str, float | str] = field(default_factory=dict)
    duration: float | None = None  # None = permanent, seconds for buffovertime
    target: str = ""  # "self", "enemy", etc.


@dataclass
class CrowdControl:
    """A crowd control effect from a spell."""

    cc_type: str  # "stun", "root", "silence", "knockback", "pull"
    duration: float = 0
    target: str = ""


@dataclass
class SpellInfo:
    """Parsed spell data."""

    unique_name: str
    category: str = ""  # "damage", "crowdcontrol", "buff", etc.
    casting_time: float = 0
    stand_time: float = 0
    cooldown: float = 0  # recastdelay
    energy_cost: float = 0
    cast_range: float = 0
    target: str = ""  # "ground", "enemy", "self", etc.
    effects: list[SpellEffect] = field(default_factory=list)
    buffs: list[SpellBuff] = field(default_factory=list)
    crowd_control: list[CrowdControl] = field(default_factory=list)
    sub_spell_names: list[str] = field(default_factory=list)


class SpellDatabase:
    """Service for querying spell/ability data."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or GAME_DATA_DIR
        self._spells: dict[str, SpellInfo] = {}
        self._name_index: dict[str, str] = {}  # lowercase display name -> unique_name
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        ensure_game_files(self._data_dir)
        self._load_spells()
        self._load_localization()
        logger.info("[SpellDB] Loaded %s spells", len(self._spells))

    def _load_spells(self) -> None:
        spells_path = self._data_dir / "spells.json"
        if not spells_path.exists():
            logger.warning("[SpellDB] Spells file not found: %s", spells_path)
            return

        try:
            raw = json.loads(spells_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("[SpellDB] Failed to load spells: %s", exc)
            return

        root = raw.get("spells", {})
        for spell_bucket in ("activespell", "passivespell", "togglespell"):
            spell_entries = root.get(spell_bucket, [])
            if isinstance(spell_entries, dict):
                spell_entries = [spell_entries]
            if not isinstance(spell_entries, list):
                continue

            for spell_data in spell_entries:
                if not isinstance(spell_data, dict):
                    continue
                spell = self._parse_spell(spell_data)
                if spell:
                    self._spells[spell.unique_name] = spell

    def _parse_spell(self, data: dict[str, Any]) -> SpellInfo | None:
        unique_name = data.get("@uniquename", "")
        if not unique_name:
            return None

        # Collect direct effects
        effects = self._parse_effects(data)
        buffs = self._parse_buffs(data)
        crowd_control = self._parse_cc(data)

        # Collect sub-spell references
        sub_spells: list[str] = []
        # spelleffectarea.@effect
        sea = data.get("spelleffectarea")
        if isinstance(sea, dict) and sea.get("@effect"):
            sub_spells.append(sea["@effect"])
        elif isinstance(sea, list):
            for s in sea:
                if isinstance(s, dict) and s.get("@effect"):
                    sub_spells.append(s["@effect"])
        # applyspell.@spell
        aps = data.get("applyspell", [])
        if isinstance(aps, dict):
            aps = [aps]
        for ap in aps:
            if isinstance(ap, dict) and ap.get("@spell"):
                sub_spells.append(ap["@spell"])
        # pulsingspell.@spell
        ps = data.get("pulsingspell")
        if isinstance(ps, dict) and ps.get("@spell"):
            sub_spells.append(ps["@spell"])
        elif isinstance(ps, list):
            for p in ps:
                if isinstance(p, dict) and p.get("@spell"):
                    sub_spells.append(p["@spell"])
        # chainspell.@spell
        cs = data.get("chainspell")
        if isinstance(cs, dict) and cs.get("@spell"):
            sub_spells.append(cs["@spell"])
        # multispell entries
        ms = data.get("multispell")
        if isinstance(ms, dict):
            for k, v in ms.items():
                if isinstance(v, dict) and v.get("@spell"):
                    sub_spells.append(v["@spell"])

        return SpellInfo(
            unique_name=unique_name,
            category=str(data.get("@category", "") or ""),
            casting_time=float(data.get("@castingtime", 0) or 0),
            stand_time=float(data.get("@standtime", 0) or 0),
            cooldown=float(data.get("@recastdelay", 0) or 0),
            energy_cost=float(data.get("@energyusage", 0) or 0),
            cast_range=float(data.get("@castrange", 0) or 0),
            target=str(data.get("@target", "") or ""),
            effects=effects,
            buffs=buffs,
            crowd_control=crowd_control,
            sub_spell_names=sub_spells,
        )

    def _parse_effects(self, data: dict[str, Any]) -> list[SpellEffect]:
        """Parse directattributechange and attributechangeovertime."""
        effects: list[SpellEffect] = []

        dac = data.get("directattributechange", [])
        if isinstance(dac, dict):
            dac = [dac]
        for d in dac:
            if isinstance(d, dict):
                try:
                    effects.append(SpellEffect(
                        target=d.get("@target", "enemy"),
                        attribute=d.get("@attribute", "health"),
                        change=float(d.get("@change", 0)),
                        effect_type=d.get("@effecttype", ""),
                    ))
                except (ValueError, TypeError):
                    pass

        acot = data.get("attributechangeovertime", [])
        if isinstance(acot, dict):
            acot = [acot]
        for a in acot:
            if isinstance(a, dict):
                try:
                    interval_raw = a.get("@interval")
                    ticks_raw = a.get("@count")
                    effects.append(SpellEffect(
                        target=a.get("@target", "enemy"),
                        attribute=a.get("@attribute", "health"),
                        change=float(a.get("@change", 0)),
                        effect_type=a.get("@effecttype", ""),
                        interval=float(interval_raw) if interval_raw else None,
                        ticks=int(ticks_raw) if ticks_raw else None,
                    ))
                except (ValueError, TypeError):
                    pass

        return effects

    def _parse_buffs(self, data: dict[str, Any]) -> list[SpellBuff]:
        """Parse buff definitions from `buff` and `buffovertime` nodes."""
        buffs: list[SpellBuff] = []

        # Permanent buffs
        raw_buffs = data.get("buff", [])
        if isinstance(raw_buffs, dict):
            raw_buffs = [raw_buffs]
        if isinstance(raw_buffs, list):
            for raw_buff in raw_buffs:
                buff = self._parse_single_buff(raw_buff, duration=None)
                if buff:
                    buffs.append(buff)

        # Timed buffs (buffovertime)
        raw_bot = data.get("buffovertime", [])
        if isinstance(raw_bot, dict):
            raw_bot = [raw_bot]
        if isinstance(raw_bot, list):
            for raw_buff in raw_bot:
                if not isinstance(raw_buff, dict):
                    continue
                dur = None
                time_raw = raw_buff.get("@time")
                if time_raw:
                    try:
                        dur = float(time_raw)
                    except (ValueError, TypeError):
                        pass
                buff = self._parse_single_buff(raw_buff, duration=dur)
                if buff:
                    buffs.append(buff)

        return buffs

    def _parse_single_buff(
        self, raw_buff: Any, *, duration: float | None
    ) -> SpellBuff | None:
        """Parse a single buff or buffovertime entry."""
        if not isinstance(raw_buff, dict):
            return None
        buff_type = str(raw_buff.get("@type", "") or "")
        if not buff_type:
            return None

        target = str(raw_buff.get("@target", "") or "")
        skip_keys = {"@type", "@target", "@time", "@persistsafterknockdown"}
        values: dict[str, float | str] = {}
        for key, value in raw_buff.items():
            if not key.startswith("@") or key in skip_keys:
                continue
            clean_key = key.lstrip("@")
            if isinstance(value, (int, float)):
                values[clean_key] = float(value)
                continue
            if isinstance(value, str):
                try:
                    values[clean_key] = float(value)
                except ValueError:
                    values[clean_key] = value
            else:
                values[clean_key] = str(value)

        return SpellBuff(buff_type=buff_type, values=values, duration=duration, target=target)

    _CC_NODES = ("stun", "root", "silence", "knockback", "pull")

    def _parse_cc(self, data: dict[str, Any]) -> list[CrowdControl]:
        """Parse crowd control nodes (stun, root, silence, knockback, pull)."""
        cc_list: list[CrowdControl] = []
        for cc_type in self._CC_NODES:
            raw = data.get(cc_type)
            if raw is None:
                continue
            entries = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    cc_list.append(CrowdControl(
                        cc_type=cc_type,
                        duration=float(entry.get("@time", 0) or 0),
                        target=str(entry.get("@target", "") or ""),
                    ))
                except (ValueError, TypeError):
                    pass
        return cc_list

    def _load_localization(self) -> None:
        loc_path = self._data_dir / "localization.json"
        if not loc_path.exists():
            return

        try:
            raw = json.loads(loc_path.read_text(encoding="utf-8"))
        except Exception:
            return

        tus = raw.get("tmx", {}).get("body", {}).get("tu", [])
        for tu in tus:
            tuid = tu.get("@tuid", "")
            if not tuid.startswith("@SPELLS_"):
                continue
            # Extract spell unique name: @SPELLS_MULTISHOT2 -> MULTISHOT2
            spell_name = tuid[len("@SPELLS_"):]
            # Skip descriptions and suffixed keys
            if spell_name.endswith("_DESC"):
                continue
            if spell_name not in self._spells:
                continue
            # Get EN-US display name
            tuvs = tu.get("tuv", [])
            if isinstance(tuvs, dict):
                tuvs = [tuvs]
            for tuv in tuvs:
                if isinstance(tuv, dict) and tuv.get("@xml:lang") == "EN-US":
                    display = tuv.get("seg", "")
                    if display:
                        key = display.lower()
                        # Prefer non-_EFFECT spells for name collisions
                        existing = self._name_index.get(key)
                        if not existing or (
                            existing.endswith("_EFFECT") and not spell_name.endswith("_EFFECT")
                        ):
                            self._name_index[key] = spell_name
                    break

    def get_spell(self, name_or_id: str) -> SpellInfo | None:
        """Look up a spell by unique name or display name."""
        self._ensure_loaded()

        if name_or_id in self._spells:
            return self._spells[name_or_id]

        # Try uppercase (common pattern)
        upper = name_or_id.upper()
        if upper in self._spells:
            return self._spells[upper]

        # Try localized name index
        lowered = name_or_id.lower()
        if lowered in self._name_index:
            return self._spells.get(self._name_index[lowered])

        # Partial match on name index
        for key, spell_id in self._name_index.items():
            if lowered in key or key in lowered:
                return self._spells.get(spell_id)

        return None

    def resolve_spell_chain(self, spell_name: str, max_depth: int = 3) -> dict[str, Any] | None:
        """Resolve a spell and all its sub-spells into a flat summary.

        Follows sub-spell references recursively to collect all damage/buff effects.
        Returns a flat dict ready for LLM consumption.
        """
        self._ensure_loaded()
        spell = self.get_spell(spell_name)
        if not spell:
            return None

        # Collect all effects from this spell and its sub-spells
        all_damage: list[dict[str, Any]] = []
        all_effects: list[dict[str, Any]] = []
        all_buffs: list[dict[str, Any]] = []
        all_cc: list[dict[str, Any]] = []
        all_sub_spells: list[str] = []
        visited: set[str] = set()

        def _collect(sp: SpellInfo, depth: int) -> None:
            if sp.unique_name in visited or depth > max_depth:
                return
            visited.add(sp.unique_name)

            for effect in sp.effects:
                entry: dict[str, Any] = {
                    "target": effect.target,
                    "attribute": effect.attribute,
                    "change": effect.change,
                    "type": effect.effect_type,
                    "source_spell": sp.unique_name,
                }
                if effect.interval is not None:
                    entry["interval"] = effect.interval
                if effect.ticks is not None:
                    entry["ticks"] = effect.ticks
                all_effects.append(entry)
                if effect.attribute == "health" and effect.change < 0:
                    dmg: dict[str, Any] = {
                        "target": effect.target,
                        "base_damage": abs(effect.change),
                        "type": effect.effect_type,
                        "source_spell": sp.unique_name,
                    }
                    if effect.interval is not None:
                        dmg["interval"] = effect.interval
                    if effect.ticks is not None:
                        dmg["ticks"] = effect.ticks
                    all_damage.append(dmg)

            for buff in sp.buffs:
                buff_entry: dict[str, Any] = {
                    "type": buff.buff_type,
                    "values": dict(buff.values),
                    "source_spell": sp.unique_name,
                }
                if buff.duration is not None:
                    buff_entry["duration"] = buff.duration
                if buff.target:
                    buff_entry["target"] = buff.target
                all_buffs.append(buff_entry)

            for cc in sp.crowd_control:
                all_cc.append({
                    "type": cc.cc_type,
                    "duration": cc.duration,
                    "target": cc.target,
                })

            for sub_name in sp.sub_spell_names:
                all_sub_spells.append(sub_name)
                sub = self._spells.get(sub_name)
                if sub:
                    _collect(sub, depth + 1)

        _collect(spell, 0)

        # Build display name from index (check both exact and _EFFECT variant)
        display_name = spell.unique_name
        for name, spell_id in self._name_index.items():
            if spell_id == spell.unique_name:
                display_name = name.title()
                break
            if spell_id == spell.unique_name + "_EFFECT":
                display_name = name.title()
                # Don't break — keep looking for exact match

        return {
            "spell_id": spell.unique_name,
            "display_name": display_name,
            "category": spell.category,
            "cooldown": spell.cooldown,
            "energy_cost": spell.energy_cost,
            "cast_range": spell.cast_range,
            "casting_time": spell.casting_time,
            "target": spell.target,
            "damage": all_damage,
            "effects": all_effects,
            "buffs": all_buffs,
            "crowd_control": all_cc,
            "sub_spells": all_sub_spells,
        }

    def search_spells(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search spells by name substring."""
        self._ensure_loaded()
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        # Search by display name first
        for display_name, spell_id in self._name_index.items():
            if query_lower in display_name:
                spell = self._spells.get(spell_id)
                if spell:
                    results.append({
                        "spell_id": spell.unique_name,
                        "display_name": display_name.title(),
                        "category": spell.category,
                    })
                    if len(results) >= limit:
                        return results

        # Then search by unique name
        for spell_id, spell in self._spells.items():
            if query_lower in spell_id.lower() and not any(
                r["spell_id"] == spell_id for r in results
            ):
                results.append({
                    "spell_id": spell.unique_name,
                    "display_name": spell.unique_name,
                    "category": spell.category,
                })
                if len(results) >= limit:
                    return results

        return results


# Default instance
default_spell_database = SpellDatabase()
