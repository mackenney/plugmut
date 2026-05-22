"""Subprocess-based CLI tests for plugmut-llm. No live API calls unless gated."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

E2E_PROJECT = (Path(__file__).parent.parent.parent / "e2e_project").resolve()
_PYTHON = Path(__file__).parent.parent.parent.parent / ".venv" / "bin" / "python"


SKIP_NO_LIVE = pytest.mark.skipif(
    not (os.environ.get("PLUGMUT_LLM_E2E_LIVE") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
    reason="Set PLUGMUT_LLM_E2E_LIVE=1 and ANTHROPIC_API_KEY to run live tests",
)


def _run_mutmut(*args, cwd, timeout=180, env_extra=None):
    """Run `mutmut` CLI as subprocess. Returns CompletedProcess."""
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [str(_PYTHON), "-m", "mutmut", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


@pytest.fixture()
def project_dir(tmp_path):
    """Copy e2e_project to a temp directory for isolation."""
    dest = tmp_path / "project"
    shutil.copytree(E2E_PROJECT, dest)
    return dest


def _prepopulate_library(project_dir):
    """Write known LLM mutations into the Library for the e2e project.

    Reuses the exact mutation strings from test_e2e_llm.py's TestOperatorIntegration.
    """
    import libcst as cst
    from mutmut_llm.library import Library

    source = (project_dir / "src" / "tiny" / "__init__.py").read_text()
    module = cst.parse_module(source)
    func_sources = {}
    for stmt in module.body:
        if isinstance(stmt, cst.FunctionDef):
            func_sources[stmt.name.value] = module.code_for_node(stmt)

    lib = Library(base_dir=project_dir)
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
        ],
        model="test-manual",
    )
    return lib


class TestGenerateDryRun:
    def test_dry_run_lists_functions(self, project_dir):
        """--dry-run should list discovered functions without calling the API."""
        result = _run_mutmut("generate", "--dry-run", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "fibonacci" in result.stdout
        assert "is_palindrome" in result.stdout
        assert "Found 2 functions" in result.stdout

    def test_dry_run_no_api_key_required(self, project_dir):
        """--dry-run should work without ANTHROPIC_API_KEY since no API call is made."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        result = subprocess.run(
            [str(_PYTHON), "-m", "mutmut", "generate", "--dry-run"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert "Traceback" not in result.stderr, f"Crashed: {result.stderr}"


class TestMutmutPathsFallback:
    def test_generate_uses_paths_to_mutate_from_config(self, project_dir):
        """Without --paths, generate should use paths_to_mutate from pyproject.toml."""
        result = _run_mutmut("generate", "--dry-run", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "src/tiny/__init__.py::fibonacci" in result.stdout
        assert "src/tiny/__init__.py::is_palindrome" in result.stdout

    def test_paths_flag_overrides_config(self, project_dir):
        """Explicit --paths should override paths_to_mutate from config."""
        extra_file = project_dir / "src" / "tiny" / "extra.py"
        extra_file.write_text("def helper():\n    return 42\n")

        result = _run_mutmut(
            "generate",
            "--dry-run",
            "--paths",
            "src/tiny/__init__.py",
            cwd=project_dir,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "fibonacci" in result.stdout
        assert "extra" not in result.stdout


class TestLlmStatus:
    def test_status_empty(self, project_dir):
        """llm-status on a fresh project with no library or runs."""
        result = _run_mutmut("llm-status", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Library: 0 functions, 0 mutations" in result.stdout
        assert "No runs recorded." in result.stdout

    def test_status_with_library(self, project_dir):
        """llm-status after pre-populating the library."""
        _prepopulate_library(project_dir)
        result = _run_mutmut("llm-status", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Library: 2 functions" in result.stdout


class TestRunWithLibrary:
    def test_run_with_prepopulated_library(self, project_dir):
        """mutmut run should pick up pre-populated LLM mutations."""
        _prepopulate_library(project_dir)
        result = _run_mutmut("run", cwd=project_dir)
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    def test_run_produces_run_result_json(self, project_dir):
        """After run, a RunResult JSON should exist with expected structure."""
        _prepopulate_library(project_dir)
        result = _run_mutmut("run", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        run_dir = project_dir / ".mutmut-cache" / "llm" / "runs"
        json_files = list(run_dir.glob("*.json")) if run_dir.exists() else []
        assert len(json_files) >= 1, f"No RunResult JSON found in {run_dir}"

        data = json.loads(json_files[0].read_text())
        assert "run_id" in data
        assert "started_at" in data
        assert "completed_at" in data
        assert isinstance(data.get("results"), list)
        assert len(data["results"]) > 0

        has_llm = any(r.get("is_llm") for r in data["results"])
        assert has_llm, "No result marked is_llm=True in RunResult"

    def test_llm_status_after_run(self, project_dir):
        """llm-status should report the run after mutmut run completes."""
        _prepopulate_library(project_dir)
        _run_mutmut("run", cwd=project_dir)

        result = _run_mutmut("llm-status", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "No runs recorded." not in result.stdout
        assert "Latest run" in result.stdout or "run" in result.stdout.lower()


@SKIP_NO_LIVE
class TestGenerateLiveSubprocess:
    def test_generate_creates_library_entries(self, project_dir):
        """Real API: generate should create library entries for both functions."""
        result = _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "Done." in result.stdout
        assert "mutations generated" in result.stdout

        from mutmut_llm.library import Library

        entries = Library(base_dir=project_dir).list_all()
        assert len(entries) == 2, f"Expected 2 entries, got {len(entries)}"

        func_names = {e.function_name for e in entries}
        assert "fibonacci" in func_names
        assert "is_palindrome" in func_names

        for entry in entries:
            assert len(entry.mutations) >= 1, f"No mutations for {entry.function_name}"

    def test_generate_cache_hit(self, project_dir):
        """Second generate run should hit cache — no new API calls."""
        _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        result = _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "0 API calls" in result.stdout or "cached" in result.stdout.lower()


@SKIP_NO_LIVE
class TestFullPipelineSubprocess:
    def test_generate_then_run(self, project_dir):
        """Full pipeline: generate LLM mutations → run mutmut → verify results."""
        gen_result = _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        assert gen_result.returncode == 0, f"generate failed: {gen_result.stderr}"

        run_result = _run_mutmut("run", cwd=project_dir)
        assert run_result.returncode == 0, f"run failed: {run_result.stderr}"

        run_dir = project_dir / ".mutmut-cache" / "llm" / "runs"
        json_files = list(run_dir.glob("*.json")) if run_dir.exists() else []
        assert json_files, "No RunResult JSON after generate→run"

        data = json.loads(json_files[0].read_text())
        has_llm = any(r.get("is_llm") for r in data.get("results", []))
        assert has_llm, "No is_llm=True results in RunResult"

    def test_pipeline_run_result_has_cost_data(self, project_dir):
        """RunResult should contain token/cost fields after a real API run."""
        _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        _run_mutmut("run", cwd=project_dir)

        run_dir = project_dir / ".mutmut-cache" / "llm" / "runs"
        json_files = list(run_dir.glob("*.json"))
        assert json_files, "No RunResult JSON"

        data = json.loads(json_files[0].read_text())
        assert "total_input_tokens" in data
        assert "total_output_tokens" in data
        assert "total_llm_cost_usd" in data

    def test_pipeline_llm_status_reports_run(self, project_dir):
        """After generate→run, llm-status should show the run."""
        _run_mutmut("generate", "--budget", "2", cwd=project_dir)
        _run_mutmut("run", cwd=project_dir)

        status = _run_mutmut("llm-status", cwd=project_dir)
        assert status.returncode == 0
        assert "No runs recorded." not in status.stdout


class TestCrossPluginDedupLLM:
    """Verify dedup reduces LLM mutations that normalize to the same AST."""

    def test_dedup_removes_equivalent_llm_mutations(self, project_dir):
        """Two LLM mutations with different strings but identical AST are deduplicated."""
        import os

        import libcst as cst
        from mutmut.file_mutation import create_mutations
        from mutmut.file_mutation import reset_plugin_operators
        from mutmut.hookspecs import hookimpl
        from mutmut.plugin_manager import get_plugin_manager
        from mutmut.plugin_manager import reset_plugin_manager
        from mutmut_dedup.plugin import mutmut_filter_mutations as dedup_filter
        from mutmut_llm.library import Library
        from mutmut_llm.operators import operator_llm
        from mutmut_llm.operators import reset_library
        from mutmut_llm.operators import set_library

        source = (project_dir / "src" / "tiny" / "__init__.py").read_text()
        module = cst.parse_module(source)
        func_sources: dict[str, str] = {}
        for stmt in module.body:
            if isinstance(stmt, cst.FunctionDef):
                func_sources[stmt.name.value] = module.code_for_node(stmt)

        # Two mutations that differ only in whitespace (a, b vs a,b).
        # The LLM operator's string-level dedup won't catch them (different strings).
        # But normalize_mutation → ast.dump strips whitespace → same AST → dedup removes one.
        mut_a = (
            "def fibonacci(n):\n"
            '    """Return the nth Fibonacci number."""\n'
            "    if n <= 0:\n"
            "        return 0\n"
            "    if n == 1:\n"
            "        return 1\n"
            "    a, b = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        a, b = b, a + b\n"
            "    return a\n"
        )
        # Identical logic, only 'a,b' vs 'a, b' — same AST, different string.
        mut_b = (
            "def fibonacci(n):\n"
            '    """Return the nth Fibonacci number."""\n'
            "    if n <= 0:\n"
            "        return 0\n"
            "    if n == 1:\n"
            "        return 1\n"
            "    a,b = 0, 1\n"
            "    for _ in range(2, n + 1):\n"
            "        a, b = b, a + b\n"
            "    return a\n"
        )

        lib = Library(base_dir=project_dir)
        lib.add(
            function_name="fibonacci",
            file_path="src/tiny/__init__.py",
            source=func_sources["fibonacci"],
            mutations=[
                {"mutated_code": mut_a, "description": "return a (variant 1)"},
                {"mutated_code": mut_b, "description": "return a (variant 2 — whitespace only)"},
            ],
            model="test-manual",
        )

        os.environ["PLUGMUT_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        reset_plugin_manager()
        reset_plugin_operators()

        class _LLM:
            @staticmethod
            @hookimpl
            def mutmut_register_operators():
                return [(cst.FunctionDef, operator_llm)]

        class _Dedup:
            @staticmethod
            @hookimpl(trylast=True)
            def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
                return dedup_filter(filename=filename, mutations=mutations)

        set_library(lib)

        pm_no_dedup = get_plugin_manager()
        pm_no_dedup.register(_LLM())
        _, muts_no_dedup = create_mutations(source, filename="src/tiny/__init__.py")

        reset_plugin_manager()
        reset_plugin_operators()
        pm_with_dedup = get_plugin_manager()
        pm_with_dedup.register(_LLM())
        pm_with_dedup.register(_Dedup())
        _, muts_with_dedup = create_mutations(source, filename="src/tiny/__init__.py")

        reset_library()
        reset_plugin_manager()
        reset_plugin_operators()
        os.environ.pop("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", None)

        assert len(muts_with_dedup) == len(muts_no_dedup) - 1, (
            f"Expected dedup to remove exactly 1 equivalent LLM mutation; "
            f"without_dedup={len(muts_no_dedup)}, with_dedup={len(muts_with_dedup)}"
        )
