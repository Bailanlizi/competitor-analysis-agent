"""APScheduler job registry (SPEC-2026-001 §3.9)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import infra.db as db
from config.settings import AppSettings, get_settings
from infra.log import cleanup_old_logs
from intel.collect import job_collect
from intel.weekly import job_weekly


def job_cleanup_raw_html() -> None:
    db.cleanup_raw_html()


def job_cleanup_failed_push() -> None:
    db.cleanup_failed_push()


def job_cleanup_logs() -> None:
    cleanup_old_logs()


def job_disk_check() -> None:
    db.check_disk_warning()


def create_scheduler(settings: AppSettings | None = None) -> AsyncIOScheduler:
    settings = settings or get_settings()
    tz = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    scheduler.add_job(
        job_collect,
        "interval",
        minutes=settings.interval_minutes,
        id="collect",
        next_run_time=datetime.now(tz),
    )
    scheduler.add_job(
        job_weekly,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="weekly",
        misfire_grace_time=None,
    )
    scheduler.add_job(
        job_cleanup_failed_push,
        "cron",
        hour=1,
        minute=0,
        id="cleanup_failed_push",
    )
    scheduler.add_job(
        job_cleanup_logs,
        "cron",
        hour=2,
        minute=0,
        id="cleanup_logs",
    )
    scheduler.add_job(
        job_cleanup_raw_html,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_raw_html",
    )
    scheduler.add_job(
        job_disk_check,
        "interval",
        minutes=60,
        id="disk_check",
    )
    return scheduler


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    scheduler.start()
