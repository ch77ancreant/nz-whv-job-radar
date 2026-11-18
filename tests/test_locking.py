"""Locks protect collection through notification handoff without stale lock deletion."""

from pathlib import Path

import pytest

from nz_job_radar.locking import ProfileBusyError, profile_lock


def test_same_profile_is_nonblocking_and_released(tmp_path: Path) -> None:
    with profile_lock(tmp_path, "live", "cafe"):
        with pytest.raises(ProfileBusyError):
            with profile_lock(tmp_path, "live", "cafe"):
                pytest.fail("overlapping run was allowed")
        with profile_lock(tmp_path, "live", "ski"):
            pass
        with profile_lock(tmp_path, "fixture", "cafe"):
            pass
    with profile_lock(tmp_path, "live", "cafe"):
        pass


def test_exception_releases_lock(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        with profile_lock(tmp_path, "fixture", "cafe"):
            raise RuntimeError("synthetic")
    with profile_lock(tmp_path, "fixture", "cafe"):
        pass
