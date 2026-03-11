"""Tests for mutmut_llm.pipeline."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mutmut_llm.cache import list_cache_entries
from mutmut_llm.config import LLMConfig
from mutmut_llm.pipeline import GenerationResult, _call_llm_and_validate, run_generation
from mutmut_llm.scope import ScopeTarget


def _make_mock_response(
    mutations: list[dict], stop_reason: str = "end_turn"
) -> MagicMock:
    """Create a mock Anthropic API response."""
    text_block = MagicMock()
    text_block.text = json.dumps(mutations)
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(input_tokens=100, output_tokens=200)
    return response


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
    @patch("anthropic.Anthropic")
    def test_generate_skips_cached_model(self, MockAnthropic, sample_project, capsys):
        """Second run with same model makes zero API calls."""
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

        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)
        first_count = mock_client.messages.create.call_count

        mock_client.messages.create.reset_mock()
        run_generation(config, paths=[str(src)], budget=10, base_dir=tmp_path)

        assert mock_client.messages.create.call_count == 0

    @patch("anthropic.Anthropic")
    def test_generate_runs_for_new_model(self, MockAnthropic, sample_project, capsys):
        """Switching model generates new entries; old model's entries remain on disk."""
        tmp_path, src = sample_project

        mutations = [
            {
                "mutated_code": "def greet(name):\n    return 'Hi'",
                "description": "simplify",
            }
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_mock_response(mutations)
        MockAnthropic.return_value = mock_client

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
