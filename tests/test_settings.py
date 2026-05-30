"""Tests for SPEC-2026-050 configuration (AC-1, AC-2, AC-3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from config.settings import load_settings, reset_settings


@pytest.fixture
def valid_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "competitors.yaml"
    path.write_text(
        Path("config/competitors.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def test_ac1_valid_config(valid_yaml: Path):
    reset_settings()
    settings = load_settings(str(valid_yaml))
    assert len(settings.competitors) == 3
    assert settings.interval_minutes == 60
    assert settings.cold_start_days == 7
    assert settings.llm.provider == "qwen"
    assert settings.llm.model == "qwen-plus"


def test_ac2_missing_sources(tmp_path: Path):
    reset_settings()
    data = yaml.safe_load(Path("config/competitors.yaml").read_text(encoding="utf-8"))
    del data["competitors"][1]["sources"]
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_settings(str(path))
    assert "sources" in str(exc_info.value)


def test_ac3_interval_minutes_boundary(tmp_path: Path):
    reset_settings()
    data = yaml.safe_load(Path("config/competitors.yaml").read_text(encoding="utf-8"))
    data["interval_minutes"] = 10
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_settings(str(path))
    assert "interval_minutes" in str(exc_info.value)


def test_file_not_found(tmp_path: Path):
    reset_settings()
    with pytest.raises(FileNotFoundError):
        load_settings(str(tmp_path / "missing.yaml"))


def test_llm_invalid_provider(tmp_path: Path):
    reset_settings()
    data = yaml.safe_load(Path("config/competitors.yaml").read_text(encoding="utf-8"))
    data["llm"] = {"provider": "unknown_vendor", "model": "x"}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")

    with pytest.raises(ValidationError) as exc_info:
        load_settings(str(path))
    assert "provider" in str(exc_info.value)
