"""Tests for mutmut_llm.pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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

    @patch("anthropic.AsyncAnthropic")
    def test_generates_and_caches(self, MockAsyncAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return f'Goodbye, {name}!'",
                "description": "swap greeting",
            },
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

        result = run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)

        assert result > 0
        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) > 0
        # Verify the mock was used (no real API calls)
        assert mock_client.messages.create.call_count > 0

    @patch("anthropic.AsyncAnthropic")
    def test_skips_cached_functions(self, MockAsyncAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return 'Hi'",
                "description": "simplify",
            }
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

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

    @patch("anthropic.AsyncAnthropic")
    def test_budget_limits_api_calls(self, MockAsyncAnthropic, sample_project, capsys):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {"mutated_code": "def greet(name):\n    return 'x'", "description": "d"}
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

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


class TestMultiModelGeneration:
    @patch("anthropic.AsyncAnthropic")
    def test_generate_skips_cached_model(self, MockAsyncAnthropic, sample_project, capsys):
        """Second run with same model makes zero API calls."""
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return 'Hi'",
                "description": "simplify",
            }
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)
        first_count = mock_client.messages.create.call_count

        mock_client.messages.create.reset_mock()
        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)

        assert mock_client.messages.create.call_count == 0

    @patch("anthropic.AsyncAnthropic")
    def test_generate_runs_for_new_model(self, MockAsyncAnthropic, sample_project, capsys):
        """Switching model generates new entries; old model's entries remain on disk."""
        tmp_path, src = sample_project

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return 'Hi'",
                "description": "simplify",
            }
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

        config_a = LLMConfig(
            api_key="test-key",
            enabled=True,
            model="claude-sonnet-4-6",
            max_mutations_per_function=3,
        )
        run_generation(config_a, paths=[str(src)], budget=10, base_dir=tmp_path)
        entries_after_a = list_cache_entries(base_dir=tmp_path)
        model_a_count = sum(
            1 for e in entries_after_a if e.model == "claude-sonnet-4-6"
        )

        mock_client.messages.create.reset_mock()
        config_b = LLMConfig(
            api_key="test-key",
            enabled=True,
            model="claude-opus-4-6",
            max_mutations_per_function=3,
        )
        run_generation(config_b, paths=[str(src)], budget=10, base_dir=tmp_path)

        assert mock_client.messages.create.call_count > 0

        entries_after_b = list_cache_entries(base_dir=tmp_path)
        model_a_remaining = sum(
            1 for e in entries_after_b if e.model == "claude-sonnet-4-6"
        )
        model_b_count = sum(1 for e in entries_after_b if e.model == "claude-opus-4-6")

        assert model_a_remaining == model_a_count
        assert model_b_count > 0


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

    @patch("anthropic.AsyncAnthropic")
    def test_cost_stored_in_cache_entry(self, MockAsyncAnthropic, sample_project):
        tmp_path, src = sample_project
        config = _config()

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return f'Goodbye, {name}!'",
                "description": "swap greeting",
            },
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))
        MockAsyncAnthropic.return_value = mock_client

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

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(mutations))

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
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

        assert any("def a" in t for t in system_texts)
        assert any("def m" in t for t in system_texts)
        assert any("def z" in t for t in system_texts)

    def test_generation_result_has_cache_fields(self):
        result = GenerationResult(
            mutations=[],
            cache_creation_tokens=100,
            cache_read_tokens=200,
        )
        assert result.cache_creation_tokens == 100
        assert result.cache_read_tokens == 200

    @patch("anthropic.AsyncAnthropic")
    def test_cache_hit_rate_includes_uncached_input_in_denominator(
        self, MockAsyncAnthropic, sample_project, capsys
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

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        MockAsyncAnthropic.return_value = mock_client

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

        mock_client = AsyncMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(
            mutations, cache_creation_input_tokens=0, cache_read_input_tokens=0
        ))

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        assert "Cache hit rate" not in output

    def test_all_cache_read_shows_100_percent(self, tmp_path, capsys):
        from mutmut_llm.pipeline import _generate_mutations

        mock_client = AsyncMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(
            mutations,
            input_tokens=0,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=500,
        ))

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        assert "Cache hit rate: 100%" in output

    def test_mixed_cache_shows_correct_percentage(self, tmp_path, capsys):
        from mutmut_llm.pipeline import _generate_mutations

        mock_client = AsyncMock()
        mutations = [{"mutated_code": "def f(): return 1", "description": "d"}]
        mock_client.messages.create = AsyncMock(return_value=_make_mock_response(
            mutations,
            cache_creation_input_tokens=250,
            cache_read_input_tokens=750,
        ))

        targets = [
            ScopeTarget(file_path="t.py", function_name="f", source="def f(): pass\n")
        ]
        budget = {"t.py::f": 3}

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            _generate_mutations(
                _config(), targets, budget, total_budget=10, base_dir=tmp_path
            )

        output = capsys.readouterr().out
        # 750 / (100 input + 750 cache_read + 250 cache_write) = 68%
        assert "Cache hit rate: 68%" in output


