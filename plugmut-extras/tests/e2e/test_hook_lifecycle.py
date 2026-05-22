"""Verify post_test and post_run hooks fire during a real _run() call."""

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from mutmut.__main__ import _run
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager

import mutmut

E2E_PROJECT = (Path(__file__).parent.parent.parent / "e2e_project").resolve()


@contextmanager
def change_cwd(path):
    old = Path.cwd().resolve()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class HookRecorder:
    def __init__(self):
        self.post_test_calls = []
        self.post_run_calls = []

    @hookimpl
    def mutmut_post_test(self, mutant_name, exit_code, status, duration):
        self.post_test_calls.append(
            {
                "mutant_name": mutant_name,
                "exit_code": exit_code,
                "status": status,
                "duration": duration,
            }
        )

    @hookimpl
    def mutmut_post_run(self, source_file_mutation_data):
        self.post_run_calls.append(source_file_mutation_data)


@pytest.fixture(scope="module")
def hook_run_results():
    """Run mutmut with extras + recording plugin, return the recorder."""
    os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    reset_plugin_manager()
    reset_plugin_operators()

    pm = get_plugin_manager()

    from mutmut_extras.plugin import mutmut_register_operators as extras_register

    class _Extras:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return extras_register()

    recorder = HookRecorder()
    pm.register(_Extras())
    pm.register(recorder)

    mutmut._reset_globals()
    mutants_path = E2E_PROJECT / "mutants"
    shutil.rmtree(mutants_path, ignore_errors=True)

    with change_cwd(E2E_PROJECT):
        _run([], None)

    yield recorder

    os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)
    reset_plugin_manager()
    reset_plugin_operators()


def test_post_test_fires(hook_run_results):
    """mutmut_post_test should fire at least once during _run()."""
    recorder = hook_run_results
    assert len(recorder.post_test_calls) > 0, "post_test hook never fired during _run()"


def test_post_test_calls_have_valid_fields(hook_run_results):
    """Each post_test call must have a non-empty mutant_name, int exit_code, valid status, non-negative duration."""
    recorder = hook_run_results
    for call in recorder.post_test_calls:
        assert isinstance(call["mutant_name"], str) and call["mutant_name"], (
            f"Invalid mutant_name: {call['mutant_name']}"
        )
        assert isinstance(call["exit_code"], int), f"exit_code not int: {call['exit_code']}"
        assert call["status"] in ("killed", "survived", "suspicious", "skipped"), f"Unknown status: {call['status']}"
        assert isinstance(call["duration"], float) and call["duration"] >= 0, f"Invalid duration: {call['duration']}"


def test_post_test_count_exceeds_baseline(hook_run_results):
    """With extras, post_test should fire more times than builtins-only baseline (~28)."""
    recorder = hook_run_results
    assert len(recorder.post_test_calls) > 28, (
        f"Expected >28 post_test calls (extras adds mutations), got {len(recorder.post_test_calls)}"
    )


def test_post_run_fires_once(hook_run_results):
    """mutmut_post_run should fire exactly once at the end of _run()."""
    recorder = hook_run_results
    assert len(recorder.post_run_calls) == 1, (
        f"post_run should fire exactly once, fired {len(recorder.post_run_calls)} times"
    )


def test_post_run_receives_mutation_data(hook_run_results):
    """mutmut_post_run should receive non-empty source_file_mutation_data."""
    recorder = hook_run_results
    data = recorder.post_run_calls[0]
    assert len(data) > 0, "post_run received empty source_file_mutation_data"
