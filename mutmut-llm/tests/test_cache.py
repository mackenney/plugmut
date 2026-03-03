"""Tests for mutmut_llm.cache: write/read round-trip, hash keying, missing entries."""

from __future__ import annotations

import json


from mutmut_llm.cache import CACHE_DIR
from mutmut_llm.cache import CacheEntry
from mutmut_llm.cache import CachedMutation
from mutmut_llm.cache import clear_cache
from mutmut_llm.cache import list_cache_entries
from mutmut_llm.cache import read_cache_entry
from mutmut_llm.cache import source_hash
from mutmut_llm.cache import write_cache_entry


def _make_entry(
    function_name: str = "foo",
    file_path: str = "src/module.py",
    source: str = "def foo(): return 1",
    mutations: list[CachedMutation] | None = None,
    model: str = "claude-sonnet-4-6",
) -> CacheEntry:
    return CacheEntry(
        function_name=function_name,
        file_path=file_path,
        source_hash=source_hash(source),
        mutations=mutations
        or [
            CachedMutation(
                mutated_code="def foo(): return 2", description="change return value"
            )
        ],
        model=model,
    )


# ---------------------------------------------------------------------------
# source_hash
# ---------------------------------------------------------------------------


class TestSourceHash:
    def test_deterministic(self):
        assert source_hash("def foo(): pass") == source_hash("def foo(): pass")

    def test_strips_whitespace(self):
        assert source_hash("  def foo(): pass  ") == source_hash("def foo(): pass")

    def test_different_sources_differ(self):
        assert source_hash("def foo(): pass") != source_hash("def bar(): pass")

    def test_length_is_16(self):
        h = source_hash("anything")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Write + Read round-trip
# ---------------------------------------------------------------------------


class TestWriteRead:
    def test_round_trip(self, tmp_path):
        entry = _make_entry()
        path = write_cache_entry(entry, base_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".json"

        loaded = read_cache_entry(
            entry.file_path, entry.function_name, entry.source_hash, base_dir=tmp_path
        )
        assert loaded is not None
        assert loaded.function_name == entry.function_name
        assert loaded.file_path == entry.file_path
        assert loaded.source_hash == entry.source_hash
        assert loaded.model == entry.model
        assert len(loaded.mutations) == 1
        assert loaded.mutations[0].mutated_code == "def foo(): return 2"
        assert loaded.mutations[0].description == "change return value"

    def test_multiple_mutations(self, tmp_path):
        mutations = [
            CachedMutation(mutated_code="def foo(): return 0", description="zero"),
            CachedMutation(mutated_code="def foo(): return -1", description="negative"),
            CachedMutation(mutated_code="def foo(): pass", description="delete body"),
        ]
        entry = _make_entry(mutations=mutations)
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path, entry.function_name, entry.source_hash, base_dir=tmp_path
        )
        assert loaded is not None
        assert len(loaded.mutations) == 3
        assert [m.description for m in loaded.mutations] == [
            "zero",
            "negative",
            "delete body",
        ]

    def test_cache_creates_directory(self, tmp_path):
        entry = _make_entry()
        write_cache_entry(entry, base_dir=tmp_path)
        assert (tmp_path / CACHE_DIR).is_dir()

    def test_overwrite_existing(self, tmp_path):
        entry1 = _make_entry(
            mutations=[CachedMutation(mutated_code="v1", description="first")]
        )
        entry2 = _make_entry(
            mutations=[CachedMutation(mutated_code="v2", description="second")]
        )

        write_cache_entry(entry1, base_dir=tmp_path)
        write_cache_entry(entry2, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry2.file_path,
            entry2.function_name,
            entry2.source_hash,
            base_dir=tmp_path,
        )
        assert loaded is not None
        assert loaded.mutations[0].mutated_code == "v2"


# ---------------------------------------------------------------------------
# Hash keying (stale cache detection)
# ---------------------------------------------------------------------------


