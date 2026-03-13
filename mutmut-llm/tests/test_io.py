"""Tests for atomic I/O helpers (_io.py)."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mutmut_llm._io import atomic_write, clean_stale_temps, file_lock


class TestAtomicWrite:
    def test_round_trip_valid_json(self, tmp_path: Path) -> None:
        target = tmp_path / "entry.json"
        payload = {"key": "value", "nested": [1, 2, 3]}
        atomic_write(target, json.dumps(payload))

        assert target.exists()
        assert json.loads(target.read_text()) == payload

    def test_no_temp_file_remains_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "entry.json"
        atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_temp_cleaned_on_replace_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.replace", side_effect=OSError("disk error")):
            with pytest.raises(OSError, match="disk error"):
                atomic_write(target, "data")

        assert not target.exists()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_original_file_untouched_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "entry.json"
        target.write_text("original")

        with patch("mutmut_llm._io.os.replace", side_effect=OSError("fail")):
            with pytest.raises(OSError):
                atomic_write(target, "replacement")

        assert target.read_text() == "original"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "entry.json"
        atomic_write(target, "first")
        atomic_write(target, "second")
        assert target.read_text() == "second"

    def test_creates_parent_via_lock(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "dir" / "entry.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, "data")
        assert target.read_text() == "data"


class TestFileLock:
    def test_lock_prevents_interleaved_writes(self, tmp_path: Path) -> None:
        target = tmp_path / "shared.json"
        results: list[str] = []
        barrier = threading.Barrier(2)

        def writer(value: str) -> None:
            barrier.wait()
            with file_lock(target):
                results.append(f"{value}-start")
                time.sleep(0.05)
                results.append(f"{value}-end")

        t1 = threading.Thread(target=writer, args=("A",))
        t2 = threading.Thread(target=writer, args=("B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Each writer's start/end must be adjacent (no interleaving)
        assert results[0].endswith("-start")
        assert results[1].endswith("-end")
        assert results[0][0] == results[1][0]
        assert results[2].endswith("-start")
        assert results[3].endswith("-end")
        assert results[2][0] == results[3][0]

    def test_lock_can_be_acquired_sequentially(self, tmp_path: Path) -> None:
        target = tmp_path / "f.json"
        with file_lock(target):
            pass
        with file_lock(target):
            pass


class TestCleanStaleTemps:
    def test_removes_old_tmp_files(self, tmp_path: Path) -> None:
        old = tmp_path / "old.tmp"
        old.write_text("stale")
        # Backdate mtime by 600 seconds
        old_time = time.time() - 600
        os.utime(old, (old_time, old_time))

        removed = clean_stale_temps(tmp_path, max_age_seconds=300)
        assert removed == 1
        assert not old.exists()

    def test_keeps_fresh_tmp_files(self, tmp_path: Path) -> None:
        fresh = tmp_path / "fresh.tmp"
        fresh.write_text("new")

        removed = clean_stale_temps(tmp_path, max_age_seconds=300)
        assert removed == 0
        assert fresh.exists()

    def test_ignores_non_tmp_files(self, tmp_path: Path) -> None:
        json_file = tmp_path / "entry.json"
        json_file.write_text("{}")
        old_time = time.time() - 600
        os.utime(json_file, (old_time, old_time))

        removed = clean_stale_temps(tmp_path, max_age_seconds=300)
        assert removed == 0
        assert json_file.exists()

    def test_handles_missing_directory(self, tmp_path: Path) -> None:
        removed = clean_stale_temps(tmp_path / "nonexistent")
        assert removed == 0

    def test_mixed_old_and_fresh(self, tmp_path: Path) -> None:
        old = tmp_path / "old.tmp"
        old.write_text("x")
        os.utime(old, (time.time() - 600, time.time() - 600))

        fresh = tmp_path / "fresh.tmp"
        fresh.write_text("y")

        removed = clean_stale_temps(tmp_path, max_age_seconds=300)
        assert removed == 1
        assert not old.exists()
        assert fresh.exists()


class TestAtomicWriteConcurrency:
    def test_concurrent_writes_produce_valid_json(self, tmp_path: Path) -> None:
        target = tmp_path / "concurrent.json"
        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def writer(n: int) -> None:
            try:
                barrier.wait()
                payload = json.dumps({"writer": n, "data": "x" * 1000})
                atomic_write(target, payload)
            except Exception as e:
                errors.append(e)

        for _ in range(10):
            threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            data = json.loads(target.read_text())
            assert "writer" in data
            assert "data" in data
