"""File-based cache for pre-generated LLM mutations.

Zero mutmut imports — stdlib only (hashlib, json, pathlib).
Cache lives in ``.mutmut-cache/llm/`` relative to the project root.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from mutmut_llm._io import atomic_write

CACHE_DIR = Path(".mutmut-cache") / "llm"


@dataclass
class CachedMutation:
    mutated_code: str
    description: str


@dataclass
class CacheEntry:
    function_name: str
    file_path: str
    source_hash: str
    mutations: list[CachedMutation]
    model: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "function_name": self.function_name,
            "file_path": self.file_path,
            "source_hash": self.source_hash,
            "mutations": [asdict(m) for m in self.mutations],
            "model": self.model,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CacheEntry:
        mutations = [CachedMutation(**m) for m in data.get("mutations", [])]
        return cls(
            function_name=data["function_name"],
            file_path=data["file_path"],
            source_hash=data["source_hash"],
            mutations=mutations,
            model=data.get("model", ""),
            cost_usd=data.get("cost_usd", 0.0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_tokens=data.get("cache_creation_tokens", 0),
            cache_read_tokens=data.get("cache_read_tokens", 0),
            generated_at=data.get("generated_at", ""),
        )


def source_hash(source: str) -> str:
    """SHA-256 hash of function source, truncated to 16 hex chars."""
    return hashlib.sha256(source.strip().encode()).hexdigest()[:16]


def _cache_key(
    file_path: str, function_name: str, src_hash: str, model: str = ""
) -> str:
    safe_path = file_path.replace("/", "_").replace("\\", "_")
    if model:
        safe_model = (
            model.replace("/", "-slash-").replace("\\", "-bslash-").replace("_", "-u-")
        )
        return f"{safe_path}__{function_name}__{src_hash}__{safe_model}"
    return f"{safe_path}__{function_name}__{src_hash}"


def _cache_dir(base_dir: Path) -> Path:
    return base_dir / CACHE_DIR


def write_cache_entry(entry: CacheEntry, base_dir: Path = Path(".")) -> Path:
    """Write a cache entry to disk. Returns the path written."""
    d = _cache_dir(base_dir)
    d.mkdir(parents=True, exist_ok=True)

    key = _cache_key(
        entry.file_path, entry.function_name, entry.source_hash, entry.model
    )
    path = d / f"{key}.json"
    atomic_write(path, json.dumps(entry.to_dict(), indent=2))
    return path


def read_cache_entry(
    file_path: str,
    function_name: str,
    src_hash: str,
    base_dir: Path = Path("."),
    model: str | None = None,
) -> CacheEntry | None:
    """Read a cache entry. Returns None if not found or hash mismatch.

    When *model* is provided, looks up the exact model's entry on disk.
    When *model* is None, scans for any matching entry (backwards-compatible).
    """
    if model is None:
        return _read_any_matching_entry(file_path, function_name, src_hash, base_dir)

    key = _cache_key(file_path, function_name, src_hash, model)
    path = _cache_dir(base_dir) / f"{key}.json"

    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        entry = CacheEntry.from_dict(data)
        if entry.source_hash != src_hash:
            return None
        return entry
    except (json.JSONDecodeError, KeyError):
        return None


def _read_any_matching_entry(
    file_path: str,
    function_name: str,
    src_hash: str,
    base_dir: Path,
) -> CacheEntry | None:
    """Scan cache directory for any entry matching (file_path, function_name, src_hash)."""
    key = _cache_key(file_path, function_name, src_hash, "")
    path = _cache_dir(base_dir) / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            entry = CacheEntry.from_dict(data)
            if entry.source_hash == src_hash:
                return entry
        except (json.JSONDecodeError, KeyError):
            pass

    d = _cache_dir(base_dir)
    if not d.exists():
        return None
    safe_path = file_path.replace("/", "_").replace("\\", "_")
    prefix = f"{safe_path}__{function_name}__{src_hash}"
    for path in sorted(d.glob(f"{prefix}__*.json")):
        try:
            data = json.loads(path.read_text())
            entry = CacheEntry.from_dict(data)
            if entry.source_hash == src_hash:
                return entry
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def list_cache_entries(base_dir: Path = Path(".")) -> list[CacheEntry]:
    """List all valid cache entries."""
    d = _cache_dir(base_dir)
    if not d.exists():
        return []

    entries = []
    for path in sorted(d.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            entries.append(CacheEntry.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return entries


def clear_cache(base_dir: Path = Path(".")) -> int:
    """Remove all cache entries. Returns count of removed files."""
    d = _cache_dir(base_dir)
    if not d.exists():
        return 0

    count = 0
    for path in d.glob("*.json"):
        path.unlink()
        count += 1
    return count
