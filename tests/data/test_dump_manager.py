"""Tests for the dump manager."""

import io
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.dump_manager import DumpInfo, DumpManager, UpdateResult


class TestDumpInfo:
    """Tests for DumpInfo dataclass."""

    def test_to_dict(self):
        dump = DumpInfo(
            name="db_backup_2026-01-15.tgz",
            url="http://example.com/db_backup_2026-01-15.tgz",
            size_bytes=1048576,
            modified_date=datetime(2026, 1, 15, 10, 0, 0),
            dump_type="daily",
        )
        result = dump.to_dict()

        assert result["name"] == "db_backup_2026-01-15.tgz"
        assert result["size_mb"] == 1.0
        assert result["dump_type"] == "daily"


class TestUpdateResult:
    """Tests for UpdateResult dataclass."""

    def test_to_dict(self):
        result = UpdateResult(
            success=True,
            downloaded=["db_backup_2026-01-15.tgz"],
            imported=["db_backup_2026-01-15.tgz"],
            errors=[],
            total_records=1000,
        )
        data = result.to_dict()

        assert data["success"] is True
        assert data["downloaded"] == ["db_backup_2026-01-15.tgz"]
        assert data["imported"] == ["db_backup_2026-01-15.tgz"]
        assert data["errors"] == []
        assert data["total_records"] == 1000


