"""Tests for SPEC-2026-050 structured logging (AC-4)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

import infra.log as log_module
from infra.log import get_logger, mask_webhook, setup_logging


def test_mask_webhook():
    assert mask_webhook("https://example.com/hook/abcd1234") == "****1234"
    assert mask_webhook("") == ""


def test_ac4_structured_log_fields(tmp_path: Path):
    log_dir = tmp_path / "logs"
    structlog.reset_defaults()
    log_module._CONFIGURED = False
    setup_logging(str(log_dir))

    logger = get_logger("test")
    logger.info("job_start", type="collection", competitors_count=3)
    logger.info("job_end", type="collection", status="success", duration_ms=1200)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.json"
    assert log_file.exists()

    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").strip().splitlines()]
    events = {line.get("event") for line in lines}
    assert "job_start" in events
    assert "job_end" in events

    job_end = next(line for line in lines if line.get("event") == "job_end")
    assert "timestamp" in job_end
    assert job_end.get("duration_ms") == 1200
