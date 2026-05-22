"""End-to-end tests: dedup (and extras+dedup) through a real _run() call."""

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from mutmut.__main__ import SourceFileMutationData
from mutmut.__main__ import _run
from mutmut.__main__ import ensure_config_loaded
from mutmut.__main__ import walk_source_files
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_dedup.plugin import mutmut_filter_mutations as dedup_filter

import mutmut

E2E_PROJECT = (Path(__file__).parent.parent.parent / "plugmut-extras" / "e2e_project").resolve()

VALID_EXIT_CODES = {0, 1, 5, 33}


@contextmanager
def change_cwd(path):
    old = Path.cwd().resolve()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _collect_results(project_path: Path) -> dict[str, int | None]:
    results: dict[str, int | None] = {}
    with change_cwd(project_path):
        ensure_config_loaded()
        assert mutmut.config is not None
        for p in walk_source_files():
            if mutmut.config.should_ignore_for_mutation(p):
                continue
            data = SourceFileMutationData(path=p)
            data.load()
            results.update(data.exit_code_by_key)
    return results


def _run_with_plugins(register_fn) -> dict[str, int | None]:
    """Reset state, register plugins via register_fn, run mutmut, return results."""
    os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    reset_plugin_manager()
    reset_plugin_operators()
    register_fn()
    mutmut._reset_globals()
    shutil.rmtree(E2E_PROJECT / "mutants", ignore_errors=True)
    with change_cwd(E2E_PROJECT):
        _run([], None)
    return _collect_results(E2E_PROJECT)


def _register_nothing():
    pass


def _register_dedup_only():
    pm = get_plugin_manager()

    class _Dedup:
        @staticmethod
        @hookimpl(trylast=True)
        def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
            return dedup_filter(filename=filename, mutations=mutations)

    pm.register(_Dedup())


def _register_extras_only():
    try:
        from mutmut_extras.plugin import mutmut_register_operators
    except ImportError:
        pytest.skip("mutmut-extras not installed")

    pm = get_plugin_manager()

    class _Extras:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return mutmut_register_operators()

    pm.register(_Extras())


def _register_extras_and_dedup():
    _register_extras_only()
    _register_dedup_only()


class TestDedupOnlyRun:
    """Dedup through a full _run() on the extras e2e_project."""

    @pytest.fixture(scope="class")
    def baseline_results(self):
        return _run_with_plugins(_register_nothing)

    @pytest.fixture(scope="class")
    def dedup_results(self):
        return _run_with_plugins(_register_dedup_only)

    def test_dedup_count_lte_baseline(self, baseline_results, dedup_results):
        assert len(dedup_results) <= len(baseline_results), (
            f"Dedup should not add mutations: {len(dedup_results)} > {len(baseline_results)}"
        )

    def test_dedup_produces_mutations(self, dedup_results):
        assert len(dedup_results) > 0, "Dedup run produced zero mutations"

    def test_all_exit_codes_valid(self, dedup_results):
        for key, code in dedup_results.items():
            assert code in VALID_EXIT_CODES, f"Mutant '{key}' has exit code {code}"


class TestExtrasAndDedupRun:
    """Extras + dedup combined through a full _run()."""

    @pytest.fixture(scope="class")
    def extras_only_results(self):
        return _run_with_plugins(_register_extras_only)

    @pytest.fixture(scope="class")
    def combined_results(self):
        return _run_with_plugins(_register_extras_and_dedup)

    def test_combined_count_lte_extras_only(self, extras_only_results, combined_results):
        assert len(combined_results) <= len(extras_only_results), (
            f"Dedup should reduce or maintain: {len(combined_results)} > {len(extras_only_results)}"
        )

    def test_combined_produces_more_than_builtins(self, combined_results):
        assert len(combined_results) > 20, f"Expected >20 mutations after extras+dedup, got {len(combined_results)}"

    def test_all_exit_codes_valid(self, combined_results):
        for key, code in combined_results.items():
            assert code in VALID_EXIT_CODES, f"Mutant '{key}' has exit code {code}"

    def test_no_crashes(self, combined_results):
        crashed = {k: v for k, v in combined_results.items() if v is not None and v < 0}
        assert not crashed, f"Mutants crashed: {crashed}"

    def test_key_functions_have_mutations(self, combined_results):
        """Core functions should still have mutations after dedup filtering."""
        for fn_name in ["safe_divide", "classify", "build_report", "compute_difference"]:
            fn_mutations = [k for k in combined_results if fn_name in k]
            assert fn_mutations, f"No mutations survived dedup for '{fn_name}'"