class TestHashKeying:
    def test_wrong_hash_returns_none(self, tmp_path):
        entry = _make_entry(source="def foo(): return 1")
        write_cache_entry(entry, base_dir=tmp_path)

        different_hash = source_hash("def foo(): return 999")
        loaded = read_cache_entry(
            entry.file_path, entry.function_name, different_hash, base_dir=tmp_path
        )
        assert loaded is None

    def test_same_function_different_source_is_separate(self, tmp_path):
        entry1 = _make_entry(source="def foo(): return 1")
        entry2 = _make_entry(source="def foo(): return 2")

        write_cache_entry(entry1, base_dir=tmp_path)
        write_cache_entry(entry2, base_dir=tmp_path)

        loaded1 = read_cache_entry(
            entry1.file_path,
            entry1.function_name,
            entry1.source_hash,
            base_dir=tmp_path,
        )
        loaded2 = read_cache_entry(
            entry2.file_path,
            entry2.function_name,
            entry2.source_hash,
            base_dir=tmp_path,
        )
        assert loaded1 is not None
        assert loaded2 is not None
        assert loaded1.source_hash != loaded2.source_hash


# ---------------------------------------------------------------------------
# Missing entries
# ---------------------------------------------------------------------------


class TestMissing:
    def test_read_nonexistent_returns_none(self, tmp_path):
        result = read_cache_entry("no.py", "nope", "abc123", base_dir=tmp_path)
        assert result is None

    def test_read_corrupt_json_returns_none(self, tmp_path):
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)
        (d / "corrupt__func__abc123.json").write_text("{bad json!!!")

        result = read_cache_entry("corrupt", "func", "abc123", base_dir=tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# list_cache_entries
# ---------------------------------------------------------------------------


class TestListEntries:
    def test_empty_when_no_cache(self, tmp_path):
        entries = list_cache_entries(base_dir=tmp_path)
        assert entries == []

    def test_lists_all_entries(self, tmp_path):
        entry1 = _make_entry(function_name="foo", source="def foo(): pass")
        entry2 = _make_entry(function_name="bar", source="def bar(): pass")

        write_cache_entry(entry1, base_dir=tmp_path)
        write_cache_entry(entry2, base_dir=tmp_path)

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 2
        names = {e.function_name for e in entries}
        assert names == {"foo", "bar"}

    def test_skips_corrupt_files(self, tmp_path):
        entry = _make_entry()
        write_cache_entry(entry, base_dir=tmp_path)

        d = tmp_path / CACHE_DIR
        (d / "corrupt.json").write_text("not json")

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clear_empty(self, tmp_path):
        count = clear_cache(base_dir=tmp_path)
        assert count == 0

    def test_clear_removes_all(self, tmp_path):
        write_cache_entry(_make_entry(function_name="a", source="a"), base_dir=tmp_path)
        write_cache_entry(_make_entry(function_name="b", source="b"), base_dir=tmp_path)

        count = clear_cache(base_dir=tmp_path)
        assert count == 2
        assert list_cache_entries(base_dir=tmp_path) == []


# ---------------------------------------------------------------------------
# CacheEntry serialization
# ---------------------------------------------------------------------------


class TestCacheEntrySerialization:
    def test_to_dict_and_from_dict(self):
        entry = _make_entry()
        d = entry.to_dict()
        restored = CacheEntry.from_dict(d)

        assert restored.function_name == entry.function_name
        assert restored.file_path == entry.file_path
        assert restored.source_hash == entry.source_hash
        assert restored.model == entry.model
        assert len(restored.mutations) == len(entry.mutations)
        assert restored.mutations[0].mutated_code == entry.mutations[0].mutated_code

    def test_from_dict_with_missing_optional_fields(self):
        data = {
            "function_name": "test",
            "file_path": "test.py",
            "source_hash": "abc123",
            "mutations": [],
        }
        entry = CacheEntry.from_dict(data)
        assert entry.model == ""

    def test_json_serializable(self):
        entry = _make_entry()
        json_str = json.dumps(entry.to_dict())
        data = json.loads(json_str)
        restored = CacheEntry.from_dict(data)
        assert restored.function_name == entry.function_name
