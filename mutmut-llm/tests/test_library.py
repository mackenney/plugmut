"""Tests for mutmut_llm.library."""

from __future__ import annotations

import json
import warnings

import pytest

from mutmut_llm.library import Library, LibraryEntry, source_hash, _entry_filename


SIMPLE_SOURCE = """\
def add(a, b):
    return a + b
"""

SIMPLE_MUTATION = {"mutated_code": "def add(a, b):\n    return a - b\n"}
MUTATION_WITH_DESC = {
    "mutated_code": "def add(a, b):\n    return a * b\n",
    "description": "Replace + with *",
}
INVALID_SYNTAX = {"mutated_code": "def add(a, b):\n    return a +\n"}  # syntax error
IMPORT_MUTATION = {
    "mutated_code": "import os\ndef add(a, b):\n    return a + b\n"
}  # introduces new import


class TestSourceHash:
    def test_stable(self):
        h = source_hash(SIMPLE_SOURCE)
        assert h == source_hash(SIMPLE_SOURCE)

    def test_strips_whitespace(self):
        assert source_hash("  def f(): pass  ") == source_hash("def f(): pass")

    def test_sixteen_chars(self):
        h = source_hash(SIMPLE_SOURCE)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_sources_differ(self):
        assert source_hash("def f(): return 1") != source_hash("def f(): return 2")


