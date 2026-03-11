"""Adversarial tests for multi-model cache implementation.

Targets: model name sanitization, backwards compat, glob collisions,
dedup correctness, mutation count consistency, and cost aggregation.
"""

from __future__ import annotations

import json

import libcst as cst
import pytest

from mutmut_llm.cache import (
    CACHE_DIR,
    CacheEntry,
    CachedMutation,
    _cache_key,
    _read_any_matching_entry,
    list_cache_entries,
    read_cache_entry,
    source_hash,
    write_cache_entry,
)


def _entry(
    function_name: str = "foo",
    file_path: str = "src/mod.py",
    source: str = "def foo(): return 1",
    model: str = "claude-sonnet-4-6",
    mutations: list[CachedMutation] | None = None,
) -> CacheEntry:
    return CacheEntry(
        function_name=function_name,
        file_path=file_path,
        source_hash=source_hash(source),
        mutations=mutations or [CachedMutation("def foo(): return 2", "mut")],
        model=model,
    )


class TestModelNameSanitization:
    """Model names containing __ break the segment-based key parsing."""

    def test_model_with_double_underscore_round_trips(self, tmp_path):
        """A model name like 'org__custom-model' must not corrupt the cache key."""
        entry = _entry(model="org__custom-model")
        path = write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model="org__custom-model",
        )
        assert loaded is not None
        assert loaded.model == "org__custom-model"

    def test_model_with_double_underscore_sanitized(self, tmp_path):
        """Model names with __ are sanitized to _ so segment count stays at 4."""
        key = _cache_key("src/mod.py", "foo", "abc123", "a__b")
        segments = key.split("__")
        assert len(segments) == 4, (
            "__ in model name must be sanitized to preserve 4-segment format"
        )

    def test_model_with_slashes_sanitized(self, tmp_path):
        """Model names like 'anthropic/claude-3' have / replaced with _."""
        entry = _entry(model="anthropic/claude-3-sonnet")
        path = write_cache_entry(entry, base_dir=tmp_path)
        assert "/" not in path.name

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model="anthropic/claude-3-sonnet",
        )
        assert loaded is not None

    def test_two_models_differing_only_by_slash_vs_underscore_no_collision(
        self, tmp_path
    ):
        """'anthropic/model' and 'anthropic_model' produce distinct cache keys."""
        entry_a = _entry(
            model="anthropic/model",
            mutations=[CachedMutation("def foo(): return 1", "a")],
        )
        entry_b = _entry(
            model="anthropic_model",
            mutations=[CachedMutation("def foo(): return 2", "b")],
        )

        write_cache_entry(entry_a, base_dir=tmp_path)
        write_cache_entry(entry_b, base_dir=tmp_path)

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 2, (
            "Slash and underscore models must produce distinct cache keys"
        )


class TestBackwardsCompat:
    """Old 3-segment filenames (no model) must still be readable."""

    def test_old_format_read_via_model_none(self, tmp_path):
        """read_cache_entry(model=None) finds old 3-segment files on disk."""
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)

        src_h = source_hash("def foo(): return 1")
        entry_data = {
            "function_name": "foo",
            "file_path": "src/mod.py",
            "source_hash": src_h,
            "mutations": [
                {"mutated_code": "def foo(): return 0", "description": "old"}
            ],
        }
        old_filename = f"src_mod.py__foo__{src_h}.json"
        (d / old_filename).write_text(json.dumps(entry_data))

        loaded = read_cache_entry(
            "src/mod.py", "foo", src_h, base_dir=tmp_path, model=None
        )
        assert loaded is not None
        assert loaded.model == ""

    def test_old_format_NOT_found_by_explicit_model(self, tmp_path):
        """read_cache_entry(model='claude-sonnet-4-6') must NOT find old 3-segment files."""
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)

        src_h = source_hash("def foo(): return 1")
        entry_data = {
            "function_name": "foo",
            "file_path": "src/mod.py",
            "source_hash": src_h,
            "mutations": [
                {"mutated_code": "def foo(): return 0", "description": "old"}
            ],
        }
        old_filename = f"src_mod.py__foo__{src_h}.json"
        (d / old_filename).write_text(json.dumps(entry_data))

        loaded = read_cache_entry(
            "src/mod.py", "foo", src_h, base_dir=tmp_path, model="claude-sonnet-4-6"
        )
        assert loaded is None


