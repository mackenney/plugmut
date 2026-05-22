"""Model pricing table and cost calculation.

Prices are hardcoded — Anthropic has no pricing API.
Historical cache entries keep the cost they were generated at.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from dataclasses import field


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cache_write_per_million: float = field(default=0.0)
    cache_read_per_million: float = field(default=0.0)

    def __post_init__(self) -> None:
        if self.cache_write_per_million == 0.0:
            object.__setattr__(self, "cache_write_per_million", self.input_per_million * 1.25)
        if self.cache_read_per_million == 0.0:
            object.__setattr__(self, "cache_read_per_million", self.input_per_million * 0.10)


MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-4-6": ModelPricing(5.0, 25.0),
    "claude-opus-4-5-20250514": ModelPricing(5.0, 25.0),
    "claude-opus-4-1-20250414": ModelPricing(15.0, 75.0),
    "claude-sonnet-4-6": ModelPricing(3.0, 15.0),
    "claude-sonnet-4-5-20250514": ModelPricing(3.0, 15.0),
    "claude-haiku-4-5-20251001": ModelPricing(1.0, 5.0),
    "claude-haiku-3-5-20241022": ModelPricing(0.80, 4.0),
}

_DEFAULT_PRICING_KEY = "claude-sonnet-4-6"


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Return USD cost for a single API call, including prompt cache costs."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        warnings.warn(f"Unknown model '{model}', using Sonnet pricing", stacklevel=2)
        pricing = MODEL_PRICING[_DEFAULT_PRICING_KEY]
    return (
        input_tokens * pricing.input_per_million
        + output_tokens * pricing.output_per_million
        + cache_creation_tokens * pricing.cache_write_per_million
        + cache_read_tokens * pricing.cache_read_per_million
    ) / 1_000_000


def format_cost(cost_usd: float) -> str:
    """Format cost for display: '$0.0042' or '<$0.001'."""
    if cost_usd == 0.0:
        return "$0.00"
    if cost_usd < 0.001:
        return "<$0.001"
    if cost_usd >= 0.01:
        return f"${cost_usd:.2f}"
    return f"${cost_usd:.4f}"
