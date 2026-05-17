"""Tests for AnthropicGenerator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch


from mutmut_llm.config import LLMConfig
from mutmut_llm.discovery import GenerationTarget
from mutmut_llm.generators.anthropic import (
    AnthropicGenerator,
    ErrorAction,
    classify_error,
)
from mutmut_llm.generators.base import GenerationStats
from mutmut_llm.library import Library


def _config(**kwargs) -> LLMConfig:
    return LLMConfig(api_key="test-key", max_retries=0, **kwargs)


def _target(
    file_path: str = "f.py",
    function_name: str = "f",
    source: str = "def f():\n    return 1\n",
    context: str = "",
) -> GenerationTarget:
    return GenerationTarget(
        file_path=file_path,
        function_name=function_name,
        source=source,
        context=context,
    )


class TestAnthropicGeneratorInit:
    def test_defaults_set(self):
        gen = AnthropicGenerator()
        assert gen._config is not None
        assert isinstance(gen._config, LLMConfig)

    def test_custom_config_stored(self):
        config = _config(model="claude-opus-4-6")
        gen = AnthropicGenerator(config=config)
        assert gen._config.model == "claude-opus-4-6"

    def test_run_method_exists(self):
        import inspect

        gen = AnthropicGenerator()
        assert "run" in [m for m, _ in inspect.getmembers(gen)]


class TestAnthropicGeneratorRunZeroBudget:
    def test_zero_budget_returns_empty_stats(self):
        gen = AnthropicGenerator(config=_config())
        stats = gen.run(
            targets=[], budget_per_target={}, library=MagicMock(), total_budget=0
        )
        assert isinstance(stats, GenerationStats)
        assert stats.api_calls == 0
        assert stats.mutations_generated == 0

    def test_zero_budget_makes_no_api_calls(self):
        mock_library = MagicMock()
        gen = AnthropicGenerator(config=_config())
        gen.run(
            targets=[_target()],
            budget_per_target={},
            library=mock_library,
            total_budget=0,
        )
        mock_library.query.assert_not_called()


class TestAnthropicGeneratorRunWithMockedApi:
    def test_run_generates_mutations(self, tmp_path):
        from tests.conftest import make_mock_response

        mutations = [
            {
                "mutated_code": "def f():\n    return 2\n",
                "description": "change constant",
            }
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_mock_response(mutations)
        )

        target = _target(source="def f():\n    return 1\n")
        library = Library(base_dir=tmp_path)
        config = _config()
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            stats = gen.run([target], {"f.py::f": 3}, library, total_budget=10)

        assert stats.api_calls == 1
        assert stats.mutations_generated == 1
        assert mock_client.messages.create.call_count == 1

    def test_run_skips_cached_target(self, tmp_path):

        source = "def f():\n    return 1\n"
        target = _target(source=source)
        library = Library(base_dir=tmp_path)
        config = _config()

        mutations = [
            {"mutated_code": "def f():\n    return 2\n", "description": "change"}
        ]
        library.add("f", "f.py", source, mutations, config.model)

        mock_client = AsyncMock()
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            stats = gen.run([target], {"f.py::f": 3}, library, total_budget=10)

        assert stats.api_calls == 0
        mock_client.messages.create.assert_not_called()

    def test_run_budget_limits_calls(self, tmp_path):
        from tests.conftest import make_mock_response

        mutations = [
            {"mutated_code": "def f():\n    return 2\n", "description": "change"}
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_mock_response(mutations)
        )

        targets = [
            _target(
                file_path=f"f{i}.py",
                function_name="f",
                source="def f():\n    return 1\n",
            )
            for i in range(3)
        ]
        library = Library(base_dir=tmp_path)
        config = _config()
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            stats = gen.run(targets, {}, library, total_budget=1)

        assert stats.api_calls == 1

    def test_run_writes_to_library(self, tmp_path):
        from tests.conftest import make_mock_response

        source = "def f():\n    return 1\n"
        mutations = [
            {"mutated_code": "def f():\n    return 2\n", "description": "change"}
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_mock_response(mutations)
        )

        target = _target(source=source)
        library = Library(base_dir=tmp_path)
        config = _config()
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            gen.run([target], {"f.py::f": 3}, library, total_budget=10)

        all_entries = library.list_all()
        assert len(all_entries) == 1
        assert len(all_entries[0].mutations) == 1

    def test_run_returns_cost_stats(self, tmp_path):
        from tests.conftest import make_mock_response

        mutations = [
            {"mutated_code": "def f():\n    return 2\n", "description": "change"}
        ]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_mock_response(
                mutations, input_tokens=100, output_tokens=50
            )
        )

        target = _target(source="def f():\n    return 1\n")
        library = Library(base_dir=tmp_path)
        config = _config()
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            stats = gen.run([target], {"f.py::f": 3}, library, total_budget=10)

        assert stats.cost_usd > 0


class TestAnthropicGeneratorCacheSeparation:
    def test_different_models_not_shared(self, tmp_path):
        """A cached entry for model-A does not suppress generation for model-B."""
        from tests.conftest import make_mock_response

        source = "def f():\n    return 1\n"
        target = _target(source=source)
        library = Library(base_dir=tmp_path)

        mutations = [
            {"mutated_code": "def f():\n    return 2\n", "description": "change"}
        ]
        library.add("f", "f.py", source, mutations, "claude-opus-4-6")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=make_mock_response(mutations)
        )

        config = _config(model="claude-sonnet-4-6")
        gen = AnthropicGenerator(config=config)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            stats = gen.run([target], {"f.py::f": 3}, library, total_budget=10)

        assert stats.api_calls == 1


class TestErrorActionImport:
    def test_error_action_importable(self):
        assert ErrorAction.RETRY
        assert ErrorAction.SKIP
        assert ErrorAction.STOP

    def test_classify_error_importable(self):
        assert callable(classify_error)
