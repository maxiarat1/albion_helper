"""Tests for MCP tool endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.data import MarketServiceError
from app.web.main import app


client = TestClient(app)


def test_list_tools():
    response = client.post("/mcp/tools/list")
    assert response.status_code == 200
    tools = response.json()["tools"]
    tool_names = {tool["name"] for tool in tools}
    # Market tools
    assert "market_data" in tool_names
    # Game data tools
    assert "item_info" in tool_names
    assert "crafting_recipe" in tool_names
    assert "search_items" in tool_names
    assert "search_activities" in tool_names
    assert "resolve_item" in tool_names
    # History DB tools
    assert "db_status" in tool_names
    # Combat tools
    assert "spell_info" in tool_names
    assert "weapon_abilities" in tool_names
    assert "destiny_fame" in tool_names
    assert "destiny_ip_scaling" in tool_names
    assert "destiny_quality_bonus" in tool_names
    assert "search_destiny" in tool_names
    assert "destiny_info" not in tool_names
    assert "market_history" not in tool_names
    # Admin-only tools should not be exposed by default
    assert "db_update" not in tool_names
    assert "read_self" not in tool_names
    assert "update_soul" not in tool_names
    assert "save_memory" not in tool_names
    assert "learn_skill" not in tool_names
    # Should be exactly 15 public tools
    assert len(tools) == 15


def test_call_resolve_item():
    with patch("app.mcp.tools.gamedata.smart_resolver") as mock_resolver:
        mock_result = type("Result", (), {
            "resolved": True,
            "matches": [type("Match", (), {
                "unique_name": "T4_BAG",
                "display_name": "T4 Bag",
                "tier": 4,
                "enchantment": 0,
                "category": "",
                "subcategory": "",
                "score": 1.0,
                "match_reason": "exact",
            })()],
            "to_dict": lambda self: {
                "resolved": True,
                "query": "T4 Bag",
                "matches": [{"unique_name": "T4_BAG", "display_name": "T4 Bag"}],
            },
        })()
        mock_resolver.resolve.return_value = mock_result

        response = client.post(
            "/mcp/tools/call",
            json={"name": "resolve_item", "arguments": {"query": "T4 Bag"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False


def test_call_market_data_handles_error():
    with patch("app.mcp.tools.market.market_app") as mock_market:
        mock_market.get_market_prices = AsyncMock(
            side_effect=MarketServiceError("No market data found", status_code=404)
        )

        response = client.post(
            "/mcp/tools/call",
            json={"name": "market_data", "arguments": {"item": "T4 Bag"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is True


def test_call_item_info_includes_stats_and_effects():
    fake_item = type("Item", (), {
        "unique_name": "T4_BAG",
        "tier": 4,
        "enchantment": 0,
        "category": "equipmentitem",
        "subcategory": "bags",
        "slot_type": "bag",
        "weight": 3.4,
        "max_quality": 5,
        "crafting_recipes": [{"id": 1}],
        "localized_names": {"EN-US": "Adept's Bag"},
        "item_power": 700,
        "ability_power": 100,
        "two_handed": False,
        "ip_progression_type": "bag",
        "combat_spec_achievement": "COMBAT_BAGS",
        "enchantment_ips": {1: 800},
        "attack_damage": 0,
        "attack_speed": 0,
        "attack_range": 0,
        "attack_type": "",
        "raw_data": {"@movespeedbonus": "0", "@hitpointsmax": "40"},
    })()

    with (
        patch("app.mcp.tools.gamedata.game_db.get_item", return_value=fake_item),
        patch(
            "app.mcp.tools.gamedata.game_db.get_item_spell_entries",
            return_value=[{"spell_id": "PASSIVE_MAXLOAD", "slot": "passive"}],
        ),
        patch(
            "app.mcp.tools.gamedata.spell_db.resolve_spell_chain",
            return_value={
                "spell_id": "PASSIVE_MAXLOAD",
                "display_name": "Trudge",
                "category": "",
                "cooldown": 0,
                "energy_cost": 0,
                "cast_range": 0,
                "casting_time": 0,
                "damage": [],
                "effects": [],
                "buffs": [{"type": "maxload", "values": {"value": 1.0}, "source_spell": "PASSIVE_MAXLOAD"}],
                "sub_spells": [],
            },
        ),
    ):
        response = client.post(
            "/mcp/tools/call",
            json={"name": "item_info", "arguments": {"item": "T4_BAG"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    payload = data["structuredContent"]
    assert payload["item_stats"]["item_power"] == 700
    assert payload["item_stats"]["modifiers"]["max_hp"] == 40
    assert payload["item_effects"][0]["spell_id"] == "PASSIVE_MAXLOAD"
    assert payload["item_effects"][0]["buffs"][0]["type"] == "maxload"


def test_call_item_info_computes_max_load_progression_table():
    fake_item = type("Item", (), {
        "unique_name": "T4_BAG",
        "tier": 4,
        "enchantment": 0,
        "category": "equipmentitem",
        "subcategory": "bags",
        "slot_type": "bag",
        "weight": 3.4,
        "max_quality": 5,
        "crafting_recipes": [{"id": 1}],
        "localized_names": {"EN-US": "Adept's Bag"},
        "item_power": 700,
        "ability_power": 100,
        "two_handed": False,
        "ip_progression_type": "bag",
        "combat_spec_achievement": "COMBAT_BAGS",
        "enchantment_ips": {1: 800, 2: 900, 3: 1000, 4: 1100},
        "attack_damage": 0,
        "attack_speed": 0,
        "attack_range": 0,
        "attack_type": "",
        "raw_data": {},
    })()

    with (
        patch("app.mcp.tools.gamedata.game_db.get_item", return_value=fake_item),
        patch(
            "app.mcp.tools.gamedata.game_db.get_item_spell_entries",
            return_value=[{"spell_id": "PASSIVE_MAXLOAD", "slot": "passive"}],
        ),
        patch(
            "app.mcp.tools.gamedata.spell_db.resolve_spell_chain",
            return_value={
                "spell_id": "PASSIVE_MAXLOAD",
                "display_name": "Trudge",
                "category": "",
                "cooldown": 0,
                "energy_cost": 0,
                "cast_range": 0,
                "casting_time": 0,
                "damage": [],
                "effects": [],
                "buffs": [{"type": "maxload", "values": {"value": 1.0}, "source_spell": "PASSIVE_MAXLOAD"}],
                "sub_spells": [],
            },
        ),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_ip_scaling",
            return_value=type("Scaling", (), {"ability_power_progression": 1.0918})(),
        ),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_ability_power_progression",
            return_value=type(
                "AbilityPower",
                (),
                {"base_damage": 100.0, "base_load": 25.0, "load_progression": 2.264101591},
            )(),
        ),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_quality_bonus",
            side_effect=lambda q: {1: 0, 2: 20, 3: 40, 4: 60, 5: 100}[q],
        ),
    ):
        response = client.post(
            "/mcp/tools/call",
            json={"name": "item_info", "arguments": {"item": "T4_BAG"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    payload = data["structuredContent"]

    max_load = payload["item_stats"]["max_load"]
    assert max_load["source_spell"] == "PASSIVE_MAXLOAD"
    rows = max_load["values"]

    def value_for(enchantment: int, quality: int) -> int:
        for row in rows:
            if row["enchantment"] == enchantment and row["quality"] == quality:
                return row["max_load_kg"]
        raise AssertionError(f"missing row for enchantment={enchantment} quality={quality}")

    assert value_for(0, 1) == 76
    assert value_for(0, 5) == 98
    assert value_for(1, 1) == 98
    assert value_for(4, 5) == 247


def test_call_item_info_computes_cape_energy_progression_table():
    fake_item = type("Item", (), {
        "unique_name": "T4_CAPE",
        "tier": 4,
        "enchantment": 0,
        "category": "equipmentitem",
        "subcategory": "accessoires_capes_capes",
        "slot_type": "cape",
        "weight": 1.7,
        "max_quality": 5,
        "crafting_recipes": [{"id": 1}],
        "localized_names": {"EN-US": "Adept's Cape"},
        "item_power": 700,
        "ability_power": 100,
        "two_handed": False,
        "ip_progression_type": "cape",
        "combat_spec_achievement": "COMBAT_CAPES",
        "enchantment_ips": {1: 800, 2: 900, 3: 1000, 4: 1100},
        "attack_damage": 0,
        "attack_speed": 0,
        "attack_range": 0,
        "attack_type": "",
        "raw_data": {},
    })()

    with (
        patch("app.mcp.tools.gamedata.game_db.get_item", return_value=fake_item),
        patch("app.mcp.tools.gamedata.game_db.get_item_spell_entries", return_value=[]),
        patch("app.mcp.tools.gamedata.spell_db.resolve_spell_chain", return_value=None),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_ip_scaling",
            return_value=type("Scaling", (), {"energy_progression": 1.0918})(),
        ),
        patch("app.mcp.tools.gamedata.destiny_db.get_energy_share", return_value=0.10),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_base_stats",
            return_value={"energy": 120.0, "energy_regen": 1.5},
        ),
        patch(
            "app.mcp.tools.gamedata.destiny_db.get_quality_bonus",
            side_effect=lambda q: {1: 0, 2: 20, 3: 40, 4: 60, 5: 100}[q],
        ),
    ):
        response = client.post(
            "/mcp/tools/call",
            json={"name": "item_info", "arguments": {"item": "T4_CAPE"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    payload = data["structuredContent"]

    cape_energy = payload["item_stats"]["cape_energy"]
    rows = cape_energy["values"]

    def row_for(enchantment: int, quality: int) -> dict:
        for row in rows:
            if row["enchantment"] == enchantment and row["quality"] == quality:
                return row
        raise AssertionError(f"missing row for enchantment={enchantment} quality={quality}")

    row_40_q1 = row_for(0, 1)
    assert row_40_q1["max_energy"] == 10
    assert row_40_q1["energy_regeneration_per_second"] == 0.13

    row_41_q5 = row_for(1, 5)
    assert row_41_q5["max_energy"] == 14
    assert row_41_q5["energy_regeneration_per_second"] == 0.18

    row_44_q5 = row_for(4, 5)
    assert row_44_q5["max_energy"] == 22
    assert row_44_q5["energy_regeneration_per_second"] == 0.28


def test_market_data_history_live_source_uses_market_service():
    with (
        patch("app.mcp.tools.market.resolve_item_smart", return_value=("T4_BAG", None)),
        patch("app.mcp.tools.market.market_app") as mock_market,
    ):
        mock_market.get_live_history = AsyncMock(
            return_value={
                "item": {"query": "T4_BAG", "id": "T4_BAG"},
                "locations": ["Caerleon"],
                "quality": None,
                "time_scale": "hourly",
                "start_date": None,
                "end_date": None,
                "data": [],
                "region": "west",
                "fetched_at": "2026-01-01T00:00:00Z",
                "source": "https://example.test",
            }
        )

        response = client.post(
            "/mcp/tools/call",
            json={
                "name": "market_data",
                "arguments": {
                    "item": "T4 Bag",
                    "mode": "history",
                    "source": "live",
                    "cities": ["Caerleon"],
                },
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    assert "structuredContent" in data
    assert data["structuredContent"]["source"]["requested"] == "live"