class TestDumpManager:
    """Tests for DumpManager class."""

    def test_get_update_progress_defaults_to_idle(self):
        manager = DumpManager()
        progress = manager.get_update_progress()

        assert progress["status"] == "idle"
        assert progress["stage"] == "idle"
        assert progress["progress_pct"] == 0.0

    def test_start_background_update_reports_running_update(self):
        manager = DumpManager(db=MagicMock())
        manager._update_lock.acquire()

        try:
            result = manager.start_background_update(max_dumps=1)
        finally:
            manager._update_lock.release()

        assert result["started"] is False
        assert "progress" in result

    def test_clear_update_progress_resets_completed_state(self):
        manager = DumpManager()
        manager._start_progress("run-1", max_dumps=1)
        manager._finalize_progress(run_id="run-1", status="completed", message="done")

        cleared = manager.clear_update_progress()

        assert cleared["status"] == "idle"
        assert cleared["stage"] == "idle"
        assert cleared["run_id"] is None

    def test_clear_update_progress_raises_while_running(self):
        manager = DumpManager()
        manager._start_progress("run-2", max_dumps=1)

        with pytest.raises(RuntimeError):
            manager.clear_update_progress()

    def test_classify_dump_daily(self):
        manager = DumpManager()
        assert manager._classify_dump("db_backup_2026-01-15.tgz") == "daily"

    def test_classify_dump_non_daily_returns_none(self):
        manager = DumpManager()
        assert manager._classify_dump("market_history_2026_01.sql.gz") is None
        assert manager._classify_dump("monthly_db_backup_2026-01.tgz") is None
        assert manager._classify_dump("random_file.txt") is None

    def test_get_missing_dumps(self):
        mock_db = MagicMock()
        mock_db.get_imported_dumps.return_value = ["db_backup_2026-01-14.tgz"]
        manager = DumpManager(db=mock_db)

        available = [
            DumpInfo(
                name="db_backup_2026-01-14.tgz",
                url="http://example.com/db_backup_2026-01-14.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 1, 14, 1, 0, 0),
                dump_type="daily",
            ),
            DumpInfo(
                name="db_backup_2026-01-15.tgz",
                url="http://example.com/db_backup_2026-01-15.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 1, 15, 1, 0, 0),
                dump_type="daily",
            ),
        ]

        missing = manager.get_missing_dumps(available, max_dumps=1)
        assert len(missing) == 1
        assert missing[0].name == "db_backup_2026-01-15.tgz"

    def test_get_recommended_dumps_prefers_newest_daily_snapshot(self):
        mock_db = MagicMock()
        mock_db.get_imported_dumps.return_value = []
        manager = DumpManager(db=mock_db)

        available = [
            DumpInfo(
                name="db_backup_2026-02-03T01_02_30.tgz",
                url="http://example.com/db_backup_2026-02-03T01_02_30.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 3, 1, 2, 30),
                dump_type="daily",
            ),
            DumpInfo(
                name="db_backup_2026-02-05T01_02_24.tgz",
                url="http://example.com/db_backup_2026-02-05T01_02_24.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 5, 1, 2, 24),
                dump_type="daily",
            ),
        ]

        recommended = manager.get_recommended_dumps(available)
        assert len(recommended) == 1
        assert recommended[0].name == "db_backup_2026-02-05T01_02_24.tgz"

    def test_get_missing_dumps_default_uses_recommended_strategy(self):
        mock_db = MagicMock()
        mock_db.get_imported_dumps.return_value = []
        manager = DumpManager(db=mock_db)

        available = [
            DumpInfo(
                name="db_backup_2026-02-05T01_02_24.tgz",
                url="http://example.com/db_backup_2026-02-05T01_02_24.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 5, 1, 2, 24),
                dump_type="daily",
            ),
        ]

        missing = manager.get_missing_dumps(available)
        assert len(missing) == 1
        assert missing[0].dump_type == "daily"

    def test_get_recommended_dumps_skips_older_daily_when_current_is_newer(self):
        manager = DumpManager(db=MagicMock())
        manager._get_current_max_timestamp = lambda: "2026-02-05 12:00:00"

        available = [
            DumpInfo(
                name="db_backup_2026-02-04T01_02_30.tgz",
                url="http://example.com/db_backup_2026-02-04T01_02_30.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 4, 1, 2, 30),
                dump_type="daily",
            ),
        ]

        recommended = manager.get_recommended_dumps(available)
        assert recommended == []

    def test_get_recommended_dumps_picks_newer_daily_when_coverage_is_behind(self):
        manager = DumpManager(db=MagicMock())
        manager._get_current_max_timestamp = lambda: "2026-02-04 01:02:30"

        available = [
            DumpInfo(
                name="db_backup_2026-02-03T01_02_30.tgz",
                url="http://example.com/db_backup_2026-02-03T01_02_30.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 3, 1, 2, 30),
                dump_type="daily",
            ),
            DumpInfo(
                name="db_backup_2026-02-05T01_02_24.tgz",
                url="http://example.com/db_backup_2026-02-05T01_02_24.tgz",
                size_bytes=5000000,
                modified_date=datetime(2026, 2, 5, 1, 2, 24),
                dump_type="daily",
            ),
        ]

        recommended = manager.get_recommended_dumps(available)
        assert len(recommended) == 1
        assert recommended[0].name == "db_backup_2026-02-05T01_02_24.tgz"

    def test_is_dump_fully_covered_compares_full_daily_timestamp(self):
        manager = DumpManager(db=MagicMock())
        dump = DumpInfo(
            name="db_backup_2026-02-05T12_00_00.tgz",
            url="http://example.com/db_backup_2026-02-05T12_00_00.tgz",
            size_bytes=5000000,
            modified_date=datetime(2026, 2, 5, 12, 0, 0),
            dump_type="daily",
        )

        assert manager._is_dump_fully_covered(dump, "2026-02-05 11:59:59") is False
        assert manager._is_dump_fully_covered(dump, "2026-02-05 12:00:00") is True

    def test_split_sql_values(self):
        manager = DumpManager()
        values = manager._split_sql_values("'item_id', 'location', 1, 2500")
        assert len(values) == 4
        assert values[0] == "'item_id'"
        assert values[1] == "'location'"
        assert values[2] == "1"
        assert values[3] == "2500"

    def test_split_sql_values_with_comma_in_string(self):
        manager = DumpManager()
        values = manager._split_sql_values("'item,with,commas', 'normal', 1")
        assert len(values) == 3
        assert values[0] == "'item,with,commas'"

    def test_clean_sql_string(self):
        manager = DumpManager()
        assert manager._clean_sql_string("'value'") == "value"
        assert manager._clean_sql_string('"value"') == "value"
        assert manager._clean_sql_string("value") == "value"
        assert manager._clean_sql_string("'it''s'") == "it's"

    def test_parse_int(self):
        manager = DumpManager()
        assert manager._parse_int("123") == 123
        assert manager._parse_int("NULL") is None
        assert manager._parse_int("null") is None
        assert manager._parse_int("  456  ") == 456
        assert manager._parse_int("invalid") is None

    def test_parse_value_tuples(self):
        manager = DumpManager()
        line = "(527231763,2,33959,'T4_BAG',1002,2,'2026-01-15 10:00:00.000000',6),"
        records = manager._parse_value_tuples(line)

        assert len(records) == 1
        record = records[0]
        assert record["item_id"] == "T4_BAG"
        assert record["location"] == "Caerleon"
        assert record["quality"] == 2
        assert record["timestamp"] == "2026-01-15 10:00:00.000000"
        assert record["sell_price_min"] == 33959
        assert record["item_count"] == 2

    def test_parse_value_tuples_multiple(self):
        manager = DumpManager()
        line = "(527231763,2,33959,'T4_BAG',1002,2,'2026-01-15',6),(527231764,5,50000,'T5_BAG',2004,1,'2026-01-15',6);"
        records = manager._parse_value_tuples(line)

        assert len(records) == 2
        assert records[0]["item_id"] == "T4_BAG"
        assert records[0]["location"] == "Caerleon"
        assert records[1]["item_id"] == "T5_BAG"
        assert records[1]["location"] == "Bridgewatch"

    def test_import_copy_stream(self):
        manager = DumpManager(db=MagicMock())
        manager.db.insert_records.side_effect = lambda records, batch_size=10000: len(records)

        sql = (
            "COPY public.market_history (id, item_count, silver_amount, item_unique_name, "
            "location, quality_level, \"timestamp\", auction_type) FROM stdin;\n"
            "1\t2\t33959\tT4_BAG\t1002\t2\t2026-01-15 10:00:00\t6\n"
            "2\t5\t50000\tT5_BAG\t2004\t1\t2026-01-16 11:00:00\t6\n"
            "\\.\n"
        )

        count, date_start, date_end = manager._import_from_sql_stream(
            io.StringIO(sql),
            source_label="test.sql",
            batch_size=10,
        )

        assert count == 2
        assert date_start == "2026-01-15"
        assert date_end == "2026-01-16"


class TestDumpManagerAsync:
    """Async tests for DumpManager."""

    @pytest.mark.asyncio
    async def test_list_available_dumps_daily_only(self):
        mock_html = """
        <html>
        <body>
        <a href="market_history_2026_01.sql.gz">market_history_2026_01.sql.gz</a> 30-Jan-2026 01:02 569216651
        <a href="monthly_db_backup_2026-01.tgz">monthly_db_backup_2026-01.tgz</a> 31-Jan-2026 00:00 623456789
        <a href="db_backup_2026-01-15.tgz">db_backup_2026-01-15.tgz</a> 15-Jan-2026 00:00 123456789
        </body>
        </html>
        """

        with patch("app.data.dump_manager.httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.text = mock_html
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_response
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None
            mock_client.return_value = mock_client_instance

            manager = DumpManager()
            dumps = await manager.list_available_dumps()

            assert len(dumps) == 1
            assert dumps[0].name == "db_backup_2026-01-15.tgz"
            assert dumps[0].dump_type == "daily"
