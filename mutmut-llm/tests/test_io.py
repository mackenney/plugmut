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

    def test_creates_deeply_nested_parent(self, tmp_path: Path) -> None:
        """atomic_write works when target.parent does not exist at all."""
        target = tmp_path / "deep" / "nested" / "dir" / "entry.json"
        assert not target.parent.exists()

        atomic_write(target, "data")

        assert target.exists()
        assert target.read_text() == "data"

    def test_write_error_cleans_temp(self, tmp_path: Path) -> None:
        """If f.write() raises, temp file must be removed."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.fdopen") as mock_fdopen:
            mock_file = mock_fdopen.return_value
            mock_file.write.side_effect = OSError("disk full")
            mock_file.fileno.return_value = 3
            with pytest.raises(OSError, match="disk full"):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"

    def test_flush_error_cleans_temp(self, tmp_path: Path) -> None:
        """If flush() raises after successful write, temp must still be cleaned."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.fdopen") as mock_fdopen:
            mock_file = mock_fdopen.return_value
            mock_file.flush.side_effect = OSError("flush failed")
            mock_file.fileno.return_value = 3
            with pytest.raises(OSError, match="flush failed"):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"

    def test_fsync_error_cleans_temp(self, tmp_path: Path) -> None:
        """If fsync raises, temp must be cleaned."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.fsync", side_effect=OSError("fsync failed")):
            with pytest.raises(OSError, match="fsync failed"):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"

    def test_keyboard_interrupt_cleans_temp(self, tmp_path: Path) -> None:
        """BaseException (KeyboardInterrupt) must also clean temp."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.replace", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"

    def test_system_exit_cleans_temp(self, tmp_path: Path) -> None:
        """SystemExit must also clean temp."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.replace", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"

    def test_fdopen_failure_closes_fd(self, tmp_path: Path) -> None:
        """When os.fdopen raises, the raw fd must be closed and temp unlinked."""
        target = tmp_path / "entry.json"

        fds_closed: list[int] = []
        original_close = os.close

        def tracking_close(fd):
            fds_closed.append(fd)
            return original_close(fd)

        with (
            patch("mutmut_llm._io.os.fdopen", side_effect=OSError("fdopen failed")),
            patch("mutmut_llm._io.os.close", side_effect=tracking_close),
        ):
            with pytest.raises(OSError, match="fdopen failed"):
                atomic_write(target, "data")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leaked temp files: {tmp_files}"
        assert len(fds_closed) == 1, (
            f"Expected exactly one os.close call, got {fds_closed}"
        )

    def test_empty_string_write(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.json"
        atomic_write(target, "")
        assert target.read_text() == ""

    def test_large_payload(self, tmp_path: Path) -> None:
        """Verify fsync works on large payloads."""
        target = tmp_path / "large.json"
        payload = json.dumps({"data": "x" * 10_000_000})
        atomic_write(target, payload)
        assert json.loads(target.read_text())["data"] == "x" * 10_000_000

    def test_unicode_content(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.json"
        payload = json.dumps({"emoji": "\U0001f600", "cjk": "\u4e16\u754c"})
        atomic_write(target, payload)
        assert json.loads(target.read_text())["emoji"] == "\U0001f600"

    def test_special_chars_in_filename(self, tmp_path: Path) -> None:
        """Target filename with spaces and special chars."""
        target = tmp_path / "my file (1).json"
        atomic_write(target, "data")
        assert target.read_text() == "data"

    def test_rapid_overwrites(self, tmp_path: Path) -> None:
        """Rapid successive writes should all produce valid results."""
        target = tmp_path / "rapid.json"
        for i in range(100):
            atomic_write(target, json.dumps({"i": i}))
        data = json.loads(target.read_text())
        assert data["i"] == 99

    def test_symlink_target(self, tmp_path: Path) -> None:
        """Writing to a symlink: os.replace replaces the symlink, not the target."""
        real_file = tmp_path / "real.json"
        real_file.write_text("original")
        link = tmp_path / "link.json"
        link.symlink_to(real_file)

        atomic_write(link, "via_symlink")

        assert link.read_text() == "via_symlink"

    def test_read_only_directory_fails(self, tmp_path: Path) -> None:
        """Writing to a read-only directory should raise, not hang."""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        target = ro_dir / "entry.json"

        ro_dir.chmod(0o444)
        try:
            with pytest.raises((OSError, PermissionError)):
                atomic_write(target, "data")
        finally:
            ro_dir.chmod(0o755)


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

    def test_lock_files_accumulate(self, tmp_path: Path) -> None:
        """Each atomic_write creates a .lock file that is never removed."""
        for i in range(5):
            target = tmp_path / f"entry_{i}.json"
            atomic_write(target, f"data_{i}")

        lock_files = list(tmp_path.glob("*.lock"))
        assert len(lock_files) == 5, f"Expected 5 lock files, got {len(lock_files)}"

    def test_nested_lock_same_path_deadlocks(self, tmp_path: Path) -> None:
        """Nested file_lock on the same path deadlocks.

        fcntl.flock is per-open-file-description. Each file_lock call opens a
        new fd, so acquiring a second LOCK_EX on the same file from the same
        thread blocks forever.
        """
        target = tmp_path / "f.json"
        completed = threading.Event()

        def nested_lock():
            with file_lock(target):
                with file_lock(target):
                    completed.set()

        t = threading.Thread(target=nested_lock, daemon=True)
        t.start()
        t.join(timeout=2)

        assert not completed.is_set(), "Expected deadlock but nested lock succeeded"
        assert t.is_alive(), "Thread should still be alive (deadlocked)"

    def test_lock_released_after_write(self, tmp_path: Path) -> None:
        """After atomic_write returns, the lock must be released."""
        target = tmp_path / "entry.json"
        atomic_write(target, "first")

        acquired = threading.Event()

        def try_lock():
            with file_lock(target):
                acquired.set()

        t = threading.Thread(target=try_lock)
        t.start()
        t.join(timeout=2)
        assert acquired.is_set(), "Lock was not released after atomic_write"

    def test_lock_released_on_error(self, tmp_path: Path) -> None:
        """Lock must be released even when atomic_write raises."""
        target = tmp_path / "entry.json"

        with patch("mutmut_llm._io.os.replace", side_effect=OSError("fail")):
            with pytest.raises(OSError):
                atomic_write(target, "data")

        acquired = threading.Event()

        def try_lock():
            with file_lock(target):
                acquired.set()

        t = threading.Thread(target=try_lock)
        t.start()
        t.join(timeout=2)
        assert acquired.is_set(), "Lock was not released after failed atomic_write"


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

    def test_ignores_lock_files(self, tmp_path: Path) -> None:
        """clean_stale_temps only removes .tmp files, not .lock files."""
        target = tmp_path / "entry.json"
        atomic_write(target, "data")

        old_time = time.time() - 600
        for lock_file in tmp_path.glob("*.lock"):
            os.utime(lock_file, (old_time, old_time))

        clean_stale_temps(tmp_path, max_age_seconds=300)

        lock_files = list(tmp_path.glob("*.lock"))
        assert len(lock_files) > 0, "Lock files should persist (they are never cleaned)"

    def test_max_age_zero_deletes_all_old_temps(self, tmp_path: Path) -> None:
        """With max_age=0, even a 1-second-old temp is cleaned."""
        temp = tmp_path / "slow_writer.tmp"
        temp.write_text("partial data")
        old_time = time.time() - 1
        os.utime(temp, (old_time, old_time))

        removed = clean_stale_temps(tmp_path, max_age_seconds=0)
        assert removed == 1

    def test_subdirectories_ending_in_tmp(self, tmp_path: Path) -> None:
        """Subdirectories ending in .tmp should not cause errors."""
        subdir = tmp_path / "subdir.tmp"
        subdir.mkdir()

        removed = clean_stale_temps(tmp_path, max_age_seconds=0)
        assert subdir.exists()


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

    def test_concurrent_clean_and_write_race(self, tmp_path: Path) -> None:
        """clean_stale_temps with max_age=0 races with active writers.

        atomic_write retries once if its temp file disappears before os.replace,
        so the writer survives the race.
        """
        target = tmp_path / "entry.json"
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def writer():
            try:
                barrier.wait()
                for i in range(20):
                    atomic_write(target, json.dumps({"i": i}))
            except Exception as e:
                errors.append(e)

        def cleaner():
            try:
                barrier.wait()
                for _ in range(20):
                    clean_stale_temps(tmp_path, max_age_seconds=0)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=cleaner)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Unexpected errors: {errors}"