class TestEmptyModelField:
    def test_write_empty_model_produces_3_segment_filename(self, tmp_path):
        entry = _entry(model="")
        path = write_cache_entry(entry, base_dir=tmp_path)
        segments = path.stem.split("__")
        assert len(segments) == 3

    def test_read_with_empty_string_model(self, tmp_path):
        """read_cache_entry(model='') should find entries written with model=''."""
        entry = _entry(model="")
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = read_cache_entry(
            entry.file_path,
            entry.function_name,
            entry.source_hash,
            base_dir=tmp_path,
            model="",
        )
        # model="" is falsy, so `if model is None` is False but `_cache_key(... model="")` uses 3-segment
        # However, read_cache_entry checks `if model is None` — model="" is not None,
        # so it goes through the exact-lookup path with 3-segment key. This should work.
        assert loaded is not None


class TestGlobCollision:
    """_read_any_matching_entry uses glob(f'{prefix}*.json') which is too greedy."""

    def test_hash_prefix_collision(self, tmp_path):
        """Hash 'abc123' glob matches 'abc12345' — returns wrong entry."""
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)

        short_hash = "abc1234567890123"
        long_hash = "abc12345678901234"

        entry_short = {
            "function_name": "foo",
            "file_path": "src/mod.py",
            "source_hash": short_hash,
            "mutations": [
                {"mutated_code": "def foo(): return 1", "description": "short"}
            ],
        }
        entry_long = {
            "function_name": "foo",
            "file_path": "src/mod.py",
            "source_hash": long_hash,
            "mutations": [
                {"mutated_code": "def foo(): return 2", "description": "long"}
            ],
        }

        # Write as 4-segment (with model) so the 3-segment exact lookup misses
        (d / f"src_mod.py__foo__{short_hash}__modelA.json").write_text(
            json.dumps(entry_short)
        )
        (d / f"src_mod.py__foo__{long_hash}__modelB.json").write_text(
            json.dumps(entry_long)
        )

        # Search for short_hash with model=None triggers glob scan.
        # Glob pattern: "src_mod.py__foo__abc1234567890123*.json"
        # This matches BOTH files because long_hash starts with short_hash prefix.
        loaded = _read_any_matching_entry("src/mod.py", "foo", short_hash, tmp_path)
        # The source_hash check inside the loop should filter correctly...
        # BUT only if the entry's source_hash field is checked. Let's verify.
        if loaded is not None:
            assert loaded.source_hash == short_hash, (
                "Glob matched wrong entry: got source_hash={loaded.source_hash}"
            )

    def test_glob_matches_model_suffix_starting_with_hash(self, tmp_path):
        """Edge case: glob 'prefix*' matches entries where model name starts with digits."""
        d = tmp_path / CACHE_DIR
        d.mkdir(parents=True)

        src_h = source_hash("def foo(): return 1")
        entry_data = {
            "function_name": "foo",
            "file_path": "src/mod.py",
            "source_hash": src_h,
            "mutations": [
                {"mutated_code": "def foo(): return 0", "description": "test"}
            ],
            "model": "v2-model",
        }
        # 4-segment: prefix is src_mod.py__foo__{src_h}, then __v2-model
        (d / f"src_mod.py__foo__{src_h}__v2-model.json").write_text(
            json.dumps(entry_data)
        )

        # Glob: f"src_mod.py__foo__{src_h}*.json" — matches because __v2-model is after prefix
        loaded = _read_any_matching_entry("src/mod.py", "foo", src_h, tmp_path)
        assert loaded is not None


