"""LLM facade: extract, summaries, and rule fallback (SPEC-2026-060)."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from config.settings import get_settings
from infra.llm.factory import get_provider, reset_provider
from infra.llm.fallback import rule_extract
from infra.log import get_logger
from models import Intel, RawDoc

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/v1/extract.j2")
SUMMARY_PROMPT_PATH = Path("prompts/v1/summary.j2")
WEEKLY_SUMMARY_PROMPT_PATH = Path("prompts/v1/weekly_summary.j2")

__all__ = [
    "extract",
    "generate_summary",
    "generate_weekly_summary",
    "reset_provider",
]


def _render_extract_prompt(raw: RawDoc) -> str:
    template = Template(PROMPT_PATH.read_text(encoding="utf-8"))
    return template.render(
        competitor=raw.competitor,
        source_type=raw.source_type,
        title=raw.title,
        content=raw.content,
    )


async def extract(raw: RawDoc) -> dict:
    """Extract structured intel via LLM; fall back to rules on failure."""
    provider = get_provider()
    if not provider.is_available():
        logger.warning("llm_no_api_key", raw_id=raw.id, provider=provider.provider_name)
        return rule_extract(raw)

    llm_cfg = get_settings().llm
    prompt = _render_extract_prompt(raw)
    messages = [
        {
            "role": "system",
            "content": "You extract competitor intelligence. Return valid JSON only.",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        content, _usage = await provider.chat(
            messages,
            max_tokens=llm_cfg.max_tokens_extract,
            json_mode=True,
        )
        result = json.loads(content or "{}")
        result.pop("_source", None)
        return result
    except Exception as exc:
        logger.warning(
            "llm_fallback",
            raw_id=raw.id,
            provider=provider.provider_name,
            error=str(exc),
        )
        return rule_extract(raw)


async def generate_summary(intel: Intel) -> str:
    """Generate short summary for weekly report; fallback to title."""
    provider = get_provider()
    if not provider.is_available():
        return intel.title

    llm_cfg = get_settings().llm
    template = Template(SUMMARY_PROMPT_PATH.read_text(encoding="utf-8"))
    prompt = template.render(intel=intel)
    messages = [
        {
            "role": "system",
            "content": "You write concise Chinese summaries for competitor intelligence.",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        text, _usage = await provider.chat(
            messages,
            max_tokens=llm_cfg.max_tokens_summary,
            json_mode=False,
        )
        return text[:100] if text else intel.title
    except Exception as exc:
        logger.warning("llm_summary_failed", intel_id=intel.id, error=str(exc))
        return intel.title


async def generate_weekly_summary(intels: list[Intel]) -> str | None:
    """Generate weekly executive summary; return None on failure."""
    if not intels:
        return None

    provider = get_provider()
    if not provider.is_available():
        return None

    llm_cfg = get_settings().llm
    template = Template(WEEKLY_SUMMARY_PROMPT_PATH.read_text(encoding="utf-8"))
    prompt = template.render(intels=intels[:50])
    messages = [
        {
            "role": "system",
            "content": "You write concise Chinese weekly competitor intelligence summaries.",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        text, _usage = await provider.chat(
            messages,
            max_tokens=llm_cfg.max_tokens_weekly,
            json_mode=False,
        )
        return text[:300] if text else None
    except Exception as exc:
        logger.warning("llm_weekly_summary_failed", error=str(exc))
        return None
