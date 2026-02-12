"""Manager for downloading and importing AODP database dumps.

Handles:
- Listing available dumps from the AODP database index
- Downloading and importing SQL dump files into DuckDB
- Bulk loading optimization via CSV streaming

## Dump Types

This project uses only:

1. **db_backup_YYYY-MM-DD.tgz** (Daily full database snapshots)
   - Contains the ENTIRE database history up to that date
   - ~540MB compressed, ~4GB uncompressed
   - Use for getting the latest complete dataset
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import io
import logging
import os
import re
import tarfile
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import httpx
from bs4 import BeautifulSoup

from .history_db import HistoryDatabase

logger = logging.getLogger(__name__)

# AODP database dump index URL
DUMP_INDEX_URL = os.getenv(
    "AODP_DUMP_INDEX_URL",
    "https://www.albion-online-data.com/database-europe/"
) or "https://www.albion-online-data.com/database-europe/"

# Download directory
DOWNLOAD_DIR = Path(os.getenv("DUMP_DOWNLOAD_DIR", "data/dumps"))

# Location ID to name mapping based on AODP data
LOCATION_MAP = {
    7: "Black Market",
    1002: "Caerleon",
    2004: "Bridgewatch",
    3003: "Lymhurst",
    3005: "Fort Sterling",
    3008: "Martlock",
    3345: "Brecilien",
    4002: "Thetford",
    5003: "Fort Sterling",  # May need verification
}


CSV_COLUMNS = [
    "item_id", "location", "quality", "timestamp",
    "sell_price_min", "sell_price_max", "buy_price_min", "buy_price_max",
    "item_count"
]

DOWNLOAD_PROGRESS_START = 15.0
DOWNLOAD_PROGRESS_END = 45.0
IMPORT_PROGRESS_START = 45.0
IMPORT_PROGRESS_END = 90.0


def _normalize_timestamp_for_compare(timestamp: Any) -> str | None:
    """Normalize timestamp-like values for lexicographic comparison.

    Returns format `YYYY-MM-DD HH:MM:SS` when possible.
    """
    if timestamp is None:
        return None

    text = str(timestamp).strip()
    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if match:
        return match.group(1)

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text} 00:00:00"

    return None


class StreamingCSVWriter:
    """Streaming CSV writer for efficient bulk record export."""

    def __init__(
        self,
        output_path: Path,
        min_timestamp_exclusive: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        progress_interval: int = 100000,
    ):
        self.output_path = output_path
        self._file = None
        self._writer = None
        self.count = 0
        self.skipped_existing = 0
        self.date_start = None
        self.date_end = None
        self.progress_callback = progress_callback
        self.progress_interval = max(1, progress_interval)
        self.min_timestamp_exclusive = _normalize_timestamp_for_compare(
            min_timestamp_exclusive
        )

    def __enter__(self):
        self._file = open(self.output_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=CSV_COLUMNS, extrasaction="ignore"
        )
        self._writer.writeheader()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()
        return False

    def write_record(self, record: dict[str, Any]) -> None:
        """Write a single record to CSV."""
        if not record.get("item_id") or not record.get("timestamp"):
            return

        timestamp = record.get("timestamp")
        normalized = _normalize_timestamp_for_compare(timestamp)

        if (
            self.min_timestamp_exclusive is not None
            and normalized is not None
            and normalized <= self.min_timestamp_exclusive
        ):
            self.skipped_existing += 1
            if self.progress_callback and self.skipped_existing % self.progress_interval == 0:
                self.progress_callback(self.count, self.skipped_existing)
            return

        # Track date range for records we actually write
        date_value = (normalized or str(timestamp))[:10]
        if self.date_start is None or date_value < self.date_start:
            self.date_start = date_value
        if self.date_end is None or date_value > self.date_end:
            self.date_end = date_value

        self._writer.writerow(record)
        self.count += 1

        # Log progress periodically
        if self.count % 500000 == 0:
            logger.info("[StreamingCSV] Written %s records...", format(self.count, ","))
        if self.progress_callback and self.count % self.progress_interval == 0:
            self.progress_callback(self.count, self.skipped_existing)

    def write_records(self, records: Iterable[dict[str, Any]]) -> None:
        """Write multiple records to CSV."""
        for record in records:
            self.write_record(record)


@dataclass
class DumpInfo:
    """Information about an available database dump."""
    name: str
    url: str
    size_bytes: int
    modified_date: datetime
    dump_type: str  # "daily"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "size_mb": round(self.size_bytes / (1024 * 1024), 2),
            "modified_date": self.modified_date.isoformat(),
            "dump_type": self.dump_type,
        }


@dataclass
class UpdateResult:
    """Result of an update operation."""
    success: bool
    downloaded: list[str]
    imported: list[str]
    errors: list[str]
    total_records: int
    cleaned_up: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "success": self.success,
            "downloaded": self.downloaded,
            "imported": self.imported,
            "errors": self.errors,
            "total_records": self.total_records,
        }
        if self.cleaned_up:
            result["cleaned_up"] = self.cleaned_up
        return result


class DumpManager:
    """Manages downloading and importing AODP database dumps."""

    def __init__(
        self,
        db: HistoryDatabase | None = None,
        download_dir: Path | None = None,
        index_url: str | None = None,
    ) -> None:
        self.db = db or HistoryDatabase()
        self.download_dir = download_dir or DOWNLOAD_DIR
        self.index_url = index_url or DUMP_INDEX_URL
        self._update_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._progress: dict[str, Any] = self._empty_progress_state()
        self._background_thread: threading.Thread | None = None

    def _empty_progress_state(self) -> dict[str, Any]:
        return {
            "run_id": None,
            "status": "idle",
            "stage": "idle",
            "message": "No database update in progress",
            "progress_pct": 0.0,
            "started_at": None,
            "updated_at": None,
            "finished_at": None,
            "total_dumps": 0,
            "completed_dumps": 0,
            "current_dump": None,
            "downloaded_bytes": 0,
            "download_total_bytes": 0,
            "records_parsed": 0,
            "records_skipped_existing": 0,
            "records_imported": 0,
            "errors": [],
            "result": None,
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _start_progress(self, run_id: str, *, max_dumps: int) -> None:
        now = self._now_iso()
        with self._progress_lock:
            self._progress = {
                **self._empty_progress_state(),
                "run_id": run_id,
                "status": "running",
                "stage": "starting",
                "message": "Starting database update...",
                "progress_pct": 1.0,
                "started_at": now,
                "updated_at": now,
                "max_dumps": max_dumps,
            }

    def _set_progress(self, *, run_id: str | None = None, **changes: Any) -> None:
        with self._progress_lock:
            if run_id is not None and self._progress.get("run_id") != run_id:
                return

            for key, value in changes.items():
                if value is None:
                    continue
                if key == "progress_pct":
                    self._progress[key] = max(0.0, min(100.0, float(value)))
                elif key == "errors":
                    self._progress[key] = list(value)
                else:
                    self._progress[key] = value

            self._progress["updated_at"] = self._now_iso()

    def _finalize_progress(self, *, run_id: str, status: Literal["completed", "failed"], message: str) -> None:
        now = self._now_iso()
        with self._progress_lock:
            if self._progress.get("run_id") != run_id:
                return
            self._progress["status"] = status
            self._progress["stage"] = status
            self._progress["message"] = message
            self._progress["progress_pct"] = 100.0
            self._progress["updated_at"] = now
            self._progress["finished_at"] = now

    def _progress_snapshot_locked(self) -> dict[str, Any]:
        snapshot = dict(self._progress)
        started_at = snapshot.get("started_at")
        finished_at = snapshot.get("finished_at")
        elapsed_seconds: float | None = None
        eta_seconds: float | None = None

        if started_at:
            try:
                started = datetime.fromisoformat(started_at)
                if finished_at:
                    end = datetime.fromisoformat(finished_at)
                else:
                    end = datetime.now(timezone.utc)
                elapsed_seconds = max(
                    0.0,
                    (end - started).total_seconds(),
                )
            except ValueError:
                elapsed_seconds = None

        progress_pct = float(snapshot.get("progress_pct") or 0.0)
        if snapshot.get("status") == "running" and elapsed_seconds is not None and progress_pct > 0:
            eta_seconds = max(0.0, elapsed_seconds * (100.0 - progress_pct) / progress_pct)

        snapshot["progress_pct"] = round(progress_pct, 2)
        snapshot["elapsed_seconds"] = round(elapsed_seconds, 1) if elapsed_seconds is not None else None
        snapshot["eta_seconds"] = round(eta_seconds, 1) if eta_seconds is not None else None
        return snapshot

    def get_update_progress(self) -> dict[str, Any]:
        with self._progress_lock:
            return self._progress_snapshot_locked()

    def clear_update_progress(self) -> dict[str, Any]:
        with self._progress_lock:
            if self._progress.get("status") == "running":
                raise RuntimeError("Cannot clear update progress while an update is running")
            self._progress = self._empty_progress_state()
            self._progress["updated_at"] = self._now_iso()
            return self._progress_snapshot_locked()

    def start_background_update(
        self,
        *,
        max_dumps: int = 1,
        cleanup_after_import: bool = True,
        parallel_downloads: int = 3,
        use_bulk_loading: bool = True,
    ) -> dict[str, Any]:
        if not self._update_lock.acquire(blocking=False):
            return {"started": False, "progress": self.get_update_progress()}

        run_id = uuid.uuid4().hex
        self._start_progress(run_id, max_dumps=max_dumps)

        def run() -> None:
            try:
                result = asyncio.run(
                    self._run_update_pipeline(
                        run_id=run_id,
                        max_dumps=max_dumps,
                        cleanup_after_import=cleanup_after_import,
                        parallel_downloads=parallel_downloads,
                        use_bulk_loading=use_bulk_loading,
                    )
                )
                self._set_progress(run_id=run_id, result=result.to_dict())
                self._finalize_progress(
                    run_id=run_id,
                    status="completed",
                    message="Database update completed successfully",
                )
            except Exception as exc:
                logger.exception("[DumpManager] Background update failed")
                error_msg = str(exc)
                self._set_progress(run_id=run_id, errors=[error_msg], result={"success": False, "errors": [error_msg]})
                self._finalize_progress(
                    run_id=run_id,
                    status="failed",
                    message=f"Database update failed: {error_msg}",
                )
            finally:
                try:
                    self.db.close()
                except Exception:
                    pass
                self._update_lock.release()

        self._background_thread = threading.Thread(
            target=run,
            name="dump-manager-update",
            daemon=True,
        )
        self._background_thread.start()

        return {
            "started": True,
            "run_id": run_id,
            "progress": self.get_update_progress(),
        }

    async def list_available_dumps(self) -> list[DumpInfo]:
        """Fetch and parse the dump index page for available files."""
        logger.info("[DumpManager] Fetching dump index from %s", self.index_url)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.index_url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        dumps: list[DumpInfo] = []

        # Parse Apache/nginx directory listing
        # Looking for daily .tgz snapshots
        for link in soup.find_all("a"):
            href = link.get("href", "")
            if not href:
                continue

            # Filter for supported dump files
            if not href.endswith(".tgz"):
                continue

            # Skip parent directory link
            if href.startswith("..") or href.startswith("/"):
                continue

            # Determine dump type
            dump_type = self._classify_dump(href)
            if not dump_type:
                continue

            # Build full URL
            url = f"{self.index_url.rstrip('/')}/{href}"

            # Try to extract size and date from page text
            # Apache format: "filename   date time   size"
            size_bytes = 0
            modified_date = datetime.now()

            # Find the row text containing this link
            parent = link.parent
            if parent:
                text = parent.get_text()
                # Try to parse size (e.g., "569216651" or "568M")
                size_match = re.search(r"(\d+)\s*$", text.strip())
                if size_match:
                    size_bytes = int(size_match.group(1))

                # Try to parse date (e.g., "30-Jan-2026 01:02")
                date_match = re.search(
                    r"(\d{2}-\w{3}-\d{4})\s+(\d{2}:\d{2})",
                    text
                )
                if date_match:
                    try:
                        modified_date = datetime.strptime(
                            f"{date_match.group(1)} {date_match.group(2)}",
                            "%d-%b-%Y %H:%M"
                        )
                    except ValueError:
                        pass

            dumps.append(DumpInfo(
                name=href,
                url=url,
                size_bytes=size_bytes,
                modified_date=modified_date,
                dump_type=dump_type,
            ))

        logger.info("[DumpManager] Found %s available dumps", len(dumps))
        return dumps

    def _classify_dump(self, filename: str) -> str | None:
        """Classify a dump file by type."""
        filename_lower = filename.lower()

        if filename_lower.startswith("db_backup_"):
            return "daily"

        return None

    def _daily_snapshot_sort_key(self, dump: DumpInfo) -> tuple[datetime, datetime]:
        """Build sort key for daily full snapshots."""
        coverage_end = self._dump_coverage_end(dump)
        if coverage_end is not None:
            return coverage_end, dump.modified_date
        return dump.modified_date, dump.modified_date

    def get_recommended_dumps(
        self,
        available: list[DumpInfo],
        max_dumps: int = 1,
    ) -> list[DumpInfo]:
        """Get recommended daily dumps.

        Policy:
        1. Import newest missing daily full snapshot that extends coverage.
        """
        imported = set(self.db.get_imported_dumps())
        current_max = self._get_current_max_datetime()

        daily_snapshots = [
            dump for dump in available
            if dump.dump_type == "daily" and dump.name not in imported
        ]
        daily_snapshots.sort(key=self._daily_snapshot_sort_key, reverse=True)
        daily_candidate = self._pick_newer_coverage_dump(daily_snapshots, current_max)
        if daily_candidate is not None:
            return [daily_candidate][:max(1, max_dumps)]

        return []

    def get_missing_dumps(
        self,
        available: list[DumpInfo],
        max_dumps: int | None = None,
    ) -> list[DumpInfo]:
        """Find pending daily dumps based on recommended strategy."""
        recommended = self.get_recommended_dumps(available, max_dumps=max_dumps or 1)
        logger.info(
            "[DumpManager] %s recommended daily dump(s) to import",
            len(recommended),
        )
        return recommended

    async def _process_dumps(
        self,
        dumps_to_process: list[DumpInfo],
        cleanup_after_import: bool = True,
        use_bulk_loading: bool = True,
        parallel_downloads: int = 3,
        run_id: str | None = None,
    ) -> UpdateResult:
        """Process a list of dumps (download and import).

        Internal method used by update().
        """
        downloaded = []
        imported = []
        errors = []
        cleaned_up = []
        total_records = 0

        if not dumps_to_process:
            self._set_progress(
                run_id=run_id,
                stage="planning",
                message="No new dumps to import",
                total_dumps=0,
                completed_dumps=0,
                progress_pct=100.0,
            )
            return UpdateResult(
                success=True,
                downloaded=[],
                imported=[],
                errors=[],
                total_records=0,
            )

        total_dumps = len(dumps_to_process)
        logger.info("[DumpManager] Processing %s dumps", total_dumps)
        self._set_progress(
            run_id=run_id,
            stage="processing",
            message=f"Processing {total_dumps} dump(s)",
            total_dumps=total_dumps,
            completed_dumps=0,
            progress_pct=10.0,
        )

        # Drop indexes for faster bulk loading
        if use_bulk_loading:
            logger.info("[DumpManager] Dropping indexes for bulk loading...")
            self._set_progress(
                run_id=run_id,
                stage="dropping_indexes",
                message="Dropping indexes for bulk loading...",
                progress_pct=12.0,
            )
            self.db.drop_indexes()

        try:
            # Download dumps in parallel
            download_semaphore = asyncio.Semaphore(parallel_downloads)
            total_download_bytes = sum(max(0, dump.size_bytes) for dump in dumps_to_process)
            download_progress: dict[str, int] = {dump.name: 0 for dump in dumps_to_process}

            async def download_with_semaphore(dump: DumpInfo) -> tuple[DumpInfo, Path | None, str | None]:
                async with download_semaphore:
                    try:
                        self._set_progress(
                            run_id=run_id,
                            stage="downloading",
                            message=f"Downloading {dump.name}",
                            current_dump=dump.name,
                            download_total_bytes=total_download_bytes,
                            progress_pct=DOWNLOAD_PROGRESS_START,
                        )

                        def on_download(downloaded: int, content_length: int | None) -> None:
                            dump_size = content_length if content_length and content_length > 0 else dump.size_bytes
                            download_progress[dump.name] = min(downloaded, max(0, dump_size))
                            downloaded_total = sum(download_progress.values())
                            ratio = (
                                min(1.0, downloaded_total / total_download_bytes)
                                if total_download_bytes > 0
                                else 0.0
                            )
                            progress_pct = DOWNLOAD_PROGRESS_START + (
                                (DOWNLOAD_PROGRESS_END - DOWNLOAD_PROGRESS_START) * ratio
                            )
                            self._set_progress(
                                run_id=run_id,
                                stage="downloading",
                                message=f"Downloading {dump.name}",
                                current_dump=dump.name,
                                downloaded_bytes=downloaded_total,
                                download_total_bytes=total_download_bytes,
                                progress_pct=progress_pct,
                            )

                        path = await self.download_dump(dump, progress_callback=on_download)
                        if dump.size_bytes > 0:
                            download_progress[dump.name] = dump.size_bytes
                        return dump, path, None
                    except Exception as e:
                        return dump, None, str(e)

            download_tasks = [download_with_semaphore(d) for d in dumps_to_process]
            download_results = await asyncio.gather(*download_tasks)
            self._set_progress(
                run_id=run_id,
                stage="downloading",
                message="Download stage completed",
                downloaded_bytes=sum(download_progress.values()),
                download_total_bytes=total_download_bytes,
                progress_pct=DOWNLOAD_PROGRESS_END,
            )

            # Process downloaded dumps sequentially
            for index, (dump, dump_path, error) in enumerate(download_results):
                if error:
                    errors.append(f"{dump.name}: Download failed - {error}")
                    self._set_progress(
                        run_id=run_id,
                        errors=errors,
                        message=f"Download failed for {dump.name}",
                    )
                    continue

                downloaded.append(dump.name)
                per_dump_span = (
                    (IMPORT_PROGRESS_END - IMPORT_PROGRESS_START) / max(1, total_dumps)
                )
                dump_start_pct = IMPORT_PROGRESS_START + (index * per_dump_span)
                self._set_progress(
                    run_id=run_id,
                    stage="importing",
                    message=f"Importing {dump.name} ({index + 1}/{total_dumps})",
                    current_dump=dump.name,
                    progress_pct=dump_start_pct + (per_dump_span * 0.1),
                )

                try:
                    def on_import_progress(
                        event: Literal["parsing", "bulk_loading", "imported"],
                        payload: dict[str, Any],
                    ) -> None:
                        if event == "parsing":
                            parsed = int(payload.get("records_parsed") or 0)
                            skipped = int(payload.get("records_skipped_existing") or 0)
                            parsed_fraction = min(0.8, parsed / 2_000_000)
                            self._set_progress(
                                run_id=run_id,
                                stage="importing",
                                message=f"Parsing {dump.name}: {format(parsed, ',')} records",
                                current_dump=dump.name,
                                records_parsed=parsed,
                                records_skipped_existing=skipped,
                                progress_pct=dump_start_pct + (per_dump_span * parsed_fraction),
                            )
                        elif event == "bulk_loading":
                            self._set_progress(
                                run_id=run_id,
                                stage="importing",
                                message=f"Bulk loading {dump.name}...",
                                current_dump=dump.name,
                                progress_pct=dump_start_pct + (per_dump_span * 0.9),
                            )
                        elif event == "imported":
                            imported_count = int(payload.get("records_imported") or 0)
                            self._set_progress(
                                run_id=run_id,
                                stage="importing",
                                message=f"Imported {format(imported_count, ',')} records from {dump.name}",
                                current_dump=dump.name,
                            )

                    count = await self.import_dump(
                        dump_path,
                        dump,
                        use_bulk_loading=use_bulk_loading,
                        progress_callback=on_import_progress,
                    )

                    if count > 0:
                        imported.append(dump.name)
                        total_records += count

                        if cleanup_after_import and dump_path:
                            if self.cleanup_dump(dump_path):
                                cleaned_up.append(dump.name)
                    else:
                        self.db.record_import(
                            dump_name=dump.name,
                            dump_type=dump.dump_type,
                            record_count=0,
                            date_range_start=None,
                            date_range_end=None,
                        )
                        imported.append(dump.name)

                        if cleanup_after_import and dump_path:
                            if self.cleanup_dump(dump_path):
                                cleaned_up.append(dump.name)

                    completed_dumps = len(imported)
                    completed_ratio = completed_dumps / max(1, total_dumps)
                    self._set_progress(
                        run_id=run_id,
                        stage="importing",
                        message=f"Imported {completed_dumps}/{total_dumps} dump(s)",
                        completed_dumps=completed_dumps,
                        records_imported=total_records,
                        progress_pct=IMPORT_PROGRESS_START + (
                            (IMPORT_PROGRESS_END - IMPORT_PROGRESS_START) * completed_ratio
                        ),
                    )
                except Exception as e:
                    error_msg = f"{dump.name}: Import failed - {str(e)}"
                    logger.error("[DumpManager] Error: %s", error_msg)
                    errors.append(error_msg)
                    self._set_progress(
                        run_id=run_id,
                        errors=errors,
                        message=f"Import failed for {dump.name}",
                    )

        finally:
            # Recreate indexes after all imports
            if use_bulk_loading:
                logger.info("[DumpManager] Recreating indexes...")
                self._set_progress(
                    run_id=run_id,
                    stage="recreating_indexes",
                    message="Recreating indexes...",
                    progress_pct=95.0,
                )
                self.db.create_indexes()

        return UpdateResult(
            success=len(errors) == 0,
            downloaded=downloaded,
            imported=imported,
            errors=errors,
            total_records=total_records,
            cleaned_up=cleaned_up if cleaned_up else None,
        )

    async def download_dump(
        self,
        dump: DumpInfo,
        progress_callback: Callable[[int, int | None], None] | None = None,
    ) -> Path:
        """Download a dump file.

        Args:
            dump: Dump info to download

        Returns:
            Path to the downloaded file
        """
        self.download_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.download_dir / dump.name

        if target_path.exists():
            logger.info("[DumpManager] Using cached: %s", dump.name)
            if progress_callback:
                progress_callback(dump.size_bytes, dump.size_bytes)
            return target_path

        logger.info(
            "[DumpManager] Downloading: %s (%s bytes)",
            dump.name,
            dump.size_bytes,
        )

        async with httpx.AsyncClient(timeout=600) as client:  # 10 min timeout for large files
            async with client.stream("GET", dump.url) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                expected_size = int(content_length) if content_length and content_length.isdigit() else None
                downloaded = 0

                with open(target_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, expected_size)

        logger.info("[DumpManager] Downloaded: %s", target_path)
        return target_path

    def cleanup_dump(self, dump_path: Path) -> bool:
        """Remove a downloaded dump file after successful import.

        Args:
            dump_path: Path to the dump file to remove

        Returns:
            True if file was removed, False otherwise
        """
        try:
            if dump_path.exists():
                dump_path.unlink()
                logger.info("[DumpManager] Cleaned up: %s", dump_path.name)
                return True
        except Exception as e:
            logger.warning("[DumpManager] Failed to cleanup %s: %s", dump_path.name, e)
        return False

    async def import_dump(
        self,
        dump_path: Path,
        dump_info: DumpInfo,
        use_bulk_loading: bool = True,
        progress_callback: Callable[[Literal["parsing", "bulk_loading", "imported"], dict[str, Any]], None] | None = None,
    ) -> int:
        """Import a dump file into the database.

        Args:
            dump_path: Path to the dump file
            dump_info: Metadata about the dump
            use_bulk_loading: Whether to use optimized bulk loading (default: True)

        Returns:
            Number of records imported
        """
        logger.info(
            "[DumpManager] Importing: %s (bulk=%s)",
            dump_path.name,
            use_bulk_loading,
        )

        if dump_info.dump_type != "daily":
            logger.warning("[DumpManager] Unsupported dump type: %s", dump_info.dump_type)
            return 0

        current_max_timestamp = self._get_current_max_timestamp()
        if current_max_timestamp and self._is_dump_fully_covered(
            dump_info,
            current_max_timestamp,
        ):
            logger.info(
                "[DumpManager] Skipping %s: already covered by existing data (max timestamp: %s)",
                dump_info.name,
                current_max_timestamp,
            )
            return 0

        if use_bulk_loading:
            count, date_start, date_end = await self._import_with_bulk_loading(
                dump_path,
                dump_info,
                min_timestamp_exclusive=current_max_timestamp,
                progress_callback=progress_callback,
            )
        else:
            # Legacy import path
            count, date_start, date_end = self._import_postgres_dump_tgz(
                dump_path,
                min_timestamp_exclusive=current_max_timestamp,
            )

        if count == 0:
            logger.warning("[DumpManager] No records found in %s", dump_path.name)
            return 0

        # Record the import
        self.db.record_import(
            dump_name=dump_info.name,
            dump_type=dump_info.dump_type,
            record_count=count,
            date_range_start=date_start,
            date_range_end=date_end,
        )
        if progress_callback:
            progress_callback("imported", {"records_imported": count})

        logger.info("[DumpManager] Imported %s records from %s", count, dump_path.name)
        return count

    async def _import_with_bulk_loading(
        self,
        dump_path: Path,
        dump_info: DumpInfo,
        min_timestamp_exclusive: str | None = None,
        progress_callback: Callable[[Literal["parsing", "bulk_loading", "imported"], dict[str, Any]], None] | None = None,
    ) -> tuple[int, str | None, str | None]:
        """Import using optimized bulk loading via CSV.

        This approach:
        1. Streams parsed records to a temp CSV file
        2. Uses DuckDB's COPY to bulk load the CSV
        3. Is 10-50x faster than row-by-row insertion
        """
        temp_dir = Path(tempfile.gettempdir())
        csv_path = temp_dir / f"import_{dump_info.name}.csv"

        try:
            # Stream records to CSV
            logger.info("[DumpManager] Streaming to CSV: %s", csv_path)

            with StreamingCSVWriter(
                csv_path,
                min_timestamp_exclusive=min_timestamp_exclusive,
                progress_callback=(
                    (lambda count, skipped: progress_callback(
                        "parsing",
                        {
                            "records_parsed": count,
                            "records_skipped_existing": skipped,
                        },
                    ))
                    if progress_callback
                    else None
                ),
            ) as csv_writer:
                self._stream_postgres_dump_to_csv(dump_path, csv_writer)

                records_parsed = csv_writer.count
                date_start = csv_writer.date_start
                date_end = csv_writer.date_end
                if progress_callback:
                    progress_callback(
                        "parsing",
                        {
                            "records_parsed": records_parsed,
                            "records_skipped_existing": csv_writer.skipped_existing,
                        },
                    )

            if csv_writer.skipped_existing > 0:
                logger.info(
                    "[DumpManager] Skipped %s already-covered records from %s",
                    format(csv_writer.skipped_existing, ","),
                    dump_info.name,
                )

            if records_parsed == 0:
                return 0, None, None

            logger.info(
                "[DumpManager] Parsed %s records, bulk loading...",
                format(records_parsed, ","),
            )
            if progress_callback:
                progress_callback("bulk_loading", {"records_parsed": records_parsed})

            # Bulk load from CSV
            inserted = self.db.bulk_insert_from_csv(csv_path)

            return inserted, date_start, date_end

        finally:
            # Cleanup temp CSV
            if csv_path.exists():
                csv_path.unlink()

    def _stream_postgres_dump_to_csv(
        self,
        tgz_path: Path,
        csv_writer: StreamingCSVWriter,
    ) -> None:
        """Stream PostgreSQL dump archive to CSV."""
        if not tgz_path.exists():
            raise FileNotFoundError(f"Dump file not found: {tgz_path}")

        logger.info("[DumpManager] Parsing PostgreSQL dump: %s", tgz_path.name)

        with tarfile.open(tgz_path, "r:gz") as tar:
            member = self._select_tgz_member(tar)
            if member is None:
                raise ValueError("No SQL dump file found in archive")

            logger.info("[DumpManager] Using dump member: %s", member.name)
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"Failed to extract {member.name}")

            if member.name.endswith(".gz"):
                with gzip.open(extracted, "rt", encoding="utf-8", errors="replace") as stream:
                    self._stream_sql_to_csv(stream, csv_writer)
            else:
                with io.TextIOWrapper(extracted, encoding="utf-8", errors="replace") as stream:
                    self._stream_sql_to_csv(stream, csv_writer)

    def _stream_sql_to_csv(
        self,
        stream: io.TextIOBase,
        csv_writer: StreamingCSVWriter,
    ) -> None:
        """Stream SQL content to CSV."""
        copy_pattern = re.compile(
            r"^COPY\s+(?P<table>[^\s]+)\s*\((?P<columns>[^)]+)\)\s+FROM\s+stdin;?$",
            re.IGNORECASE,
        )

        in_copy = False
        in_insert = False
        column_map: dict[str, int] = {}

        for raw_line in stream:
            line = raw_line.rstrip("\n")

            if in_copy:
                if line == r"\.":
                    in_copy = False
                    continue

                fields = self._split_copy_line(line)
                record = self._record_from_copy_fields(fields, column_map)
                if record:
                    csv_writer.write_record(record)
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue

            copy_match = copy_pattern.match(stripped)
            if copy_match:
                table_name = self._normalize_table_name(copy_match.group("table"))
                if table_name == "market_history":
                    in_copy = True
                    columns = self._parse_copy_columns(copy_match.group("columns"))
                    column_map = {col: idx for idx, col in enumerate(columns)}
                continue

            if in_insert:
                if stripped.startswith("("):
                    records = self._parse_value_tuples(stripped)
                    csv_writer.write_records(records)

                if stripped.endswith(";"):
                    in_insert = False
                continue

            upper_line = stripped.upper()
            if "INSERT INTO" in upper_line and "MARKET_HISTORY" in upper_line:
                in_insert = True
                if "VALUES" in upper_line:
                    upper_raw = line.upper()
                    values_idx = upper_raw.find("VALUES")
                    after_values = line[values_idx + 6:].strip()
                    if after_values:
                        records = self._parse_value_tuples(after_values)
                        csv_writer.write_records(records)
                if stripped.endswith(";"):
                    in_insert = False

    def _import_postgres_dump_tgz(
        self,
        tgz_path: Path,
        batch_size: int = 10000,
        min_timestamp_exclusive: str | None = None,
    ) -> tuple[int, str | None, str | None]:
        """Extract and import a PostgreSQL dump archive."""
        if not tgz_path.exists():
            raise FileNotFoundError(f"Dump file not found: {tgz_path}")

        logger.info("[DumpManager] Parsing PostgreSQL dump archive: %s", tgz_path.name)

        try:
            with tarfile.open(tgz_path, "r:gz") as tar:
                member = self._select_tgz_member(tar)
                if member is None:
                    raise ValueError("No SQL dump file found in archive")

                logger.info("[DumpManager] Using dump member: %s", member.name)
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise ValueError(f"Failed to extract {member.name} from archive")

                if member.name.endswith(".gz"):
                    with gzip.open(extracted, "rt", encoding="utf-8", errors="replace") as stream:
                        return self._import_from_sql_stream(
                            stream,
                            source_label=member.name,
                            batch_size=batch_size,
                            min_timestamp_exclusive=min_timestamp_exclusive,
                        )

                with io.TextIOWrapper(extracted, encoding="utf-8", errors="replace") as stream:
                    return self._import_from_sql_stream(
                        stream,
                        source_label=member.name,
                        batch_size=batch_size,
                        min_timestamp_exclusive=min_timestamp_exclusive,
                    )

        except tarfile.TarError as e:
            raise ValueError(f"Failed to read dump archive: {e}") from e

    def _select_tgz_member(self, tar: tarfile.TarFile) -> tarfile.TarInfo | None:
        members = [m for m in tar.getmembers() if m.isfile()]
        if not members:
            return None

        sql_members = [
            m for m in members
            if m.name.endswith(".sql") or m.name.endswith(".sql.gz")
        ]
        if not sql_members:
            return None

        market_members = [
            m for m in sql_members
            if "market_history" in m.name.lower()
        ]
        candidates = market_members or sql_members
        candidates.sort(key=lambda m: m.size, reverse=True)
        return candidates[0]

    def _import_from_sql_stream(
        self,
        stream: io.TextIOBase,
        source_label: str,
        batch_size: int = 10000,
        min_timestamp_exclusive: str | None = None,
    ) -> tuple[int, str | None, str | None]:
        """Import market data records from a PostgreSQL SQL stream."""
        copy_pattern = re.compile(
            r"^COPY\s+(?P<table>[^\s]+)\s*\((?P<columns>[^)]+)\)\s+FROM\s+stdin;?$",
            re.IGNORECASE,
        )

        inserted = 0
        date_start = None
        date_end = None
        batch: list[dict[str, Any]] = []
        found_section = False
        in_copy = False
        in_insert = False
        column_map: dict[str, int] = {}
        cutoff = _normalize_timestamp_for_compare(min_timestamp_exclusive)

        for line_num, raw_line in enumerate(stream, 1):
            line = raw_line.rstrip("\n")

            if in_copy:
                if line == r"\.":
                    in_copy = False
                    continue

                fields = self._split_copy_line(line)
                record = self._record_from_copy_fields(fields, column_map)
                if record:
                    timestamp = record.get("timestamp")
                    normalized_ts = _normalize_timestamp_for_compare(timestamp)
                    if cutoff and normalized_ts and normalized_ts <= cutoff:
                        continue
                    if timestamp:
                        date_value = str(timestamp)[:10]
                        if date_start is None or date_value < date_start:
                            date_start = date_value
                        if date_end is None or date_value > date_end:
                            date_end = date_value

                    batch.append(record)
                    if len(batch) >= batch_size:
                        inserted += self.db.insert_records(batch, batch_size=len(batch))
                        batch.clear()
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue

            copy_match = copy_pattern.match(stripped)
            if copy_match:
                table_name = self._normalize_table_name(copy_match.group("table"))
                if table_name == "market_history":
                    found_section = True
                    in_copy = True
                    columns = self._parse_copy_columns(copy_match.group("columns"))
                    column_map = {col: idx for idx, col in enumerate(columns)}
                continue

            if in_insert:
                if stripped.startswith("("):
                    records = self._parse_value_tuples(stripped)
                    for record in records:
                        timestamp = record.get("timestamp")
                        normalized_ts = _normalize_timestamp_for_compare(timestamp)
                        if cutoff and normalized_ts and normalized_ts <= cutoff:
                            continue
                        if timestamp:
                            date_value = str(timestamp)[:10]
                            if date_start is None or date_value < date_start:
                                date_start = date_value
                            if date_end is None or date_value > date_end:
                                date_end = date_value
                        batch.append(record)

                        if len(batch) >= batch_size:
                            inserted += self.db.insert_records(batch, batch_size=len(batch))
                            batch.clear()

                if stripped.endswith(";"):
                    in_insert = False
                continue

            upper_line = stripped.upper()
            if "INSERT INTO" in upper_line and "MARKET_HISTORY" in upper_line:
                found_section = True
                in_insert = True
                if "VALUES" in upper_line:
                    upper_raw = line.upper()
                    values_idx = upper_raw.find("VALUES")
                    after_values = line[values_idx + 6:].strip()
                    if after_values:
                        records = self._parse_value_tuples(after_values)
                        for record in records:
                            timestamp = record.get("timestamp")
                            normalized_ts = _normalize_timestamp_for_compare(timestamp)
                            if cutoff and normalized_ts and normalized_ts <= cutoff:
                                continue
                            if timestamp:
                                date_value = str(timestamp)[:10]
                                if date_start is None or date_value < date_start:
                                    date_start = date_value
                                if date_end is None or date_value > date_end:
                                    date_end = date_value
                            batch.append(record)

                            if len(batch) >= batch_size:
                                inserted += self.db.insert_records(batch, batch_size=len(batch))
                                batch.clear()
                if stripped.endswith(";"):
                    in_insert = False

        if batch:
            inserted += self.db.insert_records(batch, batch_size=len(batch))

        if not found_section:
            raise ValueError(f"No market_history data found in {source_label}")

        logger.info(
            "[DumpManager] Imported %s records from %s (PostgreSQL dump)",
            inserted,
            source_label,
        )
        return inserted, date_start, date_end

    def _normalize_table_name(self, table_name: str) -> str:
        table_name = table_name.strip()
        if "." in table_name:
            table_name = table_name.split(".")[-1]
        return table_name.strip('"')

    def _get_current_max_timestamp(self) -> str | None:
        """Get current database max timestamp, if available."""
        try:
            conn = self.db.connect()
            row = conn.execute(
                "SELECT MAX(timestamp)::VARCHAR FROM market_history"
            ).fetchone()
            if not row:
                return None
            return _normalize_timestamp_for_compare(row[0])
        except Exception:
            # Some tests pass lightweight DB doubles without a real connection.
            return None

    def _get_current_max_datetime(self) -> datetime | None:
        """Get current database max timestamp as datetime."""
        raw = self._get_current_max_timestamp()
        normalized = _normalize_timestamp_for_compare(raw)
        if normalized is None:
            return None
        try:
            return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _pick_newer_coverage_dump(
        self,
        dumps: list[DumpInfo],
        current_max: datetime | None,
    ) -> DumpInfo | None:
        """Pick newest dump that extends current coverage."""
        if not dumps:
            return None
        if current_max is None:
            return dumps[0]

        for dump in dumps:
            coverage_end = self._dump_coverage_end(dump)
            if coverage_end is None or coverage_end > current_max:
                return dump
        return None

    def _dump_coverage_end(self, dump_info: DumpInfo) -> datetime | None:
        """Estimate the latest timestamp represented by a dump filename."""
        if dump_info.dump_type == "daily":
            match = re.search(
                r"db_backup_(\d{4})-(\d{2})-(\d{2})(?:T(\d{2})_(\d{2})_(\d{2}))?",
                dump_info.name,
            )
            if match:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                if match.group(4) and match.group(5) and match.group(6):
                    hour = int(match.group(4))
                    minute = int(match.group(5))
                    second = int(match.group(6))
                    return datetime(year, month, day, hour, minute, second)
                return datetime(year, month, day, 23, 59, 59)
            return None

        return None

    def _is_dump_fully_covered(
        self,
        dump_info: DumpInfo,
        current_max_timestamp: str,
    ) -> bool:
        """Check whether an incoming dump is fully covered by existing data."""
        normalized = _normalize_timestamp_for_compare(current_max_timestamp)
        if normalized is None:
            return False

        try:
            current_max = datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False

        coverage_end = self._dump_coverage_end(dump_info)
        if coverage_end is None:
            return False
        return coverage_end <= current_max

    def _parse_copy_columns(self, columns_str: str) -> list[str]:
        columns = []
        for column in columns_str.split(","):
            cleaned = column.strip().strip('"')
            if cleaned:
                columns.append(cleaned)
        return columns

    def _split_copy_line(self, line: str) -> list[str | None]:
        fields = line.split("\t")
        return [self._unescape_copy_value(field) for field in fields]

    def _unescape_copy_value(self, value: str) -> str | None:
        if value == r"\N":
            return None

        result = []
        i = 0
        while i < len(value):
            char = value[i]
            if char == "\\" and i + 1 < len(value):
                nxt = value[i + 1]
                if nxt == "t":
                    result.append("\t")
                elif nxt == "n":
                    result.append("\n")
                elif nxt == "r":
                    result.append("\r")
                elif nxt == "\\":
                    result.append("\\")
                else:
                    result.append(nxt)
                i += 2
            else:
                result.append(char)
                i += 1

        return "".join(result)

    def _record_from_copy_fields(
        self,
        fields: list[str | None],
        column_map: dict[str, int],
    ) -> dict[str, Any] | None:
        def get_field(*names: str) -> str | None:
            for name in names:
                idx = column_map.get(name)
                if idx is not None and idx < len(fields):
                    return fields[idx]
            return None

        item_id = get_field("item_unique_name", "item_id")
        timestamp = get_field("timestamp")
        if not item_id or not timestamp:
            return None

        item_count = self._parse_int(get_field("item_count") or "NULL")
        silver_amount = self._parse_int(get_field("silver_amount") or "NULL")
        location_id = self._parse_int(get_field("location") or "NULL")
        quality = self._parse_int(get_field("quality_level", "quality") or "NULL")

        location = LOCATION_MAP.get(location_id, str(location_id)) if location_id else "Unknown"

        return {
            "item_id": item_id,
            "location": location,
            "quality": quality or 1,
            "timestamp": timestamp,
            "sell_price_min": silver_amount,
            "sell_price_max": silver_amount,
            "buy_price_min": None,
            "buy_price_max": None,
            "item_count": item_count,
        }

    def _parse_value_tuples(self, line: str) -> list[dict[str, Any]]:
        """Parse one or more value tuples from a line.

        Expected format: (v1,v2,v3,...),(v1,v2,v3,...), ...

        AODP column order:
        0: id (bigint)
        1: item_count (int)
        2: silver_amount (bigint)
        3: item_unique_name (string)
        4: location (int)
        5: quality_level (int)
        6: timestamp (datetime string)
        7: auction_type (int)
        """
        records = []

        # Remove trailing comma, semicolon
        line = line.rstrip(",;")

        # Find all tuples: (...)
        # Use regex to find balanced parentheses with content
        tuple_pattern = re.compile(r'\(([^()]+)\)')

        for match in tuple_pattern.finditer(line):
            values_str = match.group(1)
            values = self._split_sql_values(values_str)

            if len(values) >= 7:
                try:
                    # Parse according to AODP schema
                    item_count = self._parse_int(values[1])
                    silver_amount = self._parse_int(values[2])
                    item_id = self._clean_sql_string(values[3])
                    location_id = self._parse_int(values[4])
                    quality = self._parse_int(values[5])
                    timestamp = self._clean_sql_string(values[6])

                    # Map location ID to name (or keep as string if unknown)
                    location = LOCATION_MAP.get(location_id, str(location_id)) if location_id else "Unknown"

                    # Build record matching our schema
                    record = {
                        "item_id": item_id,
                        "location": location,
                        "quality": quality or 1,
                        "timestamp": timestamp,
                        "sell_price_min": silver_amount,  # AODP provides sell order prices
                        "sell_price_max": silver_amount,
                        "buy_price_min": None,
                        "buy_price_max": None,
                        "item_count": item_count,
                    }

                    if record["item_id"] and record["timestamp"]:
                        records.append(record)

                except Exception as e:
                    logger.debug("[DumpManager] Failed to parse tuple: %s", e)

        return records

    def _split_sql_values(self, values_str: str) -> list[str]:
        """Split SQL values respecting quoted strings."""
        values = []
        current = ""
        in_string = False
        string_char = None

        for char in values_str:
            if char in ("'", '"') and not in_string:
                in_string = True
                string_char = char
                current += char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
                current += char
            elif char == "," and not in_string:
                values.append(current.strip())
                current = ""
            else:
                current += char

        if current:
            values.append(current.strip())

        return values

    def _clean_sql_string(self, value: str) -> str:
        """Remove SQL quotes from a string value."""
        value = value.strip()
        if (value.startswith("'") and value.endswith("'")) or \
           (value.startswith('"') and value.endswith('"')):
            value = value[1:-1]
        # Handle escaped quotes
        value = value.replace("''", "'").replace('\\"', '"')
        return value

    def _parse_int(self, value: str) -> int | None:
        """Parse an integer from SQL value."""
        value = value.strip()
        if value.upper() == "NULL":
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def _run_update_pipeline(
        self,
        *,
        run_id: str,
        max_dumps: int = 1,
        cleanup_after_import: bool = True,
        parallel_downloads: int = 3,
        use_bulk_loading: bool = True,
    ) -> UpdateResult:
        self._set_progress(
            run_id=run_id,
            stage="fetching_index",
            message=f"Fetching dump index from {self.index_url}",
            progress_pct=3.0,
        )
        available = await self.list_available_dumps()
        self._set_progress(
            run_id=run_id,
            stage="planning",
            message=f"Found {len(available)} available dumps",
            progress_pct=7.0,
        )

        to_process = self.get_recommended_dumps(available, max_dumps=max_dumps)
        self._set_progress(
            run_id=run_id,
            stage="planning",
            message=f"Selected {len(to_process)} dump(s) for import",
            total_dumps=len(to_process),
            progress_pct=9.0,
        )

        return await self._process_dumps(
            to_process,
            cleanup_after_import=cleanup_after_import,
            use_bulk_loading=use_bulk_loading,
            parallel_downloads=parallel_downloads,
            run_id=run_id,
        )

    async def update(
        self,
        max_dumps: int = 1,
        cleanup_after_import: bool = True,
        parallel_downloads: int = 3,
        use_bulk_loading: bool = True,
    ) -> UpdateResult:
        """Check for and import new dumps.

        Args:
            max_dumps: Maximum number of dumps to process in one update
            cleanup_after_import: Whether to delete downloaded files after successful import
            parallel_downloads: Number of concurrent downloads (default: 3)
            use_bulk_loading: Whether to use optimized bulk loading (default: True)

        Returns:
            UpdateResult with details about what was imported
        """
        if not self._update_lock.acquire(blocking=False):
            raise RuntimeError("A database update is already in progress")

        run_id = uuid.uuid4().hex
        self._start_progress(run_id, max_dumps=max_dumps)

        try:
            result = await self._run_update_pipeline(
                run_id=run_id,
                max_dumps=max_dumps,
                cleanup_after_import=cleanup_after_import,
                parallel_downloads=parallel_downloads,
                use_bulk_loading=use_bulk_loading,
            )
            self._set_progress(run_id=run_id, result=result.to_dict())
            self._finalize_progress(
                run_id=run_id,
                status="completed",
                message="Database update completed successfully",
            )
            return result
        except Exception as exc:
            error_msg = str(exc)
            self._set_progress(
                run_id=run_id,
                errors=[error_msg],
                result={"success": False, "errors": [error_msg]},
            )
            self._finalize_progress(
                run_id=run_id,
                status="failed",
                message=f"Database update failed: {error_msg}",
            )
            raise
        finally:
            self._update_lock.release()


# Default instance
def get_dump_manager() -> DumpManager:
    """Get the default dump manager instance."""
    from .history_db import get_history_db
    return DumpManager(db=get_history_db())
