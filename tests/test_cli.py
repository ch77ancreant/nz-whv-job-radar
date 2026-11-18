"""CLI integration coverage with temporary journals and no network or secrets."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from nz_job_radar import cli
from nz_job_radar.profiles import load_profiles
from nz_job_radar.settings import load_live_settings

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
FIXTURE = ROOT / "tests" / "fixtures" / "phase1" / "seek-synthetic.json"


@pytest.fixture(autouse=True)
def offline_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every test must explicitly opt into even reading synthetic live settings."""

    def forbidden_client(*args, **kwargs):
        pytest.fail("CLI must not create an API client in these tests")

    def forbidden_settings(*args, **kwargs):
        pytest.fail("Offline CLI must not load live settings or .env")

    monkeypatch.setattr(cli, "ApifyClient", forbidden_client)
    monkeypatch.setattr(cli, "load_live_settings", forbidden_settings)
    monkeypatch.chdir(tmp_path)


def run_args(tmp_path: Path, profile: str, output: str = "json") -> list[str]:
    return [
        "run",
        "--profiles-dir",
        str(PROFILES),
        "--profile",
        profile,
        "--fixture",
        str(FIXTURE),
        "--state-dir",
        str(tmp_path / "state"),
        "--format",
        output,
    ]


@pytest.mark.parametrize("output", ["text", "json"])
def test_profiles_list_without_env_or_network(output: str, capsys) -> None:
    assert cli.main(["profiles", "--profiles-dir", str(PROFILES), "--format", output]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    if output == "json":
        rows = json.loads(captured.out)
        assert {row["id"] for row in rows} == {"auckland-cafe-service", "nz-ski-fields"}
        assert all(row["enabled"] for row in rows)
    else:
        assert "auckland-cafe-service: Auckland Cafe Service [enabled]" in captured.out
        assert "nz-ski-fields: NZ Ski Field Service [enabled]" in captured.out


@pytest.mark.parametrize(
    "profile,ids,excluded,pending",
    [
        ("auckland-cafe-service", {"990000001", "990000004"}, 6, 0),
        ("nz-ski-fields", {"990000005", "990000006"}, 5, 1),
    ],
)
def test_fixture_json_for_both_profiles(
    tmp_path: Path, capsys, profile: str, ids: set[str], excluded: int, pending: int
) -> None:
    assert cli.main(run_args(tmp_path, profile)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    summary = payload["summary"]
    assert summary["profile_id"] == profile
    assert summary["mode"] == "fixture"
    assert summary["fetched"] == 8
    assert summary["matched"] == 2
    assert summary["excluded"] == excluded
    assert summary["needs_profile_confirmation"] == pending
    assert summary["invalid"] == 0
    assert summary["dataset_complete"] is True
    assert summary["search_coverage"] == "synthetic"
    assert summary["usage_total_usd"] == "0"
    assert summary["run_id"] is None
    assert summary["dataset_id"] is None
    assert summary["whv"] == "assessed_phase_2"
    assert summary["telegram"] == "not_requested"
    assert {job["source_job_id"] for job in payload["jobs"]} == ids
    assert "excluded" not in payload
    assert "needs_profile_confirmation" not in payload
    assert (tmp_path / "state" / "runs.sqlite3").is_file()


@pytest.mark.parametrize(
    "profile,title,url",
    [
        ("auckland-cafe-service", "Front of House Assistant", "https://nz.seek.com/job/990000001"),
        ("nz-ski-fields", "Guest Services Assistant", "https://nz.seek.com/job/990000005"),
    ],
)
def test_fixture_text_for_both_profiles(
    tmp_path: Path, capsys, profile: str, title: str, url: str
) -> None:
    assert cli.main(run_args(tmp_path, profile, "text")) == 0
    output = capsys.readouterr().out
    assert f"Profile: {profile} | 模式: fixture" in output
    assert "取得 8 | 符合 2" in output
    assert title in output
    assert url in output
    assert "合成樣本，不是真實職缺" in output
    assert "WHV：已做規則式初篩" in output
    assert "Telegram：not_requested" in output
    assert "回讀毛額 USD: 0" in output
    assert "不是聘期" in output
    assert "[excluded]" not in output


def test_show_excluded_json_includes_reasons_and_unconfirmed(tmp_path: Path, capsys) -> None:
    assert cli.main(run_args(tmp_path, "nz-ski-fields") + ["--show-excluded"]) == 0
    payload = json.loads(capsys.readouterr().out)
    excluded = {row["job"]["source_job_id"]: row for row in payload["excluded"]}
    assert "employer_mismatch" in excluded["990000007"]["reasons"]
    assert len(payload["excluded"]) == 5
    assert len(payload["needs_profile_confirmation"]) == 1
    pending = payload["needs_profile_confirmation"][0]
    assert pending["job"]["source_job_id"] == "990000008"
    assert pending["reasons"] == ["employer_unknown"]


def test_show_excluded_text(tmp_path: Path, capsys) -> None:
    assert cli.main(run_args(tmp_path, "auckland-cafe-service", "text") + ["--show-excluded"]) == 0
    output = capsys.readouterr().out
    assert "[excluded] Barista: excluded_title" in output


def test_unknown_profile_fails_before_journal(tmp_path: Path, capsys) -> None:
    assert cli.main(run_args(tmp_path, "does-not-exist")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "找不到指定 Profile" in captured.err
    assert not (tmp_path / "state").exists()


def test_disabled_profile_fails_before_journal(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = load_profiles(PROFILES)
    profile_id = "auckland-cafe-service"
    profiles[profile_id] = replace(profiles[profile_id], enabled=False)
    monkeypatch.setattr(cli, "load_profiles", lambda _: profiles)
    assert cli.main(run_args(tmp_path, profile_id)) == 2
    assert "此 Profile 已停用" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("mode", [[], ["--fixture", str(FIXTURE), "--live"]])
def test_run_requires_one_explicit_mode(tmp_path: Path, capsys, mode: list[str]) -> None:
    args = [
        "run",
        "--profiles-dir",
        str(PROFILES),
        "--profile",
        "auckland-cafe-service",
        "--state-dir",
        str(tmp_path / "state"),
    ]
    with pytest.raises(SystemExit) as error:
        cli.main(args + mode)
    assert error.value.code == 2
    assert "--fixture" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_live_access_gate_prevents_client_and_journal(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_env = tmp_path / "nonexistent.env"

    def gated_settings(path: Path):
        assert path == fake_env
        # Do not inherit workstation secrets or an externally configured opt-in.
        return load_live_settings(path, environ={"SOURCE_ACCESS_CONFIRMED": "false"})

    monkeypatch.setattr(cli, "load_live_settings", gated_settings)
    args = [
        "run",
        "--profiles-dir",
        str(PROFILES),
        "--profile",
        "auckland-cafe-service",
        "--live",
        "--state-dir",
        str(tmp_path / "state"),
        "--env-file",
        str(fake_env),
    ]
    assert cli.main(args) == 2
    assert "SOURCE_ACCESS_CONFIRMED" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_fixture_ignores_even_an_explicit_env_path(tmp_path: Path, capsys) -> None:
    # Settings/client autouse sentinels make accidental access an immediate failure.
    fake_env = tmp_path / "not-to-be-read.env"
    fake_env.write_text("INVALID_SYNTHETIC_CONFIGURATION", encoding="utf-8")
    args = run_args(tmp_path, "auckland-cafe-service") + ["--env-file", str(fake_env)]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["mode"] == "fixture"


def test_runs_lists_completed_fixture_journal(tmp_path: Path, capsys) -> None:
    attempt_ids = set()
    for profile in ("auckland-cafe-service", "nz-ski-fields"):
        assert cli.main(run_args(tmp_path, profile)) == 0
        attempt_ids.add(json.loads(capsys.readouterr().out)["summary"]["attempt_id"])
    assert cli.main(["runs", "--state-dir", str(tmp_path / "state"), "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == attempt_ids
    assert {row["profile_id"] for row in rows} == {"auckland-cafe-service", "nz-ski-fields"}
    assert all(row["state"] == "COMPLETE" and row["mode"] == "fixture" for row in rows)
    assert all(row["run_id"] is None and row["dataset_id"] is None for row in rows)
    assert all(row["reserved_usd"] == "0" for row in rows)


def test_runs_empty_journal_is_not_an_error(tmp_path: Path, capsys) -> None:
    assert cli.main(["runs", "--state-dir", str(tmp_path / "state"), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_missing_fixture_is_a_safe_nonzero_error(tmp_path: Path, capsys) -> None:
    args = run_args(tmp_path, "auckland-cafe-service")
    args[args.index("--fixture") + 1] = str(tmp_path / "absent.json")
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fixture_invalid" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("wait", ["nan", "inf", "0", "3601", "abc"])
def test_invalid_wait_is_rejected_before_work(tmp_path: Path, wait: str) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(run_args(tmp_path, "auckland-cafe-service") + ["--wait-seconds", wait])
    assert error.value.code == 2
    assert not (tmp_path / "state").exists()
