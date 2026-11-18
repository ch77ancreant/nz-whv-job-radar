"""Transactional, mode-isolated job observations and explicit Telegram outbox.

No network calls belong here. Delivery begins only after an atomic ``claim``;
uncertain delivery is never automatically retried. Raw descriptions, tokens and
Telegram destination IDs are not persisted.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from .jobs import Job, MatchDecision
from .messages import render_notification
from .pipeline import Report
from .whv import WhvAssessment


class StoreError(ValueError):
    """An invalid observation or unsafe outbox transition was rejected."""


@dataclass(frozen=True)
class Notice:
    job_id: str
    version: str
    kind: Literal["new", "update"]
    text: str
    outbox_id: str | None = None


@dataclass(frozen=True)
class NotificationPlan:
    persisted: int
    new_jobs: int
    changed_jobs: int
    queued: int
    deduplicated: int
    held: int
    messages: tuple[Notice, ...]


def canonical_chat_id(chat_id: str) -> str:
    """Accept only nonzero numeric destinations; equivalent spellings share a key."""
    if not isinstance(chat_id, str) or not re.fullmatch(r"[+-]?[0-9]{1,20}", chat_id.strip()):
        raise StoreError("Telegram destination must be a nonzero numeric chat ID.")
    value = int(chat_id.strip())
    if value == 0 or abs(value) >= 2**52:
        raise StoreError("Telegram destination must be a nonzero numeric chat ID.")
    return str(value)


def destination_key(chat_id: str) -> str:
    return hashlib.sha256(("telegram:" + canonical_chat_id(chat_id)).encode()).hexdigest()


def canonical_job_id(job: Job) -> str:
    try:
        url = urlsplit(job.source_url)
        match = re.fullmatch(r"/job/([0-9]+)/?", url.path)
        if (
            url.scheme not in {"http", "https"}
            or url.hostname not in {"nz.seek.com", "www.seek.co.nz", "seek.co.nz"}
            or url.username is not None
            or url.password is not None
            or url.port not in {None, 80, 443}
            or not match
        ):
            raise ValueError
        return match.group(1)
    except ValueError:
        raise StoreError("A job must have a canonical public SEEK NZ job URL.") from None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"br", "p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _normalized(value: str | None) -> str:
    parser = _Text()
    parser.feed(value or "")
    return " ".join(unicodedata.normalize("NFKC", "".join(parser.parts)).casefold().split())


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def important_version(job: Job, assessment: WhvAssessment) -> str:
    """Hash content and semantic rules results, not observation/formatting metadata."""
    important: dict[str, object] = {
        name: _normalized(getattr(job, name))
        for name in (
            "title",
            "employer",
            "location",
            "country",
            "employment_type",
            "salary",
            "description",
        )
    }
    important["classification"] = {
        "label": assessment.label,
        "tenure": assessment.tenure.status,
        "start_date": assessment.tenure.start_date,
        "end_date": assessment.tenure.end_date,
        "rule_version": assessment.rule_version,
        "stale": assessment.rules_stale,
    }
    return hashlib.sha256(_json(important).encode()).hexdigest()


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS job_store_meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS jobs (
        mode TEXT NOT NULL CHECK(mode IN ('fixture','live')),
        job_id TEXT NOT NULL, version TEXT NOT NULL, snapshot_json TEXT NOT NULL,
        first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        first_attempt_id TEXT NOT NULL, last_attempt_id TEXT NOT NULL,
        PRIMARY KEY(mode,job_id))""",
    """CREATE TABLE IF NOT EXISTS job_versions (
        mode TEXT NOT NULL, job_id TEXT NOT NULL, version TEXT NOT NULL,
        snapshot_json TEXT NOT NULL, assessment_json TEXT NOT NULL,
        description_hash TEXT NOT NULL, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        first_attempt_id TEXT NOT NULL, last_attempt_id TEXT NOT NULL,
        PRIMARY KEY(mode,job_id,version),
        FOREIGN KEY(mode,job_id) REFERENCES jobs(mode,job_id))""",
    """CREATE TABLE IF NOT EXISTS profile_matches (
        mode TEXT NOT NULL, job_id TEXT NOT NULL, profile_id TEXT NOT NULL,
        version TEXT NOT NULL, fingerprint TEXT NOT NULL, match_status TEXT NOT NULL,
        eligible INTEGER NOT NULL CHECK(eligible IN (0,1)), reasons_json TEXT NOT NULL,
        attempt_id TEXT NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY(mode,job_id,profile_id),
        FOREIGN KEY(mode,job_id,version) REFERENCES job_versions(mode,job_id,version))""",
    """CREATE TABLE IF NOT EXISTS outbox (
        id TEXT PRIMARY KEY, mode TEXT NOT NULL CHECK(mode='live'), job_id TEXT NOT NULL,
        version TEXT NOT NULL, destination_key TEXT NOT NULL, kind TEXT NOT NULL,
        text TEXT NOT NULL, rules_checked_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','sending','retryable','sent','failed',
            'delivery_unknown','superseded','dismissed')),
        attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        budget_generation INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL, sending_at TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        message_id INTEGER, error_code TEXT,
        UNIQUE(mode,job_id,version,destination_key),
        UNIQUE(mode,id),
        FOREIGN KEY(mode,job_id,version) REFERENCES job_versions(mode,job_id,version))""",
    """CREATE TABLE IF NOT EXISTS outbox_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT NOT NULL, outbox_id TEXT NOT NULL,
        budget_generation INTEGER NOT NULL, attempt_no INTEGER NOT NULL,
        event TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
        finished_at TEXT, message_id INTEGER, error_code TEXT,
        FOREIGN KEY(mode,outbox_id) REFERENCES outbox(mode,id))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS outbox_attempt_identity ON outbox_attempts
        (mode,outbox_id,budget_generation,attempt_no) WHERE event='send'""",
    """CREATE INDEX IF NOT EXISTS outbox_dispatch_order ON outbox
        (mode,destination_key,status,next_attempt_at,created_at)""",
    """CREATE TABLE IF NOT EXISTS destination_cooldowns (
        mode TEXT NOT NULL CHECK(mode='live'), destination_key TEXT NOT NULL,
        not_before TEXT NOT NULL, PRIMARY KEY(mode,destination_key))""",
)
_SAFE_ERRORS = frozenset(
    {
        "rate_limited",
        "http_error",
        "transport_error",
        "network_error",
        "timeout",
        "request_rejected",
        "access_denied",
        "unauthorized",
        "forbidden",
        "bad_request",
        "delivery_unknown",
        "invalid_response",
        "response_invalid",
        "connection_error",
        "retry_exhausted",
        "stale_sending",
        "notification_error",
        "telegram_rate_limited",
        "telegram_rejected",
        "telegram_transport_error",
        "telegram_timeout",
        "telegram_error",
        "telegram_delivery_unknown",
        "telegram_invalid_response",
        "telegram_http_error",
        "manual_sent",
        "manual_retry",
        "manual_skip",
        "connection_unavailable",
        "chat_migration_required",
        "interrupted_send",
    }
)


