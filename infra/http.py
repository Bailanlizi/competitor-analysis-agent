"""HTTP client with retry and status-code handling (SPEC-2026-060 L3-6.1)."""

from __future__ import annotations

import httpx
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_fixed,
)

from infra.log import get_logger

logger = get_logger(__name__)

USER_AGENT = "CompetitorIntelBot/1.0"
DEFAULT_TIMEOUT = 10.0


class HttpClientError(Exception):
    """HTTP response error that should not be retried (4xx)."""

    def __init__(self, status_code: int, url: str, message: str = "") -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message or f"HTTP {status_code} for {url}")


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "retry_attempt",
        attempt_number=retry_state.attempt_number,
        exception_type=type(exc).__name__ if exc else None,
        next_wait_seconds=getattr(retry_state.next_action, "sleep", None),
    )


def _is_retryable_status(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and (
        exc.response.status_code >= 500 or exc.response.status_code == 429
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(
        (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)
    ),
    before_sleep=_log_retry,
    reraise=True,
)
async def _fetch_network(client: httpx.AsyncClient, url: str) -> httpx.Response:
    return await client.get(url, headers={"User-Agent": USER_AGENT})


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception(_is_retryable_status),
    before_sleep=_log_retry,
    reraise=True,
)
async def _fetch_with_server_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    resp = await client.get(url, headers={"User-Agent": USER_AGENT})
    if resp.status_code >= 500 or resp.status_code == 429:
        resp.raise_for_status()
    return resp


async def fetch_with_retry(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Fetch URL with network retries then optional 5xx/429 retries."""
    try:
        resp = await _fetch_network(client, url)
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
        logger.error("http_fetch_failed", url=url, error=str(exc), attempts="3 attempts failed")
        raise

    if 400 <= resp.status_code < 500:
        logger.info(
            "http_response",
            url=url,
            status_code=resp.status_code,
            retry_count=0,
            decision="no_retry",
        )
        if resp.status_code == 404:
            logger.warning("source_not_found", url=url)
        raise HttpClientError(resp.status_code, url)

    if resp.status_code >= 500 or resp.status_code == 429:
        try:
            resp = await _fetch_with_server_retry(client, url)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "http_fetch_failed",
                url=url,
                status_code=exc.response.status_code,
                error=str(exc),
            )
            raise

    logger.info(
        "http_response",
        url=url,
        status_code=resp.status_code,
        retry_count=0,
        decision="success",
    )
    return resp


async def fetch_text(url: str) -> str:
    """Convenience wrapper: create client and return response text."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
        resp = await fetch_with_retry(client, url)
        resp.raise_for_status()
        return resp.text
