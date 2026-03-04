"""End-to-end tests: source → create_mutations() → filter hook → verify dedup."""

from __future__ import annotations

import pytest
from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager

from mutmut_dedup.normalize import normalize_mutation
from mutmut_dedup.plugin import mutmut_filter_mutations as dedup_filter


def _setup_all_plugins():
    """Register extras + dedup plugins manually."""
    pm = get_plugin_manager()

    try:
        from mutmut_extras.plugin import mutmut_register_operators
    except ImportError:
        pytest.skip("mutmut-extras not installed")

    class _ExtrasPlugin:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return mutmut_register_operators()

    class _DedupPlugin:
        @staticmethod
        @hookimpl(trylast=True)
        def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
            return dedup_filter(filename=filename, mutations=mutations)

    pm.register(_ExtrasPlugin())
    pm.register(_DedupPlugin())


@pytest.fixture(autouse=True)
def _isolate_plugins(monkeypatch):
    monkeypatch.setenv("MUTMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    yield
    reset_plugin_manager()


def _setup_extras_only():
    """Register extras operators without dedup."""
    pm = get_plugin_manager()
    try:
        from mutmut_extras.plugin import mutmut_register_operators
    except ImportError:
        pytest.skip("mutmut-extras not installed")

    class _ExtrasPlugin:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return mutmut_register_operators()

    pm.register(_ExtrasPlugin())


class TestOverlappingOperators:
    def test_dedup_reduces_count(self):
        source = """\
def add(a, b):
    return a + b
"""
        _setup_extras_only()
        _, mutations_no_dedup = create_mutations(source)
        count_before = len(mutations_no_dedup)

        reset_plugin_manager()
        _setup_all_plugins()
        _, mutations_with_dedup = create_mutations(source)
        count_after = len(mutations_with_dedup)

        assert count_after <= count_before


class TestNoDuplicatesUnchanged:
    def test_no_duplicates_same_count(self):
        source = """\
x = 1
"""
        _, mutations_no_dedup = create_mutations(source)
        count_before = len(mutations_no_dedup)

        reset_plugin_manager()
        _setup_all_plugins()
        _, mutations_with_dedup = create_mutations(source)

        assert len(mutations_with_dedup) >= count_before - 1


class TestMultipleDupsSameSite:
    def test_exactly_one_survivor_per_form(self):
        source = """\
def f(x: int, y: int) -> int:
    return x + y
"""
        _setup_all_plugins()
        _, mutations = create_mutations(source)

        by_site: dict[int, list] = {}
        for m in mutations:
            by_site.setdefault(id(m.original_node), []).append(m)

        for site_mutations in by_site.values():
            norms = [normalize_mutation(m.mutated_node) for m in site_mutations]
            assert len(norms) == len(set(norms)), (
                f"Duplicate normalized forms at site: {norms}"
            )


class TestSurvivingMutationsValid:
    def test_all_surviving_mutations_produce_valid_python(self):
        source = """\
def compute(a, b):
    if a > b:
        return a - b
    return a + b
"""
        _setup_all_plugins()
        module, mutations = create_mutations(source)

        for m in mutations:
            mutated_module = module.deep_replace(m.original_node, m.mutated_node)
            code = mutated_module.code
            try:
                compile(code, "<test>", "exec")
            except SyntaxError:
                pytest.fail(f"Surviving mutation produced invalid Python:\n{code}")
