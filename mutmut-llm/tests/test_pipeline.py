"""Tests for mutmut_llm.pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mutmut_llm.cache import list_cache_entries
from mutmut_llm.config import LLMConfig
from mutmut_llm.pipeline import GenerationResult, _call_llm_and_validate, run_generation
from mutmut_llm.scope import ScopeTarget
from tests.conftest import make_mock_response as _make_mock_response


def _config(api_key: str = "test-key", enabled: bool = True) -> LLMConfig:
    return LLMConfig(api_key=api_key, enabled=enabled, max_mutations_per_function=3)


@pytest.fixture
def sample_project(tmp_path):
    """Create a minimal Python project for generation."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "def greet(name):\n    return f'Hello, {name}!'\n\ndef add(a, b):\n    return a + b\n"
    )
    return tmp_path, src


class TestRunGeneration:
    def test_disabled_config(self, tmp_path, capsys):
        config = _config(enabled=False)
        result = run_generation(config, paths=["src"], budget=10, base_dir=tmp_path)
        assert result == 0
        assert "disabled" in capsys.readouterr().out.lower()

    def test_no_api_key_without_dry_run(self, tmp_path, capsys):
        config = _config(api_key="")
        result = run_generation(config, paths=["src"], budget=10, base_dir=tmp_path)
        assert result == 0
        assert "ANTHROPIC_API_KEY" in capsys.readouterr().out

    def test_no_functions_found(self, tmp_path, capsys):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        config = _config()
        result = run_generation(
            config, paths=[str(empty_dir)], budget=10, base_dir=tmp_path
        )
        assert result == 0
        assert "No functions found" in capsys.readouterr().out

    def test_dry_run(self, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config(api_key="")  # API key not needed for dry run
        result = run_generation(
            config, paths=[str(src)], budget=10, dry_run=True, base_dir=tmp_path
        )
        assert result == 0
        output = capsys.readouterr().out
        assert "Dry run" in output
        assert "greet" in output
        assert "add" in output

    @patch("anthropic.Anthropic")
    def test_generates_and_caches(self, MockAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return f'Goodbye, {name}!'",
                "description": "swap greeting",
            },
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)
        MockAnthropic.return_value = mock_client

        result = run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)

        assert result > 0
        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) > 0
        # Verify the mock was used (no real API calls)
        assert mock_client.messages.create.call_count > 0

    @patch("anthropic.Anthropic")
    def test_skips_cached_functions(self, MockAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return 'Hi'",
                "description": "simplify",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)
        MockAnthropic.return_value = mock_client

        # First run: generates
        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)
        first_call_count = mock_client.messages.create.call_count

        # Second run: should skip cached
        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)
        second_call_count = mock_client.messages.create.call_count - first_call_count

        output = capsys.readouterr().out
        assert "cached" in output
        # Second run should make fewer API calls (cached entries skipped)
        assert second_call_count < first_call_count

    @patch("anthropic.Anthropic")
    def test_budget_limits_api_calls(self, MockAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {"mutated_code": "def greet(name):\n    return 'x'", "description": "d"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)
        MockAnthropic.return_value = mock_client

        result = run_generation(config, paths=[str(src)], budget=1, base_dir=tmp_path)

        assert result == 1
        assert "Budget" in capsys.readouterr().out


class TestCallLlmAndValidate:
    def test_valid_mutations_returned(self):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = _config()
        result = _call_llm_and_validate(mock_client, config, target, max_mutations=3)
        assert isinstance(result, GenerationResult)
        assert len(result.mutations) == 1
        assert result.mutations[0]["mutated_code"] == "def f(x):\n    return x - 1"

    def test_syntax_errors_rejected(self, capsys):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x\n",
        )
        mutations = [
            {"mutated_code": "def f( broken syntax", "description": "bad"},
            {"mutated_code": "def f(x):\n    return -x", "description": "good"},
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert len(result.mutations) == 1
        output = capsys.readouterr().out
        assert "Rejected" in output

    def test_new_imports_rejected(self, capsys):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x\n",
        )
        mutations = [
            {
                "mutated_code": "import os\ndef f(x):\n    return os.getcwd()",
                "description": "inject",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert len(result.mutations) == 0
        assert "Rejected" in capsys.readouterr().out

    def test_api_failure_returns_empty(self):
        target = ScopeTarget(
            file_path="test.py", function_name="f", source="def f(): pass"
        )
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        with pytest.warns(UserWarning, match="API call failed"):
            result = _call_llm_and_validate(
                mock_client, _config(), target, max_mutations=3
            )
        assert result.mutations == []
        assert result.cost_usd == 0.0

    def test_truncated_response_warns(self):
        target = ScopeTarget(
            file_path="test.py", function_name="f", source="def f(): pass"
        )
        mutations = [{"mutated_code": "def f():\n    return 1", "description": ""}]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            mutations, stop_reason="max_tokens"
        )

        with pytest.warns(UserWarning, match="truncated"):
            _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)

    def test_temperature_passed_to_api(self):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = _config()
        _call_llm_and_validate(mock_client, config, target, max_mutations=3)

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["temperature"] == 0.6

    def test_custom_temperature_passed_to_api(self):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = LLMConfig(api_key="test-key", temperature=0.3)
        _call_llm_and_validate(mock_client, config, target, max_mutations=3)

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["temperature"] == 0.3

    def test_pragma_violation_rejected(self):
        original = (
            "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x + CONST"
        )
        target = ScopeTarget(file_path="test.py", function_name="f", source=original)
        mutations = [
            {
                "mutated_code": "def f(x):\n    CONST = 99  # pragma: no mutate\n    return x + CONST",
                "description": "change constant",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = _config()
        result = _call_llm_and_validate(mock_client, config, target, max_mutations=3)
        assert len(result.mutations) == 0, (
            "Pragma-violating mutation should be rejected"
        )

    def test_valid_mutation_with_pragma_passes(self):
        original = (
            "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x + CONST"
        )
        target = ScopeTarget(file_path="test.py", function_name="f", source=original)
        mutations = [
            {
                "mutated_code": "def f(x):\n    CONST = 42  # pragma: no mutate\n    return x - CONST",
                "description": "change operator",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        config = _config()
        result = _call_llm_and_validate(mock_client, config, target, max_mutations=3)
        assert len(result.mutations) == 1, "Mutation not touching pragma should pass"

    def test_empty_response_returns_empty(self):
        target = ScopeTarget(
            file_path="test.py", function_name="f", source="def f(): pass"
        )
        text_block = MagicMock()
        text_block.text = "I cannot help with that."
        response = MagicMock()
        response.content = [text_block]
        response.stop_reason = "end_turn"
        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.mutations == []


class TestCostTracking:
    def test_cost_captured_from_usage(self):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.input_tokens == 100
        assert result.output_tokens == 200
        assert result.cost_usd > 0

    def test_api_failure_has_zero_cost(self):
        target = ScopeTarget(
            file_path="test.py", function_name="f", source="def f(): pass"
        )
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("fail")

        with pytest.warns(UserWarning):
            result = _call_llm_and_validate(
                mock_client, _config(), target, max_mutations=3
            )
        assert result.cost_usd == 0.0
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    @patch("anthropic.Anthropic")
    def test_cost_stored_in_cache_entry(self, MockAnthropic, sample_project):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return f'Goodbye, {name}!'",
                "description": "swap greeting",
            },
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)
        MockAnthropic.return_value = mock_client

        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)

        entries = list_cache_entries(base_dir=tmp_path)
        assert any(e.cost_usd > 0 for e in entries)
        assert any(e.input_tokens > 0 for e in entries)
        assert any(e.generated_at != "" for e in entries)


class TestPromptCaching:
    def test_api_call_uses_system_blocks(self):
        """API call must pass list-of-dicts system parameter, not plain string."""
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
            context="import math",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)

        call_kwargs = mock_client.messages.create.call_args[1]
        system_arg = call_kwargs["system"]
        assert isinstance(system_arg, list)
        assert all(isinstance(block, dict) for block in system_arg)
        assert system_arg[-1].get("cache_control") == {"type": "ephemeral"}

    def test_user_prompt_excludes_context(self):
        """User prompt no longer includes file context (moved to system blocks)."""
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
            context="import math",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)

        call_kwargs = mock_client.messages.create.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]
        assert "File context" not in user_content
        assert "import math" not in user_content

    def test_cache_metrics_extracted_from_response(self):
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "negate"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            mutations, cache_creation_input_tokens=500, cache_read_input_tokens=300
        )

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.cache_creation_tokens == 500
        assert result.cache_read_tokens == 300

    def test_targets_sorted_by_file_path(self, tmp_path):
        """Verify _generate_mutations processes targets sorted by file_path."""
        from mutmut_llm.pipeline import _generate_mutations

        targets = [
            ScopeTarget(
                file_path="z_file.py", function_name="z", source="def z(): pass\n"
            ),
            ScopeTarget(
                file_path="a_file.py", function_name="a", source="def a(): pass\n"
            ),
            ScopeTarget(
                file_path="m_file.py", function_name="m", source="def m(): pass\n"
            ),
        ]
        budget_per_target = {
            "z_file.py::z": 3,
            "a_file.py::a": 3,
            "m_file.py::m": 3,
        }

        mutations = [{"mutated_code": "def x(): return 1", "description": "d"}]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)

        with patch("anthropic.Anthropic", return_value=mock_client):
            config = _config()
            _generate_mutations(
                config, targets, budget_per_target, total_budget=10, base_dir=tmp_path
            )

        calls = mock_client.messages.create.call_args_list
        assert len(calls) == 3
        system_texts = []
        for call in calls:
            kwargs = call[1]
            user_msg = kwargs["messages"][0]["content"]
            system_texts.append(user_msg)

        assert "def a" in system_texts[0]
        assert "def m" in system_texts[1]
        assert "def z" in system_texts[2]

    def test_generation_result_has_cache_fields(self):
        result = GenerationResult(
            mutations=[],
            cache_creation_tokens=100,
            cache_read_tokens=200,
        )
        assert result.cache_creation_tokens == 100
        assert result.cache_read_tokens == 200

    @patch("anthropic.Anthropic")
    def test_cache_hit_rate_includes_uncached_input_in_denominator(
        self, MockAnthropic, sample_project, capsys
    ):
        """Cache hit % must account for uncached input_tokens, not just cache tokens."""
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return f'Goodbye, {name}!'",
                "description": "swap greeting",
            },
        ]
        mock_response = _make_mock_response(
            mutations, cache_creation_input_tokens=0, cache_read_input_tokens=400
        )
        mock_response.usage.input_tokens = 600

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        MockAnthropic.return_value = mock_client

        run_generation(config, paths=[str(src)], budget=1, base_dir=tmp_path)

        output = capsys.readouterr().out
        assert "Cache hit rate:" in output
        # 2 functions but budget=1, so 1 call: 400 read / (600 input + 400 read + 0 write) = 40%
        assert "40%" in output


