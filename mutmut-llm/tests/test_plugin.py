"""Tests for mutmut_llm.plugin."""

from __future__ import annotations

from unittest.mock import MagicMock

import click
import libcst as cst
import pytest

from mutmut_llm.library import Library, LibraryEntry, source_hash
from mutmut_llm.config import LLMConfig
from mutmut_llm.plugin import (
    _extract_function_name,
    _llm_mutation_count_by_function,
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

    def test_resets_library(self, monkeypatch):
        import mutmut_llm.operators as ops_mod

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        mutmut_configure(config=MagicMock(spec=[]))

        assert ops_mod._library is not None  # new Library instance set

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

        cmd = cli.get_command(None, "generate")  # type: ignore[arg-type]
        assert cmd is not None
        assert cmd.name == "generate"

    def test_generate_has_budget_option(self):
        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "generate")  # type: ignore[arg-type]
        assert cmd is not None
        param_names = [p.name for p in cmd.params]
        assert "budget" in param_names
        assert "dry_run" in param_names
        assert "paths" in param_names

    def test_registers_llm_status_command(self):
        cli = click.Group()
        mutmut_register_commands(cli_group=cli)

        cmd = cli.get_command(None, "llm-status")  # type: ignore[arg-type]
        assert cmd is not None


class TestMutmutMutationsCreated:
    def _make_library_entry(self, function_name, file_path, src_hash, mutation_codes):
        return LibraryEntry(
            function_name=function_name,
            file_path=file_path,
            source_hash=src_hash,
            model="claude-sonnet-4-6",
            mutations=[{"mutated_code": c} for c in mutation_codes],
        )

    def test_identifies_llm_mutants(self, monkeypatch):
        """When library has 2 LLM mutations for 'foo', the last 2 mutants for that function are LLM."""
        import mutmut_llm.plugin as mod

        entry = self._make_library_entry("foo", "src/mod.py", "abc123", ["code1", "code2"])
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = [entry]
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        source_tag_by_mutant_name = {
            "x_foo__mutmut_1": "",
            "x_foo__mutmut_2": "",
            "x_foo__mutmut_3": "",
            "x_foo__mutmut_4": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_tag_by_mutant_name=source_tag_by_mutant_name
        )

        assert "x_foo__mutmut_3" in mod._llm_mutant_names
        assert "x_foo__mutmut_4" in mod._llm_mutant_names
        assert "x_foo__mutmut_1" not in mod._llm_mutant_names
        assert "x_foo__mutmut_2" not in mod._llm_mutant_names

    def test_no_library_entries_no_llm_mutants(self, monkeypatch):
        import mutmut_llm.plugin as mod

        mock_lib = MagicMock()
        mock_lib.list_all.return_value = []
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        source_tag_by_mutant_name = {"x_foo__mutmut_1": "", "x_foo__mutmut_2": ""}
        mutmut_mutations_created(
            filename="src/mod.py", source_tag_by_mutant_name=source_tag_by_mutant_name
        )

        assert mod._llm_mutant_names == set()

    def test_no_library_instance_no_llm_mutants(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_library_instance", None)

        source_tag_by_mutant_name = {"x_foo__mutmut_1": "", "x_foo__mutmut_2": ""}
        mutmut_mutations_created(
            filename="src/mod.py", source_tag_by_mutant_name=source_tag_by_mutant_name
        )

        assert mod._llm_mutant_names == set()

    def test_multiple_functions_mixed(self, monkeypatch):
        import mutmut_llm.plugin as mod

        entry = self._make_library_entry("bar", "src/mod.py", "xyz", ["code1"])
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = [entry]
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        source_tag_by_mutant_name = {
            "x_foo__mutmut_1": "",
            "x_foo__mutmut_2": "",
            "x_bar__mutmut_1": "",
            "x_bar__mutmut_2": "",
            "x_bar__mutmut_3": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_tag_by_mutant_name=source_tag_by_mutant_name
        )

        # Only the last mutant for 'bar' should be LLM (1 LLM mutation)
        assert "x_bar__mutmut_3" in mod._llm_mutant_names
        assert "x_bar__mutmut_1" not in mod._llm_mutant_names
        assert "x_bar__mutmut_2" not in mod._llm_mutant_names
        # 'foo' has no library entries
        assert "x_foo__mutmut_1" not in mod._llm_mutant_names
        assert "x_foo__mutmut_2" not in mod._llm_mutant_names

    def test_class_method_mutants_matched(self, monkeypatch):
        """Library stores 'MyClass.method'; mutant names use ǁ separator. They must match."""
        import mutmut_llm.plugin as mod

        entry = self._make_library_entry("MyClass.method", "src/mod.py", "abc", ["code1"])
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = [entry]
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        source_tag_by_mutant_name = {
            "x\u01c1MyClass\u01c1method__mutmut_1": "",
            "x\u01c1MyClass\u01c1method__mutmut_2": "",
            "x\u01c1MyClass\u01c1method__mutmut_3": "",
        }
        mutmut_mutations_created(
            filename="src/mod.py", source_tag_by_mutant_name=source_tag_by_mutant_name
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
        monkeypatch.setattr(mod, "_library_instance", None)

        cache_root = tmp_path / "cache"
        monkeypatch.setattr(
            storage, "_runs_dir", lambda cache_root=None: cache_root / "runs"  # type: ignore[operator]
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

    def test_aggregates_cost_from_library(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod
        from mutmut_llm import storage

        run = new_run()
        monkeypatch.setattr(mod, "_current_run", run)

        library_entries = [
            LibraryEntry(
                function_name="f1",
                file_path="a.py",
                source_hash="h1",
                model="m",
                mutations=[],
                metadata={"cost_usd": 0.01, "input_tokens": 1000, "output_tokens": 500},
            ),
            LibraryEntry(
                function_name="f2",
                file_path="b.py",
                source_hash="h2",
                model="m",
                mutations=[],
                metadata={"cost_usd": 0.02, "input_tokens": 2000, "output_tokens": 1000},
            ),
        ]
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = library_entries
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        cache_root = tmp_path / "cache"
        monkeypatch.setattr(
            "mutmut_llm.plugin.save_run",
            lambda r: storage.save_run(r, cache_root=cache_root),
        )

        mutmut_post_run(source_file_mutation_data=[])

        assert run.total_llm_cost_usd == pytest.approx(0.03)
        assert run.total_input_tokens == 3000
        assert run.total_output_tokens == 1500

    def test_no_run_does_not_crash(self, monkeypatch):
        import mutmut_llm.plugin as mod

        monkeypatch.setattr(mod, "_current_run", None)
        mutmut_post_run(source_file_mutation_data=[])


class TestMultiModelIndex:
    """Tests for multi-model library index and operator deduplication."""

    def test_index_merges_across_models(self, tmp_path):
        """Two models for the same function both appear under the same source_hash key."""
        from mutmut_llm.library import Library
        from mutmut_llm.operators import reset_library, set_library

        source = "def foo(): return 1"
        src_hash = source_hash(source)

        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="foo",
            file_path="src/mod.py",
            source=source,
            mutations=[{"mutated_code": "def foo(): return 2"}],
            model="claude-sonnet-4-6",
        )
        lib.add(
            function_name="foo",
            file_path="src/mod.py",
            source=source,
            mutations=[{"mutated_code": "def foo(): return 3"}],
            model="claude-opus-4-6",
        )
        set_library(lib)
        try:
            entries = lib.query(src_hash)
            assert len(entries) == 2
        finally:
            reset_library()

    def test_index_handles_identical_functions_different_files(self, tmp_path):
        """Identical functions in different files both appear under the same source_hash key."""
        from mutmut_llm.library import Library
        from mutmut_llm.operators import reset_library, set_library

        source = "def get_name(self):\n    return self.name"
        src_hash = source_hash(source)

        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="get_name",
            file_path="models/user.py",
            source=source,
            mutations=[{"mutated_code": "def get_name(self):\n    return ''"}],
            model="m",
        )
        lib.add(
            function_name="get_name",
            file_path="models/product.py",
            source=source,
            mutations=[{"mutated_code": "def get_name(self):\n    return None"}],
            model="m",
        )
        set_library(lib)
        try:
            entries = lib.query(src_hash)
            assert len(entries) == 2
        finally:
            reset_library()

    def test_operator_deduplicates_across_models(self, tmp_path):
        """operator_llm yields each unique mutation exactly once across models."""
        from mutmut_llm.library import Library
        from mutmut_llm.operators import operator_llm, reset_library, set_library

        source = "def foo():\n    return 1\n"
        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="foo",
            file_path="src/mod.py",
            source=source,
            mutations=[
                {"mutated_code": "def foo():\n    return 2\n"},
                {"mutated_code": "def foo():\n    return 3\n"},
            ],
            model="claude-sonnet-4-6",
        )
        lib.add(
            function_name="foo",
            file_path="src/mod.py",
            source=source,
            mutations=[
                {"mutated_code": "def foo():\n    return 2\n"},
                {"mutated_code": "def foo():\n    return 4\n"},
            ],
            model="claude-opus-4-6",
        )
        set_library(lib)
        try:
            node = cst.parse_module(source).body[0]
            assert isinstance(node, cst.FunctionDef)
            results = list(operator_llm(node))
            assert len(results) == 3
            result_codes = {cst.Module(body=[r]).code for r in results}
            assert "def foo():\n    return 2\n" in result_codes
            assert "def foo():\n    return 3\n" in result_codes
            assert "def foo():\n    return 4\n" in result_codes
        finally:
            reset_library()

    def test_operator_yields_from_multiple_files_same_hash(self, tmp_path):
        """Identical functions in different files both contribute mutations."""
        from mutmut_llm.library import Library
        from mutmut_llm.operators import operator_llm, reset_library, set_library

        source = "def get_name(self):\n    return self.name\n"
        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="get_name",
            file_path="models/user.py",
            source=source,
            mutations=[{"mutated_code": "def get_name(self):\n    return ''\n"}],
            model="claude-sonnet-4-6",
        )
        lib.add(
            function_name="get_name",
            file_path="models/product.py",
            source=source,
            mutations=[{"mutated_code": "def get_name(self):\n    return None\n"}],
            model="claude-sonnet-4-6",
        )
        set_library(lib)
        try:
            node = cst.parse_module(source).body[0]
            assert isinstance(node, cst.FunctionDef)
            results = list(operator_llm(node))
            assert len(results) == 2
        finally:
            reset_library()


