"""Tests for infra/llm.py (SPEC-2026-060 AC-5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from infra.llm import extract
from infra.llm.base import LLMUsage
from models import RawDoc


def _sample_raw() -> RawDoc:
    return RawDoc(
        competitor="competitor_a",
        source_url="https://example.com/post",
        source_type="rss",
        title="Product V2.0 Launch",
        content="We are introducing a new feature for analytics dashboard.",
    )


def _mock_provider(*, available: bool = True, chat_side_effect=None, chat_return=None):
    provider = MagicMock()
    provider.provider_name = "openai"
    provider.model_name = "gpt-4o-mini"
    provider.is_available.return_value = available
    if chat_side_effect is not None:
        provider.chat = AsyncMock(side_effect=chat_side_effect)
    else:
        provider.chat = AsyncMock(
            return_value=chat_return or ('{"intel_type":"new_feature","title":"T","summary":"S"}', LLMUsage(1, 2))
        )
    return provider


@pytest.mark.asyncio
async def test_ac5_llm_fallback_on_rate_limit():
    raw = _sample_raw()
    provider = _mock_provider(
        chat_side_effect=openai.RateLimitError("rate limit", response=MagicMock(), body=None),
    )
    with patch("infra.llm.get_provider", return_value=provider):
        result = await extract(raw)
    assert result.get("_source") == "rule_fallback"
    assert "intel_type" in result
    assert result["title"]


@pytest.mark.asyncio
async def test_rule_extract_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    raw = _sample_raw()
    provider = _mock_provider(available=False)
    with patch("infra.llm.get_provider", return_value=provider):
        result = await extract(raw)
    assert result.get("_source") == "rule_fallback"
