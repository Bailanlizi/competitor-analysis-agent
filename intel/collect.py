"""Collection engine: RSS, HTTP, job orchestration (SPEC-2026-010)."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

import infra.db as db
from config.settings import AppSettings, CompetitorConfig, SourceConfig, get_settings
from infra.http import HttpClientError, fetch_with_retry
from infra.log import get_logger
from infra.utils import compute_content_hash, normalize_url, utc_now_iso
from intel import process, push
from models import RawDoc

logger = get_logger(__name__)

_collect_lock = asyncio.Lock()


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _extract_html_title(html: str) -> str:
    tag = BeautifulSoup(html, "html.parser").find("title")
    return tag.get_text(strip=True) if tag else ""


async def _collect_rss(competitor_id: str, source: SourceConfig, settings: AppSettings) -> list[RawDoc]:
    loop = asyncio.get_event_loop()
    feed = await loop.run_in_executor(None, feedparser.parse, str(source.url))

    if feed.bozo and not feed.entries:
        logger.warning(
            "rss_parse_error",
            url=str(source.url),
            error=str(getattr(feed, "bozo_exception", "unknown")),
        )
        return []

    if not feed.entries:
        logger.info("rss_empty_feed", url=str(source.url))
        return []

    results: list[RawDoc] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.cold_start_days)

    for entry in feed.entries[:10]:
        link = getattr(entry, "link", None)
        if not link:
            continue

        url = normalize_url(link)
        if db.intel_url_exists(url):
            logger.info(
                "collect_pre_dedup_skipped",
                source=str(source.url),
                reason="url_exists",
                link=url,
            )
            continue

        if getattr(entry, "published_parsed", None):
            pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if pub < cutoff:
                logger.info("collect_stale_entry", link=url)
                continue

        summary = getattr(entry, "summary", None) or getattr(entry, "description", "") or ""
        content = _strip_html(summary)
        content = content[:5000]
        raw = RawDoc(
            competitor=competitor_id,
            source_url=link,
            source_type="rss",
            title=getattr(entry, "title", None) or "Untitled",
            content=content,
        )
        db.save_raw_doc(raw, file_path=None)
        results.append(raw)

    return results


async def _collect_http(competitor_id: str, source: SourceConfig) -> list[RawDoc]:
    url = str(source.url)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            resp = await fetch_with_retry(client, url)
        except HttpClientError:
            logger.warning("collect_failed", source=url, type="http")
            return []
        except Exception as exc:
            logger.error("collect_failed", source=url, type="http", error=str(exc))
            return []

        html = resp.text
        doc = trafilatura.bare_extraction(html, with_metadata=True)
        if doc:
            content = doc.get("text") or ""
            title = doc.get("title") or _extract_html_title(html) or source.name or "Untitled"
        else:
            content = trafilatura.extract(html) or ""
            title = _extract_html_title(html) or source.name or "Untitled"

        content = content[:5000]
        content_hash = compute_content_hash(competitor_id, url, content)

        if db.content_hash_exists(content_hash):
            db.touch_raw_doc_by_hash(content_hash)
            logger.info(
                "collect_pre_dedup_skipped",
                source=url,
                reason="hash_unchanged",
            )
            return []

        file_path = db.save_raw_html(competitor_id, content_hash, html)
        raw = RawDoc(
            competitor=competitor_id,
            source_url=source.url,
            source_type="http",
            title=title[:200],
            content=content,
            content_hash=content_hash,
        )
        db.save_raw_doc(raw, file_path=file_path)
        return [raw]


async def collect_source(competitor_id: str, source: SourceConfig, settings: AppSettings) -> list[RawDoc]:
    if source.type == "rss":
        return await _collect_rss(competitor_id, source, settings)
    if source.type == "http":
        return await _collect_http(competitor_id, source)
    if source.type == "search":
        if not settings.search.enabled:
            return []
        logger.info("search_skipped", reason="not_implemented_v1")
        return []
    return []


async def collect_all(competitor: CompetitorConfig, settings: AppSettings | None = None) -> list[RawDoc]:
    settings = settings or get_settings()
    all_docs: list[RawDoc] = []
    for source in competitor.sources:
        try:
            docs = await collect_source(competitor.id, source, settings)
            all_docs.extend(docs)
        except Exception as exc:
            logger.error(
                "collect_failed",
                competitor=competitor.id,
                source=str(source.url),
                error=str(exc),
            )
    return all_docs


async def job_collect(settings: AppSettings | None = None) -> None:
    if _collect_lock.locked():
        logger.warning("job_collect_skipped_overlap")
        return

    settings = settings or get_settings()
    webhook = push.resolve_webhook(settings)

    async with _collect_lock:
        start = time.perf_counter()
        log_id = db.save_run_log(
            job_type="collection",
            started_at=utc_now_iso(),
            status="running",
            sources_total=sum(len(c.sources) for c in settings.competitors if c.enabled),
        )
        logger.info("job_start", type="collection", competitors_count=len(settings.competitors))

        total_new = 0
        sources_failed = 0

        for competitor in settings.competitors:
            if not competitor.enabled:
                continue
            try:
                raw_docs = await collect_all(competitor, settings)
            except Exception as exc:
                sources_failed += 1
                logger.error("collect_failed", competitor=competitor.id, error=str(exc))
                continue

            for raw in raw_docs:
                try:
                    intel = await process.process(raw)
                    if intel:
                        total_new += 1
                        await push.push(intel, webhook)
                except Exception as exc:
                    logger.error("process_failed", raw_id=raw.id, error=str(exc))

        duration_ms = int((time.perf_counter() - start) * 1000)
        status = "partial_success" if sources_failed else "success"
        db.update_run_log(
            log_id,
            finished_at=utc_now_iso(),
            status=status,
            intel_new=total_new,
            sources_failed=sources_failed,
            duration_ms=duration_ms,
        )
        logger.info(
            "job_end",
            type="collection",
            status=status,
            duration_ms=duration_ms,
            intel_new=total_new,
            sources_failed=sources_failed,
        )
