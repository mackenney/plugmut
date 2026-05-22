"""Library: validated storage for pre-generated LLM mutations.

Single validation gate and storage interface. All mutation persistence goes
through Library.add(), which enforces syntax → imports → pragmas validation.

Storage path: .plugmut-llm/entries/ (relative to base_dir).
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass
from pathlib import Path

from mutmut_llm._io import atomic_write
from mutmut_llm.validation import validate_mutation


def source_hash(source: str) -> str:
    """SHA-256 hash of function source, truncated to 16 hex chars."""
    return hashlib.sha256(source.strip().encode()).hexdigest()[:16]


def _entry_filename(file_path: str, function_name: str, src_hash: str, model: str) -> str:
    """Deterministic filename from (file_path, function_name, source_hash, model)."""
    key = f"{file_path}\0{function_name}\0{src_hash}\0{model}"
    return hashlib.sha256(key.encode()).hexdigest()[:32] + ".json"


@dataclass
class LibraryEntry:
    function_name: str
    file_path: str
    source_hash: str
    model: str
    mutations: list[dict]
    metadata: dict | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "function_name": self.function_name,
            "file_path": self.file_path,
            "source_hash": self.source_hash,
            "model": self.model,
            "mutations": self.mutations,
        }
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict) -> LibraryEntry:
        return cls(
            function_name=data["function_name"],
            file_path=data["file_path"],
            source_hash=data["source_hash"],
            model=data["model"],
            mutations=data.get("mutations", []),
            metadata=data.get("metadata"),
        )


class Library:
    def __init__(self, base_dir: Path = Path(".")) -> None:
        self._base_dir = base_dir
        self._entries_dir = base_dir / ".plugmut-llm" / "entries"
        self._index: dict[str, list[LibraryEntry]] | None = None

    def add(
        self,
        function_name: str,
        file_path: str,
        source: str,
        mutations: list[dict],
        model: str,
        metadata: dict | None = None,
    ) -> list[LibraryEntry]:
        """Validate each mutation, persist valid ones, return entries written."""
        src_hash = source_hash(source)

        valid_mutations: list[dict] = []
        for mutation in mutations:
            mutated_code = mutation.get("mutated_code", "")
            err = validate_mutation(mutated_code, source)
            if err is None:
                valid_mutations.append(mutation)
            else:
                warnings.warn(f"Mutation rejected for {function_name!r} in {file_path!r}: {err}")

        if not valid_mutations:
            return []

        entry = LibraryEntry(
            function_name=function_name,
            file_path=file_path,
            source_hash=src_hash,
            model=model,
            mutations=valid_mutations,
            metadata=metadata,
        )

        filename = _entry_filename(file_path, function_name, src_hash, model)
        self._entries_dir.mkdir(parents=True, exist_ok=True)
        path = self._entries_dir / filename
        atomic_write(path, json.dumps(entry.to_dict(), indent=2))

        # Invalidate lazy index so next query/list_all picks up new entry.
        self._index = None

        return [entry]

    def query(self, source_hash_: str) -> list[LibraryEntry]:
        """Return all entries matching source_hash, across all models."""
        self._ensure_index()
        assert self._index is not None
        return list(self._index.get(source_hash_, []))

    def list_all(self) -> list[LibraryEntry]:
        """Return all valid entries. Corrupt files are skipped with a warning."""
        self._ensure_index()
        assert self._index is not None
        result: list[LibraryEntry] = []
        for entries in self._index.values():
            result.extend(entries)
        return result

    def clear(self) -> int:
        """Remove all .json entry files. Return count removed."""
        if not self._entries_dir.exists():
            return 0
        count = 0
        for path in self._entries_dir.glob("*.json"):
            path.unlink()
            count += 1
        self._index = None
        return count

    def _ensure_index(self) -> None:
        if self._index is None:
            self._build_index()

    def _build_index(self) -> None:
        """Walk entries_dir, parse each JSON file, build source_hash → entries index."""
        index: dict[str, list[LibraryEntry]] = {}
        if not self._entries_dir.exists():
            self._index = index
            return

        for path in sorted(self._entries_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                entry = LibraryEntry.from_dict(data)
            except (json.JSONDecodeError, KeyError) as exc:
                warnings.warn(f"Skipping corrupt library entry {path}: {exc}")
                continue
            src_hash = entry.source_hash
            index.setdefault(src_hash, []).append(entry)

        self._index = index
