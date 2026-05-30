"""SQLite storage layer (SPEC-2026-070)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from models import Intel, RawDoc
from infra.utils import compute_content_hash, to_utc_iso, utc_now_iso
from infra.log import get_logger

logger = get_logger(__name__)

DB_PATH = "data/intel.db"
STORAGE_RAW_ROOT = Path("storage/raw")
DOCS_PRICING_ROOT = Path("docs/pricing-history")
DOCS_CHANGELOG_ROOT = Path("docs/changelogs")
REPORTS_WEEKLY_ROOT = Path("reports/weekly")

_DDL = """
CREATE TABLE IF NOT EXISTS intel (
    id              TEXT PRIMARY KEY,
    raw_id          TEXT NOT NULL,
    competitor      TEXT NOT NULL,
    intel_type      TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL,
    confidence      REAL NOT NULL,
    source_url      TEXT NOT NULL,
    discovered_at   TIMESTAMP NOT NULL,
    status          TEXT DEFAULT 'pending',
    dedup_status    TEXT DEFAULT 'ok',
    extracted_by    TEXT DEFAULT 'llm'
);
CREATE INDEX IF NOT EXISTS idx_intel_time ON intel(discovered_at);
CREATE INDEX IF NOT EXISTS idx_intel_competitor ON intel(competitor);
CREATE INDEX IF NOT EXISTS idx_intel_status ON intel(status);
CREATE INDEX IF NOT EXISTS idx_intel_source_url ON intel(source_url);

CREATE TABLE IF NOT EXISTS raw_doc (
    id              TEXT PRIMARY KEY,
    competitor      TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    file_path       TEXT,
    fetched_at      TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_hash ON raw_doc(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_competitor ON raw_doc(competitor, fetched_at);

CREATE TABLE IF NOT EXISTS run_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type        TEXT NOT NULL,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    status          TEXT NOT NULL,
    sources_total   INTEGER DEFAULT 0,
    sources_failed  INTEGER DEFAULT 0,
    intel_new       INTEGER DEFAULT 0,
    duration_ms     INTEGER,
    token_input     INTEGER DEFAULT 0,
    token_output    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS failed_push (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    intel_id        TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP NOT NULL,
    resolved_at     TIMESTAMP
);
"""


def configure_paths(
    *,
    db_path: str | None = None,
    storage_raw_root: Path | str | None = None,
    docs_pricing_root: Path | str | None = None,
    docs_changelog_root: Path | str | None = None,
    reports_weekly_root: Path | str | None = None,
) -> None:
    """Override default paths (used in tests)."""
    global DB_PATH, STORAGE_RAW_ROOT, DOCS_PRICING_ROOT, DOCS_CHANGELOG_ROOT, REPORTS_WEEKLY_ROOT
    if db_path is not None:
        DB_PATH = db_path
    if storage_raw_root is not None:
        STORAGE_RAW_ROOT = Path(storage_raw_root)
    if docs_pricing_root is not None:
        DOCS_PRICING_ROOT = Path(docs_pricing_root)
    if docs_changelog_root is not None:
        DOCS_CHANGELOG_ROOT = Path(docs_changelog_root)
    if reports_weekly_root is not None:
        REPORTS_WEEKLY_ROOT = Path(reports_weekly_root)


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open SQLite connection with auto commit/close."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | None = None) -> None:
    """Initialize database schema (idempotent)."""
    global DB_PATH
    if db_path is not None:
        DB_PATH = db_path

    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with get_connection() as conn:
            conn.executescript(_DDL)
    except sqlite3.DatabaseError as exc:
        logger.error("db_init_failed", error=str(exc))
        raise SystemExit(1) from exc


def _parse_utc_iso(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _row_to_intel(row: sqlite3.Row) -> Intel:
    return Intel(
        id=row["id"],
        raw_id=row["raw_id"],
        competitor=row["competitor"],
        intel_type=row["intel_type"],
        title=row["title"],
        summary=row["summary"],
        confidence=row["confidence"],
        source_url=row["source_url"],
        discovered_at=_parse_utc_iso(row["discovered_at"]),
        status=row["status"],
        dedup_status=row["dedup_status"],
        extracted_by=row["extracted_by"],
    )


def save_intel(intel: Intel) -> None:
    """Insert intel record."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO intel (
                id, raw_id, competitor, intel_type, title, summary,
                confidence, source_url, discovered_at, status,
                dedup_status, extracted_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intel.id,
                intel.raw_id,
                intel.competitor,
                intel.intel_type,
                intel.title,
                intel.summary,
                intel.confidence,
                str(intel.source_url),
                to_utc_iso(intel.discovered_at),
                intel.status,
                intel.dedup_status,
                intel.extracted_by,
            ),
        )
    archive_intel_json(intel)


