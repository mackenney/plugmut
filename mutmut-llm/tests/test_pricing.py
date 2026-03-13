"""Tests for mutmut_llm.pricing."""

from __future__ import annotations

import pytest

from mutmut_llm.pricing import MODEL_PRICING
from mutmut_llm.pricing import ModelPricing
from mutmut_llm.pricing import calculate_cost
from mutmut_llm.pricing import format_cost


class TestCalculateCost:
    def test_known_model_sonnet(self):
        cost = calculate_cost("claude-sonnet-4-6", 1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_known_model_haiku(self):
        cost = calculate_cost("claude-haiku-3-5-20241022", 10_000, 5_000)
        expected = (10_000 * 0.80 + 5_000 * 4.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_unknown_model_falls_back_with_warning(self):
        with pytest.warns(UserWarning, match="Unknown model"):
            cost = calculate_cost("unknown-model", 1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_zero_tokens_zero_cost(self):
        assert calculate_cost("claude-sonnet-4-6", 0, 0) == 0.0

    def test_all_models_have_positive_rates(self):
        for model, pricing in MODEL_PRICING.items():
            assert pricing.input_per_million > 0, f"{model} input rate must be positive"
            assert pricing.output_per_million > 0, (
                f"{model} output rate must be positive"
            )

    def test_cache_write_charges_1_25x(self):
        pricing = MODEL_PRICING["claude-sonnet-4-6"]
        cost = calculate_cost(
            "claude-sonnet-4-6", 0, 0, cache_creation_tokens=1_000_000
        )
        expected = 1_000_000 * pricing.cache_write_per_million / 1_000_000
        assert cost == pytest.approx(expected)
        assert pricing.cache_write_per_million == pytest.approx(3.0 * 1.25)

    def test_cache_read_charges_0_10x(self):
        pricing = MODEL_PRICING["claude-sonnet-4-6"]
        cost = calculate_cost("claude-sonnet-4-6", 0, 0, cache_read_tokens=1_000_000)
        expected = 1_000_000 * pricing.cache_read_per_million / 1_000_000
        assert cost == pytest.approx(expected)
        assert pricing.cache_read_per_million == pytest.approx(3.0 * 0.10)

    def test_combined_cache_and_uncached(self):
        cost = calculate_cost(
            "claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=2000,
            cache_read_tokens=3000,
        )
        p = MODEL_PRICING["claude-sonnet-4-6"]
        expected = (
            1000 * p.input_per_million
            + 500 * p.output_per_million
            + 2000 * p.cache_write_per_million
            + 3000 * p.cache_read_per_million
        ) / 1_000_000
        assert cost == pytest.approx(expected)

    def test_auto_derived_cache_pricing(self):
        for _model, pricing in MODEL_PRICING.items():
            assert pricing.cache_write_per_million == pytest.approx(
                pricing.input_per_million * 1.25
            )
            assert pricing.cache_read_per_million == pytest.approx(
                pricing.input_per_million * 0.10
            )

    def test_explicit_cache_pricing_preserved(self):
        p = ModelPricing(
            input_per_million=10.0,
            output_per_million=50.0,
            cache_write_per_million=7.0,
            cache_read_per_million=2.0,
        )
        assert p.cache_write_per_million == 7.0
        assert p.cache_read_per_million == 2.0

    def test_zero_defaults_derive_from_input(self):
        p = ModelPricing(input_per_million=10.0, output_per_million=50.0)
        assert p.cache_write_per_million == pytest.approx(12.5)
        assert p.cache_read_per_million == pytest.approx(1.0)


class TestFormatCost:
    def test_zero(self):
        assert format_cost(0.0) == "$0.00"

    def test_very_small(self):
        assert format_cost(0.00001) == "<$0.001"

    def test_small(self):
        assert format_cost(0.0042) == "$0.0042"

    def test_normal(self):
        assert format_cost(1.23) == "$1.23"

    def test_boundary(self):
        assert format_cost(0.001) == "$0.0010"
