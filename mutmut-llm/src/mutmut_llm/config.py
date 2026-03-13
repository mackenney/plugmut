"""LLM configuration loading.

Reads from ``[tool.mutmut.llm]`` in pyproject.toml + ``ANTHROPIC_API_KEY`` env var.

Supported pyproject.toml keys (all optional)::

    [tool.mutmut.llm]
    model = "claude-sonnet-4-6"
    max_mutations_per_function = 5
    max_tokens = 4096
    temperature = 0.6
    enabled = true
    cache_ttl = "5m"
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef,import-not-found]


_VALID_CACHE_TTLS = {"5m", "1h"}


@dataclass
class LLMConfig:
    api_key: str = field(default="", repr=False)
    model: str = "claude-sonnet-4-6"
    max_mutations_per_function: int = 5
    max_tokens: int = 4096
    temperature: float = 0.6
    enabled: bool = True
    cache_ttl: str = "5m"

    def __post_init__(self) -> None:
        if self.cache_ttl not in _VALID_CACHE_TTLS:
            raise ValueError(
                f"Invalid cache_ttl={self.cache_ttl!r}. Must be one of: {', '.join(sorted(_VALID_CACHE_TTLS))}"
            )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


def find_pyproject(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) to find pyproject.toml."""
    current = start or Path.cwd()
    for parent in (current, *current.parents):
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def read_toml_section(path: Path) -> dict:
    """Return the ``[tool.mutmut.llm]`` dict, or ``{}`` if absent."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("tool", {}).get("mutmut", {}).get("llm", {})


def load_config(
    *,
    pyproject_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> LLMConfig:
    """Build an ``LLMConfig`` from pyproject.toml + environment.

    Priority (highest wins):
    1. Environment variable ``ANTHROPIC_API_KEY``
    2. ``[tool.mutmut.llm]`` in pyproject.toml
    3. Dataclass defaults
    """
    if env is None:
        env = os.environ

    config = LLMConfig()

    toml_path = pyproject_path or find_pyproject()
    if toml_path is not None:
        section = read_toml_section(toml_path)
        if "model" in section:
            config.model = str(section["model"])
        if "max_mutations_per_function" in section:
            config.max_mutations_per_function = int(
                section["max_mutations_per_function"]
            )
        if "max_tokens" in section:
            config.max_tokens = int(section["max_tokens"])
        if "temperature" in section:
            config.temperature = float(section["temperature"])
        if "enabled" in section:
            config.enabled = bool(section["enabled"])
        if "cache_ttl" in section:
            ttl = str(section["cache_ttl"])
            if ttl not in _VALID_CACHE_TTLS:
                raise ValueError(
                    f"Invalid cache_ttl={ttl!r} in pyproject.toml. Must be one of: {', '.join(sorted(_VALID_CACHE_TTLS))}"
                )
            config.cache_ttl = ttl

    if not 0.0 <= config.temperature <= 1.0:
        raise ValueError(f"temperature must be in [0.0, 1.0], got {config.temperature}")

    config.api_key = env.get("ANTHROPIC_API_KEY", "")

    return config
