"""Model pricing table and cost calculation.

Prices are hardcoded — Anthropic has no pricing API.
Historical cache entries keep the cost they were generated at.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


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


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for a single API call."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        warnings.warn(f"Unknown model '{model}', using Sonnet pricing", stacklevel=2)
        pricing = MODEL_PRICING[_DEFAULT_PRICING_KEY]
    return (
        input_tokens * pricing.input_per_million
        + output_tokens * pricing.output_per_million
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
