"""Settings tests use only temporary files and explicit, synthetic environments."""

from decimal import Decimal
from pathlib import Path

import pytest

from nz_job_radar.settings import SettingsError, load_live_settings, load_telegram_settings


def valid_environment() -> dict[str, str]:
    return {
        "SOURCE_ACCESS_CONFIRMED": "true",
        "APIFY_API_TOKEN": "test-only-token-never-live",
    }


def test_defaults_and_secret_safe_representation(tmp_path: Path) -> None:
    environment = valid_environment()
    settings = load_live_settings(tmp_path / "missing.env", environ=environment)
    assert settings.token == environment["APIFY_API_TOKEN"]
    assert settings.max_charge_usd == Decimal("0.05")
    assert settings.daily_budget_usd == Decimal("0.50")
    assert settings.timeout_seconds == 120
    assert settings.token not in repr(settings)
    assert settings.token not in str(settings)


def test_process_environment_overrides_file(tmp_path: Path) -> None:
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "SOURCE_ACCESS_CONFIRMED=true\n"
        "APIFY_API_TOKEN=fixture-file-token\n"
        "APIFY_MAX_CHARGE_USD=0.02\n"
        "APIFY_DAILY_BUDGET_USD=0.25\n"
        "APIFY_TIMEOUT_SECONDS=60\n",
        encoding="utf-8",
    )
    settings = load_live_settings(
        env_file,
        environ={"APIFY_API_TOKEN": "process-token", "APIFY_MAX_CHARGE_USD": "0.04"},
    )
    assert settings.token == "process-token"
    assert settings.max_charge_usd == Decimal("0.04")
    assert settings.daily_budget_usd == Decimal("0.25")
    assert settings.timeout_seconds == 60


def test_explicit_false_environment_overrides_true_file(tmp_path: Path) -> None:
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "SOURCE_ACCESS_CONFIRMED=true\nAPIFY_API_TOKEN=fixture-file-token\n",
        encoding="utf-8",
    )
    with pytest.raises(SettingsError, match="SOURCE_ACCESS_CONFIRMED"):
        load_live_settings(env_file, environ={"SOURCE_ACCESS_CONFIRMED": "false"})


@pytest.mark.parametrize("gate", ["", "false", "0", "1", "yes", "tru", "false true"])
def test_gate_is_fail_closed(tmp_path: Path, gate: str) -> None:
    environment = valid_environment() | {"SOURCE_ACCESS_CONFIRMED": gate}
    with pytest.raises(SettingsError, match="SOURCE_ACCESS_CONFIRMED"):
        load_live_settings(tmp_path / "missing.env", environ=environment)


def test_missing_gate_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="SOURCE_ACCESS_CONFIRMED"):
        load_live_settings(tmp_path / "missing.env", environ={"APIFY_API_TOKEN": "test-token"})


def test_explicit_environment_does_not_inherit_real_process_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_ACCESS_CONFIRMED", "true")
    monkeypatch.setenv("APIFY_API_TOKEN", "synthetic-process-token")
    with pytest.raises(SettingsError, match="SOURCE_ACCESS_CONFIRMED"):
        load_live_settings(tmp_path / "missing.env", environ={})


@pytest.mark.parametrize("key", ["APIFY_MAX_CHARGE_USD", "APIFY_DAILY_BUDGET_USD"])
@pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity", "0", "-0.01", "bad"])
def test_rejects_nonpositive_or_nonfinite_amounts(tmp_path: Path, key: str, value: str) -> None:
    with pytest.raises(SettingsError, match=key):
        load_live_settings(tmp_path / "missing.env", environ=valid_environment() | {key: value})


def test_run_cap_may_not_exceed_daily_budget(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="每日預算"):
        load_live_settings(
            tmp_path / "missing.env",
            environ=valid_environment()
            | {"APIFY_MAX_CHARGE_USD": "0.06", "APIFY_DAILY_BUDGET_USD": "0.05"},
        )


@pytest.mark.parametrize("value", ["29", "3601", "1.5", "NaN", "not-an-integer"])
def test_rejects_invalid_timeout(tmp_path: Path, value: str) -> None:
    with pytest.raises(SettingsError, match="APIFY_TIMEOUT_SECONDS"):
        load_live_settings(
            tmp_path / "missing.env",
            environ=valid_environment() | {"APIFY_TIMEOUT_SECONDS": value},
        )


@pytest.mark.parametrize("token", ["", " ", "synthetic secret-token", "synthetic\ntoken"])
def test_invalid_token_never_appears_in_error(
    tmp_path: Path, token: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SettingsError) as error:
        load_live_settings(
            tmp_path / "missing.env", environ=valid_environment() | {"APIFY_API_TOKEN": token}
        )
    if token.strip():
        assert token not in str(error.value)
        assert token not in repr(error.value)
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == ""


def test_dotenv_variable_interpolation_is_disabled(tmp_path: Path) -> None:
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "SOURCE_ACCESS_CONFIRMED=true\nAPIFY_API_TOKEN=${UNRELATED_SECRET}\n",
        encoding="utf-8",
    )
    settings = load_live_settings(env_file, environ={"UNRELATED_SECRET": "must-not-expand"})
    assert settings.token == "${UNRELATED_SECRET}"


def telegram_environment() -> dict[str, str]:
    return {
        "SOURCE_ACCESS_CONFIRMED": "true",
        "TELEGRAM_BOT_TOKEN": "123456789:" + "a" * 35,
        "TELEGRAM_CHAT_ID": "-1001234567890",
    }


def test_telegram_requires_no_apify_token_and_hides_secrets(tmp_path: Path) -> None:
    environment = telegram_environment()
    settings = load_telegram_settings(tmp_path / "missing.env", environ=environment)
    assert settings.token == environment["TELEGRAM_BOT_TOKEN"]
    assert settings.chat_id == environment["TELEGRAM_CHAT_ID"]
    assert settings.token not in repr(settings)
    assert settings.chat_id not in repr(settings)


@pytest.mark.parametrize("gate", ["", "false", "yes", "1"])
def test_telegram_delivery_requires_source_permission(tmp_path: Path, gate: str) -> None:
    with pytest.raises(SettingsError, match="SOURCE_ACCESS_CONFIRMED"):
        load_telegram_settings(
            tmp_path / "missing.env",
            environ=telegram_environment() | {"SOURCE_ACCESS_CONFIRMED": gate},
        )


@pytest.mark.parametrize("chat_id", ["", "@somechannel", "0", "abc", "123 456", "9" * 100])
def test_telegram_rejects_unstable_or_invalid_destinations(tmp_path: Path, chat_id: str) -> None:
    with pytest.raises(SettingsError):
        load_telegram_settings(
            tmp_path / "missing.env", environ=telegram_environment() | {"TELEGRAM_CHAT_ID": chat_id}
        )


def test_telegram_uses_environment_precedence_without_interpolation(tmp_path: Path) -> None:
    env_file = tmp_path / "synthetic.env"
    env_file.write_text(
        "SOURCE_ACCESS_CONFIRMED=true\nTELEGRAM_BOT_TOKEN=${SECRET}\nTELEGRAM_CHAT_ID=123\n",
        encoding="utf-8",
    )
    environment = telegram_environment()
    settings = load_telegram_settings(env_file, environ=environment)
    assert settings.token == environment["TELEGRAM_BOT_TOKEN"]
    assert settings.chat_id == environment["TELEGRAM_CHAT_ID"]
    with pytest.raises(SettingsError):
        load_telegram_settings(env_file, environ={"SECRET": environment["TELEGRAM_BOT_TOKEN"]})
