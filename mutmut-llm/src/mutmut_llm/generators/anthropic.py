"""Anthropic generator implementation (stub - to be completed in step-04)."""
from __future__ import annotations

from mutmut_llm.generators.base import Generator, GenerationStats


class AnthropicGenerator:
    """Anthropic Claude generator for mutations.

    This is a stub implementation. The full implementation will be
    extracted from pipeline.py in step-04.
    """

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key

    def run(
        self,
        targets: list,
        budget_per_target: dict[str, int],
        library: "Library",  # type: ignore[name-defined]
        total_budget: int,
    ) -> GenerationStats:
        """Generate mutations using Anthropic Claude API.

        Stub implementation - raises NotImplementedError.
        Full implementation in step-04.
        """
        raise NotImplementedError("AnthropicGenerator.run() not yet implemented - see step-04")
