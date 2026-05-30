"""Shared Pydantic models (SPEC-2026-001 §3.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RawDoc(BaseModel):
    """采集输出."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    competitor: str
    source_url: HttpUrl
    source_type: Literal["rss", "http", "search"]
    title: str
    content: str
    content_hash: str | None = None
    fetched_at: datetime = Field(default_factory=_utc_now)


class Intel(BaseModel):
    """处理输出."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    raw_id: str
    competitor: str
    intel_type: Literal[
        "new_feature",
        "version_update",
        "pricing_change",
        "ui_change",
    ]
    title: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_url: HttpUrl
    discovered_at: datetime = Field(default_factory=_utc_now)
    status: Literal["pending", "pushed", "rejected"] = "pending"
    dedup_status: Literal["ok", "unchecked"] = "ok"
    extracted_by: Literal["llm", "rule_fallback"] = "llm"


class Weekly(BaseModel):
    """周报输出."""

    week_start: str
    week_end: str
    content: str
    generated_at: datetime = Field(default_factory=_utc_now)
