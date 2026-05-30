"""Production entry: scheduler with graceful shutdown (SPEC-2026-001 §3.9)."""

from __future__ import annotations

import asyncio
import signal
import sys

from config.settings import load_settings
from infra.db import init_db
from infra.log import get_logger, setup_logging
from scheduler import create_scheduler, start_scheduler


async def _run(settings) -> None:
    setup_logging()
    from infra.llm.factory import log_llm_config

    log_llm_config(settings.llm)
    init_db()
    scheduler = create_scheduler(settings)
    start_scheduler(scheduler)

    logger = get_logger("main")
    logger.info("scheduler_started", jobs=len(scheduler.get_jobs()))

    stop = asyncio.Event()

    def _shutdown() -> None:
        logger.info("shutdown_signal")
        scheduler.shutdown(wait=True)
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        await stop.wait()
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=True)


def main() -> int:
    try:
        settings = load_settings()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: configuration validation failed: {exc}", file=sys.stderr)
        return 1

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
