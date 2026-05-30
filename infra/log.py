"""Structured logging (SPEC-2026-050 L3-5.3.1)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

_CONFIGURED = False
_LOG_DIR: Path | None = None


def mask_webhook(url: str) -> str:
    """Mask webhook URL, showing only last 4 characters."""
    if not url:
        return ""
    if len(url) <= 4:
        return "****"
    return f"****{url[-4:]}"


class _DailyJsonFileWriter:
    """Append JSON lines to logs/{YYYY-MM-DD}.json."""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._current_date: str | None = None
        self._file = None

    def _ensure_file(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_date != today or self._file is None:
            if self._file is not None:
                self._file.close()
            self._current_date = today
            path = self._log_dir / f"{today}.json"
            self._file = path.open("a", encoding="utf-8")

    def write(self, message: str) -> None:
        self._ensure_file()
        assert self._file is not None
        self._file.write(message)
        if not message.endswith("\n"):
            self._file.write("\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


_file_writer: _DailyJsonFileWriter | None = None


def _json_renderer(logger: Any, method_name: str, event_dict: dict) -> str:
    """Render structlog event dict as JSON line."""
    record = dict(event_dict)
    record.setdefault("timestamp", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    record.setdefault("level", method_name)
    if "event" not in record and "message" in record:
        record["event"] = record.pop("message")
    return json.dumps(record, ensure_ascii=False, default=str)


def setup_logging(log_dir: str = "logs") -> None:
    """Configure structlog to write JSON lines to daily log files."""
    global _CONFIGURED, _LOG_DIR, _file_writer

    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"error: cannot create logs/ directory: {exc}", file=sys.stderr)
        sys.exit(1)

    _LOG_DIR = log_path
    _file_writer = _DailyJsonFileWriter(log_path)

    def _write_to_file(logger: Any, method_name: str, event_dict: dict) -> dict:
        line = _json_renderer(logger, method_name, event_dict)
        if _file_writer is not None:
            _file_writer.write(line)
        return event_dict

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _write_to_file,
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger."""
    if not _CONFIGURED:
        setup_logging()
    return structlog.get_logger(name)


def get_log_dir() -> Path | None:
    """Return configured log directory."""
    return _LOG_DIR


def cleanup_old_logs(
    log_dir: str = "logs",
    compress_after_days: int = 14,
    delete_after_days: int = 30,
) -> int:
    """Compress old JSON logs and delete very old log files."""
    import gzip
    import shutil

    log_path = Path(log_dir)
    if not log_path.exists():
        return 0

    now = datetime.now(timezone.utc)
    affected = 0

    for json_file in list(log_path.glob("*.json")):
        try:
            file_date = datetime.strptime(json_file.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_days = (now.date() - file_date.date()).days
        if age_days >= delete_after_days:
            json_file.unlink(missing_ok=True)
            gz_path = log_path / f"{json_file.stem}.json.gz"
            gz_path.unlink(missing_ok=True)
            affected += 1
        elif age_days >= compress_after_days:
            gz_path = log_path / f"{json_file.stem}.json.gz"
            if not gz_path.exists():
                with json_file.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                json_file.unlink()
                affected += 1

    for gz_file in list(log_path.glob("*.json.gz")):
        date_str = gz_file.name.removesuffix(".json.gz")
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        age_days = (now.date() - file_date.date()).days
        if age_days >= delete_after_days:
            gz_file.unlink(missing_ok=True)
            affected += 1

    return affected
