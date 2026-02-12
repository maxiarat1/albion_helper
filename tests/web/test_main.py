"""Tests for web API endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.application.item_label_service import ItemLabelApplicationService
from app.web.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "albion-helper-v2"
    assert data["status"] == "ok"
    assert data["version"] == "2.0"


def test_providers_endpoint():
    response = client.get("/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert set(providers) == {"ollama", "anthropic", "openai", "gemini"}


def test_item_labels_endpoint():
    mock_item = type(
        "ItemInfo",
        (),
        {
            "unique_name": "T4_BAG",
            "tier": 4,
            "enchantment": 0,
            "localized_names": {"EN-US": "Adept's Bag"},
        },
    )()

    mock_game_db = type("GameDB", (), {})()
    mock_game_db.get_item = lambda item_id: mock_item if item_id == "T4_BAG" else None
    mock_container = type(
        "Container",
        (),
        {"item_labels": ItemLabelApplicationService(game_db=mock_game_db)},
    )()

    with patch("app.web.routers.items.get_container", return_value=mock_container):
        response = client.get("/items/labels?ids=T4_BAG,T7_MAIN_SWORD")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert data["items"][0]["id"] == "T4_BAG"
    assert data["items"][0]["found"] is True
    assert data["items"][0]["display_name"] == "Adept's Bag"
    assert data["items"][0]["tier"] == 4
    assert data["items"][1]["id"] == "T7_MAIN_SWORD"
    assert data["items"][1]["found"] is False
    assert data["items"][1]["display_name"] == "T7_MAIN_SWORD"
    assert data["items"][1]["tier"] == 7


def test_item_labels_endpoint_requires_ids():
    response = client.get("/items/labels?ids=,")
    assert response.status_code == 400
    assert "required" in response.json()["detail"]


def test_chat_invalid_provider_returns_422():
    payload = {
        "provider": "invalid-provider",
        "model": "test-model",
        "messages": [{"role": "user", "content": "test"}],
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 422


def test_chat_non_streaming_anthropic_returns_text():
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.return_value = {"content": [{"text": "Test response"}]}

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        payload = {
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "messages": [{"role": "user", "content": "test"}],
            "stream": False,
            "options": {"max_tokens": 32},
        }
        response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["text"] == "Test response"
    mock_provider.chat.assert_awaited_once()


def test_chat_non_streaming_anthropic_reasoning_applies_thinking_and_token_reserve():
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.return_value = {
        "content": [
            {"type": "thinking", "thinking": "internal trace"},
            {"type": "text", "text": "Reasoned response"},
        ]
    }

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        payload = {
            "provider": "anthropic",
            "model": "claude-3-sonnet",
            "messages": [{"role": "user", "content": "test"}],
            "stream": False,
            "options": {
                "max_tokens": 1024,
                "reasoning": {
                    "enabled": True,
                    "provider_native": True,
                    "anthropic_budget_tokens": 2048,
                    "anthropic_output_reserve_tokens": 256,
                },
            },
        }
        response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["text"] == "Reasoned response"
    called_kwargs = mock_provider.chat.await_args.kwargs
    assert called_kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert called_kwargs["max_tokens"] >= 2304


def test_chat_non_streaming_openai_reasoning_sets_effort():
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.return_value = {
        "choices": [{"message": {"content": "OpenAI response"}}]
    }

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        payload = {
            "provider": "openai",
            "model": "o3-mini",
            "messages": [{"role": "user", "content": "test"}],
            "stream": False,
            "options": {
                "reasoning": {
                    "enabled": True,
                    "provider_native": True,
                    "effort": "high",
                },
            },
        }
        response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["text"] == "OpenAI response"
    called_kwargs = mock_provider.chat.await_args.kwargs
    assert called_kwargs["reasoning_effort"] == "high"


def test_chat_non_streaming_ollama_reasoning_sets_native_think_level():
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.return_value = {
        "message": {"content": "Ollama response"},
    }

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        payload = {
            "provider": "ollama",
            "model": "gpt-oss:20b",
            "messages": [{"role": "user", "content": "test"}],
            "stream": False,
            "options": {
                "reasoning": {
                    "enabled": True,
                    "provider_native": True,
                    "ollama_think": "high",
                },
            },
        }
        response = client.post("/chat", json=payload)

    assert response.status_code == 200
    assert response.json()["text"] == "Ollama response"
    called_kwargs = mock_provider.chat.await_args.kwargs
    assert called_kwargs["think"] == "high"


def test_list_ollama_models():
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.list_models.return_value = {
        "models": [
            {"name": "llama3:latest"},
            {"name": "gpt-oss:20b"},
        ]
    }
    mock_provider.show_model = AsyncMock(side_effect=[
        {"capabilities": ["completion"]},
        {"capabilities": ["completion", "thinking"]},
    ])

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        response = client.get("/ollama/models")

    assert response.status_code == 200
    data = response.json()
    assert len(data["models"]) == 2
    assert data["models"][0]["name"] == "llama3:latest"
    assert data["models"][0]["thinking"]["supported"] is False
    assert data["models"][1]["name"] == "gpt-oss:20b"
    assert data["models"][1]["thinking"]["supported"] is True
    assert data["models"][1]["thinking"]["mode_type"] == "levels"
    assert data["models"][1]["thinking"]["modes"] == ["low", "medium", "high"]


# =============================================================================
# Database Endpoints
# =============================================================================


def test_db_status_endpoint():
    """Test the /db/status endpoint."""
    mock_status = type(
        "DatabaseStatus",
        (),
        {
            "initialized": True,
            "total_records": 1000,
            "earliest_date": "2026-01-01",
            "latest_date": "2026-01-31",
            "imported_dumps": ["dump1.sql.gz"],
            "coverage_months": [],
        },
    )()

    mock_market = AsyncMock()
    mock_market.get_db_status.return_value = {
        "database": {
            "initialized": mock_status.initialized,
            "total_records": mock_status.total_records,
            "date_range": {
                "earliest": mock_status.earliest_date,
                "latest": mock_status.latest_date,
            },
            "imported_dumps_count": len(mock_status.imported_dumps),
            "imported_dumps": mock_status.imported_dumps[:10],
        },
        "coverage": {"months": []},
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get("/db/status")

    assert response.status_code == 200
    data = response.json()
    assert data["database"]["initialized"] is True
    assert data["database"]["total_records"] == 1000


def test_db_coverage_endpoint():
    """Test the /db/coverage endpoint."""
    mock_coverage = type(
        "MonthCoverage",
        (),
        {
            "year": 2026,
            "month": 1,
            "record_count": 1000,
            "has_data": True,
            "to_dict": lambda self: {
                "year": self.year,
                "month": self.month,
                "record_count": self.record_count,
                "has_data": self.has_data,
            },
        },
    )()

    mock_status = type(
        "DatabaseStatus",
        (),
        {
            "initialized": True,
            "total_records": 1000,
            "earliest_date": "2026-01-01",
            "latest_date": "2026-01-31",
            "imported_dumps": [],
            "coverage_months": [mock_coverage],
        },
    )()

    mock_market = type("MarketApp", (), {})()
    mock_market.get_db_coverage = lambda: {
        "initialized": mock_status.initialized,
        "total_records": mock_status.total_records,
        "date_range": {
            "earliest": mock_status.earliest_date,
            "latest": mock_status.latest_date,
        },
        "coverage": {"months": [mock_coverage.to_dict()]},
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get("/db/coverage")

    assert response.status_code == 200
    data = response.json()
    assert data["initialized"] is True
    assert len(data["coverage"]["months"]) == 1


def test_db_history_endpoint():
    """Test the /db/history endpoint."""
    mock_data = [
        {
            "period": "2026-01-15",
            "location": "Caerleon",
            "avg_sell_min": 2500,
            "avg_sell_max": 3000,
            "avg_buy_min": 2000,
            "avg_buy_max": 2300,
            "total_volume": 100,
            "data_points": 5,
        }
    ]

    mock_match = type(
        "ItemMatch",
        (),
        {
            "unique_name": "T4_BAG",
            "display_name": "Adept's Bag",
        },
    )()

    mock_resolution = type(
        "Resolution",
        (),
        {
            "matches": [mock_match],
            "resolved": True,
        },
    )()

    mock_market = AsyncMock()
    mock_market.get_db_history.return_value = {
        "item": {
            "query": "T4 Bag",
            "id": "T4_BAG",
            "display_name": "Adept's Bag",
        },
        "locations": None,
        "quality": None,
        "granularity": "daily",
        "date_range": {"start": None, "end": None},
        "data": mock_data,
        "record_count": 1,
        "source": "local_duckdb",
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get("/db/history?item=T4%20Bag")

    assert response.status_code == 200
    data = response.json()
    assert data["item"]["id"] == "T4_BAG"
    assert data["record_count"] == 1
    assert data["source"] == "local_duckdb"


def test_db_history_endpoint_with_latest_api():
    """Test /db/history with optional latest API prices enabled."""
    mock_data = [
        {
            "period": "2026-01-15",
            "location": "Caerleon",
            "avg_sell_min": 2500,
            "avg_sell_max": 3000,
            "avg_buy_min": 2000,
            "avg_buy_max": 2300,
            "total_volume": 100,
            "data_points": 5,
        }
    ]

    latest_response = {
        "item": {"id": "T4_BAG"},
        "data": [
            {
                "location": "Caerleon",
                "quality": 1,
                "sell_price_min": 2800,
                "buy_price_min": 2300,
            }
        ],
        "freshness": {"fresh_entries": 1, "total_entries": 1},
        "fetched_at": "2026-02-06T00:00:00Z",
    }

    mock_market = AsyncMock()
    mock_market.get_db_history.return_value = {
        "item": {
            "query": "T4 Bag",
            "id": "T4_BAG",
            "display_name": "Adept's Bag",
        },
        "locations": ["Caerleon"],
        "quality": None,
        "granularity": "daily",
        "date_range": {"start": None, "end": None},
        "data": mock_data,
        "record_count": 1,
        "source": "local_duckdb",
        "latest_market": latest_response,
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get(
            "/db/history?item=T4%20Bag&cities=Caerleon&include_latest_api=true"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["item"]["id"] == "T4_BAG"
    assert data["latest_market"]["data"][0]["sell_price_min"] == 2800
    mock_market.get_db_history.assert_awaited_once()


def test_db_history_endpoint_with_latest_api_error_is_non_fatal():
    """Latest API failures should not fail historical response."""
    mock_data = [
        {
            "period": "2026-01-15",
            "location": "Caerleon",
            "avg_sell_min": 2500,
            "avg_sell_max": 3000,
            "avg_buy_min": 2000,
            "avg_buy_max": 2300,
            "total_volume": 100,
            "data_points": 5,
        }
    ]

    mock_market = AsyncMock()
    mock_market.get_db_history.return_value = {
        "item": {
            "query": "T4 Bag",
            "id": "T4_BAG",
            "display_name": "Adept's Bag",
        },
        "locations": ["Caerleon"],
        "quality": None,
        "granularity": "daily",
        "date_range": {"start": None, "end": None},
        "data": mock_data,
        "record_count": 1,
        "source": "local_duckdb",
        "latest_market": {
            "error": "No market data",
            "status_code": 404,
        },
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get(
            "/db/history?item=T4%20Bag&cities=Caerleon&include_latest_api=true"
        )

    assert response.status_code == 200
    data = response.json()
    assert data["record_count"] == 1
    assert data["latest_market"]["status_code"] == 404
    assert "No market data" in data["latest_market"]["error"]


def test_db_update_endpoint():
    """Test the /db/update endpoint."""
    mock_result = type(
        "UpdateResult",
        (),
        {
            "success": True,
            "downloaded": ["dump1.sql.gz"],
            "imported": ["dump1.sql.gz"],
            "errors": [],
            "total_records": 1000,
            "to_dict": lambda self: {
                "success": self.success,
                "downloaded": self.downloaded,
                "imported": self.imported,
                "errors": self.errors,
                "total_records": self.total_records,
            },
        },
    )()

    mock_market = AsyncMock()
    mock_market.update_db.return_value = mock_result.to_dict()
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.post("/db/update", json={"max_dumps": 3})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["total_records"] == 1000


def test_db_update_start_endpoint():
    """Test the /db/update/start endpoint."""
    mock_market = type("MarketApp", (), {})()
    mock_market.start_db_update = lambda max_dumps: {
        "started": True,
        "run_id": "run-123",
        "progress": {
            "status": "running",
            "stage": "starting",
            "progress_pct": 1.0,
        },
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.post("/db/update/start", json={"max_dumps": 2})

    assert response.status_code == 200
    data = response.json()
    assert data["started"] is True
    assert data["run_id"] == "run-123"
    assert data["progress"]["status"] == "running"


def test_db_update_progress_endpoint():
    """Test the /db/update/progress endpoint."""
    mock_market = type("MarketApp", (), {})()
    mock_market.get_db_update_progress = lambda: {
        "status": "running",
        "stage": "downloading",
        "progress_pct": 42.5,
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.get("/db/update/progress")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["stage"] == "downloading"
    assert data["progress_pct"] == 42.5


def test_db_update_progress_clear_endpoint():
    """Test the /db/update/progress/clear endpoint."""
    mock_market = type("MarketApp", (), {})()
    mock_market.clear_db_update_progress = lambda: {
        "status": "idle",
        "stage": "idle",
        "progress_pct": 0.0,
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.post("/db/update/progress/clear")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "idle"
    assert data["stage"] == "idle"
    assert data["progress_pct"] == 0.0


def test_db_reset_endpoint():
    """Test the /db/reset endpoint."""
    mock_market = type("MarketApp", (), {})()
    mock_market.reset_db = lambda cleanup_dumps: {
        "success": True,
        "reset": {
            "removed_records": 123,
            "removed_imports": 4,
        },
        "cleaned_dumps_count": 0,
        "cleaned_dumps": [],
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.database.get_container", return_value=mock_container):
        response = client.post("/db/reset", json={"cleanup_dumps": False})

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["reset"]["removed_records"] == 123
    assert data["reset"]["removed_imports"] == 4