class TestErrorClassifier:
    def _make_api_exc(self, cls, message="error", status_code=400):
        """Construct an Anthropic HTTP exception."""
        import anthropic

        response = MagicMock()
        response.status_code = status_code
        response.headers = {}
        return cls(message=message, response=response, body=None)

    def test_authentication_error_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.AuthenticationError, status_code=401)
        assert classify_error(exc) == ErrorAction.STOP

    def test_permission_denied_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.PermissionDeniedError, status_code=403)
        assert classify_error(exc) == ErrorAction.STOP

    def test_rate_limit_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="rate limit hit", status_code=429)
        assert classify_error(exc) == ErrorAction.RETRY

    def test_rate_limit_with_spending_limit_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="spending limit exceeded", status_code=429)
        assert classify_error(exc) == ErrorAction.STOP

    def test_rate_limit_with_credit_stops(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.RateLimitError, message="insufficient credit", status_code=429)
        assert classify_error(exc) == ErrorAction.STOP

    def test_internal_server_error_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.InternalServerError, status_code=500)
        assert classify_error(exc) == ErrorAction.RETRY

    def test_timeout_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = anthropic.APITimeoutError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_connection_error_retries(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = anthropic.APIConnectionError(request=MagicMock())
        assert classify_error(exc) == ErrorAction.RETRY

    def test_bad_request_skips(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.BadRequestError, status_code=400)
        assert classify_error(exc) == ErrorAction.SKIP

    def test_not_found_skips(self):
        import anthropic

        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = self._make_api_exc(anthropic.NotFoundError, status_code=404)
        assert classify_error(exc) == ErrorAction.SKIP

    def test_unknown_exception_skips(self):
        from mutmut_llm.pipeline import ErrorAction, classify_error

        exc = ValueError("unexpected")
        assert classify_error(exc) == ErrorAction.SKIP


class TestTrackedSemaphore:
    async def test_in_flight_starts_at_zero(self):
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(5)
        assert sem.in_flight == 0

    async def test_in_flight_tracking(self):
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(2)
        assert sem.in_flight == 0

        async with sem:
            assert sem.in_flight == 1
            async with sem:
                assert sem.in_flight == 2
            assert sem.in_flight == 1
        assert sem.in_flight == 0

    async def test_max_concurrency_enforced(self):
        import asyncio
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(2)
        acquired = []
        released = asyncio.Event()

        async def worker():
            async with sem:
                acquired.append(1)
                await released.wait()

        tasks = [asyncio.create_task(worker()) for _ in range(3)]
        await asyncio.sleep(0.05)
        assert len(acquired) == 2
        assert sem.in_flight == 2
        released.set()
        await asyncio.gather(*tasks)
        assert sem.in_flight == 0

    async def test_in_flight_accurate_under_concurrent_access(self):
        import asyncio
        from mutmut_llm.pipeline import TrackedSemaphore
        sem = TrackedSemaphore(5)
        max_seen = 0

        async def worker():
            nonlocal max_seen
            async with sem:
                max_seen = max(max_seen, sem.in_flight)
                await asyncio.sleep(0.01)

        await asyncio.gather(*[worker() for _ in range(10)])
        assert max_seen <= 5
        assert sem.in_flight == 0


class TestSigintHandler:
    def test_sigint_sets_cancel_event(self):
        import asyncio
        import os
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        cancel_event = asyncio.Event()
        with _sigint_handler(cancel_event):
            assert not cancel_event.is_set()
            os.kill(os.getpid(), signal.SIGINT)
            assert cancel_event.is_set()

    def test_old_handler_restored(self):
        import asyncio
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        original = signal.getsignal(signal.SIGINT)
        cancel_event = asyncio.Event()
        with _sigint_handler(cancel_event):
            current = signal.getsignal(signal.SIGINT)
            assert current != original
        restored = signal.getsignal(signal.SIGINT)
        assert restored == original

    def test_handler_restored_on_exception(self):
        import asyncio
        import signal
        from mutmut_llm.pipeline import _sigint_handler

        original = signal.getsignal(signal.SIGINT)
        cancel_event = asyncio.Event()
        try:
            with _sigint_handler(cancel_event):
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        restored = signal.getsignal(signal.SIGINT)
        assert restored == original


class TestComputeConcurrency:
    def _cfg(self, min_c=5, max_c=20):
        from mutmut_llm.config import LLMConfig
        return LLMConfig(min_concurrency=min_c, max_concurrency=max_c)

    def test_zero_targets_returns_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        assert _compute_concurrency(0, self._cfg()) == 5

    def test_one_target_returns_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        assert _compute_concurrency(1, self._cfg()) == 5

    def test_six_targets_clamped_to_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 6//3=2 < 5
        assert _compute_concurrency(6, self._cfg()) == 5

    def test_fifteen_targets_equals_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 15//3=5 == min
        assert _compute_concurrency(15, self._cfg()) == 5

    def test_thirty_targets_returns_ten(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 30//3=10
        assert _compute_concurrency(30, self._cfg()) == 10

    def test_sixty_targets_equals_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 60//3=20 == max
        assert _compute_concurrency(60, self._cfg()) == 20

    def test_ninety_targets_clamped_to_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # 90//3=30 > 20
        assert _compute_concurrency(90, self._cfg()) == 20

    def test_custom_min_max_clamped_to_max(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # n=30, min=1, max=5: 30//3=10 > 5
        assert _compute_concurrency(30, self._cfg(min_c=1, max_c=5)) == 5

    def test_custom_min_max_clamped_to_min(self):
        from mutmut_llm.pipeline import _compute_concurrency
        # n=3, min=10, max=20: 3//3=1 < 10
        assert _compute_concurrency(3, self._cfg(min_c=10, max_c=20)) == 10


class TestCallLlmAndValidateAsync:
    async def test_valid_mutations_returned(self, tmp_path):
        import asyncio
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [
            {"mutated_code": "def f(): return 2", "description": "change constant"},
        ]
        client = make_async_mock_client([make_mock_response(mutations, input_tokens=100, output_tokens=50)])

        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")
        result = await _call_llm_and_validate_async(client, config, target, 3)

        assert len(result.mutations) == 1
        assert result.mutations[0]["mutated_code"] == "def f(): return 2"
        assert result.input_tokens == 100
        assert result.output_tokens == 50

    async def test_truncated_response_warns(self):
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response
        import warnings

        client = make_async_mock_client([make_mock_response([], stop_reason="max_tokens")])
        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            await _call_llm_and_validate_async(client, config, target, 3)

        assert any("max_tokens" in str(warning.message) for warning in w)

    async def test_timeout_raises(self):
        import asyncio
        from unittest.mock import AsyncMock
        from mutmut_llm.pipeline import _call_llm_and_validate_async

        async def slow_create(**kwargs):
            await asyncio.sleep(1000)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=slow_create)

        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key", request_timeout_seconds=10)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                _call_llm_and_validate_async(client, config, target, 3),
                timeout=0.1,
            )

    async def test_syntax_errors_rejected(self):
        from mutmut_llm.pipeline import _call_llm_and_validate_async
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [
            {"mutated_code": "def f(): SYNTAX ERROR!!!", "description": "invalid"},
            {"mutated_code": "def f(): return 2", "description": "valid"},
        ]
        client = make_async_mock_client([make_mock_response(mutations)])
        target = ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )
        config = LLMConfig(api_key="test-key")
        result = await _call_llm_and_validate_async(client, config, target, 3)

        assert len(result.mutations) == 1
        assert result.mutations[0]["mutated_code"] == "def f(): return 2"


