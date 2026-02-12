"""Tests for the history database service."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.data.history_db import HistoryDatabase, DatabaseStatus, MonthCoverage


class TestHistoryDatabase:
    """Tests for HistoryDatabase class."""

    @pytest.fixture
    def db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_market.duckdb"
            db = HistoryDatabase(db_path)
            yield db
            db.close()

    def test_connect_creates_schema(self, db):
        """Test that connecting creates the database schema."""
        conn = db.connect()
        assert conn is not None

        # Check that tables exist (DuckDB uses information_schema)
        result = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {row[0] for row in result}
        assert "market_history" in table_names
        assert "import_metadata" in table_names

    def test_get_status_empty_db(self, db):
        """Test get_status on empty database."""
        status = db.get_status()

        assert isinstance(status, DatabaseStatus)
        assert status.initialized is True
        assert status.total_records == 0
        assert status.earliest_date is None
        assert status.latest_date is None
        assert status.imported_dumps == []
        assert status.coverage_months == []

    def test_insert_records(self, db):
        """Test inserting records into the database."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
                "sell_price_max": 3000,
                "buy_price_min": 2000,
                "buy_price_max": 2300,
                "item_count": 50,
            },
            {
                "item_id": "T4_BAG",
                "location": "Bridgewatch",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2600,
                "sell_price_max": 3100,
                "buy_price_min": 2100,
                "buy_price_max": 2400,
                "item_count": 30,
            },
        ]

        count = db.insert_records(records)
        assert count == 2

        status = db.get_status()
        assert status.total_records == 2

    def test_query_history(self, db):
        """Test querying historical data."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
            },
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-16T10:00:00",
                "sell_price_min": 2600,
            },
            {
                "item_id": "T5_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 5000,
            },
        ]
        db.insert_records(records)

        # Query for T4_BAG only
        results = db.query_history(item_id="T4_BAG")
        assert len(results) == 2
        assert all(r["item_id"] == "T4_BAG" for r in results)

    def test_query_history_with_filters(self, db):
        """Test querying with location and date filters."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
            },
            {
                "item_id": "T4_BAG",
                "location": "Bridgewatch",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2600,
            },
        ]
        db.insert_records(records)

        results = db.query_history(item_id="T4_BAG", locations=["Caerleon"])
        assert len(results) == 1
        assert results[0]["location"] == "Caerleon"

    def test_get_aggregated_history(self, db):
        """Test aggregated history queries."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500 * 50,
                "item_count": 50,
            },
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T14:00:00",
                "sell_price_min": 2600 * 30,
                "item_count": 30,
            },
        ]
        db.insert_records(records)

        results = db.get_aggregated_history(item_id="T4_BAG", granularity="daily")
        assert len(results) == 1  # Aggregated to single day
        assert results[0]["avg_sell_min"] == 2550  # Average of 2500 and 2600
        assert results[0]["total_volume"] == 80  # Sum of 50 and 30

    def test_record_import(self, db):
        """Test recording import metadata."""
        db.record_import(
            dump_name="db_backup_2026-01-15.tgz",
            dump_type="daily",
            record_count=1000,
            date_range_start="2026-01-01",
            date_range_end="2026-01-31",
        )

        assert db.is_dump_imported("db_backup_2026-01-15.tgz")
        assert not db.is_dump_imported("db_backup_2026-01-16.tgz")

        imported = db.get_imported_dumps()
        assert "db_backup_2026-01-15.tgz" in imported

    def test_get_coverage_with_data(self, db):
        """Test coverage info with data."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
            },
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-02-15T10:00:00",
                "sell_price_min": 2600,
            },
        ]
        db.insert_records(records)

        status = db.get_status()
        assert len(status.coverage_months) == 2

        months = {(m.year, m.month) for m in status.coverage_months}
        assert (2026, 1) in months
        assert (2026, 2) in months

    def test_get_latest_timestamp(self, db):
        """Test retrieving latest timestamp."""
        records = [
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
            },
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-16T11:00:00",
                "sell_price_min": 2600,
            },
        ]
        db.insert_records(records)

        latest = db.get_latest_timestamp()
        assert latest is not None
        assert latest.startswith("2026-01-16 11:00:00")

    def test_hard_reset(self, db):
        """Test hard reset clears market data and import metadata."""
        db.insert_records([
            {
                "item_id": "T4_BAG",
                "location": "Caerleon",
                "quality": 1,
                "timestamp": "2026-01-15T10:00:00",
                "sell_price_min": 2500,
            },
        ])
        db.record_import(
            dump_name="db_backup_2026-01-15.tgz",
            dump_type="daily",
            record_count=1,
            date_range_start="2026-01-15",
            date_range_end="2026-01-15",
        )

        result = db.hard_reset()

        assert result["removed_records"] == 1
        assert result["removed_imports"] == 1

        status = db.get_status()
        assert status.total_records == 0
        assert status.imported_dumps == []


class TestMonthCoverage:
    """Tests for MonthCoverage dataclass."""

    def test_to_dict(self):
        coverage = MonthCoverage(year=2026, month=1, record_count=1000, has_data=True)
        result = coverage.to_dict()

        assert result["year"] == 2026
        assert result["month"] == 1
        assert result["record_count"] == 1000
        assert result["has_data"] is True


class TestDatabaseStatus:
    """Tests for DatabaseStatus dataclass."""

    def test_to_dict(self):
        coverage = MonthCoverage(year=2026, month=1, record_count=1000, has_data=True)
        status = DatabaseStatus(
            initialized=True,
            total_records=1000,
            earliest_date="2026-01-01",
            latest_date="2026-01-31",
            imported_dumps=["dump1.sql.gz"],
            coverage_months=[coverage],
        )
        result = status.to_dict()

        assert result["initialized"] is True
        assert result["total_records"] == 1000
        assert result["earliest_date"] == "2026-01-01"
        assert result["latest_date"] == "2026-01-31"
        assert result["imported_dumps"] == ["dump1.sql.gz"]
        assert len(result["coverage"]["months"]) == 1
