from __future__ import annotations

import libcst as cst
import pytest
from mutmut.file_mutation import Mutation
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager

from mutmut_dedup.plugin import mutmut_filter_mutations


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


class TestHookDiscovery:
    def test_plugin_hook_is_discovered(self):
        pm = get_plugin_manager()

        class _DedupPlugin:
            @staticmethod
            @hookimpl(trylast=True)
            def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
                return mutmut_filter_mutations(filename=filename, mutations=mutations)

        pm.register(_DedupPlugin())
        results = pm.hook.mutmut_filter_mutations(filename="test.py", mutations=[])
        assert results is not None


class TestDedupRemovesDuplicates:
    def test_dedup_removes_duplicate_mutations(self):
        orig = cst.Name("a")
        mut1 = cst.Name("b")
        mut2 = cst.Name("b")

        mutations = [
            Mutation(
                original_node=orig,
                mutated_node=mut1,
                contained_by_top_level_function=None,
            ),
            Mutation(
                original_node=orig,
                mutated_node=mut2,
                contained_by_top_level_function=None,
            ),
        ]

        result = mutmut_filter_mutations(filename="test.py", mutations=mutations)
        assert result is not None
        assert len(result) == 1


class TestTrylastOrdering:
    def test_dedup_runs_after_other_filters(self):
        pm = get_plugin_manager()
        call_order: list[str] = []

        class _EarlyFilter:
            @staticmethod
            @hookimpl
            def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
                call_order.append("early")
                return None

        class _DedupPlugin:
            @staticmethod
            @hookimpl(trylast=True)
            def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
                call_order.append("dedup")
                return None

        pm.register(_EarlyFilter())
        pm.register(_DedupPlugin())
        pm.hook.mutmut_filter_mutations(filename="test.py", mutations=[])
        assert call_order == ["early", "dedup"]


class TestNoneWhenNoDuplicates:
    def test_returns_none_when_no_duplicates(self):
        orig = cst.Name("a")
        mut1 = cst.Name("b")
        mut2 = cst.Name("c")

        mutations = [
            Mutation(
                original_node=orig,
                mutated_node=mut1,
                contained_by_top_level_function=None,
            ),
            Mutation(
                original_node=orig,
                mutated_node=mut2,
                contained_by_top_level_function=None,
            ),
        ]

        result = mutmut_filter_mutations(filename="test.py", mutations=mutations)
        assert result is None