class TestUsageFieldExtraction:
    """Verify the pipeline correctly reads Anthropic's usage field names."""

    def test_missing_cache_fields_in_usage_default_to_zero(self):
        """If Anthropic doesn't return cache fields (old API), getattr defaults to 0."""
        import json

        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "d"}
        ]

        usage = MagicMock(spec=["input_tokens", "output_tokens"])
        usage.input_tokens = 50
        usage.output_tokens = 100

        text_block = MagicMock()
        text_block.text = json.dumps(mutations)
        response = MagicMock()
        response.content = [text_block]
        response.stop_reason = "end_turn"
        response.usage = usage

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.cache_creation_tokens == 0
        assert result.cache_read_tokens == 0

    def test_no_usage_at_all(self):
        """If response has no usage attribute, all tokens default to 0."""
        import json

        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "d"}
        ]

        text_block = MagicMock()
        text_block.text = json.dumps(mutations)
        response = MagicMock(spec=["content", "stop_reason"])
        response.content = [text_block]
        response.stop_reason = "end_turn"

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.cache_creation_tokens == 0
        assert result.cache_read_tokens == 0

    def test_pipeline_passes_raw_api_tokens(self):
        """Verify pipeline doesn't subtract cache tokens from input_tokens."""
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "d"}
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(
            mutations,
            input_tokens=50,
            output_tokens=100,
            cache_creation_input_tokens=800,
            cache_read_input_tokens=200,
        )

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.input_tokens == 50
        assert result.cache_creation_tokens == 800
        assert result.cache_read_tokens == 200


class TestCacheHitLogging:
    def test_no_cache_tokens_no_log(self, tmp_path, capsys):
        """When no cache tokens at all, cache hit line should not appear."""
        from mutmut_llm.pipeline import _generate_mutations

        mock_client = MagicMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create.return_value = _make_mock_response(
            mutations, cache_creation_input_tokens=0, cache_read_input_tokens=0
        )

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.Anthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        assert "Cache hit rate" not in output

    def test_all_cache_read_shows_100_percent(self, tmp_path, capsys):
        from mutmut_llm.pipeline import _generate_mutations

        mock_client = MagicMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create.return_value = _make_mock_response(
            mutations,
            input_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=500,
        )

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.Anthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        assert "Cache hit rate: 100%" in output

    def test_mixed_cache_shows_correct_percentage(self, tmp_path, capsys):
        from mutmut_llm.pipeline import _generate_mutations

        mock_client = MagicMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create.return_value = _make_mock_response(
            mutations,
            cache_creation_input_tokens=250,
            cache_read_input_tokens=750,
        )

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.Anthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        # 750 / (100 input + 750 cache_read + 250 cache_write) = 68%
        assert "Cache hit rate: 68%" in output
