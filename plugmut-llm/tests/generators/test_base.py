"""Tests for generator base protocol and types."""

from mutmut_llm.generators import GenerationStats
from mutmut_llm.generators import Generator


def test_generation_stats_defaults():
    stats = GenerationStats()
    assert stats.api_calls == 0
    assert stats.mutations_generated == 0
    assert stats.errors == []


def test_generation_stats_with_values():
    stats = GenerationStats(
        api_calls=5,
        mutations_generated=10,
        cost_usd=0.05,
    )
    assert stats.api_calls == 5
    assert stats.mutations_generated == 10
    assert stats.cost_usd == 0.05


def test_generator_is_runtime_checkable():
    class FakeGenerator:
        def run(self, targets, budget_per_target, library, total_budget):
            return GenerationStats()

    assert isinstance(FakeGenerator(), Generator)
