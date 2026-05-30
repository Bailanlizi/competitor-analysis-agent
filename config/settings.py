"""Configuration loading and validation (SPEC-2026-050)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator

from config.env import load_env

SETTINGS: "AppSettings | None" = None


class SourceConfig(BaseModel):
    type: Literal["rss", "http", "search"]
    url: HttpUrl
    name: str = ""

    @field_validator("name")
    @classmethod
    def http_requires_name(cls, v: str, info) -> str:
        if info.data.get("type") == "http" and not v:
            raise ValueError("http 类型源必须提供 name 字段")
        return v


class CompetitorConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    enabled: bool = True
    sources: list[SourceConfig] = Field(min_length=1)


class SearchConfig(BaseModel):
    enabled: bool = False
    provider: Literal["serpapi", "bing", "google"] = "serpapi"
    api_key_env: str = "SEARCH_API_KEY"
    keywords: list[str] = []
    max_results: int = Field(default=5, ge=1, le=20)


LLMProviderName = Literal[
    "openai",
    "deepseek",
    "qwen",
    "moonshot",
    "zhipu",
    "ollama",
    "azure",
    "custom",
]


class LLMConfig(BaseModel):
    provider: LLMProviderName = "openai"
    model: str = "gpt-4o-mini"
    timeout: int = Field(default=30, ge=5, le=120)
    max_tokens_extract: int = Field(default=500, ge=1, le=4096)
    max_tokens_summary: int = Field(default=200, ge=1, le=4096)
    max_tokens_weekly: int = Field(default=500, ge=1, le=4096)


class AppSettings(BaseModel):
    interval_minutes: int = Field(default=60, ge=15, le=120)
    cold_start_days: int = Field(default=7, ge=1, le=30)
    timezone: str = "Asia/Shanghai"
    feishu_webhook: str = ""
    dingtalk_webhook: str = ""
    search: SearchConfig = Field(default_factory=SearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    competitors: list[CompetitorConfig] = Field(min_length=3, max_length=3)

    @field_validator("competitors")
    @classmethod
    def unique_ids(cls, v: list[CompetitorConfig]) -> list[CompetitorConfig]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("competitor id 必须唯一")
        return v


def load_settings(path: str = "config/competitors.yaml") -> AppSettings:
    """Load .env, validate YAML configuration, and return AppSettings."""
    load_env()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"config/competitors.yaml not found: {config_path}")

    try:
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ValueError(f"yaml parse error: {exc}") from exc

    if data is None:
        data = {}

    try:
        return AppSettings(**data)
    except ValidationError:
        raise


def get_settings(path: str = "config/competitors.yaml") -> AppSettings:
    """Lazy-loaded global settings singleton."""
    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings(path)
    return SETTINGS


def reset_settings() -> None:
    """Reset singleton (for tests)."""
    global SETTINGS
    SETTINGS = None
    from config.env import reset_env_loaded
    from infra.llm.factory import reset_provider

    reset_env_loaded()
    reset_provider()
