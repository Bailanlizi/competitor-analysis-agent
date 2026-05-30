"""End-to-end pipeline tests (M5 integration)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from config.settings import AppSettings, CompetitorConfig, SearchConfig, SourceConfig
from intel.collect import job_collect
import infra.db as db


def _minimal_settings() -> AppSettings:
    return AppSettings(
        feishu_webhook="",
        competitors=[
            CompetitorConfig(
                id="competitor_a",
                name="A",
                enabled=True,
                sources=[SourceConfig(type="rss", url="https://example.com/feed.xml")],
            ),
            CompetitorConfig(
                id="competitor_b",
                name="B",
                enabled=False,
                sources=[SourceConfig(type="rss", url="https://example.com/b.xml")],
            ),
            CompetitorConfig(
                id="competitor_c",
                name="C",
                enabled=False,
                sources=[SourceConfig(type="http", url="https://example.com/c", name="C")],
            ),
        ],
        search=SearchConfig(),
    )


@pytest.mark.asyncio
async def test_pipeline_rss_to_pending_without_webhook(tmp_env):
    entry = SimpleNamespace(
        link="https://example.com/pipeline-1",
        title="Pipeline Article",
        summary="Introducing a major new analytics feature for users.",
        published_parsed=(2026, 5, 29, 12, 0, 0, 0, 0, 0),
    )
    feed = SimpleNamespace(bozo=False, bozo_exception=None, entries=[entry])

    with patch("intel.collect.feedparser.parse", return_value=feed):
        with patch(
            "intel.process.llm.extract",
            new_callable=AsyncMock,
            return_value={
                "intel_type": "new_feature",
                "title": "Pipeline Feature",
                "summary": "A substantial summary about the new analytics pipeline feature.",
            },
        ):
            await job_collect(_minimal_settings())

    rows = db.get_intel_by_time_range("2000-01-01T00:00:00Z", "2099-01-01T01:00:00Z")
    assert len(rows) >= 1
    intel = rows[0]
    assert intel.status == "pending"


@pytest.mark.asyncio
async def test_pipeline_high_confidence_push(tmp_env):
    entry = SimpleNamespace(
        link="https://example.com/pipeline-push",
        title="Push Article",
        summary="Launch introducing new feature.",
        published_parsed=(2026, 5, 29, 12, 0, 0, 0, 0, 0),
    )
    feed = SimpleNamespace(bozo=False, bozo_exception=None, entries=[entry])
    settings = _minimal_settings()
    settings.feishu_webhook = "https://open.feishu.cn/hook/pipeline"

    with patch("intel.collect.feedparser.parse", return_value=feed):
        with patch(
            "intel.process.llm.extract",
            new_callable=AsyncMock,
            return_value={
                "intel_type": "new_feature",
                "title": "Push Feature",
                "summary": "A substantial summary about push pipeline feature release today.",
            },
        ):
            with respx.mock:
                respx.post(settings.feishu_webhook).mock(
                    return_value=httpx.Response(200, json={"code": 0})
                )
                await job_collect(settings)

    rows = db.get_intel_by_time_range("2000-01-01T00:00:00Z", "2099-01-01T01:00:00Z")
    pushed = [r for r in rows if r.source_url and "pipeline-push" in str(r.source_url)]
    assert pushed
    assert pushed[0].status == "pushed"
