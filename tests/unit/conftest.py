"""Auto-fixtures for unit tests - isolate AppSettings from local .env."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Clear BRAIN_* env vars and chdir to a clean tmp dir.

    Prevents AppSettings from picking up a local .env file during unit tests.
    """
    for key in list(os.environ):
        if key.startswith("BRAIN_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
