"""Tests for pluggable LLM provider factory."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from config.settings import LLMConfig, load_settings, reset_settings
from infra.llm.factory import PRESETS, create_provider, get_provider, reset_provider


def test_llm_defaults():
    cfg = LLMConfig()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.timeout == 30


def test_custom_provider_requires_base_url():
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(provider="custom", model="my-model")
    assert "base_url" in str(exc_info.value)


def test_azure_provider_requires_base_url():
    with pytest.raises(ValidationError) as exc_info:
        LLMConfig(provider="azure", model="gpt-4o")
    assert "base_url" in str(exc_info.value)


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


def test_ollama_available_without_api_key():
    provider = create_provider(LLMConfig(provider="ollama", model="qwen2.5:7b"))
    assert provider.is_available()


def test_get_provider_singleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_settings()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
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
    provider = create_provider(LLMConfig())
    assert not provider.is_available()
