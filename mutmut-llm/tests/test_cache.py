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
        assert entry.cost_usd == 0.0
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.generated_at == ""

    def test_json_serializable(self):
        entry = _make_entry()
        json_str = json.dumps(entry.to_dict())
        data = json.loads(json_str)
        restored = CacheEntry.from_dict(data)
        assert restored.function_name == entry.function_name

    def test_cost_fields_round_trip(self):
        entry = CacheEntry(
            function_name="foo",
            file_path="test.py",
            source_hash="abc123",
            mutations=[],
            model="claude-sonnet-4-6",
            cost_usd=0.0042,
            input_tokens=1500,
            output_tokens=800,
            generated_at="2026-03-04T12:00:00+00:00",
        )
        d = entry.to_dict()
        assert d["cost_usd"] == 0.0042
        assert d["input_tokens"] == 1500
        assert d["output_tokens"] == 800
        assert d["generated_at"] == "2026-03-04T12:00:00+00:00"

        restored = CacheEntry.from_dict(d)
        assert restored.cost_usd == entry.cost_usd
        assert restored.input_tokens == entry.input_tokens
        assert restored.output_tokens == entry.output_tokens
        assert restored.generated_at == entry.generated_at

    def test_cost_fields_persisted_to_disk(self, tmp_path):
        entry = CacheEntry(
            function_name="bar",
            file_path="bar.py",
            source_hash=source_hash("def bar(): pass"),
            mutations=[],
            model="claude-sonnet-4-6",
            cost_usd=0.015,
            input_tokens=2000,
            output_tokens=1000,
            generated_at="2026-03-04T12:00:00+00:00",
        )
        write_cache_entry(entry, base_dir=tmp_path)
        loaded = read_cache_entry(
            entry.file_path, entry.function_name, entry.source_hash, base_dir=tmp_path
        )
        assert loaded is not None
        assert loaded.cost_usd == 0.015
        assert loaded.input_tokens == 2000
        assert loaded.output_tokens == 1000
        assert loaded.generated_at == "2026-03-04T12:00:00+00:00"


class TestMultiModelCache:
    def test_multi_model_entries_coexist(self, tmp_path):
        """Entries for the same function from different models produce separate files."""
        source = "def foo(): return 1"
        entry_a = _make_entry(model="claude-sonnet-4-6", source=source)
        entry_b = _make_entry(
            model="claude-opus-4-6",
            source=source,
            mutations=[
                CachedMutation(
                    mutated_code="def foo(): return 99", description="opus mutation"
                )
            ],
        )

        path_a = write_cache_entry(entry_a, base_dir=tmp_path)
        path_b = write_cache_entry(entry_b, base_dir=tmp_path)

        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 2
        models = {e.model for e in entries}
        assert models == {"claude-sonnet-4-6", "claude-opus-4-6"}

    def test_read_with_model_returns_exact_match(self, tmp_path):
        """read_cache_entry(model=X) returns only that model's entry."""
        source = "def foo(): return 1"
        entry = _make_entry(model="claude-sonnet-4-6", source=source)
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model="claude-sonnet-4-6",
        )
        assert loaded is not None
        assert loaded.model == "claude-sonnet-4-6"

        missing = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model="claude-opus-4-6",
        )
        assert missing is None

    def test_read_without_model_returns_any(self, tmp_path):
        """read_cache_entry(model=None) returns any matching entry (backwards compat)."""
        source = "def foo(): return 1"
        entry = _make_entry(model="claude-sonnet-4-6", source=source)
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model=None,
        )
        assert loaded is not None
        assert loaded.model == "claude-sonnet-4-6"

    def test_old_format_entries_still_readable(self, tmp_path):
        """Old 3-segment filename entries (no model in key) are still loaded by list_cache_entries."""
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)

        entry_data = {
            "function_name": "foo",
            "file_path": "src/module.py",
            "source_hash": "abc123deadbeef00",
            "mutations": [
                {"mutated_code": "def foo(): return 0", "description": "old"}
            ],
        }
        old_filename = "src_module.py__foo__abc123deadbeef00.json"
        (d / old_filename).write_text(json.dumps(entry_data))

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 1
        assert entries[0].model == ""
        assert entries[0].function_name == "foo"

    def test_old_format_readable_via_read_cache_entry(self, tmp_path):
        """read_cache_entry(model=None) finds old 3-segment files."""
        entry = _make_entry(model="", source="def foo(): return 1")
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model=None,
        )
        assert loaded is not None
        assert loaded.model == ""

    def test_write_with_model_includes_model_in_filename(self, tmp_path):
        """Filename contains model segment for entries with a model."""
        entry = _make_entry(model="claude-sonnet-4-6")
        path = write_cache_entry(entry, base_dir=tmp_path)
        assert "claude-sonnet-4-6" in path.name

    def test_write_without_model_uses_old_format(self, tmp_path):
        """Entries with model="" use the 3-segment filename (backwards compat)."""
        entry = _make_entry(model="")
        path = write_cache_entry(entry, base_dir=tmp_path)
        parts = path.stem.split("__")
        assert len(parts) == 3

    def test_model_names_with_underscores_do_not_collide(self, tmp_path):
        """Models like 'org__model' and 'org_model' must produce distinct cache keys."""
        source = "def foo(): return 1"
        entry_a = _make_entry(model="org__model", source=source)
        entry_b = _make_entry(model="org_model", source=source)

        path_a = write_cache_entry(entry_a, base_dir=tmp_path)
        path_b = write_cache_entry(entry_b, base_dir=tmp_path)

        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 2
        models = {e.model for e in entries}
        assert models == {"org__model", "org_model"}
