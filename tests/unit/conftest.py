"""Auto-fixtures for unit tests - isolate tests from local BRAIN_* env."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Clear BRAIN_* env vars and chdir to a clean tmp dir.

    Prevents tests from picking up a developer's local environment.
    """
    for key in list(os.environ):
        if key.startswith("BRAIN_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
