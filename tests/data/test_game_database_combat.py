"""Tests for GameDatabase combat field extensions."""

from pathlib import Path

import pytest

from app.data.game_database import GameDatabase

DATA_DIR = Path("docs/ao-bin-dumps")


@pytest.fixture(scope="module")
def game_db():
    db = GameDatabase(items_path=DATA_DIR / "items.json")
    db._ensure_loaded()
    return db


def test_weapon_item_power(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.item_power == 700


def test_weapon_ability_power(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.ability_power == 120


def test_weapon_two_handed(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.two_handed is True


def test_weapon_one_handed(game_db: GameDatabase):
    item = game_db.get_item("T4_MAIN_SWORD")
    assert item is not None
    assert item.two_handed is False


def test_weapon_spell_list(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert len(item.spell_list) > 0
    assert "MULTISHOT2" in item.spell_list
    assert "DEADLYSHOT" in item.spell_list


def test_weapon_enchantment_ips(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.enchantment_ips.get(1) == 800
    assert item.enchantment_ips.get(2) == 900
    assert item.enchantment_ips.get(3) == 1000
    assert item.enchantment_ips.get(4) == 1100


def test_weapon_ip_progression_type(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.ip_progression_type == "mainhand"


def test_weapon_combat_spec_achievement(game_db: GameDatabase):
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.combat_spec_achievement == "COMBAT_BOWS_BOW"


def test_non_weapon_has_no_spells(game_db: GameDatabase):
    item = game_db.get_item("T4_BAG")
    assert item is not None
    assert item.spell_list == []


def test_item_spell_entries_resolve_reference(game_db: GameDatabase):
    entries = game_db.get_item_spell_entries("T4_BAG")
    assert any(e["spell_id"] == "PASSIVE_MAXLOAD" for e in entries)
    assert all(e["slot"] == "passive" for e in entries)


def test_weapon_spell_entries_include_slots(game_db: GameDatabase):
    entries = game_db.get_item_spell_entries("T4_2H_BOW")
    slots = {e["slot"] for e in entries}
    assert "Q" in slots
    assert "W" in slots
    assert "E" in slots


def test_equipment_has_item_power(game_db: GameDatabase):
    item = game_db.get_item("T4_HEAD_CLOTH_SET1")
    assert item is not None
    assert item.item_power > 0


def test_weapon_attack_stats(game_db: GameDatabase):
    """Weapon should have auto-attack stats parsed."""
    item = game_db.get_item("T4_MAIN_SWORD")
    assert item is not None
    assert item.attack_damage == 33.0
    assert item.attack_speed == 1.35
    assert item.attack_range == 3.0
    assert item.attack_type == "melee"


def test_non_weapon_no_attack_stats(game_db: GameDatabase):
    """Non-weapon items should have zero attack stats."""
    item = game_db.get_item("T4_BAG")
    assert item is not None
    assert item.attack_damage == 0
    assert item.attack_type == ""


def test_consumable_consume_spell(game_db: GameDatabase):
    """Food items should have consume_spell populated."""
    item = game_db.get_item("T4_MEAL_STEW")
    assert item is not None
    assert item.consume_spell == "FOOD_BUFF_DMG_P1"


def test_consumable_spell_entries(game_db: GameDatabase):
    """get_item_spell_entries should return consumespell for food."""
    entries = game_db.get_item_spell_entries("T4_MEAL_STEW")
    assert len(entries) >= 1
    assert entries[0]["spell_id"] == "FOOD_BUFF_DMG_P1"
    assert entries[0]["slot"] == "consumable"


def test_weapon_no_consume_spell(game_db: GameDatabase):
    """Weapons should not have consume_spell."""
    item = game_db.get_item("T4_2H_BOW")
    assert item is not None
    assert item.consume_spell == ""
