"""Tests for market price endpoint."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.data import MarketServiceError
from app.web.main import app


client = TestClient(app)


def test_market_prices_success():
    mock_market = AsyncMock()
    mock_market.get_market_prices.return_value = {
        "item": {"id": "T4_BAG"},
        "locations": ["Caerleon"],
        "data": [{"location": "Caerleon"}],
        "cached": False,
        "fetched_at": "2026-02-01T00:00:00Z",
        "source": "albion-online-data.com",
    }
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.market.get_container", return_value=mock_container):
        response = client.get("/market/prices", params={"item": "T4 Bag", "city": "Caerleon"})

    assert response.status_code == 200
    data = response.json()
    assert data["item"]["id"] == "T4_BAG"
    assert data["data"][0]["location"] == "Caerleon"


def test_market_prices_no_data_returns_404():
    mock_market = AsyncMock()
    mock_market.get_market_prices.side_effect = MarketServiceError("No market data found", status_code=404)
    mock_container = type("Container", (), {"market": mock_market})()

    with patch("app.web.routers.market.get_container", return_value=mock_container):
        response = client.get("/market/prices", params={"item": "T4 Bag", "city": "Caerleon"})

    assert response.status_code == 404
