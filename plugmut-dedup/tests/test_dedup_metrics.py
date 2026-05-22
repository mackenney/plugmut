"""Measure dedup effectiveness across e2e projects with all mutation sources.

Generates mutations using core + extras + LLM operators, then measures
how many get deduplicated. Requires ANTHROPIC_API_KEY for LLM generation.

Run with: uv run --package mutmut-dedup pytest mutmut-dedup/tests/test_dedup_metrics.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from mutmut.file_mutation import create_mutations
from mutmut.file_mutation import reset_plugin_operators
from mutmut.hookspecs import hookimpl
from mutmut.plugin_manager import get_plugin_manager
from mutmut.plugin_manager import reset_plugin_manager
from mutmut_dedup.normalize import deduplicate
from mutmut_dedup.normalize import normalize_mutation

E2E_ROOT = Path(__file__).resolve().parents[2] / "mutmut" / "e2e_projects"

E2E_SOURCES: dict[str, Path] = {
    "my_lib": E2E_ROOT / "my_lib" / "src" / "my_lib" / "__init__.py",
    "config": E2E_ROOT / "config" / "config_pkg" / "math.py",
    "type_checking": E2E_ROOT / "type_checking" / "src" / "type_checking" / "__init__.py",
    "py3_14_features": E2E_ROOT / "py3_14_features" / "src" / "py3_14_features" / "__init__.py",
    "covered_lines": E2E_ROOT / "mutate_only_covered_lines" / "src" / "mutate_only_covered_lines" / "__init__.py",
}


def _register_extras():
    pm = get_plugin_manager()
    from mutmut_extras.plugin import mutmut_register_operators

    class _Extras:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return mutmut_register_operators()

    pm.register(_Extras())


def _register_llm(cache_dir: Path):
    pm = get_plugin_manager()
    import mutmut_llm.operators as llm_ops
    from mutmut_llm.cache import list_cache_entries  # ty: ignore[unresolved-import]
    from mutmut_llm.operators import operator_llm

    entries = list_cache_entries(base_dir=cache_dir)
    llm_ops._cache_index = {e.source_hash: e for e in entries}  # ty: ignore[unresolved-attribute]

    import libcst as cst

    class _LLM:
        @staticmethod
        @hookimpl
        def mutmut_register_operators():
            return [(cst.FunctionDef, operator_llm)]

    pm.register(_LLM())


def _register_dedup():
    pm = get_plugin_manager()
    from mutmut_dedup.plugin import mutmut_filter_mutations as dedup_filter

    class _Dedup:
        @staticmethod
        @hookimpl(trylast=True)
        def mutmut_filter_mutations(filename: str, mutations: list) -> list | None:
            return dedup_filter(filename=filename, mutations=mutations)

    pm.register(_Dedup())


def _run_llm_generation(source_path: Path, cache_dir: Path):
    """Generate LLM mutations for a source file into cache_dir."""
    from mutmut_llm.config import load_config
    from mutmut_llm.pipeline import run_generation

    config = load_config()

    run_generation(
        config=config,
        paths=[str(source_path.parent)],
        budget=50,
        dry_run=False,
        base_dir=cache_dir,
    )


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("PLUGMUT_DISABLE_PLUGIN_AUTOLOAD", "1")
    reset_plugin_manager()
    reset_plugin_operators()
    yield
    reset_plugin_manager()
    reset_plugin_operators()


@pytest.fixture(scope="session")
def llm_cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("llm_cache")


def _needs_api_key():
    return pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY not set",
    )


def _analyze_duplicates(mutations):
    """Analyze mutations for duplicates, returning detailed breakdown."""
    by_site: dict[int, list] = {}
    for m in mutations:
        by_site.setdefault(id(m.original_node), []).append(m)

    total_dupes = 0
    site_details = []
    for site_id, site_muts in by_site.items():
        norms = [normalize_mutation(m.mutated_node) for m in site_muts]
        unique = len(set(norms))
        dupes = len(norms) - unique
        total_dupes += dupes
        if dupes > 0:
            seen = set()
            dup_forms = []
            for n in norms:
                if n in seen:
                    dup_forms.append(n)
                else:
                    seen.add(n)
            site_details.append(
                {
                    "total": len(norms),
                    "unique": unique,
                    "dupes": dupes,
                    "dup_forms": dup_forms[:3],
                }
            )

    return {
        "total_mutations": len(mutations),
        "total_sites": len(by_site),
        "total_duplicates": total_dupes,
        "after_dedup": len(mutations) - total_dupes,
        "reduction_pct": (total_dupes / len(mutations) * 100) if mutations else 0,
        "sites_with_dupes": len(site_details),
        "site_details": site_details[:5],
    }


class TestDedupMetrics:
    """Measure dedup effectiveness across e2e projects."""

    @pytest.fixture(scope="class")
    def llm_caches(self, tmp_path_factory):
        """Generate LLM mutations once for all tests in this class."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("ANTHROPIC_API_KEY not set")

        caches = {}
        for name, source_path in E2E_SOURCES.items():
            if not source_path.exists():
                continue
            cache_dir = tmp_path_factory.mktemp(f"llm_{name}")
            try:
                _run_llm_generation(source_path, cache_dir)
                caches[name] = cache_dir
            except Exception as e:
                print(f"\n  LLM generation failed for {name}: {e}")
        return caches

    def test_dedup_metrics_all_projects(self, llm_caches):
        """Generate mutations for all e2e projects and report dedup stats."""
        results = {}

        for name, source_path in E2E_SOURCES.items():
            if not source_path.exists():
                continue

            source = source_path.read_text()

            reset_plugin_manager()
            reset_plugin_operators()
            _register_extras()
            if name in llm_caches:
                _register_llm(llm_caches[name])
            _, mutations_before = create_mutations(source, filename=str(source_path))

            analysis = _analyze_duplicates(mutations_before)

            deduped = deduplicate(mutations_before)
            assert len(deduped) == analysis["after_dedup"]

            results[name] = analysis

        print("\n")
        print("=" * 80)
        print("DEDUP METRICS REPORT")
        print("=" * 80)
        header = f"{'Project':<20} {'Total':>6} {'Unique':>6} {'Duped':>6} {'Reduction':>10} {'Sites w/ Dupes':>14}"
        print(header)
        print("-" * 80)

        grand_total = 0
        grand_duped = 0
        for name, stats in results.items():
            grand_total += stats["total_mutations"]
            grand_duped += stats["total_duplicates"]
            print(
                f"{name:<20} {stats['total_mutations']:>6} "
                f"{stats['after_dedup']:>6} {stats['total_duplicates']:>6} "
                f"{stats['reduction_pct']:>9.1f}% {stats['sites_with_dupes']:>14}"
            )

        print("-" * 80)
        grand_pct = (grand_duped / grand_total * 100) if grand_total else 0
        print(f"{'TOTAL':<20} {grand_total:>6} {grand_total - grand_duped:>6} {grand_duped:>6} {grand_pct:>9.1f}%")
        print("=" * 80)

        for name, stats in results.items():
            if stats["site_details"]:
                print(f"\n  {name} — sites with duplicates:")
                for i, detail in enumerate(stats["site_details"]):
                    print(f"    site {i + 1}: {detail['total']} mutations, {detail['dupes']} dupes")

        assert grand_total > 0, "No mutations generated at all"

    def test_dedup_metrics_core_only(self):
        """Baseline: core operators only, no extras or LLM."""
        results = {}
        for name, source_path in E2E_SOURCES.items():
            if not source_path.exists():
                continue
            source = source_path.read_text()
            reset_plugin_manager()
            reset_plugin_operators()
            _, mutations = create_mutations(source, filename=str(source_path))
            results[name] = _analyze_duplicates(mutations)

        print("\n")
        print("=" * 80)
        print("CORE-ONLY BASELINE (no extras, no LLM)")
        print("=" * 80)
        header = f"{'Project':<20} {'Total':>6} {'Unique':>6} {'Duped':>6} {'Reduction':>10}"
        print(header)
        print("-" * 80)
        for name, stats in results.items():
            print(
                f"{name:<20} {stats['total_mutations']:>6} "
                f"{stats['after_dedup']:>6} {stats['total_duplicates']:>6} "
                f"{stats['reduction_pct']:>9.1f}%"
            )

    def test_dedup_metrics_core_plus_extras(self):
        """Core + extras operators, no LLM."""
        results = {}
        for name, source_path in E2E_SOURCES.items():
            if not source_path.exists():
                continue
            source = source_path.read_text()
            reset_plugin_manager()
            reset_plugin_operators()
            _register_extras()
            _, mutations = create_mutations(source, filename=str(source_path))
            results[name] = _analyze_duplicates(mutations)

        print("\n")
        print("=" * 80)
        print("CORE + EXTRAS (no LLM)")
        print("=" * 80)
        header = f"{'Project':<20} {'Total':>6} {'Unique':>6} {'Duped':>6} {'Reduction':>10}"
        print(header)
        print("-" * 80)
        for name, stats in results.items():
            print(
                f"{name:<20} {stats['total_mutations']:>6} "
                f"{stats['after_dedup']:>6} {stats['total_duplicates']:>6} "
                f"{stats['reduction_pct']:>9.1f}%"
            )
