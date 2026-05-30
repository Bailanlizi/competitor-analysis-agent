"""Tests for intel/process.py (SPEC-2026-020)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import infra.db as db
from intel.process import LLMExtractResult, _score, clean_content, process
from models import Intel, RawDoc


def _rss_raw(**kwargs) -> RawDoc:
    defaults = {
        "competitor": "competitor_a",
        "source_url": "https://example.com/post?utm_source=twitter",
        "source_type": "rss",
        "title": "Launch",
        "content": "<p>New feature release with analytics dashboard improvements.</p>",
    }
    defaults.update(kwargs)
    return RawDoc(**defaults)


@pytest.mark.asyncio
async def test_ac6_pre_dedup_utm(tmp_env):
    db.save_intel(
        Intel(
            raw_id="r0",
            competitor="competitor_a",
            intel_type="new_feature",
            title="Existing",
            summary="s",
            confidence=0.9,
            source_url="https://example.com/post",
        )
    )
    with patch("intel.process.llm.extract", new_callable=AsyncMock) as mock_llm:
        result = await process(_rss_raw())
    assert result is None
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_ac6d_rejected_url_can_process(tmp_env):
    db.save_intel(
        Intel(
            raw_id="r0",
            competitor="competitor_a",
            intel_type="new_feature",
            title="Old",
            summary="s",
            confidence=0.5,
            source_url="https://example.com/post",
            status="rejected",
        )
    )
    with patch(
        "intel.process.llm.extract",
        new_callable=AsyncMock,
        return_value={
            "intel_type": "new_feature",
            "title": "New Launch",
            "summary": "A substantial summary about the new analytics feature release.",
        },
    ):
        result = await process(_rss_raw())
    assert result is not None
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_ac2_rule_fallback_scoring(tmp_env):
    with patch(
        "intel.process.llm.extract",
        new_callable=AsyncMock,
        return_value={
            "intel_type": "version_update",
            "title": "Update",
            "summary": "short",
            "_source": "rule_fallback",
        },
    ):
        result = await process(
            _rss_raw(content="version update text " * 20, source_type="search")
        )
    assert result is not None
    assert result.confidence <= 0.6
    assert result.extracted_by == "rule_fallback"


def test_ac4_high_score():
    extracted = {"summary": "A" * 30}
    raw = RawDoc(
        competitor="competitor_a",
        source_url="https://example.com/a",
        source_type="rss",
        title="t",
        content="c",
    )
    assert _score(raw, extracted) >= 0.8


def test_ac5_low_score():
    extracted = {"summary": "short", "_source": "rule_fallback"}
    raw = RawDoc(
        competitor="competitor_a",
        source_url="https://example.com/a",
        source_type="search",
        title="t",
        content="c",
    )
    assert _score(raw, extracted) <= 0.6


@pytest.mark.asyncio
async def test_ac7_title_duplicate(tmp_env):
    db.save_intel(
        Intel(
            raw_id="r0",
            competitor="competitor_a",
            intel_type="new_feature",
            title="Product V2.0 Launch",
            summary="summary " * 5,
            confidence=0.9,
            source_url="https://example.com/other",
            discovered_at=datetime.now(timezone.utc),
        )
    )
    with patch(
        "intel.process.llm.extract",
        new_callable=AsyncMock,
        return_value={
            "intel_type": "new_feature",
            "title": "Product V2.0 Launch!",
            "summary": "Another substantial summary for duplicate title test case.",
        },
    ):
        result = await process(
            _rss_raw(source_url="https://example.com/new-post", title="Dup")
        )
    assert result is None


@pytest.mark.asyncio
async def test_ac8_title_not_duplicate(tmp_env):
    db.save_intel(
        Intel(
            raw_id="r0",
            competitor="competitor_a",
            intel_type="new_feature",
            title="Product V2.0 Launch",
            summary="summary " * 5,
            confidence=0.9,
            source_url="https://example.com/other",
        )
    )
    with patch(
        "intel.process.llm.extract",
        new_callable=AsyncMock,
        return_value={
            "intel_type": "new_feature",
            "title": "New Dashboard Feature",
            "summary": "A substantial summary about dashboard redesign and UX updates.",
        },
    ):
        result = await process(
            _rss_raw(source_url="https://example.com/unique-post")
        )
    assert result is not None


def test_clean_content_strips_html():
    html = "<p>Hello</p><p>World</p>"
    cleaned = clean_content(html)
    assert "<" not in cleaned
    assert "Hello" in cleaned


def test_llm_extract_result_validation():
    with pytest.raises(Exception):
        LLMExtractResult(title="only title")
