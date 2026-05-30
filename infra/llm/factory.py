"""LLM provider factory and preset registry."""

from __future__ import annotations

from dataclasses import dataclass

from config.settings import LLMConfig, get_settings
from infra.llm.base import LLMProvider
from infra.llm.providers.openai_compat import build_openai_compat_provider

_PROVIDER: LLMProvider | None = None


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str | None
    api_key_env: str
    require_api_key: bool = True


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


def create_provider(cfg: LLMConfig) -> LLMProvider:
    preset = PRESETS[cfg.provider]
    api_key_env = cfg.api_key_env or preset.api_key_env
    base_url = cfg.base_url or preset.base_url
    return build_openai_compat_provider(
        provider_name=cfg.provider,
        model=cfg.model,
        api_key_env=api_key_env,
        base_url=base_url,
        timeout=cfg.timeout,
    )


def get_provider() -> LLMProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = create_provider(get_settings().llm)
    return _PROVIDER


def reset_provider() -> None:
    global _PROVIDER
    _PROVIDER = None
