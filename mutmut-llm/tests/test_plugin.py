"""Tests for mutmut_llm.plugin."""

from __future__ import annotations

from unittest.mock import MagicMock

import click
import libcst as cst

from mutmut_llm.cache import CacheEntry
from mutmut_llm.cache import CachedMutation
from mutmut_llm.config import LLMConfig
from mutmut_llm.plugin import (
    _extract_function_name,
    mutmut_configure,
    mutmut_mutations_created,
    mutmut_post_run,
    mutmut_post_test,
    mutmut_register_commands,
    mutmut_register_operators,
)
from mutmut_llm.storage import load_latest_run
from mutmut_llm.storage import new_run


class TestExtractFunctionName:
    def test_simple_function(self):
        assert _extract_function_name("x_foo__mutmut_1") == "foo"

    def test_with_module_prefix(self):
        assert _extract_function_name("some.module.x_bar__mutmut_3") == "bar"

    def test_with_class(self):
        assert (
            _extract_function_name("x\u01c1MyClass\u01c1method__mutmut_2")
            == "MyClass.method"
        )

    def test_with_class_and_module(self):
        assert (
            _extract_function_name("mod.x\u01c1Cls\u01c1do_thing__mutmut_5")
            == "Cls.do_thing"
        )


class TestMutmutConfigure:
    def test_loads_llm_config(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
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

        mock_config = MagicMock(spec=[])
        mutmut_configure(config=mock_config)

        assert mod._mutmut_paths == []

    def test_clears_llm_mutant_names(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)
        mod._llm_mutant_names.update({"x_foo__mutmut_1", "x_bar__mutmut_2"})

        mutmut_configure(config=MagicMock(spec=[]))

        assert mod._llm_mutant_names == set()

    def test_resets_cache_index(self, monkeypatch):
        import mutmut_llm.operators as ops_mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)
        ops_mod._cache_index = {"fake": "data"}

        mutmut_configure(config=MagicMock(spec=[]))

        assert ops_mod._cache_index is None

    def test_initializes_current_run(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        mutmut_configure(config=MagicMock(spec=[]))

        assert mod._current_run is not None
        assert mod._current_run.run_id is not None
        assert mod._current_run.results == []


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
        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "generate")
        assert cmd is not None
        assert cmd.name == "generate"

    def test_generate_has_budget_option(self):
        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "generate")
        param_names = [p.name for p in cmd.params]
        assert "budget" in param_names
        assert "dry_run" in param_names
        assert "paths" in param_names

    def test_registers_llm_status_command(self):
        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "llm-status")
        assert cmd is not None


class TestMutmutMutationsCreated:
    def test_identifies_llm_mutants(self, monkeypatch):
        """When cache has 2 LLM mutations for 'foo', the last 2 mutants for that function are LLM."""
        import mutmut_llm.plugin as mod

        cache_entries = [
            CacheEntry(
                function_name="foo",
                file_path="src/mod.py",
                source_hash="abc123",
                mutations=[
                    CachedMutation("code1", "d1"),
                    CachedMutation("code2", "d2"),
                ],
            )
        ]
        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: cache_entries
        )

        source_by_mutant_name = {
            "x_foo__mutmut_1": "",
            "x_foo__mutmut_2": "",
            "x_foo__mutmut_3": "",
            "x_foo__mutmut_4": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_by_mutant_name=source_by_mutant_name
        )

        assert "x_foo__mutmut_3" in mod._llm_mutant_names
        assert "x_foo__mutmut_4" in mod._llm_mutant_names
        assert "x_foo__mutmut_1" not in mod._llm_mutant_names
        assert "x_foo__mutmut_2" not in mod._llm_mutant_names

    def test_no_cache_entries_no_llm_mutants(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr("mutmut_llm.plugin.list_cache_entries", lambda: [])

        source_by_mutant_name = {"x_foo__mutmut_1": "", "x_foo__mutmut_2": ""}
        mutmut_mutations_created(
            filename="src/mod.py", source_by_mutant_name=source_by_mutant_name
        )

        assert mod._llm_mutant_names == set()

    def test_multiple_functions_mixed(self, monkeypatch):
        import mutmut_llm.plugin as mod

        cache_entries = [
            CacheEntry(
                function_name="bar",
                file_path="src/mod.py",
                source_hash="xyz",
                mutations=[CachedMutation("code1", "d1")],
            )
        ]
        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: cache_entries
        )

        source_by_mutant_name = {
            "x_foo__mutmut_1": "",
            "x_foo__mutmut_2": "",
            "x_bar__mutmut_1": "",
            "x_bar__mutmut_2": "",
            "x_bar__mutmut_3": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_by_mutant_name=source_by_mutant_name
        )

        # Only the last mutant for 'bar' should be LLM (1 LLM mutation)
        assert "x_bar__mutmut_3" in mod._llm_mutant_names
        assert "x_bar__mutmut_1" not in mod._llm_mutant_names
        assert "x_bar__mutmut_2" not in mod._llm_mutant_names
        # 'foo' has no cache entries
        assert "x_foo__mutmut_1" not in mod._llm_mutant_names
        assert "x_foo__mutmut_2" not in mod._llm_mutant_names

    def test_class_method_mutants_matched(self, monkeypatch):
        """Cache stores 'MyClass.method'; mutant names use ǁ separator. They must match."""
        import mutmut_llm.plugin as mod

        cache_entries = [
            CacheEntry(
                function_name="MyClass.method",
                file_path="src/mod.py",
                source_hash="abc",
                mutations=[CachedMutation("code1", "d1")],
            )
        ]
        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: cache_entries
        )

        source_by_mutant_name = {
            "x\u01c1MyClass\u01c1method__mutmut_1": "",
            "x\u01c1MyClass\u01c1method__mutmut_2": "",
            "x\u01c1MyClass\u01c1method__mutmut_3": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_by_mutant_name=source_by_mutant_name
        )

        assert "x\u01c1MyClass\u01c1method__mutmut_3" in mod._llm_mutant_names
        assert "x\u01c1MyClass\u01c1method__mutmut_1" not in mod._llm_mutant_names
        assert "x\u01c1MyClass\u01c1method__mutmut_2" not in mod._llm_mutant_names


