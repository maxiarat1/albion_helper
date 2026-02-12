"""Tests for SpellDatabase."""

from pathlib import Path

import pytest

from app.data.spell_database import SpellDatabase

DATA_DIR = Path("docs/ao-bin-dumps")


@pytest.fixture(scope="module")
def spell_db():
    db = SpellDatabase(data_dir=DATA_DIR)
    db._ensure_loaded()
    return db


def test_load_spells(spell_db: SpellDatabase):
    assert len(spell_db._spells) > 5000


def test_load_localization_names(spell_db: SpellDatabase):
    assert len(spell_db._name_index) > 500


def test_get_spell_by_id(spell_db: SpellDatabase):
    spell = spell_db.get_spell("MULTISHOT2")
    assert spell is not None
    assert spell.unique_name == "MULTISHOT2"
    assert spell.category == "damage"
    assert spell.cooldown == 3.0
    assert spell.energy_cost == 4.0


def test_get_spell_by_display_name(spell_db: SpellDatabase):
    spell = spell_db.get_spell("multishot")
    assert spell is not None
    assert spell.unique_name == "MULTISHOT2"


def test_get_passive_spell_has_buffs(spell_db: SpellDatabase):
    spell = spell_db.get_spell("PASSIVE_MAXLOAD")
    assert spell is not None
    assert len(spell.buffs) >= 1
    assert spell.buffs[0].buff_type == "maxload"


def test_get_spell_not_found(spell_db: SpellDatabase):
    assert spell_db.get_spell("NONEXISTENT_SPELL_XYZ") is None


def test_resolve_chain_multishot(spell_db: SpellDatabase):
    result = spell_db.resolve_spell_chain("MULTISHOT2")
    assert result is not None
    assert result["spell_id"] == "MULTISHOT2"
    assert result["display_name"] == "Multishot"
    assert result["cooldown"] == 3.0
    assert result["energy_cost"] == 4.0
    # Should have damage from sub-spell
    assert len(result["damage"]) >= 2
    pvp_dmg = [d for d in result["damage"] if d["target"] == "enemyplayers"]
    assert pvp_dmg
    assert pvp_dmg[0]["base_damage"] == 100.0
    assert pvp_dmg[0]["type"] == "physical"


def test_resolve_chain_splitting_slash(spell_db: SpellDatabase):
    result = spell_db.resolve_spell_chain("splitting slash")
    assert result is not None
    assert "SPLITTINGSLASH" in result["spell_id"]
    assert len(result["damage"]) >= 1
    assert result["damage"][0]["type"] == "physical"


def test_resolve_chain_not_found(spell_db: SpellDatabase):
    assert spell_db.resolve_spell_chain("FAKE_SPELL_999") is None


def test_resolve_chain_includes_passive_buffs(spell_db: SpellDatabase):
    result = spell_db.resolve_spell_chain("PASSIVE_MAXLOAD")
    assert result is not None
    assert any(b["type"] == "maxload" for b in result["buffs"])


def test_search_spells(spell_db: SpellDatabase):
    results = spell_db.search_spells("multishot", limit=10)
    assert len(results) >= 1
    assert any(r["spell_id"] == "MULTISHOT2" for r in results)


def test_search_spells_empty(spell_db: SpellDatabase):
    results = spell_db.search_spells("xyznonexistent999", limit=10)
    assert len(results) == 0


@pytest.mark.parametrize("spell_name,expected_id", [
    ("DEADLYSHOT", "DEADLYSHOT"),
    ("GROUNDARROW", "GROUNDARROW"),
    ("deadly shot", "DEADLYSHOT"),
])
def test_resolve_various_spells(spell_db: SpellDatabase, spell_name: str, expected_id: str):
    result = spell_db.resolve_spell_chain(spell_name)
    assert result is not None
    assert result["spell_id"] == expected_id


def test_buffovertime_food_spell(spell_db: SpellDatabase):
    """Food spells should have timed buffs with duration from buffovertime."""
    spell = spell_db.get_spell("FOOD_BUFF_DMG_P1")
    assert spell is not None
    timed_buffs = [b for b in spell.buffs if b.duration is not None]
    assert len(timed_buffs) >= 1
    # Stew gives 1800s (30min) buffs
    assert any(b.duration == 1800.0 for b in timed_buffs)
    assert any(b.buff_type == "physicalattackdamagebonus" for b in timed_buffs)


def test_buffovertime_resolve_chain(spell_db: SpellDatabase):
    """Resolved food spell chain should include buff duration and target."""
    result = spell_db.resolve_spell_chain("FOOD_BUFF_DMG_P1")
    assert result is not None
    assert len(result["buffs"]) >= 1
    timed = [b for b in result["buffs"] if b.get("duration")]
    assert len(timed) >= 1
    assert timed[0]["duration"] == 1800.0
    assert timed[0].get("target") == "self"


def test_permanent_buff_has_no_duration(spell_db: SpellDatabase):
    """Permanent passive buffs should have no duration."""
    spell = spell_db.get_spell("PASSIVE_MAXLOAD")
    assert spell is not None
    assert len(spell.buffs) >= 1
    assert spell.buffs[0].duration is None


def test_cc_stun_parsed(spell_db: SpellDatabase):
    """Spells with stun nodes should have crowd_control entries."""
    # Search for any spell with a stun
    stun_spells = [s for s in spell_db._spells.values() if any(cc.cc_type == "stun" for cc in s.crowd_control)]
    assert len(stun_spells) > 0
    stun = stun_spells[0].crowd_control[0]
    assert stun.cc_type == "stun"
    assert stun.duration > 0


def test_cc_root_parsed(spell_db: SpellDatabase):
    """Spells with root nodes should have crowd_control entries."""
    root_spells = [s for s in spell_db._spells.values() if any(cc.cc_type == "root" for cc in s.crowd_control)]
    assert len(root_spells) > 0
    root = root_spells[0].crowd_control[0]
    assert root.cc_type == "root"
    assert root.duration > 0


def test_resolve_chain_includes_cc(spell_db: SpellDatabase):
    """Resolved spell chain should propagate CC from sub-spells."""
    # Find a known spell with CC in its chain
    for spell in spell_db._spells.values():
        if spell.crowd_control:
            result = spell_db.resolve_spell_chain(spell.unique_name)
            assert result is not None
            assert len(result["crowd_control"]) >= 1
            cc = result["crowd_control"][0]
            assert "type" in cc
            assert "duration" in cc
            break


def test_dot_effect_has_interval_and_ticks(spell_db: SpellDatabase):
    """attributechangeovertime effects should carry interval and ticks."""
    # Find any spell with a DoT/HoT effect
    for spell in spell_db._spells.values():
        dot_effects = [e for e in spell.effects if e.interval is not None]
        if dot_effects:
            assert dot_effects[0].interval > 0
            assert dot_effects[0].ticks is not None
            break
    else:
        pytest.skip("No DoT spells found")
