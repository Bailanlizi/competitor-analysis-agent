"""Tests for pluggable LLM provider factory."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from config.settings import LLMConfig, load_settings, reset_settings
from infra.llm.factory import (
    LLM_API_KEY_FALLBACK_ENV,
    LLM_BASE_URL_ENV,
    PRESETS,
    create_provider,
    get_provider,
    resolve_llm_credentials,
    reset_provider,
)


def test_llm_defaults():
    cfg = LLMConfig()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.timeout == 30


def test_deepseek_preset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_settings()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    data = yaml.safe_load(Path("config/competitors.yaml").read_text(encoding="utf-8"))
    data["llm"] = {"provider": "deepseek", "model": "deepseek-chat"}
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    settings = load_settings(str(path))
    provider = create_provider(settings.llm)
    assert provider.provider_name == "deepseek"
    assert provider.model_name == "deepseek-chat"
    assert provider.is_available()
    assert PRESETS["deepseek"].base_url == "https://api.deepseek.com"


def test_llm_api_key_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(LLM_API_KEY_FALLBACK_ENV, "fallback-key")
    creds = resolve_llm_credentials(LLMConfig(provider="openai", model="gpt-4o-mini"))
    assert creds.api_key == "fallback-key"
    provider = create_provider(LLMConfig(provider="openai", model="gpt-4o-mini"))
    assert provider.is_available()


def test_llm_base_url_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(LLM_BASE_URL_ENV, "https://custom.example.com/v1")
    creds = resolve_llm_credentials(LLMConfig(provider="qwen", model="qwen-plus"))
    assert creds.base_url == "https://custom.example.com/v1"


def test_custom_unavailable_without_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(LLM_BASE_URL_ENV, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = create_provider(LLMConfig(provider="custom", model="my-model"))
    assert not provider.is_available()


def test_custom_available_with_base_url_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(LLM_BASE_URL_ENV, "https://gateway.example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider = create_provider(LLMConfig(provider="custom", model="my-model"))
    assert provider.is_available()


def test_ollama_available_without_api_key():
    provider = create_provider(LLMConfig(provider="ollama", model="qwen2.5:7b"))
    assert provider.is_available()


def test_get_provider_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_settings()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    data = yaml.safe_load(Path("config/competitors.yaml").read_text(encoding="utf-8"))
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    load_settings(str(path))

    first = get_provider()
    second = get_provider()
    assert first is second

    reset_provider()
    third = get_provider()
    assert third is not first


def test_openai_unavailable_without_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(LLM_API_KEY_FALLBACK_ENV, raising=False)
    provider = create_provider(LLMConfig())
    assert not provider.is_available()
