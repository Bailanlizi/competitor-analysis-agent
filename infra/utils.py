"""Shared utilities for UTC timestamps and content hashing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def to_utc_iso(dt: datetime) -> str:
    """Convert datetime to UTC ISO8601 string with Z suffix for SQL storage."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    """Current UTC time as ISO8601 Z string."""
    return to_utc_iso(datetime.now(timezone.utc))


def compute_content_hash(competitor: str, source_url: str, content: str) -> str:
    """SHA256(competitor + source_url + content[:1000]) first 12 hex chars."""
    raw = f"{competitor}{source_url}{content[:1000]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def normalize_url(url: str) -> str:
    """Strip utm_*, ref, source tracking query params."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    params = {
        k: v
        for k, v in parse_qs(parsed.query).items()
        if not k.startswith(("utm_", "ref", "source"))
    }
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def get_last_week_range(timezone_name: str = "Asia/Shanghai") -> tuple[str, str, str, str]:
    """Return display dates and UTC ISO boundaries for the previous calendar week."""
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    days_since_monday = now.weekday()
    last_monday = (now - timedelta(days=days_since_monday + 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end_local = last_monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    week_start_utc = to_utc_iso(last_monday)
    week_end_utc = to_utc_iso(week_end_local)
    week_start_display = last_monday.strftime("%Y-%m-%d")
    week_end_display = week_end_local.strftime("%Y-%m-%d")
    return week_start_display, week_end_display, week_start_utc, week_end_utc
