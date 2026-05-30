"""LLM extraction with retry and rule fallback (SPEC-2026-060 L3-6.2)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import openai
from jinja2 import Template
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from infra.log import get_logger
from models import Intel, RawDoc

logger = get_logger(__name__)

PROMPT_PATH = Path("prompts/v1/extract.j2")
SUMMARY_PROMPT_PATH = Path("prompts/v1/summary.j2")
WEEKLY_SUMMARY_PROMPT_PATH = Path("prompts/v1/weekly_summary.j2")
MODEL = "gpt-4o-mini"

TYPE_KEYWORDS = {
    "new_feature": ["新功能", "launch", "introducing", "new feature", "发布"],
    "version_update": ["版本", "version", "update", "release", "changelog"],
    "pricing_change": ["定价", "价格", "pricing", "price", "plan"],
    "ui_change": ["界面", "ui", "design", "redesign", "交互"],
}


def _rule_extract(raw: RawDoc) -> dict:
    text = (raw.title + " " + raw.content).lower()
    intel_type = "version_update"
    for itype, keywords in TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            intel_type = itype
            break
    return {
        "intel_type": intel_type,
        "title": raw.title[:50],
        "summary": raw.content[:100],
        "_source": "rule_fallback",
    }


def _render_prompt(raw: RawDoc) -> str:
    template_text = PROMPT_PATH.read_text(encoding="utf-8")
    template = Template(template_text)
    return template.render(
        competitor=raw.competitor,
        source_type=raw.source_type,
        title=raw.title,
        content=raw.content,
    )


def _get_client() -> AsyncOpenAI | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return AsyncOpenAI(api_key=api_key)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(
        (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError)
    ),
    reraise=True,
)
async def _llm_call(client: AsyncOpenAI, prompt: str) -> tuple[dict, int, int]:
    start = time.perf_counter()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You extract competitor intelligence. Return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        timeout=30,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    content = response.choices[0].message.content or "{}"
    usage = response.usage
    token_input = usage.prompt_tokens if usage else 0
    token_output = usage.completion_tokens if usage else 0
    logger.info(
        "llm_call",
        model=MODEL,
        duration_ms=duration_ms,
        token_input=token_input,
        token_output=token_output,
        status="success",
    )
    return json.loads(content), token_input, token_output


async def _llm_text_call(client: AsyncOpenAI, system: str, prompt: str, max_tokens: int = 500) -> str:
    start = time.perf_counter()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
        timeout=30,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    usage = response.usage
    logger.info(
        "llm_call",
        model=MODEL,
        duration_ms=duration_ms,
        token_input=usage.prompt_tokens if usage else 0,
        token_output=usage.completion_tokens if usage else 0,
        status="success",
    )
    return (response.choices[0].message.content or "").strip()


async def generate_summary(intel: Intel) -> str:
    """Generate short summary for weekly report; fallback to title."""
    client = _get_client()
    if client is None:
        return intel.title

    template = Template(SUMMARY_PROMPT_PATH.read_text(encoding="utf-8"))
    prompt = template.render(intel=intel)
    try:
        text = await _llm_text_call(
            client,
            "You write concise Chinese summaries for competitor intelligence.",
            prompt,
            max_tokens=200,
        )
        return text[:100] if text else intel.title
    except Exception as exc:
        logger.warning("llm_summary_failed", intel_id=intel.id, error=str(exc))
        return intel.title


async def generate_weekly_summary(intels: list[Intel]) -> str | None:
    """Generate weekly executive summary; return None on failure."""
    if not intels:
        return None

    client = _get_client()
    if client is None:
        return None

    template = Template(WEEKLY_SUMMARY_PROMPT_PATH.read_text(encoding="utf-8"))
    prompt = template.render(intels=intels[:50])
    try:
        text = await _llm_text_call(
            client,
            "You write concise Chinese weekly competitor intelligence summaries.",
            prompt,
            max_tokens=500,
        )
        return text[:300] if text else None
    except Exception as exc:
        logger.warning("llm_weekly_summary_failed", error=str(exc))
        return None


async def extract(raw: RawDoc) -> dict:
    """Extract structured intel via LLM; fall back to rules on failure."""
    client = _get_client()
    if client is None:
        logger.warning("llm_no_api_key", raw_id=raw.id)
        return _rule_extract(raw)

    prompt = _render_prompt(raw)
    try:
        result, token_in, token_out = await _llm_call(client, prompt)
        result.pop("_source", None)
        return result
    except (
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.APIError,
        json.JSONDecodeError,
        Exception,
    ) as exc:
        logger.warning("llm_fallback", raw_id=raw.id, error=str(exc))
        return _rule_extract(raw)
