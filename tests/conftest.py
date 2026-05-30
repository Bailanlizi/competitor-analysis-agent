"""Pytest fixtures for isolated DB and filesystem paths."""

from __future__ import annotations

from pathlib import Path

import pytest

import infra.db as db_module
from config.settings import reset_settings


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated database, storage, and docs directories."""
    reset_settings()

    db_path = tmp_path / "data" / "intel.db"
    storage = tmp_path / "storage" / "raw"
    docs_pricing = tmp_path / "docs" / "pricing-history"
    docs_changelog = tmp_path / "docs" / "changelogs"
    reports = tmp_path / "reports" / "weekly"
    logs = tmp_path / "logs"

    for d in (storage, docs_pricing, docs_changelog, reports, logs):
        d.mkdir(parents=True)

    db_module.configure_paths(
        db_path=str(db_path),
        storage_raw_root=storage,
        docs_pricing_root=docs_pricing,
        docs_changelog_root=docs_changelog,
        reports_weekly_root=reports,
    )
    db_module.init_db(str(db_path))

    monkeypatch.chdir(tmp_path)

    yield {
        "db_path": db_path,
        "storage": storage,
        "docs_pricing": docs_pricing,
        "docs_changelog": docs_changelog,
        "reports": reports,
        "logs": logs,
        "root": tmp_path,
    }

    reset_settings()
