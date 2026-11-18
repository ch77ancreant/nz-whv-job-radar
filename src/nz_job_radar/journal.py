"""Execution/cost journal; Phase 3 job/outbox tables are managed separately by JobStore."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from nz_job_radar.apify import RunInfo

_SUMMARY_FIELDS = frozenset(
    {
        "profile_id",
        "mode",
        "attempt_id",
        "run_id",
        "dataset_id",
        "usage_total_usd",
        "charged_item_count",
        "fetched",
        "matched",
        "excluded",
        "needs_profile_confirmation",
        "invalid",
        "duplicates",
        "reasons",
        "dataset_complete",
        "search_coverage",
        "search_limits",
        "warnings",
        "error_code",
        "whv",
        "whv_counts",
        "whv_all_counts",
        "whv_rules",
        "notification_policy",
        "telegram",
        "persistence",
        "notifications",
    }
)


class JournalError(ValueError):
    pass


@dataclass(frozen=True)
class Attempt:
    id: str
    profile_id: str
    fingerprint: str
    mode: str
    state: str
    run_id: str | None
    dataset_id: str | None
    reserved_usd: Decimal


class Journal:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                mode TEXT NOT NULL, state TEXT NOT NULL, run_id TEXT UNIQUE,
                dataset_id TEXT, api_status TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, budget_day TEXT NOT NULL, reserved_usd TEXT NOT NULL,
                usage_usd TEXT, emitted_items INTEGER, error_code TEXT, summary_json TEXT
            )"""
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _time() -> str:
        return datetime.now(UTC).isoformat()

    def reserve(
        self, profile_id: str, fingerprint: str, maximum: Decimal, daily: Decimal
    ) -> Attempt:
        """Atomic conservative budget reservation, including unknown starts."""
        now = self._time()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            busy = self.connection.execute(
                """SELECT id FROM runs WHERE profile_id=? AND mode='live'
                   AND state NOT IN ('COMPLETE','REMOTE_FAILED','START_REJECTED') LIMIT 1""",
                (profile_id,),
            ).fetchone()
            if busy:
                raise JournalError("此 Profile 有未解決的 live 執行；先用 runs 查詢並 resume。")
            rows = self.connection.execute(
                "SELECT reserved_usd, usage_usd FROM runs WHERE budget_day=? AND mode='live'",
                (now[:10],),
            ).fetchall()
            used = sum((max(Decimal(row[0]), Decimal(row[1] or "0")) for row in rows), Decimal("0"))
            if used + maximum > daily:
                raise JournalError("已達本機 UTC 日預算；沒有啟動新的付費 run。")
            attempt_id = uuid.uuid4().hex
            self.connection.execute(
                """INSERT INTO runs
                   (id,profile_id,fingerprint,mode,state,created_at,updated_at,budget_day,reserved_usd)
                   VALUES (?,?,?,'live','STARTING',?,?,?,?)""",
                (attempt_id, profile_id, fingerprint, now, now, now[:10], str(maximum)),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.get(attempt_id)

    def fixture(self, profile_id: str, fingerprint: str) -> Attempt:
        now = self._time()
        attempt_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                """INSERT INTO runs
                   (id,profile_id,fingerprint,mode,state,created_at,updated_at,budget_day,reserved_usd)
                   VALUES (?,?,?,'fixture','PROCESSING',?,?,?,'0')""",
                (attempt_id, profile_id, fingerprint, now, now, now[:10]),
            )
        return self.get(attempt_id)

    def get(self, attempt_id: str) -> Attempt:
        row = self.connection.execute("SELECT * FROM runs WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise JournalError("找不到本機執行紀錄。")
        return Attempt(
            row["id"],
            row["profile_id"],
            row["fingerprint"],
            row["mode"],
            row["state"],
            row["run_id"],
            row["dataset_id"],
            Decimal(row["reserved_usd"]),
        )

    def by_run(self, run_id: str) -> Attempt:
        row = self.connection.execute("SELECT id FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise JournalError(
                "此 run 未記錄於本機。若為啟動結果不明的紀錄，請同時提供 --attempt-id。"
            )
        return self.get(row["id"])

    def observe(self, attempt_id: str, run: RunInfo) -> None:
        with self.connection:
            # Serialize the read/compare/write with reservations and other observers.
            # A stale or corrected lower API response must not release spent budget.
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT usage_usd FROM runs WHERE id=?", (attempt_id,)
            ).fetchone()
            if previous is None:
                raise JournalError("找不到本機執行紀錄。")
            usage = run.usage_usd
            if previous["usage_usd"] is not None:
                observed = Decimal(previous["usage_usd"])
                usage = observed if usage is None else max(observed, usage)
            self.connection.execute(
                """UPDATE runs SET run_id=?, dataset_id=?, api_status=?, updated_at=?,
                   usage_usd=COALESCE(?,usage_usd), emitted_items=COALESCE(?,emitted_items)
                   WHERE id=?""",
                (
                    run.id,
                    run.dataset_id,
                    run.status,
                    self._time(),
                    str(usage) if usage is not None else None,
                    run.charged_item_count,
                    attempt_id,
                ),
            )

    def state(self, attempt_id: str, state: str, error_code: str | None = None) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET state=?,error_code=?,updated_at=? WHERE id=?",
                (state, error_code, self._time(), attempt_id),
            )

    def finish(self, attempt_id: str, summary: dict[str, Any], *, complete: bool) -> None:
        # Store operational summaries only, not job objects or raw provider payloads.
        safe_summary = {key: value for key, value in summary.items() if key in _SUMMARY_FIELDS}
        with self.connection:
            self.connection.execute(
                "UPDATE runs SET state=?,summary_json=?,error_code=?,updated_at=? WHERE id=?",
                (
                    "COMPLETE" if complete else "PARTIAL",
                    json.dumps(safe_summary, ensure_ascii=False),
                    safe_summary.get("error_code"),
                    self._time(),
                    attempt_id,
                ),
            )

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT id,profile_id,mode,state,run_id,dataset_id,api_status,
               reserved_usd,usage_usd,emitted_items,error_code,created_at,summary_json
               FROM runs ORDER BY created_at DESC LIMIT 30"""
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            raw_summary = result.pop("summary_json")
            result["summary"] = None
            if raw_summary is not None:
                try:
                    summary = json.loads(raw_summary)
                except (json.JSONDecodeError, TypeError):
                    raise JournalError("本機執行摘要損毀；請檢查 journal 資料庫。") from None
                if not isinstance(summary, dict):
                    raise JournalError("本機執行摘要格式無效；請檢查 journal 資料庫。")
                result["summary"] = {
                    key: value for key, value in summary.items() if key in _SUMMARY_FIELDS
                }
            results.append(result)
        return results