def get_intel_by_id(intel_id: str) -> Intel | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM intel WHERE id = ?", (intel_id,)).fetchone()
    if row is None:
        return None
    return _row_to_intel(row)


def get_intel_for_weekly(start: str, end: str) -> list[Intel]:
    """Query intel for weekly report: pending + pushed only."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM intel
            WHERE discovered_at BETWEEN ? AND ?
              AND status IN ('pending', 'pushed')
            ORDER BY discovered_at DESC
            """,
            (start, end),
        ).fetchall()
    return [_row_to_intel(row) for row in rows]


def get_failed_pushes_enriched() -> list[dict]:
    """Unresolved failed pushes with intel title for weekly report."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fp.id, fp.intel_id, fp.webhook_url, fp.error_message,
                   fp.retry_count, fp.created_at, i.title
            FROM failed_push fp
            LEFT JOIN intel i ON fp.intel_id = i.id
            WHERE fp.resolved_at IS NULL
            ORDER BY fp.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_intel_by_time_range(
    start: str,
    end: str,
    status: str | None = None,
) -> list[Intel]:
    with get_connection() as conn:
        if status is not None:
            rows = conn.execute(
                """
                SELECT * FROM intel
                WHERE discovered_at BETWEEN ? AND ? AND status = ?
                ORDER BY discovered_at DESC
                """,
                (start, end, status),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM intel
                WHERE discovered_at BETWEEN ? AND ?
                ORDER BY discovered_at DESC
                """,
                (start, end),
            ).fetchall()
    return [_row_to_intel(row) for row in rows]


def update_intel_status(intel_id: str, status: str) -> None:
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE intel SET status = ? WHERE id = ?",
            (status, intel_id),
        )
        if cursor.rowcount == 0:
            logger.warning("intel_status_update_missing", intel_id=intel_id, status=status)


def intel_url_exists(normalized_url: str) -> bool:
    """Return True if URL exists with status pending or pushed."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM intel
            WHERE source_url = ? AND status IN ('pending', 'pushed')
            LIMIT 1
            """,
            (normalized_url,),
        ).fetchone()
    return row is not None


def content_hash_exists(content_hash: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM raw_doc WHERE content_hash = ? LIMIT 1",
            (content_hash,),
        ).fetchone()
    return row is not None


def touch_raw_doc_by_hash(content_hash: str) -> None:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE raw_doc SET fetched_at = ? WHERE content_hash = ?",
            (now, content_hash),
        )


