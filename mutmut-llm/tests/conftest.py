"""Shared fixtures for mutmut-llm tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mutmut_llm.operators import _reset_cache_index


@pytest.fixture(autouse=True)
def _reset_plugin_state(monkeypatch):
    """Reset plugin module-level state between tests."""
    import mutmut_llm.plugin as mod

    monkeypatch.setattr(mod, "_llm_config", None)
    monkeypatch.setattr(mod, "_mutmut_paths", [])
    monkeypatch.setattr(mod, "_llm_mutant_names", set())
    monkeypatch.setattr(mod, "_current_run", None)


@pytest.fixture(autouse=True)
def _clean_cache_index():
    """Reset the in-memory cache index before each test."""
    _reset_cache_index()
    yield
    _reset_cache_index()


@pytest.fixture()
def cache_root(tmp_path) -> Path:
    return tmp_path / "cache"
