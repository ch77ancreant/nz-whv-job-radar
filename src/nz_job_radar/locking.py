"""Nonblocking per-profile process lock; released by the OS even after a crash."""

import hashlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ProfileBusyError(ValueError):
    pass


@contextmanager
def profile_lock(state_dir: Path, mode: str, profile_id: str) -> Iterator[None]:
    directory = state_dir / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{mode}:{profile_id}".encode()).hexdigest()
    # Never unlink the lock file: a concurrent opener could otherwise lock another inode.
    with (directory / f"{key}.lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ProfileBusyError("此 Profile 正在此 state 目錄執行，請等該程序結束。") from None
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
