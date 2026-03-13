"""Live API integration tests for the mutmut-llm plugin.

Gated behind MUTMUT_LLM_E2E_LIVE=1 to prevent accidental API spend.
Requires ANTHROPIC_API_KEY to be set with a valid key.

Run with:
    MUTMUT_LLM_E2E_LIVE=1 uv run --package mutmut-llm pytest mutmut-llm/tests/e2e/test_e2e_live.py -v
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import libcst as cst
import pytest

from mutmut_llm.cache import list_cache_entries, source_hash
from mutmut_llm.config import load_config
from mutmut_llm.operators import _reset_cache_index
from mutmut_llm.pipeline import GenerationResult, _call_llm_and_validate, run_generation
from mutmut_llm.scope import ScopeTarget
from mutmut_llm.validation import validate_imports

LIVE_ENABLED = os.environ.get("MUTMUT_LLM_E2E_LIVE") == "1"
HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))

skip_no_live = pytest.mark.skipif(
    not (LIVE_ENABLED and HAS_API_KEY),
    reason="Set MUTMUT_LLM_E2E_LIVE=1 and ANTHROPIC_API_KEY to run live tests",
)

SAMPLE_FUNCTION_SOURCE = """\
def moving_average(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        chunk = values[start:i + 1]
        result.append(sum(chunk) / len(chunk))
    return result
"""

SAMPLE_CONTEXT = "from __future__ import annotations\n"


@contextmanager
def change_cwd(path):
    old = Path.cwd().resolve()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


@pytest.fixture(scope="module")
def live_generation_result():
    """Call the real API once, reuse across all tests in this module."""
    import anthropic

    config = load_config(env=os.environ)
    assert config.is_configured, "ANTHROPIC_API_KEY not set"

    client = anthropic.Anthropic(api_key=config.api_key)
    target = ScopeTarget(
        file_path="sample.py",
        function_name="moving_average",
        source=SAMPLE_FUNCTION_SOURCE,
        context=SAMPLE_CONTEXT,
    )
    mutations = _call_llm_and_validate(
        client, config, target, config.max_mutations_per_function
    )
    return mutations


@pytest.fixture(scope="session")
def live_pipeline_result(tmp_path_factory):
    """Run the full pipeline once, reuse across tests needing cache state."""
    project_dir = tmp_path_factory.mktemp("live_pipeline")
    src_dir = project_dir / "src"
    src_dir.mkdir()

    (src_dir / "sample.py").write_text(SAMPLE_CONTEXT + "\n" + SAMPLE_FUNCTION_SOURCE)

    (project_dir / "pyproject.toml").write_text(
        "[project]\nname = 'live-test'\nversion = '0.1.0'\n\n"
        "[tool.mutmut]\npaths_to_mutate = ['src/']\n"
    )

    config = load_config(env=os.environ)
    with change_cwd(project_dir):
        api_calls = run_generation(
            config=config,
            paths=["src/sample.py"],
            budget=1,
            base_dir=project_dir,
        )

    return {
        "project_dir": project_dir,
        "api_calls": api_calls,
        "config": config,
    }


@skip_no_live
class TestBasicResponseValidation:
    """Step 2: Verify the LLM returns structurally valid mutations."""

    def test_live_returns_mutations(self, live_generation_result):
        assert isinstance(live_generation_result, GenerationResult)
        assert len(live_generation_result.mutations) > 0, "LLM returned no mutations"

    def test_live_mutations_have_required_fields(self, live_generation_result):
        for m in live_generation_result.mutations:
            assert "mutated_code" in m, f"Missing 'mutated_code' key in mutation: {m}"

    def test_live_mutations_have_descriptions(self, live_generation_result):
        for m in live_generation_result.mutations:
            assert "description" in m, f"Missing 'description' key in mutation: {m}"
            assert isinstance(m["description"], str) and m["description"].strip(), (
                f"Empty description in mutation: {m}"
            )

    def test_live_mutation_count_within_budget(self, live_generation_result):
        config = load_config(env=os.environ)
        assert (
            len(live_generation_result.mutations) <= config.max_mutations_per_function
        ), (
            f"Got {len(live_generation_result.mutations)} mutations, "
            f"budget is {config.max_mutations_per_function}"
        )


@skip_no_live
class TestSyntaxAndValidation:
    """Step 3: Verify mutations pass the validation pipeline."""

    def test_live_mutations_parse(self, live_generation_result):
        for m in live_generation_result.mutations:
            module = cst.parse_module(m["mutated_code"])
            assert module.body, f"Parsed module has empty body: {m['mutated_code']}"

    def test_live_mutations_are_functions(self, live_generation_result):
        for m in live_generation_result.mutations:
            module = cst.parse_module(m["mutated_code"])
            func_defs = [
                stmt for stmt in module.body if isinstance(stmt, cst.FunctionDef)
            ]
            assert func_defs, f"No FunctionDef found in mutation:\n{m['mutated_code']}"

    def test_live_mutations_pass_import_validation(self, live_generation_result):
        for m in live_generation_result.mutations:
            err = validate_imports(m["mutated_code"], SAMPLE_FUNCTION_SOURCE)
            assert err is None, (
                f"Import validation failed: {err}\nCode: {m['mutated_code']}"
            )

    def test_live_mutations_differ_from_original(self, live_generation_result):
        for m in live_generation_result.mutations:
            assert m["mutated_code"].strip() != SAMPLE_FUNCTION_SOURCE.strip(), (
                "Mutation is identical to original source"
            )


@skip_no_live
class TestPromptQuality:
    """Step 4: Verify prompt engineering produces non-trivial mutations."""

    def test_live_mutations_are_not_trivial_operator_swaps(
        self, live_generation_result
    ):
        original_no_ops = _strip_operators(SAMPLE_FUNCTION_SOURCE)

        non_trivial = 0
        for m in live_generation_result.mutations:
            mutated_no_ops = _strip_operators(m["mutated_code"])
            if original_no_ops != mutated_no_ops:
                non_trivial += 1

        assert non_trivial > 0, (
            f"All {len(live_generation_result.mutations)} mutations are trivial operator swaps"
        )

    def test_live_mutations_preserve_function_signature(self, live_generation_result):
        original_module = cst.parse_module(SAMPLE_FUNCTION_SOURCE)
        original_func = next(
            stmt for stmt in original_module.body if isinstance(stmt, cst.FunctionDef)
        )
        original_name = original_func.name.value
        original_params = original_module.code_for_node(original_func.params)

        for m in live_generation_result.mutations:
            mutated_module = cst.parse_module(m["mutated_code"])
            mutated_func = next(
                (
                    stmt
                    for stmt in mutated_module.body
                    if isinstance(stmt, cst.FunctionDef)
                ),
                None,
            )
            assert mutated_func is not None, (
                f"No function found in: {m['mutated_code']}"
            )
            assert mutated_func.name.value == original_name, (
                f"Function name changed: {mutated_func.name.value} != {original_name}"
            )
            mutated_params = mutated_module.code_for_node(mutated_func.params)
            assert mutated_params == original_params, (
                f"Parameters changed: {mutated_params} != {original_params}"
            )


@skip_no_live
class TestFullPipeline:
    """Step 5: Test the complete `mutmut generate` flow with real API."""

    def test_live_full_pipeline(self, live_pipeline_result):
        project_dir = live_pipeline_result["project_dir"]
        api_calls = live_pipeline_result["api_calls"]

        assert api_calls == 1, f"Expected 1 API call, got {api_calls}"

        entries = list_cache_entries(base_dir=project_dir)
        assert len(entries) == 1, f"Expected 1 cache entry, got {len(entries)}"

        entry = entries[0]
        assert entry.function_name == "moving_average"
        assert len(entry.mutations) > 0

        expected_hash = source_hash(SAMPLE_FUNCTION_SOURCE)
        assert entry.source_hash == expected_hash, (
            f"Hash mismatch: {entry.source_hash} != {expected_hash}"
        )

    def test_live_cache_hit_no_api_call(self, live_pipeline_result):
        """Re-running with same source should hit cache."""
        project_dir = live_pipeline_result["project_dir"]
        config = live_pipeline_result["config"]

        with change_cwd(project_dir):
            result = run_generation(
                config=config,
                paths=["src/sample.py"],
                budget=1,
                base_dir=project_dir,
            )

        assert result == 0, f"Expected 0 API calls (cache hit), got {result}"


@skip_no_live
class TestOperatorReadsCache:
    """Step 6: Test that cached mutations are picked up by the operator."""

    def test_live_operator_reads_cache(self, live_pipeline_result):
        from mutmut_llm.operators import operator_llm

        project_dir = live_pipeline_result["project_dir"]
        _reset_cache_index()

        source_text = (project_dir / "src" / "sample.py").read_text()
        module = cst.parse_module(source_text)
        func_node = next(
            stmt for stmt in module.body if isinstance(stmt, cst.FunctionDef)
        )

        os.chdir(project_dir)
        try:
            _reset_cache_index()
            mutations = list(operator_llm(func_node))
        finally:
            _reset_cache_index()

        assert len(mutations) > 0, "operator_llm returned no mutations from cache"
        for m in mutations:
            assert isinstance(m, cst.FunctionDef)
            assert m.name.value == "moving_average"
            reparsed = cst.parse_module(module.code_for_node(m))
            assert reparsed.body, "Mutation code is not parseable"


@skip_no_live
class TestErrorHandling:
    """Step 7: Graceful failure modes."""

    def test_live_invalid_api_key(self):
        import anthropic

        config = load_config(
            env={**os.environ, "ANTHROPIC_API_KEY": "sk-bogus-key-12345"}
        )
        client = anthropic.Anthropic(api_key="sk-bogus-key-12345")
        target = ScopeTarget(
            file_path="sample.py",
            function_name="moving_average",
            source=SAMPLE_FUNCTION_SOURCE,
            context=SAMPLE_CONTEXT,
        )

        result = _call_llm_and_validate(client, config, target, 3)
        assert isinstance(result, GenerationResult)
        assert result.mutations == [], (
            f"Expected empty mutations for invalid key, got {result.mutations}"
        )

    def test_live_empty_function(self, live_generation_result):
        """Pass a trivial function — should handle gracefully."""
        import anthropic

        config = load_config(env=os.environ)
        client = anthropic.Anthropic(api_key=config.api_key)
        target = ScopeTarget(
            file_path="sample.py",
            function_name="f",
            source="def f(): pass\n",
            context="",
        )

        result = _call_llm_and_validate(client, config, target, 3)
        assert isinstance(result, GenerationResult)


class _OperatorCollector(cst.CSTVisitor):
    """Collect all binary and comparison operators from a CST tree."""

    def __init__(self) -> None:
        self.ops: list[str] = []

    def visit_BinaryOperation(self, node: cst.BinaryOperation) -> None:
        self.ops.append(type(node.operator).__name__)

    def visit_Comparison(self, node: cst.Comparison) -> None:
        for target in node.comparisons:
            self.ops.append(type(target.operator).__name__)

    def visit_UnaryOperation(self, node: cst.UnaryOperation) -> None:
        self.ops.append(type(node.operator).__name__)


def _collect_operators(module: cst.Module) -> list[str]:
    collector = _OperatorCollector()
    module.visit(collector)
    return collector.ops


def _strip_operators(code: str) -> str:
    """Replace all operators with a placeholder to compare non-operator structure."""

    class _OpReplacer(cst.CSTTransformer):
        def leave_BinaryOperation(
            self, original: cst.BinaryOperation, updated: cst.BinaryOperation
        ) -> cst.BaseExpression:
            return updated.with_changes(operator=cst.Add())

        def leave_Comparison(
            self, original: cst.Comparison, updated: cst.Comparison
        ) -> cst.BaseExpression:
            new_targets = [
                t.with_changes(operator=cst.Equal()) for t in updated.comparisons
            ]
            return updated.with_changes(comparisons=new_targets)

    module = cst.parse_module(code)
    return module.visit(_OpReplacer()).code
