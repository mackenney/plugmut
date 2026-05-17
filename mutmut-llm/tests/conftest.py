"""Shared fixtures for mutmut-llm tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mutmut_llm.operators import reset_library


@pytest.fixture(autouse=True)
def _reset_plugin_state(monkeypatch):
    """Reset plugin module-level state between tests."""
    import mutmut_llm.plugin as mod

    monkeypatch.setattr(mod, "_llm_config", None)
    monkeypatch.setattr(mod, "_mutmut_paths", [])
    monkeypatch.setattr(mod, "_llm_mutant_names", set())
    monkeypatch.setattr(mod, "_current_run", None)
    monkeypatch.setattr(mod, "_library_instance", None)


@pytest.fixture(autouse=True)
def _clean_library():
    """Reset the in-memory cache index before each test."""
    reset_library()
    yield
    reset_library()


@pytest.fixture()
def cache_root(tmp_path) -> Path:
    return tmp_path / "cache"


def make_mock_response(
    mutations: list[dict],
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 200,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> MagicMock:
    """Create a mock Anthropic API response with usage metadata."""
    text_block = MagicMock()
    text_block.text = json.dumps(mutations)
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    return response


def make_async_mock_client(responses=None):
    """Create a mock AsyncAnthropic client.

    Args:
        responses: List of responses for messages.create. If None, returns empty mutations.
                   Can contain exceptions to simulate failures.
    """
    from unittest.mock import AsyncMock
    client = AsyncMock()
    if responses:
        client.messages.create = AsyncMock(side_effect=responses)
    else:
        client.messages.create = AsyncMock(return_value=make_mock_response([]))
    return client
