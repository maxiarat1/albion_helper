"""Tests for market service, including freshness filtering."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.data.market_service import FreshnessInfo, MarketService, _is_empty_entry


class TestFreshnessInfo:
    """Tests for FreshnessInfo dataclass."""

    def test_to_dict(self):
        info = FreshnessInfo(
            max_age_s=900,
            total_entries=5,
            fresh_entries=3,
            stale_entries=2,
        )
        result = info.to_dict()

        assert result["max_age_seconds"] == 900
        assert result["max_age_minutes"] == 15.0
        assert result["total_entries"] == 5
        assert result["fresh_entries"] == 3
        assert result["stale_entries"] == 2


class TestIsEmptyEntry:
    """Tests for the _is_empty_entry helper."""

    def test_all_zeros_is_empty(self):
        entry = {
            "sell_price_min": 0,
            "sell_price_max": 0,
            "buy_price_min": 0,
            "buy_price_max": 0,
        }
        assert _is_empty_entry(entry) is True

    def test_any_nonzero_is_not_empty(self):
        entry = {
            "sell_price_min": 100,
            "sell_price_max": 0,
            "buy_price_min": 0,
            "buy_price_max": 0,
        }
        assert _is_empty_entry(entry) is False

    def test_missing_keys_is_empty(self):
        assert _is_empty_entry({}) is True

    def test_buy_only_is_not_empty(self):
        entry = {
            "sell_price_min": 0,
            "sell_price_max": 0,
            "buy_price_min": 0,
            "buy_price_max": 500,
        }
        assert _is_empty_entry(entry) is False


class TestSentinelDates:
    """Tests for sentinel date handling."""

    @pytest.fixture
    def service(self):
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                mock_cache_instance = mock_cache.return_value
                mock_cache_instance.get.return_value = None
                mock_resolver_instance = mock_resolver.from_env.return_value

                service = MarketService(
                    cache=mock_cache_instance,
                    resolver=mock_resolver_instance,
                    base_url="https://europe.albion-online-data.com",
                    timeout_s=15,
                    freshness_ttl_s=900,
                )
                yield service

    def test_parse_timestamp_sentinel_returns_none(self, service):
        """0001-01-01 is treated as no data."""
        assert service._parse_timestamp("0001-01-01T00:00:00") is None

    def test_parse_timestamp_real_date(self, service):
        result = service._parse_timestamp("2026-02-07T11:20:00")
        assert result is not None
        assert result.year == 2026

    def test_parse_timestamp_none_input(self, service):
        assert service._parse_timestamp(None) is None

    def test_clean_date_sentinel(self, service):
        assert service._clean_date("0001-01-01T00:00:00") is None

    def test_clean_date_real(self, service):
        assert service._clean_date("2026-02-07T11:20:00") == "2026-02-07T11:20:00"

    def test_clean_date_none(self, service):
        assert service._clean_date(None) is None


class TestMarketServiceFreshness:
    """Tests for freshness filtering in MarketService."""

    @pytest.fixture
    def service(self):
        """Create a MarketService with mocked dependencies."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                mock_cache_instance = mock_cache.return_value
                mock_cache_instance.get.return_value = None

                mock_resolver_instance = mock_resolver.from_env.return_value
                mock_resolver_instance.resolve.return_value = type(
                    "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                )()

                service = MarketService(
                    cache=mock_cache_instance,
                    resolver=mock_resolver_instance,
                    base_url="https://europe.albion-online-data.com",
                    timeout_s=15,
                    freshness_ttl_s=900,  # 15 minutes
                )
                yield service

    def test_filter_by_freshness_all_fresh(self, service):
        """Test filtering when all entries are fresh."""
        now = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()

        entries = [
            {"location": "Caerleon", "sell_price_min": 1000, "sell_price_min_date": five_min_ago},
            {"location": "Bridgewatch", "sell_price_min": 1100, "sell_price_min_date": five_min_ago},
        ]

        filtered, info = service._filter_by_freshness(entries, max_age_s=900, now=now)

        assert len(filtered) == 2
        assert info.fresh_entries == 2
        assert info.stale_entries == 0

    def test_filter_by_freshness_some_stale(self, service):
        """Test filtering when some entries are stale."""
        now = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()
        thirty_min_ago = (now - timedelta(minutes=30)).isoformat()

        entries = [
            {"location": "Caerleon", "sell_price_min": 1000, "sell_price_min_date": five_min_ago},
            {"location": "Bridgewatch", "sell_price_min": 1100, "sell_price_min_date": thirty_min_ago},
        ]

        filtered, info = service._filter_by_freshness(entries, max_age_s=900, now=now)

        assert len(filtered) == 1
        assert filtered[0]["location"] == "Caerleon"
        assert info.fresh_entries == 1
        assert info.stale_entries == 1

    def test_filter_by_freshness_missing_timestamp(self, service):
        """Test filtering when entries have no timestamp."""
        now = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()

        entries = [
            {"location": "Caerleon", "sell_price_min": 1000, "sell_price_min_date": five_min_ago},
            {"location": "Bridgewatch", "sell_price_min": 1100, "sell_price_min_date": None},
        ]

        filtered, info = service._filter_by_freshness(entries, max_age_s=900, now=now)

        assert len(filtered) == 1
        assert info.stale_entries == 1

    def test_filter_by_freshness_sentinel_date_is_stale(self, service):
        """Entries with 0001-01-01 sentinel dates are treated as stale."""
        now = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()

        entries = [
            {"location": "Caerleon", "sell_price_min": 1000, "sell_price_min_date": five_min_ago},
            {"location": "Bridgewatch", "sell_price_min": 1100, "sell_price_min_date": "0001-01-01T00:00:00"},
        ]

        filtered, info = service._filter_by_freshness(entries, max_age_s=900, now=now)

        assert len(filtered) == 1
        assert filtered[0]["location"] == "Caerleon"
        assert info.stale_entries == 1

    def test_filter_by_freshness_adds_age_seconds(self, service):
        """Test that filtered entries include age_seconds."""
        now = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()

        entries = [
            {"location": "Caerleon", "sell_price_min": 1000, "sell_price_min_date": five_min_ago},
        ]

        filtered, _ = service._filter_by_freshness(entries, max_age_s=900, now=now)

        assert "age_seconds" in filtered[0]
        assert filtered[0]["age_seconds"] == pytest.approx(300.0, rel=0.1)


class TestMarketServiceGetPrices:
    """Tests for MarketService.get_prices with freshness."""

    @pytest.fixture
    def mock_aodp_response(self):
        """Sample AODP API response with real data and empty entries."""
        return [
            {
                "item_id": "T4_BAG",
                "city": "Caerleon",
                "quality": 1,
                "sell_price_min": 2500,
                "sell_price_min_date": "2026-02-02T11:55:00",
                "sell_price_max": 3000,
                "sell_price_max_date": "2026-02-02T11:50:00",
                "buy_price_min": 2000,
                "buy_price_min_date": "2026-02-02T11:54:00",
                "buy_price_max": 2300,
                "buy_price_max_date": "2026-02-02T11:56:00",
            },
            # Empty entry (quality 2 with no data) — should be filtered out
            {
                "item_id": "T4_BAG",
                "city": "Caerleon",
                "quality": 2,
                "sell_price_min": 0,
                "sell_price_min_date": "0001-01-01T00:00:00",
                "sell_price_max": 0,
                "sell_price_max_date": "0001-01-01T00:00:00",
                "buy_price_min": 0,
                "buy_price_min_date": "0001-01-01T00:00:00",
                "buy_price_max": 0,
                "buy_price_max_date": "0001-01-01T00:00:00",
            },
        ]

    @pytest.mark.asyncio
    async def test_get_prices_filters_empty_entries(self, mock_aodp_response):
        """Empty (all-zero) entries are stripped from the data array."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value
                    mock_cache_instance.get.return_value = None

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    mock_client = AsyncMock()
                    mock_client.get_prices.return_value = mock_aodp_response
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_prices(
                        item="T4 Bag",
                        cities=["Caerleon"],
                    )

                    # Only the quality-1 entry should remain
                    assert len(result["data"]) == 1
                    assert result["data"][0]["quality"] == 1
                    assert result["data"][0]["sell_price_min"] == 2500

    @pytest.mark.asyncio
    async def test_get_prices_cleans_sentinel_dates(self, mock_aodp_response):
        """Sentinel dates (0001-01-01) are replaced with None."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value
                    mock_cache_instance.get.return_value = None

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    # Entry with some sentinel dates (sell has data, buy doesn't)
                    mock_client = AsyncMock()
                    mock_client.get_prices.return_value = [
                        {
                            "item_id": "T4_BAG",
                            "city": "Caerleon",
                            "quality": 1,
                            "sell_price_min": 2500,
                            "sell_price_min_date": "2026-02-02T11:55:00",
                            "sell_price_max": 3000,
                            "sell_price_max_date": "2026-02-02T11:50:00",
                            "buy_price_min": 0,
                            "buy_price_min_date": "0001-01-01T00:00:00",
                            "buy_price_max": 0,
                            "buy_price_max_date": "0001-01-01T00:00:00",
                        },
                    ]
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_prices(item="T4 Bag", cities=["Caerleon"])

                    entry = result["data"][0]
                    assert entry["sell_price_min_date"] == "2026-02-02T11:55:00"
                    assert entry["buy_price_min_date"] is None
                    assert entry["buy_price_max_date"] is None

    @pytest.mark.asyncio
    async def test_get_prices_includes_freshness(self, mock_aodp_response):
        """Test that get_prices includes freshness info in response."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value
                    mock_cache_instance.get.return_value = None

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    mock_client = AsyncMock()
                    mock_client.get_prices.return_value = mock_aodp_response
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_prices(
                        item="T4 Bag",
                        cities=["Caerleon"],
                    )

                    assert "freshness" in result
                    assert "max_age_minutes" in result["freshness"]
                    assert result["region"] == "europe"

    @pytest.mark.asyncio
    async def test_get_prices_no_per_item_without_quantity(self, mock_aodp_response):
        """Per-item fields are omitted when item_count is not provided."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value
                    mock_cache_instance.get.return_value = None

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    # No item_count in response (typical for prices endpoint)
                    mock_client = AsyncMock()
                    mock_client.get_prices.return_value = [mock_aodp_response[0]]
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_prices(item="T4 Bag", cities=["Caerleon"])

                    entry = result["data"][0]
                    # item_count not in the API response, so per-item fields are omitted
                    assert "item_count" not in entry
                    assert "sell_price_min_per_item" not in entry

    @pytest.mark.asyncio
    async def test_get_prices_with_stack_quantity(self):
        """Per-item fields are included when item_count > 1."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value
                    mock_cache_instance.get.return_value = None

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    mock_client = AsyncMock()
                    mock_client.get_prices.return_value = [
                        {
                            "item_id": "T4_BAG",
                            "city": "Caerleon",
                            "quality": 1,
                            "item_count": 5,
                            "sell_price_min": 2500,
                            "sell_price_min_date": "2026-02-02T11:55:00",
                            "sell_price_max": 3000,
                            "sell_price_max_date": "2026-02-02T11:50:00",
                            "buy_price_min": 2000,
                            "buy_price_min_date": "2026-02-02T11:54:00",
                            "buy_price_max": 2300,
                            "buy_price_max_date": "2026-02-02T11:56:00",
                        },
                    ]
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_prices(item="T4 Bag", cities=["Caerleon"])

                    entry = result["data"][0]
                    assert entry["item_count"] == 5
                    assert entry["sell_price_min_per_item"] == 500.0


class TestMarketServiceGetHistory:
    """Tests for MarketService.get_history."""

    @pytest.fixture
    def mock_history_response_nested(self):
        """Sample AODP history API response (real nested format)."""
        return [
            {
                "location": "Caerleon",
                "item_id": "T4_BAG",
                "quality": 1,
                "data": [
                    {
                        "item_count": 50,
                        "avg_price": 2400,
                        "timestamp": "2026-02-02T10:00:00",
                    },
                    {
                        "item_count": 35,
                        "avg_price": 2500,
                        "timestamp": "2026-02-02T11:00:00",
                    },
                ],
            },
        ]

    @pytest.fixture
    def mock_history_response_flat(self):
        """Sample history response in flat format (backward compat)."""
        return [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-02-02T10:00:00",
                "item_count": 50,
                "avg_price": 2400,
            },
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-02-02T11:00:00",
                "item_count": 35,
                "avg_price": 2500,
            },
        ]

    @pytest.mark.asyncio
    async def test_get_history_nested_format(self, mock_history_response_nested):
        """History flattens the nested AODP format correctly."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    mock_client = AsyncMock()
                    mock_client.get_history.return_value = mock_history_response_nested
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_history(
                        item="T4 Bag",
                        cities=["Caerleon"],
                        time_scale="hourly",
                    )

                    assert result["item"]["id"] == "T4_BAG"
                    assert result["time_scale"] == "hourly"
                    assert len(result["data"]) == 2
                    assert result["data"][0]["avg_price"] == 2400
                    assert result["data"][0]["location"] == "Caerleon"
                    assert result["data"][0]["timestamp"] == "2026-02-02T10:00:00"
                    assert result["data"][1]["avg_price"] == 2500

    @pytest.mark.asyncio
    async def test_get_history_flat_format(self, mock_history_response_flat):
        """History also handles the flat format for backward compatibility."""
        with patch("app.data.market_service.TTLCache") as mock_cache:
            with patch("app.data.market_service.ItemResolver") as mock_resolver:
                with patch("app.data.market_service.AODPClient") as mock_client_cls:
                    mock_cache_instance = mock_cache.return_value

                    mock_resolver_instance = mock_resolver.from_env.return_value
                    mock_resolver_instance.resolve.return_value = type(
                        "Resolution", (), {"item_id": "T4_BAG", "strategy": "catalog", "display_name": "T4 Bag"}
                    )()

                    mock_client = AsyncMock()
                    mock_client.get_history.return_value = mock_history_response_flat
                    mock_client_cls.return_value.__aenter__.return_value = mock_client

                    service = MarketService(
                        cache=mock_cache_instance,
                        resolver=mock_resolver_instance,
                        base_url="https://europe.albion-online-data.com",
                        timeout_s=15,
                        freshness_ttl_s=900,
                    )

                    result = await service.get_history(
                        item="T4 Bag",
                        cities=["Caerleon"],
                        time_scale="hourly",
                    )

                    assert len(result["data"]) == 2
                    assert result["data"][0]["avg_price"] == 2400
