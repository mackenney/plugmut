"""Tests for mutmut_llm.pricing."""

from __future__ import annotations

import pytest

from mutmut_llm.pricing import MODEL_PRICING, calculate_cost, format_cost


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
