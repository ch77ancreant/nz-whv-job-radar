"""Acceptance sends have an explicit cap validated before credentials or paid work."""

import pytest

from nz_job_radar import cli


@pytest.mark.parametrize("value", ["0", "-1", "101", "NaN", "1.5", "bad"])
@pytest.mark.parametrize("command", ["run", "resume", "deliver"])
def test_notification_limit_rejects_invalid_before_side_effects(value, command, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid limit must fail before reading configuration")

    monkeypatch.setattr(cli, "load_profiles", forbidden)
    if command == "run":
        args = ["run", "--profile", "cafe", "--live", "--notify", "--notify-limit", value]
    elif command == "resume":
        args = [
            "resume",
            "--profile",
            "cafe",
            "--live",
            "--run-id",
            "syntheticRun",
            "--notify",
            "--notify-limit",
            value,
        ]
    else:
        args = ["deliver", "--send", "--limit", value]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


def test_default_and_smoke_notification_limits():
    args = ["run", "--profile", "cafe", "--live", "--notify"]
    assert cli.parser().parse_args(args).notify_limit == 20
    assert cli.parser().parse_args(args + ["--notify-limit", "3"]).notify_limit == 3
