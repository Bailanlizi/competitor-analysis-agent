"""Tests for infra/llm.py (SPEC-2026-060 AC-5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import openai
import pytest

from infra.llm import extract
from models import RawDoc


def _sample_raw() -> RawDoc:
    return RawDoc(
        competitor="competitor_a",
        source_url="https://example.com/post",
        source_type="rss",
        title="Product V2.0 Launch",
        content="We are introducing a new feature for analytics dashboard.",
    )


@pytest.mark.asyncio
async def test_ac5_llm_fallback_on_rate_limit():
    raw = _sample_raw()
    with patch("infra.llm._get_client") as mock_client:
        mock = AsyncMock()
        mock.chat.completions.create = AsyncMock(side_effect=openai.RateLimitError("rate limit", response=AsyncMock(), body=None))
        mock_client.return_value = mock

        result = await extract(raw)
        assert result.get("_source") == "rule_fallback"
        assert "intel_type" in result
        assert result["title"]


@pytest.mark.asyncio
async def test_rule_extract_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    raw = _sample_raw()
    result = await extract(raw)
    assert result.get("_source") == "rule_fallback"