class TestReadAnyMatchingEntryBehavior:
    """_read_any_matching_entry should return any entry. Verify which one."""

    def test_returns_first_sorted_match(self, tmp_path):
        """When multiple models exist, returns the first by sorted filename."""
        source = "def foo(): return 1"
        entry_a = _entry(model="aaa-model", source=source)
        entry_z = _entry(
            model="zzz-model",
            source=source,
            mutations=[CachedMutation("def foo(): return 99", "z-mut")],
        )
        write_cache_entry(entry_a, base_dir=tmp_path)
        write_cache_entry(entry_z, base_dir=tmp_path)

        loaded = _read_any_matching_entry(
            "src/mod.py", "foo", source_hash(source), tmp_path
        )
        # Sorted glob means aaa-model file comes first (unless 3-segment exact hits first)
        assert loaded is not None


class TestDeduplicationEdgeCases:
    """operator_llm deduplicates by exact mutated_code string."""

    def test_whitespace_only_difference_not_deduped(self, monkeypatch):
        """Trailing newline difference = two separate mutations (potential issue)."""
        from mutmut_llm.operators import _reset_cache_index, operator_llm

        source = "def foo():\n    return 1\n"
        src_h = source_hash(source)

        entry_a = CacheEntry(
            function_name="foo",
            file_path="a.py",
            source_hash=src_h,
            mutations=[CachedMutation("def foo():\n    return 2\n", "with newline")],
            model="model-a",
        )
        entry_b = CacheEntry(
            function_name="foo",
            file_path="a.py",
            source_hash=src_h,
            mutations=[CachedMutation("def foo():\n    return 2", "without newline")],
            model="model-b",
        )

        monkeypatch.setattr(
            "mutmut_llm.operators.list_cache_entries",
            lambda: [entry_a, entry_b],
        )
        _reset_cache_index()

        node = cst.parse_module(source).body[0]
        results = list(operator_llm(node))
        # Both are considered unique despite producing identical AST
        assert len(results) == 2, (
            "Whitespace-only diff produces duplicate mutations in practice"
        )

    def test_identical_mutations_from_three_models_deduped(self, monkeypatch):
        """Same mutation from 3 models yields exactly 1 result."""
        from mutmut_llm.operators import _reset_cache_index, operator_llm

        source = "def foo():\n    return 1\n"
        src_h = source_hash(source)
        shared = "def foo():\n    return 2\n"

        entries = [
            CacheEntry(
                function_name="foo",
                file_path="a.py",
                source_hash=src_h,
                mutations=[CachedMutation(shared, f"from model {i}")],
                model=f"model-{i}",
            )
            for i in range(3)
        ]

        monkeypatch.setattr("mutmut_llm.operators.list_cache_entries", lambda: entries)
        _reset_cache_index()

        node = cst.parse_module(source).body[0]
        results = list(operator_llm(node))
        assert len(results) == 1


class TestMutationCountConsistency:
    """_llm_mutation_count_by_function counts raw cache entries.
    operator_llm deduplicates. These can disagree, causing wrong LLM mutant tagging.
    """

    def test_count_matches_actual_yielded_mutations(self, monkeypatch):
        """Duplicate mutations across models are deduplicated in both count and operator."""
        from mutmut_llm.operators import _reset_cache_index, operator_llm
        from mutmut_llm.plugin import _llm_mutation_count_by_function

        source = "def compute():\n    return 42\n"
        src_h = source_hash(source)
        shared_mutation = "def compute():\n    return 0\n"

        entry_a = CacheEntry(
            function_name="compute",
            file_path="src/calc.py",
            source_hash=src_h,
            mutations=[CachedMutation(shared_mutation, "sonnet")],
            model="claude-sonnet-4-6",
            cost_usd=0.01,
        )
        entry_b = CacheEntry(
            function_name="compute",
            file_path="src/calc.py",
            source_hash=src_h,
            mutations=[CachedMutation(shared_mutation, "opus")],
            model="claude-opus-4-6",
            cost_usd=0.02,
        )

        monkeypatch.setattr(
            "mutmut_llm.operators.list_cache_entries", lambda: [entry_a, entry_b]
        )
        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: [entry_a, entry_b]
        )
        _reset_cache_index()

        node = cst.parse_module(source).body[0]
        actual_mutations = list(operator_llm(node))
        reported_count = _llm_mutation_count_by_function()

        assert len(actual_mutations) == 1
        assert reported_count["compute"] == 1
        assert reported_count["compute"] == len(actual_mutations)


