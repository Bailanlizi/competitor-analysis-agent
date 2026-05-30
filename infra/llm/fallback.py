"""Rule-based extraction fallback when LLM is unavailable."""

from __future__ import annotations

from models import RawDoc

TYPE_KEYWORDS = {
    "new_feature": ["新功能", "launch", "introducing", "new feature", "发布"],
    "version_update": ["版本", "version", "update", "release", "changelog"],
    "pricing_change": ["定价", "价格", "pricing", "price", "plan"],
    "ui_change": ["界面", "ui", "design", "redesign", "交互"],
}


def rule_extract(raw: RawDoc) -> dict:
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
