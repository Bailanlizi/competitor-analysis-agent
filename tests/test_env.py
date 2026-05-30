"""Tests for config/env.py dotenv loading."""

from __future__ import annotations

import os

from config.env import load_env, reset_env_loaded


def test_load_env_reads_file(tmp_path, monkeypatch):
    reset_env_loaded()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=from-dotenv\n", encoding="utf-8")

    assert load_env() is True
    assert os.environ.get("DASHSCOPE_API_KEY") == "from-dotenv"


def test_load_env_idempotent(tmp_path, monkeypatch):
    reset_env_loaded()
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LLM_API_KEY=first\n", encoding="utf-8")
    assert load_env() is True

    (tmp_path / ".env").write_text("LLM_API_KEY=second\n", encoding="utf-8")
    assert load_env() is False
    assert os.environ.get("LLM_API_KEY") == "first"
