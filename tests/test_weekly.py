"""Tests for intel/weekly.py (SPEC-2026-040)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time

from config.settings import AppSettings, CompetitorConfig, SearchConfig, SourceConfig
from infra.db import get_intel_for_weekly, save_failed_push, save_intel
from infra.utils import get_last_week_range, to_utc_iso
from intel.weekly import (
    _ensure_summaries,
    generate_and_push,
    group_by_competitor,
    render_weekly_markdown,
    sort_intels,
)
from models import Intel


def _settings() -> AppSettings:
    return AppSettings(
        competitors=[
            CompetitorConfig(
                id="competitor_a",
                name="竞品A",
                sources=[SourceConfig(type="rss", url="https://example.com/a.xml")],
            ),
            CompetitorConfig(
                id="competitor_b",
                name="竞品B",
                sources=[SourceConfig(type="rss", url="https://example.com/b.xml")],
            ),
            CompetitorConfig(
                id="competitor_c",
                name="竞品C",
                sources=[SourceConfig(type="rss", url="https://example.com/c.xml")],
            ),
        ],
        search=SearchConfig(),
        feishu_webhook="https://example.com/hook/test",
    )


def _make_intel(**kwargs) -> Intel:
    defaults = {
        "raw_id": "raw001",
        "competitor": "competitor_a",
        "intel_type": "new_feature",
        "title": "Test Feature",
        "summary": "Summary text",
        "confidence": 0.9,
        "source_url": "https://example.com/post",
        "discovered_at": datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc),
        "status": "pushed",
    }
    defaults.update(kwargs)
    return Intel(**defaults)


@freeze_time("2026-06-08 10:00:00", tz_offset=8)
def test_ac1_last_week_range():
    week_start, week_end, start_utc, end_utc = get_last_week_range("Asia/Shanghai")
    assert week_start == "2026-06-01"
    assert week_end == "2026-06-07"
    assert start_utc == "2026-05-31T16:00:00Z"
    assert end_utc.startswith("2026-06-07")


def test_ac1b_utc_boundary_excluded(tmp_env):
    week_start, week_end, start_utc, end_utc = "2026-05-26", "2026-06-01", "2026-05-25T16:00:00Z", "2026-06-01T15:59:59Z"
    save_intel(
        _make_intel(
            id="before",
            discovered_at=datetime(2026, 5, 25, 15, 59, 59, tzinfo=timezone.utc),
        )
    )
    save_intel(
        _make_intel(
            id="inside",
            discovered_at=datetime(2026, 5, 25, 16, 0, 0, tzinfo=timezone.utc),
        )
    )
    results = get_intel_for_weekly(start_utc, end_utc)
    ids = {i.id for i in results}
    assert "before" not in ids
    assert "inside" in ids


def test_ac2_weekly_query_includes_pending_excludes_rejected(tmp_env):
    base = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)
    for i, status in enumerate(["pushed", "pushed", "pushed", "pending", "pending", "rejected"]):
        save_intel(_make_intel(id=f"intel{i}", status=status, discovered_at=base))
    start = to_utc_iso(datetime(2026, 5, 25, 16, 0, 0, tzinfo=timezone.utc))
    end = to_utc_iso(datetime(2026, 6, 1, 15, 59, 59, tzinfo=timezone.utc))
    results = get_intel_for_weekly(start, end)
    assert len(results) == 5
    assert all(r.status in ("pushed", "pending") for r in results)


def test_ac3_group_by_competitor():
    intels = [
        _make_intel(id="a1", competitor="competitor_a"),
        _make_intel(id="a2", competitor="competitor_a"),
        _make_intel(id="b1", competitor="competitor_b"),
        _make_intel(id="c1", competitor="competitor_c"),
    ]
    groups = group_by_competitor(intels, _settings().competitors)
    assert len(groups) == 3
    assert len(groups["competitor_a"]) == 2
    assert len(groups["competitor_b"]) == 1
    assert groups["competitor_c"] == [intels[3]]


def test_ac4_sort_intels():
    intels = [
        _make_intel(id="ui", intel_type="ui_change"),
        _make_intel(id="nf", intel_type="new_feature"),
        _make_intel(id="vu", intel_type="version_update"),
    ]
    sorted_intels = sort_intels(intels)
    assert [i.intel_type for i in sorted_intels] == [
        "new_feature",
        "version_update",
        "ui_change",
    ]


@pytest.mark.asyncio
async def test_ac5_summary_reuse_no_llm():
    long_summary = "这是一段足够长的摘要内容，超过十个字符，不需要调用 LLM 重新生成。"
    intel = _make_intel(summary=long_summary)
    groups = {"competitor_a": [intel]}
    with patch("intel.weekly.llm.generate_summary", new_callable=AsyncMock) as mock_llm:
        await _ensure_summaries(groups)
        mock_llm.assert_not_called()
    assert intel.summary == long_summary


def test_ac6_render_weekly_markdown():
    intels_a = [
        _make_intel(id="a1", title="Feature A", summary="Summary A"),
        _make_intel(id="a2", title="Feature A2", summary="Summary A2"),
    ]
    intels_b = [_make_intel(id="b1", competitor="competitor_b", title="Feature B", summary="Summary B")]
    groups = {
        "competitor_a": intels_a,
        "competitor_b": intels_b,
        "competitor_c": [],
    }
    content = render_weekly_markdown(
        "2026-05-26",
        "2026-06-01",
        groups,
        _settings().competitors,
        llm_summary="本周重点变化",
        failed_pushes=[],
    )
    assert "# 竞品情报周报 2026-05-26 ~ 2026-06-01" in content
    assert "## 本周总结" in content
    assert "## 竞品A" in content
    assert "## 竞品B" in content
    assert "本周无新情报" in content
    assert "[来源](https://example.com/post)" in content
    assert "## 推送失败记录" in content


@pytest.mark.asyncio
@freeze_time("2026-06-02 10:00:00", tz_offset=8)
async def test_ac9_generate_and_push_archives(tmp_env):
    save_intel(_make_intel(id="w1"))
    settings = _settings()
    mock_provider = MagicMock()
    mock_provider.is_available.return_value = False
    with patch("intel.weekly.push.push_weekly_report", new_callable=AsyncMock, return_value=True):
        with patch("infra.llm.get_provider", return_value=mock_provider):
            weekly = await generate_and_push(settings.feishu_webhook, settings)
    report_path = tmp_env["reports"] / f"{weekly.week_start}.md"
    assert report_path.exists()
    assert report_path.read_text(encoding="utf-8") == weekly.content


def test_ac10_failed_push_section():
    failed = [
        {
            "created_at": "2026-05-30T10:00:00Z",
            "title": "Failed Title",
            "error_message": "timeout",
        }
    ]
    content = render_weekly_markdown(
        "2026-05-26",
        "2026-06-01",
        {"competitor_a": [], "competitor_b": [], "competitor_c": []},
        _settings().competitors,
        llm_summary=None,
        failed_pushes=failed,
    )
    assert "Failed Title" in content
    assert "timeout" in content


def test_ac10_failed_push_from_db(tmp_env):
    save_intel(_make_intel(id="fp1", title="Push Failed Intel"))
    save_failed_push("fp1", "https://hook", "connection error")
    from infra.db import get_failed_pushes_enriched

    enriched = get_failed_pushes_enriched()
    assert len(enriched) == 1
    assert enriched[0]["title"] == "Push Failed Intel"
