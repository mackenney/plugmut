"""Tests for mutmut_llm.storage."""

from __future__ import annotations

from mutmut_llm.storage import (
    MutantResult,
    RunResult,
    list_runs,
    load_latest_run,
    load_run,
    new_run,
    save_run,
)


def _make_result(
    name: str = "mod.func__mutmut_1", status: str = "killed", is_llm: bool = False
) -> MutantResult:
    return MutantResult(mutant_name=name, status=status, duration=0.5, is_llm=is_llm)


class TestSaveLoadRoundTrip:
    def test_round_trip_preserves_data(self, cache_root):
        run = RunResult(
            run_id="abc123",
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:01:00+00:00",
            results=[
                _make_result("mod.func__mutmut_1", "killed", is_llm=False),
                _make_result("mod.func__mutmut_2", "survived", is_llm=True),
            ],
        )
        save_run(run, cache_root=cache_root)
        loaded = load_run("abc123", cache_root=cache_root)

        assert loaded is not None
        assert loaded.run_id == "abc123"
        assert loaded.started_at == "2026-01-01T00:00:00+00:00"
        assert loaded.completed_at == "2026-01-01T00:01:00+00:00"
        assert len(loaded.results) == 2

    def test_mutant_result_fields_preserved(self, cache_root):
        run = RunResult(
            run_id="x1",
            started_at="2026-01-01T00:00:00+00:00",
            results=[_make_result("a.b__mutmut_3", "timeout", is_llm=True)],
        )
        save_run(run, cache_root=cache_root)
        loaded = load_run("x1", cache_root=cache_root)

        r = loaded.results[0]
        assert r.mutant_name == "a.b__mutmut_3"
        assert r.status == "timeout"
        assert r.duration == 0.5
        assert r.is_llm is True

    def test_load_nonexistent_returns_none(self, cache_root):
        assert load_run("does_not_exist", cache_root=cache_root) is None

    def test_run_without_completed_at(self, cache_root):
        run = RunResult(run_id="open1", started_at="2026-01-01T00:00:00+00:00")
        save_run(run, cache_root=cache_root)
        loaded = load_run("open1", cache_root=cache_root)
        assert loaded.completed_at is None
        assert loaded.results == []


class TestListRuns:
    def test_empty_dir_returns_empty_list(self, cache_root):
        assert list_runs(cache_root=cache_root) == []

    def test_sorted_newest_first(self, cache_root):
        for ts, rid in [
            ("2026-01-01T00:00:00+00:00", "old"),
            ("2026-03-01T00:00:00+00:00", "new"),
        ]:
            save_run(RunResult(run_id=rid, started_at=ts), cache_root=cache_root)

        runs = list_runs(cache_root=cache_root)
        assert len(runs) == 2
        assert runs[0].run_id == "new"
        assert runs[1].run_id == "old"

    def test_list_runs_skips_corrupt_file(self, cache_root):
        save_run(
            RunResult(run_id="good", started_at="2026-01-01T00:00:00+00:00"),
            cache_root=cache_root,
        )
        corrupt_path = cache_root / "runs" / "corrupt.json"
        corrupt_path.write_text("not json at all {{{")

        runs = list_runs(cache_root=cache_root)
        assert len(runs) == 1
        assert runs[0].run_id == "good"

    def test_load_run_returns_none_on_corrupt(self, cache_root):
        runs_dir = cache_root / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / "badid.json").write_text("totally broken json !!!")

        assert load_run("badid", cache_root=cache_root) is None

    def test_multiple_runs_all_listed(self, cache_root):
        for i in range(5):
            save_run(
                RunResult(
                    run_id=f"run{i}", started_at=f"2026-01-0{i + 1}T00:00:00+00:00"
                ),
                cache_root=cache_root,
            )
        assert len(list_runs(cache_root=cache_root)) == 5


class TestLoadLatestRun:
    def test_returns_newest(self, cache_root):
        save_run(
            RunResult(run_id="older", started_at="2026-01-01T00:00:00+00:00"),
            cache_root=cache_root,
        )
        save_run(
            RunResult(run_id="newer", started_at="2026-02-01T00:00:00+00:00"),
            cache_root=cache_root,
        )
        latest = load_latest_run(cache_root=cache_root)
        assert latest.run_id == "newer"

    def test_no_runs_returns_none(self, cache_root):
        assert load_latest_run(cache_root=cache_root) is None


class TestNewRun:
    def test_creates_valid_run(self):
        run = new_run()
        assert len(run.run_id) == 12
        assert run.started_at is not None
        assert run.completed_at is None
        assert run.results == []

    def test_unique_ids(self):
        ids = {new_run().run_id for _ in range(20)}
        assert len(ids) == 20
