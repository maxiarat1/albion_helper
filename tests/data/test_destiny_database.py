"""Tests for DestinyDatabase."""

from pathlib import Path

import pytest

from app.data.destiny_database import DestinyDatabase

DATA_DIR = Path("docs/ao-bin-dumps")


@pytest.fixture(scope="module")
def destiny_db():
    db = DestinyDatabase(data_dir=DATA_DIR)
    db._ensure_loaded()
    return db


def test_load_nodes(destiny_db: DestinyDatabase):
    assert len(destiny_db._nodes) > 500


def test_load_templates(destiny_db: DestinyDatabase):
    assert len(destiny_db._templates) == 24


def test_load_ip_scaling(destiny_db: DestinyDatabase):
    assert len(destiny_db._ip_scaling) > 10


def test_load_base_stats(destiny_db: DestinyDatabase):
    stats = destiny_db.get_base_stats()
    assert stats["hp"] == 1200.0
    assert stats["energy"] == 120.0
    assert stats["premium_fame_factor"] == 1.5


def test_get_destiny_node(destiny_db: DestinyDatabase):
    node = destiny_db.get_destiny_node("COMBAT_BOWS")
    assert node is not None
    assert node.template_name == "COMBAT_BASE"
    assert node.category == "fighting"
    assert node.total_levels == 100


def test_get_destiny_node_case_insensitive(destiny_db: DestinyDatabase):
    node = destiny_db.get_destiny_node("combat_bows")
    assert node is not None
    assert node.node_id == "COMBAT_BOWS"


def test_get_destiny_node_not_found(destiny_db: DestinyDatabase):
    assert destiny_db.get_destiny_node("NONEXISTENT_XYZ") is None


def test_fame_to_level_range(destiny_db: DestinyDatabase):
    result = destiny_db.get_fame_to_level("COMBAT_BOWS", 0, 10)
    assert result is not None
    assert result["from_level"] == 0
    assert result["to_level"] == 10
    assert result["level_count"] == 10
    assert result["total_fame_required"] > 0
    assert result["total_lp_cost"] > 0
    assert len(result["levels"]) == 10


def test_fame_to_level_full(destiny_db: DestinyDatabase):
    result = destiny_db.get_fame_to_level("COMBAT_BOWS", 0, 100)
    assert result is not None
    assert result["level_count"] == 100
    assert result["total_fame_required"] > 1_000_000


def test_fame_to_level_mid_range(destiny_db: DestinyDatabase):
    result = destiny_db.get_fame_to_level("COMBAT_BOWS", 40, 60)
    assert result is not None
    assert result["from_level"] == 40
    assert result["to_level"] == 60
    assert result["level_count"] == 20


def test_fame_to_level_not_found(destiny_db: DestinyDatabase):
    assert destiny_db.get_fame_to_level("FAKE_NODE", 0, 50) is None


def test_ip_scaling_mainhand_2h(destiny_db: DestinyDatabase):
    scaling = destiny_db.get_ip_scaling("mainhand_2h")
    assert scaling is not None
    assert scaling.attack_damage_progression == 1.0918
    assert scaling.ability_power_progression == 1.0918
    assert scaling.hp_progression == 1.06
    assert scaling.armor_progression == 1.03


def test_ip_scaling_mainhand_1h(destiny_db: DestinyDatabase):
    scaling = destiny_db.get_ip_scaling("mainhand_1h")
    assert scaling is not None
    assert scaling.attack_damage_progression == 1.0825


def test_ip_scaling_not_found(destiny_db: DestinyDatabase):
    assert destiny_db.get_ip_scaling("fake_slot") is None


def test_ability_power_progression_constants(destiny_db: DestinyDatabase):
    progression = destiny_db.get_ability_power_progression()
    assert progression.base_damage == 100.0
    assert progression.base_load == 25.0
    assert progression.load_progression == pytest.approx(2.264101591)


def test_energy_share_cape(destiny_db: DestinyDatabase):
    assert destiny_db.get_energy_share("cape") == pytest.approx(0.10)


@pytest.mark.parametrize("quality,expected_bonus", [
    (1, 0),
    (2, 20),
    (3, 40),
    (4, 60),
    (5, 100),
])
def test_quality_bonus(destiny_db: DestinyDatabase, quality: int, expected_bonus: int):
    assert destiny_db.get_quality_bonus(quality) == expected_bonus


def test_search_destiny_nodes(destiny_db: DestinyDatabase):
    results = destiny_db.search_destiny_nodes(query="BOW")
    assert len(results) >= 1
    assert any(r["node_id"] == "COMBAT_BOWS" for r in results)


def test_search_destiny_by_category(destiny_db: DestinyDatabase):
    results = destiny_db.search_destiny_nodes(category="gathering")
    assert len(results) >= 5
    assert all(r["category"] == "gathering" for r in results)
