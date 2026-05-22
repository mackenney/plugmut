"""End-to-end tests for mutmut-extras plugin operators."""

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
from mutmut.plugin_manager import reset_plugin_manager

import mutmut

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
    # Builtins alone produce ~28 mutations on the e2e_project; extras add ~18 more
    assert total > 28, f"Expected >28 mutations with plugins, got {total}"


def test_plugin_mutations_are_killed(e2e_results):
    """Plugin-generated mutations for key functions should be killed (exit_code == 1)."""
    killed_keys = {k for k, v in e2e_results.items() if v == 1}

    # Original functions + new operator target functions
    functions_to_check = [
        "safe_divide",
        "middle_elements",
        "classify",
        "build_report",
        "generate_evens",
        "positive_values",
        "greet",
        "paginate",
        "first_come_first_served",
        "has_prefix",
        "clean_input",
        "compute_difference",
        "last_index",
        "check_numeric",
        "safe_parse",
        "resilient_process",
    ]
    for fn_name in functions_to_check:
        fn_killed = [k for k in killed_keys if fn_name in k]
        assert fn_killed, (
            f"Expected at least one killed mutant for '{fn_name}', "
            f"but none found. All keys: {sorted(k for k in e2e_results if fn_name in k)}"
        )


def test_no_plugin_crashes(e2e_results):
    """No mutant should produce a negative exit code (segfault/crash)."""
    # 0=survived, 1=killed, 5=skipped (no tests collected), 33=suspicious (timeout)
    valid_exit_codes = {0, 1, 5, 33}
    for key, exit_code in e2e_results.items():
        assert exit_code in valid_exit_codes, (
            f"Mutant '{key}' has unexpected exit code {exit_code}. Expected one of {valid_exit_codes}"
        )


def test_new_operator_targets_have_mutations(e2e_results):
    """Each new operator target function should have at least one mutation."""
    new_targets = [
        "build_report",
        "generate_evens",
        "positive_values",
        "Dog",
        "greet",
        "paginate",
        "first_come_first_served",
        "has_prefix",
        "clean_input",
        "compute_difference",
        "last_index",
        "check_numeric",
        "safe_parse",
        "resilient_process",
    ]
    for target in new_targets:
        target_mutations = [k for k in e2e_results if target in k]
        assert target_mutations, f"No mutations found for '{target}'. All keys: {sorted(e2e_results.keys())}"


def test_baseline_comparison():
    """Plugins should produce strictly more mutations than builtins alone."""
    os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    try:
        reset_plugin_manager()
        reset_plugin_operators()
        baseline_results = run_mutmut_on_e2e_project()
    finally:
        del os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"]
        reset_plugin_manager()
        reset_plugin_operators()

    plugin_results = run_mutmut_on_e2e_project()

    baseline_count = len(baseline_results)
    plugin_count = len(plugin_results)

    assert plugin_count > baseline_count, (
        f"Plugin run ({plugin_count} mutations) should produce more mutations "
        f"than baseline ({baseline_count} mutations)"
    )
