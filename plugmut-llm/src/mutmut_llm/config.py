"""LLM configuration loading.

Reads from ``[tool.plugmut.llm]`` in pyproject.toml + ``ANTHROPIC_API_KEY`` env var.

Supported pyproject.toml keys (all optional)::

    [tool.plugmut.llm]
    model = "claude-sonnet-4-6"
    min_mutations_per_function = 2
    max_mutations_per_function = 5
    max_tokens = 4096
    temperature = 0.6
    enabled = true
    cache_ttl = "5m"
    generator = "anthropic"
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # ty: ignore[unresolved-import]
    except ModuleNotFoundError:
        import tomli as tomllib  # ty: ignore[unresolved-import]


_VALID_CACHE_TTLS = {"5m", "1h"}


@dataclass
class LLMConfig:
    api_key: str = field(default="", repr=False)
    model: str = "claude-sonnet-4-6"
    generator: str = "anthropic"
    min_mutations_per_function: int = 2
    max_mutations_per_function: int = 5
    max_tokens: int = 4096
    temperature: float = 0.6
    enabled: bool = True
    cache_ttl: str = "5m"
    min_concurrency: int = 5
    max_concurrency: int = 20
    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    request_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.generator != "anthropic":
            raise ValueError(f"Unsupported generator={self.generator!r}. Only 'anthropic' is supported in v1.")
        if self.cache_ttl not in _VALID_CACHE_TTLS:
            raise ValueError(
                f"Invalid cache_ttl={self.cache_ttl!r}. Must be one of: {', '.join(sorted(_VALID_CACHE_TTLS))}"
            )
        if self.min_concurrency < 1:
            raise ValueError(f"min_concurrency must be >= 1, got {self.min_concurrency}")
        if self.max_concurrency < self.min_concurrency:
            raise ValueError(
                f"max_concurrency must be >= min_concurrency, got max={self.max_concurrency} < min={self.min_concurrency}"
            )
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got {self.max_retries}")
        if self.base_backoff_seconds <= 0:
            raise ValueError(f"base_backoff_seconds must be > 0, got {self.base_backoff_seconds}")
        if self.request_timeout_seconds < 10:
            raise ValueError(f"request_timeout_seconds must be >= 10, got {self.request_timeout_seconds}")
        if self.min_mutations_per_function > self.max_mutations_per_function:
            raise ValueError(
                f"min_mutations_per_function ({self.min_mutations_per_function}) must be \u2264 "
                f"max_mutations_per_function ({self.max_mutations_per_function})"
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
    """Return the ``[tool.plugmut.llm]`` dict, or ``{}`` if absent.

    Raises ValueError if ``[tool.mutmut.llm]`` exists without ``[tool.plugmut.llm]``.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    tool = data.get("tool", {})
    new_section = tool.get("plugmut", {}).get("llm", {})
    old_section = tool.get("mutmut", {}).get("llm", {})
    if old_section and not new_section:
        raise ValueError(
            "Config section [tool.mutmut.llm] is deprecated. Rename to [tool.plugmut.llm] in your pyproject.toml."
        )
    return new_section


def load_config(
    *,
    pyproject_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> LLMConfig:
    """Build an ``LLMConfig`` from pyproject.toml + environment.

    Priority (highest wins):
    1. Environment variable ``ANTHROPIC_API_KEY``
    2. ``[tool.plugmut.llm]`` in pyproject.toml
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
        if "generator" in section:
            gen = str(section["generator"])
            if gen != "anthropic":
                raise ValueError(f"Unsupported generator={gen!r}. Only 'anthropic' is supported in v1.")
            config.generator = gen
        if "min_mutations_per_function" in section:
            config.min_mutations_per_function = int(section["min_mutations_per_function"])
        if "max_mutations_per_function" in section:
            config.max_mutations_per_function = int(section["max_mutations_per_function"])
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
        if "min_concurrency" in section:
            config.min_concurrency = int(section["min_concurrency"])
        if "max_concurrency" in section:
            config.max_concurrency = int(section["max_concurrency"])
        if "max_retries" in section:
            config.max_retries = int(section["max_retries"])
        if "base_backoff_seconds" in section:
            config.base_backoff_seconds = float(section["base_backoff_seconds"])
        if "request_timeout_seconds" in section:
            config.request_timeout_seconds = int(section["request_timeout_seconds"])

    if not 0.0 <= config.temperature <= 1.0:
        raise ValueError(f"temperature must be in [0.0, 1.0], got {config.temperature}")

    config.api_key = env.get("ANTHROPIC_API_KEY", "")

    return config