class TestMutmutPostTest:
    def test_accumulates_results(self, monkeypatch):
        import mutmut_llm.plugin as mod

        run = new_run()
        monkeypatch.setattr(mod, "_current_run", run)
        monkeypatch.setattr(mod, "_llm_mutant_names", {"x_foo__mutmut_2"})

        mutmut_post_test(
            mutant_name="x_foo__mutmut_1", exit_code=1, status="killed", duration=0.3
        )
        mutmut_post_test(
            mutant_name="x_foo__mutmut_2", exit_code=0, status="survived", duration=0.5
        )

        assert len(run.results) == 2
        assert run.results[0].mutant_name == "x_foo__mutmut_1"
        assert run.results[0].is_llm is False
        assert run.results[0].status == "killed"
        assert run.results[1].mutant_name == "x_foo__mutmut_2"
        assert run.results[1].is_llm is True
        assert run.results[1].status == "survived"

    def test_no_run_does_not_crash(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_current_run", None)
        # Should not raise
        mutmut_post_test(
            mutant_name="x_foo__mutmut_1", exit_code=1, status="killed", duration=0.1
        )


class TestMutmutPostRun:
    def test_saves_run(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod
        from mutmut_llm import storage

        run = new_run()
        monkeypatch.setattr(mod, "_current_run", run)

        cache_root = tmp_path / "cache"
        monkeypatch.setattr(
            storage, "_runs_dir", lambda cache_root=None: cache_root / "runs"
        )
        monkeypatch.setattr(
            "mutmut_llm.plugin.save_run",
            lambda r: storage.save_run(r, cache_root=cache_root),
        )

        mutmut_post_run(source_file_mutation_data=[])

        assert run.completed_at is not None
        loaded = load_latest_run(cache_root=cache_root)
        assert loaded is not None
        assert loaded.run_id == run.run_id

    def test_no_run_does_not_crash(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_current_run", None)
        mutmut_post_run(source_file_mutation_data=[])


class TestFullLifecycle:
    """Integration test: configure -> mutations_created -> post_test x N -> post_run -> verify saved."""

    def test_full_lifecycle(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod

        cache_root = tmp_path / "cache"

        # Setup: mock config loading, cache entries, and storage path
        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        cache_entries = [
            CacheEntry(
                function_name="compute",
                file_path="src/calc.py",
                source_hash="h1",
                mutations=[CachedMutation("def compute(): return 1", "negate")],
            )
        ]
        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: cache_entries
        )

        # Redirect save_run to tmp_path
        original_save_run = (
            mod.save_run.__wrapped__ if hasattr(mod.save_run, "__wrapped__") else None
        )

        def patched_save_run(r):
            from mutmut_llm.storage import save_run as real_save

            return real_save(r, cache_root=cache_root)

        monkeypatch.setattr("mutmut_llm.plugin.save_run", patched_save_run)

        # 1. Configure
        mutmut_configure(config=MagicMock(spec=[]))
        assert mod._current_run is not None

        # 2. Mutations created (3 builtin + 1 LLM for compute)
        mutmut_mutations_created(
            filename="src/calc.py",
            source_by_mutant_name={
                "x_compute__mutmut_1": "",
                "x_compute__mutmut_2": "",
                "x_compute__mutmut_3": "",
                "x_compute__mutmut_4": "",
            },
        )
        assert "x_compute__mutmut_4" in mod._llm_mutant_names
        assert len(mod._llm_mutant_names) == 1

        # 3. Post-test for each mutant
        mutmut_post_test(
            mutant_name="x_compute__mutmut_1",
            exit_code=1,
            status="killed",
            duration=0.2,
        )
        mutmut_post_test(
            mutant_name="x_compute__mutmut_2",
            exit_code=1,
            status="killed",
            duration=0.3,
        )
        mutmut_post_test(
            mutant_name="x_compute__mutmut_3",
            exit_code=0,
            status="survived",
            duration=0.4,
        )
        mutmut_post_test(
            mutant_name="x_compute__mutmut_4",
            exit_code=1,
            status="killed",
            duration=0.5,
        )

        assert len(mod._current_run.results) == 4

        # 4. Post-run
        mutmut_post_run(source_file_mutation_data=[])
        assert mod._current_run.completed_at is not None

        # 5. Verify saved
        loaded = load_latest_run(cache_root=cache_root)
        assert loaded is not None
        assert loaded.run_id == mod._current_run.run_id
        assert len(loaded.results) == 4

        llm_results = [r for r in loaded.results if r.is_llm]
        builtin_results = [r for r in loaded.results if not r.is_llm]
        assert len(llm_results) == 1
        assert llm_results[0].mutant_name == "x_compute__mutmut_4"
        assert len(builtin_results) == 3
