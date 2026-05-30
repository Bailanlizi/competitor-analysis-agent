"""Weekly report factory (SPEC-2026-040)."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

import infra.db as db
import infra.llm as llm
from config.settings import AppSettings, CompetitorConfig, get_settings
from infra.log import get_logger
from infra.utils import get_last_week_range, utc_now_iso
from intel import push
from models import Intel, Weekly

logger = get_logger(__name__)

TYPE_ORDER = {
    "new_feature": 0,
    "version_update": 1,
    "pricing_change": 2,
    "ui_change": 3,
}

TYPE_LABELS = {
    "new_feature": "新功能",
    "version_update": "版本更新",
    "pricing_change": "定价调整",
    "ui_change": "UI变化",
}


def fetch_weekly_intels(start_utc: str, end_utc: str) -> list[Intel]:
    return db.get_intel_for_weekly(start_utc, end_utc)


def group_by_competitor(
    intels: list[Intel],
    competitors: list[CompetitorConfig],
) -> dict[str, list[Intel]]:
    groups: dict[str, list[Intel]] = defaultdict(list)
    for intel in intels:
        groups[intel.competitor].append(intel)
    for comp in competitors:
        groups.setdefault(comp.id, [])
    return dict(groups)


def sort_intels(intels: list[Intel]) -> list[Intel]:
    return sorted(
        intels,
        key=lambda x: (TYPE_ORDER.get(x.intel_type, 99), -x.discovered_at.timestamp()),
    )


async def _ensure_summaries(groups: dict[str, list[Intel]]) -> None:
    for intels in groups.values():
        for intel in intels:
            if len(intel.summary) <= 10:
                intel.summary = await llm.generate_summary(intel)


def _competitor_name(competitor_id: str, competitors: list[CompetitorConfig]) -> str:
    for comp in competitors:
        if comp.id == competitor_id:
            return comp.name
    return competitor_id


def render_weekly_markdown(
    week_start: str,
    week_end: str,
    groups: dict[str, list[Intel]],
    competitors: list[CompetitorConfig],
    llm_summary: str | None,
    failed_pushes: list[dict],
) -> str:
    all_intels = [intel for intels in groups.values() for intel in intels]
    pushed_count = sum(1 for i in all_intels if i.status == "pushed")
    pending_count = sum(1 for i in all_intels if i.status == "pending")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# 竞品情报周报 {week_start} ~ {week_end}",
        "",
        f"> 生成时间：{generated_at}",
        f"> 本周共 {len(all_intels)} 条情报（已推送 {pushed_count} 条，待审核 {pending_count} 条）",
        "",
    ]

    if llm_summary:
        lines.extend(["## 本周总结", "", llm_summary, "", "---", ""])

    for comp in competitors:
        comp_intels = sort_intels(groups.get(comp.id, []))
        lines.append(f"## {comp.name}")
        lines.append("")
        if comp_intels:
            for intel in comp_intels:
                type_label = TYPE_LABELS.get(intel.intel_type, intel.intel_type)
                confidence_pct = int(intel.confidence * 100)
                lines.append(
                    f"- **[{type_label}]** {intel.title} — {intel.summary} "
                    f"[{confidence_pct}%] [来源]({intel.source_url})"
                )
        else:
            lines.append("本周无新情报。")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## 推送失败记录")
    lines.append("")
    if failed_pushes:
        for fp in failed_pushes:
            title = fp.get("title") or fp.get("intel_id", "")
            lines.append(f"- {fp.get('created_at', '')} | {title} | {fp.get('error_message', '')}")
    else:
        lines.append("无推送失败记录。")

    return "\n".join(lines)


async def generate_and_push(webhook: str, settings: AppSettings | None = None) -> Weekly:
    settings = settings or get_settings()
    week_start, week_end, start_utc, end_utc = get_last_week_range(settings.timezone)

    intels = fetch_weekly_intels(start_utc, end_utc)
    groups = group_by_competitor(intels, settings.competitors)
    await _ensure_summaries(groups)

    llm_summary = await llm.generate_weekly_summary(intels)
    failed_pushes = db.get_failed_pushes_enriched()
    content = render_weekly_markdown(
        week_start,
        week_end,
        groups,
        settings.competitors,
        llm_summary,
        failed_pushes,
    )

    weekly = Weekly(week_start=week_start, week_end=week_end, content=content)
    db.save_weekly_report(week_start, content)

    pushed = await push.push_weekly_report(content, webhook)
    if not pushed:
        logger.warning("weekly_push_failed", week_start=week_start)

    return weekly


async def job_weekly(settings: AppSettings | None = None) -> None:
    settings = settings or get_settings()
    webhook = push.resolve_webhook(settings)
    start = time.perf_counter()

    log_id = db.save_run_log(
        job_type="weekly",
        started_at=utc_now_iso(),
        status="running",
    )
    logger.info("job_start", type="weekly")

    try:
        weekly = await generate_and_push(webhook, settings)
        duration_ms = int((time.perf_counter() - start) * 1000)
        db.update_run_log(
            log_id,
            finished_at=utc_now_iso(),
            status="success",
            duration_ms=duration_ms,
        )
        logger.info(
            "job_end",
            type="weekly",
            status="success",
            duration_ms=duration_ms,
            week_start=weekly.week_start,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        db.update_run_log(
            log_id,
            finished_at=utc_now_iso(),
            status="failed",
            duration_ms=duration_ms,
        )
        logger.error("job_end", type="weekly", status="failed", error=str(exc))
        raise