class TestComputeBackoff:
    def test_attempt_zero(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(0, 1.0)
        assert 1.0 <= d <= 1.5

    def test_attempt_one(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(1, 1.0)
        assert 2.0 <= d <= 2.5

    def test_attempt_two(self):
        from mutmut_llm.pipeline import _compute_backoff
        d = _compute_backoff(2, 1.0)
        assert 4.0 <= d <= 4.5

    def test_capped_at_thirty(self):
        from mutmut_llm.pipeline import _compute_backoff
        # 1.0 * 2^10 = 1024 >> 30, capped at 30
        d = _compute_backoff(10, 1.0)
        assert 30.0 <= d <= 30.5


class TestCallLlmAsync:
    def _make_target(self):
        from mutmut_llm.scope import ScopeTarget
        return ScopeTarget(
            file_path="f.py",
            function_name="f",
            source="def f(): return 1",
            context="",
        )

    def _make_semaphore(self, n=5):
        from mutmut_llm.pipeline import TrackedSemaphore
        return TrackedSemaphore(n)

    async def test_successful_call_returns_result(self):
        import asyncio
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_async_mock_client, make_mock_response

        mutations = [{"mutated_code": "def f(): return 2", "description": ""}]
        client = make_async_mock_client([make_mock_response(mutations)])
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert len(result.mutations) == 1

    async def test_cancel_event_prevents_call(self):
        import asyncio
        from unittest.mock import AsyncMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        client = AsyncMock()
        config = LLMConfig(api_key="test-key")
        cancel_event = asyncio.Event()
        cancel_event.set()  # Already cancelled
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert result.mutations == []
        client.messages.create.assert_not_called()

    async def test_skip_on_permanent_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 400
        response.headers = {}
        exc = anthropic.BadRequestError(message="bad request", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        result = await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert result.mutations == []
        # Should only call once (no retries for SKIP)
        assert client.messages.create.call_count == 1

    async def test_stop_on_fatal_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 401
        response.headers = {}
        exc = anthropic.AuthenticationError(message="invalid key", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)
        config = LLMConfig(api_key="test-key", max_retries=2)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        with pytest.raises(anthropic.AuthenticationError):
            await _call_llm_async(client, config, target, 3, sem, cancel_event)
        assert cancel_event.is_set()

    async def test_retry_on_transient_error(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock, patch
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_mock_response

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        exc = anthropic.InternalServerError(message="server error", response=response, body=None)

        success_response = make_mock_response([{"mutated_code": "def f(): return 2", "description": ""}])
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=[exc, success_response])

        config = LLMConfig(api_key="test-key", max_retries=2, base_backoff_seconds=0.001)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        sleep_calls = []
        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", mock_sleep):
            result = await _call_llm_async(client, config, target, 3, sem, cancel_event)

        assert len(result.mutations) == 1
        assert len(sleep_calls) == 1  # One sleep between attempts
        assert client.messages.create.call_count == 2

    async def test_max_retries_exhausted_returns_empty(self):
        import asyncio
        import anthropic
        from unittest.mock import AsyncMock, MagicMock, patch
        from mutmut_llm.pipeline import _call_llm_async
        from mutmut_llm.config import LLMConfig

        response = MagicMock()
        response.status_code = 500
        response.headers = {}
        exc = anthropic.InternalServerError(message="server error", response=response, body=None)

        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=exc)

        config = LLMConfig(api_key="test-key", max_retries=2, base_backoff_seconds=0.001)
        cancel_event = asyncio.Event()
        sem = self._make_semaphore()
        target = self._make_target()

        async def mock_sleep(delay):
            pass

        with patch("asyncio.sleep", mock_sleep):
            result = await _call_llm_async(client, config, target, 3, sem, cancel_event)

        assert result.mutations == []
        assert client.messages.create.call_count == 3  # 1 initial + 2 retries


class TestGenerateMutationsAsync:
    def _make_targets(self, n=2, base="f"):
        from mutmut_llm.scope import ScopeTarget
        return [
            ScopeTarget(
                file_path=f"{base}{i}.py",
                function_name="f",
                source="def f(): return 1",
                context="",
            )
            for i in range(n)
        ]

    async def test_all_cached_returns_zero(self, tmp_path, capsys):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from mutmut_llm.pipeline import _generate_mutations_async
        from mutmut_llm.config import LLMConfig
        from mutmut_llm.cache import write_cache_entry, CacheEntry, source_hash

        target = self._make_targets(1)[0]
        src_hash = source_hash(target.source)
        entry = CacheEntry(
            function_name=target.function_name,
            file_path=target.file_path,
            source_hash=src_hash,
            mutations=[],
            model="claude-sonnet-4-6",
            cost_usd=0.0,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            generated_at="2024-01-01T00:00:00+00:00",
        )
        write_cache_entry(entry, base_dir=tmp_path)

        config = LLMConfig(api_key="test-key")
        with patch("anthropic.AsyncAnthropic") as MockClient:
            result = await _generate_mutations_async(config, [target], {}, 10, tmp_path)

        assert result == 0
        assert "All targets cached" in capsys.readouterr().out

    async def test_budget_enforcement(self, tmp_path, capsys):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from mutmut_llm.pipeline import _generate_mutations_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_mock_response

        targets = self._make_targets(3)
        mutations = [{"mutated_code": "def f(): return 2", "description": ""}]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=make_mock_response(mutations))

        config = LLMConfig(api_key="test-key", max_retries=0)
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await _generate_mutations_async(config, targets, {}, 1, tmp_path)

        assert result == 1  # Only 1 budget

    async def test_tqdm_update_called_per_task(self, tmp_path):
        import asyncio
        from unittest.mock import patch, AsyncMock, MagicMock
        from mutmut_llm.pipeline import _generate_mutations_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_mock_response

        targets = self._make_targets(3)
        mutations = [{"mutated_code": "def f(): return 2", "description": ""}]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=make_mock_response(mutations))

        config = LLMConfig(api_key="test-key", max_retries=0)
        mock_pbar = MagicMock()
        mock_tqdm = MagicMock(return_value=mock_pbar)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch("mutmut_llm.pipeline.tqdm", mock_tqdm):
                await _generate_mutations_async(config, targets, {}, 10, tmp_path)

        assert mock_pbar.update.call_count == 3

    async def test_cost_accumulation(self, tmp_path, capsys):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from mutmut_llm.pipeline import _generate_mutations_async
        from mutmut_llm.config import LLMConfig
        from tests.conftest import make_mock_response

        targets = self._make_targets(2)
        mutations = [{"mutated_code": "def f(): return 2", "description": ""}]
        response = make_mock_response(mutations, input_tokens=100, output_tokens=50)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=response)

        config = LLMConfig(api_key="test-key", max_retries=0)
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            result = await _generate_mutations_async(config, targets, {}, 10, tmp_path)

        assert result == 2
        out = capsys.readouterr().out
        assert "2 API calls" in out

    async def test_targets_processed_in_sorted_order(self, tmp_path, capsys):
        from unittest.mock import patch, AsyncMock
        from mutmut_llm.pipeline import _generate_mutations_async
        from mutmut_llm.config import LLMConfig
        from mutmut_llm.scope import ScopeTarget
        from tests.conftest import make_mock_response

        # Create targets in unsorted order
        targets = [
            ScopeTarget(file_path="z_file.py", function_name="f", source="def f(): return 1", context=""),
            ScopeTarget(file_path="a_file.py", function_name="f", source="def f(): return 1", context=""),
        ]
        call_order = []

        async def mock_create(**kwargs):
            # Track which file is being processed via the content
            return make_mock_response([])

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=mock_create)

        config = LLMConfig(api_key="test-key", max_retries=0)
        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            await _generate_mutations_async(config, targets, {}, 10, tmp_path)

        # Verify a_file.py was cached before z_file.py (sorted order)
        from mutmut_llm.cache import list_cache_entries
        entries = list_cache_entries(base_dir=tmp_path)
        file_paths = [e.file_path for e in entries]
        assert file_paths.index("a_file.py") < file_paths.index("z_file.py")