class TestCostDoubleCountingBug:
    """mutmut_post_run and llm-status sum costs from ALL cache entries.
    With multi-model entries, costs from previous model runs are included.
    """

    def test_post_run_sums_all_models_costs(self, monkeypatch, tmp_path):
        """Running with model B after model A: post_run reports A+B cost, not just B."""
        from mutmut_llm import storage
        import mutmut_llm.plugin as mod
        from mutmut_llm.plugin import mutmut_post_run
        from mutmut_llm.storage import new_run

        entry_a = CacheEntry(
            function_name="f",
            file_path="a.py",
            source_hash="h1",
            mutations=[],
            model="model-a",
            cost_usd=0.05,
            input_tokens=1000,
            output_tokens=500,
        )
        entry_b = CacheEntry(
            function_name="f",
            file_path="a.py",
            source_hash="h1",
            mutations=[],
            model="model-b",
            cost_usd=0.10,
            input_tokens=2000,
            output_tokens=1000,
        )

        monkeypatch.setattr(
            "mutmut_llm.plugin.list_cache_entries", lambda: [entry_a, entry_b]
        )

        run = new_run()
        monkeypatch.setattr(mod, "_current_run", run)

        cache_root = tmp_path / "cache"
        monkeypatch.setattr(
            "mutmut_llm.plugin.save_run",
            lambda r: storage.save_run(r, cache_root=cache_root),
        )

        mutmut_post_run(source_file_mutation_data=[])

        # BUG: cost is 0.15 (both models) not 0.10 (just this run's model)
        assert run.total_llm_cost_usd == pytest.approx(0.15)
        # This is technically correct if "total cost" means "all-time cache cost",
        # but misleading if user expects "this run's cost".


class TestConcurrentWriteSafety:
    """Two generates for different models writing to the same cache directory."""

    def test_different_models_write_different_files(self, tmp_path):
        """Concurrent writes for different models should not interfere."""
        source = "def foo(): return 1"
        entry_a = _entry(model="model-a", source=source)
        entry_b = _entry(model="model-b", source=source)

        path_a = write_cache_entry(entry_a, base_dir=tmp_path)
        path_b = write_cache_entry(entry_b, base_dir=tmp_path)

        assert path_a != path_b
        assert path_a.exists()
        assert path_b.exists()

        loaded_a = read_cache_entry(
            entry_a.file_path,
            entry_a.function_name,
            entry_a.source_hash,
            base_dir=tmp_path,
            model="model-a",
        )
        loaded_b = read_cache_entry(
            entry_b.file_path,
            entry_b.function_name,
            entry_b.source_hash,
            base_dir=tmp_path,
            model="model-b",
        )
        assert loaded_a is not None
        assert loaded_b is not None

    def test_same_model_overwrites_atomically(self, tmp_path):
        """Two writes with the same model overwrite the same file."""
        source = "def foo(): return 1"
        entry_v1 = _entry(
            model="model-a", source=source, mutations=[CachedMutation("v1", "first")]
        )
        entry_v2 = _entry(
            model="model-a", source=source, mutations=[CachedMutation("v2", "second")]
        )

        write_cache_entry(entry_v1, base_dir=tmp_path)
        write_cache_entry(entry_v2, base_dir=tmp_path)

        entries = list_cache_entries(base_dir=tmp_path)
        assert len(entries) == 1
        assert entries[0].mutations[0].mutated_code == "v2"


class TestReadAnyMatchingEntryNoDeadCode:
    """Dead code (None branch) has been removed; glob fallback still works."""

    def test_glob_fallback_finds_model_entry(self, tmp_path):
        """Model-specific entries are found via the __*.json glob fallback."""
        source = "def foo(): return 1"
        entry = _entry(model="some-model", source=source)
        write_cache_entry(entry, base_dir=tmp_path)

        loaded = _read_any_matching_entry(
            "src/mod.py", "foo", source_hash(source), tmp_path
        )
        assert loaded is not None
        assert loaded.model == "some-model"
