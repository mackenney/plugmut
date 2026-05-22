"""Base protocol and types for mutation generators."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Protocol
from typing import runtime_checkable

if TYPE_CHECKING:
    from mutmut_llm.library import Library


@dataclass
class GenerationStats:
    """Statistics from a generation run."""

    api_calls: int = 0
    mutations_generated: int = 0
    mutations_rejected: int = 0
    cached_skipped: int = 0
    cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


@runtime_checkable
class Generator(Protocol):
    """Protocol for mutation generators.

    Generators receive targets from Discovery, call an API (or other source)
    to generate mutations, and write results to Library.
    """

    def run(
        self,
        targets: list,
        budget_per_target: dict[str, int],
        library: Library,
        total_budget: int,
    ) -> GenerationStats:
        """Generate mutations for targets and write them to library.

        Contract:
        - MUST NOT make API calls if total_budget == 0
        - MUST skip targets that already have a valid library entry for this model
        - MUST write mutations via library.add(); MUST NOT write directly to disk
        - MAY process targets concurrently
        - MAY return before exhausting all targets if total_budget is reached

        Args:
            targets: List of GenerationTarget objects from Discovery
            budget_per_target: Dict mapping function_name to max mutations to generate
            library: Library instance for persisting mutations
            total_budget: Maximum total API calls allowed

        Returns:
            GenerationStats with counts and costs from the run
        """
        ...
