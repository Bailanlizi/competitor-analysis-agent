"""Tests for intel/push.py (SPEC-2026-030)."""

from __future__ import annotations

import httpx
import pytest
import respx

from intel.push import build_feishu_message, push, should_push
from models import Intel


def _intel(**kwargs) -> Intel:
    defaults = {
        "raw_id": "raw1",
        "competitor": "competitor_a",
        "intel_type": "new_feature",
        "title": "Product Launch",
        "summary": "New analytics feature",
        "confidence": 0.9,
        "source_url": "https://example.com/post",
        "extracted_by": "llm",
    }
    defaults.update(kwargs)
    return Intel(**defaults)


def test_should_push_high_confidence():
    assert should_push(_intel(confidence=0.9)) is True


def test_ac2_new_feature_llm_low_confidence():
    assert should_push(
        _intel(confidence=0.5, intel_type="new_feature", extracted_by="llm")
    ) is True


def test_ac3_rule_fallback_new_feature_not_forced():
    assert should_push(
        _intel(confidence=0.5, intel_type="new_feature", extracted_by="rule_fallback")
    ) is False


def test_ac8_unchecked_tag():
    msg = build_feishu_message(_intel(dedup_status="unchecked"))
    assert "[未去重]" in msg["content"]["text"]


@pytest.mark.asyncio
async def test_ac1_high_confidence_push(tmp_env):
    intel = _intel()
    import infra.db as db

    db.save_intel(intel)
    webhook = "https://open.feishu.cn/hook/test1234"
    with respx.mock:
        respx.post(webhook).mock(return_value=httpx.Response(200, json={"code": 0}))
        ok = await push(intel, webhook)
    assert ok is True
    loaded = db.get_intel_by_id(intel.id)
    assert loaded is not None
    assert loaded.status == "pushed"


@pytest.mark.asyncio
async def test_ac4_push_failure_keeps_pending(tmp_env):
    intel = _intel()
    import infra.db as db

    db.save_intel(intel)
    webhook = "https://open.feishu.cn/hook/fail"
    with respx.mock:
        respx.post(webhook).mock(return_value=httpx.Response(500))
        ok = await push(intel, webhook)
    assert ok is False
    loaded = db.get_intel_by_id(intel.id)
    assert loaded is not None
    assert loaded.status == "pending"


@pytest.mark.asyncio
async def test_ac6_webhook_empty(tmp_env):
    intel = _intel()
    import infra.db as db

    db.save_intel(intel)
    ok = await push(intel, "")
    assert ok is False
