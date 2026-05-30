"""Bootstrap entry: load config, init logging and database (M4 smoke test)."""

from __future__ import annotations

import sys

from config.settings import load_settings
from infra.db import init_db
from infra.log import get_logger, setup_logging


def main() -> int:
    try:
        settings = load_settings()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: configuration validation failed: {exc}", file=sys.stderr)
        return 1

    setup_logging()
    logger = get_logger("bootstrap")

    from infra.llm.factory import log_llm_config

    log_llm_config(settings.llm)

    try:
        init_db()
    except SystemExit:
        return 1

    logger.info(
        "bootstrap_ready",
        competitors=len(settings.competitors),
        interval_minutes=settings.interval_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
