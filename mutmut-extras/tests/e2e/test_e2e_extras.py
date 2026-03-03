"""End-to-end tests for mutmut-extras plugin operators."""

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

import mutmut
from mutmut.__main__ import (
    SourceFileMutationData,
    _run,
    ensure_config_loaded,
    walk_source_files,
)
from mutmut.plugin_manager import reset_plugin_manager

E2E_PROJECT = (Path(__file__).parent.parent.parent / "e2e_project").resolve()


@contextmanager
def change_cwd(path):
    old_cwd = Path.cwd().resolve()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def run_mutmut_on_e2e_project() -> dict[str, int | None]:
    """Run mutmut on the e2e project and return {mutant_key: exit_code}."""
    mutmut._reset_globals()

    mutants_path = E2E_PROJECT / "mutants"
    shutil.rmtree(mutants_path, ignore_errors=True)

    with change_cwd(E2E_PROJECT):
        _run([], None)

    results: dict[str, int | None] = {}
    with change_cwd(E2E_PROJECT):
        ensure_config_loaded()
        assert mutmut.config is not None
        for p in walk_source_files():
            if mutmut.config.should_ignore_for_mutation(p):
                continue
            data = SourceFileMutationData(path=p)
            data.load()
            results.update(data.exit_code_by_key)

    return results


@pytest.fixture(scope="module")
def e2e_results() -> dict[str, int | None]:
    """Run mutmut once for the module and cache results."""
    return run_mutmut_on_e2e_project()


def test_plugin_mutations_are_generated(e2e_results):
    """With plugins loaded, mutation count should exceed builtins-only baseline (~28)."""
    total = len(e2e_results)
    # Builtins alone produce ~28 mutations; with extras plugins we expect ~46+
    assert total > 28, f"Expected >28 mutations with plugins, got {total}"


def test_plugin_mutations_are_killed(e2e_results):
    """Plugin-generated mutations for key functions should be killed (exit_code == 1)."""
    killed_keys = {k for k, v in e2e_results.items() if v == 1}

    # Check that at least one mutation in each target function is killed
    functions_to_check = ["safe_divide", "middle_elements", "classify"]
    for fn_name in functions_to_check:
        fn_killed = [k for k in killed_keys if fn_name in k]
        assert fn_killed, (
            f"Expected at least one killed mutant for '{fn_name}', "
            f"but none found. All keys: {sorted(k for k in e2e_results if fn_name in k)}"
        )


def test_no_plugin_crashes(e2e_results):
    """No mutant should produce a negative exit code (segfault/crash)."""
    valid_exit_codes = {0, 1, 5, 33}
    for key, exit_code in e2e_results.items():
        assert exit_code in valid_exit_codes, (
            f"Mutant '{key}' has unexpected exit code {exit_code}. "
            f"Expected one of {valid_exit_codes}"
        )


def test_baseline_comparison():
    """Plugins should produce strictly more mutations than builtins alone."""
    os.environ["MUTMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        reset_plugin_manager()
        baseline_results = run_mutmut_on_e2e_project()
    finally:
        del os.environ["MUTMUT_DISABLE_PLUGIN_AUTOLOAD"]
        reset_plugin_manager()

    plugin_results = run_mutmut_on_e2e_project()

    baseline_count = len(baseline_results)
    plugin_count = len(plugin_results)

    assert plugin_count > baseline_count, (
        f"Plugin run ({plugin_count} mutations) should produce more mutations "
        f"than baseline ({baseline_count} mutations)"
    )
