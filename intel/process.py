"""Intelligence processing pipeline (SPEC-2026-020)."""

from __future__ import annotations

import asyncio
import re
import time
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

import infra.db as db
import infra.llm as llm
from infra.log import get_logger
from infra.utils import normalize_url
from models import Intel, RawDoc

logger = get_logger(__name__)

DEDUP_TIMEOUT_SEC = 5.0
TITLE_DUPLICATE_THRESHOLD = 0.85


class LLMExtractResult(BaseModel):
    intel_type: Literal["new_feature", "version_update", "pricing_change", "ui_change"]
    title: str = Field(max_length=50)
    summary: str = Field(max_length=100)


def clean_content(content: str) -> str:
    text = re.sub(r"<[^>]+>", "", content)
    text = re.sub(r"\n{3,}", "\n\n", text)
    noise_patterns = ["分享到", "相关阅读", "推荐阅读", "广告", "Share this"]
    lines = [line for line in text.split("\n") if not any(p in line for p in noise_patterns)]
    return "\n".join(lines).strip()


def _score(raw: RawDoc, extracted: dict) -> float:
    score = 0.5
    if raw.source_type == "rss":
        score += 0.2
    if len(extracted.get("summary", "")) > 20:
        score += 0.2
    if raw.source_type == "http" and len(raw.content) > 500:
        score += 0.1
    if extracted.get("_source") == "rule_fallback":
        score -= 0.2
    if raw.source_type == "search":
        score -= 0.1
    if len(extracted.get("summary", "")) <= 10:
        score -= 0.2
    return min(max(score, 0.0), 1.0)


async def _pre_dedup(raw: RawDoc) -> bool:
    """Return True if duplicate and should skip."""
    if raw.source_type in ("rss", "search"):
        url = normalize_url(str(raw.source_url))
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(db.intel_url_exists, url),
                timeout=DEDUP_TIMEOUT_SEC,
            )
        except TimeoutError:
            logger.warning("dedup_timeout", raw_id=raw.id)
            return False
    return False


async def _is_title_duplicate(intel: Intel) -> bool:
    try:
        titles = await asyncio.wait_for(
            asyncio.to_thread(db.get_recent_titles, intel.competitor, 7),
            timeout=DEDUP_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.warning("dedup_timeout", intel_id=intel.id, stage="title")
        intel.dedup_status = "unchecked"
        return False

    for existing in titles:
        ratio = SequenceMatcher(None, intel.title.lower(), existing.lower()).ratio()
        if ratio > TITLE_DUPLICATE_THRESHOLD:
            return True
    return False


async def _handle_extract_failure(raw: RawDoc, extracted: dict) -> Intel:
    intel = Intel(
        raw_id=raw.id,
        competitor=raw.competitor,
        intel_type="version_update",
        title=raw.title[:50],
        summary="[LLM提取失败，待人工审核]",
        confidence=0.3,
        source_url=normalize_url(str(raw.source_url)),
        extracted_by="llm",
        status="pending",
    )
    db.save_intel(intel)
    return intel


async def process(raw: RawDoc) -> Intel | None:
    raw.content = clean_content(raw.content)
    if not raw.content.strip():
        logger.info("skip_empty_content", raw_id=raw.id)
        return None

    if await _pre_dedup(raw):
        logger.info("pre_dedup_skipped", raw_id=raw.id, source_url=str(raw.source_url))
        return None

    extracted = await llm.extract(raw)

    try:
        result = LLMExtractResult(**extracted)
    except ValidationError:
        return await _handle_extract_failure(raw, extracted)

    confidence = _score(raw, extracted)
    extracted_by = "rule_fallback" if extracted.get("_source") == "rule_fallback" else "llm"

    intel = Intel(
        raw_id=raw.id,
        competitor=raw.competitor,
        intel_type=result.intel_type,
        title=result.title,
        summary=result.summary,
        confidence=confidence,
        source_url=normalize_url(str(raw.source_url)),
        extracted_by=extracted_by,
    )

    if await _is_title_duplicate(intel):
        logger.info("title_duplicate_skipped", title=intel.title)
        return None

    db.save_intel(intel)
    return intel
