"""End-to-end tests for the mutmut-llm plugin.

These tests make real API calls to the Anthropic API. They require
ANTHROPIC_API_KEY to be set. Skipped automatically if the key is missing.

Run with:
    uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/ -v
"""

from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

import libcst as cst
import pytest

import mutmut
from mutmut.__main__ import (
    SourceFileMutationData,
    _run,
    ensure_config_loaded,
    walk_source_files,
)
from mutmut.plugin_manager import reset_plugin_manager

from mutmut_llm.cache import list_cache_entries
from mutmut_llm.config import load_config
from mutmut_llm.operators import _reset_cache_index
from mutmut_llm.pipeline import run_generation
from mutmut_llm.validation import validate_mutation

E2E_PROJECT = (Path(__file__).parent.parent.parent / "e2e_project").resolve()
E2E_SRC = E2E_PROJECT / "src" / "tiny" / "__init__.py"

SKIP_NO_KEY = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@contextmanager
def change_cwd(path):
    old = Path.cwd().resolve()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


@pytest.fixture(autouse=True)
def _clean_e2e_state():
    """Clean caches and mutants before/after each test."""
    _reset_cache_index()

    mutants_path = E2E_PROJECT / "mutants"
    cache_path = E2E_PROJECT / ".mutmut-cache"
    lib_path = E2E_PROJECT / ".plugmut-llm"
    shutil.rmtree(mutants_path, ignore_errors=True)
    shutil.rmtree(cache_path, ignore_errors=True)
    shutil.rmtree(lib_path, ignore_errors=True)

    yield

    _reset_cache_index()
    shutil.rmtree(mutants_path, ignore_errors=True)
    shutil.rmtree(cache_path, ignore_errors=True)
    shutil.rmtree(lib_path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Generation tests (real API calls)
# ---------------------------------------------------------------------------


@SKIP_NO_KEY
class TestGeneration:
    """Test the generation pipeline against a real LLM."""

    def test_generate_creates_cache_entries(self):
        """mutmut generate populates the file cache with valid entries."""
        config = load_config(env=os.environ)
        assert config.is_configured

        with change_cwd(E2E_PROJECT):
            result = run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        assert result == 2, f"Expected 2 API calls (one per function), got {result}"

        entries = list_cache_entries(base_dir=E2E_PROJECT)
        assert len(entries) == 2, f"Expected 2 cache entries, got {len(entries)}"

        func_names = {e.function_name for e in entries}
        assert "fibonacci" in func_names
        assert "is_palindrome" in func_names

    def test_generated_mutations_are_valid_python(self):
        """Every cached mutation must be syntactically valid and not add imports."""
        config = load_config(env=os.environ)
        original_source = E2E_SRC.read_text()

        with change_cwd(E2E_PROJECT):
            run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        entries = list_cache_entries(base_dir=E2E_PROJECT)
        assert entries, "No cache entries generated"

        for entry in entries:
            for mutation in entry.mutations:
                err = validate_mutation(mutation.mutated_code, original_source)
                assert err is None, (
                    f"Mutation for {entry.function_name} failed validation: {err}\n"
                    f"Code: {mutation.mutated_code}"
                )

    def test_generated_mutations_contain_function_defs(self):
        """Every mutation must contain a FunctionDef matching the original name."""
        config = load_config(env=os.environ)

        with change_cwd(E2E_PROJECT):
            run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        entries = list_cache_entries(base_dir=E2E_PROJECT)
        for entry in entries:
            # The function name may be qualified (e.g. "Class.method") — take the bare name
            bare_name = entry.function_name.split(".")[-1]
            for mutation in entry.mutations:
                module = cst.parse_module(mutation.mutated_code)
                func_names = [
                    stmt.name.value
                    for stmt in module.body
                    if isinstance(stmt, cst.FunctionDef)
                ]
                assert bare_name in func_names, (
                    f"Mutation for {entry.function_name} doesn't contain expected "
                    f"function def '{bare_name}'. Found: {func_names}\n"
                    f"Code: {mutation.mutated_code}"
                )

    def test_generated_mutations_differ_from_original(self):
        """Mutations must actually change the code (not be equivalent to original)."""
        config = load_config(env=os.environ)
        original_source = E2E_SRC.read_text()
        original_module = cst.parse_module(original_source)

        # Extract original function sources
        original_funcs = {}
        for stmt in original_module.body:
            if isinstance(stmt, cst.FunctionDef):
                original_funcs[stmt.name.value] = original_module.code_for_node(stmt)

        with change_cwd(E2E_PROJECT):
            run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        entries = list_cache_entries(base_dir=E2E_PROJECT)
        for entry in entries:
            bare_name = entry.function_name.split(".")[-1]
            original_code = original_funcs.get(bare_name, "")
            for mutation in entry.mutations:
                assert mutation.mutated_code.strip() != original_code.strip(), (
                    f"Mutation for {entry.function_name} is identical to original"
                )

    def test_cache_skips_already_generated(self, capsys):
        """Running generate twice should skip already-cached functions."""
        config = load_config(env=os.environ)

        with change_cwd(E2E_PROJECT):
            run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )
            # Second run: should find cache hits
            result = run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        assert result == 0, "Second run should make 0 API calls (all cached)"
        output = capsys.readouterr().out
        assert "cached" in output


