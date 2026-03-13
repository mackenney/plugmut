"""Adversarial tests for prompt caching implementation.

Probes edge cases, backwards compatibility, pricing correctness,
TTL validation gaps, and double-counting risks.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from mutmut_llm.cache import CacheEntry, CachedMutation
from mutmut_llm.config import LLMConfig, load_config
from mutmut_llm.pipeline import _call_llm_and_validate
from mutmut_llm.pricing import MODEL_PRICING, ModelPricing, calculate_cost
from mutmut_llm.prompts import (
    SYSTEM_PROMPT,
    build_system_with_context,
    build_user_prompt,
)
from mutmut_llm.scope import ScopeTarget


def _make_mock_response(
    mutations: list[dict],
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 200,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> MagicMock:
    text_block = MagicMock()
    text_block.text = json.dumps(mutations)
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
    response.usage = MagicMock(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    return response


def _config(**kwargs) -> LLMConfig:
    defaults = {"api_key": "test-key", "enabled": True, "max_mutations_per_function": 3}
    defaults.update(kwargs)
    return LLMConfig(**defaults)


class TestSystemBlockStructure:
    """Verify system blocks match Anthropic's expected schema."""

    def test_block_has_required_keys_with_context(self):
        blocks = build_system_with_context("import os")
        for block in blocks:
            assert "type" in block
            assert "text" in block
            assert block["type"] == "text"

    def test_block_has_required_keys_without_context(self):
        blocks = build_system_with_context("")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"
        assert "text" in blocks[0]
        assert "cache_control" in blocks[0]

    def test_cache_control_only_on_last_block(self):
        blocks = build_system_with_context("import os")
        assert "cache_control" not in blocks[0]
        assert "cache_control" in blocks[-1]

    def test_cache_control_shape(self):
        blocks = build_system_with_context("ctx")
        cc = blocks[-1]["cache_control"]
        assert "type" in cc
        assert cc["type"] == "ephemeral"

    def test_no_extra_keys_in_blocks(self):
        """Anthropic API rejects unknown keys in content blocks."""
        blocks = build_system_with_context("ctx")
        allowed_keys = {"type", "text", "cache_control"}
        for block in blocks:
            assert set(block.keys()) <= allowed_keys


class TestEmptyContextHandling:
    def test_empty_string_produces_single_block(self):
        blocks = build_system_with_context("")
        assert len(blocks) == 1

    def test_none_context_produces_single_block(self):
        """None is falsy like empty string — should not crash."""
        blocks = build_system_with_context(None)  # type: ignore[arg-type]
        assert len(blocks) == 1
        assert "cache_control" in blocks[0]

    def test_whitespace_only_context_treated_as_empty(self):
        """Whitespace-only context is stripped and treated as no context."""
        blocks = build_system_with_context("   ")
        assert len(blocks) == 1
        assert "cache_control" in blocks[0]

    def test_cache_control_on_correct_block_no_context(self):
        blocks = build_system_with_context("")
        assert blocks[0]["cache_control"]["type"] == "ephemeral"
        assert blocks[0]["text"] == SYSTEM_PROMPT


