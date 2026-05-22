from __future__ import annotations

import time

import libcst as cst
import pytest
from mutmut.file_mutation import Mutation
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_dedup.plugin import mutmut_filter_mutations


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


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


class TestBytecodeEquivalentRemoval:
    def test_plugin_removes_bytecode_equivalent(self):
        mod = cst.parse_module("def f(): return 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        ret_node = func.body.body[0].value  # ty: ignore[unresolved-attribute]

        mutations = [
            Mutation(
                original_node=ret_node,
                mutated_node=ret_node,
                contained_by_top_level_function=func,
            ),
        ]

        result = mutmut_filter_mutations(filename="test.py", mutations=mutations)
        assert result is not None
        assert len(result) == 0


class TestBytecodeNoDuplicatesUnchanged:
    def test_returns_none_when_all_bytecode_unique(self):
        mod = cst.parse_module("def f(x):\n    return x + 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        orig_node = func.body.body[0].body[0].value  # ty: ignore[unresolved-attribute]

        mutations = [
            Mutation(
                original_node=orig_node,
                mutated_node=cst.parse_expression("x - 1"),
                contained_by_top_level_function=func,
            ),
            Mutation(
                original_node=orig_node,
                mutated_node=cst.parse_expression("x * 1"),
                contained_by_top_level_function=func,
            ),
        ]

        result = mutmut_filter_mutations(filename="test.py", mutations=mutations)
        assert result is None


class TestBytecodePerformanceSanity:
    def test_100_mutations_under_one_second(self):
        mod = cst.parse_module("def f(x):\n    return x + 1\n")
        func = mod.body[0]
        assert isinstance(func, cst.FunctionDef)
        orig_node = func.body.body[0].body[0].value  # ty: ignore[unresolved-attribute]

        mutations = [
            Mutation(
                original_node=orig_node,
                mutated_node=cst.parse_expression(f"x + {i}"),
                contained_by_top_level_function=func,
            )
            for i in range(100)
        ]

        start = time.monotonic()
        mutmut_filter_mutations(filename="test.py", mutations=mutations)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Took {elapsed:.2f}s"
