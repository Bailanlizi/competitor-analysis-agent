"""Tests for intel/collect.py (SPEC-2026-010)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from config.settings import AppSettings, CompetitorConfig, SearchConfig, SourceConfig
from intel.collect import _collect_http, _collect_rss, collect_all, job_collect
from models import RawDoc


def _settings() -> AppSettings:
    return AppSettings(
        competitors=[
            CompetitorConfig(
                id="competitor_a",
                name="A",
                sources=[
                    SourceConfig(type="rss", url="https://example.com/feed.xml"),
                    SourceConfig(type="http", url="https://example.com/changelog", name="Changelog"),
                ],
            ),
            CompetitorConfig(id="competitor_b", name="B", sources=[SourceConfig(type="rss", url="https://example.com/b.xml")]),
            CompetitorConfig(
                id="competitor_c",
                name="C",
                sources=[SourceConfig(type="http", url="https://example.com/c", name="C page")],
            ),
        ],
        search=SearchConfig(),
    )


def _feed(entries):
    feed = SimpleNamespace(bozo=False, bozo_exception=None, entries=entries)
    return feed


@pytest.mark.asyncio
async def test_ac1_rss_collect(tmp_env):
    entry = SimpleNamespace(
        link="https://example.com/article-1",
        title="Article 1",
        summary="<p>Content one</p>",
        published_parsed=(2026, 5, 28, 12, 0, 0, 0, 0, 0),
    )
    source = SourceConfig(type="rss", url="https://example.com/feed.xml")
    with patch("intel.collect.feedparser.parse", return_value=_feed([entry] * 5)):
        docs = await _collect_rss("competitor_a", source, _settings())
    assert len(docs) == 5
    for doc in docs:
        assert doc.source_type == "rss"
        assert doc.title
        assert doc.content
        assert doc.competitor == "competitor_a"


@pytest.mark.asyncio
async def test_ac2_rss_empty_feed(tmp_env):
    source = SourceConfig(type="rss", url="https://example.com/empty.xml")
    with patch("intel.collect.feedparser.parse", return_value=_feed([])):
        docs = await _collect_rss("competitor_a", source, _settings())
    assert docs == []


@pytest.mark.asyncio
async def test_ac4_http_collect(tmp_env):
    html = "<html><head><title>Changelog - Product</title></head><body><p>Release notes</p></body></html>"
    source = SourceConfig(type="http", url="https://example.com/changelog", name="Changelog")
    with respx.mock:
        respx.get("https://example.com/changelog").mock(return_value=httpx.Response(200, text=html))
        with patch("intel.collect.trafilatura.bare_extraction") as mock_extract:
            mock_extract.return_value = {"text": "Release notes body text", "title": "Changelog - Product"}
            docs = await _collect_http("competitor_a", source)
    assert len(docs) == 1
    assert docs[0].title == "Changelog - Product"
    assert "Release notes" in docs[0].content


@pytest.mark.asyncio
async def test_ac4b_http_title_fallback(tmp_env):
    html = "<html><body><p>Body only</p></body></html>"
    source = SourceConfig(type="http", url="https://example.com/page", name="更新日志")
    with respx.mock:
        respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=html))
        with patch("intel.collect.trafilatura.bare_extraction", return_value=None):
            with patch("intel.collect.trafilatura.extract", return_value="Body only"):
                docs = await _collect_http("competitor_a", source)
    assert docs[0].title == "更新日志"


@pytest.mark.asyncio
async def test_ac12_http_hash_dedup(tmp_env):
    html = "<html><title>T</title><body>Same content</body></html>"
    source = SourceConfig(type="http", url="https://example.com/page", name="Page")
    with respx.mock:
        respx.get("https://example.com/page").mock(return_value=httpx.Response(200, text=html))
        with patch("intel.collect.trafilatura.bare_extraction") as mock_extract:
            mock_extract.return_value = {"text": "Same content", "title": "T"}
            first = await _collect_http("competitor_a", source)
            second = await _collect_http("competitor_a", source)
    assert len(first) == 1
    assert len(second) == 0


@pytest.mark.asyncio
async def test_ac8_single_source_failure(tmp_env, monkeypatch):
    settings = _settings()

    async def mock_collect_all(competitor, settings=None):
        if competitor.id == "competitor_a":
            raise TimeoutError("source failed")
        return [
            RawDoc(
                competitor=competitor.id,
                source_url="https://example.com/ok",
                source_type="rss",
                title="T",
                content="body text",
            )
        ]

    monkeypatch.setattr("intel.collect.collect_all", mock_collect_all)
    monkeypatch.setattr("intel.collect.process.process", AsyncMock(return_value=None))

    await job_collect(settings)


@pytest.mark.asyncio
async def test_ac14_cold_start_filter(tmp_env):
    old_entry = SimpleNamespace(
        link="https://example.com/old",
        title="Old",
        summary="old",
        published_parsed=(2020, 1, 1, 0, 0, 0, 0, 0, 0),
    )
    new_entry = SimpleNamespace(
        link="https://example.com/new",
        title="New",
        summary="new",
        published_parsed=(2026, 5, 28, 0, 0, 0, 0, 0, 0),
    )
    source = SourceConfig(type="rss", url="https://example.com/feed.xml")
    with patch("intel.collect.feedparser.parse", return_value=_feed([old_entry, new_entry])):
        docs = await _collect_rss("competitor_a", source, _settings())
    assert len(docs) == 1
    assert str(docs[0].source_url) == "https://example.com/new"