class TestTTLValidation:
    def test_valid_5m_default(self):
        blocks = build_system_with_context("ctx", ttl="5m")
        assert "ttl" not in blocks[-1]["cache_control"]

    def test_valid_1h(self):
        blocks = build_system_with_context("ctx", ttl="1h")
        assert blocks[-1]["cache_control"]["ttl"] == "1h"

    def test_invalid_ttl_10m_raises(self):
        """10m is not a valid Anthropic TTL — must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="10m")

    def test_garbage_ttl_raises(self):
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="garbage")

    def test_empty_ttl_raises(self):
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="")

    def test_config_rejects_invalid_ttl(self):
        """LLMConfig validates cache_ttl on construction."""
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            LLMConfig(cache_ttl="999hours")

    def test_config_rejects_invalid_ttl_from_toml(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.mutmut.llm]\ncache_ttl = "10m"\n')
        with pytest.raises(ValueError, match="Invalid cache_ttl"):
            load_config(pyproject_path=pyproject, env={})


class TestPricingMath:
    def test_sonnet_cache_write_rate(self):
        p = MODEL_PRICING["claude-sonnet-4-6"]
        # $3/MTok input * 1.25 = $3.75/MTok cache write
        assert p.cache_write_per_million == pytest.approx(3.75)

    def test_sonnet_cache_read_rate(self):
        p = MODEL_PRICING["claude-sonnet-4-6"]
        # $3/MTok input * 0.10 = $0.30/MTok cache read
        assert p.cache_read_per_million == pytest.approx(0.30)

    def test_opus_cache_write_rate(self):
        p = MODEL_PRICING["claude-opus-4-6"]
        # $5/MTok input * 1.25 = $6.25/MTok
        assert p.cache_write_per_million == pytest.approx(6.25)

    def test_opus_cache_read_rate(self):
        p = MODEL_PRICING["claude-opus-4-6"]
        # $5/MTok * 0.10 = $0.50/MTok
        assert p.cache_read_per_million == pytest.approx(0.50)

    def test_explicit_cache_pricing_overrides_auto(self):
        """If explicit cache rates are given, __post_init__ should NOT override."""
        p = ModelPricing(
            input_per_million=3.0,
            output_per_million=15.0,
            cache_write_per_million=99.0,
            cache_read_per_million=88.0,
        )
        assert p.cache_write_per_million == 99.0
        assert p.cache_read_per_million == 88.0


class TestDoubleCountingTokens:
    """The Anthropic API returns input_tokens as ONLY non-cached tokens.
    cache_creation_input_tokens and cache_read_input_tokens are separate.
    Verify calculate_cost doesn't double-count.
    """

    def test_pure_cache_read_scenario(self):
        """All input comes from cache — input_tokens should be near 0."""
        cost = calculate_cost(
            "claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=100,
            cache_creation_tokens=0,
            cache_read_tokens=1000,
        )
        p = MODEL_PRICING["claude-sonnet-4-6"]
        expected = (
            100 * p.output_per_million + 1000 * p.cache_read_per_million
        ) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_mixed_cached_and_uncached(self):
        """Some tokens cached, some not — all three are separate line items."""
        cost = calculate_cost(
            "claude-sonnet-4-6",
            input_tokens=500,
            output_tokens=200,
            cache_creation_tokens=300,
            cache_read_tokens=700,
        )
        p = MODEL_PRICING["claude-sonnet-4-6"]
        expected = (
            500 * p.input_per_million
            + 200 * p.output_per_million
            + 300 * p.cache_write_per_million
            + 700 * p.cache_read_per_million
        ) / 1_000_000
        assert cost == pytest.approx(expected)

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

        # Pipeline should pass through raw values without adjustment
        assert result.input_tokens == 50
        assert result.cache_creation_tokens == 800
        assert result.cache_read_tokens == 200


class TestCacheEntryBackwardsCompat:
    def test_old_entry_without_cache_fields(self):
        """Entries cached before prompt caching lack cache_*_tokens fields."""
        old_data = {
            "function_name": "f",
            "file_path": "test.py",
            "source_hash": "abc123",
            "mutations": [{"mutated_code": "def f(): pass", "description": "d"}],
            "model": "claude-sonnet-4-6",
            "cost_usd": 0.001,
            "input_tokens": 100,
            "output_tokens": 50,
            "generated_at": "2025-01-01T00:00:00Z",
        }
        entry = CacheEntry.from_dict(old_data)
        assert entry.cache_creation_tokens == 0
        assert entry.cache_read_tokens == 0

    def test_old_entry_without_any_optional_fields(self):
        """Minimal entry with only required fields."""
        minimal_data = {
            "function_name": "f",
            "file_path": "test.py",
            "source_hash": "abc123",
            "mutations": [],
        }
        entry = CacheEntry.from_dict(minimal_data)
        assert entry.model == ""
        assert entry.cost_usd == 0.0
        assert entry.cache_creation_tokens == 0
        assert entry.cache_read_tokens == 0

    def test_roundtrip_preserves_cache_fields(self):
        entry = CacheEntry(
            function_name="f",
            file_path="test.py",
            source_hash="abc",
            mutations=[CachedMutation("def f(): pass", "d")],
            cache_creation_tokens=500,
            cache_read_tokens=300,
        )
        data = entry.to_dict()
        restored = CacheEntry.from_dict(data)
        assert restored.cache_creation_tokens == 500
        assert restored.cache_read_tokens == 300


class TestBuildUserPromptNoContext:
    def test_no_context_in_user_prompt(self):
        """User prompt contains only the function source, no file context."""
        prompt = build_user_prompt("def f(): pass")
        assert "File context" not in prompt


class TestSortStability:
    def test_same_file_preserves_order(self):
        """Multiple functions in the same file should maintain original order after sort."""
        targets = [
            ScopeTarget(
                file_path="same.py",
                function_name="z_func",
                source="def z_func(): pass\n",
            ),
            ScopeTarget(
                file_path="same.py",
                function_name="a_func",
                source="def a_func(): pass\n",
            ),
            ScopeTarget(
                file_path="same.py",
                function_name="m_func",
                source="def m_func(): pass\n",
            ),
        ]
        sorted_targets = sorted(targets, key=lambda t: t.file_path)
        # Stable sort preserves insertion order for equal keys
        assert [t.function_name for t in sorted_targets] == [
            "z_func",
            "a_func",
            "m_func",
        ]

    def test_sort_groups_by_file_for_caching(self):
        """Functions from same file should be grouped together for cache locality."""
        targets = [
            ScopeTarget(
                file_path="b.py", function_name="b1", source="def b1(): pass\n"
            ),
            ScopeTarget(
                file_path="a.py", function_name="a1", source="def a1(): pass\n"
            ),
            ScopeTarget(
                file_path="b.py", function_name="b2", source="def b2(): pass\n"
            ),
            ScopeTarget(
                file_path="a.py", function_name="a2", source="def a2(): pass\n"
            ),
        ]
        sorted_targets = sorted(targets, key=lambda t: t.file_path)
        file_order = [t.file_path for t in sorted_targets]
        assert file_order == ["a.py", "a.py", "b.py", "b.py"]
        # Within same file, original order preserved
        a_funcs = [t.function_name for t in sorted_targets if t.file_path == "a.py"]
        assert a_funcs == ["a1", "a2"]


class TestCacheHitLogging:
    def test_no_cache_tokens_no_log(self, tmp_path, capsys):
        """When no cache tokens at all, cache hit line should not appear."""
        from unittest.mock import patch

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

    def test_all_cache_read_shows_correct_percent(self, tmp_path, capsys):
        from unittest.mock import patch

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
        from unittest.mock import patch

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


class TestExplicitCachePricingNotOverridden:
    """Zero default triggers auto-derivation; explicit nonzero values are preserved."""

    def test_zero_default_triggers_derivation(self):
        p = ModelPricing(
            input_per_million=3.0,
            output_per_million=15.0,
        )
        assert p.cache_write_per_million == pytest.approx(3.0 * 1.25)
        assert p.cache_read_per_million == pytest.approx(3.0 * 0.10)

    def test_nonzero_cache_pricing_preserved(self):
        p = ModelPricing(
            input_per_million=3.0,
            output_per_million=15.0,
            cache_write_per_million=5.0,
            cache_read_per_million=1.0,
        )
        assert p.cache_write_per_million == 5.0
        assert p.cache_read_per_million == 1.0


class TestUsageFieldExtraction:
    """Verify the pipeline correctly reads Anthropic's usage field names."""

    def test_usage_field_names_match_anthropic_api(self):
        """Anthropic returns cache_creation_input_tokens and cache_read_input_tokens."""
        target = ScopeTarget(
            file_path="test.py",
            function_name="f",
            source="def f(x):\n    return x + 1\n",
        )
        mutations = [
            {"mutated_code": "def f(x):\n    return x - 1", "description": "d"}
        ]

        usage = MagicMock()
        usage.input_tokens = 50
        usage.output_tokens = 100
        usage.cache_creation_input_tokens = 800
        usage.cache_read_input_tokens = 200

        text_block = MagicMock()
        text_block.text = json.dumps(mutations)
        response = MagicMock()
        response.content = [text_block]
        response.stop_reason = "end_turn"
        response.usage = usage

        mock_client = MagicMock()
        mock_client.messages.create.return_value = response

        result = _call_llm_and_validate(mock_client, _config(), target, max_mutations=3)
        assert result.cache_creation_tokens == 800
        assert result.cache_read_tokens == 200

    def test_missing_cache_fields_in_usage_default_to_zero(self):
        """If Anthropic doesn't return cache fields (old API), getattr defaults to 0."""
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
