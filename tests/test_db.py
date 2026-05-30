"""Tests for SPEC-2026-070 storage layer."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from infra.db import (
    cleanup_raw_html,
    content_hash_exists,
    get_intel_by_id,
    get_intel_by_time_range,
    get_recent_titles,
    intel_url_exists,
    save_intel,
    save_raw_doc,
    save_raw_html,
    save_weekly_report,
    touch_raw_doc_by_hash,
    update_intel_status,
)
from infra.utils import compute_content_hash, to_utc_iso
from models import Intel, RawDoc


def _make_intel(**kwargs) -> Intel:
    defaults = {
        "raw_id": "raw001",
        "competitor": "competitor_a",
        "intel_type": "new_feature",
        "title": "Test Feature",
        "summary": "Summary text",
        "confidence": 0.9,
        "source_url": "https://example.com/post",
        "discovered_at": datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc),
    }
    defaults.update(kwargs)
    return Intel(**defaults)


def test_ac1_database_init(tmp_env):
    conn = sqlite3.connect(str(tmp_env["db_path"]))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert {"intel", "raw_doc", "run_log", "failed_push"}.issubset(tables)


def test_ac2_intel_save_and_query(tmp_env):
    intel = _make_intel(id="intel001")
    save_intel(intel)
    loaded = get_intel_by_id("intel001")
    assert loaded is not None
    assert loaded.title == intel.title
    assert loaded.discovered_at == intel.discovered_at
    assert to_utc_iso(loaded.discovered_at).endswith("Z")


def test_ac3_time_range_query(tmp_env):
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(10):
        save_intel(
            _make_intel(
                id=f"intel{i:03d}",
                discovered_at=base + timedelta(hours=i),
                title=f"Title {i}",
            )
        )

    start = to_utc_iso(base + timedelta(hours=2))
    end = to_utc_iso(base + timedelta(hours=5))
    results = get_intel_by_time_range(start, end)
    assert len(results) == 4
    assert all(start <= to_utc_iso(r.discovered_at) <= end for r in results)


def test_ac4_raw_html_path(tmp_env):
    content_hash = "abc123def456"
    rel = save_raw_html("competitor_a", content_hash, "<html>body</html>")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert rel == f"storage/raw/competitor_a/{today}/{content_hash}.html"
    assert Path(rel).exists()

    raw = RawDoc(
        id="raw001",
        competitor="competitor_a",
        source_url="https://example.com/page",
        source_type="http",
        title="Page",
        content="body content",
        content_hash=content_hash,
    )
    save_raw_doc(raw, file_path=rel)

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    row = conn.execute("SELECT file_path FROM raw_doc WHERE id = 'raw001'").fetchone()
    conn.close()
    assert row[0] == rel


def test_ac5_cleanup_raw_html(tmp_env):
    storage: Path = tmp_env["storage"]
    old_date = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(timezone.utc) - timedelta(days=29)).strftime("%Y-%m-%d")

    old_file = storage / "competitor_a" / old_date / "oldhash.html"
    recent_file = storage / "competitor_a" / recent_date / "newhash.html"
    old_file.parent.mkdir(parents=True)
    recent_file.parent.mkdir(parents=True)
    old_file.write_text("<html>old</html>", encoding="utf-8")
    recent_file.write_text("<html>new</html>", encoding="utf-8")

    old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=29)).timestamp()
    os.utime(old_file, (old_ts, old_ts))
    os.utime(recent_file, (recent_ts, recent_ts))

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    conn.execute(
        """
        INSERT INTO raw_doc (id, competitor, source_url, source_type, content_hash, file_path, fetched_at)
        VALUES ('r1', 'competitor_a', 'https://example.com/o', 'http', 'oldhash', ?, ?)
        """,
        (str(old_file.as_posix()), to_utc_iso(datetime.fromtimestamp(old_ts, tz=timezone.utc))),
    )
    conn.commit()
    conn.close()

    deleted = cleanup_raw_html(30)
    assert deleted >= 1
    assert not old_file.exists()
    assert recent_file.exists()


def test_ac6_recent_titles_performance(tmp_env):
    base = datetime.now(timezone.utc)
    for i in range(1000):
        save_intel(
            _make_intel(
                id=f"perf{i:04d}",
                title=f"Title {i}",
                discovered_at=base - timedelta(hours=i % 48),
            )
        )

    start = time.perf_counter()
    titles = get_recent_titles("competitor_a", 7)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(titles) > 0
    assert elapsed_ms <= 100


def test_ac8_rss_metadata(tmp_env):
    for i in range(2):
        raw = RawDoc(
            id=f"rss{i}",
            competitor="competitor_a",
            source_url=f"https://example.com/feed/item{i}",
            source_type="rss",
            title=f"Entry {i}",
            content=f"Content {i}",
        )
        save_raw_doc(raw, file_path=None)

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    rows = conn.execute("SELECT file_path FROM raw_doc").fetchall()
    conn.close()
    assert len(rows) == 2
    assert all(r[0] is None for r in rows)


def test_ac9_intel_url_excludes_rejected(tmp_env):
    intel = _make_intel(
        id="rej001",
        source_url="https://example.com/rejected",
        status="rejected",
    )
    save_intel(intel)
    assert intel_url_exists("https://example.com/rejected") is False

    pending = _make_intel(
        id="pend001",
        source_url="https://example.com/pending",
        status="pending",
    )
    save_intel(pending)
    assert intel_url_exists("https://example.com/pending") is True


def test_ac10_hash_dedup_no_duplicate_raw_doc(tmp_env):
    raw = RawDoc(
        id="raw_dup1",
        competitor="competitor_a",
        source_url="https://example.com/page",
        source_type="http",
        title="Page",
        content="same content here",
    )
    h = compute_content_hash(raw.competitor, str(raw.source_url), raw.content)
    raw.content_hash = h

    save_raw_doc(raw, file_path=None)
    save_raw_doc(
        RawDoc(
            id="raw_dup2",
            competitor="competitor_a",
            source_url="https://example.com/page",
            source_type="http",
            title="Page",
            content="same content here",
            content_hash=h,
        ),
        file_path=None,
    )

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    count = conn.execute("SELECT COUNT(*) FROM raw_doc WHERE content_hash = ?", (h,)).fetchone()[0]
    conn.close()
    assert count == 1
    assert content_hash_exists(h)


def test_touch_raw_doc_updates_fetched_at(tmp_env):
    raw = RawDoc(
        id="touch1",
        competitor="competitor_a",
        source_url="https://example.com/touch",
        source_type="http",
        title="T",
        content="content",
    )
    save_raw_doc(raw, file_path=None)
    h = raw.content_hash
    assert h is not None

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    before = conn.execute(
        "SELECT fetched_at FROM raw_doc WHERE content_hash = ?", (h,)
    ).fetchone()[0]
    conn.close()

    touch_raw_doc_by_hash(h)

    conn = sqlite3.connect(str(tmp_env["db_path"]))
    after = conn.execute(
        "SELECT fetched_at FROM raw_doc WHERE content_hash = ?", (h,)
    ).fetchone()[0]
    conn.close()
    assert after >= before


def test_save_weekly_report(tmp_env):
    path = save_weekly_report("2026-05-26", "# Weekly Report")
    assert Path(path).exists()
    assert Path(path).read_text(encoding="utf-8") == "# Weekly Report"


def test_update_intel_status_missing(tmp_env):
    update_intel_status("nonexistent", "pushed")
