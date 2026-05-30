"""Tests for scheduler.py (SPEC-2026-001 §3.9)."""

from __future__ import annotations

from config.settings import AppSettings, CompetitorConfig, SearchConfig, SourceConfig
from scheduler import create_scheduler


def _settings() -> AppSettings:
    return AppSettings(
        interval_minutes=60,
        timezone="Asia/Shanghai",
        competitors=[
            CompetitorConfig(
                id="competitor_a",
                name="A",
                sources=[SourceConfig(type="rss", url="https://example.com/a.xml")],
            ),
            CompetitorConfig(
                id="competitor_b",
                name="B",
                sources=[SourceConfig(type="rss", url="https://example.com/b.xml")],
            ),
            CompetitorConfig(
                id="competitor_c",
                name="C",
                sources=[SourceConfig(type="rss", url="https://example.com/c.xml")],
            ),
        ],
        search=SearchConfig(),
    )


def test_create_scheduler_registers_six_jobs():
    scheduler = create_scheduler(_settings())
    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        "collect",
        "weekly",
        "cleanup_failed_push",
        "cleanup_logs",
        "cleanup_raw_html",
        "disk_check",
    }


def test_collect_job_has_next_run_time():
    scheduler = create_scheduler(_settings())
    collect_job = next(j for j in scheduler.get_jobs() if j.id == "collect")
    assert collect_job.next_run_time is not None


def test_weekly_job_cron_monday_9am():
    scheduler = create_scheduler(_settings())
    weekly_job = next(j for j in scheduler.get_jobs() if j.id == "weekly")
    assert str(weekly_job.trigger) == "cron[day_of_week='mon', hour='9', minute='0']"
    assert weekly_job.misfire_grace_time is None
