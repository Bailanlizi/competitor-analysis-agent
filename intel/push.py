"""Push gateway for Feishu webhook (SPEC-2026-030)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

import infra.db as db
from config.settings import AppSettings
from infra.log import get_logger, mask_webhook
from models import Intel

logger = get_logger(__name__)

FAILED_PUSH_PATH = Path("data/failed_push.txt")

TYPE_LABELS = {
    "new_feature": "新功能",
    "version_update": "版本更新",
    "pricing_change": "定价调整",
    "ui_change": "UI变化",
}


def should_push(intel: Intel) -> bool:
    if intel.confidence >= 0.8:
        return True
    if intel.intel_type == "new_feature" and intel.extracted_by == "llm":
        return True
    return False


def resolve_webhook(settings: AppSettings) -> str:
    if settings.feishu_webhook:
        return settings.feishu_webhook
    return settings.dingtalk_webhook or ""


def build_feishu_message(intel: Intel) -> dict:
    dedup_tag = " [未去重]" if intel.dedup_status == "unchecked" else ""
    confidence_tag = f"置信度: {intel.confidence:.0%}"
    type_label = TYPE_LABELS.get(intel.intel_type, intel.intel_type)
    text = (
        f"🔔 **{intel.competitor}** | {type_label}\n\n"
        f"**{intel.title}**{dedup_tag}\n\n"
        f"{intel.summary}\n\n"
        f"{confidence_tag}\n"
        f"[查看来源]({intel.source_url})"
    )
    return {"msg_type": "text", "content": {"text": text}}


def _is_feishu_success(resp: httpx.Response) -> bool:
    if resp.status_code != 200:
        return False
    try:
        data = resp.json()
        if data.get("code") == 0:
            return True
    except Exception:
        pass
    body = resp.text
    return '"StatusCode":0' in body or '"ok"' in body


def _append_failed_push_txt(intel: Intel, error: str) -> None:
    FAILED_PUSH_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | {intel.competitor} | {intel.title} | {error}\n"
    with FAILED_PUSH_PATH.open("a", encoding="utf-8") as f:
        f.write(line)


async def _fallback_local(intel: Intel, reason: str) -> None:
    logger.warning("webhook_not_configured", webhook=mask_webhook(""))
    _append_failed_push_txt(intel, reason)
    db.save_failed_push(intel.id, "", reason)


@retry(stop=stop_after_attempt(2), wait=wait_fixed(5), reraise=True)
async def _post_webhook(webhook: str, message: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook, json=message)
        if resp.status_code != 200:
            resp.raise_for_status()
        if not _is_feishu_success(resp):
            raise ValueError(f"webhook business error: {resp.text[:200]}")
        return resp


async def _send_with_retry(webhook: str, message: dict, intel: Intel) -> bool:
    try:
        await _post_webhook(webhook, message)
        db.update_intel_status(intel.id, "pushed")
        logger.info("pushed", intel_id=intel.id, webhook=mask_webhook(webhook))
        return True
    except Exception as exc:
        error = str(exc)
        logger.error("push_failed", intel_id=intel.id, error=error)
        db.save_failed_push(intel.id, webhook, error)
        _append_failed_push_txt(intel, error)
        return False


async def push(intel: Intel, webhook: str) -> bool:
    if not should_push(intel):
        return False

    if not webhook:
        await _fallback_local(intel, "webhook_not_configured")
        return False

    message = build_feishu_message(intel)
    return await _send_with_retry(webhook, message, intel)


async def push_weekly_report(content: str, webhook: str) -> bool:
    if not webhook:
        logger.warning("webhook_not_configured")
        return False
    text = content[:4000]
    message = {"msg_type": "text", "content": {"text": text}}
    try:
        await _post_webhook(webhook, message)
        return True
    except Exception as exc:
        logger.error("push_failed", error=str(exc), report=True)
        return False
