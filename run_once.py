"""Manual one-shot collection run (M5 E2E entry)."""

from __future__ import annotations

import asyncio
import sys

from config.settings import load_settings
from infra.db import init_db
from infra.log import get_logger, setup_logging
from intel.collect import job_collect


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
    logger = get_logger("run_once")

    from infra.llm.factory import log_llm_config

    log_llm_config(settings.llm)

    try:
        init_db()
    except SystemExit:
        return 1

    asyncio.run(job_collect(settings))
    logger.info("run_once_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
