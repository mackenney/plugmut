"""End-to-end tests: source → create_mutations() → filter hook → verify dedup."""

from __future__ import annotations

import libcst as cst
import pytest
from mutmut.file_mutation import create_mutations
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager, reset_plugin_manager
from mutmut.file_mutation import reset_plugin_operators

from mutmut_dedup.bytecode import bytecode_signature
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
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


def _setup_dedup_only():
    """Register only the dedup plugin — no extras dependency."""
    pm = get_plugin_manager()

    class _DedupPlugin:
        @staticmethod
        @hookimpl(trylast=True)
        def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
            return dedup_filter(filename=filename, mutations=mutations)

    pm.register(_DedupPlugin())


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
        reset_plugin_operators()
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
        reset_plugin_operators()
        _setup_all_plugins()
        _, mutations_with_dedup = create_mutations(source)

        assert len(mutations_with_dedup) == count_before


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


class TestBytecodeEquivalenceE2E:
    def test_no_surviving_mutation_is_bytecode_equivalent(self):
        source = """\
def compute(x, y):
    if x > 0:
        return x + y
    return x - y
"""
        _setup_dedup_only()
        module, mutations = create_mutations(source)

        for m in mutations:
            if m.contained_by_top_level_function is None:
                continue
            func = m.contained_by_top_level_function
            orig_source = cst.Module(body=[func]).code
            mutated_func = func.deep_replace(m.original_node, m.mutated_node)
            mut_source = cst.Module(body=[mutated_func]).code
            orig_sig = bytecode_signature(orig_source)
            mut_sig = bytecode_signature(mut_source)
            assert orig_sig != mut_sig, (
                f"Surviving mutation is bytecode-equivalent to original:\n"
                f"Original: {orig_source}\nMutated: {mut_source}"
            )


class TestBytecodeDedupE2E:
    def test_no_bytecode_duplicates_survive(self):
        source = """\
def process(a, b, c):
    result = a + b
    if result > c:
        return result * 2
    return result - c
"""
        _setup_dedup_only()
        module, mutations = create_mutations(source)

        by_site: dict[int, list] = {}
        for m in mutations:
            by_site.setdefault(id(m.original_node), []).append(m)

        for site_id, site_muts in by_site.items():
            sigs = []
            for m in site_muts:
                if m.contained_by_top_level_function is None:
                    continue
                func = m.contained_by_top_level_function
                mutated_func = func.deep_replace(m.original_node, m.mutated_node)
                sig = bytecode_signature(cst.Module(body=[mutated_func]).code)
                if sig is not None:
                    sigs.append(sig)
            assert len(sigs) == len(set(sigs)), "Bytecode duplicates survived filtering"


class TestDedupCountComparison:
    def test_dedup_count_lte_no_dedup(self):
        source = """\
def analyze(data):
    total = 0
    for item in data:
        if item > 0:
            total = total + item
        else:
            total = total - item
    return total
"""
        _, mutations_no_dedup = create_mutations(source)
        count_without = len(mutations_no_dedup)

        reset_plugin_manager()
        reset_plugin_operators()
        _setup_dedup_only()
        _, mutations_with_dedup = create_mutations(source)
        count_with = len(mutations_with_dedup)

        assert count_with <= count_without


class TestSurvivingMutationsValidBytecode:
    def test_all_surviving_produce_valid_python(self):
        source = """\
def transform(x):
    if x is None:
        return 0
    return x * 2 + 1
"""
        _setup_dedup_only()
        module, mutations = create_mutations(source)

        for m in mutations:
            mutated = module.deep_replace(m.original_node, m.mutated_node)
            code = mutated.code
            try:
                compile(code, "<test>", "exec")
            except SyntaxError:
                pytest.fail(f"Mutation produced invalid Python:\n{code}")
