"""mutmut-llm plugin: LLM-powered mutation operator for mutmut.

Registers:
- ``operator_llm`` (FunctionDef operator) via ``mutmut_register_operators``
- ``mutmut generate`` CLI command via ``mutmut_register_commands``
- Config loading via ``mutmut_configure``
"""

from __future__ import annotations

import click
import libcst as cst

from mutmut.hookspecs import hookimpl
from mutmut.node_mutation import OPERATORS_TYPE

from mutmut_llm.config import LLMConfig, load_config
from mutmut_llm.operators import operator_llm

_llm_config: LLMConfig | None = None
_mutmut_paths: list[str] = []


@hookimpl
def mutmut_configure(config: object) -> None:
    global _llm_config, _mutmut_paths
    _llm_config = load_config()
    if hasattr(config, "paths_to_mutate"):
        _mutmut_paths = [str(p) for p in config.paths_to_mutate]


@hookimpl
def mutmut_register_operators() -> OPERATORS_TYPE:
    if _llm_config and _llm_config.enabled:
        return [(cst.FunctionDef, operator_llm)]
    return []


@hookimpl
def mutmut_register_commands(cli_group: object) -> None:
    @cli_group.command()  # type: ignore[union-attr]
    @click.option("--budget", type=int, default=20, help="Max API calls.")
    @click.option("--dry-run", is_flag=True, help="Show functions without calling LLM.")
    @click.option(
        "--paths", multiple=True, help="Paths to scan (overrides mutmut config)."
    )
    def generate(budget: int, dry_run: bool, paths: tuple[str, ...]) -> None:
        """Generate LLM mutations for functions in scope."""
        from mutmut_llm.pipeline import run_generation

        config = _llm_config or load_config()
        scan_paths = list(paths) if paths else (_mutmut_paths or ["src"])
        run_generation(config=config, paths=scan_paths, budget=budget, dry_run=dry_run)