# ---------------------------------------------------------------------------
# Operator integration tests (uses pre-generated cache, no API calls)
# ---------------------------------------------------------------------------


class TestOperatorIntegration:
    """Test that cached LLM mutations are picked up by mutmut run."""

    def _prepopulate_cache(self):
        """Write known mutations into the cache for the e2e project.

        fibonacci: 3 mutations, all killed by existing tests.
        is_palindrome: 3 mutations — strip-removal survives, other two killed.
        """
        from mutmut_llm.library import Library

        source = E2E_SRC.read_text()
        module = cst.parse_module(source)

        func_sources: dict[str, str] = {}
        for stmt in module.body:
            if isinstance(stmt, cst.FunctionDef) and stmt.name.value in (
                "fibonacci",
                "is_palindrome",
            ):
                func_sources[stmt.name.value] = module.code_for_node(stmt)

        assert "fibonacci" in func_sources, "fibonacci not found in e2e source"
        assert "is_palindrome" in func_sources, "is_palindrome not found in e2e source"

        lib = Library(base_dir=E2E_PROJECT)
        lib.add(
            function_name="fibonacci",
            file_path="src/tiny/__init__.py",
            source=func_sources["fibonacci"],
            mutations=[
                {
                    "mutated_code": 'def fibonacci(n):\n    """Return the nth Fibonacci number."""\n    if n <= 0:\n        return 0\n    if n == 1:\n        return 0\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n',
                    "description": "change fib(1) base case from 1 to 0",
                },
                {
                    "mutated_code": 'def fibonacci(n):\n    """Return the nth Fibonacci number."""\n    if n < 0:\n        return 0\n    if n == 1:\n        return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n',
                    "description": "boundary: n < 0 instead of n <= 0",
                },
                {
                    "mutated_code": 'def fibonacci(n):\n    """Return the nth Fibonacci number."""\n    if n <= 0:\n        return 0\n    if n == 1:\n        return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return a\n',
                    "description": "return wrong accumulator",
                },
            ],
            model="test-manual",
        )
        lib.add(
            function_name="is_palindrome",
            file_path="src/tiny/__init__.py",
            source=func_sources["is_palindrome"],
            mutations=[
                {
                    "mutated_code": 'def is_palindrome(s):\n    """Check if a string is a palindrome (case-insensitive)."""\n    cleaned = s.lower()\n    return cleaned == cleaned[::-1]\n',
                    "description": "remove strip()",
                },
                {
                    "mutated_code": 'def is_palindrome(s):\n    """Check if a string is a palindrome (case-insensitive)."""\n    cleaned = s.strip()\n    return cleaned == cleaned[::-1]\n',
                    "description": "remove lower()",
                },
                {
                    "mutated_code": 'def is_palindrome(s):\n    """Check if a string is a palindrome (case-insensitive)."""\n    cleaned = s.lower().strip()\n    return cleaned != cleaned[::-1]\n',
                    "description": "logic inversion",
                },
            ],
            model="test-manual",
        )

    def _run_mutmut(self) -> dict[str, int | None]:
        """Run mutmut on the e2e project with plugins enabled."""
        mutmut._reset_globals()
        reset_plugin_manager()

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

    def test_llm_mutations_appear_in_results(self):
        """Pre-populated cache mutations should appear in mutmut run results."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        # There should be mutations for fibonacci
        fib_mutations = {k: v for k, v in results.items() if "fibonacci" in k}
        assert fib_mutations, (
            f"No fibonacci mutations found. All keys: {sorted(results.keys())}"
        )

        # Count total mutations — with LLM, there should be more than builtins alone
        total = len(results)
        assert total > 0

    def test_llm_mutation_is_killed(self):
        """The manually-crafted LLM mutation (fib(1)=0) should be killed by tests."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        fib_mutations = {k: v for k, v in results.items() if "fibonacci" in k}
        killed = {k for k, v in fib_mutations.items() if v == 1}
        assert killed, (
            f"Expected at least one killed fibonacci mutation. Results: {fib_mutations}"
        )

    def test_no_crashes(self):
        """No mutant should crash (negative exit code)."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        valid_codes = {0, 1, 5, 33}
        for key, code in results.items():
            assert code in valid_codes, f"Mutant '{key}' crashed with exit code {code}"

    def test_llm_mutations_cover_both_functions(self):
        """Cache entries exist for both fibonacci and is_palindrome."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        fib_mutations = {k: v for k, v in results.items() if "fibonacci" in k}
        pal_mutations = {k: v for k, v in results.items() if "is_palindrome" in k}
        assert fib_mutations, f"No fibonacci mutations. Keys: {sorted(results.keys())}"
        assert pal_mutations, (
            f"No is_palindrome mutations. Keys: {sorted(results.keys())}"
        )

    def test_surviving_mutation_detected(self):
        """At least one LLM mutation should survive (exit code 0)."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        survivors = {k: v for k, v in results.items() if v == 0}
        assert survivors, (
            f"Expected at least one surviving mutation (strip-removal). Results: {results}"
        )

    def test_killed_and_survived_counts(self):
        """Verify expected kill/survive split across all mutations."""
        self._prepopulate_cache()
        results = self._run_mutmut()

        killed = {k for k, v in results.items() if v == 1}
        survived = {k for k, v in results.items() if v == 0}

        # 5 killed LLM mutations + builtins; at least 1 survivor (strip-removal)
        assert len(killed) >= 5, f"Expected >=5 killed, got {len(killed)}: {killed}"
        assert len(survived) >= 1, (
            f"Expected >=1 survivor, got {len(survived)}: {survived}"
        )

    def test_more_mutations_than_builtins_alone(self):
        """With LLM cache populated, total mutations should exceed builtins-only count."""
        # Run without cache (builtins only)
        baseline_results = self._run_mutmut()
        baseline_count = len(baseline_results)

        # Clean mutants so mutmut regenerates mutations with the LLM cache
        shutil.rmtree(E2E_PROJECT / "mutants", ignore_errors=True)

        # Now populate cache and run again
        self._prepopulate_cache()
        _reset_cache_index()
        reset_plugin_manager()
        llm_results = self._run_mutmut()
        llm_count = len(llm_results)

        assert llm_count > baseline_count, (
            f"LLM run ({llm_count}) should produce more mutations than baseline ({baseline_count})"
        )


# ---------------------------------------------------------------------------
# Full loop test (generate + run, requires API key)
# ---------------------------------------------------------------------------


@SKIP_NO_KEY
class TestFullLoop:
    """Generate mutations via API, then run mutmut with them."""

    def test_generate_then_run(self):
        """Full pipeline: generate LLM mutations → run mutmut → verify results."""
        config = load_config(env=os.environ)

        with change_cwd(E2E_PROJECT):
            api_calls = run_generation(
                config=config,
                paths=["src/tiny/__init__.py"],
                budget=2,
                base_dir=E2E_PROJECT,
            )

        assert api_calls > 0, "Generation made no API calls"

        entries = list_cache_entries(base_dir=E2E_PROJECT)
        total_mutations = sum(len(e.mutations) for e in entries)
        assert total_mutations > 0, "No mutations were generated"

        # Now run mutmut with the generated cache
        _reset_cache_index()
        mutmut._reset_globals()
        reset_plugin_manager()

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

        assert results, "mutmut run produced no results"

        # At least some mutations should be killed
        killed = {k for k, v in results.items() if v == 1}
        assert killed, f"No mutations were killed. Results: {results}"

        # No crashes
        for key, code in results.items():
            assert code in {0, 1, 5, 33}, f"Mutant '{key}' crashed: exit code {code}"