def get_recent_titles(competitor: str, days: int = 7) -> list[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = to_utc_iso(cutoff)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT title FROM intel
            WHERE competitor = ? AND discovered_at >= ?
            ORDER BY discovered_at DESC
            """,
            (competitor, cutoff_iso),
        ).fetchall()
    return [row["title"] for row in rows]


def save_raw_doc(raw: RawDoc, file_path: str | None = None) -> None:
    """Save raw_doc metadata; skip INSERT if content_hash already exists."""
    content_hash = raw.content_hash or compute_content_hash(
        raw.competitor, str(raw.source_url), raw.content
    )
    raw.content_hash = content_hash

    if content_hash_exists(content_hash):
        touch_raw_doc_by_hash(content_hash)
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO raw_doc (
                id, competitor, source_url, source_type,
                content_hash, file_path, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw.id,
                raw.competitor,
                str(raw.source_url),
                raw.source_type,
                content_hash,
                file_path,
                to_utc_iso(raw.fetched_at),
            ),
        )


def save_raw_html(competitor: str, content_hash: str, html: str) -> str:
    """Write HTML file and return relative path."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rel_path = STORAGE_RAW_ROOT / competitor / today / f"{content_hash}.html"
    rel_path.parent.mkdir(parents=True, exist_ok=True)
    rel_path.write_text(html, encoding="utf-8")
    return f"storage/raw/{competitor}/{today}/{content_hash}.html"


def archive_intel_json(intel: Intel) -> None:
    """Archive pricing_change / version_update to JSON files."""
    if intel.intel_type == "pricing_change":
        root = DOCS_PRICING_ROOT
    elif intel.intel_type == "version_update":
        root = DOCS_CHANGELOG_ROOT
    else:
        return

    date_str = intel.discovered_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    target_dir = root / intel.competitor
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{date_str}.json"

    entry = {
        "id": intel.id,
        "title": intel.title,
        "summary": intel.summary,
        "source_url": str(intel.source_url),
        "discovered_at": to_utc_iso(intel.discovered_at),
    }

    records: list[dict] = []
    if target_file.exists():
        records = json.loads(target_file.read_text(encoding="utf-8"))
    records.append(entry)
    target_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def save_weekly_report(week_start: str, content: str) -> str:
    """Save weekly markdown report; overwrite if exists."""
    REPORTS_WEEKLY_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORTS_WEEKLY_ROOT / f"{week_start}.md"
    path.write_text(content, encoding="utf-8")
    return str(path.as_posix())


def save_run_log(
    job_type: str,
    started_at: str,
    status: str,
    *,
    sources_total: int = 0,
    sources_failed: int = 0,
    intel_new: int = 0,
    duration_ms: int | None = None,
    token_input: int = 0,
    token_output: int = 0,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO run_log (
                job_type, started_at, status, sources_total, sources_failed,
                intel_new, duration_ms, token_input, token_output
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_type,
                started_at,
                status,
                sources_total,
                sources_failed,
                intel_new,
                duration_ms,
                token_input,
                token_output,
            ),
        )
        return int(cursor.lastrowid)


def update_run_log(
    log_id: int,
    *,
    finished_at: str | None = None,
    status: str | None = None,
    sources_total: int | None = None,
    sources_failed: int | None = None,
    intel_new: int | None = None,
    duration_ms: int | None = None,
    token_input: int | None = None,
    token_output: int | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    updates = {
        "finished_at": finished_at,
        "status": status,
        "sources_total": sources_total,
        "sources_failed": sources_failed,
        "intel_new": intel_new,
        "duration_ms": duration_ms,
        "token_input": token_input,
        "token_output": token_output,
    }
    for key, val in updates.items():
        if val is not None:
            fields.append(f"{key} = ?")
            values.append(val)
    if not fields:
        return
    values.append(log_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE run_log SET {', '.join(fields)} WHERE id = ?", values)


def save_failed_push(intel_id: str, webhook: str, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO failed_push (intel_id, webhook_url, error_message, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (intel_id, webhook, error, utc_now_iso()),
        )


def get_unresolved_failed_pushes() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, intel_id, webhook_url, error_message, retry_count, created_at
            FROM failed_push
            WHERE resolved_at IS NULL
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_disk_usage_percent(path: str | Path = ".") -> float:
    """Return disk usage percentage for the given path."""
    usage = shutil.disk_usage(path)
    return (usage.used / usage.total) * 100.0


def check_disk_warning(path: str | Path = ".", threshold: float = 80.0) -> float:
    """Log disk_warning if usage exceeds threshold; return usage percent."""
    percent = get_disk_usage_percent(path)
    if percent >= threshold:
        logger.warning("disk_warning", usage_percent=round(percent, 2), level="warning")
    return percent


def cleanup_raw_html(older_than_days: int = 30) -> int:
    """Delete raw HTML files and raw_doc records older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    cutoff_iso = to_utc_iso(cutoff)
    deleted_count = 0

    if STORAGE_RAW_ROOT.exists():
        for html_file in STORAGE_RAW_ROOT.rglob("*.html"):
            try:
                mtime = datetime.fromtimestamp(html_file.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if mtime < cutoff:
                rel_path = html_file.as_posix()
                try:
                    html_file.unlink()
                    deleted_count += 1
                except OSError as exc:
                    logger.warning("cleanup_file_failed", path=rel_path, error=str(exc))
                    continue
                with get_connection() as conn:
                    conn.execute(
                        "DELETE FROM raw_doc WHERE file_path = ?",
                        (rel_path,),
                    )

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM raw_doc WHERE fetched_at < ? AND file_path IS NOT NULL",
            (cutoff_iso,),
        )
        conn.execute(
            "DELETE FROM raw_doc WHERE fetched_at < ? AND file_path IS NULL",
            (cutoff_iso,),
        )

    check_disk_warning()
    return deleted_count


def cleanup_failed_push(older_than_days: int = 7) -> int:
    """Delete unresolved failed_push records older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    cutoff_iso = to_utc_iso(cutoff)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM failed_push
            WHERE created_at < ? AND resolved_at IS NULL
            """,
            (cutoff_iso,),
        )
        deleted = cursor.rowcount
    if deleted > 0:
        logger.warning("failed_push_cleaned", count=deleted)
    return deleted
