"""Adversarial tests for atomic cache writes implementation.

Targets edge cases, race conditions, and failure modes in _io.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from mutmut_llm._io import atomic_write, clean_stale_temps, file_lock


class TestTempFileLeak:
    """Verify temp files are cleaned in all failure modes."""

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


class TestFdLeakOnFdopenFailure:
    """Verify os.fdopen() failure closes the raw fd from mkstemp."""

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


class TestLockFileAccumulation:
    """GAP: .lock files are never cleaned up."""

    def test_lock_files_accumulate(self, tmp_path: Path) -> None:
        """Each atomic_write creates a .lock file that is never removed."""
        for i in range(5):
            target = tmp_path / f"entry_{i}.json"
            atomic_write(target, f"data_{i}")

        lock_files = list(tmp_path.glob("*.lock"))
        # This documents the behavior: lock files accumulate
        assert len(lock_files) == 5, f"Expected 5 lock files, got {len(lock_files)}"

    def test_clean_stale_temps_ignores_lock_files(self, tmp_path: Path) -> None:
        """clean_stale_temps only removes .tmp files, not .lock files."""
        target = tmp_path / "entry.json"
        atomic_write(target, "data")

        old_time = time.time() - 600
        for lock_file in tmp_path.glob("*.lock"):
            os.utime(lock_file, (old_time, old_time))

        clean_stale_temps(tmp_path, max_age_seconds=300)

        lock_files = list(tmp_path.glob("*.lock"))
        assert len(lock_files) > 0, "Lock files should persist (they are never cleaned)"


class TestNestedLockDeadlock:
    """BUG: Nested file_lock on same path deadlocks (different fd = different lock)."""

    def test_nested_lock_same_path_deadlocks(self, tmp_path: Path) -> None:
        """BUG: Nested file_lock on the same path deadlocks.

        fcntl.flock is per-open-file-description. Each file_lock call opens a
        new fd, so acquiring a second LOCK_EX on the same file from the same
        thread blocks forever.

        This test proves the deadlock exists (thread cannot complete within 2s).
        Production code must never nest file_lock on the same path.
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

        # The thread hangs — proving the deadlock
        assert not completed.is_set(), "Expected deadlock but nested lock succeeded"
        assert t.is_alive(), "Thread should still be alive (deadlocked)"


class TestDirectoryCreation:
    """Verify atomic_write works when target.parent does not exist."""

    def test_parent_dir_created_by_lock(self, tmp_path: Path) -> None:
        """file_lock creates lock_path.parent, which is target.parent.

        The existing test_creates_parent_via_lock in test_io.py manually creates
        the parent dir, defeating the purpose. This test verifies the real behavior.
        """
        target = tmp_path / "deep" / "nested" / "dir" / "entry.json"
        assert not target.parent.exists()

        atomic_write(target, "data")

        assert target.exists()
        assert target.read_text() == "data"


class TestCleanStaleTempsRace:
    """Verify clean_stale_temps doesn't race with active writers."""

    def test_fresh_temp_not_deleted(self, tmp_path: Path) -> None:
        """A just-created temp file (mtime = now) should not be cleaned."""
        temp = tmp_path / "entry.tmp"
        temp.write_text("in progress")

        removed = clean_stale_temps(tmp_path, max_age_seconds=300)
        assert removed == 0
        assert temp.exists()

    def test_concurrent_clean_and_write_race(self, tmp_path: Path) -> None:
        """clean_stale_temps with max_age=0 races with active writers.

        clean_stale_temps does not acquire the file lock before deleting .tmp files.
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

    def test_max_age_zero_deletes_all_old_temps(self, tmp_path: Path) -> None:
        """With max_age=0, even a 1-second-old temp is cleaned.

        This could race with an active writer if the writer is slow.
        """
        temp = tmp_path / "slow_writer.tmp"
        temp.write_text("partial data")
        old_time = time.time() - 1
        os.utime(temp, (old_time, old_time))

        removed = clean_stale_temps(tmp_path, max_age_seconds=0)
        assert removed == 1


class TestEdgeCases:
    """Miscellaneous edge cases."""

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

        # os.replace replaces the symlink itself with the temp file
        # so link is now a regular file, and real.json still has original content
        assert link.read_text() == "via_symlink"
        # real_file may or may not still exist depending on os.replace behavior
        # The key point: the write succeeded and produced valid content

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

    def test_clean_stale_temps_with_subdirectories(self, tmp_path: Path) -> None:
        """Subdirectories ending in .tmp should not cause errors."""
        subdir = tmp_path / "subdir.tmp"
        subdir.mkdir()

        # Should handle gracefully (glob matches dirs too, but unlink fails on dirs)
        removed = clean_stale_temps(tmp_path, max_age_seconds=0)
        # The dir won't be removed by p.unlink() — it will raise OSError
        # and be caught by the except clause
        assert subdir.exists()


class TestExistingTestGap:
    """Documents a gap in the existing test_creates_parent_via_lock test."""

    def test_existing_test_creates_parent_manually(self, tmp_path: Path) -> None:
        """The existing test in test_io.py creates parent dir before calling atomic_write.

        This means it doesn't actually test whether file_lock creates the directory.
        Our TestDirectoryCreation.test_parent_dir_created_by_lock tests the real behavior.
        """
        # This just documents the gap; see TestDirectoryCreation above for the real test.


class TestLockBehaviorDocumentation:
    """Tests that document lock behavior for correctness verification."""

    def test_lock_released_after_write(self, tmp_path: Path) -> None:
        """After atomic_write returns, the lock must be released."""
        target = tmp_path / "entry.json"
        atomic_write(target, "first")

        # If lock is still held, this would deadlock
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