def _error_code(value: str | None) -> str | None:
    if value is None:
        return None
    if value in _SAFE_ERRORS or re.fullmatch(r"(?:telegram_)?http_[45][0-9]{2}", value):
        return value
    return "notification_error"


class JobStore:
    def __init__(self, path: Path, *, now: Callable[[], datetime] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = now or (lambda: datetime.now(UTC))
        self.connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        try:
            with self._transaction():
                for statement in _SCHEMA:
                    self.connection.execute(statement)
                self.connection.execute(
                    "INSERT OR IGNORE INTO job_store_meta(key,value) VALUES ('schema_version','1')"
                )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise StoreError("The store clock must include a timezone.")
        return value.astimezone(UTC)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    @staticmethod
    def _mode(mode: str) -> None:
        if mode not in {"fixture", "live"}:
            raise StoreError("Observation mode must be fixture or live.")

    def _eligible_profiles(self, mode: str, job_id: str, version: str) -> list[dict[str, str]]:
        rows = self.connection.execute(
            """SELECT p.profile_id,p.fingerprint FROM profile_matches p
               JOIN jobs j ON j.mode=p.mode AND j.job_id=p.job_id AND j.version=p.version
               WHERE p.mode=? AND p.job_id=? AND p.version=? AND p.eligible=1
               AND p.match_status='matched' ORDER BY p.profile_id""",
            (mode, job_id, version),
        ).fetchall()
        return [
            {"profile_id": row["profile_id"], "fingerprint": row["fingerprint"]} for row in rows
        ]

    def _blocking(self, mode: str, job_id: str, key: str) -> bool:
        return (
            self.connection.execute(
                """SELECT 1 FROM outbox WHERE mode=? AND job_id=? AND destination_key=?
               AND status IN ('sending','delivery_unknown') LIMIT 1""",
                (mode, job_id, key),
            ).fetchone()
            is not None
        )

    def _cooldown(self, mode: str, key: str) -> str | None:
        row = self.connection.execute(
            "SELECT not_before FROM destination_cooldowns WHERE mode=? AND destination_key=?",
            (mode, key),
        ).fetchone()
        return str(row["not_before"]) if row is not None else None

    def record(
        self,
        report: Report,
        *,
        profile_fingerprint: str,
        chat_id: str | None = None,
        enqueue: bool = False,
        preview: bool = False,
    ) -> NotificationPlan:
        self._mode(report.mode)
        if not profile_fingerprint or not report.profile_id or not report.attempt_id:
            raise StoreError("Profile fingerprint, profile ID and attempt ID are required.")
        if enqueue and (preview or report.mode != "live" or chat_id is None):
            raise StoreError("Enqueue requires live mode, a numeric chat ID, and no preview.")
        key = (
            "preview"
            if preview and chat_id == "preview"
            else destination_key(chat_id)
            if chat_id is not None
            else "preview"
        )
        prepared: dict[str, tuple[Job, WhvAssessment, MatchDecision, bool, str]] = {}
        candidates = [(job, MatchDecision("matched", ())) for job in report.matched]
        candidates += report.pending + report.excluded
        for job, decision in candidates:
            job_id = canonical_job_id(job)
            assessment = report.whv_assessments.get(job.source_job_id)
            if assessment is None:
                raise StoreError("Every persisted job requires its WHV assessment.")
            version = important_version(job, assessment)
            if job_id in prepared:
                if prepared[job_id][4] != version:
                    raise StoreError("One report contains conflicting versions of a SEEK job.")
                continue
            eligible = (
                decision.status == "matched" and job.source_job_id in report.notification_candidates
            )
            canonical = replace(
                job, source_job_id=job_id, source_url=f"https://nz.seek.com/job/{job_id}"
            )
            prepared[job_id] = (canonical, assessment, decision, eligible, version)
        new_jobs = changed_jobs = queued = deduplicated = held = 0
        notices: list[Notice] = []
        now = self._now().isoformat()
        with self._transaction():
            for job_id, (job, assessment, decision, eligible, version) in prepared.items():
                old = self.connection.execute(
                    "SELECT version FROM jobs WHERE mode=? AND job_id=?",
                    (report.mode, job_id),
                ).fetchone()
                new_jobs += int(old is None)
                changed_jobs += int(old is not None and old["version"] != version)
                snapshot = asdict(job)
                snapshot.pop("description")
                snapshot_json = _json(snapshot)
                self.connection.execute(
                    """INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(mode,job_id) DO UPDATE SET version=excluded.version,
                       snapshot_json=excluded.snapshot_json,last_seen_at=excluded.last_seen_at,
                       last_attempt_id=excluded.last_attempt_id""",
                    (
                        report.mode,
                        job_id,
                        version,
                        snapshot_json,
                        now,
                        now,
                        report.attempt_id,
                        report.attempt_id,
                    ),
                )
                self.connection.execute(
                    """INSERT INTO job_versions VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(mode,job_id,version) DO UPDATE SET
                       snapshot_json=excluded.snapshot_json,assessment_json=excluded.assessment_json,
                       last_seen_at=excluded.last_seen_at,last_attempt_id=excluded.last_attempt_id""",
                    (
                        report.mode,
                        job_id,
                        version,
                        snapshot_json,
                        _json(asdict(assessment)),
                        hashlib.sha256(_normalized(job.description).encode()).hexdigest(),
                        now,
                        now,
                        report.attempt_id,
                        report.attempt_id,
                    ),
                )
                self.connection.execute(
                    """INSERT INTO profile_matches VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(mode,job_id,profile_id) DO UPDATE SET
                       version=excluded.version,fingerprint=excluded.fingerprint,
                       match_status=excluded.match_status,eligible=excluded.eligible,
                       reasons_json=excluded.reasons_json,attempt_id=excluded.attempt_id,
                       observed_at=excluded.observed_at""",
                    (
                        report.mode,
                        job_id,
                        report.profile_id,
                        version,
                        profile_fingerprint,
                        decision.status,
                        int(eligible),
                        _json(decision.reasons),
                        report.attempt_id,
                        now,
                    ),
                )
                if not preview:
                    self.connection.execute(
                        """UPDATE outbox SET status='superseded',updated_at=?
                           WHERE mode=? AND job_id=? AND version<>?
                           AND status IN ('pending','retryable','failed')""",
                        (now, report.mode, job_id, version),
                    )
                if (
                    not (enqueue or preview)
                    or not eligible
                    or not self._eligible_profiles(report.mode, job_id, version)
                ):
                    continue
                if self._blocking(report.mode, job_id, key):
                    held += 1
                    continue
                existing = self.connection.execute(
                    """SELECT * FROM outbox WHERE mode=? AND job_id=? AND version=?
                       AND destination_key=?""",
                    (report.mode, job_id, version, key),
                ).fetchone()
                if existing and existing["status"] != "superseded":
                    deduplicated += 1
                    preview_text = existing["text"]
                    if existing["status"] in {"pending", "retryable"} and (
                        assessment.rules_checked_at > existing["rules_checked_at"]
                    ):
                        # A fresh rules audit is metadata, not a new notification/version.
                        # Preserve the retry budget and flood-control deadline.
                        preview_text = render_notification(
                            job, assessment, kind=existing["kind"], synthetic=False
                        )
                        if enqueue:
                            self.connection.execute(
                                """UPDATE outbox SET text=?,rules_checked_at=?,updated_at=?
                                   WHERE id=?""",
                                (preview_text, assessment.rules_checked_at, now, existing["id"]),
                            )
                    if preview and existing["status"] in {"pending", "retryable"}:
                        notices.append(
                            Notice(job_id, version, existing["kind"], preview_text, existing["id"])
                        )
                        until = max(
                            existing["next_attempt_at"], self._cooldown(report.mode, key) or ""
                        )
                        held += int(until > now)
                    continue
                sent = self.connection.execute(
                    """SELECT 1 FROM outbox WHERE mode=? AND job_id=? AND destination_key=?
                       AND status='sent' LIMIT 1""",
                    (report.mode, job_id, key),
                ).fetchone()
                kind: Literal["new", "update"] = "update" if sent else "new"
                message = render_notification(
                    job, assessment, kind=kind, synthetic=report.mode == "fixture"
                )
                outbox_id = existing["id"] if existing else uuid.uuid4().hex if enqueue else None
                if enqueue and existing:
                    self.connection.execute(
                        """UPDATE outbox SET status='pending',kind=?,text=?,rules_checked_at=?,
                           attempts=0,budget_generation=budget_generation+1,next_attempt_at=?,
                           sending_at=NULL,updated_at=?,message_id=NULL,error_code=NULL
                           WHERE id=?""",
                        (kind, message, assessment.rules_checked_at, now, now, outbox_id),
                    )
                    queued += 1
                elif enqueue:
                    self.connection.execute(
                        """INSERT INTO outbox
                           (id,mode,job_id,version,destination_key,kind,text,rules_checked_at,
                            status,next_attempt_at,created_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,'pending',?,?,?)""",
                        (
                            outbox_id,
                            report.mode,
                            job_id,
                            version,
                            key,
                            kind,
                            message,
                            assessment.rules_checked_at,
                            now,
                            now,
                            now,
                        ),
                    )
                    queued += 1
                notices.append(Notice(job_id, version, kind, message, outbox_id))
        return NotificationPlan(
            len(prepared), new_jobs, changed_jobs, queued, deduplicated, held, tuple(notices)
        )

    def _row(self, outbox_id: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM outbox WHERE id=?", (outbox_id,)).fetchone()
        if not isinstance(row, sqlite3.Row):
            raise StoreError("Notification ID was not found.")
        return row

    def _decode(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["destination_not_before"] = self._cooldown(row["mode"], row["destination_key"])
        result["eligible_profiles"] = self._eligible_profiles(
            row["mode"], row["job_id"], row["version"]
        )
        result["attempt_history"] = [
            dict(item)
            for item in self.connection.execute(
                "SELECT * FROM outbox_attempts WHERE mode=? AND outbox_id=? ORDER BY id",
                (row["mode"], row["id"]),
            ).fetchall()
        ]
        return result

    def get(self, outbox_id: str) -> dict[str, Any]:
        return self._decode(self._row(outbox_id))

    def list_outbox(
        self,
        *,
        mode: str | None = None,
        chat_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if mode is not None:
            self._mode(mode)
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise StoreError("Outbox limit must be between 1 and 10000.")
        conditions: list[str] = []
        args: list[object] = []
        if mode is not None:
            conditions.append("o.mode=?")
            args.append(mode)
        if chat_id is not None:
            conditions.append("o.destination_key=?")
            args.append(destination_key(chat_id))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self.connection.execute(
            "SELECT o.* FROM outbox o LEFT JOIN destination_cooldowns d "
            "ON d.mode=o.mode AND d.destination_key=o.destination_key"
            + where
            + """ ORDER BY
            CASE WHEN o.status IN ('pending','retryable') AND o.next_attempt_at<=?
                 AND COALESCE(d.not_before,'')<=? THEN 0
                 WHEN o.status IN ('pending','retryable') THEN 1 ELSE 2 END,
            MAX(o.next_attempt_at,COALESCE(d.not_before,'')),o.created_at,o.id LIMIT ?""",
            (*args, self._now().isoformat(), self._now().isoformat(), limit),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def claim(
        self, outbox_id: str, chat_id: str, *, max_attempts: int = 3
    ) -> dict[str, Any] | None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise StoreError("The retry budget must be between 1 and 10 attempts.")
        key = destination_key(chat_id)
        now = self._now().isoformat()
        with self._transaction():
            row = self._row(outbox_id)
            if row["mode"] != "live" or row["destination_key"] != key:
                raise StoreError("Notification mode or destination does not match the request.")
            if row["status"] not in {"pending", "retryable"} or row["next_attempt_at"] > now:
                return None
            if (self._cooldown(row["mode"], key) or "") > now:
                return None
            maximum = (
                max_attempts if row["attempts"] == 0 else min(max_attempts, row["max_attempts"])
            )
            if row["attempts"] >= maximum:
                return None
            if not self._eligible_profiles(row["mode"], row["job_id"], row["version"]):
                return None
            if self._blocking(row["mode"], row["job_id"], key):
                return None
            attempt_no = row["attempts"] + 1
            self.connection.execute(
                """UPDATE outbox SET status='sending',attempts=?,max_attempts=?,sending_at=?,
                   updated_at=?,error_code=NULL WHERE id=?""",
                (attempt_no, maximum, now, now, outbox_id),
            )
            self.connection.execute(
                """INSERT INTO outbox_attempts
                   (mode,outbox_id,budget_generation,attempt_no,event,status,started_at)
                   VALUES (?,?,?,?,'send','sending',?)""",
                (row["mode"], outbox_id, row["budget_generation"], attempt_no, now),
            )
            result = self.get(outbox_id)
        return result

    @staticmethod
    def _message_id(message_id: int | None) -> None:
        if type(message_id) is not int or message_id <= 0:
            raise StoreError("Confirmed delivery requires a positive Telegram message ID.")

    def finish(
        self,
        outbox_id: str,
        *,
        status: str,
        message_id: int | None = None,
        error_code: str | None = None,
        retry_after: int = 0,
    ) -> None:
        if status not in {"sent", "retryable", "failed", "delivery_unknown"}:
            raise StoreError("Unsupported delivery outcome.")
        if status == "sent":
            self._message_id(message_id)
        elif message_id is not None:
            raise StoreError("Only confirmed delivery can have a message ID.")
        if type(retry_after) is not int or not 0 <= retry_after <= 604800:
            raise StoreError("Retry delay must be between 0 and 604800 seconds.")
        moment = self._now()
        now = moment.isoformat()
        safe_error = _error_code(error_code)
        with self._transaction():
            row = self._row(outbox_id)
            if row["status"] != "sending":
                raise StoreError("Only a claimed notification can receive a delivery outcome.")
            if status == "retryable" and row["attempts"] >= row["max_attempts"]:
                status = "failed"
                safe_error = safe_error or "retry_exhausted"
            due = (moment + timedelta(seconds=retry_after)).isoformat()
            if safe_error in {"rate_limited", "telegram_rate_limited"} and retry_after:
                self.connection.execute(
                    """INSERT INTO destination_cooldowns VALUES (?,?,?)
                       ON CONFLICT(mode,destination_key) DO UPDATE SET
                       not_before=MAX(destination_cooldowns.not_before,excluded.not_before)""",
                    (row["mode"], row["destination_key"], due),
                )
            self.connection.execute(
                """UPDATE outbox SET status=?,message_id=?,error_code=?,next_attempt_at=?,
                   sending_at=NULL,updated_at=? WHERE id=?""",
                (status, message_id, safe_error, due, now, outbox_id),
            )
            self.connection.execute(
                """UPDATE outbox_attempts SET status=?,finished_at=?,message_id=?,error_code=?
                   WHERE mode=? AND outbox_id=? AND budget_generation=? AND attempt_no=?
                   AND event='send' AND status='sending'""",
                (
                    status,
                    now,
                    message_id,
                    safe_error,
                    row["mode"],
                    outbox_id,
                    row["budget_generation"],
                    row["attempts"],
                ),
            )

    def recover_stale_sending(self, *, older_than_seconds: int = 300) -> int:
        if type(older_than_seconds) is not int or older_than_seconds <= 0:
            raise StoreError("The abandoned-delivery timeout must be positive.")
        moment = self._now()
        now = moment.isoformat()
        cutoff = (moment - timedelta(seconds=older_than_seconds)).isoformat()
        with self._transaction():
            rows = self.connection.execute(
                "SELECT * FROM outbox WHERE status='sending' AND sending_at<?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                self.connection.execute(
                    """UPDATE outbox SET status='delivery_unknown',error_code='stale_sending',
                       sending_at=NULL,updated_at=? WHERE id=?""",
                    (now, row["id"]),
                )
                self.connection.execute(
                    """UPDATE outbox_attempts SET status='delivery_unknown',finished_at=?,
                       error_code='stale_sending' WHERE mode=? AND outbox_id=?
                       AND budget_generation=? AND attempt_no=? AND event='send'
                       AND status='sending'""",
                    (now, row["mode"], row["id"], row["budget_generation"], row["attempts"]),
                )
        return len(rows)

    def resolve(
        self,
        outbox_id: str,
        *,
        action: Literal["sent", "retry", "skip"],
        message_id: int | None = None,
    ) -> None:
        if action not in {"sent", "retry", "skip"}:
            raise StoreError("Resolution must be sent, retry, or skip.")
        if action == "sent":
            self._message_id(message_id)
        elif message_id is not None:
            raise StoreError("Only confirmed delivery can have a message ID.")
        now = self._now().isoformat()
        with self._transaction():
            row = self._row(outbox_id)
            if row["status"] not in {"failed", "delivery_unknown"}:
                raise StoreError("Resolve only failed or delivery-unknown notifications.")
            if action == "retry" and not self._eligible_profiles(
                row["mode"], row["job_id"], row["version"]
            ):
                raise StoreError(
                    "This version is no longer current and eligible; resolve it with skip or sent."
                )
            new_status = {"sent": "sent", "retry": "pending", "skip": "dismissed"}[action]
            attempts = 0 if action == "retry" else row["attempts"]
            generation = row["budget_generation"] + int(action == "retry")
            self.connection.execute(
                """UPDATE outbox SET status=?,message_id=?,error_code=?,attempts=?,
                   budget_generation=?,next_attempt_at=?,sending_at=NULL,updated_at=? WHERE id=?""",
                (
                    new_status,
                    message_id,
                    "manual_" + action,
                    attempts,
                    generation,
                    now,
                    now,
                    outbox_id,
                ),
            )
            self.connection.execute(
                """INSERT INTO outbox_attempts
                   (mode,outbox_id,budget_generation,attempt_no,event,status,started_at,
                    finished_at,message_id,error_code) VALUES (?,?,?,?,'resolution',?,?,?,?,?)""",
                (
                    row["mode"],
                    outbox_id,
                    generation,
                    attempts,
                    new_status,
                    now,
                    now,
                    message_id,
                    "manual_" + action,
                ),
            )
