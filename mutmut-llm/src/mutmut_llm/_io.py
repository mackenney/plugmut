"""Atomic file I/O and advisory locking for crash-safe cache writes."""

from __future__ import annotations

import contextlib
import fcntl
import os
import tempfile
import time
from collections.abc import Generator
from pathlib import Path


def _atomic_write(target: Path, data: str) -> None:
    """Write *data* to *target* atomically via temp-file + rename.

    Uses fsync before os.replace to survive power loss. The temp file
    lives in the same directory so os.replace is a same-filesystem
    rename (atomic on POSIX).
    """
    with _file_lock(target):
        fd, tmp_path = tempfile.mkstemp(
            dir=target.parent,
            suffix=".tmp",
            prefix=target.stem + ".",
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(target))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise


@contextlib.contextmanager
def _file_lock(path: Path) -> Generator[None, None, None]:
    """Advisory exclusive lock scoped to *path* via a sidecar .lock file."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_path, "w")  # noqa: SIM115
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def clean_stale_temps(directory: Path, max_age_seconds: int = 300) -> int:
    """Remove .tmp files in *directory* older than *max_age_seconds*.

    Returns the number of files removed. Silently skips files that
    disappear between listing and unlinking (race with other cleaners).
    """
    if not directory.exists():
        return 0

    now = time.time()
    removed = 0
    for p in directory.glob("*.tmp"):
        try:
            if now - p.stat().st_mtime > max_age_seconds:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed
