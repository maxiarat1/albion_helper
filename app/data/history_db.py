"""DuckDB service for historical market data.

Stores consolidated market history from AODP database dumps,
enabling efficient trend analysis over weeks/months.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import csv
import tempfile

import duckdb

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(os.getenv("MARKET_HISTORY_DB", "data/history/market.duckdb"))

# Schema definitions
SCHEMA_SQL = """
-- Main market history table
CREATE TABLE IF NOT EXISTS market_history (
    item_id VARCHAR NOT NULL,
    location VARCHAR NOT NULL,
    quality INTEGER DEFAULT 1,
    timestamp TIMESTAMP NOT NULL,
    sell_price_min INTEGER,
    sell_price_max INTEGER,
    buy_price_min INTEGER,
    buy_price_max INTEGER,
    item_count INTEGER,
    PRIMARY KEY (item_id, location, quality, timestamp)
);

-- Index for item+location queries
CREATE INDEX IF NOT EXISTS idx_item_location ON market_history(item_id, location);

-- Index for time-range queries
CREATE INDEX IF NOT EXISTS idx_timestamp ON market_history(timestamp);

-- Gold price history (silver per gold)
CREATE TABLE IF NOT EXISTS gold_prices (
    timestamp TIMESTAMP PRIMARY KEY,
    price INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gold_timestamp ON gold_prices(timestamp);

-- Metadata table for tracking imported dumps
CREATE TABLE IF NOT EXISTS import_metadata (
    dump_name VARCHAR PRIMARY KEY,
    dump_type VARCHAR,
    import_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    record_count INTEGER,
    date_range_start DATE,
    date_range_end DATE
);
"""


@dataclass
class MonthCoverage:
    """Data coverage for a single month."""
    year: int
    month: int
    record_count: int
    has_data: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "record_count": self.record_count,
            "has_data": self.has_data,
        }


@dataclass
class DatabaseStatus:
    """Overall database status."""
    initialized: bool
    total_records: int
    earliest_date: str | None
    latest_date: str | None
    imported_dumps: list[str]
    coverage_months: list[MonthCoverage]

    def to_dict(self) -> dict[str, Any]:
        return {
            "initialized": self.initialized,
            "total_records": self.total_records,
            "earliest_date": self.earliest_date,
            "latest_date": self.latest_date,
            "imported_dumps": self.imported_dumps,
            "coverage": {
                "months": [m.to_dict() for m in self.coverage_months],
            },
        }


class HistoryDatabase:
    """DuckDB service for historical market data."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._conn: duckdb.DuckDBPyConnection | None = None

    @staticmethod
    def _is_closed_connection_error(exc: Exception) -> bool:
        text = str(exc).lower()
        return "connection already closed" in text or ("connection error" in text and "closed" in text)

    def _open_connection(self) -> duckdb.DuckDBPyConnection:
        """Open a fresh connection and ensure schema is available."""
        self._ensure_dir()
        self._conn = duckdb.connect(str(self.db_path))
        self._init_schema()
        logger.info("[HistoryDB] Connected to %s", self.db_path)
        return self._conn

    def _ensure_dir(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection."""
        if self._conn is None:
            return self._open_connection()
        try:
            self._conn.execute("SELECT 1")
        except Exception as exc:
            if not self._is_closed_connection_error(exc):
                raise
            logger.warning("[HistoryDB] Reopening closed connection to %s", self.db_path)
            self._conn = None
            return self._open_connection()
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:
                logger.warning("[HistoryDB] Ignoring close error: %s", exc)
            finally:
                self._conn = None

    def _init_schema(self) -> None:
        """Initialize database schema."""
        if self._conn:
            self._conn.execute(SCHEMA_SQL)
            logger.info("[HistoryDB] Schema initialized")

    def get_status(self) -> DatabaseStatus:
        """Get overall database status and coverage info."""
        conn = self.connect()

        # Check if we have any data
        try:
            total = conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0]
        except Exception:
            total = 0

        if total == 0:
            return DatabaseStatus(
                initialized=True,
                total_records=0,
                earliest_date=None,
                latest_date=None,
                imported_dumps=[],
                coverage_months=[],
            )

        # Get date range
        result = conn.execute("""
            SELECT
                MIN(timestamp)::DATE::VARCHAR as earliest,
                MAX(timestamp)::DATE::VARCHAR as latest
            FROM market_history
        """).fetchone()
        earliest_date = result[0] if result else None
        latest_date = result[1] if result else None

        # Get imported dumps
        try:
            dumps = conn.execute(
                "SELECT dump_name FROM import_metadata ORDER BY import_date DESC"
            ).fetchall()
            imported_dumps = [d[0] for d in dumps]
        except Exception:
            imported_dumps = []

        # Get monthly coverage
        coverage_result = conn.execute("""
            SELECT
                EXTRACT(YEAR FROM timestamp)::INTEGER as year,
                EXTRACT(MONTH FROM timestamp)::INTEGER as month,
                COUNT(*) as record_count
            FROM market_history
            GROUP BY year, month
            ORDER BY year, month
        """).fetchall()

        coverage_months = [
            MonthCoverage(year=row[0], month=row[1], record_count=row[2], has_data=True)
            for row in coverage_result
        ]

        return DatabaseStatus(
            initialized=True,
            total_records=total,
            earliest_date=earliest_date,
            latest_date=latest_date,
            imported_dumps=imported_dumps,
            coverage_months=coverage_months,
        )

    def get_coverage(self) -> dict[str, Any]:
        """Get data coverage summary."""
        status = self.get_status()
        return status.to_dict()["coverage"]

    def get_latest_timestamp(self) -> str | None:
        """Get the latest timestamp in the market history table."""
        conn = self.connect()
        try:
            result = conn.execute(
                "SELECT MAX(timestamp)::VARCHAR FROM market_history"
            ).fetchone()
            if not result:
                return None
            return result[0]
        except Exception:
            return None

    def hard_reset(self) -> dict[str, int]:
        """Remove all historical data and import metadata."""
        conn = self.connect()

        try:
            record_count = conn.execute(
                "SELECT COUNT(*) FROM market_history"
            ).fetchone()[0]
        except Exception:
            record_count = 0

        try:
            import_count = conn.execute(
                "SELECT COUNT(*) FROM import_metadata"
            ).fetchone()[0]
        except Exception:
            import_count = 0

        conn.execute("DELETE FROM market_history")
        conn.execute("DELETE FROM import_metadata")

        try:
            conn.execute("CHECKPOINT")
        except Exception:
            pass

        logger.info(
            f"[HistoryDB] Hard reset complete (removed_records={record_count}, "
            f"removed_imports={import_count})"
        )
        return {
            "removed_records": int(record_count),
            "removed_imports": int(import_count),
        }

    def query_history(
        self,
        item_id: str,
        locations: list[str] | None = None,
        quality: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query historical prices for an item.

        Args:
            item_id: Item unique name
            locations: Optional list of locations to filter
            quality: Optional quality level
            start_date: Optional start date (YYYY-MM-DD)
            end_date: Optional end date (YYYY-MM-DD)
            limit: Maximum rows to return

        Returns:
            List of price records
        """
        conn = self.connect()

        # Normalize prices to per-item values for display
        def per_item_expr(column: str) -> str:
            return (
                "CASE "
                f"WHEN {column} IS NULL THEN NULL "
                f"ELSE {column}::DOUBLE / COALESCE(NULLIF(item_count, 0), 1) "
                "END"
            )

        sell_min_expr = per_item_expr("sell_price_min")
        sell_max_expr = per_item_expr("sell_price_max")
        buy_min_expr = per_item_expr("buy_price_min")
        buy_max_expr = per_item_expr("buy_price_max")

        # Build query
        conditions = ["item_id = ?"]
        params: list[Any] = [item_id]

        if locations:
            placeholders = ", ".join(["?" for _ in locations])
            conditions.append(f"location IN ({placeholders})")
            params.extend(locations)

        if quality is not None:
            conditions.append("quality = ?")
            params.append(quality)

        if start_date:
            conditions.append("timestamp >= ?::TIMESTAMP")
            params.append(start_date)

        if end_date:
            conditions.append("timestamp <= ?::TIMESTAMP")
            params.append(end_date)

        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT
                item_id,
                location,
                quality,
                timestamp::VARCHAR as timestamp,
                CAST(ROUND({sell_min_expr}) AS INTEGER) as sell_price_min,
                CAST(ROUND({sell_max_expr}) AS INTEGER) as sell_price_max,
                CAST(ROUND({buy_min_expr}) AS INTEGER) as buy_price_min,
                CAST(ROUND({buy_max_expr}) AS INTEGER) as buy_price_max,
                item_count
            FROM market_history
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """

        result = conn.execute(query, params).fetchall()
        columns = [
            "item_id", "location", "quality", "timestamp",
            "sell_price_min", "sell_price_max", "buy_price_min", "buy_price_max",
            "item_count"
        ]

        return [dict(zip(columns, row)) for row in result]

    def get_aggregated_history(
        self,
        item_id: str,
        locations: list[str] | None = None,
        quality: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        granularity: str = "daily",
    ) -> list[dict[str, Any]]:
        """Get aggregated price history (daily/weekly/monthly averages).

        Args:
            item_id: Item unique name
            locations: Optional list of locations to filter
            quality: Optional quality level
            start_date: Optional start date
            end_date: Optional end date
            granularity: "hourly", "daily", "weekly", or "monthly"

        Returns:
            List of aggregated price records
        """
        conn = self.connect()

        # Normalize prices to per-item values for aggregation
        def per_item_expr(column: str) -> str:
            return (
                "CASE "
                f"WHEN {column} IS NULL THEN NULL "
                f"ELSE {column}::DOUBLE / COALESCE(NULLIF(item_count, 0), 1) "
                "END"
            )

        sell_min_expr = per_item_expr("sell_price_min")
        sell_max_expr = per_item_expr("sell_price_max")
        buy_min_expr = per_item_expr("buy_price_min")
        buy_max_expr = per_item_expr("buy_price_max")

        # Determine date truncation
        trunc_map = {
            "hourly": "hour",
            "daily": "day",
            "weekly": "week",
            "monthly": "month",
        }
        trunc = trunc_map.get(granularity, "day")

        # Build conditions
        conditions = ["item_id = ?"]
        params: list[Any] = [item_id]

        if locations:
            placeholders = ", ".join(["?" for _ in locations])
            conditions.append(f"location IN ({placeholders})")
            params.extend(locations)

        if quality is not None:
            conditions.append("quality = ?")
            params.append(quality)

        if start_date:
            conditions.append("timestamp >= ?::TIMESTAMP")
            params.append(start_date)

        if end_date:
            conditions.append("timestamp <= ?::TIMESTAMP")
            params.append(end_date)

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                DATE_TRUNC('{trunc}', timestamp)::VARCHAR as period,
                location,
                quality,
                CAST(ROUND(AVG({sell_min_expr})) AS INTEGER) as avg_sell_min,
                CAST(ROUND(AVG({sell_max_expr})) AS INTEGER) as avg_sell_max,
                CAST(ROUND(AVG({buy_min_expr})) AS INTEGER) as avg_buy_min,
                CAST(ROUND(AVG({buy_max_expr})) AS INTEGER) as avg_buy_max,
                SUM(item_count) as total_volume,
                COUNT(*) as data_points
            FROM market_history
            WHERE {where_clause}
            GROUP BY period, location, quality
            ORDER BY period DESC, location, quality
            LIMIT 1000
        """

        result = conn.execute(query, params).fetchall()
        columns = [
            "period", "location", "quality", "avg_sell_min", "avg_sell_max",
            "avg_buy_min", "avg_buy_max", "total_volume", "data_points"
        ]

        return [dict(zip(columns, row)) for row in result]

    # --- Gold price methods ---

    def query_gold_prices(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query gold price history.

        Returns list of {timestamp, price} records ordered by timestamp DESC.
        """
        conn = self.connect()

        conditions: list[str] = []
        params: list[Any] = []

        if start_date:
            conditions.append("timestamp >= ?::TIMESTAMP")
            params.append(start_date)
        if end_date:
            conditions.append("timestamp <= ?::TIMESTAMP")
            params.append(end_date)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT timestamp::VARCHAR as timestamp, price
            FROM gold_prices
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """

        result = conn.execute(query, params).fetchall()
        return [{"timestamp": row[0], "price": row[1]} for row in result]

    def get_latest_gold_timestamp(self) -> str | None:
        """Get the latest timestamp in the gold_prices table."""
        conn = self.connect()
        try:
            result = conn.execute(
                "SELECT MAX(timestamp)::VARCHAR FROM gold_prices"
            ).fetchone()
            if not result:
                return None
            return result[0]
        except Exception:
            return None

    def insert_gold_prices(self, records: list[dict[str, Any]]) -> int:
        """Insert gold price records (upsert).

        Args:
            records: List of {timestamp, price} dicts

        Returns:
            Number of records inserted
        """
        if not records:
            return 0

        conn = self.connect()
        values = [(r["timestamp"], r["price"]) for r in records]

        try:
            conn.executemany("""
                INSERT OR REPLACE INTO gold_prices (timestamp, price)
                VALUES (?::TIMESTAMP, ?)
            """, values)
            logger.info("[HistoryDB] Inserted %s gold price records", len(values))
            return len(values)
        except Exception as e:
            logger.error("[HistoryDB] Failed to insert gold prices: %s", e)
            return 0

    def insert_records(
        self,
        records: list[dict[str, Any]],
        batch_size: int = 10000,
    ) -> int:
        """Insert market history records.

        Args:
            records: List of records to insert
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not records:
            return 0

        conn = self.connect()
        inserted = 0

        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]

            # Prepare data for bulk insertion
            values = []
            for record in batch:
                values.append((
                    record.get("item_id"),
                    record.get("location"),
                    record.get("quality", 1),
                    record.get("timestamp"),
                    record.get("sell_price_min"),
                    record.get("sell_price_max"),
                    record.get("buy_price_min"),
                    record.get("buy_price_max"),
                    record.get("item_count"),
                ))

            try:
                # Use executemany for bulk insert - much faster than individual inserts
                conn.executemany("""
                    INSERT OR REPLACE INTO market_history
                    (item_id, location, quality, timestamp,
                     sell_price_min, sell_price_max, buy_price_min, buy_price_max, item_count)
                    VALUES (?, ?, ?, ?::TIMESTAMP, ?, ?, ?, ?, ?)
                """, values)
                
                inserted += len(values)
                logger.info(
                    "[HistoryDB] Inserted batch %s, total: %s",
                    i // batch_size + 1,
                    inserted,
                )
            except Exception as e:
                logger.error("[HistoryDB] Failed to insert batch: %s", e)
                # Fall back to individual inserts for this batch on error
                for record in batch:
                    try:
                        conn.execute("""
                            INSERT OR REPLACE INTO market_history
                            (item_id, location, quality, timestamp,
                             sell_price_min, sell_price_max, buy_price_min, buy_price_max, item_count)
                            VALUES (?, ?, ?, ?::TIMESTAMP, ?, ?, ?, ?, ?)
                        """, [
                            record.get("item_id"),
                            record.get("location"),
                            record.get("quality", 1),
                            record.get("timestamp"),
                            record.get("sell_price_min"),
                            record.get("sell_price_max"),
                            record.get("buy_price_min"),
                            record.get("buy_price_max"),
                            record.get("item_count"),
                        ])
                        inserted += 1
                    except Exception as e2:
                        logger.warning("[HistoryDB] Failed to insert record: %s", e2)

        return inserted

    def record_import(
        self,
        dump_name: str,
        dump_type: str,
        record_count: int,
        date_range_start: str | None = None,
        date_range_end: str | None = None,
    ) -> None:
        """Record metadata about an imported dump."""
        conn = self.connect()
        conn.execute("""
            INSERT OR REPLACE INTO import_metadata
            (dump_name, dump_type, import_date, record_count, date_range_start, date_range_end)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?::DATE, ?::DATE)
        """, [dump_name, dump_type, record_count, date_range_start, date_range_end])
        logger.info("[HistoryDB] Recorded import: %s", dump_name)

    def is_dump_imported(self, dump_name: str) -> bool:
        """Check if a dump has already been imported."""
        conn = self.connect()
        result = conn.execute(
            "SELECT 1 FROM import_metadata WHERE dump_name = ?",
            [dump_name]
        ).fetchone()
        return result is not None

    def get_imported_dumps(self) -> list[str]:
        """Get list of all imported dump names."""
        conn = self.connect()
        result = conn.execute(
            "SELECT dump_name FROM import_metadata ORDER BY import_date"
        ).fetchall()
        return [row[0] for row in result]

    def drop_indexes(self) -> None:
        """Drop indexes for faster bulk loading."""
        conn = self.connect()
        try:
            conn.execute("DROP INDEX IF EXISTS idx_item_location")
            conn.execute("DROP INDEX IF EXISTS idx_timestamp")
            logger.info("[HistoryDB] Indexes dropped for bulk loading")
        except Exception as e:
            logger.warning("[HistoryDB] Failed to drop indexes: %s", e)

    def create_indexes(self) -> None:
        """Recreate indexes after bulk loading."""
        conn = self.connect()
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_item_location ON market_history(item_id, location)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timestamp ON market_history(timestamp)"
        )
        logger.info("[HistoryDB] Indexes recreated")

    def bulk_insert_from_csv(self, csv_path: Path | str) -> int:
        """Bulk insert records from a CSV file using COPY command.

        This is 10-50x faster than executemany for large datasets.

        Args:
            csv_path: Path to CSV file with columns matching market_history table

        Returns:
            Number of records inserted
        """
        conn = self.connect()
        csv_path = Path(csv_path)

        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # Count rows before
        before_count = conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0]

        # Use COPY to bulk load - much faster than INSERT
        # ON CONFLICT UPDATE for upsert behavior
        conn.execute(f"""
            INSERT INTO market_history
            SELECT * FROM read_csv(
                '{csv_path}',
                columns={{
                    'item_id': 'VARCHAR',
                    'location': 'VARCHAR',
                    'quality': 'INTEGER',
                    'timestamp': 'TIMESTAMP',
                    'sell_price_min': 'INTEGER',
                    'sell_price_max': 'INTEGER',
                    'buy_price_min': 'INTEGER',
                    'buy_price_max': 'INTEGER',
                    'item_count': 'INTEGER'
                }},
                header=true,
                ignore_errors=true
            )
            ON CONFLICT (item_id, location, quality, timestamp)
            DO UPDATE SET
                sell_price_min = COALESCE(excluded.sell_price_min, market_history.sell_price_min),
                sell_price_max = COALESCE(excluded.sell_price_max, market_history.sell_price_max),
                buy_price_min = COALESCE(excluded.buy_price_min, market_history.buy_price_min),
                buy_price_max = COALESCE(excluded.buy_price_max, market_history.buy_price_max),
                item_count = COALESCE(excluded.item_count, market_history.item_count)
        """)

        # Count rows after
        after_count = conn.execute("SELECT COUNT(*) FROM market_history").fetchone()[0]
        inserted = after_count - before_count

        logger.info("[HistoryDB] Bulk inserted %s records from CSV", inserted)
        return inserted

    def bulk_insert_from_records(
        self,
        records: list[dict[str, Any]],
        temp_dir: Path | str | None = None,
    ) -> int:
        """Bulk insert records by writing to temp CSV then using COPY.

        This is the fastest way to insert large numbers of records.

        Args:
            records: List of record dictionaries
            temp_dir: Optional temp directory for CSV file

        Returns:
            Number of records inserted
        """
        if not records:
            return 0

        temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Write records to temp CSV
        csv_path = temp_dir / f"bulk_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        columns = [
            "item_id", "location", "quality", "timestamp",
            "sell_price_min", "sell_price_max", "buy_price_min", "buy_price_max",
            "item_count"
        ]

        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(records)

            logger.info("[HistoryDB] Wrote %s records to temp CSV", len(records))

            # Bulk load from CSV
            inserted = self.bulk_insert_from_csv(csv_path)
            return inserted

        finally:
            # Cleanup temp file
            if csv_path.exists():
                csv_path.unlink()


# Default instance
def get_history_db() -> HistoryDatabase:
    """Get the default history database instance."""
    return HistoryDatabase()