class TestFullLifecycle:
    """Integration test: configure -> mutations_created -> post_test x N -> post_run -> verify saved."""

    def test_full_lifecycle(self, monkeypatch, tmp_path):
        import mutmut_llm.plugin as mod

        cache_root = tmp_path / "cache"

        monkeypatch.setattr("mutmut_llm.config.find_pyproject", lambda start=None: None)

        library_entries = [
            LibraryEntry(
                function_name="compute",
                file_path="src/calc.py",
                source_hash="h1",
                model="m",
                mutations=[{"mutated_code": "def compute(): return 1"}],
            )
        ]
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = library_entries

        def patched_save_run(r):
            from mutmut_llm.storage import save_run as real_save

            return real_save(r, cache_root=cache_root)

        monkeypatch.setattr("mutmut_llm.plugin.save_run", patched_save_run)

        # 1. Configure
        mutmut_configure(config=MagicMock(spec=[]))
        assert mod._current_run is not None

        # Inject mock library after configure
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        # 2. Mutations created (3 builtin + 1 LLM for compute)
        mutmut_mutations_created(
            filename="src/calc.py",
            source_tag_by_mutant_name={
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


class TestMutationCountConsistency:
    """_llm_mutation_count_by_function and operator_llm must agree after deduplication."""

    def test_count_matches_actual_yielded_mutations(self, monkeypatch, tmp_path):
        """Duplicate mutations across models are deduplicated in both count and operator."""
        from mutmut_llm.library import Library
        from mutmut_llm.operators import operator_llm, reset_library, set_library
        import mutmut_llm.plugin as mod

        source = "def compute():\n    return 42\n"
        shared_mutation = "def compute():\n    return 0\n"

        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="compute",
            file_path="src/calc.py",
            source=source,
            mutations=[{"mutated_code": shared_mutation}],
            model="claude-sonnet-4-6",
        )
        lib.add(
            function_name="compute",
            file_path="src/calc.py",
            source=source,
            mutations=[{"mutated_code": shared_mutation}],
            model="claude-opus-4-6",
        )
        set_library(lib)
        monkeypatch.setattr(mod, "_library_instance", lib)

        try:
            node = cst.parse_module(source).body[0]
            assert isinstance(node, cst.FunctionDef)
            actual_mutations = list(operator_llm(node))
            reported_count = _llm_mutation_count_by_function()
            assert len(actual_mutations) == 1
            assert reported_count["compute"] == 1
            assert reported_count["compute"] == len(actual_mutations)
        finally:
            reset_library()


class TestCostAggregationAcrossModels:
    """mutmut_post_run sums costs from ALL library entries across all models."""

    def test_post_run_sums_all_models_costs(self, monkeypatch, tmp_path):
        """Running with model B after model A: post_run reports A+B cost, not just B."""
        import mutmut_llm.plugin as mod
        from mutmut_llm import storage

        library_entries = [
            LibraryEntry(
                function_name="f",
                file_path="a.py",
                source_hash="h1",
                model="model-a",
                mutations=[],
                metadata={"cost_usd": 0.05, "input_tokens": 1000, "output_tokens": 500},
            ),
            LibraryEntry(
                function_name="f",
                file_path="a.py",
                source_hash="h1",
                model="model-b",
                mutations=[],
                metadata={"cost_usd": 0.10, "input_tokens": 2000, "output_tokens": 1000},
            ),
        ]
        mock_lib = MagicMock()
        mock_lib.list_all.return_value = library_entries
        monkeypatch.setattr(mod, "_library_instance", mock_lib)

        run = new_run()
        monkeypatch.setattr(mod, "_current_run", run)

        cache_root = tmp_path / "cache"
        monkeypatch.setattr(
            "mutmut_llm.plugin.save_run",
            lambda r: storage.save_run(r, cache_root=cache_root),
        )

        mutmut_post_run(source_file_mutation_data=[])

        assert run.total_llm_cost_usd == pytest.approx(0.15)
        assert run.total_input_tokens == 3000
        assert run.total_output_tokens == 1500