class TestLibraryAdd:
    def test_add_valid_returns_entry_and_file_exists(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        entries = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION],
            model="claude-3",
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.function_name == "add"
        assert entry.file_path == "src/math.py"
        assert entry.source_hash == source_hash(SIMPLE_SOURCE)
        assert entry.model == "claude-3"
        assert entry.mutations == [SIMPLE_MUTATION]

        # File must exist on disk
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        assert entries_dir.exists()
        json_files = list(entries_dir.glob("*.json"))
        assert len(json_files) == 1

    def test_add_with_metadata(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        meta = {"cost_usd": 0.01, "model_version": "v3"}
        entries = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION],
            model="claude-3",
            metadata=meta,
        )
        assert entries[0].metadata == meta

    def test_add_multiple_mutations(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        entries = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION, MUTATION_WITH_DESC],
            model="claude-3",
        )
        assert len(entries) == 1
        assert len(entries[0].mutations) == 2

    def test_add_invalid_syntax_returns_empty_with_warning(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entries = lib.add(
                function_name="add",
                file_path="src/math.py",
                source=SIMPLE_SOURCE,
                mutations=[INVALID_SYNTAX],
                model="claude-3",
            )
        assert entries == []
        assert len(caught) == 1
        assert "rejected" in str(caught[0].message).lower()

    def test_add_import_mutation_returns_empty_with_warning(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entries = lib.add(
                function_name="add",
                file_path="src/math.py",
                source=SIMPLE_SOURCE,
                mutations=[IMPORT_MUTATION],
                model="claude-3",
            )
        assert entries == []
        assert len(caught) >= 1

    def test_add_mixed_valid_invalid(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            entries = lib.add(
                function_name="add",
                file_path="src/math.py",
                source=SIMPLE_SOURCE,
                mutations=[INVALID_SYNTAX, SIMPLE_MUTATION],
                model="claude-3",
            )
        assert len(entries) == 1
        assert len(entries[0].mutations) == 1
        assert entries[0].mutations[0] == SIMPLE_MUTATION
        # One warning for the invalid mutation
        assert len(caught) == 1

    def test_add_no_mutations(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        entries = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[],
            model="claude-3",
        )
        assert entries == []
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        assert not entries_dir.exists() or len(list(entries_dir.glob("*.json"))) == 0

    def test_add_idempotent(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        entries1 = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION],
            model="claude-3",
        )
        entries2 = lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION],
            model="claude-3",
        )
        # Same filename → same file, no duplicates
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        json_files = list(entries_dir.glob("*.json"))
        assert len(json_files) == 1
        assert entries1[0].source_hash == entries2[0].source_hash

    def test_add_different_models_create_separate_files(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[SIMPLE_MUTATION],
            model="claude-3",
        )
        lib.add(
            function_name="add",
            file_path="src/math.py",
            source=SIMPLE_SOURCE,
            mutations=[MUTATION_WITH_DESC],
            model="claude-opus",
        )
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        json_files = list(entries_dir.glob("*.json"))
        assert len(json_files) == 2

    def test_add_no_file_when_all_invalid(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            lib.add(
                function_name="add",
                file_path="src/math.py",
                source=SIMPLE_SOURCE,
                mutations=[INVALID_SYNTAX],
                model="claude-3",
            )
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        assert not entries_dir.exists() or len(list(entries_dir.glob("*.json"))) == 0


class TestLibraryQuery:
    def test_query_returns_matching_entries(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        src_hash = source_hash(SIMPLE_SOURCE)
        results = lib.query(src_hash)
        assert len(results) == 1
        assert results[0].function_name == "add"

    def test_query_no_match_returns_empty(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        results = lib.query("nonexistent0000000")
        assert results == []

    def test_query_returns_all_models(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [MUTATION_WITH_DESC], "claude-opus")
        src_hash = source_hash(SIMPLE_SOURCE)
        results = lib.query(src_hash)
        assert len(results) == 2
        models = {e.model for e in results}
        assert models == {"claude-3", "claude-opus"}

    def test_query_uses_lazy_index(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        # Index not loaded yet
        assert lib._index is None
        src_hash = source_hash(SIMPLE_SOURCE)
        lib.query(src_hash)
        # After query, index is loaded
        assert lib._index is not None

    def test_query_returns_copy(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        src_hash = source_hash(SIMPLE_SOURCE)
        r1 = lib.query(src_hash)
        r2 = lib.query(src_hash)
        # Same content but separate list objects
        assert r1 == r2
        assert r1 is not r2


class TestLibraryListAll:
    def test_list_all_returns_all_entries(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        lib.add("sub", "src/math.py", "def sub(a,b):\n return a-b", [SIMPLE_MUTATION], "claude-3")
        all_entries = lib.list_all()
        assert len(all_entries) == 2

    def test_list_all_empty_when_no_entries(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        assert lib.list_all() == []

    def test_list_all_skips_corrupt_with_warning(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        # Write a corrupt file
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        (entries_dir / "corrupt.json").write_text("{invalid json{{")
        # Force re-index
        lib._index = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            all_entries = lib.list_all()
        assert len(all_entries) == 1
        assert any("corrupt" in str(w.message).lower() for w in caught)

    def test_list_all_skips_missing_key_with_warning(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        entries_dir.mkdir(parents=True)
        # Missing required "function_name" key
        (entries_dir / "bad.json").write_text(json.dumps({"model": "x"}))
        lib._index = None
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            all_entries = lib.list_all()
        assert all_entries == []
        assert len(caught) >= 1


class TestLibraryClear:
    def test_clear_removes_files_returns_count(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [MUTATION_WITH_DESC], "claude-opus")
        count = lib.clear()
        assert count == 2
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        assert len(list(entries_dir.glob("*.json"))) == 0

    def test_clear_returns_zero_when_no_entries(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        assert lib.clear() == 0

    def test_clear_invalidates_index(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        lib.list_all()  # populate index
        lib.clear()
        assert lib._index is None

    def test_clear_then_list_all_returns_empty(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        lib.clear()
        assert lib.list_all() == []


class TestLibraryEntryFilename:
    def test_filename_deterministic(self):
        f1 = _entry_filename("src/math.py", "add", "abc123", "claude-3")
        f2 = _entry_filename("src/math.py", "add", "abc123", "claude-3")
        assert f1 == f2

    def test_filename_differs_by_model(self):
        f1 = _entry_filename("src/math.py", "add", "abc123", "claude-3")
        f2 = _entry_filename("src/math.py", "add", "abc123", "claude-opus")
        assert f1 != f2

    def test_filename_differs_by_function(self):
        f1 = _entry_filename("src/math.py", "add", "abc123", "claude-3")
        f2 = _entry_filename("src/math.py", "sub", "abc123", "claude-3")
        assert f1 != f2

    def test_filename_format(self):
        f = _entry_filename("src/math.py", "add", "abc123", "claude-3")
        assert f.endswith(".json")
        assert len(f) == 37  # 32 hex chars + ".json"


class TestLibraryRoundTrip:
    def test_entry_persisted_as_json(self, tmp_path):
        lib = Library(base_dir=tmp_path)
        lib.add("add", "src/math.py", SIMPLE_SOURCE, [SIMPLE_MUTATION], "claude-3")
        entries_dir = tmp_path / ".plugmut-llm" / "entries"
        path = next(entries_dir.glob("*.json"))
        data = json.loads(path.read_text())
        assert data["function_name"] == "add"
        assert data["file_path"] == "src/math.py"
        assert data["source_hash"] == source_hash(SIMPLE_SOURCE)
        assert data["model"] == "claude-3"
        assert data["mutations"] == [SIMPLE_MUTATION]

    def test_entry_from_dict_roundtrip(self):
        entry = LibraryEntry(
            function_name="add",
            file_path="src/math.py",
            source_hash="abc123",
            model="claude-3",
            mutations=[{"mutated_code": "def add(a,b): return a-b"}],
            metadata={"cost": 0.01},
        )
        recovered = LibraryEntry.from_dict(entry.to_dict())
        assert recovered.function_name == entry.function_name
        assert recovered.file_path == entry.file_path
        assert recovered.source_hash == entry.source_hash
        assert recovered.model == entry.model
        assert recovered.mutations == entry.mutations
        assert recovered.metadata == entry.metadata

    def test_from_dict_no_metadata(self):
        data = {
            "function_name": "f",
            "file_path": "a.py",
            "source_hash": "hash",
            "model": "m",
            "mutations": [],
        }
        entry = LibraryEntry.from_dict(data)
        assert entry.metadata is None
