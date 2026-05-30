"""LLM provider factory and preset registry."""

from __future__ import annotations

import os
from dataclasses import dataclass

from config.settings import LLMConfig, get_settings
from infra.llm.base import LLMProvider
from infra.llm.providers.openai_compat import OpenAICompatProvider
from infra.log import get_logger, mask_webhook

logger = get_logger(__name__)

_PROVIDER: LLMProvider | None = None

LLM_BASE_URL_ENV = "LLM_BASE_URL"
LLM_API_KEY_FALLBACK_ENV = "LLM_API_KEY"


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str | None
    api_key_env: str
    require_api_key: bool = True


@dataclass(frozen=True)
class ResolvedLLMCredentials:
    api_key_env: str
    api_key: str
    base_url: str | None


PRESETS: dict[str, ProviderPreset] = {
    "openai": ProviderPreset(base_url=None, api_key_env="OPENAI_API_KEY"),
    "deepseek": ProviderPreset(
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
    ),
    "qwen": ProviderPreset(
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
    ),
    "moonshot": ProviderPreset(
        base_url="https://api.moonshot.cn/v1",
        api_key_env="MOONSHOT_API_KEY",
    ),
    "zhipu": ProviderPreset(
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZHIPU_API_KEY",
    ),
    "ollama": ProviderPreset(
        base_url="http://localhost:11434/v1",
        api_key_env="",
        require_api_key=False,
    ),
    "azure": ProviderPreset(base_url=None, api_key_env="AZURE_OPENAI_API_KEY"),
    "custom": ProviderPreset(base_url=None, api_key_env="OPENAI_API_KEY"),
}


def resolve_llm_credentials(cfg: LLMConfig) -> ResolvedLLMCredentials:
    preset = PRESETS[cfg.provider]
    api_key = ""
    if preset.api_key_env:
        api_key = os.environ.get(preset.api_key_env, "") or os.environ.get(
            LLM_API_KEY_FALLBACK_ENV, ""
        )
    base_url = os.environ.get(LLM_BASE_URL_ENV) or preset.base_url
    return ResolvedLLMCredentials(
        api_key_env=preset.api_key_env,
        api_key=api_key,
        base_url=base_url or None,
    )


def log_llm_config(cfg: LLMConfig) -> None:
    """Log LLM readiness after settings and .env are loaded."""
    creds = resolve_llm_credentials(cfg)
    preset = PRESETS[cfg.provider]
    api_key_configured = preset.require_api_key and bool(creds.api_key)
    if not preset.require_api_key:
        api_key_configured = True

    logger.info(
        "llm_config_ready",
        provider=cfg.provider,
        model=cfg.model,
        api_key_env=creds.api_key_env or None,
        api_key_configured=api_key_configured,
        base_url=mask_webhook(creds.base_url or ""),
    )

    if cfg.provider in ("custom", "azure") and not creds.base_url:
        logger.error(
            "llm_base_url_missing",
            provider=cfg.provider,
            hint=f"Set {LLM_BASE_URL_ENV} in .env",
        )
    elif preset.require_api_key and not creds.api_key:
        logger.warning(
            "llm_api_key_missing",
            provider=cfg.provider,
            api_key_env=creds.api_key_env or LLM_API_KEY_FALLBACK_ENV,
        )


def create_provider(cfg: LLMConfig) -> LLMProvider:
    preset = PRESETS[cfg.provider]
    creds = resolve_llm_credentials(cfg)
    return OpenAICompatProvider(
        provider_name=cfg.provider,
        model=cfg.model,
        api_key=creds.api_key or None,
        base_url=creds.base_url,
        timeout=cfg.timeout,
        require_api_key=preset.require_api_key,
    )


def get_provider() -> LLMProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = create_provider(get_settings().llm)
    return _PROVIDER


def reset_provider() -> None:
    global _PROVIDER
    _PROVIDER = None
