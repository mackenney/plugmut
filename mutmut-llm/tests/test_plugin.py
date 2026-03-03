"""Tests for mutmut_llm.plugin."""

from __future__ import annotations

from unittest.mock import MagicMock

import libcst as cst
import pytest

from mutmut_llm.config import LLMConfig
from mutmut_llm.plugin import (
    mutmut_configure,
    mutmut_register_commands,
    mutmut_register_operators,
)


@pytest.fixture(autouse=True)
def _reset_plugin_state(monkeypatch):
    """Reset plugin module-level state between tests."""
    import mutmut_llm.plugin as mod

    monkeypatch.setattr(mod, "_llm_config", None)
    monkeypatch.setattr(mod, "_mutmut_paths", [])


class TestMutmutConfigure:
    def test_loads_llm_config(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        # Prevent find_pyproject from finding the workspace pyproject.toml
        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        mock_config = MagicMock()
        mock_config.paths_to_mutate = [tmp_path / "src"]
        mutmut_configure(config=mock_config)

        assert mod._llm_config is not None
        assert mod._llm_config.api_key == "test-key-123"

    def test_stores_paths_to_mutate(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        mock_config = MagicMock()
        mock_config.paths_to_mutate = [tmp_path / "src", tmp_path / "lib"]
        mutmut_configure(config=mock_config)

        assert len(mod._mutmut_paths) == 2

    def test_handles_config_without_paths(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        mock_config = MagicMock(spec=[])  # No attributes
        mutmut_configure(config=mock_config)

        assert mod._mutmut_paths == []


class TestMutmutRegisterOperators:
    def test_returns_operator_when_enabled(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_llm_config", LLMConfig(enabled=True))
        ops = mutmut_register_operators()
        assert len(ops) == 1
        node_type, func = ops[0]
        assert node_type is cst.FunctionDef

    def test_returns_empty_when_disabled(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_llm_config", LLMConfig(enabled=False))
        assert mutmut_register_operators() == []

    def test_returns_empty_when_no_config(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_llm_config", None)
        assert mutmut_register_operators() == []


class TestMutmutRegisterCommands:
    def test_registers_generate_command(self):
        import click

        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "generate")
        assert cmd is not None
        assert cmd.name == "generate"

    def test_generate_has_budget_option(self):
        import click

        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "generate")
        param_names = [p.name for p in cmd.params]
        assert "budget" in param_names
        assert "dry_run" in param_names
        assert "paths" in param_names
