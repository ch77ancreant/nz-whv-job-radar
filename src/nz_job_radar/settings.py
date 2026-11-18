"""Read live-only settings without exposing credentials in exceptions or repr."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import dotenv_values


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class LiveSettings:
    token: str = field(repr=False)
    max_charge_usd: Decimal
    daily_budget_usd: Decimal
    timeout_seconds: int


@dataclass(frozen=True)
class TelegramSettings:
    token: str = field(repr=False)
    chat_id: str = field(repr=False)


def _values(env_file: Path, environ: Mapping[str, str] | None) -> dict[str, str | None]:
    try:
        values = dict(dotenv_values(env_file, interpolate=False)) if env_file.is_file() else {}
    except (OSError, UnicodeError):
        raise SettingsError("無法讀取設定檔；請檢查檔案與編碼。") from None
    values.update(dict(os.environ if environ is None else environ))
    return values


def _require_source_access(values: Mapping[str, str | None]) -> None:
    if (values.get("SOURCE_ACCESS_CONFIRMED") or "").strip().lower() != "true":
        raise SettingsError(
            "live 已停用：來源資料使用許可確認後，才可設定 SOURCE_ACCESS_CONFIRMED=true。"
        )


def load_telegram_settings(
    env_file: Path, *, environ: Mapping[str, str] | None = None
) -> TelegramSettings:
    """Read credentials only for an explicitly requested live delivery, never a preview."""
    from nz_job_radar.telegram import TelegramError, normalize_chat_id, validate_token

    values = _values(env_file, environ)
    _require_source_access(values)
    try:
        token = validate_token(values.get("TELEGRAM_BOT_TOKEN") or "")
        chat_id = normalize_chat_id(values.get("TELEGRAM_CHAT_ID") or "")
    except TelegramError as error:
        raise SettingsError(str(error)) from None
    return TelegramSettings(token, chat_id)


def _amount(values: Mapping[str, str | None], key: str, default: str) -> Decimal:
    try:
        amount = Decimal(values.get(key) or default)
    except InvalidOperation:
        raise SettingsError(f"{key} 必須是正的 USD 金額。") from None
    if not amount.is_finite() or amount <= 0:
        raise SettingsError(f"{key} 必須是有限的正數。")
    return amount


def load_live_settings(env_file: Path, *, environ: Mapping[str, str] | None = None) -> LiveSettings:
    """Environment overrides .env; fixture and profile commands never call this."""
    values = _values(env_file, environ)
    _require_source_access(values)
    token = (values.get("APIFY_API_TOKEN") or "").strip()
    if not token or any(character.isspace() for character in token):
        raise SettingsError("APIFY_API_TOKEN 缺少或格式無效。")
    maximum = _amount(values, "APIFY_MAX_CHARGE_USD", "0.05")
    daily = _amount(values, "APIFY_DAILY_BUDGET_USD", "0.50")
    if maximum > daily:
        raise SettingsError("每次費用上限不能超過每日預算。")
    try:
        timeout = int(values.get("APIFY_TIMEOUT_SECONDS") or "120")
    except ValueError:
        raise SettingsError("APIFY_TIMEOUT_SECONDS 必須是整數。") from None
    if not 30 <= timeout <= 3600:
        raise SettingsError("APIFY_TIMEOUT_SECONDS 必須介於 30 與 3600。")
    return LiveSettings(token, maximum, daily, timeout)
